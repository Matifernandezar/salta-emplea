"""Retención explícita en SQLite temporal; sin producción ni envíos externos."""

import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from salta_emplea import db, domain, retention


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=60)).isoformat(timespec='seconds')


@pytest.fixture
def conn(tmp_path, monkeypatch):
    target = tmp_path / 'retencion-prueba.sqlite3'
    db.init_db(target)
    connection = db.connect(target)
    monkeypatch.setattr(retention, '_now', lambda: NOW)
    yield connection
    connection.close()


def subscriber(conn, name='prueba', **changes):
    values = dict(email=name + '@example.org', frequency='weekly', status='pending',
                  token_hash='hash-ficticio', created_at=OLD, confirmed_at=None, last_sent_at=None)
    values.update(changes)
    columns = ','.join(values)
    with conn:
        return conn.execute('INSERT INTO subscribers(' + columns + ') VALUES (' + ','.join('?' for _ in values) + ')',
                            tuple(values.values())).lastrowid


def confirmation(conn, subscriber_id, key='prueba', **changes):
    values = dict(kind='confirmation', subscriber_id=subscriber_id, recipient='prueba@example.org',
                  subject='PRUEBA', body='Contenido ficticio privado', status='pending',
                  idempotency_key=key, attempts=0, first_attempt_at=None,
                  created_at=OLD, sent_at=None)
    values.update(changes)
    with conn:
        return conn.execute('INSERT INTO outbox(' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')',
                            tuple(values.values())).lastrowid


def job(conn, image_path=None):
    job_id, _ = domain.create_job(conn, {
        'title': 'PRUEBA — Aviso ficticio', 'source_url': 'https://example.org/prueba',
        'application_url': 'https://example.org/postular-prueba', 'image_path': image_path,
    }, actor='administrador')
    return job_id


def apply(conn, **config):
    return retention.apply(conn, {'RETENTION_APPLY_CONFIRMED': True, **config})


def test_preview_never_writes_or_exposes_private_values(conn):
    person = subscriber(conn)
    confirmation(conn, person)
    with conn:
        conn.execute('INSERT INTO rate_limits(key,count,reset_at) VALUES (?,?,?)', ('huella-privada', 2, '10'))
    before = conn.total_changes
    result = retention.preview(conn, {})
    assert conn.total_changes == before
    assert not conn.in_transaction
    assert result['mode'] == 'preview'
    assert result['rate_limits']['selected'] == 1
    assert result['subscribers']['selected'] == 1
    assert result['subscribers']['confirmations_selected'] == 1
    rendered = json.dumps(result)
    assert '@example.org' not in rendered and 'huella-privada' not in rendered
    assert 'hash-ficticio' not in rendered and 'Contenido ficticio privado' not in rendered


@pytest.mark.parametrize('flag', [None, False, '1', 1, 'true'])
def test_apply_requires_programmatic_explicit_confirmation(conn, flag):
    subscriber(conn)
    with pytest.raises(ValueError, match='confirmación explícita'):
        retention.apply(conn, {'RETENTION_APPLY_CONFIRMED': flag})
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 1


def test_old_never_attempted_confirmations_removed_explicitly_and_repeating_is_noop(conn):
    person = subscriber(conn)
    confirmation(conn, person, key='pendiente')
    confirmation(conn, person, key='cancelada', status='cancelled')
    result = apply(conn)
    assert result['removed'] == {'rate_limits': 0, 'subscribers': 1, 'confirmations': 2}
    assert conn.execute('SELECT count(*) FROM outbox').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 0
    event = conn.execute("SELECT detail FROM audit WHERE action='retention_applied'").fetchone()[0]
    assert '@' not in event and 'hash-ficticio' not in event
    before = conn.total_changes
    repeated = apply(conn)
    assert repeated['removed'] == {'rate_limits': 0, 'subscribers': 0, 'confirmations': 0}
    assert conn.execute("SELECT count(*) FROM audit WHERE action='retention_applied'").fetchone()[0] == 1
    # El bloqueo SQLite puede realizar un UPDATE sin filas; no agrega registros.
    assert conn.total_changes == before


