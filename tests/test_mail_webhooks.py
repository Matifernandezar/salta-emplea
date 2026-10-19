"""Firmas oficiales y eventos locales: nunca se contacta Resend ni destinatarios."""

import base64
import hashlib
import hmac
import json
import time

import pytest
from flask import Flask

from salta_emplea import mailer, mail_webhooks
from salta_emplea.db import connect, init_db


SIGNING_KEY = b"clave-local-de-pruebas-32-bytes!!"
WEBHOOK_SECRET = "whsec_" + base64.b64encode(SIGNING_KEY).decode()
TEST_EMAIL = "prueba@pruebas.ar"


def event_bytes(event="email.bounced", *, to=None, extra=None):
    value = {"type": event, "created_at": "2026-10-19T00:00:00Z", "data": {
        "email_id": "56761188-7520-42d8-8898-ff6fc54ce618", "to": to or [TEST_EMAIL],
        "subject": "PRUEBA privada: no guardar el cuerpo", "bounce": {"type": "Permanent"},
    }}
    if extra:
        value.update(extra)
    return json.dumps(value).encode()


def signed_headers(raw, *, identifier="msg_prueba_1", timestamp=None, key=SIGNING_KEY):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = base64.b64encode(hmac.new(key, identifier.encode() + b"." + stamp.encode() + b"." + raw, hashlib.sha256).digest()).decode()
    return {"svix-id": identifier, "svix-timestamp": stamp, "svix-signature": "v1," + signature}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "webhook.sqlite"
    init_db(path)
    conn = connect(path)
    with conn:
        conn.execute(
            "INSERT INTO subscribers(email,status,token_hash,created_at) VALUES (?,'confirmed','token-local',?)",
            (TEST_EMAIL, mailer._stamp()),
        )
        conn.execute(
            "INSERT INTO outbox(kind,subscriber_id,recipient,subject,body,idempotency_key,created_at) "
            "VALUES ('digest',1,?,'PRUEBA','PRUEBA','clave-local',?)", (TEST_EMAIL, mailer._stamp()),
        )
    yield conn
    conn.close()


@pytest.fixture
def app(database):
    app = Flask(__name__)
    app.config.update(TESTING=True, RESEND_WEBHOOK_SECRET=WEBHOOK_SECRET)
    app.register_blueprint(mail_webhooks.create_blueprint(lambda: database))
    return app


def post(client, raw, **kwargs):
    return client.post("/api/webhooks/resend", data=raw, content_type="application/json",
                       headers=signed_headers(raw, **kwargs))


def test_vector_oficial_svix_verifica_sin_depender_de_nuestra_funcion_de_firma():
    # Vector publicado en docs.svix.com/receiving/verifying-payloads/how-manual.
    payload = b'{"event_type":"ping","data":{"success":true}}'
    headers = {"svix-id": "msg_loFOjxBNrRLzqYUf", "svix-timestamp": "1731705121",
               "svix-signature": "v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0="}
    assert mail_webhooks.verify_signature(payload, headers, "whsec_plJ3nmyCDGBKInavdOK15jsl", now=1731705121) == headers["svix-id"]


@pytest.mark.parametrize("event", sorted(mail_webhooks.SUPPRESSION_EVENTS))
def test_evento_autenticado_da_baja_cancela_pendientes_y_no_guarda_datos_externos(app, database, event):
    raw = event_bytes(event)
    response = post(app.test_client(), raw)
    assert response.status_code == 200
    assert response.json == {"status": "processed"}
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    row = database.execute("SELECT status,token_hash FROM subscribers").fetchone()
    assert tuple(row) == ("unsubscribed", "")
    assert database.execute("SELECT status,attempts FROM outbox").fetchone()["status"] == "cancelled"
    assert mailer.is_suppressed(database, TEST_EMAIL.upper())
    stored = json.dumps([dict(row) for row in database.execute("SELECT * FROM audit")])
    stored += json.dumps([dict(row) for row in database.execute("SELECT * FROM settings")])
    for forbidden in (TEST_EMAIL, "PRUEBA privada", "msg_prueba_1", "56761188-7520", WEBHOOK_SECRET):
        assert forbidden not in stored


def test_repeticion_firmada_no_repite_efectos_y_conflicto_no_suprime_otro_email(app, database):
    raw = event_bytes()
    client = app.test_client()
    assert post(client, raw).status_code == 200
    assert post(client, raw).json == {"status": "duplicate"}
    assert database.execute("SELECT count(*) FROM audit WHERE action='mail_webhook'").fetchone()[0] == 1
    changed = event_bytes(to=["otra@pruebas.ar"])
    response = post(client, changed)
    assert response.status_code == 409
    assert response.json == {"status": "event_conflict"}
    assert not mailer.is_suppressed(database, "otra@pruebas.ar")
    assert database.execute("SELECT count(*) FROM settings WHERE key LIKE 'mail_webhook:%'").fetchone()[0] == 1


