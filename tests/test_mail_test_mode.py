"""Prueba limitada: proveedor sustituido y destinatarios ficticios aislados."""

import json

import pytest

from salta_emplea import db, domain, mailer, tasks
from salta_emplea.app import create_app


ORIGIN = 'https://empleos.pruebas.ar'
AUTHORIZED = 'prueba-autorizada@example.test'
OTHER = 'tercera-persona@example.test'
WEBHOOK = 'whsec_cHJ1ZWJhLWZpY3RpY2lhLW5vLXNlY3JldG8='


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(mailer, 'urlopen', lambda *_a, **_k: pytest.fail('No enviar correo real.'))
    return create_app({
        'TESTING': True, 'SERVERLESS': False, 'DATABASE_URL': '', 'APP_ENV': 'production',
        'DATABASE_PATH': str(tmp_path / 'PRUEBA-modo-correo.sqlite'),
        'UPLOAD_DIR': str(tmp_path / 'PRUEBA-imagenes'),
        'SECRET_KEY': 'firma-ficticia-aislada-' * 3,
        'ADMIN_PASSWORD_HASH': 'hash-ficticio',
        'PUBLIC_BASE_URL': ORIGIN, 'PUBLIC_RESPONSIBLE_NAME': 'RESPONSABLE DE PRUEBA',
        'PUBLIC_CONTACT_URL': 'https://www.linkedin.com/in/perfil-de-prueba',
        'RESEND_API_KEY': 'API-FICTICIA', 'MAIL_FROM': 'PRUEBA <avisos@pruebas.ar>',
        'RESEND_WEBHOOK_SECRET': WEBHOOK, 'MAIL_ENABLED': '1',
        'MAIL_TEST_RECIPIENT': AUTHORIZED,
    })


@pytest.fixture
def conn(app):
    connection = db.connect(app.config['DATABASE_TARGET'])
    yield connection
    connection.close()


def add_subscriber(conn, email, status='pending'):
    with conn:
        return conn.execute(
            'INSERT INTO subscribers(email,frequency,status,token_hash,created_at) VALUES (?,?,?,?,?)',
            (email, 'daily', status, '', mailer._stamp()),
        ).lastrowid


def confirmation(conn, app, email):
    sid = add_subscriber(conn, email)
    mailer.queue_confirmation(conn, sid, ORIGIN, app.config['SECRET_KEY'])
    return sid


def approve_test_job(conn):
    job_id, _ = domain.create_job(conn, {
        'title': 'PRUEBA: administrativo', 'company': 'EMPRESA FICTICIA',
        'location': 'Salta Capital', 'sector': 'Administración', 'modality': 'presencial',
        'application_url': 'mailto:rrhh@example.test',
    })
    domain.transition_job(conn, job_id, 'approve', 'administrador de prueba', acknowledge=True)


def rows(conn, table):
    return [dict(row) for row in conn.execute('SELECT * FROM ' + table + ' ORDER BY 1')]


def accepted_provider(monkeypatch):
    requests = []

    class Accepted:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

    def send(request, timeout):
        requests.append(json.loads(request.data))
        return Accepted()

    monkeypatch.setattr(mailer, 'urlopen', send)
    return requests


def test_confirmaciones_solo_autorizada_y_cola_ajena_intacta(app, conn, monkeypatch):
    confirmation(conn, app, OTHER)
    before = rows(conn, 'outbox')[0]
    confirmation(conn, app, AUTHORIZED)
    app.config['MAIL_TEST_RECIPIENT'] = '  PRUEBA-AUTORIZADA@EXAMPLE.TEST  '
    requests = accepted_provider(monkeypatch)
    result = mailer.send_outbox(conn, app.config)
    assert result['sent'] == 1
    assert [request['to'] for request in requests] == [[AUTHORIZED]]
    assert rows(conn, 'outbox')[0] == before
    assert conn.execute("SELECT count(*) FROM audit WHERE action='mail_reserved'").fetchone()[0] == 1
    assert mailer.send_outbox(conn, app.config)['sent'] == 0
    assert len(requests) == 1


@pytest.mark.parametrize('value', [' ', None, 1, True, 'sin-correo', 'a@b', 'a@foo-.ar', '.a@pruebas.ar', 'a@pruebas.ar\nBcc: otra@pruebas.ar'])
def test_restriccion_invalida_falla_cerrada_sin_tocar_cola_reservas_o_cursores(app, conn, value):
    confirmation(conn, app, AUTHORIZED)
    add_subscriber(conn, OTHER, 'confirmed')
    approve_test_job(conn)
    before = {table: rows(conn, table) for table in ('outbox', 'subscribers', 'audit', 'deliveries')}
    app.config['MAIL_TEST_RECIPIENT'] = value
    assert not mailer.delivery_readiness(app.config)['ready']
    assert mailer.queue_digests(conn, ORIGIN, app.config['SECRET_KEY'], config=app.config)['queued'] == 0
    assert mailer.send_outbox(conn, app.config)['sent'] == 0
    assert {table: rows(conn, table) for table in before} == before
    assert conn.execute("SELECT value FROM settings WHERE key IN ('digest_cursor','digest_test_cursor')").fetchone() is None


