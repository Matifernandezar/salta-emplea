"""Integración de configuración, firma y CLI; no usa proveedores reales."""
import base64
import hashlib
import hmac
import json
import sys
import time

from salta_emplea import cli, db, mailer
from salta_emplea.app import create_app


def test_signed_webhook_bypasses_only_its_csrf_boundary_and_never_opens_public_forms(tmp_path):
    path = tmp_path / 'integracion.sqlite'
    key = b'clave-ficticia-para-integracion-32'
    app = create_app({'TESTING': True, 'APP_ENV': 'development', 'SECRET_KEY': 'clave-local',
        'DATABASE_PATH': str(path), 'UPLOAD_DIR': str(tmp_path / 'imagenes'),
        'RESEND_WEBHOOK_SECRET': 'whsec_' + base64.b64encode(key).decode()})
    conn = db.connect(path)
    with conn:
        conn.execute("INSERT INTO subscribers(email,status,token_hash,created_at) VALUES (?,'confirmed','PRUEBA',?)",
                     ('prueba@example.test', mailer._stamp()))
    body = json.dumps({'type': 'email.bounced', 'data': {'to': ['prueba@example.test']}}).encode()
    stamp = str(int(time.time()))
    signature = base64.b64encode(hmac.new(key, b'msg_integracion.' + stamp.encode() + b'.' + body, hashlib.sha256).digest()).decode()
    headers = {'svix-id': 'msg_integracion', 'svix-timestamp': stamp, 'svix-signature': 'v1,' + signature}
    client = app.test_client()
    response = client.post('/api/webhooks/resend', data=body, content_type='application/json', headers=headers)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert conn.execute('SELECT status FROM subscribers').fetchone()[0] == 'unsubscribed'
    assert client.post('/api/webhooks/resend', data=body, content_type='application/json').status_code == 401
    for route in ('/publicar', '/alertas', '/admin/ingresar'):
        assert client.post(route, data={}).status_code == 400
    conn.close()


def test_mail_limits_are_loaded_from_server_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv('MAIL_DAILY_LIMIT', '12')
    monkeypatch.setenv('MAIL_MONTHLY_LIMIT', '240')
    monkeypatch.setenv('MAIL_CONFIRMATION_RESERVE_DAILY', '3')
    app = create_app({'TESTING': True, 'APP_ENV': 'development', 'SECRET_KEY': 'clave-local',
        'DATABASE_PATH': str(tmp_path / 'limites.sqlite'), 'UPLOAD_DIR': str(tmp_path / 'imagenes')})
    conn = db.connect(app.config['DATABASE_TARGET'])
    quotas = mailer.quota_status(conn, app.config)
    assert quotas['daily']['limit'] == 12
    assert quotas['daily']['digest_limit'] == 9
    assert quotas['monthly']['limit'] == 240
    conn.close()


def test_backup_cli_uses_private_environment_without_starting_app(tmp_path, monkeypatch, capsys):
    from salta_emplea import backup
    monkeypatch.setattr(cli, 'create_app', lambda: (_ for _ in ()).throw(AssertionError('No iniciar app')))
    monkeypatch.setenv('DATABASE_URL', 'postgresql://PRUEBA:secreto-no-imprimir@localhost/PRUEBA')
    received = []
    monkeypatch.setattr(backup, 'backup_postgres', lambda url, destination: received.append((url, destination)))
    monkeypatch.setattr(sys, 'argv', ['salta', 'backup-postgres', str(tmp_path / 'copia.dump')])
    assert cli.main() == 0
    assert received[0][0].startswith('postgresql://PRUEBA:')
    assert 'secreto-no-imprimir' not in capsys.readouterr().out


def test_restore_cli_requires_explicit_isolation_and_does_not_start_app(tmp_path, monkeypatch, capsys):
    from salta_emplea import backup
    monkeypatch.setattr(cli, 'create_app', lambda: (_ for _ in ()).throw(AssertionError('No iniciar app')))
    monkeypatch.setenv('POSTGRES_RESTORE_URL', 'postgresql://PRUEBA:secreto-no-imprimir@localhost/salta_restore_' + 'a' * 16)
    flags = []
    def restore(_archive, _target, *, isolation_confirmed):
        flags.append(isolation_confirmed)
        if not isolation_confirmed:
            raise backup.BackupError('isolation_required')
    monkeypatch.setattr(backup, 'restore_postgres_isolated', restore)
    monkeypatch.setattr(sys, 'argv', ['salta', 'restore-postgres-isolated', str(tmp_path / 'copia.dump')])
    assert cli.main() == 1
    monkeypatch.setattr(sys, 'argv', ['salta', 'restore-postgres-isolated', str(tmp_path / 'copia.dump'), '--confirm-isolation'])
    assert cli.main() == 0
    assert flags == [False, True]
    assert 'secreto-no-imprimir' not in capsys.readouterr().out


