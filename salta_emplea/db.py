"""SQLite local y PostgreSQL para despliegues sin disco persistente.

El adaptador conserva la pequeña interfaz de las reglas editoriales. Abrir una
conexión remota nunca modifica el esquema: las migraciones son explícitas.
"""

import re
import secrets
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


_ID_TABLES = frozenset({
    "jobs", "provenance", "sources", "reports", "subscribers", "outbox",
    "ads", "audit", "task_runs",
})
_EDITORIAL_LOCK = 6000001001
_MAILER_LOCK = 6000001002
_MIGRATION_LOCK = 6000001003
_MEMORY_TASK_LOCK = threading.Lock()
SCHEMA_VERSION = 2


def is_postgres(target):
    """Acepta una URL o una conexión, sin mostrar credenciales en errores."""
    if getattr(target, "backend", None) == "postgres":
        return True
    return isinstance(target, str) and target.startswith(("postgres://", "postgresql://"))


def _qmark_sql(statement):
    """Convierte parámetros fuera de literales/comentarios a formato psycopg.

    Los porcentajes literales también se escapan para psycopg. Los valores del
    usuario siguen separados de la sentencia, nunca se interpolan.
    """
    result, index, state = [], 0, None
    while index < len(statement):
        char = statement[index]
        pair = statement[index:index + 2]
        if state == "line":
            result.append("%%" if char == "%" else char)
            if char == "\n":
                state = None
        elif state == "block":
            if pair == "*/":
                result.append(pair)
                index += 1
                state = None
            else:
                result.append("%%" if char == "%" else char)
        elif state in ("'", '"'):
            result.append("%%" if char == "%" else char)
            if char == state:
                if index + 1 < len(statement) and statement[index + 1] == state:
                    result.append(state)
                    index += 1
                else:
                    state = None
        elif pair in ("--", "/*"):
            state = "line" if pair == "--" else "block"
            result.append(pair)
            index += 1
        elif char in ("'", '"'):
            state = char
            result.append(char)
        else:
            result.append("%s" if char == "?" else "%%" if char == "%" else char)
        index += 1
    return "".join(result)


def _postgres_statement(statement):
    """Adapta únicamente las formas INSERT usadas por el código existente."""
    sql = statement.strip().rstrip(";")
    ignored = bool(re.match(r"INSERT\s+OR\s+IGNORE\b", sql, re.I))
    if ignored:
        sql = re.sub(r"^INSERT\s+OR\s+IGNORE\b", "INSERT", sql, count=1, flags=re.I)
        sql += " ON CONFLICT DO NOTHING"
    inserted = re.match(r"INSERT\s+INTO\s+([a-z_]+)\b", sql, re.I)
    generated_id = bool(inserted and inserted.group(1).lower() in _ID_TABLES
                        and not re.search(r"\bRETURNING\b", sql, re.I))
    if generated_id:
        sql += " RETURNING id"
    return sql, generated_id


class _Row:
    """Como sqlite3.Row: nombre/posición y conversión con dict(row)."""

    def __init__(self, columns, values):
        self._columns, self._values = tuple(columns), tuple(values)
        self._positions = {column: index for index, column in enumerate(columns)}

    def __getitem__(self, key):
        if isinstance(key, str):
            key = self._positions[key]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._columns


class _Cursor:
    def __init__(self, cursor, generated_id=False):
        self._cursor = cursor
        self._columns = tuple(column.name for column in (cursor.description or ()))
        self._first = cursor.fetchone() if generated_id else None
        self.lastrowid = self._first[0] if self._first is not None else None

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def fetchone(self):
        if self._first is not None:
            values, self._first = self._first, None
        else:
            values = self._cursor.fetchone()
        return _Row(self._columns, values) if values is not None else None

    def fetchall(self):
        rows = []
        if self._first is not None:
            rows.append(_Row(self._columns, self._first))
            self._first = None
        rows.extend(_Row(self._columns, values) for values in self._cursor.fetchall())
        return rows

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def close(self):
        self._cursor.close()


