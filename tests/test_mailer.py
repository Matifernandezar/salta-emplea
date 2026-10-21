"""Pruebas locales: el proveedor siempre está sustituido, no salen correos reales."""

import base64
import json
from datetime import timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from itsdangerous import TimestampSigner

from salta_emplea import mailer
from salta_emplea.db import connect, init_db
from salta_emplea.domain import create_job, transition_job


SECRET = "clave-de-pruebas-locales-sin-uso-en-produccion"
BASE_URL = "https://empleos.pruebas.ar"
WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"PRUEBA-secreto-webhook-aislado").decode("ascii")


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "test.sqlite"
    init_db(path)
    conn = connect(path)
    yield conn
    conn.close()


@pytest.fixture
def config():
    return {"APP_ENV": "production", "RESEND_API_KEY": "solo-prueba", "MAIL_FROM": "Alertas <alertas@pruebas.ar>",
            "PUBLIC_BASE_URL": BASE_URL, "SECRET_KEY": SECRET,
            "MAIL_ENABLED": "1", "RESEND_WEBHOOK_SECRET": WEBHOOK_SECRET}


def subscriber(conn, *, status="confirmed", **overrides):
    data = {"email": f"prueba-{conn.execute('SELECT count(*) FROM subscribers').fetchone()[0]}@pruebas.ar",
            "frequency": "daily", "status": status, "locality": None, "sector": None, "modality": None,
            "token_hash": "", "created_at": mailer._stamp()}
    data.update(overrides)
    columns = list(data)
    with conn:
        cursor = conn.execute(f"INSERT INTO subscribers({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                              [data[key] for key in columns])
    return cursor.lastrowid


def job(conn, *, approve=True, **overrides):
    data = {"title": "PRUEBA: Analista", "company": "Empresa de prueba", "location": "Salta Capital",
            "sector": "Tecnología", "modality": "presencial", "application_url": "mailto:rrhh@pruebas.ar"}
    data.update(overrides)
    job_id, _ = create_job(conn, data)
    if approve:
        transition_job(conn, job_id, "approve", "administrador de prueba", acknowledge=True)
    return job_id


def outbox(conn):
    return conn.execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 1").fetchone()


class Accepted:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return 200


def block_network(*args, **kwargs):
    pytest.fail("Esta prueba no permite acceso de red.")


def test_tokens_separan_confirmacion_y_baja_y_rechazan_firmas_invalidas():
    token = mailer.confirmation_token(3, SECRET)
    assert mailer.verify_token(token, SECRET, "confirm")[0] == 3
    assert mailer.verify_token(token, SECRET, "unsubscribe") is None
    assert mailer.verify_token(token + "x", SECRET, "confirm") is None
    assert mailer.verify_token(token, "otra-clave", "confirm") is None
    assert mailer.verify_token(mailer.unsubscribe_token(3, SECRET), SECRET, "unsubscribe", max_age=None)[0] == 3


def test_confirmacion_vencida_no_se_valida(monkeypatch):
    original = TimestampSigner.get_timestamp
    with monkeypatch.context() as patch:
        patch.setattr(TimestampSigner, "get_timestamp", lambda self: original(self) - mailer.CONFIRM_MAX_AGE - 10)
        token = mailer.confirmation_token(1, SECRET)
    assert mailer.verify_token(token, SECRET, "confirm") is None


def test_encolar_confirmacion_es_idempotente_y_no_activa_suscriptor(database):
    subscriber_id = subscriber(database, status="pending")
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["queued"] == 1
    item = outbox(database)
    token = item["body"].split("/alertas/confirmar/")[1].split("\n")[0]
    verified = mailer.verify_token(token, SECRET, "confirm")
    stored = database.execute("SELECT * FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()
    assert verified == (subscriber_id, stored["token_hash"])
    assert stored["status"] == "pending"
    assert token not in stored["token_hash"]
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["skipped"] == 1
    assert database.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    confirmed = subscriber(database)
    assert mailer.queue_confirmation(database, confirmed, BASE_URL, SECRET)["queued"] == 0


def test_repetir_solicitud_reemplaza_solo_confirmacion_vencida(database):
    subscriber_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)
    old_id = outbox(database)["id"]
    with database:
        database.execute("UPDATE outbox SET created_at=?", (mailer._stamp(mailer._now() - timedelta(days=3)),))
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["queued"] == 1
    assert database.execute("SELECT status FROM outbox WHERE id=?", (old_id,)).fetchone()[0] == "cancelled"
    assert outbox(database)["status"] == "pending"


def test_resumen_filtra_y_nunca_incluye_ofertas_no_aprobadas_o_vencidas(database):
    subscriber(database, locality="Salta Capital", sector="Tecnología", modality="presencial")
    subscriber(database, status="pending")
    wanted = job(database)
    job(database, approve=False, title="PRUEBA: Pendiente")
    job(database, title="PRUEBA: Otro lugar", location="Orán")
    job(database, title="PRUEBA: Otro rubro", sector="Comercio")
    job(database, title="PRUEBA: Otra modalidad", modality="remota")
    job(database, approve=False, title="PRUEBA: Vencida", expires_at=mailer._stamp(mailer._now() - timedelta(days=1)))
    assert mailer.queue_digests(database, BASE_URL, SECRET)["queued"] == 1
    assert json.loads(outbox(database)["job_ids"]) == [wanted]
    assert "Dar de baja:" in outbox(database)["body"]
    assert mailer.queue_digests(database, BASE_URL, SECRET)["queued"] == 0
    assert database.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1


@pytest.mark.parametrize("frequency,days", [("daily", 1), ("weekly", 7)])
def test_frecuencia_y_reservas_impiden_repetir_ofertas(database, monkeypatch, frequency, days):
    subscriber(database, frequency=frequency)
    first_job = job(database)
    initial = mailer._now()
    mailer.queue_digests(database, BASE_URL, SECRET)
    second_job = job(database, title="PRUEBA: Segundo")
    assert mailer.queue_digests(database, BASE_URL, SECRET)["queued"] == 0
    monkeypatch.setattr(mailer, "_now", lambda: initial + timedelta(days=days, seconds=2))
    assert mailer.queue_digests(database, BASE_URL, SECRET)["queued"] == 1
    assert json.loads(outbox(database)["job_ids"]) == [second_job]
    assert first_job != second_job
    assert mailer.queue_digests(database, BASE_URL, SECRET)["queued"] == 0


@pytest.mark.parametrize("override", [
    {"APP_ENV": "development"}, {"RESEND_API_KEY": ""}, {"MAIL_FROM": ""}, {"SECRET_KEY": ""},
    {"PUBLIC_BASE_URL": "http://empleos.pruebas.ar"}, {"PUBLIC_BASE_URL": "https://example.com"},
    {"PUBLIC_BASE_URL": "https://salta.test"}, {"PUBLIC_BASE_URL": "https://127.0.0.1"},
    {"PUBLIC_BASE_URL": "https://bad domain.ar"},
])
def test_sin_produccion_configurada_deja_cola_pendiente(database, config, monkeypatch, override):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    config.update(override)
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config) == {"queued": 0, "sent": 0, "skipped": 1, "errors": 0}
    assert outbox(database)["status"] == "pending"
    assert outbox(database)["attempts"] == 0


