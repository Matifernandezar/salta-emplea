"""Contrato del adaptador y pruebas reales opcionales con POSTGRES_TEST_URL.

Las pruebas remotas crean y borran únicamente un esquema aleatorio propio.
La cuenta de prueba necesita CREATE SCHEMA; no usar credenciales de producción.
"""

import os
import secrets
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlsplit

import pytest

from salta_emplea import db, domain, mailer
from salta_emplea.app import create_app


def test_postgres_target_detection_and_row_contract():
    assert db.is_postgres("postgres://user:secret@localhost/test")
    assert db.is_postgres("postgresql://user:secret@localhost/test")
    assert not db.is_postgres("/tmp/local.sqlite3")
    row = db._Row(("id", "title"), (4, "Puesto"))
    assert row[0] == row["id"] == 4
    assert row[-1] == "Puesto"
    assert dict(row) == {"id": 4, "title": "Puesto"}


def test_parameters_leave_literals_and_comments_intact():
    sql = "SELECT ?, '¿qué? 10%', 'it''s ?', \"a?\" -- ?\n/* ? */ WHERE name LIKE ?"
    assert db._qmark_sql(sql) == "SELECT %s, '¿qué? 10%%', 'it''s ?', \"a?\" -- ?\n/* ? */ WHERE name LIKE %s"


def test_insert_translation_is_limited_to_known_forms():
    sql, generated = db._postgres_statement("INSERT OR IGNORE INTO provenance(job_id) VALUES (?)")
    assert sql == "INSERT INTO provenance(job_id) VALUES (?) ON CONFLICT DO NOTHING RETURNING id"
    assert generated
    sql, generated = db._postgres_statement("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO NOTHING")
    assert sql.endswith("ON CONFLICT(key) DO NOTHING")
    assert not generated
    sql, generated = db._postgres_statement("INSERT INTO jobs(title) VALUES (?) RETURNING id")
    assert sql.count("RETURNING") == 1
    assert not generated


def test_sqlite_task_lock_is_shared_and_released(tmp_path):
    target = tmp_path / "locks.sqlite3"
    db.init_db(target)
    first, second = db.connect(target), db.connect(target)
    try:
        with db.task_lock(first, "salta-emplea-tasks") as acquired:
            assert acquired
            with db.task_lock(second, "salta-emplea-tasks") as other:
                assert not other
        with db.task_lock(second, "salta-emplea-tasks") as acquired:
            assert acquired
    finally:
        first.close()
        second.close()


@pytest.fixture
def postgres(monkeypatch):
    target = os.environ.get("POSTGRES_TEST_URL")
    if not target:
        pytest.skip("POSTGRES_TEST_URL no configurada; requiere PostgreSQL real")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    original_connect = db.connect
    schema = "salta_test_" + secrets.token_hex(8)
    admin = original_connect(target)
    admin._connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    def scoped_connect(url):
        conn = original_connect(url)
        if db.is_postgres(url):
            conn._connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        return conn

    monkeypatch.setattr(db, "connect", scoped_connect)
    connections = []

    def connection():
        conn = scoped_connect(target)
        connections.append(conn)
        return conn

    try:
        db.init_db(target)
        yield target, connection
    finally:
        for conn in connections:
            conn.close()
        admin._connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def _offer():
    return {
        "title": "Técnico de prueba PostgreSQL",
        "company": "EMPRESA DE PRUEBA",
        "location": "Orán",
        "modality": "presencial",
        "description": "Datos ficticios para pruebas automatizadas; no publicar.",
        "source_url": "https://example.test/postgres-oferta",
        "application_url": "mailto:pruebas@example.test",
    }