class _PostgresConnection:
    backend = "postgres"

    def __init__(self, connection):
        self._connection = connection
        self._contexts = []
        self._savepoint = 0

    @property
    def in_transaction(self):
        # psycopg TransactionStatus.IDLE == 0; también detecta INERROR.
        return self._connection.info.transaction_status != 0

    def execute(self, statement, parameters=None):
        if statement.strip().rstrip(";").upper() == "BEGIN IMMEDIATE":
            cursor = self._connection.execute("BEGIN")
            self._connection.execute("SELECT pg_advisory_xact_lock(%s)", (_MAILER_LOCK,))
            return _Cursor(cursor)
        sql, generated_id = _postgres_statement(statement)
        cursor = self._connection.execute(_qmark_sql(sql), parameters) if parameters is not None else self._connection.execute(sql)
        return _Cursor(cursor, generated_id)

    def executemany(self, statement, parameters):
        last = None
        for values in parameters:
            last = self.execute(statement, values)
        return last

    def executescript(self, statement):
        return self._connection.execute(statement, prepare=False)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        if self.in_transaction:
            self._savepoint += 1
            name = f"db_context_{self._savepoint}"
            self._connection.execute(f"SAVEPOINT {name}")
        else:
            name = None
            self._connection.execute("BEGIN")
        self._contexts.append(name)
        return self

    def __exit__(self, error_type, error, traceback):
        name = self._contexts.pop()
        if name is None:
            self.rollback() if error_type else self.commit()
        else:
            if error_type:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self._connection.execute(f"RELEASE SAVEPOINT {name}")
        return False


def connect(path):
    if is_postgres(path):
        import psycopg

        return _PostgresConnection(psycopg.connect(
            path, autocommit=True, connect_timeout=15, application_name="salta_emplea",
            prepare_threshold=None,
        ))
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.create_function("fold", 1, lambda value: "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).casefold(), deterministic=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def editorial_lock(conn):
    """Reservar la deduplicación dentro de la transacción editorial actual."""
    if is_postgres(conn):
        if not conn.in_transaction:
            raise RuntimeError("El bloqueo editorial requiere una transacción.")
        conn.execute("SELECT pg_advisory_xact_lock(?)", (_EDITORIAL_LOCK,))
    else:
        # SQLite obtiene su reserva de escritura incluso sin filas coincidentes.
        conn.execute("UPDATE settings SET value=value WHERE key='__domain_lock__'")


def mailer_lock(conn):
    """Serializa reservas de correo también dentro de una transacción existente."""
    if is_postgres(conn):
        if not conn.in_transaction:
            raise RuntimeError("El bloqueo de correo requiere una transacción.")
        conn.execute("SELECT pg_advisory_xact_lock(?)", (_MAILER_LOCK,))


@contextmanager
def task_lock(conn, name="all", ttl_seconds=900):
    """Bloqueo de tareas: flock local o lease PostgreSQL compatible con poolers.

    El presupuesto de la tarea debe ser inferior al TTL. Una liberación tardía
    jamás elimina el lease adquirido posteriormente por otro trabajador.
    """
    if not is_postgres(conn):
        import fcntl

        database_path = conn.execute("PRAGMA database_list").fetchone()[2]
        if not database_path:
            acquired = _MEMORY_TASK_LOCK.acquire(blocking=False)
            try:
                yield acquired
            finally:
                if acquired:
                    _MEMORY_TASK_LOCK.release()
            return
        with open(database_path + ".tasks.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
            try:
                yield acquired
            finally:
                if acquired:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        return
    if conn.in_transaction:
        raise RuntimeError("El lease requiere una conexión sin transacción abierta.")
    if not isinstance(name, str) or not name or len(name) > 100 or not 30 <= ttl_seconds <= 3600:
        raise ValueError("Nombre o duración del bloqueo no válido.")
    owner = secrets.token_hex(24)
    row = conn.execute(
        "INSERT INTO task_locks(name,owner,expires_at) "
        "VALUES (?,?,EXTRACT(EPOCH FROM clock_timestamp())::BIGINT + ?) "
        "ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at "
        "WHERE task_locks.expires_at<=EXTRACT(EPOCH FROM clock_timestamp())::BIGINT RETURNING owner",
        (name, owner, ttl_seconds),
    ).fetchone()
    acquired = bool(row and row["owner"] == owner)
    try:
        yield acquired
    finally:
        if acquired:
            conn.execute("DELETE FROM task_locks WHERE name=? AND owner=?", (name, owner))


def init_db(path):
    if is_postgres(path):
        conn = connect(path)
        try:
            with conn:
                conn.execute("SELECT pg_advisory_xact_lock(?)", (_MIGRATION_LOCK,))
                conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                version = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise RuntimeError("La base usa una versión más nueva que esta aplicación.")
                if version == 0:
                    conn.executescript(Path(__file__).with_name("schema_postgres.sql").read_text(encoding="utf-8"))
                if version < 2:
                    conn.executescript(Path(__file__).with_name("migration_002.sql").read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (2,?)",
                                 (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
        finally:
            conn.close()
        return
    if str(path) != ':memory:':
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("La base usa una versión más nueva que esta aplicación.")
        if version == 0:
            conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            conn.commit()
        if version < 2:
            script = Path(__file__).with_name("migration_002.sql").read_text(encoding="utf-8")
            conn.executescript("BEGIN IMMEDIATE;\n" + script + "\nINSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES (2,CURRENT_TIMESTAMP);\nPRAGMA user_version=2;\nCOMMIT;")
    finally:
        conn.close()
