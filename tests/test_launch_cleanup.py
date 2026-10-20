"""Retiro autorizado con registros PRUEBA aislados, sin producción ni red."""

import json
import os
import secrets
import sqlite3

import pytest

from salta_emplea import db, domain, launch_cleanup


ENABLED = {
    "RETIRE_KNOWN_TEST_OFFER": "1",
    "VERCEL_ENV": "production",
    "PUBLIC_BASE_URL": "https://saltaemplea.com",
}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "PRUEBA-retiro.sqlite"
    db.init_db(path)
    conn = db.connect(path)
    yield conn
    conn.close()


def seed(conn, **changes):
    number = conn.execute("SELECT count(*) FROM jobs").fetchone()[0] + 1
    data = {
        **launch_cleanup.EXPECTED_FIELDS,
        "source_url": f"https://example.test/PRUEBA/{number}",
        "source_name": "PRUEBA propia aislada",
        "application_url": f"https://example.test/PRUEBA/postular/{number}",
        "original_text": "PRUEBA ficticia: no publicar en producción.",
    }
    data.update(changes)
    job_id, _ = domain.create_job(conn, data, "administrador")
    domain.transition_job(conn, job_id, "approve", "administrador", acknowledge=True)
    return job_id


def retirement_count(conn):
    return conn.execute("SELECT count(*) FROM audit WHERE actor='titular_autorizo_retiro'").fetchone()[0]


def test_archiva_solo_prueba_conserva_original_y_oferta_real(database):
    test_id = seed(database)
    real_id = seed(database, title="PRUEBA de vacante real", company="Empresa de ejemplo",
                   description="Descripción respaldada por fuente ficticia.")
    assert test_id == launch_cleanup.JOB_ID
    before = dict(database.execute("SELECT * FROM jobs WHERE id=?", (test_id,)).fetchone())
    real_before = dict(database.execute("SELECT * FROM jobs WHERE id=?", (real_id,)).fetchone())
    provenance_before = [dict(row) for row in database.execute("SELECT * FROM provenance ORDER BY id")]

    assert launch_cleanup.retire_known_test_offer(database, ENABLED) == {
        "status": "archived", "archived": 1, "job_id": test_id,
    }

    after = dict(database.execute("SELECT * FROM jobs WHERE id=?", (test_id,)).fetchone())
    assert after["status"] == "archived"
    assert after["approved_at"] is None and after["approved_by"] is None
    assert after["review_needed"] == 0
    for key in before.keys() - {"status", "approved_at", "approved_by", "review_needed", "updated_at"}:
        assert after[key] == before[key]
    assert dict(database.execute("SELECT * FROM jobs WHERE id=?", (real_id,)).fetchone()) == real_before
    assert [dict(row) for row in database.execute("SELECT * FROM provenance ORDER BY id")] == provenance_before
    assert [row["id"] for row in domain.public_jobs(database)] == [real_id]
    audit = database.execute("SELECT * FROM audit WHERE actor='titular_autorizo_retiro'").fetchone()
    assert audit["action"] == "archive" and audit["entity_id"] == test_id
    assert json.loads(audit["detail"]) == {
        "previous_status": "approved",
        "reason": "retiro_aviso_prueba_autorizado_por_titular",
        "authorization_date": "2026-10-20",
        "operation": launch_cleanup.SETTING_KEY,
    }
    assert database.execute("SELECT count(*) FROM settings WHERE key=?", (launch_cleanup.SETTING_KEY,)).fetchone()[0] == 1


def test_reintento_no_duplica_auditoria_ni_retira_una_decision_posterior(database):
    seed(database)
    launch_cleanup.retire_known_test_offer(database, ENABLED)
    domain.transition_job(database, 1, "approve", "administrador", acknowledge=True)
    assert launch_cleanup.retire_known_test_offer(database, ENABLED)["status"] == "already_applied"
    assert retirement_count(database) == 1
    assert database.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0] == "approved"