def test_postgres_migrations_rows_transactions_and_private_uploads(postgres):
    target, connect = postgres
    db.init_db(target)
    conn = connect()
    assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    assert conn.execute("SELECT fold(?)", ("TÉCNICO en Orán",)).fetchone()[0] == "tecnico en oran"
    assert not conn.in_transaction
    with pytest.raises(RuntimeError, match="transacción"):
        db.editorial_lock(conn)
    with pytest.raises(ValueError):
        with conn:
            conn.execute("INSERT INTO settings(key,value) VALUES (?,?)", ("rollback", "no"))
            raise ValueError("Revertir")
    assert not conn.in_transaction
    assert conn.execute("SELECT value FROM settings WHERE key='rollback'").fetchone() is None
    with conn:
        conn.execute("INSERT INTO uploads(name,data,created_at) VALUES (?,?,?)", ("prueba.jpg", b"\x00\x01", domain.now()))
    assert bytes(connect().execute("SELECT data FROM uploads WHERE name=?", ("prueba.jpg",)).fetchone()[0]) == b"\x00\x01"


def test_postgres_complete_editorial_flow_and_deduplication(postgres):
    _, connect = postgres
    conn = connect()
    job_id, duplicates = domain.create_job(conn, _offer(), "administrador")
    assert isinstance(job_id, int) and not duplicates
    assert domain.public_jobs(conn) == []
    domain.transition_job(conn, job_id, "approve", "administrador")
    assert [job["id"] for job in domain.public_jobs(connect(), {"q": "tecnico", "location": "orán"})] == [job_id]
    assert domain.create_job(connect(), _offer(), "administrador")[0] == job_id
    assert conn.execute("SELECT count(*) FROM provenance").fetchone()[0] == 1
    updated = _offer() | {"application_url": "https://example.test/otro-contacto"}
    domain.create_job(conn, updated, "recopilador_autorizado")
    assert domain.public_jobs(conn) == []


def test_postgres_concurrent_imports_share_editorial_lock(postgres):
    _, connect = postgres
    barrier = Barrier(2)

    def import_once():
        conn = connect()
        barrier.wait(timeout=10)
        return domain.create_job(conn, _offer(), "recopilador_autorizado")[0]

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: import_once(), range(2)))
    assert results[0] == results[1]
    assert connect().execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_postgres_leases_exclusion_expiry_and_owner_release(postgres):
    _, connect = postgres
    first, second = connect(), connect()
    first_lock = db.task_lock(first, "salta-emplea-tasks")
    assert first_lock.__enter__()
    with db.task_lock(second, "salta-emplea-tasks") as acquired:
        assert not acquired
    second.execute("UPDATE task_locks SET expires_at=0 WHERE name=?", ("salta-emplea-tasks",))
    with db.task_lock(second, "salta-emplea-tasks") as acquired:
        assert acquired
        first_lock.__exit__(None, None, None)
        assert second.execute("SELECT count(*) FROM task_locks").fetchone()[0] == 1
    assert first.execute("SELECT count(*) FROM task_locks").fetchone()[0] == 0


def test_postgres_mail_reservations_are_idempotent(postgres):
    _, connect = postgres
    conn = connect()
    job_id, _ = domain.create_job(conn, _offer(), "administrador")
    domain.transition_job(conn, job_id, "approve", "administrador")
    with conn:
        subscriber_id = conn.execute(
            "INSERT INTO subscribers(email,status,token_hash,created_at) VALUES (?,'confirmed','',?)",
            ("prueba@example.test", domain.now()),
        ).lastrowid
    assert subscriber_id
    assert mailer.queue_digests(conn, "https://example.test", "secret" * 8)["queued"] == 1
    assert not conn.in_transaction
    assert mailer.queue_digests(connect(), "https://example.test", "secret" * 8)["queued"] == 0
    assert conn.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1
    assert mailer.send_outbox(conn, {"APP_ENV": "development"})["skipped"] == 1


