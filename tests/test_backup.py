"""Seguridad de archivos/credenciales y ensayo PostgreSQL real opcional.

POSTGRES_TEST_URL debe apuntar exclusivamente al servidor desechable de CI.
El ensayo crea dos bases aleatorias propias; nunca consulta producción.
"""

from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import pytest
from PIL import Image

from salta_emplea import backup, db, domain


_URL = "postgresql://usuario:clave-ficticia-privada@localhost/prueba?sslmode=require&channel_binding=require"
_image_stream = BytesIO()
Image.new("RGB", (24, 24), "#123456").save(_image_stream, "JPEG")
_IMAGE = _image_stream.getvalue()


def _fake_clients(monkeypatch, *, dump_error=False, timeout=False):
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if arguments[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=(arguments[0] + " (PostgreSQL) 17.7\n").encode())
        if arguments[0] == "pg_dump":
            kwargs["stdout"].write(b"PGDMP-archivo-ficticio-de-PRUEBA")
            if timeout:
                raise subprocess.TimeoutExpired(arguments, 900, stderr=b"clave-ficticia-privada")
            return SimpleNamespace(returncode=int(dump_error))
        assert arguments[0] == "pg_restore"
        assert kwargs["stdin"].read(5) == b"PGDMP"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backup.subprocess, "run", run)
    return calls


def test_dump_custom_archive_is_private_checksummed_and_credentials_are_not_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "credencial-heredada-no-utilizable")
    monkeypatch.setenv("PGSERVICE", "servicio-no-utilizable")
    monkeypatch.setenv("RESEND_API_KEY", "otra-credencial-no-utilizable")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "otra-clave-no-utilizable")
    calls = _fake_clients(monkeypatch)
    destination = tmp_path / "respaldo.dump"
    result = backup.backup_postgres(_URL, destination)
    assert backup.verify_archive(destination) == result
    assert result["archive_bytes"] == destination.stat().st_size
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.manifest_path(destination).stat().st_mode) == 0o600
    for arguments, kwargs in calls:
        assert not any(value in " ".join(arguments) for value in (_URL, "clave-ficticia-privada", "usuario", "localhost"))
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["env"]["PGPASSWORD"] == "clave-ficticia-privada"
        assert kwargs["env"]["PGSSLMODE"] == "require"
        assert kwargs["env"]["PGCHANNELBINDING"] == "require"
        assert kwargs["env"]["PGPASSFILE"] == os.devnull
        assert not {"PGSERVICE", "RESEND_API_KEY", "GOOGLE_VISION_API_KEY"} & kwargs["env"].keys()
    manifest = backup.manifest_path(destination).read_text()
    assert not any(value in manifest for value in (_URL, "clave-ficticia-privada", "usuario", "localhost"))
    assert "--format=custom" in calls[-1][0]
    assert "--no-owner" in calls[-1][0] and "--no-acl" in calls[-1][0]


@pytest.mark.parametrize("existing", ["archive", "manifest", "symlink"])
def test_backup_never_overwrites_existing_files(tmp_path, monkeypatch, existing):
    _fake_clients(monkeypatch)
    destination = tmp_path / "respaldo.dump"
    retained = tmp_path / "conservar"
    retained.write_bytes(b"NO CAMBIAR")
    if existing == "archive":
        destination.write_bytes(b"NO CAMBIAR")
    elif existing == "manifest":
        backup.manifest_path(destination).write_bytes(b"NO CAMBIAR")
    else:
        destination.symlink_to(retained)
    with pytest.raises(backup.BackupError) as failure:
        backup.backup_postgres(_URL, destination)
    assert failure.value.code == "destination_exists"
    assert retained.read_bytes() == b"NO CAMBIAR"
    if existing == "manifest":
        assert not destination.exists()
        assert backup.manifest_path(destination).read_bytes() == b"NO CAMBIAR"
    elif existing == "archive":
        assert destination.read_bytes() == b"NO CAMBIAR"