@pytest.mark.parametrize("key,value,status", [
    ("RETIRE_KNOWN_TEST_OFFER", None, "disabled"),
    ("RETIRE_KNOWN_TEST_OFFER", "0", "disabled"),
    ("RETIRE_KNOWN_TEST_OFFER", "true", "disabled"),
    ("RETIRE_KNOWN_TEST_OFFER", 1, "disabled"),
    ("VERCEL_ENV", "preview", "not_production"),
    ("VERCEL_ENV", "production ", "not_production"),
    ("PUBLIC_BASE_URL", "https://example.test", "wrong_origin"),
    ("PUBLIC_BASE_URL", "https://saltaemplea.com/", "wrong_origin"),
])
def test_guardas_exactas_no_acceden_a_base(key, value, status):
    class UnusedConnection:
        def __getattr__(self, _name):
            pytest.fail("La operación deshabilitada no debe acceder a la base.")

    assert launch_cleanup.retire_known_test_offer(UnusedConnection(), ENABLED | {key: value}) == {
        "status": status, "archived": 0, "job_id": 1,
    }


@pytest.mark.parametrize("field", launch_cleanup.EXPECTED_FIELDS)
def test_cualquier_dato_modificado_impide_retiro(database, field):
    seed(database, **{field: "Texto corregido por el titular"})
    before = dict(database.execute("SELECT * FROM jobs WHERE id=1").fetchone())
    assert launch_cleanup.retire_known_test_offer(database, ENABLED)["status"] == "identity_mismatch"
    assert dict(database.execute("SELECT * FROM jobs WHERE id=1").fetchone()) == before
    assert retirement_count(database) == 0
    assert database.execute("SELECT count(*) FROM settings WHERE key=?", (launch_cleanup.SETTING_KEY,)).fetchone()[0] == 0


def test_oferta_ausente_no_busca_otras_coincidencias(database):
    assert launch_cleanup.retire_known_test_offer(database, ENABLED)["status"] == "not_found"
    assert retirement_count(database) == 0


@pytest.mark.parametrize("action", ["archive", "expire", "reject"])
def test_oferta_ya_privada_no_se_modifica(database, action):
    seed(database)
    domain.transition_job(database, 1, action, "administrador")
    before = dict(database.execute("SELECT * FROM jobs WHERE id=1").fetchone())
    assert launch_cleanup.retire_known_test_offer(database, ENABLED)["status"] == "not_public"
    assert dict(database.execute("SELECT * FROM jobs WHERE id=1").fetchone()) == before
    assert retirement_count(database) == 0


@pytest.mark.parametrize("table,condition", [
    ("settings", "NEW.key='launch_cleanup:known_test_offer_1:v1'"),
    ("audit", "NEW.actor='titular_autorizo_retiro'"),
])
def test_fallo_revierte_retiro_auditoria_y_marcador(database, table, condition):
    seed(database)
    with database:
        database.execute(f"CREATE TEMP TRIGGER fail_cleanup BEFORE INSERT ON {table} "
                         f"WHEN {condition} BEGIN SELECT RAISE(ABORT,'fallo local PRUEBA'); END")
    before = dict(database.execute("SELECT * FROM jobs WHERE id=1").fetchone())
    with pytest.raises(sqlite3.IntegrityError):
        launch_cleanup.retire_known_test_offer(database, ENABLED)
    assert dict(database.execute("SELECT * FROM jobs WHERE id=1").fetchone()) == before
    assert retirement_count(database) == 0
    assert database.execute("SELECT count(*) FROM settings WHERE key=?", (launch_cleanup.SETTING_KEY,)).fetchone()[0] == 0
    assert not database.in_transaction


def test_transaccion_externa_conserva_control_del_llamador(database):
    seed(database)
    database.execute("BEGIN IMMEDIATE")
    assert launch_cleanup.retire_known_test_offer(database, ENABLED)["status"] == "archived"
    assert database.in_transaction
    database.rollback()
    assert database.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0] == "approved"
    assert retirement_count(database) == 0
    assert database.execute("SELECT count(*) FROM settings WHERE key=?", (launch_cleanup.SETTING_KEY,)).fetchone()[0] == 0


