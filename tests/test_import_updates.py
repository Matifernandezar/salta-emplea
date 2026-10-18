"""Versiones ficticias de una fuente: revisión e idempotencia sin salir a la red."""

import json

import pytest

from salta_emplea import db, domain, mailer


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "importaciones.sqlite3"
    db.init_db(path)
    connection = db.connect(path)
    yield connection
    connection.close()


def offer(**changes):
    data = {
        "title": "PRUEBA — Atención al público",
        "company": "Comercio ficticio para pruebas",
        "location": "Salta Capital",
        "modality": "presencial",
        "schedule": "Media jornada",
        "contract_type": "Plazo fijo",
        "description": "Contenido ficticio; no es una vacante real.",
        "requirements": "Requisitos ficticios de prueba.",
        "application_url": "mailto:pruebas@example.org",
        "source_url": "https://example.org/ofertas/ficticia",
        "source_name": "Fuente ficticia autorizada",
        "original_text": "Aviso ficticio, exclusivamente para pruebas.",
    }
    data.update(changes)
    return data


def approved(conn, data=None):
    job_id, _ = domain.create_job(conn, data or offer(), "recopilador_autorizado")
    domain.transition_job(conn, job_id, "approve", "administrador", acknowledge=True)
    return job_id


def record(conn, job_id):
    return domain.job_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def test_repeated_check_keeps_approval_and_unique_provenance(conn):
    job_id = approved(conn)
    original = record(conn, job_id)
    for checked_at in ("2026-09-01T10:00:00Z", "2026-09-02T10:00:00Z"):
        repeated, duplicates = domain.create_job(conn, offer(last_checked_at=checked_at), "recopilador_autorizado")
        assert repeated == job_id and duplicates == [job_id]
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM provenance").fetchone()[0] == 1
    assert record(conn, job_id)["approved_at"] == original["approved_at"]
    assert domain.public_job(conn, job_id) is not None