@pytest.mark.parametrize("override,key", [
    ({"MAIL_ENABLED": None}, "pausado"),
    ({"MAIL_ENABLED": "0"}, "pausado"),
    ({"MAIL_ENABLED": "true"}, "pausado"),
    ({"MAIL_ENABLED": " 1"}, "pausado"),
    ({"MAIL_ENABLED": 1}, "pausado"),
    ({"MAIL_ENABLED": True}, "pausado"),
    ({"RESEND_WEBHOOK_SECRET": ""}, "webhook"),
    ({"RESEND_WEBHOOK_SECRET": "whsec_no-es-base64"}, "webhook"),
    ({"RESEND_WEBHOOK_SECRET": "whsec_" + base64.b64encode(b"corto").decode("ascii")}, "webhook"),
    ({"MAIL_DAILY_LIMIT": "0"}, "limites"),
    ({"MAIL_MONTHLY_LIMIT": "0"}, "limites"),
    ({"MAIL_MONTHLY_LIMIT": "sin-limite"}, "limites"),
])
def test_activacion_incompleta_no_toca_cola_intentos_reservas_ni_suscriptores(
        database, config, monkeypatch, override, key):
    subscriber(database)
    pending_id = subscriber(database, status="pending")
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    mailer.queue_confirmation(database, pending_id, BASE_URL, SECRET)
    config.update(override)
    before = {
        table: [dict(row) for row in database.execute(f"SELECT * FROM {table} ORDER BY id")]
        for table in ("outbox", "subscribers", "audit")
    }
    monkeypatch.setattr(mailer, "urlopen", block_network)

    readiness = mailer.delivery_readiness(config)
    assert not readiness["ready"]
    assert key in {item["key"] for item in readiness["missing"]}
    result = mailer.send_outbox(database, config)

    assert result["sent"] == 0 and result["skipped"] == 2
    for table, rows in before.items():
        assert [dict(row) for row in database.execute(f"SELECT * FROM {table} ORDER BY id")] == rows
    assert mailer.quota_status(database, config)["daily"]["used"] == 0


