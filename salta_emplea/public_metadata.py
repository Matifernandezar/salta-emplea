"""Metadatos públicos sin usar Host ni datos privados como origen de enlaces.

No se emite JobPosting: el modelo actual no conserva direcciones estructuradas
ni países elegibles de los remotos. Tampoco se reemplaza datePosted por la
recopilación. Requisitos consultados el 19/10/2026:
https://developers.google.com/search/docs/appearance/structured-data/job-posting
"""

import re
from urllib.parse import quote, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring


SITE_NAME = 'Salta Emplea'
DEFAULT_DESCRIPTION = ('Encontrá ofertas de trabajo en Salta y oportunidades remotas '
                       'accesibles desde la provincia. Postulate por el canal original del aviso.')
SITEMAP_NAMESPACE = 'http://www.sitemaps.org/schemas/sitemap/0.9'


def public_origin(config):
    """Solo un origen HTTPS explícito y válido; nunca encabezados del cliente."""
    value = str(config.get('PUBLIC_BASE_URL') or '').strip()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.query or parsed.fragment or
                parsed.path not in ('', '/') or parsed.port not in (None, 443) or
                any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value):
            return None
        host = parsed.hostname.encode('idna').decode('ascii').lower()
        # Un dominio configurado no necesita conectividad para construir metadatos.
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host):
            return None
        return 'https://' + host
    except (ValueError, UnicodeError):
        return None


def public_url(config, path):
    origin = public_origin(config)
    if not origin or not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        return None
    if any(c in path for c in ('?', '#', '\\', '\r', '\n')):
        return None
    return origin + path


def legal_identity(config):
    name = str(config.get('PUBLIC_RESPONSIBLE_NAME') or '').strip()[:200]
    email = str(config.get('PUBLIC_CONTACT_EMAIL') or '').strip()[:254]
    if (not re.fullmatch(r'[^\s@<>"?&#]+@[^\s@<>"?&#]+\.[^\s@<>"?&#]+', email) or
            any(ord(c) < 32 for c in email)):
        email = ''
    return {'name': name, 'email': email, 'complete': bool(name and email),
            'mailto': 'mailto:' + quote(email, safe='@.+-') if email else None}


def page_metadata(config, endpoint, *, job=None, filtered=False, method='GET'):
    """Las páginas con tokens o acciones nunca reciben URL pública ni OG."""
    pages = {
        'index': ('Trabajo en Salta', '/', DEFAULT_DESCRIPTION),
        'privacy': ('Privacidad', '/privacidad', 'Cómo se tratan los datos, las imágenes y las solicitudes de privacidad en Salta Emplea.'),
        'terms': ('Condiciones del servicio', '/condiciones', 'Alcance del servicio, fuentes de los avisos y condiciones de uso de Salta Emplea.'),
        'subscribe': ('Alertas por correo', '/alertas', 'Elegí tus preferencias de ofertas laborales. Suscripción voluntaria con confirmación y baja sencilla.'),
        'submit_job': ('Compartir una oferta', '/publicar', 'Aportá un aviso de trabajo para revisión. Ninguna oferta se publica sin aprobación.'),
    }
    indexable = method in ('GET', 'HEAD') and endpoint in ('index', 'job_detail', 'privacy', 'terms')
    if endpoint == 'job_detail' and job:
        title = ' '.join(str(job['title']).split())
        details = [job.get('company'), job.get('location'), job.get('modality')]
        description = ' · '.join(str(v) for v in details if v)
        description = ((title + '. ' + description).strip('. ') + '. Consultá los detalles y postulate por el canal original.')[:300]
        path = '/ofertas/' + str(int(job['id']))
    elif endpoint in pages:
        title, path, description = pages[endpoint]
    else:
        title, path, description = SITE_NAME, None, DEFAULT_DESCRIPTION
        indexable = False
    if endpoint in ('privacy', 'terms') and not legal_identity(config)['complete']:
        indexable = False
    if filtered:
        indexable = False
    canonical = public_url(config, path) if path else None
    return {'title': title + ' · ' + SITE_NAME if title != SITE_NAME else title,
            'description': description, 'canonical': canonical,
            'indexable': bool(indexable and canonical), 'site_name': SITE_NAME}


def sitemap_xml(config, jobs):
    """Recibe solo ofertas públicas; limita a 50.000 URLs por especificación."""
    if not public_origin(config):
        raise ValueError('Falta un PUBLIC_BASE_URL HTTPS válido para el sitemap.')
    root = Element('urlset', xmlns=SITEMAP_NAMESPACE)
    paths = ['/']
    if legal_identity(config)['complete']:
        paths += ['/privacidad', '/condiciones']
    paths += ['/ofertas/' + str(int(job['id'])) for job in jobs]
    if len(paths) > 50_000:
        raise ValueError('El sitemap requiere paginación antes de superar 50.000 URLs.')
    for path in paths:
        entry = SubElement(root, 'url')
        SubElement(entry, 'loc').text = public_url(config, path)
    # Se omite lastmod antes que presentar comprobaciones como cambios editoriales.
    return tostring(root, encoding='utf-8', xml_declaration=True)