def test_postgres_http_serverless_editorial_images_alerts_and_cron(postgres, tmp_path, monkeypatch):
    """HTTP → reglas → PostgreSQL real → otra conexión, sin envíos externos."""
    from PIL import Image
    from werkzeug.security import generate_password_hash

    target, connect = postgres
    password = "contraseña-exclusiva-de-pruebas-postgresql"
    origin = "https://empleos.pruebas.ar"
    secret = "clave-ficticia-solo-para-pruebas-postgresql"
    app = create_app({
        "TESTING": True, "SERVERLESS": True, "DATABASE_URL": target,
        "SECRET_KEY": secret, "ADMIN_PASSWORD_HASH": generate_password_hash(password),
        "PUBLIC_BASE_URL": origin, "CRON_SECRET": "cron-ficticio-de-pruebas",
        "PUBLIC_RESPONSIBLE_NAME": "RESPONSABLE DE PRUEBA", "PUBLIC_CONTACT_EMAIL": "contacto@example.test",
        "DATABASE_PATH": str(tmp_path / "no-debe-crearse.sqlite3"),
        "UPLOAD_DIR": str(tmp_path / "no-debe-crearse"),
        # Proveedor sustituido debajo: ninguna conexión ni entrega real.
        "RESEND_API_KEY": "credencial-ficticia-solo-pruebas", "MAIL_FROM": "PRUEBA <alertas@pruebas.ar>",
        "MAIL_ENABLED": "1", "RESEND_WEBHOOK_SECRET": "whsec_cHJ1ZWJhLWZpY3RpY2lhLW5vLXNlY3JldG8=",
    })
    class Accepted:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def getcode(self):
            return 200
        def read(self, *_args):
            return b'{"id":"proveedor-ficticio-sin-entrega"}'
    monkeypatch.setattr(mailer, 'urlopen', lambda *_args, **_kwargs: Accepted())
    public, admin = app.test_client(), app.test_client()

    def get(client, path, **kwargs):
        return client.get(path, base_url=origin, **kwargs)

    def post(client, path, data=None):
        with client.session_transaction(base_url=origin) as state:
            state.setdefault("csrf", "csrf-ficticio-de-pruebas")
            token = state["csrf"]
        return client.post(path, base_url=origin, data={"csrf_token": token, **(data or {})})

    assert not (tmp_path / "no-debe-crearse").exists()
    assert not (tmp_path / "no-debe-crearse.sqlite3").exists()
    assert get(public, "/salud").json == {"status": "ok"}
    assert get(public, "/admin").status_code == 302
    image = BytesIO()
    Image.new("RGB", (10, 10), "white").save(image, "PNG")
    image.seek(0)
    assert post(public, "/publicar", _offer() | {"consent": "1", "image": (image, "prueba.png")}).status_code == 200
    conn = connect()
    job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
    assert get(public, f"/ofertas/{job_id}").status_code == 404
    assert get(public, f"/admin/imagenes/{job_id}").status_code == 302
    assert post(admin, "/admin/ingresar", {"password": password}).status_code == 302
    private_image = get(admin, f"/admin/imagenes/{job_id}")
    assert private_image.status_code == 200 and private_image.mimetype == "image/jpeg"
    assert post(admin, f"/admin/ofertas/{job_id}/approve", {"acknowledge": "1"}).status_code == 302
    assert get(public, "/?q=tecnico&location=orán").status_code == 200
    assert "Técnico de prueba PostgreSQL" in get(public, "/?q=tecnico").get_data(as_text=True)
    assert "mailto:pruebas@example.test" in get(public, f"/ofertas/{job_id}").get_data(as_text=True)
    assert post(public, "/publicar", _offer() | {"consent": "1"}).status_code == 200
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1

    assert post(public, "/alertas", {"email": "alertas@example.test", "consent": "1", "frequency": "daily"}).status_code == 200
    subscriber = conn.execute("SELECT * FROM subscribers").fetchone()
    confirmation = conn.execute("SELECT body FROM outbox WHERE kind='confirmation'").fetchone()[0]
    confirm_path = urlsplit(confirmation.split("\n\n")[1]).path
    assert get(public, confirm_path).status_code == 200
    assert post(public, confirm_path).status_code == 200
    assert conn.execute("SELECT status FROM subscribers").fetchone()[0] == "confirmed"
    assert get(public, "/api/cron/mail").status_code == 401
    cron_headers = {"Authorization": "Bearer cron-ficticio-de-pruebas"}
    assert get(public, "/api/cron/mail", headers=cron_headers).status_code == 200
    assert get(public, "/api/cron/mail", headers=cron_headers).status_code == 200
    assert conn.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1
    unsubscribe_path = "/alertas/baja/" + mailer.unsubscribe_token(subscriber["id"], secret)
    assert post(public, unsubscribe_path).status_code == 200
    assert conn.execute("SELECT status FROM subscribers").fetchone()[0] == "unsubscribed"
    with conn:
        conn.execute("UPDATE jobs SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job_id,))
    assert get(public, "/api/cron/expire", headers=cron_headers).status_code == 200
    assert get(public, f"/ofertas/{job_id}").status_code == 404
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0] == "expired"


