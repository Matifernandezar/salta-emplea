"""Retiro acotado y reversible de un aviso de prueba autorizado por el titular.

No ofrece una API pública ni elimina registros. El build debe habilitar esta
operación expresamente; una coincidencia parcial nunca autoriza el retiro.
"""

import json
from contextlib import contextmanager

from . import db, domain


SETTING_KEY = "launch_cleanup:known_test_offer_1:v1"
JOB_ID = 1
EXPECTED_FIELDS = {
    "title": "Prueba 1",
    "company": "Prueba 2",
    "description": "Dllcfkf",
    "requirements": "Grfgfdf",
    "location": "Salta",
}


@contextmanager
def _transaction(conn):
    nested = conn.in_transaction
    if nested:
        conn.execute("SAVEPOINT launch_cleanup_transaction")
    else:
        conn.execute("BEGIN IMMEDIATE")
    try:
        db.editorial_lock(conn)
        yield
    except Exception:
        if nested:
            conn.execute("ROLLBACK TO SAVEPOINT launch_cleanup_transaction")
            conn.execute("RELEASE SAVEPOINT launch_cleanup_transaction")
        else:
            conn.rollback()
        raise
    else:
        if nested:
            conn.execute("RELEASE SAVEPOINT launch_cleanup_transaction")
        else:
            conn.commit()


def _result(status, archived=0):
    return {"status": status, "archived": archived, "job_id": JOB_ID}


def retire_known_test_offer(conn, environment):
    """Archiva solo la identidad exacta revisada el 20/10/2026, una sola vez.

    El marcador y la auditoría se confirman junto al retiro. Las guardas de entorno
    se evalúan antes de acceder a la base. El resultado no contiene datos del aviso
    ni valores de configuración que puedan filtrarse en los logs del build.
    """
    if environment.get("RETIRE_KNOWN_TEST_OFFER") != "1":
        return _result("disabled")
    if environment.get("VERCEL_ENV") != "production":
        return _result("not_production")
    if environment.get("PUBLIC_BASE_URL") != "https://saltaemplea.com":
        return _result("wrong_origin")

    with _transaction(conn):
        if conn.execute("SELECT 1 FROM settings WHERE key=?", (SETTING_KEY,)).fetchone():
            return _result("already_applied")
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (JOB_ID,)).fetchone()
        if job is None:
            return _result("not_found")
        if any(job[field] != expected for field, expected in EXPECTED_FIELDS.items()):
            return _result("identity_mismatch")
        if job["status"] != "approved":
            return _result("not_public")

        stamp = domain.now()
        conn.execute(
            "UPDATE jobs SET status='archived',approved_at=NULL,approved_by=NULL,"
            "review_needed=0,updated_at=? WHERE id=?",
            (stamp, JOB_ID),
        )
        detail = {
            "previous_status": job["status"],
            "reason": "retiro_aviso_prueba_autorizado_por_titular",
            "authorization_date": "2026-10-20",
            "operation": SETTING_KEY,
        }
        conn.execute(
            "INSERT INTO audit(actor,action,entity_id,detail,created_at) "
            "VALUES ('titular_autorizo_retiro','archive',?,?,?)",
            (JOB_ID, json.dumps(detail, sort_keys=True), stamp),
        )
        conn.execute(
            "INSERT INTO settings(key,value) VALUES (?,?)",
            (SETTING_KEY, json.dumps({"job_id": JOB_ID, "archived_at": stamp}, sort_keys=True)),
        )
    return _result("archived", 1)
