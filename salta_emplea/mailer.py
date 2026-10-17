"""Alertas con doble consentimiento y una bandeja persistente, sin envíos simulados.

La bandeja reserva cada pareja suscriptor/oferta antes de enviar. Una respuesta
ambigua queda en ``uncertain`` para revisión humana: nunca se reintenta a ciegas.
Las credenciales, los tokens y los cuerpos de los correos no se registran.
"""

import hashlib
import ipaddress
import json
import re
import secrets
import socket
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .domain import public_jobs
from . import db


CONFIRM_MAX_AGE = 48 * 60 * 60
MAX_ATTEMPTS = 3
MAX_DIGEST_JOBS = 30
IDEMPOTENCY_WINDOW = timedelta(hours=23)


def _now():
    return datetime.now(timezone.utc)


def _stamp(value=None):
    return (value or _now()).isoformat(timespec="seconds")


def _parse(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _counts(**values):
    return dict(queued=0, sent=0, skipped=0, errors=0) | values


@contextmanager
def _transaction(conn):
    """Reserva escrituras también si el llamador ya abrió una transacción."""
    nested = conn.in_transaction
    if nested:
        conn.execute("SAVEPOINT mailer_transaction")
    else:
        conn.execute("BEGIN IMMEDIATE")
    try:
        if nested:
            db.mailer_lock(conn)
        yield
    except Exception:
        if nested:
            conn.execute("ROLLBACK TO SAVEPOINT mailer_transaction")
            conn.execute("RELEASE SAVEPOINT mailer_transaction")
        else:
            conn.rollback()
        raise
    else:
        if nested:
            conn.execute("RELEASE SAVEPOINT mailer_transaction")
        else:
            conn.commit()


def _serializer(secret_key):
    if not secret_key:
        raise ValueError("Configurá SECRET_KEY antes de preparar alertas.")
    return URLSafeTimedSerializer(secret_key)


def confirmation_token(subscriber_id, secret_key):
    return _serializer(secret_key).dumps(
        {"subscriber_id": int(subscriber_id), "nonce": secrets.token_urlsafe(24)}, salt="confirm"
    )


def unsubscribe_token(subscriber_id, secret_key):
    return _serializer(secret_key).dumps({"subscriber_id": int(subscriber_id)}, salt="unsubscribe")


def verify_token(token, secret_key, salt, max_age=CONFIRM_MAX_AGE):
    """Devuelve (id, hash) o None; la ruta de confirmación compara el hash guardado.

    Para una baja permanente, usar salt='unsubscribe', max_age=None. Los tokens
    de confirmación y de baja no son intercambiables.
    """
    if salt not in {"confirm", "unsubscribe"} or not isinstance(token, str) or len(token) > 2048:
        return None
    try:
        data = _serializer(secret_key).loads(token, salt=salt, max_age=max_age)
        subscriber_id = data["subscriber_id"]
        if type(subscriber_id) is not int or subscriber_id < 1:
            return None
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None
    return subscriber_id, hashlib.sha256(token.encode()).hexdigest()


def _base_url(base_url):
    return str(base_url or "").rstrip("/")


def queue_confirmation(conn, subscriber_id, base_url, secret_key):
    """Prepara una confirmación solicitada; no manda correo ni renueva por cron."""
    instant = _now()
    with _transaction(conn):
        subscriber = conn.execute("SELECT * FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()
        if subscriber is None or subscriber["status"] != "pending":
            return _counts(skipped=1)
        previous = conn.execute(
            "SELECT * FROM outbox WHERE subscriber_id=? AND kind='confirmation' ORDER BY id DESC LIMIT 1",
            (subscriber_id,),
        ).fetchone()
        if previous and previous["status"] in {"pending", "sent", "uncertain"}:
            if _parse(previous["created_at"]) > instant - timedelta(seconds=CONFIRM_MAX_AGE):
                return _counts(skipped=1)
        # Un correo viejo nunca se reactiva porque alguien repita la tarea.
        conn.execute(
            "UPDATE outbox SET status='cancelled',last_error='Confirmación reemplazada o vencida.' "
            "WHERE subscriber_id=? AND kind='confirmation' AND status='pending'", (subscriber_id,),
        )
        token = confirmation_token(subscriber_id, secret_key)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        conn.execute("UPDATE subscribers SET token_hash=? WHERE id=?", (token_hash, subscriber_id))
        body = (
            "Solicitaste alertas laborales de Salta Emplea. Para confirmar tu correo, abrí este enlace "
            "dentro de las próximas 48 horas:\n\n"
            f"{_base_url(base_url)}/alertas/confirmar/{token}\n\n"
            "Si no solicitaste estas alertas, ignorá este mensaje. No recibirás ofertas sin confirmar.\n\n"
            f"Cancelar la solicitud: {_base_url(base_url)}/alertas/baja/{unsubscribe_token(subscriber_id, secret_key)}"
        )
        conn.execute(
            "INSERT INTO outbox(kind,subscriber_id,recipient,subject,body,idempotency_key,created_at) "
            "VALUES ('confirmation',?,?,?,?,?,?)",
            (subscriber_id, subscriber["email"], "Confirmá tus alertas de Salta Emplea", body,
             "confirm-" + token_hash, _stamp(instant)),
        )
    return _counts(queued=1)


def _digest_body(subscriber_id, jobs, base_url, secret_key, unsubscribe_url=None):
    lines = ["Ofertas aprobadas y activas en Salta Emplea:", ""]
    for job in jobs:
        lines.extend([
            job["title"],
            f"Empresa: {job.get('company') or 'No informado'}",
            f"Localidad: {job.get('location') or 'No informado'} · Modalidad: {job.get('modality') or 'No informado'}",
            f"{_base_url(base_url)}/ofertas/{job['id']}", "",
        ])
    lines.extend([
        "Salta Emplea centraliza avisos y no garantiza contratación. La vigencia puede cambiar.",
        "Recibís este correo porque confirmaste tu suscripción.",
        "Dar de baja: " + (unsubscribe_url or f"{_base_url(base_url)}/alertas/baja/{unsubscribe_token(subscriber_id, secret_key)}"),
    ])
    return "\n".join(lines)


def queue_digests(conn, base_url, secret_key, *, limit=100, deadline=None):
    """Reserva un lote de suscripciones sin perder el avance entre corridas.

    El cursor circular avanza incluso si no hay ofertas o todavía no corresponde
    enviar. Así un lote pequeño no deja a las últimas personas sin procesar.
    ``last_sent_at`` se conserva exclusivamente para entregas confirmadas.
    """
    counters = _counts()
    instant = _now()
    limit = max(1, min(int(limit), 100))
    with _transaction(conn):
        cursor = conn.execute("SELECT value FROM settings WHERE key='digest_cursor'").fetchone()
        try:
            after_id = int(cursor[0]) if cursor else 0
        except (ValueError, TypeError):
            after_id = 0
        subscribers = conn.execute(
            "SELECT * FROM subscribers WHERE status='confirmed' AND id>? ORDER BY id LIMIT ?", (after_id, limit),
        ).fetchall()
        if len(subscribers) < limit:
            subscribers += conn.execute(
                "SELECT * FROM subscribers WHERE status='confirmed' AND id<=? ORDER BY id LIMIT ?",
                (after_id, limit - len(subscribers)),
            ).fetchall()
        for subscriber in subscribers:
            if deadline is not None and time.monotonic() >= deadline:
                counters['budget_exhausted'] = True
                break
            conn.execute(
                "INSERT INTO settings(key,value) VALUES ('digest_cursor',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(subscriber['id']),),
            )
            previous = conn.execute(
                "SELECT created_at FROM outbox WHERE subscriber_id=? AND kind='digest' ORDER BY id DESC LIMIT 1",
                (subscriber["id"],),
            ).fetchone()
            references = [value for value in [subscriber["last_sent_at"], previous["created_at"] if previous else None] if value]
            wait = timedelta(days=1 if subscriber["frequency"] == "daily" else 7)
            if references and max(_parse(value) for value in references) + wait > instant:
                counters["skipped"] += 1
                continue
            filters = {"location": subscriber["locality"], "sector": subscriber["sector"], "modality": subscriber["modality"]}
            delivered = {row[0] for row in conn.execute("SELECT job_id FROM deliveries WHERE subscriber_id=?", (subscriber["id"],))}
            jobs = [job for job in public_jobs(conn, filters) if job["id"] not in delivered][:MAX_DIGEST_JOBS]
            if not jobs:
                counters["skipped"] += 1
                continue
            ids = [job["id"] for job in jobs]
            key = hashlib.sha256(json.dumps([subscriber["id"], sorted(ids)]).encode()).hexdigest()
            cursor = conn.execute(
                "INSERT INTO outbox(kind,subscriber_id,job_ids,recipient,subject,body,idempotency_key,created_at) "
                "VALUES ('digest',?,?,?,?,?,?,?)",
                (subscriber["id"], json.dumps(ids), subscriber["email"], "Nuevas ofertas en Salta Emplea",
                 _digest_body(subscriber["id"], jobs, base_url, secret_key), "digest-" + key, _stamp(instant)),
            )
            conn.executemany("INSERT INTO deliveries(subscriber_id,job_id,outbox_id) VALUES (?,?,?)",
                             [(subscriber["id"], job_id, cursor.lastrowid) for job_id in ids])
            counters["queued"] += 1
    return counters


def _valid_delivery_config(config):
    """Falla de forma cerrada: modo development y dominios de prueba no envían."""
    if str(config.get("APP_ENV", "development")).lower() != "production":
        return False
    if not config.get("RESEND_API_KEY") or not config.get("SECRET_KEY"):
        return False
    sender = str(config.get("MAIL_FROM") or "")
    address = parseaddr(sender)[1]
    if "\r" in sender or "\n" in sender or "@" not in address or "." not in address.rsplit("@", 1)[1]:
        return False
    try:
        parsed = urlsplit(_base_url(config.get("PUBLIC_BASE_URL")))
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if not re.fullmatch(r"[a-z0-9.-]+", host) or re.search(r"[\s\\]", str(config.get("PUBLIC_BASE_URL"))):
            return False
        if parsed.port not in {None, 443} or "." not in host or host == "localhost":
            return False
        if host.endswith((".test", ".invalid", ".example", ".localhost", ".local")) or host in {"example.com", "example.org", "example.net"}:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def _cancel(conn, outbox_id, reason):
    conn.execute("UPDATE outbox SET status='cancelled',last_error=? WHERE id=?", (reason, outbox_id))


def _prepare_delivery(conn, item, config):
    """Revalida justo antes de reservar el intento; devuelve cuerpo o None."""
    subscriber = conn.execute("SELECT * FROM subscribers WHERE id=?", (item["subscriber_id"],)).fetchone()
    if subscriber is None or subscriber["email"] != item["recipient"]:
        _cancel(conn, item["id"], "La suscripción cambió o ya no existe.")
        return None
    if item["kind"] == "confirmation":
        if subscriber["status"] != "pending" or _parse(item["created_at"]) + timedelta(seconds=CONFIRM_MAX_AGE) <= _now():
            _cancel(conn, item["id"], "Confirmación vencida o consentimiento ya resuelto.")
            return None
        # Un cambio de base URL o token requiere que la persona vuelva a solicitarla.
        lines = item["body"].split("\n\n")
        prefix = _base_url(config["PUBLIC_BASE_URL"]) + "/alertas/confirmar/"
        token = lines[1][len(prefix):] if len(lines) > 1 and lines[1].startswith(prefix) else ""
        verified = verify_token(token, config["SECRET_KEY"], "confirm")
        if verified is None or verified != (subscriber["id"], subscriber["token_hash"]):
            _cancel(conn, item["id"], "La URL pública cambió: solicitar una nueva confirmación.")
            return None
        return item["body"]
    if item["kind"] != "digest" or subscriber["status"] != "confirmed":
        _cancel(conn, item["id"], "Consentimiento revocado o clase de correo inválida.")
        return None
    if subscriber["last_sent_at"]:
        next_allowed = _parse(subscriber["last_sent_at"]) + timedelta(days=1 if subscriber["frequency"] == "daily" else 7)
        if next_allowed > _now():
            conn.execute("UPDATE outbox SET next_attempt_at=?,last_error=NULL WHERE id=?", (_stamp(next_allowed), item["id"]))
            return None
    try:
        ids = json.loads(item["job_ids"])
        if not isinstance(ids, list) or any(type(job_id) is not int for job_id in ids):
            raise ValueError("La lista de ofertas no es válida.")
    except (ValueError, TypeError):
        _cancel(conn, item["id"], "La lista de ofertas requiere revisión manual.")
        return None
    filters = {"location": subscriber["locality"], "sector": subscriber["sector"], "modality": subscriber["modality"]}
    jobs = [job for job in public_jobs(conn, filters) if job["id"] in ids]
    if not jobs:
        _cancel(conn, item["id"], "Las ofertas dejaron de estar aprobadas y activas.")
        return None
    # La firma temporal de la baja se conserva entre intentos. Resend exige
    # idéntico contenido para reutilizar una clave de idempotencia.
    unsubscribe_url = item["body"].rsplit("Dar de baja: ", 1)[-1]
    prefix = _base_url(config["PUBLIC_BASE_URL"]) + "/alertas/baja/"
    verified = verify_token(unsubscribe_url[len(prefix):], config["SECRET_KEY"], "unsubscribe", max_age=None) if unsubscribe_url.startswith(prefix) else None
    if verified is None or verified[0] != subscriber["id"]:
        if item["attempts"]:
            _cancel(conn, item["id"], "El enlace de baja cambió tras un intento: revisar manualmente.")
            return None
        unsubscribe_url = None
    body = _digest_body(subscriber["id"], jobs, config["PUBLIC_BASE_URL"], config["SECRET_KEY"], unsubscribe_url)
    if item["attempts"] and body != item["body"]:
        _cancel(conn, item["id"], "Las ofertas cambiaron tras un intento: revisar manualmente sin repetir el envío.")
        return None
    return body


def send_outbox(conn, config, *, limit=None, deadline=None):
    """Envía con Resend únicamente en producción configurada. Nunca usar en tests sin mock.

    Se registra ``uncertain`` antes de salir a la red: un cierre del proceso o
    timeout exige revisión humana. Sólo 429 y 5xx explícitos admiten reintento,
    con la misma clave durante menos de 24 horas y hasta tres intentos.
    """
    counters = _counts()
    if not _valid_delivery_config(config):
        counters["skipped"] = conn.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0]
        return counters
    # No enviar mientras el llamador conserva cambios sin confirmar.
    if conn.in_transaction:
        raise ValueError("Confirmá la transacción antes de procesar correos.")
    limit = max(1, min(int(limit if limit is not None else config.get('TASK_MAIL_BATCH', 10)), 100))
    pending_ids = [row[0] for row in conn.execute(
        "SELECT id FROM outbox WHERE status='pending' AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY id LIMIT ?",
        (_stamp(), limit),
    )]
    for outbox_id in pending_ids:
        # Reservar tiempo para el timeout de red antes de marcar un intento.
        # Lo diferido sigue pendiente, sin consumir intentos ni reservas nuevas.
        if deadline is not None and time.monotonic() + 15 >= deadline:
            counters['budget_exhausted'] = True
            break
        with _transaction(conn):
            item = conn.execute(
                "SELECT * FROM outbox WHERE id=? AND status='pending' AND (next_attempt_at IS NULL OR next_attempt_at<=?)",
                (outbox_id, _stamp()),
            ).fetchone()
            if item is None:
                counters["skipped"] += 1
                continue
            first_attempt = _parse(item["first_attempt_at"] or item["created_at"])
            if item["attempts"] >= MAX_ATTEMPTS or (item["attempts"] and first_attempt + IDEMPOTENCY_WINDOW <= _now()):
                conn.execute("UPDATE outbox SET status='failed',last_error='Se agotó la ventana segura de reintentos.' WHERE id=?", (outbox_id,))
                counters["errors"] += 1
                continue
            body = _prepare_delivery(conn, item, config)
            if body is None:
                counters["skipped"] += 1
                continue
            stamp = _stamp()
            conn.execute(
                "UPDATE outbox SET status='uncertain',attempts=attempts+1,first_attempt_at=COALESCE(first_attempt_at,?),"
                "body=?,last_error='Intento reservado: comprobar proveedor si el proceso se interrumpe.' WHERE id=?",
                (stamp, body, outbox_id),
            )
        payload = {"from": config["MAIL_FROM"], "to": [item["recipient"]], "subject": item["subject"], "text": body}
        if item['kind'] == 'digest':
            # Reutilizar el enlace persistido mantiene idéntico el payload durante reintentos.
            unsubscribe_url = body.rsplit('\n', 1)[-1].removeprefix('Dar de baja: ')
            payload['headers'] = {'List-Unsubscribe': f'<{unsubscribe_url}>', 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'}
        request = Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST", headers={
            "Authorization": "Bearer " + config["RESEND_API_KEY"], "Content-Type": "application/json",
            "Idempotency-Key": item["idempotency_key"],
        })
        status = "uncertain"
        error = None
        try:
            timeout = min(15, max(0.1, deadline - time.monotonic())) if deadline is not None else 15
            with urlopen(request, timeout=timeout) as response:
                code = response.getcode()
                if 200 <= code < 300:
                    status = "sent"
                else:
                    error = f"Respuesta HTTP inesperada ({code}); revisar proveedor."
        except HTTPError as exc:
            attempts = item["attempts"] + 1
            if (exc.code == 429 or 500 <= exc.code <= 599) and attempts < MAX_ATTEMPTS:
                status = "pending"
            else:
                status = "failed"
            error = f"Proveedor respondió HTTP {exc.code}."
        except (TimeoutError, socket.timeout, URLError, OSError):
            error = "Entrega incierta por interrupción de red; revisar el proveedor antes de actuar."
        with _transaction(conn):
            next_attempt = _stamp(_now() + timedelta(minutes=5 * 2 ** item["attempts"])) if status == "pending" else None
            conn.execute("UPDATE outbox SET status=?,sent_at=?,next_attempt_at=?,last_error=? WHERE id=?",
                         (status, _stamp() if status == "sent" else None, next_attempt, error, outbox_id))
            if status == "sent" and item["kind"] == "digest":
                conn.execute("UPDATE subscribers SET last_sent_at=? WHERE id=?", (_stamp(), item["subscriber_id"]))
        counters["sent" if status == "sent" else "errors"] += 1
    return counters
