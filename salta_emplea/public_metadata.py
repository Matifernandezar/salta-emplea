"""Metadatos públicos sin usar Host ni datos privados como origen de enlaces.

No se emite JobPosting: el modelo actual no conserva direcciones estructuradas
ni países elegibles de los remotos. Tampoco se reemplaza datePosted por la
recopilación. Requisitos consultados el 19/10/2026:
https://developers.google.com/search/docs/appearance/structured-data/job-posting
"""

import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from . import guides


SITE_NAME = 'Salta Emplea'
DEFAULT_DESCRIPTION = ('Buscá trabajo en Salta y oportunidades remotas. Filtrá por localidad, '
                       'rubro y modalidad y consultá cómo postularte en cada aviso.')
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


def public_contact_url(config):
    """Acepta solo un perfil público de LinkedIn configurado expresamente.

    No se deriva un perfil del nombre, no se consulta LinkedIn y no se conserva
    ningún parámetro que pudiera contener tokens o seguimiento. Los dominios
    Unicode o codificados no se convierten a un dominio admitido por semejanza.
    El identificador conserva sus caracteres: solo se normaliza su codificación
    UTF-8, sin transliterar ni cambiar la composición Unicode del nombre.
    """
    value = config.get('PUBLIC_CONTACT_URL') or ''
    if (not isinstance(value, str) or len(value) > 500 or
            any(c.isspace() or ord(c) < 32 for c in value) or
            any(c in value for c in ('\\', '?', '#'))):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or
                parsed.port not in (None, 443) or
                not re.fullmatch(r'(?:www\.)?linkedin\.com(?::443)?', parsed.netloc,
                                 re.I | re.ASCII)):
            return None
        path = re.fullmatch(r'/in/([^/]+)/?', parsed.path)
        if not path or re.search(r'%(?![0-9A-Fa-f]{2})', path[1]):
            return None
        # Una sola decodificación estricta impide aceptar UTF-8 inválido,
        # dobles escapes o separadores que cambien la ruta al interpretarse.
        slug = unquote(path[1], encoding='utf-8', errors='strict')
        if not 1 <= len(slug) <= 200:
            return None
        categories = [unicodedata.category(character) for character in slug]
        if (categories[0][0] != 'L' and categories[0] != 'Nd') or any(
                character != '-' and category[0] != 'L' and
                category not in ('Nd', 'Mn', 'Mc')
                for character, category in zip(slug, categories)):
            return None
        normalized = 'https://' + parsed.hostname.lower() + '/in/' + quote(slug, safe='-')
        return normalized if len(normalized) <= 500 else None
    except (ValueError, UnicodeError):
        return None


def legal_identity(config):
    name = str(config.get('PUBLIC_RESPONSIBLE_NAME') or '').strip()[:200]
    email = str(config.get('PUBLIC_CONTACT_EMAIL') or '').strip()[:254]
    if (not re.fullmatch(r'[^\s@<>"?&#]+@[^\s@<>"?&#]+\.[^\s@<>"?&#]+', email) or
            any(ord(c) < 32 for c in email)):
        email = ''
    contact_url = public_contact_url(config)
    return {'name': name, 'email': email, 'url': contact_url,
            'complete': bool(name and (email or contact_url)),
            'mailto': 'mailto:' + quote(email, safe='@.+-') if email else None}


def page_metadata(config, endpoint, *, job=None, guide=None, filtered=False, method='GET'):
    """Las páginas con tokens o acciones nunca reciben URL pública ni OG."""
    pages = {
        'index': ('Trabajo en Salta y ofertas de empleo', '/', DEFAULT_DESCRIPTION),
        'privacy': ('Privacidad', '/privacidad', 'Cómo se tratan los datos, las imágenes y las solicitudes de privacidad en Salta Emplea.'),
        'terms': ('Condiciones del servicio', '/condiciones', 'Alcance del servicio, fuentes de los avisos y condiciones de uso de Salta Emplea.'),
        'subscribe': ('Alertas por correo', '/alertas', 'Elegí tus preferencias de ofertas laborales. Suscripción voluntaria con confirmación y baja sencilla.'),
        'submit_job': ('Compartir una oferta', '/publicar', 'Aportá un aviso de trabajo para revisión. Ninguna oferta se publica sin aprobación.'),
    }
    indexable = method in ('GET', 'HEAD') and endpoint in ('index', 'job_detail', 'privacy', 'terms')
    if endpoint == 'guide_detail' and guide and guides.get_guide(guide.get('slug')):
        guide = guides.get_guide(guide['slug'])
        title, path, description = guide['title'], '/guias/' + guide['slug'], guide['summary']
        indexable = method in ('GET', 'HEAD')
    elif endpoint == 'job_detail' and job:
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
    document_title = (title + ' | ' + SITE_NAME if endpoint == 'index'
                      else title + ' · ' + SITE_NAME if title != SITE_NAME else title)
    return {'title': document_title,
            'description': description, 'canonical': canonical,
            'indexable': bool(indexable and canonical), 'site_name': SITE_NAME}


def sitemap_xml(config, jobs):
    """Recibe solo ofertas públicas; limita a 50.000 URLs por especificación."""
    if not public_origin(config):
        raise ValueError('Falta un PUBLIC_BASE_URL HTTPS válido para el sitemap.')
    root = Element('urlset', xmlns=SITEMAP_NAMESPACE)
    paths = ['/'] + ['/guias/' + guide['slug'] for guide in guides.all_guides()]
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