def test_readiness_describe_solo_pendientes_fijos_sin_revelar_valores(config):
    config.update(
        MAIL_ENABLED="0", APP_ENV="desarrollo-privado", SECRET_KEY="",
        RESEND_API_KEY="", MAIL_FROM="remitente-privado-invalido",
        PUBLIC_BASE_URL="http://destino-privado-invalido", RESEND_WEBHOOK_SECRET="secreto-webhook-invalido",
        MAIL_DAILY_LIMIT=0,
    )
    result = mailer.delivery_readiness(config)
    assert not result["ready"]
    assert {item["key"] for item in result["missing"]} == {
        "pausado", "entorno", "url", "clave_app", "api", "remitente", "webhook", "limites",
    }
    serialized = json.dumps(result)
    assert all(str(value) not in serialized for key, value in config.items()
               if key in {"APP_ENV", "MAIL_FROM", "PUBLIC_BASE_URL", "RESEND_WEBHOOK_SECRET"})
    assert all(set(item) == {"key", "message"} for item in result["missing"])


def test_readiness_no_exige_una_consulta_al_proveedor_o_a_la_base(config, monkeypatch):
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.delivery_readiness(config) == {"ready": True, "missing": []}
    assert mailer._valid_delivery_config(config)
    del config["MAIL_ENABLED"]
    assert not mailer._valid_delivery_config(config)


@pytest.mark.parametrize("size,valid", [(15, False), (16, True), (64, True), (65, False)])
def test_secreto_webhook_respeta_el_mismo_limite_que_svix(config, size, valid):
    from salta_emplea.mail_webhooks import WebhookError, verify_signature

    config["RESEND_WEBHOOK_SECRET"] = "whsec_" + base64.b64encode(b"x" * size).decode("ascii")
    result = mailer.delivery_readiness(config)
    assert result["ready"] is valid
    assert ("webhook" in {item["key"] for item in result["missing"]}) is not valid
    with pytest.raises(WebhookError) as error:
        verify_signature(b"{}", {}, config["RESEND_WEBHOOK_SECRET"])
    assert error.value.code == ("invalid_signature" if valid else "not_configured")


def test_envio_real_mock_revalida_aprobacion_y_registra_solo_un_envio(database, config, monkeypatch):
    subscriber_id = subscriber(database)
    job(database)
    archived = job(database, title="PRUEBA: No debe enviarse")
    mailer.queue_digests(database, BASE_URL, SECRET)
    transition_job(database, archived, "archive", "administrador de prueba")
    requests = []

    def provider(request, timeout):
        requests.append(request)
        assert timeout == 15
        assert outbox(database)["status"] == "uncertain"
        assert outbox(database)["attempts"] == 1
        assert not database.in_transaction
        return Accepted()

    monkeypatch.setattr(mailer, "urlopen", provider)
    assert mailer.send_outbox(database, config)["sent"] == 1
    payload = json.loads(requests[0].data)
    assert "PRUEBA: Analista" in payload["text"]
    assert "PRUEBA: No debe enviarse" not in payload["text"]
    assert requests[0].full_url == "https://api.resend.com/emails"
    assert requests[0].get_header("User-agent") == "SaltaEmplea/1.0"
    assert requests[0].get_header("Accept") == "application/json"
    assert outbox(database)["status"] == "sent"
    assert database.execute("SELECT last_sent_at FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()[0]
    assert mailer.send_outbox(database, config)["sent"] == 0
    assert len(requests) == 1


def test_baja_antes_de_envio_cancela_sin_contactar_proveedor(database, config, monkeypatch):
    subscriber_id = subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    with database:
        database.execute("UPDATE subscribers SET status='unsubscribed' WHERE id=?", (subscriber_id,))
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["skipped"] == 1
    assert outbox(database)["status"] == "cancelled"


def test_todas_las_ofertas_retiradas_cancelan_resumen(database, config, monkeypatch):
    subscriber(database)
    job_id = job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    transition_job(database, job_id, "reject", "administrador de prueba")
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["skipped"] == 1
    assert outbox(database)["status"] == "cancelled"


def test_confirmacion_expirada_en_cola_no_se_envia(database, config, monkeypatch):
    subscriber_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)
    with database:
        database.execute("UPDATE outbox SET created_at=?", (mailer._stamp(mailer._now() - timedelta(days=3)),))
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["skipped"] == 1
    assert outbox(database)["status"] == "cancelled"