def test_production_rejects_collecting_addresses_for_test_sender(tmp_path):
    path = tmp_path / 'remitente.sqlite'
    app = create_app({'TESTING': True, 'APP_ENV': 'production', 'SECRET_KEY': 'clave-ficticia-' * 4,
        'ADMIN_PASSWORD_HASH': 'hash-ficticio-no-usado', 'PUBLIC_BASE_URL': 'https://empleos.pruebas.ar',
        'DATABASE_PATH': str(path), 'UPLOAD_DIR': str(tmp_path / 'imagenes'),
        'RESEND_API_KEY': 'clave-ficticia', 'MAIL_FROM': 'onboarding@resend.dev',
        'MAIL_ENABLED': '1', 'RESEND_WEBHOOK_SECRET': 'whsec_cHJ1ZWJhLWZpY3RpY2lhLW5vLXNlY3JldG8='})
    client = app.test_client()
    origin = 'https://empleos.pruebas.ar'
    with client.session_transaction(base_url=origin) as state:
        state['csrf'] = 'csrf-local'
    response = client.post('/alertas', base_url=origin, data={'csrf_token': 'csrf-local',
        'email': 'prueba@example.test', 'consent': '1', 'frequency': 'daily'})
    assert response.status_code == 200
    assert 'pendientes de configuración' in response.get_data(as_text=True)
    conn = db.connect(path)
    assert conn.execute('SELECT COUNT(*) FROM subscribers').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
    conn.close()


def test_resubscription_cannot_reactivate_a_confirmation_revoked_by_unsubscribe(tmp_path):
    from urllib.parse import urlsplit
    path = tmp_path / 'consentimiento.sqlite'
    secret = 'clave-local-solo-de-pruebas'
    app = create_app({'TESTING': True, 'APP_ENV': 'development', 'SECRET_KEY': secret,
        'PUBLIC_BASE_URL': 'https://example.test', 'RESEND_API_KEY': 'clave-ficticia',
        'MAIL_FROM': 'prueba@example.test', 'MAIL_ENABLED': '1',
        'DATABASE_PATH': str(path), 'UPLOAD_DIR': str(tmp_path / 'imagenes')})
    client = app.test_client()
    with client.session_transaction() as state:
        state['csrf'] = 'csrf-local'
    def post(route, **data):
        return client.post(route, data={'csrf_token': 'csrf-local', **data})
    request = dict(email='prueba@example.test', consent='1', frequency='daily')
    assert post('/alertas', **request).status_code == 200
    conn = db.connect(path)
    def confirmation_path():
        body = conn.execute("SELECT body FROM outbox WHERE kind='confirmation' ORDER BY id DESC LIMIT 1").fetchone()[0]
        return urlsplit(body.split('\n\n')[1]).path
    old_path = confirmation_path()
    assert post(old_path).status_code == 200
    subscriber_id = conn.execute('SELECT id FROM subscribers').fetchone()[0]
    assert post('/alertas/baja/' + mailer.unsubscribe_token(subscriber_id, secret)).status_code == 200
    assert conn.execute('SELECT token_hash FROM subscribers').fetchone()[0] == ''
    assert post('/alertas', **request).status_code == 200
    new_path = confirmation_path()
    assert old_path != new_path
    assert client.get(old_path).status_code == 400
    assert post(old_path).status_code == 400
    assert post(new_path).status_code == 200
    conn.close()


def test_production_requires_public_responsible_before_collecting_subscriptions(tmp_path):
    path = tmp_path / 'responsable.sqlite'
    app = create_app({'TESTING': True, 'APP_ENV': 'production', 'SECRET_KEY': 'clave-ficticia-' * 4,
        'ADMIN_PASSWORD_HASH': 'hash-ficticio-no-usado', 'PUBLIC_BASE_URL': 'https://empleos.pruebas.ar',
        'DATABASE_PATH': str(path), 'UPLOAD_DIR': str(tmp_path / 'imagenes'),
        'RESEND_API_KEY': 'clave-ficticia', 'MAIL_FROM': 'PRUEBA <alertas@pruebas.ar>',
        'MAIL_ENABLED': '1', 'RESEND_WEBHOOK_SECRET': 'whsec_cHJ1ZWJhLWZpY3RpY2lhLW5vLXNlY3JldG8=',
        'PUBLIC_RESPONSIBLE_NAME': '', 'PUBLIC_CONTACT_EMAIL': ''})
    client = app.test_client()
    origin = 'https://empleos.pruebas.ar'
    with client.session_transaction(base_url=origin) as state:
        state['csrf'] = 'csrf-local'
    response = client.post('/alertas', base_url=origin, data={'csrf_token': 'csrf-local',
        'email': 'prueba@example.test', 'consent': '1', 'frequency': 'daily'})
    assert response.status_code == 200
    conn = db.connect(path)
    assert conn.execute('SELECT COUNT(*) FROM subscribers').fetchone()[0] == 0
    conn.close()
