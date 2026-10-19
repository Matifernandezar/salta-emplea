"""Respaldos PostgreSQL fuera de HTTP y restauraciones únicamente aisladas.

Un archivo pg_dump contiene datos personales y SQL ejecutable. El checksum
verifica integridad, no procedencia ni inocuidad. No conectar esta utilidad a
una ruta web ni ejecutarla sobre un destino de producción.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from datetime import datetime, timezone


_MESSAGES = {
    "invalid_database": "Configurá una URL PostgreSQL válida mediante el entorno privado.",
    "unsupported_options": "La conexión contiene opciones no admitidas por el respaldo; revisá la configuración privada.",
    "client_unavailable": "No se pudo ejecutar el cliente PostgreSQL requerido (versión 17 o posterior).",
    "destination_exists": "El respaldo y su manifiesto requieren destinos nuevos; no se sobrescribió ningún archivo.",
    "write_failed": "No se pudo crear el respaldo privado; revisá permisos y espacio disponible.",
    "dump_failed": "Falló el respaldo PostgreSQL; no se conservó una copia incompleta.",
    "invalid_archive": "El archivo o su manifiesto no superaron la comprobación de integridad y permisos.",
    "isolation_required": "La restauración requiere confirmar un entorno aislado y una base nueva salta_restore_<hexadecimal>.",
    "target_not_empty": "La base de restauración contiene objetos; no se modificó su contenido.",
    "restore_failed": "Falló la restauración aislada; revisá el destino antes de volver a intentarla.",
    "quarantine_failed": "La copia restaurada no pudo ponerse en cuarentena; mantenela desconectada de la aplicación.",
}


class BackupError(RuntimeError):
    """Código fijo: nunca incluye DSN, stderr, valores SQL ni secretos."""

    def __init__(self, code):
        self.code = code if code in _MESSAGES else "dump_failed"
        super().__init__(_MESSAGES[self.code])


# No se heredan credenciales de otros proveedores ni PGOPTIONS/servicios.
_LIBPQ_OPTIONS = {
    "host": "PGHOST", "hostaddr": "PGHOSTADDR", "port": "PGPORT",
    "dbname": "PGDATABASE", "user": "PGUSER", "password": "PGPASSWORD",
    "sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY", "sslpassword": "PGSSLPASSWORD",
    "channel_binding": "PGCHANNELBINDING", "sslsni": "PGSSLSNI",
    "ssl_min_protocol_version": "PGSSLMINPROTOCOLVERSION",
    "ssl_max_protocol_version": "PGSSLMAXPROTOCOLVERSION",
    "gssencmode": "PGGSSENCMODE", "target_session_attrs": "PGTARGETSESSIONATTRS",
    "connect_timeout": "PGCONNECT_TIMEOUT", "application_name": "PGAPPNAME",
}
_RESTORE_NAME = re.compile(r"salta_restore_[a-f0-9]{16,32}\Z")


def _connection_environment(database_url):
    if not isinstance(database_url, str) or not database_url.startswith(("postgres://", "postgresql://")):
        raise BackupError("invalid_database")
    try:
        from psycopg.conninfo import conninfo_to_dict
        values = conninfo_to_dict(database_url)
    except Exception:
        raise BackupError("invalid_database") from None
    if not values.get("dbname") or not values.get("host"):
        raise BackupError("invalid_database")
    if set(values) - _LIBPQ_OPTIONS.keys():
        raise BackupError("unsupported_options")
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT") if key in os.environ}
    environment.update({
        "PGPASSFILE": os.devnull,
        "PGSERVICEFILE": os.devnull,
        "PGCONNECT_TIMEOUT": "15",
        "PGAPPNAME": "salta_emplea_backup",
        "PGCLIENTENCODING": "UTF8",
    })
    environment.update({_LIBPQ_OPTIONS[key]: value for key, value in values.items()})
    return values, environment


def _run(arguments, environment, *, stdout=subprocess.DEVNULL, timeout=900):
    try:
        result = subprocess.run(
            arguments, stdin=subprocess.DEVNULL, stdout=stdout,
            stderr=subprocess.DEVNULL, env=environment,
            check=False, timeout=timeout, close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise BackupError("client_unavailable") from None
    return result


def _client_major(command, environment):
    result = _run([command, "--version"], environment, stdout=subprocess.PIPE, timeout=15)
    match = re.fullmatch(rb"[\w_-]+ \(PostgreSQL\) (\d+)(?:\.\d+)*(?:[^\r\n]*)\r?\n?", result.stdout or b"")
    if result.returncode or not match or int(match[1]) < 17:
        raise BackupError("client_unavailable")
    return int(match[1])


def manifest_path(archive):
    return Path(str(archive) + ".json")


def _exclusive_file(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600), "wb")


def _stream_digest(stream):
    digest = hashlib.sha256()
    if stream.read(5) != b"PGDMP":
        raise BackupError("invalid_archive")
    stream.seek(0)
    for part in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(part)
    stream.seek(0)
    return digest.hexdigest()


def _digest(path):
    with path.open("rb") as stream:
        return _stream_digest(stream)


def backup_postgres(database_url, destination):
    """Copia consistente custom + manifiesto0600; no sobrescribe ni inicia app.

    La URL debe provenir de configuración privada. El archivo no está cifrado:
    almacenarlo únicamente en disco privado y cifrar su copia externa.
    """
    _, environment = _connection_environment(database_url)
    major = _client_major("pg_dump", environment)
    archive, created = Path(destination), []
    manifest = manifest_path(archive)
    if archive.exists() or archive.is_symlink() or manifest.exists() or manifest.is_symlink():
        raise BackupError("destination_exists")
    try:
        with _exclusive_file(archive) as stream:
            created.append(archive)
            result = _run([
                "pg_dump", "--format=custom", "--no-owner", "--no-acl",
                "--lock-wait-timeout=10s",
            ], environment, stdout=stream)
            if result.returncode:
                raise BackupError("dump_failed")
            stream.flush()
            os.fsync(stream.fileno())
        metadata = {
            "version": 1, "format": "postgresql-custom", "pg_dump_major": major,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "archive_bytes": archive.stat().st_size, "archive_sha256": _digest(archive),
        }
        with _exclusive_file(manifest) as stream:
            created.append(manifest)
            stream.write((json.dumps(metadata, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        return metadata
    except FileExistsError:
        error = BackupError("destination_exists")
    except BackupError as failure:
        error = BackupError("dump_failed") if failure.code in {"invalid_archive", "client_unavailable"} else failure
    except (OSError, ValueError):
        error = BackupError("write_failed")
    except BaseException:
        # Ctrl+C también retira los archivos de este intento. Un apagado del
        # proceso/SIGKILL puede dejar un archivo sin manifiesto: no restaurarlo.
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    for path in reversed(created):
        try:
            path.unlink()
        except OSError:
            pass
    raise error from None


def verify_archive(archive):
    """Comprueba hash, tamaño, tipo y permisos; no ejecuta el SQL del archivo."""
    archive = Path(archive)
    manifest = manifest_path(archive)
    try:
        for path in (archive, manifest):
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise BackupError("invalid_archive")
        if manifest.stat().st_size > 4096:
            raise BackupError("invalid_archive")
        metadata = json.loads(manifest.read_text(encoding="ascii"))
        if not isinstance(metadata, dict) or metadata.get("version") != 1 or metadata.get("format") != "postgresql-custom":
            raise BackupError("invalid_archive")
        if type(metadata.get("pg_dump_major")) is not int or metadata["pg_dump_major"] < 17:
            raise BackupError("invalid_archive")
        if type(metadata.get("archive_bytes")) is not int or metadata["archive_bytes"] != archive.stat().st_size:
            raise BackupError("invalid_archive")
        if not isinstance(metadata.get("archive_sha256"), str) or metadata["archive_sha256"] != _digest(archive):
            raise BackupError("invalid_archive")
        return metadata
    except (OSError, ValueError, TypeError, UnicodeError):
        raise BackupError("invalid_archive") from None


def _empty_target(database_url, expected_name):
    """Solo SELECT antes de restaurar; sin crear/borrar bases o esquemas."""
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=15, autocommit=True) as conn:
            actual_name = conn.execute("SELECT current_database()").fetchone()[0]
            if actual_name != expected_name:
                raise BackupError("isolation_required")
            occupied = conn.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                    AND n.nspname NOT LIKE 'pg_toast%'
                ) OR EXISTS (
                    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                ) OR EXISTS (
                    SELECT 1 FROM pg_namespace WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema')
                    AND nspname NOT LIKE 'pg_toast%' AND nspname NOT LIKE 'pg_temp_%'
                )
            """).fetchone()[0]
            if occupied:
                raise BackupError("target_not_empty")
    except BackupError:
        raise
    except Exception:
        raise BackupError("restore_failed") from None


