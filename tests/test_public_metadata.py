"""Metadatos, publicación y textos públicos con base aislada, sin proveedores."""

from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest

from salta_emplea import db, domain, public_metadata
from salta_emplea.app import create_app


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
        'PUBLIC_RESPONSIBLE_NAME': '', 'PUBLIC_CONTACT_EMAIL': '',
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
    assert sitemap_locations(client.get('/sitemap.xml')) == ['https://empleos.example.org/']
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
    assert sitemap_locations(client.get('/sitemap.xml')) == ['https://empleos.example.org/']
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
        'https://empleos.example.org/condiciones'}


def test_invalid_contact_never_becomes_an_injected_mailto():
    for email in ('no-es-correo', 'test@example.org?subject=secreto', 'test@example.org\nBcc:otro@example.org'):
        assert not public_metadata.legal_identity({'PUBLIC_CONTACT_EMAIL': email})['email']


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
