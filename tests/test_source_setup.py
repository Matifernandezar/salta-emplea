"""Configuración de fuentes sin red, ofertas ni aprobaciones reales."""

import json
import os
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from salta_emplea import db, source_setup


ENABLED = {"ENABLE_JOBICY_SOURCE": "1", "VERCEL_ENV": "production"}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "source-setup.sqlite"
    db.init_db(path)
    conn = db.connect(path)
    yield conn
    conn.close()


@pytest.mark.parametrize("flag", [None, "", "0", "true", "01", " 1", 1, True])
def test_solo_flag_exacto_habilita_sin_tocar_base(flag):
    class UnusedConnection:
        def __getattr__(self, _name):
            pytest.fail("La configuración deshabilitada no debe tocar la base.")

    assert source_setup.configure_authorized_source(UnusedConnection(), {
        "ENABLE_JOBICY_SOURCE": flag, "VERCEL_ENV": "production",
    }) == {"status": "disabled", "created": 0, "existing": 0}


@pytest.mark.parametrize("environment", [None, "", "preview", "development", "Production", "production "])
def test_preview_desarrollo_y_entorno_ausente_no_tocan_base(environment):
    class UnusedConnection:
        def __getattr__(self, _name):
            pytest.fail("Un entorno distinto a producción no debe tocar la base.")

    assert source_setup.configure_authorized_source(UnusedConnection(), {
        "ENABLE_JOBICY_SOURCE": "1", "VERCEL_ENV": environment,
    }) == {"status": "not_production", "created": 0, "existing": 0}


def _assert_new_source(conn):
    result = source_setup.configure_authorized_source(conn, ENABLED)
    assert result["status"] == "created"
    assert result["created"] == 1 and result["existing"] == 0
    assert type(result["source_id"]) is int
    row = conn.execute("SELECT * FROM sources").fetchone()
    assert row["id"] == result["source_id"]
    assert row["name"] == "Remotos compatibles"
    assert row["url"] == "https://jobicy.com/api/v2/remote-jobs"
    assert row["method"] == "jobicy"
    assert row["frequency_hours"] == 6
    assert row["status"] == "active" and row["authorized"] == 1
    assert row["terms_url"] == "https://jobicy.com/jobs-rss-feed"
    assert row["terms_checked_at"]
    assert row["last_result"] is None and row["last_run_at"] is None
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM provenance").fetchone()[0] == 0
    event = conn.execute("SELECT * FROM audit").fetchone()
    assert event["actor"] == "configuracion_titular"
    assert event["action"] == "fuente_autorizada"
    assert event["entity_id"] == result["source_id"]
    detail = json.loads(event["detail"])
    assert detail == {"status": "created", "created": 1, "existing": 0,
                      "source_url": source_setup.JOBICY_URL, "terms_url": source_setup.JOBICY_TERMS_URL,
                      "authorization_date": "2026-10-19", "terms_review_date": "2026-10-19"}
    # Los valores de entorno ajenos no se persisten como detalle de auditoría.
    assert "secreto" not in json.dumps(detail)
    return result["source_id"]


def test_crea_fuente_declarativa_sin_recopilar_ofertas_y_audita_autorizacion(database):
    _assert_new_source(database)


def _assert_no_reactivation(conn):
    source_id = _assert_new_source(conn)
    with conn:
        conn.execute("UPDATE sources SET status='disabled',authorized=0,frequency_hours=24,name='Decisión editorial' WHERE id=?", (source_id,))
    before = dict(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())
    assert source_setup.configure_authorized_source(conn, ENABLED) == {"status": "already_configured", "created": 0, "existing": 0}
    assert dict(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()) == before
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM audit WHERE action='fuente_autorizada'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM settings WHERE key=?", (source_setup.SETTING_KEY,)).fetchone()[0] == 1


def test_nuevo_despliegue_no_reactiva_ni_sobrescribe_decisiones_editoriales(database):
    _assert_no_reactivation(database)


@pytest.mark.parametrize("url", [source_setup.JOBICY_URL, source_setup.JOBICY_URL + "/",
                                 source_setup.JOBICY_URL + "?count=100", "http://jobicy.com/api/v2/remote-jobs",
                                 "https://www.jobicy.com/api/v2/remote-jobs"])
def test_referencia_existente_se_preserva_completa_y_requiere_revision(database, url):
    with database:
        database.execute(
            "INSERT INTO sources(name,url,method,frequency_hours,status,last_result,last_run_at,terms_url,terms_checked_at,authorized) "
            "VALUES ('Referencia previa',?,'manual',24,'disabled','No consultada','2026-10-01',?,NULL,0)",
            (url, "https://example.test/condiciones-previas"),
        )
    before = dict(database.execute("SELECT * FROM sources").fetchone())
    assert source_setup.configure_authorized_source(database, ENABLED) == {"status": "existing_requires_review", "created": 0, "existing": 1}
    assert dict(database.execute("SELECT * FROM sources").fetchone()) == before
    assert source_setup.configure_authorized_source(database, ENABLED)["status"] == "already_configured"
    assert dict(database.execute("SELECT * FROM sources").fetchone()) == before
    detail = json.loads(database.execute("SELECT detail FROM audit WHERE action='fuente_autorizada'").fetchone()[0])
    assert detail["status"] == "existing_requires_review"