@pytest.mark.parametrize('changes', [
    {'status': 'sent'}, {'status': 'uncertain'}, {'status': 'failed'},
    {'attempts': 1}, {'first_attempt_at': OLD}, {'sent_at': OLD},
    {'kind': 'digest'}, {'created_at': NOW.isoformat()},
])
def test_attempted_uncertain_or_recent_mail_protects_subscription(conn, changes):
    person = subscriber(conn)
    outbox_id = confirmation(conn, person, **changes)
    assert retention.preview(conn, {})['subscribers']['protected'] == 1
    assert apply(conn)['removed']['subscribers'] == 0
    assert conn.execute('SELECT id FROM outbox WHERE id=?', (outbox_id,)).fetchone()


def test_reservation_ledger_overrides_reset_attempt_fields(conn):
    person = subscriber(conn)
    outbox_id = confirmation(conn, person)
    with conn:
        conn.execute('INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES (?,?,?,?,?)',
                     ('mailer', 'mail_reserved', outbox_id, 'confirmation', OLD))
    assert apply(conn)['removed']['subscribers'] == 0
    assert conn.execute("SELECT count(*) FROM audit WHERE action='mail_reserved'").fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM outbox').fetchone()[0] == 1


def test_confirmed_unsubscribed_previously_confirmed_or_recent_people_never_removed(conn):
    subscriber(conn, 'confirmada', status='confirmed', confirmed_at=OLD)
    subscriber(conn, 'baja', status='unsubscribed')
    subscriber(conn, 'historial', confirmed_at=OLD)
    subscriber(conn, 'enviado', last_sent_at=OLD)
    subscriber(conn, 'reciente', created_at=NOW.isoformat())
    subscriber(conn, 'fecha-incierta', created_at='2000-fecha-desconocida')
    subscriber(conn, 'fecha-sin-zona', created_at='2000-01-01T00:00:00')
    assert apply(conn)['removed']['subscribers'] == 0
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 7


def test_foreign_key_deliveries_protect_both_referenced_subscriber_and_outbox(conn):
    pending = subscriber(conn, 'pendiente')
    confirmed = subscriber(conn, 'confirmada', status='confirmed', confirmed_at=OLD)
    outbox_id = confirmation(conn, pending)
    job_id = job(conn)
    with conn:
        conn.execute('INSERT INTO deliveries(subscriber_id,job_id,outbox_id) VALUES (?,?,?)',
                     (confirmed, job_id, outbox_id))
    assert apply(conn)['removed']['subscribers'] == 0
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 1
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    with conn:
        conn.execute('DELETE FROM deliveries')
        conn.execute('INSERT INTO deliveries(subscriber_id,job_id) VALUES (?,?)', (pending, job_id))
    assert apply(conn)['removed']['subscribers'] == 0


def test_quotas_ocr_backup_ledgers_and_suppressions_are_never_erased(conn):
    with conn:
        for action in ('ocr_reserved', 'ocr_failed', 'mail_reserved', 'backup_created', 'manual_review'):
            conn.execute('INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES (?,?,?,?,?)',
                         ('prueba', action, 999, '{}', OLD))
        for key in ('mail_suppressed:huella', 'mail_webhook:huella', 'backup:ultimo'):
            conn.execute('INSERT INTO settings(key,value) VALUES (?,?)', (key, 'privado'))
    subscriber(conn)
    assert apply(conn)['removed']['subscribers'] == 1
    assert conn.execute("SELECT count(*) FROM audit WHERE action<>'retention_applied'").fetchone()[0] == 5
    assert conn.execute('SELECT count(*) FROM settings').fetchone()[0] == 3


