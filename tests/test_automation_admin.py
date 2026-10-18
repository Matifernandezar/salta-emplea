"""Control manual de tareas reales, con datos ficticios y proveedores locales."""
import json

import pytest

from salta_emplea import db, domain, mailer, tasks
from salta_emplea.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({
        'TESTING': True, 'APP_ENV': 'development',
        'SECRET_KEY': 'secreto-ficticio-de-pruebas-automatizacion',
        'ADMIN_PASSWORD_HASH': '', 'DATABASE_URL': '', 'SERVERLESS': False,
        'DATABASE_PATH': str(tmp_path / 'automatizacion.sqlite3'),
        'UPLOAD_DIR': str(tmp_path / 'imagenes'),
        'PUBLIC_BASE_URL': 'https://example.org',
        'RESEND_API_KEY': '', 'MAIL_FROM': '', 'CRON_SECRET': '',
    })


@pytest.fixture
def conn(app):
    connection = db.connect(app.config['DATABASE_TARGET'])
    yield connection
    connection.close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    # La autenticación con contraseña se cubre en test_web; acá se aísla el permiso.
    with client.session_transaction() as state:
        state['admin'] = True
        state['csrf'] = 'token-ficticio-de-automatizacion'
    return client


def run(admin, task, **kwargs):
    return admin.post('/admin/automatizacion/' + task,
                      data={'csrf_token': 'token-ficticio-de-automatizacion'}, **kwargs)


def test_automation_requires_admin_for_reads_and_writes(client, conn):
    with client.session_transaction() as state:
        state['csrf'] = 'token-ficticio-de-automatizacion'
    assert client.get('/admin/automatizacion').location.endswith('/admin/ingresar')
    assert run(client, 'expire').location.endswith('/admin/ingresar')
    assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 0


def test_manual_task_requires_post_and_matching_csrf(admin, conn):
    assert admin.get('/admin/automatizacion/expire').status_code == 405
    for data in ({}, {'csrf_token': 'otro-token'}):
        assert admin.post('/admin/automatizacion/expire', data=data).status_code == 400
    assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 0


@pytest.mark.parametrize('task', ['approve', 'all', 'activate', 'desconocida'])
def test_unknown_task_is_rejected_without_changes(admin, conn, task):
    assert run(admin, task).status_code == 404
    assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM audit').fetchone()[0] == 0


def test_status_distinguishes_configuration_from_scheduler_evidence(admin, app, conn):
    app.config.update(CRON_SECRET='no-mostrar-cron', RESEND_API_KEY='no-mostrar-api',
                      MAIL_FROM='remitente-privado@pruebas.ar')
    with conn:
        conn.execute("INSERT INTO task_runs(task,started_at,status,detail) VALUES ('collect',?,'failed',?)",
                     (domain.now(), 'postgresql://usuario:clave@db.example.org/base'))
        conn.execute("INSERT INTO sources(name,url,method,status,authorized,last_result) VALUES ('FUENTE FICTICIA',?,'jobicy','active',1,?)",
                     (tasks.JOBICY_API, 'https://usuario:clave@proveedor.example.org'))
    response = admin.get('/admin/automatizacion')
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'SQLite' in text
    assert 'No hay evidencia de llamadas autenticadas al cron' in text
    assert 'no demuestra que el programador' in text
    assert 'Deshabilitado por configuración incompleta o entorno de desarrollo' in text
    for private in ('no-mostrar-cron', 'no-mostrar-api', 'remitente-privado', 'usuario:clave'):
        assert private not in text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'


def test_authenticated_cron_is_recorded_but_fake_call_is_not(admin, app, client, conn):
    app.config['CRON_SECRET'] = 'secreto-cron-ficticio'
    assert client.get('/api/cron/expire').status_code == 401
    assert conn.execute("SELECT count(*) FROM audit WHERE action='cron_recibido'").fetchone()[0] == 0
    assert client.get('/api/cron/expire', headers={'Authorization': 'Bearer secreto-cron-ficticio'}).status_code == 200
    event = conn.execute("SELECT * FROM audit WHERE action='cron_recibido'").fetchone()
    assert event['actor'] == 'programador'
    assert event['detail'] == 'expire'
    text = admin.get('/admin/automatizacion').get_data(as_text=True)
    assert event['created_at'] in text
    assert 'no garantiza que la tarea haya terminado' in text


def test_manual_task_uses_shared_lock_without_interrupting_live_run(admin, conn):
    with conn:
        conn.execute("INSERT INTO task_runs(task,started_at,status) VALUES ('collect',?,'running')", (domain.now(),))
    with db.task_lock(conn, tasks.TASK_LOCK_NAME) as acquired:
        assert acquired
        response = run(admin, 'expire', follow_redirects=True)
    assert 'Ya hay una tarea en ejecución' in response.get_data(as_text=True)
    assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 1
    assert conn.execute('SELECT status FROM task_runs').fetchone()[0] == 'running'