def test_referencias_duplicadas_existentes_no_se_modifican_o_fusionan(database):
    with database:
        for name, method, status, authorized in (("Manual", "manual", "disabled", 0), ("Activa", "jobicy", "active", 1)):
            database.execute(
                "INSERT INTO sources(name,url,method,status,authorized) VALUES (?,?,?,?,?)",
                (name, source_setup.JOBICY_URL, method, status, authorized),
            )
    before = [dict(row) for row in database.execute("SELECT * FROM sources ORDER BY id")]
    assert source_setup.configure_authorized_source(database, ENABLED)["existing"] == 2
    assert [dict(row) for row in database.execute("SELECT * FROM sources ORDER BY id")] == before


def test_fuentes_ajenas_no_se_modifican_y_variables_privadas_no_se_guardan(database):
    with database:
        database.execute("INSERT INTO sources(name,url) VALUES ('Otra','https://example.test/fuente')")
    before = dict(database.execute("SELECT * FROM sources").fetchone())
    result = source_setup.configure_authorized_source(database, ENABLED | {"RESEND_API_KEY": "secreto-ficticio", "DATABASE_URL": "no registrar"})
    assert result["created"] == 1
    assert dict(database.execute("SELECT * FROM sources WHERE id=?", (before["id"],)).fetchone()) == before
    data = json.dumps([dict(row) for row in database.execute("SELECT * FROM settings")])
    data += json.dumps([dict(row) for row in database.execute("SELECT * FROM audit")])
    assert "secreto-ficticio" not in data and "no registrar" not in data


def test_marker_existente_no_recrea_fuente_borrada_o_corregida(database):
    _assert_new_source(database)
    with database:
        database.execute("DELETE FROM sources")
    assert source_setup.configure_authorized_source(database, ENABLED)["status"] == "already_configured"
    assert database.execute("SELECT count(*) FROM sources").fetchone()[0] == 0


def test_fallo_al_auditar_revierte_fuente_y_marker(database):
    with database:
        database.execute(
            "CREATE TEMP TRIGGER fail_source_audit BEFORE INSERT ON audit "
            "WHEN NEW.action='fuente_autorizada' BEGIN SELECT RAISE(ABORT,'fallo local'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        source_setup.configure_authorized_source(database, ENABLED)
    assert database.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
    assert database.execute("SELECT count(*) FROM settings WHERE key=?", (source_setup.SETTING_KEY,)).fetchone()[0] == 0
    assert not database.in_transaction


def test_respeta_transaccion_del_llamador_y_su_rollback(database):
    database.execute("BEGIN IMMEDIATE")
    assert source_setup.configure_authorized_source(database, ENABLED)["created"] == 1
    assert database.in_transaction
    database.rollback()
    assert database.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
    assert database.execute("SELECT count(*) FROM settings WHERE key=?", (source_setup.SETTING_KEY,)).fetchone()[0] == 0


def _assert_concurrent(factory):
    ready = Barrier(2)

    def worker():
        conn = factory()
        try:
            ready.wait(timeout=5)
            return source_setup.configure_authorized_source(conn, ENABLED)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: worker(), range(2)))
    assert sorted(result["status"] for result in results) == ["already_configured", "created"]
    conn = factory()
    try:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM settings WHERE key=?", (source_setup.SETTING_KEY,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM audit WHERE action='fuente_autorizada'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    finally:
        conn.close()


def test_dos_despliegues_sqlite_simultaneos_crean_solo_una_fuente(database):
    path = database.execute("PRAGMA database_list").fetchone()[2]
    _assert_concurrent(lambda: db.connect(path))


@pytest.fixture
def postgres(monkeypatch):
    target = os.environ.get("POSTGRES_TEST_URL")
    if not target:
        pytest.skip("POSTGRES_TEST_URL no configurada; requiere PostgreSQL real")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    original_connect = db.connect
    schema = "salta_source_setup_" + secrets.token_hex(8)
    admin = original_connect(target)
    admin._connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    connections = []

    def scoped_connect(url):
        conn = original_connect(url)
        if db.is_postgres(url):
            conn._connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connections.append(conn)
        return conn

    monkeypatch.setattr(db, "connect", scoped_connect)
    try:
        db.init_db(target)
        yield lambda: scoped_connect(target)
    finally:
        for conn in connections:
            conn.close()
        admin._connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def test_dos_despliegues_postgres_simultaneos_crean_solo_una_fuente(postgres):
    _assert_concurrent(postgres)


def test_postgres_no_reactiva_fuente_pausada_por_el_titular(postgres):
    conn = postgres()
    _assert_no_reactivation(conn)