def test_only_expired_canonical_numeric_rate_limits_are_removed(conn):
    values = [('antiguo', '1'), ('actual', str(int(NOW.timestamp()))),
              ('futuro', str(int(NOW.timestamp()) + 100)), ('desconocido', 'ayer')]
    with conn:
        conn.executemany('INSERT INTO rate_limits(key,count,reset_at) VALUES (?,1,?)', values)
    result = apply(conn)
    assert result['rate_limits']['invalid'] == 1
    assert result['removed']['rate_limits'] == 1
    assert {r[0] for r in conn.execute('SELECT key FROM rate_limits')} == {'actual', 'futuro', 'desconocido'}


def test_batch_limit_counts_subscribers_and_outbox_rows_together(conn):
    person = subscriber(conn)
    confirmation(conn, person, 'primera')
    confirmation(conn, person, 'segunda')
    assert apply(conn, RETENTION_BATCH_LIMIT=2)['removed']['subscribers'] == 0
    result = apply(conn, RETENTION_BATCH_LIMIT=3)
    assert sum(result['removed'].values()) == 3
    for index in range(5):
        subscriber(conn, 'sin-cola-' + str(index))
    assert apply(conn, RETENTION_BATCH_LIMIT=2)['removed']['subscribers'] == 2
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 3


def test_scan_limit_is_reported_and_never_deletes_unexamined_rows(conn):
    for index in range(5):
        subscriber(conn, 'persona-' + str(index))
    result = apply(conn, RETENTION_SCAN_LIMIT=2)
    assert result['subscribers']['truncated'] is True
    assert result['subscribers']['scanned'] == 2
    assert result['removed']['subscribers'] == 2


def test_excessive_confirmation_history_requires_manual_review(conn):
    person = subscriber(conn)
    for index in range(retention.MAX_CONFIRMATIONS_PER_SUBSCRIBER + 1):
        confirmation(conn, person, str(index))
    assert apply(conn)['removed']['subscribers'] == 0


@pytest.mark.parametrize('config', [
    {'RETENTION_UNCONFIRMED_DAYS': 29}, {'RETENTION_UNCONFIRMED_DAYS': 'infinito'},
    {'RETENTION_BATCH_LIMIT': 0}, {'RETENTION_BATCH_LIMIT': 1001},
    {'RETENTION_SCAN_LIMIT': 10001}, {'RETENTION_BATCH_LIMIT': True},
])
def test_invalid_limits_fail_without_deletion(conn, config):
    subscriber(conn)
    with pytest.raises(ValueError, match='Configuración de retención'):
        apply(conn, **config)
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 1


def test_images_are_inventory_only_and_ocr_or_provenance_references_preserved(conn, tmp_path):
    directory = tmp_path / 'imagenes'
    directory.mkdir()
    referenced = 'a' * 64 + '.jpg'
    ledger = 'b' * 64 + '.jpg'
    orphan = 'c' * 64 + '.jpg'
    for name in (referenced, ledger, orphan):
        (directory / name).write_bytes(b'PRUEBA: no es una imagen real')
    job_id = job(conn, referenced)
    with conn:
        # La procedencia sigue protegiendo la imagen anterior al cambiar el aviso.
        conn.execute('UPDATE jobs SET image_path=NULL WHERE id=?', (job_id,))
        conn.execute('INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES (?,?,?,?,?)',
                     ('lector', 'ocr_reserved', 999, json.dumps({'image_path': ledger}), OLD))
    before = sorted(p.name for p in directory.iterdir())
    images = retention.preview(conn, {'UPLOAD_DIR': str(directory)})['images']
    assert images['editorial_references'] == 1
    assert images['ocr_ledger_references'] == 1
    assert images['unreferenced_needs_review'] == 1
    assert images['deletion_enabled'] is False
    apply(conn, UPLOAD_DIR=str(directory))
    assert sorted(p.name for p in directory.iterdir()) == before


