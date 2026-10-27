"""Navegación pública construida únicamente con ofertas ya publicables.

No clasifica ocupaciones ni deduce experiencia o residencia. Los enlaces son
filtros de la portada existente, no nuevas categorías indexables.
"""

from . import categories
from collections import Counter
import unicodedata
from urllib.parse import urlencode


FILTER_KEYS = ('q', 'location', 'sector', 'modality', 'schedule', 'days')
_FILTER_LABELS = {
    'q': 'Búsqueda', 'location': 'Ubicación', 'sector': 'Categoría',
    'modality': 'Modalidad', 'schedule': 'Jornada',
}
_PART_TIME_SCHEDULES = {
    'media jornada', 'medio tiempo', 'jornada parcial', 'part time', 'part-time',
}
_MODALITIES = {'presencial': 'presencial', 'hibrida': 'híbrida', 'remota': 'remota'}


def _fold(value):
    return ''.join(character for character in unicodedata.normalize('NFKD', value)
                   if not unicodedata.combining(character)).casefold()


def search_filters(arguments):
    """Conserva filtros conocidos y el alias de fecha previo, sin tracking."""
    result = {}
    for key in FILTER_KEYS:
        value = arguments.get(key)
        if key == 'days' and not value:
            value = arguments.get('date_days')
        if value is not None and str(value).strip():
            value = str(value).strip()
            if key == 'sector':
                value = categories.known(value) or value
            elif key == 'modality':
                value = _MODALITIES.get(_fold(value), value)
            elif key == 'days':
                try:
                    days = int(value)
                except ValueError:
                    pass
                else:
                    # Lo inválido se conserva para que public_jobs produzca
                    # el error habitual, sin corregir silenciosamente límites.
                    if 1 <= days <= 3650:
                        value = str(days)
            result[key] = value
    return result


def _selection_url(index_url, filters, **updates):
    selected = {key: value for key, value in filters.items() if key in FILTER_KEYS}
    for key, value in updates.items():
        if value is None:
            selected.pop(key, None)
        elif key in FILTER_KEYS:
            selected[key] = value
    selected = search_filters(selected)
    # public_jobs ya valida el formulario; este límite adicional evita que
    # futuros consumidores internos generen chips con datos sin acotar.
    if any(len(value) > 200 for value in selected.values()):
        raise ValueError('El filtro excede el máximo de 200 caracteres.')
    query = urlencode([(key, selected[key]) for key in FILTER_KEYS if selected.get(key)])
    return index_url + ('?' + query if query else '') + '#ofertas'


def facets(jobs, filters):
    """Localidades y jornadas del inventario; categorías del catálogo cerrado."""
    result = {}
    for name, field in (('locations', 'location'), ('schedules', 'schedule')):
        options = {job[field] for job in jobs if job.get(field) and
                   (field != 'location' or job.get('modality') != 'remota')}
        # Si cambió el inventario o se ingresó una variante con/sin tilde, el
        # formulario sigue mostrando el valor que produjo esta búsqueda.
        if filters.get(field):
            options.add(filters[field])
        result[name] = sorted(options, key=lambda value: (_fold(value), value))
    result['sectors'] = list(categories.CATEGORIES)
    return result


def _links(index_url, jobs, field, *, physical_only=False):
    if field == 'sector':
        jobs = [dict(job, sector=categories.normalize(job.get('sector'))) for job in jobs]
    counts = Counter(job[field] for job in jobs if job.get(field) and
                     (not physical_only or job.get('modality') != 'remota'))
    return [
        {'label': value, 'count': count,
         'url': _selection_url(index_url, {}, **{field: value})}
        for value, count in sorted(counts.items(), key=lambda pair: (_fold(pair[0]), pair[0]))
    ]


def presentation(jobs, filtered_jobs, filters, *, index_url='/'):
    """Recibe las filas de public_jobs: no consulta ni altera la base."""
    active = []
    for key in FILTER_KEYS:
        value = filters.get(key)
        if not value:
            continue
        if key == 'days':
            label = ('Incorporación: últimas 24 horas' if value == '1'
                     else f'Incorporación: últimos {value} días')
        else:
            label = f'{_FILTER_LABELS[key]}: {value}'
        active.append({'label': label,
                       'url': _selection_url(index_url, filters, **{key: None})})

    shortcuts = []
    schedules = Counter(job['schedule'] for job in jobs if job.get('schedule') and
                        _fold(job['schedule']) in _PART_TIME_SCHEDULES)
    if schedules:
        schedule, count = sorted(schedules.items(),
                                 key=lambda pair: (-pair[1], _fold(pair[0])))[0]
        shortcuts.append({'label': 'Medio tiempo', 'count': count,
                          'url': _selection_url(index_url, {}, schedule=schedule)})
    # El modelo no conserva una validación estructurada de experiencia ni de
    # residencia remota. Una palabra en la descripción o una aprobación con
    # alertas reconocidas no prueba esos requisitos: no inventar esos atajos.
    return {
        'is_filtered': bool(active), 'active_filters': active,
        'sector_links': _links(index_url, jobs, 'sector'),
        'location_links': _links(index_url, jobs, 'location', physical_only=True),
        'shortcuts': shortcuts, 'total_published': len(jobs),
        'filtered_count': len(filtered_jobs),
    }
