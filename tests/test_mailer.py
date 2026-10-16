"""Pruebas locales: el proveedor siempre está sustituido, no salen correos reales."""

import json
from datetime import timedelta
from urllib.error import HTTPError, URLError

import pytest
from itsdangerous import TimestampSigner

from salta_emplea import mailer
from salta_emplea.db import connect, init_db
from salta_emplea.domain import create_job, transition_job


SECRET = "clave-de-pruebas-locales-sin-uso-en-produccion"
BASE_URL = "https://empleos.pruebas.ar"


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
            "PUBLIC_BASE_URL": BASE_URL, "SECRET_KEY": SECRET}


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