def test_postgres_image_reading_reserves_once_and_never_publishes(postgres, monkeypatch):
    """Reserva → proveedor sustituido → PostgreSQL → otra conexión, sin red real."""
    import hashlib
    import io
    from PIL import Image
    from salta_emplea import extraction, image_pipeline, tasks

    target, connect = postgres
    conn = connect()
    content = io.BytesIO()
    Image.new('RGB', (80, 80), 'blue').save(content, 'JPEG', quality=85)
    image = content.getvalue()
    name = hashlib.sha256(image).hexdigest() + '.jpg'
    with conn:
        conn.execute('INSERT INTO uploads(name,data,created_at) VALUES (?,?,?)', (name, image, domain.now()))
    job_id, _ = domain.create_job(conn, {'title': 'Aviso pendiente de transcripción', 'image_path': name})
    config = {'DATABASE_TARGET': target, 'APP_ENV': 'production', 'OCR_ENABLED': '1',
              'GOOGLE_VISION_API_KEY': 'clave-ficticia-no-productiva', 'OCR_MONTHLY_LIMIT': 1,
              'SECRET_KEY': 'secreto-ficticio-de-pruebas'}
    image_pipeline.authorize(conn, job_id, config, 'administrador-prueba')
    calls = []
    def extract(image_bytes, key):
        calls.append(image_bytes)
        return {'text': 'Puesto: PRUEBA — Atención\nCorreo: rrhh@example.test', 'warnings': []}
    monkeypatch.setattr(extraction, 'extract_image', extract)
    assert image_pipeline.status(conn, config)['pending'] == 1
    assert tasks.run_tasks(conn, config, only='extract')['images']['prepared'] == 1
    other = connect()
    row = other.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    assert row['title'] == 'PRUEBA — Atención' and row['status'] == 'pending'
    assert row['approved_at'] is None and domain.public_jobs(other) == []
    assert image_pipeline.result_for(other, job_id, name)['status'] == 'completed'
    assert image_pipeline.status(other, config)['pending'] == 0
    assert tasks.run_tasks(other, config, only='extract')['images']['quota_reached'] is True
    assert calls == [image]


def test_postgres_edits_and_approvals_share_editorial_lock(postgres):
    """Una lectura OCR no pierde el bloqueo entre contrastar y escribir datos."""
    from threading import Event
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    _, connect = postgres
    owner = connect()
    job_id, _ = domain.create_job(owner, _offer(), 'administrador')
    started = Event()
    def edit_or_approve(action):
        concurrent = connect()
        started.set()
        if action == 'edit':
            domain.edit_job(concurrent, job_id, {'title': 'PRUEBA — Edición concurrente'}, 'administrador')
        else:
            domain.transition_job(concurrent, job_id, 'approve', 'administrador', acknowledge=True)
    with ThreadPoolExecutor(max_workers=1) as workers:
        for action in ('edit', 'approve'):
            started.clear()
            with owner:
                db.editorial_lock(owner)
                future = workers.submit(edit_or_approve, action)
                assert started.wait(3)
                with pytest.raises(FutureTimeout): future.result(timeout=0.15)
            future.result(timeout=5)
    assert owner.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'approved'


