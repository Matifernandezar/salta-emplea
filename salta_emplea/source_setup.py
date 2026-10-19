"""Registro declarativo de la primera fuente autorizada por el titular.

No consulta proveedores, recopila ofertas ni aprueba publicaciones. El marcador
persistente impide que un nuevo despliegue reemplace decisiones del administrador.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import db


JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_TERMS_URL = "https://jobicy.com/jobs-rss-feed"
AUTHORIZATION_DATE = "2026-10-19"
TERMS_REVIEW_DATE = "2026-10-19"
SETTING_KEY = "source_setup:jobicy:v1"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _transaction(conn):
    nested = conn.in_transaction
    if nested:
        conn.execute("SAVEPOINT source_setup_transaction")
    else:
        conn.execute("BEGIN IMMEDIATE")
    try:
        db.editorial_lock(conn)
        yield
    except Exception:
        if nested:
            conn.execute("ROLLBACK TO SAVEPOINT source_setup_transaction")
            conn.execute("RELEASE SAVEPOINT source_setup_transaction")
        else:
            conn.rollback()
        raise
    else:
        if nested:
            conn.execute("RELEASE SAVEPOINT source_setup_transaction")
        else:
            conn.commit()


def _same_endpoint(value):
    """Una referencia equivalente requiere revisión; nunca reescribir su URL."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme.lower() in {"http", "https"}
                and (parsed.hostname or "").lower().rstrip(".") in {"jobicy.com", "www.jobicy.com"}
                and parsed.path.rstrip("/") == "/api/v2/remote-jobs")
    except ValueError:
        return False


def configure_authorized_source(conn, environment):
    """Aplicar una sola vez la autorización declarativa, solo en producción.

    El flag debe ser exactamente ``"1"`` y VERCEL_ENV ``"production"``. Estos
    nombres no son secretos. Una referencia previa se conserva por completo,
    aunque estuviera pausada, sin autorización o con un método distinto.
    """
    if environment.get("ENABLE_JOBICY_SOURCE") != "1":
        return {"status": "disabled", "created": 0, "existing": 0}
    if environment.get("VERCEL_ENV") != "production":
        return {"status": "not_production", "created": 0, "existing": 0}
    with _transaction(conn):
        if conn.execute("SELECT 1 FROM settings WHERE key=?", (SETTING_KEY,)).fetchone():
            return {"status": "already_configured", "created": 0, "existing": 0}
        existing = [row for row in conn.execute("SELECT id,url FROM sources ORDER BY id")
                    if _same_endpoint(row["url"])]
        stamp = _now()
        if existing:
            result = {"status": "existing_requires_review", "created": 0, "existing": len(existing)}
            source_id = existing[0]["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO sources(name,url,method,frequency_hours,status,terms_url,terms_checked_at,authorized) "
                "VALUES (?,?, 'jobicy',6,'active',?,?,1)",
                ("Remotos compatibles", JOBICY_URL, JOBICY_TERMS_URL, stamp),
            )
            source_id = cursor.lastrowid
            result = {"status": "created", "created": 1, "existing": 0, "source_id": source_id}
        detail = {"status": result["status"], "created": result["created"], "existing": result["existing"],
                  "source_url": JOBICY_URL, "terms_url": JOBICY_TERMS_URL,
                  "authorization_date": AUTHORIZATION_DATE, "terms_review_date": TERMS_REVIEW_DATE}
        conn.execute(
            "INSERT INTO settings(key,value) VALUES (?,?)",
            (SETTING_KEY, json.dumps({**result, "source_id": source_id, "configured_at": stamp}, sort_keys=True)),
        )
        conn.execute(
            "INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES ('configuracion_titular','fuente_autorizada',?,?,?)",
            (source_id, json.dumps(detail, sort_keys=True), stamp),
        )
    return result