def _quarantine(database_url):
    """Defensa adicional: la copia se mantiene desconectada y sin secretos reales."""
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=15) as conn:
            conn.execute("UPDATE sources SET authorized=0,status='paused'")
            conn.execute("UPDATE subscribers SET status='unsubscribed'")
            conn.execute("UPDATE outbox SET status='cancelled',last_error='Copia aislada: envío bloqueado.' WHERE status NOT IN ('sent','cancelled')")
            conn.execute("DELETE FROM task_locks")
    except Exception:
        raise BackupError("quarantine_failed") from None


def restore_postgres_isolated(archive, target_url, *, isolation_confirmed=False):
    """Restaura solo una base vacía salta_restore_<16..32 hex> y la cuarentena.

    El llamador confirma un servidor aislado sin acceso/secretos de producción.
    No se valida la inocuidad del SQL: usar únicamente copias de origen propio
    comprobado y rol limitado. Nunca ejecutar sobre el servidor de producción.
    No crea bases, no usa --clean y no inicia la app, tareas ni correo.
    """
    values, environment = _connection_environment(target_url)
    if isolation_confirmed is not True or not _RESTORE_NAME.fullmatch(values["dbname"]):
        raise BackupError("isolation_required")
    metadata = verify_archive(archive)
    if _client_major("pg_restore", environment) < metadata["pg_dump_major"]:
        raise BackupError("client_unavailable")
    _empty_target(target_url, values["dbname"])
    try:
        stream = os.fdopen(os.open(archive, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb")
    except OSError:
        raise BackupError("invalid_archive") from None
    with stream:
        # Se vuelve a comprobar el descriptor que realmente leerá pg_restore,
        # evitando seguir un enlace o restaurar otra copia tras la comprobación.
        try:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or info.st_size != metadata["archive_bytes"]
                    or _stream_digest(stream) != metadata["archive_sha256"]):
                raise BackupError("invalid_archive")
        except OSError:
            raise BackupError("invalid_archive") from None
        # El archivo entra por stdin; solo el nombre aislado de la base figura
        # en argumentos. El host, usuario, contraseña y TLS van por entorno.
        try:
            result = subprocess.run(
                ["pg_restore", "--dbname=" + values["dbname"], "--no-owner", "--no-acl", "--exit-on-error", "--single-transaction"],
                stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=environment, check=False, timeout=900, close_fds=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise BackupError("restore_failed") from None
    if result.returncode:
        raise BackupError("restore_failed")
    _quarantine(target_url)
    return {"restored": True, "quarantined": True, "archive_sha256": metadata["archive_sha256"]}
