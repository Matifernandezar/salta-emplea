"""Metadatos, publicación y textos públicos con base aislada, sin proveedores."""

from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest

from salta_emplea import db, domain, public_metadata
from salta_emplea.app import create_app


GUIDE_URLS = [
    'https://empleos.example.org/guias/cv-sin-experiencia',
    'https://empleos.example.org/guias/como-postularse',
    'https://empleos.example.org/guias/ofertas-laborales-falsas',
]


class Head(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.meta = {}
        self.canonicals = []
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('name') or attrs.get('property')] = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs.get('href'))


@pytest.fixture
def app(tmp_path):
    return create_app({
        'TESTING': True, 'APP_ENV': 'development', 'SERVERLESS': False,
        'SECRET_KEY': 'clave-ficticia-exclusiva-de-pruebas-publicas',
        'DATABASE_URL': '', 'DATABASE_PATH': str(tmp_path / 'publico.sqlite3'),
        'UPLOAD_DIR': str(tmp_path / 'privadas'),
        'PUBLIC_BASE_URL': 'https://empleos.example.org',
        'PUBLIC_RESPONSIBLE_NAME': '', 'PUBLIC_CONTACT_EMAIL': '', 'PUBLIC_CONTACT_URL': '',
        'RESEND_API_KEY': '', 'MAIL_FROM': '', 'OCR_ENABLED': '0',
    })


@pytest.fixture
def conn(app):
    connection = db.connect(app.config['DATABASE_PATH'])
    yield connection
    connection.close()


def create_job(conn, *, approved=False, **changes):
    data = {
        'title': 'PRUEBA — Puesto <técnico>', 'company': 'Empresa ficticia & Co.',
        'location': 'Salta Capital', 'modality': 'presencial',
        'description': 'Descripción ficticia de prueba.',
        'source_url': 'https://example.org/aviso-prueba',
        'source_name': 'Fuente ficticia',
        'application_url': 'https://example.org/postular-prueba',
        'original_text': 'Original ficticio, nunca publicar en producción.',
    }
    data.update(changes)
    job_id, _ = domain.create_job(conn, data, actor='administrador')
    if approved:
        domain.transition_job(conn, job_id, 'approve', actor='administrador')
    return job_id


def sitemap_locations(response):
    assert response.status_code == 200
    root = ElementTree.fromstring(response.data)
    return [entry.text for entry in root.findall('{*}url/{*}loc')]


@pytest.mark.parametrize('origin', [
    '', 'http://empleos.example.org', 'https://user:secret@example.org',
    'https://example.org/base', 'https://example.org?token=secreto',
    'https://example.org/#secreto', 'https://example.org:99999',
    'https://example.org:8443', 'https://example.org\\@evil.test',
    'https://example.org\nevil.test', '//example.org',
])
def test_invalid_configured_origin_is_never_a_canonical(origin):
    assert public_metadata.public_url({'PUBLIC_BASE_URL': origin}, '/') is None


def test_origin_is_normalized_and_cannot_build_private_query_links():
    config = {'PUBLIC_BASE_URL': 'https://EMPLEOS.example.org:443/'}
    assert public_metadata.public_url(config, '/ofertas/12') == 'https://empleos.example.org/ofertas/12'
    for path in ('//evil.test', '/?token=secreto', '/#secreto', '/\\evil.test', '/\nsecreto'):
        assert public_metadata.public_url(config, path) is None


def test_home_canonical_ignores_untrusted_host_and_filters_are_not_indexable(app):
    client = app.test_client()
    response = client.get('/', base_url='https://host-ajeno.example',
                          headers={'X-Forwarded-Host': 'host-ajeno.example'})
    head = Head(response)
    assert head.canonicals == ['https://empleos.example.org/']
    assert head.meta['og:url'] == head.canonicals[0]
    assert 'robots' not in head.meta
    assert 'host-ajeno' not in response.get_data(as_text=True)
    filtered = client.get('/?q=PRUEBA&location=Salta')
    assert Head(filtered).canonicals == head.canonicals
    assert Head(filtered).meta['robots'] == 'noindex, follow'
    assert filtered.headers['X-Robots-Tag'] == 'noindex, follow'
    assert 'X-Robots-Tag' not in client.head('/').headers