def test_confirmacion_revalidada_antes_de_enviar(database, config, monkeypatch):
    subscriber_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)
    monkeypatch.setattr(mailer, "urlopen", lambda request, timeout: Accepted())
    assert mailer.send_outbox(database, config)["sent"] == 1
    assert database.execute("SELECT status FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()[0] == "pending"


def test_rechazo_403_conserva_historial_y_causa_segura_sin_reintento(database, config, monkeypatch):
    subscriber_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)
    calls = []

    def rejected(request, timeout):
        calls.append(request)
        body = {"statusCode": 403, "name": "validation_error",
                "message": "The dominio-privado.test domain is not verified. dato-confidencial"}
        raise HTTPError(request.full_url, 403, "no registrar", {}, BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr(mailer, "urlopen", rejected)
    assert mailer.send_outbox(database, config)["errors"] == 1
    before = dict(outbox(database))
    assert before["status"] == "failed" and before["attempts"] == 1
    assert before["next_attempt_at"] is None
    assert "dominio del remitente no figura verificado" in before["last_error"]
    assert "dominio-privado" not in before["last_error"] and "dato-confidencial" not in before["last_error"]
    assert mailer.send_outbox(database, config)["sent"] == 0
    assert dict(outbox(database)) == before
    assert len(calls) == 1
    assert mailer.quota_status(database, config)["daily"]["used"] == 1


@pytest.mark.parametrize("code", [429, 500, 503])
def test_reintento_acotado_reutiliza_idempotencia(database, config, monkeypatch, code):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    requests = []

    def provider(request, timeout):
        requests.append(request)
        if len(requests) == 1:
            raise HTTPError(request.full_url, code, "fallo de prueba", {}, None)
        return Accepted()

    monkeypatch.setattr(mailer, "urlopen", provider)
    assert mailer.send_outbox(database, config)["errors"] == 1
    assert outbox(database)["status"] == "pending"
    assert outbox(database)["next_attempt_at"] > mailer._stamp()
    assert mailer.send_outbox(database, config)["sent"] == 0
    with database:
        database.execute("UPDATE outbox SET next_attempt_at=NULL")
    assert mailer.send_outbox(database, config)["sent"] == 1
    assert requests[0].get_header("Idempotency-key") == requests[1].get_header("Idempotency-key")
    assert requests[0].data == requests[1].data
    headers = json.loads(requests[0].data)['headers']
    assert headers['List-Unsubscribe'].startswith('<https://empleos.pruebas.ar/alertas/baja/')
    assert headers['List-Unsubscribe-Post'] == 'List-Unsubscribe=One-Click'
    assert outbox(database)["attempts"] == 2


def test_reintento_con_contenido_cambiado_se_detiene_para_revision(database, config, monkeypatch):
    subscriber(database)
    retained = job(database)
    withdrawn = job(database, title="PRUEBA: Segundo")
    mailer.queue_digests(database, BASE_URL, SECRET)

    def provider(request, timeout):
        raise HTTPError(request.full_url, 503, "fallo de prueba", {}, None)

    monkeypatch.setattr(mailer, "urlopen", provider)
    mailer.send_outbox(database, config)
    transition_job(database, withdrawn, "archive", "administrador de prueba")
    with database:
        database.execute("UPDATE outbox SET next_attempt_at=NULL")
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["skipped"] == 1
    assert outbox(database)["status"] == "cancelled"
    assert retained in json.loads(outbox(database)["job_ids"])


def test_tres_fallos_explicitos_agotan_reintentos(database, config, monkeypatch):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)

    def provider(request, timeout):
        raise HTTPError(request.full_url, 503, "fallo de prueba", {}, None)

    monkeypatch.setattr(mailer, "urlopen", provider)
    for _ in range(3):
        with database:
            database.execute("UPDATE outbox SET next_attempt_at=NULL")
        mailer.send_outbox(database, config)
    assert outbox(database)["status"] == "failed"
    assert outbox(database)["attempts"] == 3
    assert mailer.send_outbox(database, config)["sent"] == 0