@pytest.mark.parametrize("timeout", [False, True])
def test_failed_or_interrupted_process_leaves_no_restorable_copy(tmp_path, monkeypatch, timeout):
    _fake_clients(monkeypatch, dump_error=True, timeout=timeout)
    destination = tmp_path / "fallido.dump"
    with pytest.raises(backup.BackupError) as failure:
        backup.backup_postgres(_URL, destination)
    assert failure.value.code == "dump_failed"
    assert not destination.exists() and not backup.manifest_path(destination).exists()
    assert "clave-ficticia-privada" not in str(failure.value)


def test_keyboard_interrupt_removes_only_files_created_by_that_attempt(tmp_path, monkeypatch):
    original = _fake_clients(monkeypatch)
    fake_run = backup.subprocess.run

    def interrupted(arguments, **kwargs):
        if arguments[-1] == "--version":
            return fake_run(arguments, **kwargs)
        kwargs["stdout"].write(b"PGDMP-incompleto")
        raise KeyboardInterrupt

    monkeypatch.setattr(backup.subprocess, "run", interrupted)
    destination = tmp_path / "interrumpido.dump"
    with pytest.raises(KeyboardInterrupt):
        backup.backup_postgres(_URL, destination)
    assert not destination.exists() and not backup.manifest_path(destination).exists()
    assert len(original) == 1


@pytest.mark.parametrize("url,code", [
    ("sqlite:///privada", "invalid_database"),
    ("postgresql://malformado:%error@/privada", "invalid_database"),
    (_URL + "&options=-c%20log_statement%3Dall", "unsupported_options"),
    (_URL + "&service=externo", "unsupported_options"),
])
def test_invalid_connection_is_rejected_before_starting_process(tmp_path, monkeypatch, url, code):
    calls = _fake_clients(monkeypatch)
    with pytest.raises(backup.BackupError) as failure:
        backup.backup_postgres(url, tmp_path / "x.dump")
    assert failure.value.code == code
    assert not calls
    assert url not in str(failure.value)


@pytest.mark.parametrize("tamper", ["archive", "hash", "permissions", "symlink", "large_manifest"])
def test_integrity_check_rejects_changed_or_exposed_backups(tmp_path, monkeypatch, tamper):
    _fake_clients(monkeypatch)
    destination = tmp_path / "respaldo.dump"
    backup.backup_postgres(_URL, destination)
    manifest = backup.manifest_path(destination)
    if tamper == "archive":
        destination.write_bytes(b"PGDMP-CONTENIDO DIFERENTE")
    elif tamper == "hash":
        metadata = json.loads(manifest.read_text())
        metadata["archive_sha256"] = "0" * 64
        manifest.write_text(json.dumps(metadata))
    elif tamper == "permissions":
        destination.chmod(0o644)
    elif tamper == "symlink":
        other = tmp_path / "otro.dump"
        destination.rename(other)
        destination.symlink_to(other)
    else:
        manifest.write_bytes(b" " * 4097)
    with pytest.raises(backup.BackupError) as failure:
        backup.verify_archive(destination)
    assert failure.value.code == "invalid_archive"


@pytest.mark.parametrize("confirmed,name", [
    (False, "salta_restore_0123456789abcdef"),
    (True, "produccion"),
    (True, "salta_restore_corto"),
    (True, "salta_restore_0123456789abcdef/otro"),
])
def test_restore_requires_explicit_isolation_and_reserved_name(tmp_path, monkeypatch, confirmed, name):
    calls = _fake_clients(monkeypatch)
    target = "postgresql://u:p@localhost/" + quote(name, safe="")
    with pytest.raises(backup.BackupError) as failure:
        backup.restore_postgres_isolated(tmp_path / "no-existe", target, isolation_confirmed=confirmed)
    assert failure.value.code == "isolation_required"
    assert not calls


