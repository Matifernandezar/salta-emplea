"""Diagnóstico agregado de solo lectura, sin inferir programación ni entrega."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from salta_emplea import db
from salta_emplea.operations import operations_snapshot


_NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "operacion.sqlite3"
    db.init_db(path)
    connection = db.connect(path)
    # Simula exclusivamente la tabla/contrato de leases PostgreSQL sin exigir
    # servidor real para los casos de diagnóstico. SQLite normal usa flock.
    connection.execute("CREATE TABLE task_locks(name TEXT PRIMARY KEY,owner TEXT,expires_at INTEGER)")

    class LeasedConnection:
        backend = "postgres"

        def __getattr__(self, key):
            return getattr(connection, key)

        def __enter__(self):
            connection.__enter__()
            return self

        def __exit__(self, *args):
            return connection.__exit__(*args)

    yield LeasedConnection()
    connection.close()


def _date(hours=0):
    return (_NOW - timedelta(hours=hours)).isoformat()


def _run(conn, task="collect", status="succeeded", hours=0, finished=None):
    conn.execute(
        "INSERT INTO task_runs(task,status,started_at,finished_at,detail) VALUES (?,?,?,?,?)",
        (task, status, _date(hours + 0.1), finished or (_date(hours) if status != "running" else None),
         "postgresql://no-mostrar:clave@servidor/base"),
    )
    conn.commit()


def _task(snapshot, name="collect"):
    return next(item for item in snapshot["tasks"] if item["task"] == name)


def _mail(conn, status="pending", hours=1):
    conn.execute(
        "INSERT INTO outbox(kind,recipient,subject,body,status,idempotency_key,created_at) VALUES ('digest',?,?,?,?,?,?)",
        ("no-mostrar@example.test", "asunto privado", "token-secreto-no-mostrar", status, status + str(hours), _date(hours)),
    )
    conn.commit()


def test_empty_snapshot_has_no_evidence_and_never_claims_scheduler_or_production_backup(conn):
    snapshot = operations_snapshot(conn, {}, now=_NOW)
    assert all(item["state"] == "sin_evidencia" for item in snapshot["tasks"])
    assert all(item["cron_state"] == "sin_evidencia" for item in snapshot["tasks"])
    assert snapshot["scheduler"]["state"] == "no_verificado"
    assert snapshot["backups"]["state"] == "sin_evidencia_produccion"
    assert snapshot["external_alerts"]["state"] == "no_configuradas"
    assert not snapshot["lease"]["active"]
    assert not snapshot["mail_queue"]["needs_review"]


def test_snapshot_only_runs_selects_and_does_not_return_free_text_or_credentials(conn):
    _run(conn)
    _mail(conn)
    with conn:
        conn.execute("INSERT INTO audit(actor,action,detail,created_at) VALUES ('programador','cron_recibido','collect',?)", (_date(),))
        conn.execute("INSERT INTO audit(actor,action,detail,created_at) VALUES ('programador','cron_recibido','token-secreto-no-mostrar',?)", (_date(),))
    before = conn.execute("SELECT count(*) FROM audit").fetchone()[0]
    statements = []

    class ReadOnly:
        backend = "postgres"

        def execute(self, sql, parameters=None):
            assert sql.lstrip().upper().startswith("SELECT ")
            statements.append(sql)
            return conn.execute(sql, parameters) if parameters is not None else conn.execute(sql)

    snapshot = operations_snapshot(ReadOnly(), {"RESEND_API_KEY": "clave-no-mostrar"}, now=_NOW)
    assert statements and len(statements) <= 12
    assert conn.execute("SELECT count(*) FROM audit").fetchone()[0] == before
    text = json.dumps(snapshot)
    for private in ("no-mostrar", "postgresql://", "clave-no-mostrar", "asunto privado", "token-secreto"):
        assert private not in text
    assert _task(snapshot)["state"] == "reciente"
    assert _task(snapshot)["cron_state"] == "llamadas_recibidas"
    assert snapshot["scheduler"]["state"] == "no_verificado"


def test_manual_success_does_not_create_cron_evidence(conn):
    _run(conn, "expire")
    snapshot = operations_snapshot(conn, {}, now=_NOW)
    assert _task(snapshot, "expire")["state"] == "reciente"
    assert _task(snapshot, "expire")["cron_state"] == "sin_evidencia"
    assert _task(snapshot)["state"] == "sin_evidencia"
    assert snapshot["scheduler"]["state"] == "no_verificado"


def test_cron_evidence_is_per_task_and_is_not_success(conn):
    with conn:
        conn.execute("INSERT INTO audit(actor,action,detail,created_at) VALUES ('programador','cron_recibido','mail',?)", (_date(),))
        conn.execute("INSERT INTO audit(actor,action,detail,created_at) VALUES ('otro','cron_recibido','collect',?)", (_date(),))
    snapshot = operations_snapshot(conn, {}, now=_NOW)
    assert _task(snapshot, "mail")["cron_state"] == "llamadas_recibidas"
    assert _task(snapshot, "mail")["state"] == "sin_evidencia"
    assert _task(snapshot)["cron_state"] == "sin_evidencia"


@pytest.mark.parametrize("status", ["partial", "failed", "interrupted"])
def test_new_failed_run_is_visible_while_preserving_last_success(conn, status):
    _run(conn, hours=5)
    _run(conn, status=status, hours=1)
    item = _task(operations_snapshot(conn, {}, now=_NOW))
    assert item["state"] == "fallo"
    assert item["last_run"]["status"] == status
    assert item["last_success_at"] == _date(5)
    assert item["last_success_age_hours"] == 5


def test_thresholds_change_staleness_without_programming_anything(conn):
    _run(conn, hours=30)
    with conn:
        conn.execute("INSERT INTO audit(actor,action,detail,created_at) VALUES ('programador','cron_recibido','collect',?)", (_date(30),))
    assert _task(operations_snapshot(conn, {}, now=_NOW))["state"] == "reciente"
    item = _task(operations_snapshot(conn, {"OPERATIONS_COLLECT_MAX_AGE_HOURS": "24"}, now=_NOW))
    assert item["state"] == "antigua" and item["cron_state"] == "antigua"
    assert item["max_age_hours"] == 24


@pytest.mark.parametrize("value,expected", [(None, 48), (True, 48), ("secreto", 48), (0, 1), (99999, 720)])
def test_bad_or_unbounded_thresholds_are_safe(conn, value, expected):
    item = _task(operations_snapshot(conn, {"OPERATIONS_COLLECT_MAX_AGE_HOURS": value}, now=_NOW))
    assert item["max_age_hours"] == expected


def test_running_run_requires_a_current_shared_lease(conn):
    _run(conn, status="running")
    assert _task(operations_snapshot(conn, {}, now=_NOW))["state"] == "requiere_revision"
    with conn:
        conn.execute("INSERT INTO task_locks(name,owner,expires_at) VALUES ('salta-emplea-tasks','no-mostrar-propietario',?)", (int(_NOW.timestamp()) + 300,))
    snapshot = operations_snapshot(conn, {}, now=_NOW)
    assert _task(snapshot)["state"] == "en_curso" and snapshot["lease"]["active"]
    assert "no-mostrar-propietario" not in json.dumps(snapshot)
    with conn:
        conn.execute("UPDATE task_locks SET expires_at=?", (int(_NOW.timestamp()) - 1,))
    assert _task(operations_snapshot(conn, {}, now=_NOW))["state"] == "requiere_revision"


def test_successful_all_run_applies_but_partial_all_is_not_invented_as_success(conn):
    _run(conn, task="all", hours=1)
    snapshot = operations_snapshot(conn, {}, now=_NOW)
    assert all(item["state"] == "reciente" and item["last_run"]["scope"] == "all" for item in snapshot["tasks"])
    _run(conn, task="all", status="partial")
    snapshot = operations_snapshot(conn, {}, now=_NOW)
    assert all(item["state"] == "fallo" and item["last_success_at"] == _date(1) for item in snapshot["tasks"])


@pytest.mark.parametrize("date", ["sin-fecha-no-mostrar", "2026-10-19T12:00:00", "2026-10-20T12:00:00+00:00"])
def test_invalid_or_future_timestamps_are_redacted_and_need_review(conn, date):
    _run(conn, finished=date)
    with conn:
        conn.execute("INSERT INTO audit(actor,action,detail,created_at) VALUES ('programador','cron_recibido','collect',?)", (date,))
    item = _task(operations_snapshot(conn, {}, now=_NOW))
    assert item["state"] == "requiere_revision"
    assert item["last_success_at"] is None
    assert item["cron_state"] == "requiere_revision" and item["cron_received_at"] is None
    assert date not in json.dumps(item)


def test_outbox_counts_and_age_need_review_without_exposing_messages(conn):
    _mail(conn, "pending", 50)
    _mail(conn, "uncertain", 1)
    _mail(conn, "sent", 2)
    snapshot = operations_snapshot(conn, {}, now=_NOW)
    queue = snapshot["mail_queue"]
    assert queue["counts"] == {"pending": 1, "uncertain": 1, "sent": 1, "failed": 0, "cancelled": 0}
    assert queue["oldest_pending_at"] == _date(50) and queue["oldest_pending_age_hours"] == 50
    assert queue["needs_review"]
    assert "no-mostrar@example.test" not in json.dumps(snapshot)


def test_recent_pending_queue_is_not_failure_but_unknown_dates_require_review(conn):
    _mail(conn, "pending", 1)
    assert not operations_snapshot(conn, {}, now=_NOW)["mail_queue"]["needs_review"]
    with conn:
        conn.execute("UPDATE outbox SET created_at='no-mostrar-fecha-invalida'")
    queue = operations_snapshot(conn, {}, now=_NOW)["mail_queue"]
    assert queue["oldest_pending_at"] is None and queue["needs_review"]


def test_snapshot_rejects_a_naive_current_time(conn):
    with pytest.raises(ValueError, match="zona horaria"):
        operations_snapshot(conn, {}, now=datetime(2026, 10, 19))


def test_sqlite_snapshot_does_not_assume_a_postgres_lease_table(tmp_path):
    path = tmp_path / "sqlite-real.sqlite3"
    db.init_db(path)
    connection = db.connect(path)
    try:
        snapshot = operations_snapshot(connection, {}, now=_NOW)
        assert snapshot["lease"] == {"supported": False, "active": None, "expires_at": None}
        assert connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='task_locks'").fetchone()[0] == 0
    finally:
        connection.close()