@pytest.mark.parametrize("exception", [TimeoutError("timeout de prueba"), URLError("red de prueba")])
def test_timeout_es_incierto_y_nunca_reintenta_automaticamente(database, config, monkeypatch, exception):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    calls = []

    def provider(request, timeout):
        calls.append(request)
        raise exception

    monkeypatch.setattr(mailer, "urlopen", provider)
    assert mailer.send_outbox(database, config)["errors"] == 1
    assert outbox(database)["status"] == "uncertain"
    assert mailer.send_outbox(database, config)["sent"] == 0
    assert len(calls) == 1


def test_no_reintenta_fuera_de_ventana_del_proveedor(database, config, monkeypatch):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    with database:
        database.execute("UPDATE outbox SET attempts=1,first_attempt_at=?", (mailer._stamp(mailer._now() - timedelta(days=2)),))
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["errors"] == 1
    assert outbox(database)["status"] == "failed"


def test_segundo_trabajador_no_envia_intento_ya_reservado(database, config, monkeypatch):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    path = database.execute("PRAGMA database_list").fetchone()[2]
    second = connect(path)

    def provider(request, timeout):
        assert mailer.send_outbox(second, config) == {"queued": 0, "sent": 0, "skipped": 0, "errors": 0}
        return Accepted()

    monkeypatch.setattr(mailer, "urlopen", provider)
    try:
        assert mailer.send_outbox(database, config)["sent"] == 1
    finally:
        second.close()


def test_cola_acumulada_respeta_frecuencia_al_reanudar_envios(database, config, monkeypatch):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    with database:
        database.execute("UPDATE outbox SET created_at=?", (mailer._stamp(mailer._now() - timedelta(days=2)),))
    job(database, title="PRUEBA: Acumulada")
    mailer.queue_digests(database, BASE_URL, SECRET)
    monkeypatch.setattr(mailer, "urlopen", lambda request, timeout: Accepted())
    result = mailer.send_outbox(database, config)
    assert result["sent"] == 1
    assert result["skipped"] == 1
    assert outbox(database)["status"] == "pending"
    assert outbox(database)["attempts"] == 0
    assert outbox(database)["next_attempt_at"] > mailer._stamp()


def _small_quota(config, *, daily=100, monthly=3000, reserve_daily=0, reserve_monthly=0):
    config.update(MAIL_DAILY_LIMIT=daily, MAIL_MONTHLY_LIMIT=monthly,
                  MAIL_CONFIRMATION_RESERVE_DAILY=reserve_daily,
                  MAIL_CONFIRMATION_RESERVE_MONTHLY=reserve_monthly)


def test_cupo_diario_conserva_pendientes_sin_consumir_intentos(database, config, monkeypatch):
    for _ in range(3):
        subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    _small_quota(config, daily=2)
    calls = []
    monkeypatch.setattr(mailer, "urlopen", lambda request, timeout: calls.append(request) or Accepted())
    result = mailer.send_outbox(database, config)
    assert (result["sent"], result["skipped"], result["quota_reached"]) == (2, 1, True)
    assert len(calls) == 2
    assert outbox(database)["status"] == "pending"
    assert outbox(database)["attempts"] == 0
    assert mailer.send_outbox(database, config)["quota_reached"]
    assert len(calls) == 2
    status = mailer.quota_status(database, config)
    assert status["daily"]["used"] == 2
    assert status["monthly"]["used"] == 2
    reservations = database.execute("SELECT detail FROM audit WHERE action='mail_reserved'").fetchall()
    assert [row["detail"] for row in reservations] == ["digest", "digest"]