def test_restore_checks_empty_target_and_quarantines_without_starting_app(tmp_path, monkeypatch):
    calls = _fake_clients(monkeypatch)
    destination = tmp_path / "respaldo.dump"
    backup.backup_postgres(_URL, destination)
    target = "postgresql://u:secreto-restauracion@localhost/salta_restore_0123456789abcdef"
    checkpoints = []
    monkeypatch.setattr(backup, "_empty_target", lambda url, name: checkpoints.append(("empty", name)))
    monkeypatch.setattr(backup, "_quarantine", lambda url: checkpoints.append(("quarantine", None)))
    result = backup.restore_postgres_isolated(destination, target, isolation_confirmed=True)
    assert result["restored"] and result["quarantined"]
    assert checkpoints == [("empty", "salta_restore_0123456789abcdef"), ("quarantine", None)]
    arguments, kwargs = calls[-1]
    assert "--single-transaction" in arguments and "--exit-on-error" in arguments
    assert "--clean" not in arguments and "--create" not in arguments
    assert target not in " ".join(arguments) and "secreto-restauracion" not in " ".join(arguments)
    assert kwargs["env"]["PGPASSWORD"] == "secreto-restauracion"


@pytest.mark.parametrize("change", ["missing", "symlink", "content"])
def test_restore_rechecks_actual_file_descriptor_after_target_check(tmp_path, monkeypatch, change):
    calls = _fake_clients(monkeypatch)
    destination = tmp_path / "respaldo.dump"
    backup.backup_postgres(_URL, destination)

    def changed(*args):
        if change == "content":
            destination.write_bytes(b"PGDMP-copia-modificada")
        else:
            other = tmp_path / "otra.dump"
            destination.rename(other)
            if change == "symlink":
                destination.symlink_to(other)

    monkeypatch.setattr(backup, "_empty_target", changed)
    with pytest.raises(backup.BackupError) as failure:
        backup.restore_postgres_isolated(destination, "postgresql://u:p@localhost/salta_restore_0123456789abcdef", isolation_confirmed=True)
    assert failure.value.code == "invalid_archive"
    assert not any(args[0] == "pg_restore" and "--version" not in args for args, _ in calls)


def test_restore_does_not_invoke_restore_when_target_has_data(tmp_path, monkeypatch):
    calls = _fake_clients(monkeypatch)
    destination = tmp_path / "respaldo.dump"
    backup.backup_postgres(_URL, destination)

    def occupied(*args):
        raise backup.BackupError("target_not_empty")

    monkeypatch.setattr(backup, "_empty_target", occupied)
    with pytest.raises(backup.BackupError) as failure:
        backup.restore_postgres_isolated(destination, "postgresql://u:p@localhost/salta_restore_0123456789abcdef", isolation_confirmed=True)
    assert failure.value.code == "target_not_empty"
    assert not any(args[0] == "pg_restore" and "--version" not in args for args, _ in calls)


def _database_url(url, name, user=None, password=None):
    parts = urlsplit(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key not in {"dbname", "user", "password"}])
    netloc = parts.netloc
    if user is not None:
        host = "[" + parts.hostname + "]" if ":" in parts.hostname else parts.hostname
        netloc = quote(user, safe="") + ":" + quote(password, safe="") + "@" + host
        if parts.port:
            netloc += ":" + str(parts.port)
    return urlunsplit((parts.scheme, netloc, "/" + name, query, ""))