def test_resultado_y_auditoria_no_copian_variables_ajenas(database):
    seed(database)
    result = launch_cleanup.retire_known_test_offer(database, ENABLED | {
        "RESEND_API_KEY": "secreto-ficticio-no-persistir", "DATABASE_URL": "otro-secreto-ficticio",
    })
    serialized = json.dumps(result) + json.dumps([dict(row) for row in database.execute("SELECT * FROM settings")])
    serialized += json.dumps([dict(row) for row in database.execute("SELECT * FROM audit")])
    assert "secreto-ficticio" not in serialized


@pytest.fixture
def postgres(monkeypatch):
    target = os.environ.get("POSTGRES_TEST_URL")
    if not target:
        pytest.skip("POSTGRES_TEST_URL no configurada; requiere PostgreSQL aislado")
    pytest.importorskip("psycopg")
    from psycopg import sql

    original_connect = db.connect
    schema = "salta_launch_cleanup_" + secrets.token_hex(8)
    admin = original_connect(target)
    admin._connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    connections = []

    def scoped_connect(url):
        connection = original_connect(url)
        if db.is_postgres(url):
            connection._connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connections.append(connection)
        return connection

    monkeypatch.setattr(db, "connect", scoped_connect)
    try:
        db.init_db(target)
        yield scoped_connect(target)
    finally:
        for connection in connections:
            connection.close()
        admin._connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def test_postgres_archiva_conserva_real_y_reintento_no_duplica(postgres):
    seed(postgres)
    real_id = seed(postgres, title="PRUEBA real aislada", company="Otra empresa")
    real_before = dict(postgres.execute("SELECT * FROM jobs WHERE id=?", (real_id,)).fetchone())
    assert launch_cleanup.retire_known_test_offer(postgres, ENABLED)["status"] == "archived"
    assert postgres.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0] == "archived"
    assert dict(postgres.execute("SELECT * FROM jobs WHERE id=?", (real_id,)).fetchone()) == real_before
    assert launch_cleanup.retire_known_test_offer(postgres, ENABLED)["status"] == "already_applied"
    assert retirement_count(postgres) == 1


def test_postgres_no_retira_si_se_corrigio_la_identidad(postgres):
    seed(postgres, company="Empresa corregida por el titular")
    before = dict(postgres.execute("SELECT * FROM jobs WHERE id=1").fetchone())
    assert launch_cleanup.retire_known_test_offer(postgres, ENABLED)["status"] == "identity_mismatch"
    assert dict(postgres.execute("SELECT * FROM jobs WHERE id=1").fetchone()) == before
    assert retirement_count(postgres) == 0
    assert postgres.execute("SELECT count(*) FROM settings WHERE key=?", (launch_cleanup.SETTING_KEY,)).fetchone()[0] == 0


def test_postgres_fallo_marcador_revierte_retiro_y_auditoria(postgres):
    import psycopg

    seed(postgres)
    with postgres:
        postgres.executescript("""
            CREATE FUNCTION fail_cleanup_marker() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'fallo local PRUEBA';
            END;
            $$;
            CREATE TRIGGER fail_cleanup_marker BEFORE INSERT ON settings
                FOR EACH ROW WHEN (NEW.key='launch_cleanup:known_test_offer_1:v1')
                EXECUTE FUNCTION fail_cleanup_marker();
        """)
    before = dict(postgres.execute("SELECT * FROM jobs WHERE id=1").fetchone())
    with pytest.raises(psycopg.Error):
        launch_cleanup.retire_known_test_offer(postgres, ENABLED)
    assert dict(postgres.execute("SELECT * FROM jobs WHERE id=1").fetchone()) == before
    assert retirement_count(postgres) == 0
    assert postgres.execute("SELECT count(*) FROM settings WHERE key=?", (launch_cleanup.SETTING_KEY,)).fetchone()[0] == 0
    assert not postgres.in_transaction
