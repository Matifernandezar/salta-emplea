"""Computrabajo se aporta y revisa manualmente; los destinos PRUEBA no se visitan."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest

from salta_emplea import db, domain
from salta_emplea.app import create_app


ORIGINAL = ('https://ar.computrabajo.com/ofertas-de-trabajo/'
            'oferta-de-trabajo-de-prueba-editorial')
CSRF = 'PRUEBA-csrf-aislado-computrabajo'


class Elements(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.items = []
        self.open = []
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        item = {'tag': tag, 'attrs': dict(attrs), 'text': ''}
        self.items.append(item)
        if tag not in {'input', 'img', 'meta', 'link', 'br', 'hr'}:
            self.open.append(item)

    def handle_endtag(self, tag):
        for index in range(len(self.open) - 1, -1, -1):
            if self.open[index]['tag'] == tag:
                self.open = self.open[:index]
                break

    def handle_data(self, data):
        for item in self.open:
            item['text'] += data

    def named(self, name):
        return [item['attrs'] for item in self.items
                if item['attrs'].get('name') == name]

    def with_text(self, tag, text):
        return [item for item in self.items
                if item['tag'] == tag and text in item['text']]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr('salta_emplea.app.load_env', lambda: None)

    def no_network(*_args, **_kwargs):
        raise AssertionError('Las pruebas CT no deben abrir conexiones de red.')

    monkeypatch.setattr('socket.create_connection', no_network)
    return create_app({
        'TESTING': True, 'APP_ENV': 'development', 'SERVERLESS': False,
        'SECRET_KEY': 'PRUEBA-clave-ficticia-de-interfaz-computrabajo',
        'ADMIN_PASSWORD_HASH': '', 'DATABASE_URL': '',
        'DATABASE_PATH': str(tmp_path / 'computrabajo-ui.sqlite3'),
        'UPLOAD_DIR': str(tmp_path / 'imagenes-prueba'),
        'PUBLIC_BASE_URL': 'https://example.test', 'CRON_SECRET': '',
        'RESEND_API_KEY': '', 'MAIL_FROM': '', 'MAIL_ENABLED': '0',
        'GOOGLE_VISION_API_KEY': '', 'OCR_ENABLED': '0',
    })


@pytest.fixture
def conn(app):
    connection = db.connect(app.config['DATABASE_TARGET'])
    yield connection
    connection.close()


@pytest.fixture
def admin(app):
    client = app.test_client()
    # Se aísla la autorización; el ingreso con contraseña tiene su propio circuito.
    with client.session_transaction() as session:
        session['admin'] = True
        session['csrf'] = CSRF
    return client


def offer(**changes):
    data = {
        'title': 'PRUEBA — Comercio manual de Computrabajo',
        'company': 'PRUEBA Empresa ficticia', 'location': 'Salta Capital',
        'modality': 'presencial', 'sector': 'Comercio',
        'description': 'PRUEBA: resumen breve ficticio con permiso para QA.',
        'requirements': 'PRUEBA: requisito ficticio.',
        'source_name': 'Computrabajo', 'source_url': ORIGINAL,
        'application_url': ORIGINAL,
        'original_text': 'PRUEBA: referencia editorial ficticia. No postularse.',
    }
    data.update(changes)
    return data


@pytest.mark.parametrize('path', ['/admin/fuentes', '/admin/automatizacion'])
def test_private_panels_explain_block_without_collection_endpoint(app, admin, path):
    public = app.test_client().get(path)
    assert public.status_code == 302
    assert urlsplit(public.location).path == '/admin/ingresar'

    response = admin.get(path)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    html = response.get_data(as_text=True)
    for text in ('Estado: Sin configurar', '2026-10-22',
                 'Sin corrida registrada', 'Sin programación', '600 caracteres'):
        assert text in html
    elements = Elements(response)
    buttons = elements.with_text('button', 'Recopilar Computrabajo')
    assert len(buttons) == 1
    assert buttons[0]['attrs'].get('type') == 'button'
    assert 'disabled' in buttons[0]['attrs']
    assert buttons[0]['attrs'].get('aria-describedby') == 'computrabajo-blocked'
    links = elements.with_text('a', 'Incorporar aviso de Computrabajo')
    assert len(links) == 1
    target = urlsplit(links[0]['attrs']['href'])
    assert target.path == '/admin/nueva'
    assert parse_qs(target.query) == {'source_preset': ['computrabajo-salta']}
    for item in elements.items:
        if item['tag'] == 'form':
            assert 'computrabajo' not in item['attrs'].get('action', '').lower() or (
                item['attrs']['action'] == '/admin/fuentes/preparadas/computrabajo-salta')


def test_prefill_only_identifies_the_source_and_does_not_create_offer(admin, conn):
    response = admin.get('/admin/nueva?source_preset=computrabajo-salta')
    assert response.status_code == 200
    elements = Elements(response)
    assert elements.named('source_name')[0]['value'] == 'Computrabajo'
    assert elements.named('source_url')[0]['value'] == ''
    assert elements.named('application_url')[0]['value'] == ''
    assert elements.named('title')[0]['value'] == ''
    assert not elements.named('image')
    assert not elements.named('allow_ocr')
    assert 'Aporte manual de Computrabajo' in response.get_data(as_text=True)
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0


def test_reference_registration_requires_csrf_and_remains_disabled(admin, conn):
    path = '/admin/fuentes/preparadas/computrabajo-salta'
    for data in ({}, {'csrf_token': 'PRUEBA-token-incorrecto'}):
        assert admin.post(path, data=data).status_code == 400
    assert admin.post(path, data={'csrf_token': CSRF}).status_code == 302
    source = dict(conn.execute('SELECT * FROM sources').fetchone())
    assert (source['method'], source['status'], source['authorized']) == (
        'manual', 'disabled', 0)
    response = admin.get('/admin/fuentes')
    elements = Elements(response)
    update = [item for item in elements.with_text('form', 'Guardar fuente')]
    assert len(update) == 1
    assert 'Recopilación automática no disponible' in update[0]['text']
    disabled = [attrs for attrs in elements.named('enabled') if 'disabled' in attrs]
    assert len(disabled) == 1 and 'checked' not in disabled[0]
    assert 'API pública Jobicy' in response.get_data(as_text=True)


def test_html_is_rejected_and_failed_form_escapes_the_external_input(admin, conn):
    unsafe = '<script>PRUEBA externa sin autorización para ejecutar</script>'
    response = admin.post('/admin/nueva', data={
        'csrf_token': CSRF, **offer(original_text=unsafe),
    })
    assert response.status_code == 200
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    html = response.get_data(as_text=True)
    assert unsafe not in html
    assert '&lt;script&gt;PRUEBA externa sin autorización para ejecutar&lt;/script&gt;' in html
    assert 'sin HTML ni imágenes' in html


def test_manual_offer_stays_private_and_plain_original_is_escaped(app, admin, conn):
    original_text = 'PRUEBA: resumen & evidencia > referencia externa.'
    response = admin.post('/admin/nueva', data={
        'csrf_token': CSRF, **offer(original_text=original_text),
    })
    assert response.status_code == 302
    job = dict(conn.execute('SELECT * FROM jobs').fetchone())
    assert job['status'] == 'pending'
    assert app.test_client().get(f'/ofertas/{job["id"]}').status_code == 404
    review = admin.get(response.location)
    html = review.get_data(as_text=True)
    for text in ('Aporte manual de Computrabajo', '600 caracteres',
                 'Este formulario no consulta Computrabajo', 'Aviso original',
                 'Abrir fuente original', 'Aprobar y publicar'):
        assert text in html
    assert 'PRUEBA: resumen &amp; evidencia &gt; referencia externa.' in html
    originals = Elements(review).with_text('a', 'Abrir fuente original')
    assert originals[0]['attrs']['href'] == ORIGINAL
    assert originals[0]['attrs']['rel'] == 'noopener noreferrer'


def test_approved_computrabajo_opens_canonical_original_and_other_cta_is_preserved(
        app, admin, conn):
    job_id, _ = domain.create_job(conn, offer(
        source_url=ORIGINAL + '?utm_source=PRUEBA#referencia'), actor='administrador')
    response = admin.post(f'/admin/ofertas/{job_id}/approve', data={
        'csrf_token': CSRF, 'acknowledge': '1',
    })
    assert response.status_code == 302
    public = app.test_client()
    response = public.get(f'/ofertas/{job_id}')
    assert response.status_code == 200
    links = Elements(response).with_text('a', 'Ver oferta y postularme')
    assert len(links) == 1
    assert links[0]['attrs']['href'] == ORIGINAL
    assert links[0]['attrs']['target'] == '_blank'
    assert links[0]['attrs']['rel'] == 'noopener noreferrer'

    other_id, _ = domain.create_job(conn, offer(
        title='PRUEBA — Otra fuente', source_name='PRUEBA Jobicy',
        source_url='https://example.test/avisos/otra-fuente',
        application_url='https://example.test/postularse/otra-fuente',
    ), actor='administrador')
    domain.transition_job(conn, other_id, 'approve', 'administrador', acknowledge=True)
    other = public.get(f'/ofertas/{other_id}')
    links = Elements(other).with_text('a', 'Postularme')
    assert len(links) == 1
    assert links[0]['attrs']['href'] == 'https://example.test/postularse/otra-fuente'
    assert not Elements(other).with_text('a', 'Ver oferta y postularme')


def test_forged_source_activation_is_rejected_on_the_server(admin, conn):
    response = admin.post('/admin/fuentes', data={
        'csrf_token': CSRF, 'name': 'Computrabajo',
        'url': 'https://ar.computrabajo.com/trabajo-en-salta',
        'method': 'manual', 'frequency_hours': '24', 'enabled': '1',
        'authorized': '1', 'terms_url': 'https://ar.computrabajo.com/avisolegal/',
    })
    assert response.status_code == 200
    assert 'no tiene un acceso automático verificado' in response.get_data(as_text=True)
    assert conn.execute('SELECT count(*) FROM sources').fetchone()[0] == 0


def test_image_is_rejected_before_parsing_or_persisting(admin, conn, app, monkeypatch):
    from io import BytesIO
    from pathlib import Path

    monkeypatch.setattr('salta_emplea.app.Image.open',
        lambda *_a, **_k: pytest.fail('CT no debe abrir ni almacenar imágenes.'))
    response = admin.post('/admin/nueva', data={
        'csrf_token': CSRF, **offer(), 'image': (BytesIO(b'PRUEBA'), 'PRUEBA.jpg'),
    }, content_type='multipart/form-data')
    assert response.status_code == 200
    assert 'no se almacenan imágenes de esta fuente' in response.get_data(as_text=True)
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    assert list(Path(app.config['UPLOAD_DIR']).glob('*')) == []


def test_ct_limits_are_visible_without_changing_other_sources(admin):
    limited = Elements(admin.get('/admin/nueva?source_preset=computrabajo-salta'))
    ordinary = Elements(admin.get('/admin/nueva'))
    def maxlength(elements, name):
        return next(item['attrs']['maxlength'] for item in elements.items
                    if item['tag'] == 'textarea' and item['attrs'].get('name') == name)
    assert maxlength(limited, 'description') == '600'
    assert maxlength(limited, 'requirements') == '600'
    assert maxlength(limited, 'original_text') == '2000'
    assert maxlength(ordinary, 'description') == '15000'
    assert maxlength(ordinary, 'original_text') == '30000'


@pytest.mark.parametrize('action', ['archive', 'expire'])
def test_closed_ct_offer_has_no_public_application(app, conn, action):
    job_id, _ = domain.create_job(conn, offer(), 'administrador')
    domain.transition_job(conn, job_id, 'approve', 'administrador')
    domain.transition_job(conn, job_id, action, 'administrador')
    response = app.test_client().get(f'/ofertas/{job_id}')
    assert response.status_code == 404
    assert not Elements(response).with_text('a', 'Ver oferta y postularme')


def test_legacy_unvalidated_destination_is_not_exposed_as_an_original(app, conn):
    job_id, _ = domain.create_job(conn, offer(), 'administrador')
    domain.transition_job(conn, job_id, 'approve', 'administrador')
    with conn:
        conn.execute('UPDATE jobs SET source_url=?,application_url=? WHERE id=?',
                     ('https://example.test/otro', 'https://example.test/otro', job_id))
    response = app.test_client().get(f'/ofertas/{job_id}')
    assert response.status_code == 200
    assert not Elements(response).with_text('a', 'Ver oferta y postularme')
    assert 'https://example.test/otro' not in response.get_data(as_text=True)