def test_cupo_mensual_no_se_reinicia_al_cambiar_el_dia(database, config, monkeypatch):
    from datetime import datetime, timezone

    instant = datetime(2026, 10, 10, 23, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(mailer, "_now", lambda: instant)
    for _ in range(2):
        subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    _small_quota(config, daily=1, monthly=1)
    calls = []
    monkeypatch.setattr(mailer, "urlopen", lambda request, timeout: calls.append(request) or Accepted())
    assert mailer.send_outbox(database, config)["sent"] == 1
    monkeypatch.setattr(mailer, "_now", lambda: instant + timedelta(minutes=2))
    assert mailer.quota_status(database, config)["daily"]["used"] == 0
    assert mailer.send_outbox(database, config)["quota_reached"]
    assert len(calls) == 1
    assert outbox(database)["attempts"] == 0
    monkeypatch.setattr(mailer, "_now", lambda: instant.replace(month=11, day=1))
    assert mailer.send_outbox(database, config)["sent"] == 1
    assert len(calls) == 2


def test_prioriza_confirmaciones_y_reserva_capacidad_que_no_usan_resumenes(database, config, monkeypatch):
    for _ in range(3):
        subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    pending_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, pending_id, BASE_URL, SECRET)
    _small_quota(config, daily=3, monthly=3, reserve_daily=2, reserve_monthly=2)
    calls = []
    monkeypatch.setattr(mailer, "urlopen", lambda request, timeout: calls.append(request) or Accepted())
    result = mailer.send_outbox(database, config)
    assert result["sent"] == 2
    assert result["quota_reached"]
    assert "Confirmá" in json.loads(calls[0].data)["subject"]
    assert "Nuevas ofertas" in json.loads(calls[1].data)["subject"]
    # Queda capacidad reservada para otra confirmación, no para un resumen.
    another_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, another_id, BASE_URL, SECRET)
    assert mailer.send_outbox(database, config)["sent"] == 1
    assert mailer.quota_status(database, config)["daily"]["used"] == 3
    assert len(calls) == 3


def test_fallo_explicito_cuenta_y_cupo_no_borra_reserva_ni_reintenta(database, config, monkeypatch):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    _small_quota(config, daily=1)
    calls = []

    def provider(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 503, "no registrar datos externos", {}, None)

    monkeypatch.setattr(mailer, "urlopen", provider)
    assert mailer.send_outbox(database, config)["errors"] == 1
    with database:
        database.execute("UPDATE outbox SET next_attempt_at=NULL")
    assert mailer.send_outbox(database, config)["quota_reached"]
    assert len(calls) == 1
    assert outbox(database)["status"] == "pending"
    assert outbox(database)["attempts"] == 1
    assert mailer.quota_status(database, config)["daily"]["used"] == 1


def test_cupo_se_reserva_antes_de_red_y_serializa_trabajadores(database, config, monkeypatch):
    for _ in range(2):
        subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    _small_quota(config, daily=1)
    second = connect(database.execute("PRAGMA database_list").fetchone()[2])
    calls = []

    def provider(request, timeout):
        calls.append(request)
        assert mailer.quota_status(second, config)["daily"]["used"] == 1
        assert mailer.send_outbox(second, config)["quota_reached"]
        return Accepted()

    monkeypatch.setattr(mailer, "urlopen", provider)
    try:
        assert mailer.send_outbox(database, config)["sent"] == 1
        assert len(calls) == 1
        assert outbox(database)["attempts"] == 0
    finally:
        second.close()


@pytest.mark.parametrize("limit", [0, -1, "sin límite", "1.5", None, True])
def test_limite_invalido_o_cero_no_envia(database, config, monkeypatch, limit):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    _small_quota(config, daily=limit)
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["quota_reached"]
    assert outbox(database)["status"] == "pending"
    assert outbox(database)["attempts"] == 0


@pytest.mark.parametrize("sender", ["onboarding@resend.dev", "Alertas <x@sub.resend.dev>",
                                   "x@example.com", "x@pruebas.test"])
def test_remitente_de_pruebas_no_se_presenta_como_produccion(database, config, monkeypatch, sender):
    subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    config["MAIL_FROM"] = sender
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["skipped"] == 1
    assert mailer.quota_status(database, config)["daily"]["used"] == 0