def test_job_metadata_uses_only_approved_public_fields_and_escapes_markup(app, conn):
    job_id = create_job(conn, approved=True)
    response = app.test_client().get(f'/ofertas/{job_id}')
    assert response.status_code == 200
    head = Head(response)
    assert head.canonicals == [f'https://empleos.example.org/ofertas/{job_id}']
    assert head.meta['og:title'] == 'PRUEBA — Puesto <técnico> · Salta Emplea'
    assert 'Empresa ficticia & Co.' in head.meta['description']
    assert 'Original ficticio' not in head.meta['description']
    assert 'application/ld+json' not in response.get_data(as_text=True)
    assert 'JobPosting' not in response.get_data(as_text=True)
    assert "script-src 'none'" in response.headers['Content-Security-Policy']


def test_sitemap_omits_pending_closed_and_materially_changed_jobs(app, conn):
    client = app.test_client()
    job_id = create_job(conn)
    assert sitemap_locations(client.get('/sitemap.xml')) == ['https://empleos.example.org/', *GUIDE_URLS]
    assert client.get(f'/ofertas/{job_id}').status_code == 404
    domain.transition_job(conn, job_id, 'approve', actor='administrador')
    location = f'https://empleos.example.org/ofertas/{job_id}'
    assert location in sitemap_locations(client.get('/sitemap.xml'))
    updated = dict(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
    updated['company'] = 'Empresa ficticia cambiada'
    domain.edit_job(conn, job_id, updated, actor='administrador')
    assert location not in sitemap_locations(client.get('/sitemap.xml'))
    hidden = client.get(f'/ofertas/{job_id}')
    assert hidden.status_code == 404 and hidden.headers['X-Robots-Tag'] == 'noindex, follow'
    assert not Head(hidden).canonicals
    domain.transition_job(conn, job_id, 'approve', actor='administrador')
    with conn:
        conn.execute("UPDATE jobs SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job_id,))
    assert location not in sitemap_locations(client.get('/sitemap.xml'))
    assert client.get(f'/ofertas/{job_id}').status_code == 404


@pytest.mark.parametrize('action', ['reject', 'archive', 'expire'])
def test_closed_job_is_removed_from_sitemap_and_detail(app, conn, action):
    job_id = create_job(conn, approved=True)
    domain.transition_job(conn, job_id, action, actor='administrador')
    client = app.test_client()
    assert sitemap_locations(client.get('/sitemap.xml')) == ['https://empleos.example.org/', *GUIDE_URLS]
    assert client.get(f'/ofertas/{job_id}').status_code == 404


def test_legal_identity_remains_pending_until_real_config_is_supplied(app):
    client = app.test_client()
    for path in ('/privacidad', '/condiciones'):
        response = client.get(path)
        assert 'Información preliminar' in response.get_data(as_text=True)
        assert 'Pendiente de informar' in response.get_data(as_text=True)
        assert Head(response).meta['robots'] == 'noindex, follow'
    privacy = client.get('/privacidad').get_data(as_text=True)
    assert 'Google Cloud Vision está en pausa' in privacy
    assert 'No hay todavía una política automática completa' in privacy
    assert all(provider in privacy for provider in ('Vercel', 'Neon', 'GitHub', 'Resend'))
    app.config.update(PUBLIC_RESPONSIBLE_NAME='Responsable ficticio <PRUEBA>',
                      PUBLIC_CONTACT_EMAIL='contacto@example.org')
    response = client.get('/privacidad')
    assert 'Información preliminar' not in response.get_data(as_text=True)
    assert 'Responsable ficticio &lt;PRUEBA&gt;' in response.get_data(as_text=True)
    assert 'mailto:contacto@example.org' in response.get_data(as_text=True)
    assert set(sitemap_locations(client.get('/sitemap.xml'))) == {
        'https://empleos.example.org/', 'https://empleos.example.org/privacidad',
        'https://empleos.example.org/condiciones', *GUIDE_URLS}


def test_invalid_contact_never_becomes_an_injected_mailto():
    for email in ('no-es-correo', 'test@example.org?subject=secreto', 'test@example.org\nBcc:otro@example.org'):
        assert not public_metadata.legal_identity({'PUBLIC_CONTACT_EMAIL': email})['email']


@pytest.mark.parametrize(('value', 'normalized'), [
    ('https://www.linkedin.com/in/perfil-ficticio-prueba', 'https://www.linkedin.com/in/perfil-ficticio-prueba'),
    ('https://linkedin.com/in/perfil-ficticio-prueba/', 'https://linkedin.com/in/perfil-ficticio-prueba'),
    ('https://WWW.LINKEDIN.COM:443/in/Perfil-Prueba-123/', 'https://www.linkedin.com/in/Perfil-Prueba-123'),
    ('https://www.linkedin.com/in/perfil-matías-prueba',
     'https://www.linkedin.com/in/perfil-mat%C3%ADas-prueba'),
    ('https://www.linkedin.com/in/perfil-mat%c3%adas-prueba/',
     'https://www.linkedin.com/in/perfil-mat%C3%ADas-prueba'),
    ('https://www.linkedin.com/in/%50erfil-%C3%91-prueba',
     'https://www.linkedin.com/in/Perfil-%C3%91-prueba'),
    ('https://www.linkedin.com/in/perfil-mati\u0301as-prueba',
     'https://www.linkedin.com/in/perfil-mati%CC%81as-prueba'),
])
def test_public_contact_accepts_only_explicit_profile_and_normalizes_safe_url(value, normalized):
    identity = public_metadata.legal_identity({
        'PUBLIC_RESPONSIBLE_NAME': 'Responsable ficticio de prueba',
        'PUBLIC_CONTACT_URL': value,
    })
    assert identity['url'] == normalized
    assert public_metadata.public_contact_url({'PUBLIC_CONTACT_URL': normalized}) == normalized
    assert identity['complete'] is True
    assert identity['email'] == '' and identity['mailto'] is None


def test_public_contact_canonical_unicode_url_respects_limit_and_is_idempotent():
    prefix = 'https://www.linkedin.com/in/'
    # Cada letra ocupa seis caracteres al codificarse como UTF-8 en la URL.
    longest_slug = 'á' * ((500 - len(prefix)) // 6)
    canonical = public_metadata.public_contact_url({'PUBLIC_CONTACT_URL': prefix + longest_slug})
    assert canonical is not None and len(canonical) <= 500
    assert public_metadata.public_contact_url({'PUBLIC_CONTACT_URL': canonical}) == canonical
    assert public_metadata.public_contact_url({
        'PUBLIC_CONTACT_URL': prefix + longest_slug + 'á',
    }) is None


@pytest.mark.parametrize('value', [
    'http://www.linkedin.com/in/prueba', '//www.linkedin.com/in/prueba',
    'javascript:alert(1)', 'https://evil.example/in/prueba',
    'https://www.linkedin.com.evil.example/in/prueba',
    'https://evil-linkedin.com/in/prueba', 'https://wwwlinkedin.com/in/prueba',
    'https://es.linkedin.com/in/prueba', 'https://www.linkedin.com./in/prueba',
    'https://www.linkedіn.com/in/prueba',  # i cirílica, no el dominio real
    'https://www.linkedİn.com/in/prueba',  # el casefold Unicode no habilita dominios
    'https://www.lınkedin.com/in/prueba',
    'https://www.linKedin.com/in/prueba',
    'https://www.linkedin。com/in/prueba', 'https://ｗｗｗ.linkedin.com/in/prueba',
    'https://xn--linkedin-9jg.com/in/prueba',
    'https://user:secret@www.linkedin.com/in/prueba',
    'https://www.linkedin.com@evil.example/in/prueba',
    'https://@www.linkedin.com/in/prueba',
    'https://www.linkedin.com:8443/in/prueba', 'https://www.linkedin.com:99999/in/prueba',
    'https://www.linkedin.com:/in/prueba', 'https://www.linkedin.com:0443/in/prueba',
    'https://www.linkedin.com/in/prueba?token=secreto-no-publicar',
    'https://www.linkedin.com/in/prueba#secreto-no-publicar',
    'https://www.linkedin.com/in/prueba?', 'https://www.linkedin.com/in/prueba#',
    'https://www.linkedin.com/in/prueba%3Ftoken%3Dsecreto-no-publicar',
    'https://www.linkedin.com/in/prueba%2Fotra-ruta',
    'https://www.linkedin.com/in/prueba%2f',
    'https://www.linkedin.com/in/prueba%5cotra-ruta',
    'https://www.linkedin.com/in/prueba%252Fotra-ruta',
    'https://www.linkedin.com/in/prueba%25C3%25AD',
    'https://www.linkedin.com/in/prueba%3Ddato',
    'https://www.linkedin.com/in/prueba%40host',
    'https://www.linkedin.com/in/prueba%0A',
    'https://www.linkedin.com/in/prueba%00',
    'https://www.linkedin.com/in/prueba%20nombre',
    'https://www.linkedin.com/in/prueba%C0%AFotra-ruta',  # UTF-8 excesivamente largo
    'https://www.linkedin.com/in/prueba%ED%A0%80',  # sustituto Unicode inválido
    'https://www.linkedin.com/in/prueba%FF',
    'https://www.linkedin.com/in/prueba%3', 'https://www.linkedin.com/in/prueba%GG',
    'https://www.linkedin.com/in/prueba%',
    'https://www.linkedin.com/in/prueba\ud800',
    'https://www.linkedin.com/in/prueba\u202Eotro',  # control de dirección
    'https://www.linkedin.com/in/prueba%E2%80%AEotro',
    'https://www.linkedin.com/in/prueba\u200Dotro',  # unión invisible
    'https://www.linkedin.com/in/\u0301prueba',
    'https://www.linkedin.com/in/' + 'á' * 201,
    'https://www.linkedin.com/%69n/prueba',
    'https://www.linkedin.com/in/prueba/otra-ruta',
    'https://www.linkedin.com/in/../prueba', 'https://www.linkedin.com/company/prueba',
    'https://www.linkedin.com/in/', 'https://www.linkedin.com/in/prueba\\@evil.example',
    'https://www.linkedin.com/in/prueba\n', 'https://www.linkedin.com/\tin/prueba',
    'https://www.linkedin.com/in/prueba" onclick="alert(1)',
])
def test_public_contact_rejects_external_confusable_or_secret_bearing_urls(value):
    identity = public_metadata.legal_identity({
        'PUBLIC_RESPONSIBLE_NAME': 'Responsable ficticio de prueba',
        'PUBLIC_CONTACT_URL': value,
    })
    assert identity['url'] is None
    assert identity['complete'] is False


def test_profile_contact_completes_legal_pages_without_personal_email_or_phone(app):
    app.config.update(PUBLIC_RESPONSIBLE_NAME='Matías Fernández',
                      PUBLIC_CONTACT_URL='https://www.linkedin.com/in/perfil-matías-prueba',
                      MAIL_FROM='Alertas <alertas@example.org>')
    client = app.test_client()
    for path in ('/privacidad', '/condiciones'):
        response = client.get(path)
        html = response.get_data(as_text=True)
        assert 'Información preliminar' not in html
        assert 'Matías Fernández' in html
        assert 'Perfil de LinkedIn del responsable' in html
        assert 'href="https://www.linkedin.com/in/perfil-mat%C3%ADas-prueba"' in html
        assert 'LinkedIn es un servicio externo' in html
        assert 'tel:' not in html and 'mailto:' not in html
        assert 'alertas@example.org' not in html
        assert 'robots' not in Head(response).meta
        assert 'X-Robots-Tag' not in response.headers
    assert 'contactá al responsable por su perfil de LinkedIn' in client.get('/privacidad').get_data(as_text=True)
    assert set(sitemap_locations(client.get('/sitemap.xml'))) == {
        'https://empleos.example.org/', 'https://empleos.example.org/privacidad',
        'https://empleos.example.org/condiciones', *GUIDE_URLS}


def test_missing_profile_is_not_invented_from_responsible_name_or_sender(app):
    app.config.update(PUBLIC_RESPONSIBLE_NAME='Matías Fernández',
                      MAIL_FROM='Alertas <alertas@example.org>')
    identity = public_metadata.legal_identity(app.config)
    assert identity['url'] is None and identity['email'] == '' and identity['complete'] is False
    client = app.test_client()
    response = client.get('/privacidad')
    assert 'Información preliminar' in response.get_data(as_text=True)
    assert 'Pendiente de informar' in response.get_data(as_text=True)
    assert Head(response).meta['robots'] == 'noindex, follow'
    assert sitemap_locations(client.get('/sitemap.xml')) == ['https://empleos.example.org/', *GUIDE_URLS]


def test_rejected_profile_never_leaks_its_query_or_changes_indexability(app):
    app.config.update(PUBLIC_RESPONSIBLE_NAME='Matías Fernández',
                      PUBLIC_CONTACT_URL='https://www.linkedin.com/in/prueba?token=secreto-no-publicar')
    client = app.test_client()
    response = client.get('/privacidad')
    html = response.get_data(as_text=True)
    assert 'secreto-no-publicar' not in html
    assert 'Perfil de LinkedIn del responsable' not in html
    assert Head(response).meta['robots'] == 'noindex, follow'
    assert sitemap_locations(client.get('/sitemap.xml')) == ['https://empleos.example.org/', *GUIDE_URLS]


def test_email_contact_api_remains_compatible_and_profile_needs_responsible_name():
    identity = public_metadata.legal_identity({
        'PUBLIC_RESPONSIBLE_NAME': 'Responsable ficticio',
        'PUBLIC_CONTACT_EMAIL': 'contacto@example.org',
        'PUBLIC_CONTACT_URL': 'https://evil.example/in/prueba',
    })
    assert identity['name'] == 'Responsable ficticio'
    assert identity['email'] == 'contacto@example.org'
    assert identity['mailto'] == 'mailto:contacto@example.org'
    assert identity['complete'] is True and identity['url'] is None
    assert public_metadata.legal_identity({
        'PUBLIC_CONTACT_URL': 'https://www.linkedin.com/in/perfil-ficticio-prueba',
    })['complete'] is False


def test_private_links_never_appear_in_sitemap_robots_or_metadata(app):
    client = app.test_client()
    robots = client.get('/robots.txt')
    assert robots.mimetype == 'text/plain'
    text = robots.get_data(as_text=True)
    assert 'Disallow: /admin' in text and 'Disallow: /alertas/' in text
    assert 'Sitemap: https://empleos.example.org/sitemap.xml' in text
    for path in ('/admin/ingresar', '/alertas/confirmar/token-privado',
                 '/alertas/baja/token-privado', '/publicar', '/alertas'):
        response = client.get(path)
        assert 'noindex' in response.headers['X-Robots-Tag']
        if '/token-privado' in path or path.startswith('/admin'):
            assert not Head(response).canonicals
            assert 'og:url' not in Head(response).meta
    assert 'token-privado' not in text
    assert '/admin' not in client.get('/sitemap.xml').get_data(as_text=True)


def test_missing_public_origin_omits_canonicals_and_refuses_fake_sitemap(app):
    app.config['PUBLIC_BASE_URL'] = ''
    client = app.test_client()
    response = client.get('/', base_url='https://untrusted.example')
    assert not Head(response).canonicals
    assert Head(response).meta['robots'] == 'noindex, follow'
    assert client.get('/sitemap.xml').status_code == 503
    assert 'Sitemap:' not in client.get('/robots.txt').get_data(as_text=True)


@pytest.mark.parametrize('slug', ['cv-sin-experiencia', 'como-postularse', 'ofertas-laborales-falsas'])
def test_guides_are_readable_canonical_and_discovered_without_job_markup(app, slug):
    client = app.test_client()
    response = client.get('/guias/' + slug)
    assert response.status_code == 200
    head = Head(response)
    expected = 'https://empleos.example.org/guias/' + slug
    assert head.canonicals == [expected]
    assert 'robots' not in head.meta
    assert 'X-Robots-Tag' not in response.headers
    html = response.get_data(as_text=True)
    assert html.count('<h1>') == 1
    assert '20/10/2026' in html
    assert 'JobPosting' not in html and 'application/ld+json' not in html
    assert expected in sitemap_locations(client.get('/sitemap.xml'))
    assert 'href="/guias/' + slug + '"' in client.get('/').get_data(as_text=True)
    assert "script-src 'none'" in response.headers['Content-Security-Policy']


def test_unknown_guide_is_not_a_fake_page_or_sitemap_entry(app):
    client = app.test_client()
    response = client.get('/guias/PRUEBA-no-existe')
    assert response.status_code == 404
    assert not Head(response).canonicals
    assert 'PRUEBA-no-existe' not in client.get('/sitemap.xml').get_data(as_text=True)


def test_home_metadata_and_paused_mail_match_the_visible_primary_action(app):
    response = app.test_client().get('/')
    html = response.get_data(as_text=True)
    head = Head(response)
    title = 'Trabajo en Salta y ofertas de empleo | Salta Emplea'
    assert '<title>' + title + '</title>' in html
    assert head.meta['og:title'] == title
    assert html.count('<h1') == 1 and 'Encontrá trabajo en Salta.' in html
    assert 'Buscar empleos' in html and 'role="search"' in html
    assert 'Las alertas están en pausa' in html
    assert 'Crear una alerta' not in html
    assert 'Avisame cuando haya oportunidades' not in html
    assert 'Sin cuenta en Salta Emplea' in html
    assert 'Portal independiente de organismos públicos' in html