def test_postgres_rejected_image_retry_is_private_serialized_and_consumed_once(postgres, monkeypatch):
    import hashlib
    import io
    from PIL import Image
    from salta_emplea import extraction, image_pipeline, tasks

    target, connect = postgres
    first, second = connect(), connect()
    buffer = io.BytesIO()
    Image.new('RGB', (80,80), 'green').save(buffer, 'JPEG')
    image = buffer.getvalue()
    name = hashlib.sha256(image).hexdigest() + '.jpg'
    with first:
        first.execute('INSERT INTO uploads(name,data,created_at) VALUES (?,?,?)', (name,image,domain.now()))
    job_id, _ = domain.create_job(first, {'title':'Aviso pendiente de transcripción','image_path':name})
    config = {'DATABASE_TARGET':target, 'APP_ENV':'production', 'OCR_ENABLED':'1',
              'GOOGLE_VISION_API_KEY':'clave-ficticia-no-productiva', 'OCR_MONTHLY_LIMIT':999,
              'SECRET_KEY':'secreto-ficticio-solo-pruebas'}
    image_pipeline.authorize(first,job_id,config,'administrador-prueba')
    calls = []
    def extract(*_a):
        calls.append(1)
        if len(calls)==1: raise extraction.ExtractionError('credentials_rejected')
        return {'text':'Puesto: PRUEBA — Reintento\nCorreo: prueba@example.test','warnings':[]}
    monkeypatch.setattr(extraction,'extract_image',extract)
    assert tasks.run_tasks(first,config,only='extract')['images']['errors']==1
    failed = image_pipeline.result_for(second,job_id,name)
    image_pipeline.authorize_retry(second,job_id,config,failed['event_id'],'administrador-prueba')
    assert image_pipeline.status(first,config)['pending']==1
    with db.task_lock(first,tasks.TASK_LOCK_NAME) as acquired:
        assert acquired
        assert 'skipped' in tasks.run_tasks(second,config,only='extract')
    assert tasks.run_tasks(second,config,only='extract')['images']['prepared']==1
    assert tasks.run_tasks(first,config,only='extract')['images']['processed']==0
    assert calls==[1,1] and image_pipeline.usage(first)==2
    assert image_pipeline.result_for(first,job_id,name)['status']=='completed'
    job = first.execute('SELECT status,approved_at FROM jobs WHERE id=?',(job_id,)).fetchone()
    assert job['status']=='pending' and job['approved_at'] is None and domain.public_jobs(first)==[]


def test_postgres_mail_quota_serializes_workers_and_verified_suppression_is_idempotent(postgres):
    import json
    from salta_emplea import mail_webhooks
    _target, connection = postgres
    first = connection()
    email = 'prueba-cuota@example.test'
    with first:
        subscriber_id = first.execute(
            "INSERT INTO subscribers(email,status,token_hash,created_at) VALUES (?,'confirmed','PRUEBA',?)",
            (email, mailer._stamp()),
        ).lastrowid
        outbox_id = first.execute(
            "INSERT INTO outbox(kind,subscriber_id,recipient,subject,body,idempotency_key,created_at) "
            "VALUES ('confirmation',?,?,'PRUEBA','PRUEBA','cuota-pg',?)",
            (subscriber_id, email, mailer._stamp()),
        ).lastrowid
    config = {'MAIL_DAILY_LIMIT': 1, 'MAIL_MONTHLY_LIMIT': 10}
    barrier = Barrier(2)
    def reserve():
        conn = connection()
        barrier.wait(timeout=10)
        with mailer._transaction(conn):
            return mailer._reserve_quota(conn, {'id': outbox_id, 'kind': 'confirmation'}, config)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve) for _ in range(2)]
        assert sorted(future.result(timeout=15) for future in futures) == [False, True]
    assert mailer.quota_status(first, config)['daily']['used'] == 1
    body = json.dumps({'type': 'email.bounced', 'data': {'to': [email]}}).encode()
    assert mail_webhooks.process_verified_event(first, body, 'msg_pg_test')['status'] == 'processed'
    assert mail_webhooks.process_verified_event(connection(), body, 'msg_pg_test')['status'] == 'duplicate'
    assert first.execute('SELECT status FROM subscribers WHERE id=?', (subscriber_id,)).fetchone()[0] == 'unsubscribed'
    assert mailer.is_suppressed(first, email)
    assert first.execute("SELECT COUNT(*) FROM audit WHERE action='mail_reserved'").fetchone()[0] == 1
