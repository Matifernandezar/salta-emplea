"""Activación de correo: HTTP y cola aislados, sin cuenta ni proveedor real."""

import pytest

from salta_emplea import db, mailer
from salta_emplea.app import create_app


ORIGIN = 'https://empleos.pruebas.ar'
WEBHOOK = 'whsec_cHJ1ZWJhLWZpY3RpY2lhLW5vLXNlY3JldG8='


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(mailer, 'urlopen', lambda *_a, **_k: pytest.fail('No se permiten envíos reales.'))
    return create_app({
        'TESTING': True, 'SERVERLESS': False, 'DATABASE_URL': '', 'APP_ENV': 'production',
        'DATABASE_PATH': str(tmp_path / 'PRUEBA-activacion.sqlite'),
        'UPLOAD_DIR': str(tmp_path / 'PRUEBA-imagenes'),
        'SECRET_KEY': 'firma-ficticia-para-pruebas-' * 3,
        'ADMIN_PASSWORD_HASH': 'hash-ficticio-sin-autenticacion-real',
        'PUBLIC_BASE_URL': ORIGIN, 'PUBLIC_RESPONSIBLE_NAME': 'RESPONSABLE DE PRUEBA',
        'PUBLIC_CONTACT_URL': 'https://www.linkedin.com/in/perfil-de-prueba',
        'RESEND_API_KEY': 'API-FICTICIA-NO-MOSTRAR',
        'MAIL_FROM': 'PRUEBA <REMITENTE-PRIVADO@pruebas.ar>',
        'RESEND_WEBHOOK_SECRET': WEBHOOK, 'MAIL_ENABLED': '1',
    })


@pytest.fixture
def conn(app):
    connection = db.connect(app.config['DATABASE_TARGET'])
    yield connection
    connection.close()


def client_with_csrf(app, *, admin=False):
    client = app.test_client()
    with client.session_transaction(base_url=ORIGIN) as session:
        session['csrf'] = 'csrf-ficticio'
        if admin:
            session['admin'] = True
    return client


@pytest.mark.parametrize('changes', [
    {'MAIL_ENABLED': '0'}, {'MAIL_ENABLED': None},
    {'RESEND_WEBHOOK_SECRET': ''}, {'RESEND_WEBHOOK_SECRET': 'formato-incorrecto'},
    {'MAIL_DAILY_LIMIT': '0'}, {'MAIL_MONTHLY_LIMIT': '0'},
])
def test_pausa_o_configuracion_incompleta_no_ofrecen_formulario_ni_guardan_email(app, conn, changes):
    app.config.update(changes)
    client = client_with_csrf(app)
    html = client.get('/alertas', base_url=ORIGIN).get_data(as_text=True)
    assert 'pendientes de configuración' in html
    assert 'name="email"' not in html and 'name="consent"' not in html
    assert 'Crear una alerta' not in client.get('/', base_url=ORIGIN).get_data(as_text=True)
    response = client.post('/alertas', base_url=ORIGIN, data={
        'csrf_token': 'csrf-ficticio', 'email': 'persona-ficticia@example.test',
        'frequency': 'daily', 'consent': '1',
    })
    assert response.status_code == 200
    assert 'No registramos tu dirección' in response.get_data(as_text=True)
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM outbox').fetchone()[0] == 0


def test_activacion_completa_solo_prepara_confirmacion_y_pausa_conserva_pendientes(app, conn):
    client = client_with_csrf(app)
    assert 'name="email"' in client.get('/alertas', base_url=ORIGIN).get_data(as_text=True)
    assert 'Crear una alerta' in client.get('/', base_url=ORIGIN).get_data(as_text=True)
    response = client.post('/alertas', base_url=ORIGIN, data={
        'csrf_token': 'csrf-ficticio', 'email': 'persona-ficticia@example.test',
        'frequency': 'daily', 'consent': '1',
    })
    assert response.status_code == 200
    assert conn.execute('SELECT status FROM subscribers').fetchone()[0] == 'pending'
    before = [dict(row) for row in conn.execute('SELECT * FROM outbox')]
    assert len(before) == 1 and before[0]['attempts'] == 0
    app.config['MAIL_ENABLED'] = '0'
    assert mailer.send_outbox(conn, app.config)['sent'] == 0
    assert [dict(row) for row in conn.execute('SELECT * FROM outbox')] == before
    assert 'name="email"' not in client.get('/alertas', base_url=ORIGIN).get_data(as_text=True)


@pytest.mark.parametrize('path', ['/admin/configuracion', '/admin/automatizacion'])
def test_panel_explica_requisitos_sin_mostrar_secretos_ni_afirmar_verificacion(app, path):
    app.config['MAIL_ENABLED'] = '0'
    public = app.test_client().get(path, base_url=ORIGIN)
    assert public.status_code == 302 and public.location.endswith('/admin/ingresar')
    response = client_with_csrf(app, admin=True).get(path, base_url=ORIGIN)
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Preparar alertas por correo' in text
    assert 'El envío de correo está pausado' in text
    assert 'alerts.saltaemplea.com' in text
    assert 'no consulta Resend ni comprueba DNS' in text
    for secret in (app.config['RESEND_API_KEY'], app.config['MAIL_FROM'], WEBHOOK, app.config['SECRET_KEY']):
        assert secret not in text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
