"""Diagnóstico HTTP privado con resultados y credenciales ficticios; sin envíos."""

import logging

import pytest

from salta_emplea import db, mailer, tasks
from salta_emplea.app import create_app


ORIGIN = 'https://empleos.pruebas.ar'


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(mailer, 'urlopen', lambda *_a, **_k: pytest.fail('No enviar correo real.'))
    app = create_app({
        'TESTING': True, 'SERVERLESS': False, 'DATABASE_URL': '', 'APP_ENV': 'production',
        'DATABASE_PATH': str(tmp_path / 'PRUEBA-diagnostico.sqlite'),
        'UPLOAD_DIR': str(tmp_path / 'PRUEBA-imagenes'),
        'SECRET_KEY': 'FIRMA-FICTICIA-PRIVADA-' * 3, 'ADMIN_PASSWORD_HASH': 'hash-ficticio',
        'PUBLIC_BASE_URL': ORIGIN, 'PUBLIC_RESPONSIBLE_NAME': 'RESPONSABLE DE PRUEBA',
        'PUBLIC_CONTACT_URL': 'https://www.linkedin.com/in/perfil-de-prueba',
        'RESEND_API_KEY': 'API-FICTICIA-PRIVADA', 'MAIL_FROM': 'PRUEBA <remitente@pruebas.ar>',
        'RESEND_WEBHOOK_SECRET': 'whsec_cHJ1ZWJhLWZpY3RpY2lhLW5vLXNlY3JldG8=',
        'MAIL_ENABLED': '1', 'MAIL_TEST_RECIPIENT': '',
    })
    client = app.test_client()
    with client.session_transaction(base_url=ORIGIN) as session:
        session['admin'] = True
        session['csrf'] = 'csrf-ficticio'
    return app, client


def run_manual(client):
    return client.post('/admin/automatizacion/mail', base_url=ORIGIN,
                       data={'csrf_token': 'csrf-ficticio'}, follow_redirects=True).get_data(as_text=True)


@pytest.mark.parametrize(('delivery', 'expected', 'absent'), [
    ({'sent': 1, 'errors': 0}, 'El proveedor aceptó 1 correo(s). Esto no confirma su recepción.', 'El lote registró errores'),
    ({'sent': 0, 'errors': 1}, 'El lote registró errores de envío.', 'El proveedor aceptó'),
    ({'sent': 0, 'errors': 0}, 'No hubo nuevas entregas en este lote.', 'El proveedor aceptó'),
    ({'sent': 0, 'errors': 0, 'quota_reached': True}, 'Se alcanzó el cupo de correo.', 'No hubo nuevas entregas'),
])
def test_resultado_manual_distingue_aceptacion_error_ausencia_y_cupo(configured, monkeypatch, delivery, expected, absent):
    _app, client = configured
    monkeypatch.setattr(tasks, 'run_tasks', lambda *_a, **_k: {'mail': delivery})
    html = run_manual(client)
    assert expected in html
    assert absent not in html
    assert 'href="/admin#registro-envios"' in html


def test_entrega_incierta_se_muestra_sin_reactivarla(configured, monkeypatch):
    app, client = configured
    conn = db.connect(app.config['DATABASE_TARGET'])
    try:
        with conn:
            sid = conn.execute('INSERT INTO subscribers(email,frequency,status,token_hash,created_at) VALUES (?,?,?,?,?)',
                ('persona-ficticia@example.test', 'daily', 'pending', '', mailer._stamp())).lastrowid
        mailer.queue_confirmation(conn, sid, ORIGIN, app.config['SECRET_KEY'])
        with conn:
            conn.execute("UPDATE outbox SET status='uncertain',attempts=1")
        before = [dict(row) for row in conn.execute('SELECT * FROM outbox')]
        monkeypatch.setattr(tasks, 'run_tasks', lambda *_a, **_k: {'mail': {'sent': 0, 'errors': 0}})
        html = run_manual(client)
        assert 'Hay entregas inciertas registradas.' in html
        assert 'no se reenviarán automáticamente' in html
        assert 'No hubo nuevas entregas' not in html
        assert [dict(row) for row in conn.execute('SELECT * FROM outbox')] == before
    finally:
        conn.close()


def test_logs_solo_contadores_y_estados_de_correo_separados_de_avisos(configured, monkeypatch, caplog):
    app, client = configured
    private = ['persona-ficticia@example.test', 'CUERPO-PRIVADO-FICTICIO', 'ERROR-EXTERNO-FICTICIO']
    monkeypatch.setattr(tasks, 'run_tasks', lambda *_a, **_k: {
        'mail': {'sent': 0, 'errors': 1, 'recipient': private[0], 'body': private[1], 'last_error': private[2]},
        'external_detail': app.config['RESEND_API_KEY'],
    })
    with caplog.at_level(logging.INFO, logger=app.logger.name):
        html = run_manual(client)
    assert 'SALTA_TASK_MANUAL' in caplog.text and '"errors": 1' in caplog.text
    for value in private + [app.config['RESEND_API_KEY'], app.config['SECRET_KEY'], app.config['RESEND_WEBHOOK_SECRET']]:
        assert value not in caplog.text and value not in html
    rendered = app.jinja_env.from_string("{% from '_macros.html' import status_badge, mail_status_badge %}"
        "{{ status_badge('pending') }} {{ mail_status_badge('pending') }} {{ mail_status_badge('sent') }}"
        "{{ mail_status_badge('uncertain') }} {{ mail_status_badge('failed') }} {{ mail_status_badge('cancelled') }}").render()
    for label in ['Pendiente de revisión', 'En cola', 'Aceptado por el proveedor', 'Entrega incierta: revisar', 'Falló el envío', 'Cancelado']:
        assert label in rendered
    assert 'href="/admin#registro-envios"' in html
    assert 'id="registro-envios"' in client.get('/admin', base_url=ORIGIN).get_data(as_text=True)