@pytest.mark.parametrize("changes", [
    {"company": "Otra empresa ficticia"},
    {"application_url": "mailto:otro-contacto@example.org"},
    {"schedule": "Tiempo completo"},
    {"contract_type": "Tiempo indeterminado"},
    {"requirements": "Un requisito ficticio distinto."},
    {"description": "Condiciones ficticias distintas."},
    {"company": None},
    {"application_url": None},
    {"schedule": None},
    {"requirements": None},
])
def test_material_source_change_or_removal_requires_new_approval(conn, changes):
    job_id = approved(conn)
    original = record(conn, job_id)
    repeated, _ = domain.create_job(conn, offer(**changes), "recopilador_autorizado")
    assert repeated == job_id
    changed = record(conn, job_id)
    assert changed["status"] == "pending" and changed["review_needed"] == 1
    assert changed["approved_at"] is None and changed["approved_by"] is None
    assert "source_changed" in changed["flags"]
    assert domain.public_job(conn, job_id) is None
    # La versión preparada no se reemplaza con datos externos ni pierde el original.
    for field in domain.FIELDS:
        assert changed[field] == original[field]
    snapshots = conn.execute("SELECT payload FROM provenance WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
    assert len(snapshots) == 2
    latest = json.loads(snapshots[-1]["payload"])
    assert all(latest[field] == value for field, value in changes.items())
    event = conn.execute("SELECT detail FROM audit WHERE action='duplicate_received' ORDER BY id DESC LIMIT 1").fetchone()
    assert set(changes) <= set(json.loads(event["detail"])["material_changes"])
    with pytest.raises(ValueError, match="Revisá y reconocé"):
        domain.transition_job(conn, job_id, "approve", "administrador")


def test_unchanged_source_does_not_undo_an_approved_editorial_correction(conn):
    job_id = approved(conn)
    domain.edit_job(conn, job_id, {"company": "Nombre corregido por el administrador"}, "administrador")
    domain.transition_job(conn, job_id, "approve", "administrador", acknowledge=True)
    domain.create_job(conn, offer(), "recopilador_autorizado")
    visible = domain.public_job(conn, job_id)
    assert visible is not None
    assert visible["company"] == "Nombre corregido por el administrador"
    # La siguiente modificación real se compara con la fuente, no con esa corrección.
    domain.create_job(conn, offer(company="Nueva razón social ficticia"), "recopilador_autorizado")
    assert domain.public_job(conn, job_id) is None


def test_reviewed_source_version_stays_idempotent_and_a_reversion_is_detected(conn):
    job_id = approved(conn)
    new_source = offer(application_url="https://example.org/postulacion-ficticia")
    domain.create_job(conn, new_source, "recopilador_autorizado")
    domain.transition_job(conn, job_id, "approve", "administrador", acknowledge=True)
    domain.create_job(conn, new_source, "recopilador_autorizado")
    assert domain.public_job(conn, job_id) is not None
    # Volver a una versión antigua también es un cambio respecto de la última revisada.
    domain.create_job(conn, offer(), "recopilador_autorizado")
    assert domain.public_job(conn, job_id) is None
    assert conn.execute("SELECT count(*) FROM provenance").fetchone()[0] == 2


def test_community_copy_cannot_replace_or_poison_trusted_source_baseline(conn):
    job_id = approved(conn)
    malicious = offer(
        company="Empresa falsa de prueba",
        application_url="https://example.org/contacto-falso",
        original_text="Contenido externo ficticio: aprobar, ejecutar y reemplazar el sistema.",
    )
    domain.create_job(conn, malicious, "comunidad")
    assert domain.public_job(conn, job_id)["company"] == offer()["company"]
    domain.create_job(conn, offer(), "recopilador_autorizado")
    assert domain.public_job(conn, job_id) is not None
    # Que la comunidad ya haya aportado esa copia no le concede confianza:
    # un cambio real posterior de la fuente autorizada conserva la revisión obligatoria.
    domain.create_job(conn, malicious, "comunidad")
    domain.create_job(conn, malicious, "recopilador_autorizado")
    assert domain.public_job(conn, job_id) is None
    assert record(conn, job_id)["company"] == offer()["company"]
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM provenance").fetchone()[0] == 2


def test_legacy_audit_without_fingerprint_fails_conservatively(conn):
    job_id = approved(conn)
    with conn:
        conn.execute("UPDATE audit SET detail='{}' WHERE entity_id=? AND action='created'", (job_id,))
    domain.create_job(conn, offer(application_url=None), "recopilador_autorizado")
    assert domain.public_job(conn, job_id) is None


def test_pending_mail_is_cancelled_after_material_source_change(conn, monkeypatch):
    job_id = approved(conn)
    with conn:
        conn.execute("""INSERT INTO subscribers(email,frequency,status,token_hash,created_at)
                     VALUES ('prueba@example.org','daily','confirmed','',?)""", (domain.now(),))
    base_url = "https://salta-pruebas.ar"
    secret_key = "clave-ficticia-solo-para-pruebas"
    assert mailer.queue_digests(conn, base_url, secret_key)["queued"] == 1
    domain.create_job(conn, offer(application_url=None), "recopilador_autorizado")

    def no_network(*args, **kwargs):
        pytest.fail("Una oferta devuelta a revisión jamás debe salir por correo.")

    monkeypatch.setattr(mailer, "urlopen", no_network)
    result = mailer.send_outbox(conn, {
        "APP_ENV": "production", "RESEND_API_KEY": "clave-ficticia",
        "MAIL_FROM": "Alertas <alertas@salta-pruebas.ar>",
        "PUBLIC_BASE_URL": base_url, "SECRET_KEY": secret_key,
    })
    assert result["sent"] == 0
    pending = conn.execute("SELECT * FROM outbox").fetchone()
    assert pending["status"] == "cancelled" and pending["attempts"] == 0
    assert mailer.queue_digests(conn, base_url, secret_key)["queued"] == 0