def test_image_inventory_never_follows_symlinks_or_opens_files(conn, tmp_path, monkeypatch):
    directory = tmp_path / 'imagenes'
    directory.mkdir()
    external = tmp_path / 'privado.txt'
    external.write_text('NO LEER: dato privado ficticio')
    (directory / ('a' * 64 + '.jpg')).symlink_to(external)
    (directory / 'carpeta').mkdir()
    (directory / 'desconocido.txt').write_text('PRUEBA')
    def forbidden(*_args, **_kwargs):
        raise AssertionError('El inventario no debe abrir archivos.')
    monkeypatch.setattr('pathlib.Path.open', forbidden)
    images = retention.preview(conn, {'UPLOAD_DIR': str(directory)})['images']
    assert images['symlinks_skipped'] == 1
    assert images['unrecognized_entries'] == 2
    link = tmp_path / 'carpeta-enlazada'
    link.symlink_to(directory, target_is_directory=True)
    images = retention.preview(conn, {'UPLOAD_DIR': str(link)})['images']
    assert images['scanned'] == 0 and images['symlinks_skipped'] == 1


def test_apply_is_atomic_if_a_late_database_operation_fails(conn):
    person = subscriber(conn)
    confirmation(conn, person)
    with conn:
        conn.execute("CREATE TRIGGER prueba_fallo BEFORE INSERT ON audit WHEN NEW.action='retention_applied' "
                     "BEGIN SELECT RAISE(ABORT, 'fallo ficticio'); END")
    with pytest.raises(Exception, match='fallo ficticio'):
        apply(conn)
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM outbox').fetchone()[0] == 1
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_nested_apply_rolls_back_with_the_callers_transaction(conn):
    subscriber(conn)
    conn.execute('BEGIN IMMEDIATE')
    assert apply(conn)['removed']['subscribers'] == 1
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM subscribers').fetchone()[0] == 1


def test_postgres_retention_keeps_ledgers_uploads_and_shared_mailer_lock(monkeypatch):
    target = os.environ.get('POSTGRES_TEST_URL')
    if not target:
        pytest.skip('POSTGRES_TEST_URL no configurada; requiere PostgreSQL aislado')
    pytest.importorskip('psycopg')
    from psycopg import sql
    from pathlib import Path

    admin, connection, observer = db.connect(target), db.connect(target), db.connect(target)
    schema = 'salta_retention_test_' + secrets.token_hex(8)
    original_lock = db.mailer_lock
    try:
        admin._connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        for item in (connection, observer):
            item._connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        with connection:
            connection.executescript(Path(db.__file__).with_name('schema_postgres.sql').read_text())
        monkeypatch.setattr(retention, '_now', lambda: NOW)
        person = subscriber(connection)
        confirmation(connection, person)
        image_name = 'd' * 64 + '.jpg'
        with connection:
            connection.execute('INSERT INTO uploads(name,data,created_at) VALUES (?,?,?)', (image_name, b'PRUEBA', OLD))
            connection.execute('INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES (?,?,?,?,?)',
                               ('lector', 'ocr_reserved', 999, json.dumps({'image_path': image_name}), OLD))
            connection.execute('INSERT INTO settings(key,value) VALUES (?,?)', ('mail_suppressed:prueba', '1'))
            connection.execute('INSERT INTO rate_limits(key,count,reset_at) VALUES (?,1,?)', ('prueba', '1'))
        result = retention.preview(connection, {})
        assert not connection.in_transaction
        assert result['images']['ocr_ledger_references'] == 1

        def observed_lock(conn):
            original_lock(conn)
            with observer:
                assert observer.execute('SELECT pg_try_advisory_xact_lock(?)', (db._MAILER_LOCK,)).fetchone()[0] is False

        monkeypatch.setattr(db, 'mailer_lock', observed_lock)
        assert apply(connection)['removed'] == {'rate_limits': 1, 'subscribers': 1, 'confirmations': 1}
        assert connection.execute('SELECT count(*) FROM uploads').fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM audit WHERE action='ocr_reserved'").fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM settings').fetchone()[0] == 1
        assert sum(apply(connection)['removed'].values()) == 0
    finally:
        connection.close()
        observer.close()
        admin._connection.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
        admin.close()
