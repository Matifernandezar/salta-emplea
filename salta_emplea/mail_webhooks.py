"""Recepción acotada y autenticada de eventos de Resend, sin guardar el cuerpo.

Implementa el protocolo HMAC-SHA256 documentado por Svix: el cuerpo se verifica
antes de interpretar JSON. No necesita SDK ni realiza consultas al proveedor.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import time

from flask import Blueprint, current_app, request

from . import mailer


MAX_PAYLOAD_BYTES = 64 * 1024
TIMESTAMP_TOLERANCE_SECONDS = 5 * 60
SUPPRESSION_EVENTS = frozenset({"email.bounced", "email.complained", "email.suppressed"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,200}")
_EMAIL = re.compile(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+")


class WebhookError(ValueError):
    """Solo códigos propios y fijos: nunca incluir secretos o datos recibidos."""

    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def verify_signature(raw_body, headers, secret, *, now=None):
    """Valida el protocolo Svix oficial y devuelve el identificador autenticado."""
    if not isinstance(raw_body, bytes) or len(raw_body) > MAX_PAYLOAD_BYTES:
        raise WebhookError("payload_too_large", 413)
    if not isinstance(secret, str) or not secret.startswith("whsec_") or len(secret) > 200:
        raise WebhookError("not_configured", 503)
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
        if not 16 <= len(key) <= 64:
            raise ValueError
    except (ValueError, binascii.Error):
        raise WebhookError("not_configured", 503) from None
    message_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "")
    if (not isinstance(message_id, str) or not _IDENTIFIER.fullmatch(message_id)
            or not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,12}", timestamp)
            or not isinstance(signatures, str) or len(signatures) > 2048):
        raise WebhookError("invalid_signature", 401)
    if abs(int(time.time() if now is None else now) - int(timestamp)) > TIMESTAMP_TOLERANCE_SECONDS:
        raise WebhookError("invalid_signature", 401)
    signed = f"{message_id}.{timestamp}.".encode("ascii") + raw_body
    expected = hmac.new(key, signed, hashlib.sha256).digest()
    parts = signatures.split()
    if len(parts) > 10:
        raise WebhookError("invalid_signature", 401)
    valid = False
    for part in parts:
        if not part.startswith("v1,"):
            continue
        try:
            received = base64.b64decode(part[3:], validate=True)
        except (ValueError, binascii.Error):
            continue
        # Comparar todos los candidatos; Svix puede enviar varias firmas al rotar.
        valid |= hmac.compare_digest(expected, received)
    if not valid:
        raise WebhookError("invalid_signature", 401)
    return message_id


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError


def _payload(raw_body):
    try:
        value = json.loads(raw_body.decode("utf-8"), object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise WebhookError("invalid_payload") from None
    if (not isinstance(value, dict) or not isinstance(value.get("type"), str)
            or not 1 <= len(value["type"]) <= 64 or not isinstance(value.get("data"), dict)):
        raise WebhookError("invalid_payload")
    return value


def _recipients(data):
    recipients = data.get("to")
    if not isinstance(recipients, list) or not 1 <= len(recipients) <= 50:
        raise WebhookError("invalid_payload")
    normalized = set()
    for value in recipients:
        if (not isinstance(value, str) or not value.isascii() or not 3 <= len(value) <= 254
                or not _EMAIL.fullmatch(value)):
            raise WebhookError("invalid_payload")
        normalized.add(value.lower())
    return sorted(normalized)


def process_verified_event(conn, raw_body, message_id):
    """Aplica únicamente un evento cuya firma ya verificó el llamador.

    Un ID firmado repetido acepta el mismo cuerpo. Si trae otro cuerpo devuelve
    conflicto sin alterar supresiones. Ledger y cambios se confirman juntos bajo
    el bloqueo de correo compartido por SQLite y PostgreSQL.
    """
    payload = _payload(raw_body)
    event = payload["type"]
    recipients = _recipients(payload["data"]) if event in SUPPRESSION_EVENTS else []
    event_hash = hashlib.sha256(raw_body).hexdigest()
    ledger_key = "mail_webhook:" + hashlib.sha256(message_id.encode("ascii")).hexdigest()
    stamp = mailer._stamp()
    with mailer._transaction(conn):
        previous = conn.execute("SELECT value FROM settings WHERE key=?", (ledger_key,)).fetchone()
        if previous:
            try:
                same = hmac.compare_digest(json.loads(previous["value"])["payload_hash"], event_hash)
            except (ValueError, TypeError, KeyError):
                same = False
            if not same:
                raise WebhookError("event_conflict", 409)
            return {"status": "duplicate"}
        affected = 0
        for email in recipients:
            # Solo el hash estable y una razón enumerada persisten en settings.
            conn.execute(
                "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (mailer.suppression_key(email), json.dumps({"reason": event, "created_at": stamp}, sort_keys=True)),
            )
            row = conn.execute("SELECT id FROM subscribers WHERE email=?", (email,)).fetchone()
            if row is not None:
                affected += 1
                conn.execute("UPDATE subscribers SET status='unsubscribed',token_hash='' WHERE id=?", (row["id"],))
                conn.execute(
                    "UPDATE outbox SET status='cancelled',last_error='Dirección suprimida por el proveedor; requiere revisión.' "
                    "WHERE subscriber_id=? AND status='pending'", (row["id"],),
                )
        detail = {"event": event if event in SUPPRESSION_EVENTS else "ignored", "affected": affected}
        conn.execute(
            "INSERT INTO settings(key,value) VALUES (?,?)",
            (ledger_key, json.dumps({"payload_hash": event_hash, "received_at": stamp, **detail}, sort_keys=True)),
        )
        conn.execute(
            "INSERT INTO audit(actor,action,detail,created_at) VALUES ('resend_webhook','mail_webhook',?,?)",
            (json.dumps(detail, sort_keys=True), stamp),
        )
    return {"status": "processed" if recipients else "ignored"}


def create_blueprint(connection):
    """El dueño de la app proporciona la misma conexión y su cierre habitual."""
    blueprint = Blueprint("mail_webhooks", __name__)

    @blueprint.post("/api/webhooks/resend")
    def resend():
        try:
            if request.content_length is not None and request.content_length > MAX_PAYLOAD_BYTES:
                raise WebhookError("payload_too_large", 413)
            if request.mimetype != "application/json" or request.headers.get("Content-Encoding", "identity") != "identity":
                raise WebhookError("invalid_payload")
            raw_body = request.stream.read(MAX_PAYLOAD_BYTES + 1)
            message_id = verify_signature(raw_body, request.headers, current_app.config.get("RESEND_WEBHOOK_SECRET", ""))
            result = process_verified_event(connection(), raw_body, message_id)
        except WebhookError as error:
            return {"status": error.code}, error.status
        except Exception as error:
            # Un fallo de base debe permitir reintento del proveedor sin filtrar
            # DSN, direcciones ni el cuerpo recibido mediante un traceback.
            current_app.logger.error("Falló la recepción de correo (%s).", type(error).__name__)
            return {"status": "temporarily_unavailable"}, 503
        return result

    @blueprint.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return blueprint