def test_postgres_real_custom_dump_restore_integrity_private_image_and_quarantine(tmp_path):
    """PostgreSQL17 → pg_dump real → checksum → pg_restore real → SQL/imagen.

    Este ensayo no envía correo, no inicia Flask ni conecta al programador.
    """
    target = os.environ.get("POSTGRES_TEST_URL")
    if not target:
        pytest.skip("POSTGRES_TEST_URL no configurada; requiere PostgreSQL real aislado")
    import psycopg
    from psycopg import sql

    source_name = "salta_backup_" + secrets.token_hex(8)
    restore_name = "salta_restore_" + secrets.token_hex(8)
    role = "salta_backup_role_" + secrets.token_hex(8)
    password = secrets.token_urlsafe(30)
    source_url = _database_url(target, source_name, role, password)
    restore_url = _database_url(target, restore_name, role, password)
    created, role_created = [], False
    admin = psycopg.connect(target, autocommit=True)
    try:
        try:
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Identifier(role), sql.Literal(password)))
        except psycopg.errors.InsufficientPrivilege:
            pytest.skip("El servidor de pruebas requiere CREATE ROLE para verificar restauración con rol limitado")
        role_created = True
        for name in (source_name, restore_name):
            try:
                admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(name), sql.Identifier(role)))
            except psycopg.errors.InsufficientPrivilege:
                pytest.skip("El servidor de pruebas requiere permiso CREATE DATABASE para el ensayo aislado")
            created.append(name)
        db.init_db(source_url)
        conn = db.connect(source_url)
        try:
            job_id, _ = domain.create_job(conn, {
                "title": "PRUEBA DE RESTAURACIÓN — no publicar",
                "company": "EMPRESA FICTICIA DE PRUEBA", "location": "Salta",
                "modality": "presencial", "description": "Datos ficticios para verificar integridad.",
                "source_url": "https://example.test/backup-prueba",
                "application_url": "mailto:prueba@example.test",
            }, "prueba_aislada")
            with conn:
                conn.execute("INSERT INTO uploads(name,data,created_at) VALUES (?,?,?)", ("prueba.jpg", _IMAGE, domain.now()))
                conn.execute("UPDATE jobs SET image_path='prueba.jpg' WHERE id=?", (job_id,))
                conn.execute("INSERT INTO sources(name,url,status,authorized) VALUES ('PRUEBA','https://example.test/feed','active',1)")
                subscriber = conn.execute("INSERT INTO subscribers(email,status,token_hash,created_at) VALUES ('backup@example.test','confirmed','ficticio',?)", (domain.now(),)).lastrowid
                conn.execute("INSERT INTO outbox(kind,subscriber_id,recipient,subject,body,status,idempotency_key,created_at) VALUES ('digest',?,'backup@example.test','PRUEBA','PRUEBA','pending','backup-prueba',?)", (subscriber, domain.now()))
                conn.execute("INSERT INTO task_locks(name,owner,expires_at) VALUES ('prueba','ficticio',9999999999)")
            original_title = conn.execute("SELECT title FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
        finally:
            conn.close()
        archive = tmp_path / "real.dump"
        metadata = backup.backup_postgres(source_url, archive)
        assert metadata == backup.verify_archive(archive)
        assert backup.restore_postgres_isolated(archive, restore_url, isolation_confirmed=True)["quarantined"]
        restored = db.connect(restore_url)
        try:
            row = restored.execute("SELECT title,status,image_path FROM jobs WHERE id=?", (job_id,)).fetchone()
            assert dict(row) == {"title": original_title, "status": "pending", "image_path": "prueba.jpg"}
            restored_image = bytes(restored.execute("SELECT data FROM uploads WHERE name='prueba.jpg'").fetchone()[0])
            assert restored_image == _IMAGE
            with Image.open(BytesIO(restored_image)) as image:
                assert image.format == "JPEG" and image.size == (24, 24)
            assert restored.execute("SELECT count(*) FROM provenance WHERE job_id=?", (job_id,)).fetchone()[0] == 1
            assert restored.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
            assert restored.execute("SELECT count(*) FROM sources WHERE authorized=0 AND status='paused'").fetchone()[0] == 1
            assert restored.execute("SELECT status FROM subscribers").fetchone()[0] == "unsubscribed"
            assert restored.execute("SELECT status FROM outbox").fetchone()[0] == "cancelled"
            assert restored.execute("SELECT count(*) FROM task_locks").fetchone()[0] == 0
            assert domain.public_jobs(restored) == []
            from salta_emplea.operations import operations_snapshot
            operational = operations_snapshot(restored, {})
            assert operational["lease"]["supported"] is True and not operational["lease"]["active"]
            assert operational["mail_queue"]["counts"]["cancelled"] == 1
            assert operational["backups"]["state"] == "sin_evidencia_produccion"
            with pytest.raises(backup.BackupError) as failure:
                backup.restore_postgres_isolated(archive, restore_url, isolation_confirmed=True)
            assert failure.value.code == "target_not_empty"
        finally:
            restored.close()
        original = db.connect(source_url)
        try:
            assert original.execute("SELECT status FROM outbox").fetchone()[0] == "pending"
            assert original.execute("SELECT status FROM subscribers").fetchone()[0] == "confirmed"
            assert original.execute("SELECT authorized FROM sources").fetchone()[0] == 1
        finally:
            original.close()
    finally:
        for name in reversed(created):
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        if role_created:
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        admin.close()
