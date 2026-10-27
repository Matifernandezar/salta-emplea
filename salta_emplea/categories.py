"""Catálogo único de categorías; compatibilidad con rubros anteriores."""
import unicodedata

CATEGORIES = (
    'Administración / Oficina',
    'Almacén / Logística / Transporte',
    'Atención a clientes',
    'CallCenter / Telemercadeo',
    'Compras / Comercio Exterior',
    'Construcción y obra',
    'Contabilidad / Finanzas',
    'Dirección / Gerencia',
    'Diseño / Artes gráficas',
    'Docencia',
    'Hostelería / Turismo',
    'Informática / Telecomunicaciones',
    'Ingeniería',
    'Investigación y Calidad',
    'Legal / Asesoría',
    'Mantenimiento y Reparaciones Técnicas',
    'Medicina / Salud',
    'Mercadotecnia / Publicidad / Comunicación',
    'Otros',
    'Producción / Operarios / Manufactura',
    'Recursos Humanos',
    'Servicios Generales, Aseo y Seguridad',
    'Ventas',
)


def fold(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(value or ''))
                           if not unicodedata.combining(c)).casefold().split())


_KNOWN = {fold(value): value for value in CATEGORIES}
_ALIASES = {
    'Administración': CATEGORIES[0], 'Oficina': CATEGORIES[0],
    'Logística': CATEGORIES[1], 'Transporte': CATEGORIES[1], 'Almacén': CATEGORIES[1],
    'Atención al cliente': CATEGORIES[2], 'Atención al público': CATEGORIES[2],
    'Call center': CATEGORIES[3], 'Telemarketing': CATEGORIES[3],
    'Compras': CATEGORIES[4], 'Comercio exterior': CATEGORIES[4],
    'Construcción': CATEGORIES[5], 'Contabilidad': CATEGORIES[6], 'Finanzas': CATEGORIES[6],
    'Gerencia': CATEGORIES[7], 'Diseño': CATEGORIES[8], 'Educación': CATEGORIES[9],
    'Hotelería': CATEGORIES[10], 'Turismo': CATEGORIES[10], 'Gastronomía': CATEGORIES[10],
    'Hotelería y gastronomía': CATEGORIES[10],
    'Tecnología': CATEGORIES[11], 'Informática': CATEGORIES[11],
    'IT': CATEGORIES[11], 'Telecomunicaciones': CATEGORIES[11],
    'Calidad': CATEGORIES[13], 'Legal': CATEGORIES[14],
    'Mantenimiento': CATEGORIES[15], 'Salud': CATEGORIES[16],
    'Marketing': CATEGORIES[17], 'Publicidad': CATEGORIES[17], 'Comunicación': CATEGORIES[17],
    'Otro': 'Otros', 'Producción': CATEGORIES[19], 'Industria': CATEGORIES[19],
    'RRHH': CATEGORIES[20], 'Seguridad': CATEGORIES[21], 'Limpieza': CATEGORIES[21],
    'Comercio': 'Ventas', 'Comercial': 'Ventas',
}
_KNOWN.update({fold(key): value for key, value in _ALIASES.items()})


def known(value):
    """Un alias conocido; los valores de búsqueda desconocidos no significan Otros."""
    return _KNOWN.get(fold(value))


def normalize(value):
    """No borra ofertas: rubros anteriores sin equivalencia se muestran en Otros."""
    if not str(value or '').strip():
        return None
    return known(value) or 'Otros'