@pytest.mark.parametrize("age", [-301, 301, -10000, 10000])
def test_replay_viejo_o_timestamp_futuro_no_modifica_datos(app, database, age):
    raw = event_bytes()
    response = post(app.test_client(), raw, timestamp=int(time.time()) + age)
    assert response.status_code == 401
    assert database.execute("SELECT status FROM subscribers").fetchone()[0] == "confirmed"
    assert database.execute("SELECT count(*) FROM settings").fetchone()[0] == 0


@pytest.mark.parametrize("headers_override", [
    {"svix-id": ""}, {"svix-id": "id\u00e9ntificador"}, {"svix-timestamp": "NaN"},
    {"svix-timestamp": "9" * 30}, {"svix-signature": "v1,no-base64!!"},
    {"svix-signature": "v2,desconocida"}, {"svix-signature": "x" * 2049},
])
def test_cabeceras_invalidas_no_modifican_datos(app, database, headers_override):
    raw = event_bytes()
    headers = signed_headers(raw) | headers_override
    response = app.test_client().post("/api/webhooks/resend", data=raw, content_type="application/json", headers=headers)
    assert response.status_code == 401
    assert database.execute("SELECT count(*) FROM audit").fetchone()[0] == 0


def test_no_acepta_cuerpo_tocado_ni_clave_ajena(app, database):
    raw = event_bytes()
    client = app.test_client()
    assert client.post("/api/webhooks/resend", data=raw + b" ", content_type="application/json", headers=signed_headers(raw)).status_code == 401
    assert post(client, raw, key=b"otra-clave-de-prueba-32-bytes!!").status_code == 401
    assert database.execute("SELECT status FROM subscribers").fetchone()[0] == "confirmed"


def test_rotacion_permita_firma_valida_entre_candidatos(app, database):
    raw = event_bytes()
    headers = signed_headers(raw)
    headers["svix-signature"] = "v1,bm8taG1hYy12YWxpZG8= v2,abc " + headers["svix-signature"]
    response = app.test_client().post("/api/webhooks/resend", data=raw, content_type="application/json", headers=headers)
    assert response.status_code == 200
    assert mailer.is_suppressed(database, TEST_EMAIL)


@pytest.mark.parametrize("secret", ["", None, "secreto-sin-prefijo", "whsec_???", "whsec_YQ=="])
def test_falta_de_configuracion_cierra_endpoint_sin_exponer_secretos(app, database, secret):
    app.config["RESEND_WEBHOOK_SECRET"] = secret
    raw = event_bytes()
    response = post(app.test_client(), raw)
    assert response.status_code == 503
    assert response.json == {"status": "not_configured"}
    assert database.execute("SELECT count(*) FROM settings").fetchone()[0] == 0


@pytest.mark.parametrize("raw", [
    b"{}", b"[]", b"null", b"not-json", b"\xff",
    b'{"type":"email.bounced","type":"email.complained","data":{"to":["prueba@pruebas.ar"]}}',
    b'{"type":"email.bounced","data":{"to":["prueba@pruebas.ar"]},"value":NaN}',
    b'{"type":"email.bounced","data":{"to":["prueba@pruebas.ar"]},"value":Infinity}',
    b'{"type":"email.bounced","data":{"to":["nombre <prueba@pruebas.ar>"]}}',
    b'{"type":"email.bounced","data":{"to":[]}}',
    b'{"type":"email.bounced","data":{"to":["bad\\u000a@pruebas.ar"]}}',
])
def test_payload_firmado_malformado_no_produce_efectos(app, database, raw):
    response = post(app.test_client(), raw)
    assert response.status_code == 400
    assert database.execute("SELECT count(*) FROM settings").fetchone()[0] == 0


def test_no_guarda_cuerpos_enormes_ni_acepta_compresion(app, database):
    client = app.test_client()
    huge = b"x" * (mail_webhooks.MAX_PAYLOAD_BYTES + 1)
    assert post(client, huge).status_code == 413
    raw = event_bytes()
    headers = signed_headers(raw) | {"Content-Encoding": "gzip"}
    assert client.post("/api/webhooks/resend", data=raw, content_type="application/json", headers=headers).status_code == 400
    assert client.post("/api/webhooks/resend", data=raw, headers=signed_headers(raw), content_type="text/plain").status_code == 400
    assert database.execute("SELECT count(*) FROM settings").fetchone()[0] == 0