def test_supresion_persistente_impide_reactivacion_por_nueva_solicitud(database, config, monkeypatch):
    subscriber_id = subscriber(database, status="pending")
    row = database.execute("SELECT email FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()
    with database:
        database.execute("INSERT INTO settings(key,value) VALUES (?,?)", (mailer.suppression_key(row["email"]), "{}"))
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["skipped"] == 1
    assert database.execute("SELECT status FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()[0] == "unsubscribed"
    assert database.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0


def test_supresion_posterior_a_cola_cancela_antes_de_reservar_cupo(database, config, monkeypatch):
    subscriber_id = subscriber(database)
    job(database)
    mailer.queue_digests(database, BASE_URL, SECRET)
    row = database.execute("SELECT email FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()
    with database:
        database.execute("INSERT INTO settings(key,value) VALUES (?,?)", (mailer.suppression_key(row["email"]), "{}"))
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["skipped"] == 1
    assert outbox(database)["status"] == "cancelled"
    assert outbox(database)["attempts"] == 0
    assert mailer.quota_status(database, config)["daily"]["used"] == 0


def test_re_suscripcion_revocada_crea_nonce_nuevo_y_no_revalida_confirmacion_enviada(database, config, monkeypatch):
    subscriber_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)
    previous = dict(outbox(database))
    old_token = previous["body"].split("/alertas/confirmar/")[1].split("\n")[0]
    # Fixture de una confirmación anteriormente enviada; no se contacta proveedor.
    with database:
        database.execute("UPDATE outbox SET status='sent',attempts=1,sent_at=? WHERE id=?", (mailer._stamp(), previous["id"]))
        database.execute("UPDATE subscribers SET status='unsubscribed',token_hash='' WHERE id=?", (subscriber_id,))
        database.execute("UPDATE subscribers SET status='pending' WHERE id=?", (subscriber_id,))
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["queued"] == 1
    current = outbox(database)
    new_token = current["body"].split("/alertas/confirmar/")[1].split("\n")[0]
    assert old_token != new_token
    current_hash = database.execute("SELECT token_hash FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()[0]
    assert mailer.verify_token(new_token, SECRET, "confirm") == (subscriber_id, current_hash)
    assert mailer.verify_token(old_token, SECRET, "confirm")[1] != current_hash
    assert current["idempotency_key"] != previous["idempotency_key"]
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["skipped"] == 1
    calls = []
    monkeypatch.setattr(mailer, "urlopen", lambda request, timeout: calls.append(request) or Accepted())
    assert mailer.send_outbox(database, config)["sent"] == 1
    assert len(calls) == 1
    assert new_token in json.loads(calls[0].data)["text"]
    assert old_token not in json.loads(calls[0].data)["text"]
    assert database.execute("SELECT status,attempts FROM outbox WHERE id=?", (previous["id"],)).fetchone()["attempts"] == 1


def test_confirmacion_enviada_con_hash_vigente_no_se_renueva_antes_de_vencer(database):
    subscriber_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)
    before = outbox(database)["idempotency_key"]
    with database:
        database.execute("UPDATE outbox SET status='sent',attempts=1")
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["skipped"] == 1
    assert outbox(database)["idempotency_key"] == before
    with database:
        database.execute("UPDATE outbox SET created_at=?", (mailer._stamp(mailer._now() - timedelta(days=3)),))
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["queued"] == 1
    assert outbox(database)["idempotency_key"] != before


@pytest.mark.parametrize("older_than_latest", [False, True])
def test_re_suscripcion_no_repite_confirmacion_incierta_ni_borra_reservas(database, config, monkeypatch, older_than_latest):
    subscriber_id = subscriber(database, status="pending")
    mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)
    old = outbox(database)
    with database:
        database.execute("UPDATE outbox SET status='uncertain',attempts=1,created_at=? WHERE id=?",
                         (mailer._stamp(mailer._now() - timedelta(days=3)), old["id"]))
        database.execute("INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES ('mailer','mail_reserved',?,'confirmation',?)",
                         (old["id"], mailer._stamp()))
        database.execute("UPDATE subscribers SET token_hash='' WHERE id=?", (subscriber_id,))
        if older_than_latest:
            database.execute(
                "INSERT INTO outbox(kind,subscriber_id,recipient,subject,body,idempotency_key,created_at,status) "
                "VALUES ('confirmation',?,'prueba@pruebas.ar','PRUEBA','PRUEBA','confirmation-cancelled-local',?,'cancelled')",
                (subscriber_id, mailer._stamp()),
            )
    before = database.execute("SELECT count(*) FROM outbox").fetchone()[0]
    assert mailer.queue_confirmation(database, subscriber_id, BASE_URL, SECRET)["skipped"] == 1
    monkeypatch.setattr(mailer, "urlopen", block_network)
    assert mailer.send_outbox(database, config)["sent"] == 0
    assert database.execute("SELECT count(*) FROM outbox").fetchone()[0] == before
    previous = database.execute("SELECT status,attempts FROM outbox WHERE id=?", (old["id"],)).fetchone()
    assert tuple(previous) == ("uncertain", 1)
    assert mailer.quota_status(database, config)["daily"]["used"] == 1