def test_manual_collection_deduplicates_and_never_approves_or_activates(admin, conn, monkeypatch):
    with conn:
        source_id = conn.execute("INSERT INTO sources(name,url,method,status,authorized,frequency_hours) VALUES ('FUENTE FICTICIA',?,'jobicy','active',1,24)", (tasks.JOBICY_API,)).lastrowid
        other_id = conn.execute("INSERT INTO sources(name,url,method,status,authorized) VALUES ('SIN PERMISO',?,'jobicy','disabled',0)", (tasks.JOBICY_API,)).lastrowid
    calls = []

    def fetch(url):
        calls.append(url)
        if '/status?' in url:
            return {'jobs': [{'id': 998877, 'status': 'active'}]}
        return {'jobs': [{
            'id': 998877, 'jobTitle': 'PRUEBA — Operador remoto',
            'companyName': 'Empresa ficticia', 'jobGeo': 'Argentina',
            'url': 'https://jobicy.com/jobs/998877-prueba-ficticia',
            'jobDescription': 'Oferta ficticia de prueba, no postularse.',
        }]}

    monkeypatch.setattr(tasks, 'fetch_json', fetch)
    assert run(admin, 'collect').status_code == 302
    with conn:
        conn.execute('UPDATE sources SET last_run_at=NULL WHERE id=?', (source_id,))
    assert run(admin, 'collect').status_code == 302
    assert len(calls) == 4
    jobs = conn.execute('SELECT * FROM jobs').fetchall()
    assert len(jobs) == 1 and jobs[0]['status'] == 'pending'
    assert domain.public_jobs(conn) == []
    assert conn.execute('SELECT status,authorized,last_run_at FROM sources WHERE id=?', (other_id,)).fetchone()[:] == ('disabled', 0, None)
    assert json.loads(conn.execute('SELECT last_result FROM sources WHERE id=?', (source_id,)).fetchone()[0])['duplicates'] == 1


def test_mail_without_provider_preserves_queue_and_never_sends(admin, app, conn, monkeypatch):
    with conn:
        subscriber_id = conn.execute("INSERT INTO subscribers(email,frequency,status,token_hash,created_at) VALUES ('prueba@example.org','daily','pending','',?)", (domain.now(),)).lastrowid
    mailer.queue_confirmation(conn, subscriber_id, app.config['PUBLIC_BASE_URL'], app.config['SECRET_KEY'])
    monkeypatch.setattr(mailer, 'urlopen', lambda *_a, **_k: pytest.fail('No debe enviar sin proveedor.'))
    for _ in range(2):
        response = run(admin, 'mail', follow_redirects=True)
        assert 'No se enviaron correos' in response.get_data(as_text=True)
    messages = conn.execute('SELECT status,attempts FROM outbox').fetchall()
    assert len(messages) == 1 and tuple(messages[0]) == ('pending', 0)
    assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 2


def test_manual_tasks_never_publish_pending_jobs(admin, conn):
    job_id, _ = domain.create_job(conn, {
        'title': 'PRUEBA — Oferta pendiente', 'application_url': 'https://example.org/prueba',
    })
    for task in ('collect', 'expire', 'mail'):
        assert run(admin, task).status_code == 302
    assert conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'pending'
    assert domain.public_jobs(conn) == []


def test_manual_runs_are_bounded_and_rate_limited(admin, app, conn, monkeypatch):
    app.config.update(TASK_BUDGET_SECONDS=240, TASK_MAIL_BATCH=100, TASK_SOURCE_BATCH=10)
    calls = []

    def run_task(_conn, config, only):
        calls.append((config['TASK_BUDGET_SECONDS'], config['TASK_MAIL_BATCH'], config['TASK_SOURCE_BATCH'], only))
        return {}

    monkeypatch.setattr(tasks, 'run_tasks', run_task)
    for _ in range(6):
        assert run(admin, 'expire').status_code == 302
    assert run(admin, 'expire').status_code == 429
    assert calls == [(60, 3, 1, 'expire')] * 6


def test_task_failure_is_friendly_and_does_not_reveal_exception(admin, conn, monkeypatch, caplog):
    def broken(*_a, **_k):
        raise RuntimeError('credencial-ultrasecreta https://usuario:clave@servidor.example.org')

    monkeypatch.setattr(tasks, 'run_tasks', broken)
    response = run(admin, 'collect', follow_redirects=True)
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'No se pudo completar la corrida' in text
    for private in ('credencial-ultrasecreta', 'usuario:clave'):
        assert private not in text
        assert private not in caplog.text


def test_admin_navigation_links_to_automation(admin):
    assert 'href="/admin/automatizacion"' in admin.get('/admin').get_data(as_text=True)