def test_resumenes_restringidos_no_reservan_ofertas_ajenas_ni_cambian_cursor_general(app, conn, monkeypatch):
    other = add_subscriber(conn, OTHER, 'confirmed')
    authorized = add_subscriber(conn, AUTHORIZED, 'confirmed')
    approve_test_job(conn)
    with conn:
        conn.execute("INSERT INTO settings(key,value) VALUES ('digest_cursor','999')")
    requests = accepted_provider(monkeypatch)
    result = tasks.run_tasks(conn, app.config, only='mail')
    assert result['queue']['queued'] == 1 and result['mail']['sent'] == 1
    assert [request['to'] for request in requests] == [[AUTHORIZED]]
    assert conn.execute('SELECT count(*) FROM deliveries WHERE subscriber_id=?', (other,)).fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM deliveries WHERE subscriber_id=?', (authorized,)).fetchone()[0] == 1
    assert conn.execute("SELECT value FROM settings WHERE key='digest_cursor'").fetchone()[0] == '999'
    assert tasks.run_tasks(conn, app.config, only='mail')['mail']['sent'] == 0
    assert len(requests) == 1


def test_suscripcion_ajena_no_se_guarda_y_template_no_revela_direccion(app, conn):
    client = app.test_client()
    with client.session_transaction(base_url=ORIGIN) as session:
        session['csrf'] = 'csrf-prueba'
    html = client.get('/alertas', base_url=ORIGIN).get_data(as_text=True)
    assert 'prueba limitada' in html and AUTHORIZED not in html and 'name="email"' in html
    response = client.post('/alertas', base_url=ORIGIN, data={
        'csrf_token': 'csrf-prueba', 'email': OTHER, 'frequency': 'daily', 'consent': '1',
    })
    assert response.status_code == 200
    assert 'prueba limitada' in response.get_data(as_text=True)
    assert rows(conn, 'subscribers') == [] and rows(conn, 'outbox') == []
    response = client.post('/alertas', base_url=ORIGIN, data={
        'csrf_token': 'csrf-prueba', 'email': AUTHORIZED.upper(), 'frequency': 'daily', 'consent': '1',
    })
    assert 'Solicitud recibida' in response.get_data(as_text=True)
    assert [row['email'] for row in rows(conn, 'subscribers')] == [AUTHORIZED]


def test_modo_vacio_conserva_envio_general(app, conn, monkeypatch):
    app.config['MAIL_TEST_RECIPIENT'] = ''
    confirmation(conn, app, AUTHORIZED)
    confirmation(conn, app, OTHER)
    requests = accepted_provider(monkeypatch)
    assert mailer.send_outbox(conn, app.config)['sent'] == 2
    assert {request['to'][0] for request in requests} == {AUTHORIZED, OTHER}


def test_cambio_de_suscriptor_despues_de_encolar_no_modifica_mensaje_ajeno(app, conn):
    sid = confirmation(conn, app, AUTHORIZED)
    before = rows(conn, 'outbox')
    with conn:
        conn.execute('UPDATE subscribers SET email=? WHERE id=?', (OTHER, sid))
    assert mailer.send_outbox(conn, app.config)['sent'] == 0
    assert rows(conn, 'outbox') == before
    assert conn.execute("SELECT count(*) FROM audit WHERE action='mail_reserved'").fetchone()[0] == 0


def test_panel_informa_restriccion_sin_revelar_destinatario(app):
    client = app.test_client()
    with client.session_transaction(base_url=ORIGIN) as session:
        session['admin'] = True
    html = client.get('/admin/automatizacion', base_url=ORIGIN).get_data(as_text=True)
    assert 'El correo está limitado a una prueba' in html
    assert AUTHORIZED not in html


def test_endpoint_cron_respeta_destinatario_limitado(app, conn, monkeypatch):
    app.config['CRON_SECRET'] = 'cron-exclusivamente-ficticio'
    confirmation(conn, app, OTHER)
    foreign = rows(conn, 'outbox')[0]
    confirmation(conn, app, AUTHORIZED)
    requests = accepted_provider(monkeypatch)
    response = app.test_client().get('/api/cron/mail', base_url=ORIGIN,
        headers={'Authorization': 'Bearer cron-exclusivamente-ficticio'})
    assert response.status_code == 200
    assert response.json['mail']['sent'] == 1
    assert [request['to'] for request in requests] == [[AUTHORIZED]]
    assert rows(conn, 'outbox')[0] == foreign
