"""Fuentes elegidas: referencias manuales, sin acceso ni permisos implícitos.

Este catálogo no consulta a proveedores ni modifica el registro persistente. La
elección de una fuente no autoriza su extracción ni la reutilización de imágenes.
"""

from types import MappingProxyType


_PRESETS = tuple(MappingProxyType(item) for item in (
    {
        'id': 'instagram-empleosalta12',
        'name': 'Instagram @empleosalta12',
        'url': 'https://www.instagram.com/empleosalta12/',
        'method': 'manual',
        'status': 'disabled',
        'status_label': 'Manual · permisos pendientes',
        'access_explanation': (
            'La cuenta pertenece a otra persona. Podés incorporar un enlace, '
            'texto o una imagen que tengas permiso de reutilizar. Una conexión '
            'oficial requiere comprobar el tipo de cuenta, los permisos y el '
            'alcance disponible; no está conectada ni verificada.'
        ),
        'terms_url': 'https://www.facebook.com/legal/automated_data_collection_terms',
        'automation_ready': False,
        'authorized': False,
        'enabled': False,
    },
    {
        'id': 'computrabajo-salta',
        'name': 'Computrabajo · Salta',
        'url': 'https://ar.computrabajo.com/trabajo-en-salta',
        'method': 'manual',
        'status': 'disabled',
        'status_label': 'Manual · autorización pendiente',
        'access_explanation': (
            'Podés guardar el enlace original y preparar el aviso para revisión. '
            'No hay una API de búsqueda ni permiso de recopilación y '
            'redistribución verificados para este proyecto. La incorporación '
            'manual no concede permiso para copiar texto o imágenes.'
        ),
        'terms_url': 'https://ar.computrabajo.com/avisolegal/',
        'automation_ready': False,
        'authorized': False,
        'enabled': False,
    },
    {
        'id': 'linkedin',
        'name': 'LinkedIn',
        'url': 'https://www.linkedin.com/jobs/',
        'method': 'manual',
        'status': 'disabled',
        'status_label': 'Manual · autorización pendiente',
        'access_explanation': (
            'Podés incorporar el enlace original de una oferta. LinkedIn '
            'restringe la extracción automatizada; sus integraciones para '
            'publicar empleos no habilitan una búsqueda general. No hay acceso '
            'oficial de lectura conectado ni permiso de reutilización verificado.'
        ),
        'terms_url': 'https://www.linkedin.com/legal/user-agreement',
        'automation_ready': False,
        'authorized': False,
        'enabled': False,
    },
))


def source_presets() -> tuple[dict, ...]:
    """Devuelve copias para presentar opciones sin habilitar integraciones."""
    return tuple(dict(item) for item in _PRESETS)


def select_preset(key: str) -> dict:
    """Devuelve una referencia conocida; rechaza identificadores arbitrarios."""
    for item in _PRESETS:
        if item['id'] == key:
            return dict(item)
    raise ValueError('Fuente elegida desconocida.')