def test_eventos_de_entrega_no_suprimen_ni_prueban_recepcion_humana(app, database):
    raw = event_bytes("email.delivered")
    response = post(app.test_client(), raw)
    assert response.json == {"status": "ignored"}
    assert database.execute("SELECT status FROM subscribers").fetchone()[0] == "confirmed"
    assert not mailer.is_suppressed(database, TEST_EMAIL)


def test_varios_destinatarios_unicos_no_reactivan_y_suprimen_desconocidos(app, database):
    raw = event_bytes(to=[TEST_EMAIL, TEST_EMAIL.upper(), "otra@pruebas.ar"])
    assert post(app.test_client(), raw).status_code == 200
    assert mailer.is_suppressed(database, "otra@pruebas.ar")
    assert database.execute("SELECT count(*) FROM settings WHERE key LIKE 'mail_suppressed:%'").fetchone()[0] == 2
    detail = json.loads(database.execute("SELECT detail FROM audit WHERE action='mail_webhook'").fetchone()[0])
    assert detail["affected"] == 1


def test_evento_no_reconcilia_un_envio_incierto_ni_borra_intentos(app, database):
    with database:
        database.execute("UPDATE outbox SET status='uncertain',attempts=1")
    assert post(app.test_client(), event_bytes("email.complained")).status_code == 200
    item = database.execute("SELECT status,attempts FROM outbox").fetchone()
    assert tuple(item) == ("uncertain", 1)
    assert database.execute("SELECT status FROM subscribers").fetchone()[0] == "unsubscribed"


def test_idempotencia_persiste_entre_conexiones_y_sus_efectos_son_atomicos(database):
    raw = event_bytes()
    second = connect(database.execute("PRAGMA database_list").fetchone()[2])
    try:
        assert mail_webhooks.process_verified_event(database, raw, "msg_entre_conexiones") == {"status": "processed"}
        assert mail_webhooks.process_verified_event(second, raw, "msg_entre_conexiones") == {"status": "duplicate"}
        assert second.execute("SELECT count(*) FROM audit WHERE action='mail_webhook'").fetchone()[0] == 1
        assert second.execute("SELECT status FROM outbox").fetchone()[0] == "cancelled"
    finally:
        second.close()


def test_eventos_simultaneos_con_mismo_id_aplican_una_sola_vez(database):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    path = database.execute("PRAGMA database_list").fetchone()[2]
    raw = event_bytes()
    ready = threading.Barrier(2)

    def worker():
        conn = connect(path)
        try:
            ready.wait(timeout=5)
            return mail_webhooks.process_verified_event(conn, raw, "msg_simultaneo")
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: worker(), range(2)))
    assert sorted(result["status"] for result in results) == ["duplicate", "processed"]
    assert database.execute("SELECT count(*) FROM audit WHERE action='mail_webhook'").fetchone()[0] == 1
    assert database.execute("SELECT status FROM subscribers").fetchone()[0] == "unsubscribed"


def test_fallo_antes_de_confirmar_no_deja_supresion_parcial_ni_ledger(database):
    import sqlite3

    # Fallo local deliberado en el último paso, sin modificar el esquema real.
    with database:
        database.execute(
            "CREATE TEMP TRIGGER fail_mail_audit BEFORE INSERT ON audit "
            "WHEN NEW.action='mail_webhook' BEGIN SELECT RAISE(ABORT,'fallo local de prueba'); END"
        )
    raw = event_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        mail_webhooks.process_verified_event(database, raw, "msg_rollback")
    assert database.execute("SELECT count(*) FROM settings").fetchone()[0] == 0
    assert database.execute("SELECT status FROM subscribers").fetchone()[0] == "confirmed"
    assert database.execute("SELECT status FROM outbox").fetchone()[0] == "pending"


def test_fallo_interno_no_expone_cuerpo_o_credencial_y_permite_reintento(app, database, monkeypatch, caplog):
    def failure(*_args):
        raise RuntimeError("no mostrar: " + TEST_EMAIL + " " + WEBHOOK_SECRET)

    monkeypatch.setattr(mail_webhooks, "process_verified_event", failure)
    response = post(app.test_client(), event_bytes())
    assert response.status_code == 503
    assert response.json == {"status": "temporarily_unavailable"}
    assert "RuntimeError" in caplog.text
    assert TEST_EMAIL not in caplog.text + response.get_data(as_text=True)
    assert WEBHOOK_SECRET not in caplog.text + response.get_data(as_text=True)
    assert database.execute("SELECT count(*) FROM settings").fetchone()[0] == 0
