"""Reglas deterministas del circuito editorial de Salta Emplea.

El contenido importado sólo se almacena como datos. Aquí no se ejecutan
instrucciones, se visitan enlaces ni se solicita a una IA completar campos.
"""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import db
from zoneinfo import ZoneInfo


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, limit=20000):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.casefold() in {"no informado", "no informada"}:
        return None
    if len(value) > limit:
        raise ValueError(f"El texto excede el máximo de {limit} caracteres.")
    return value


def _fold(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c)).casefold().split())


def _date(value, field):
    value = _text(value, 60)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Fecha inválida: {field}.") from exc
    if field == "expires_at" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        # Una fecha de cierre incluye todo ese día en Salta. El límite es
        # exclusivo: comienza el día siguiente a las 00:00 de la provincia.
        parsed = (parsed + timedelta(days=1)).replace(tzinfo=ZoneInfo("America/Argentina/Salta"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def application_url(value):
    """Devuelve una dirección segura o lanza ValueError; no hace solicitudes."""
    value = _text(value, 2048)
    if not value:
        return None
    if re.search(r"[\s\x00-\x1f\x7f\\]", value):
        raise ValueError("El enlace de postulación contiene caracteres inválidos.")
    if value.lower().startswith("mailto:"):
        address = value[7:]
        if not re.fullmatch(r"[A-Za-z0-9._+-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", address):
            raise ValueError("Usá mailto: con una sola dirección de correo, sin parámetros.")
        return "mailto:" + address
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("El enlace de postulación no es válido.") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("La postulación debe usar HTTPS, mailto: o https://wa.me/número.")
    if "." not in parsed.hostname or parsed.hostname.startswith(".") or parsed.hostname.endswith("."):
        raise ValueError("El enlace debe incluir un dominio válido.")
    if parsed.hostname.lower() in {"wa.me", "www.wa.me"}:
        if not re.fullmatch(r"/[1-9][0-9]{6,14}/?", parsed.path):
            raise ValueError("WhatsApp requiere https://wa.me/ seguido del número internacional, sólo dígitos.")
        if any(key != "text" for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise ValueError("El enlace de WhatsApp sólo admite el parámetro text.")
    if port is not None and port not in {443}:
        raise ValueError("El enlace HTTPS debe usar el puerto estándar.")
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def canonical_url(value):
    value = application_url(value)
    if not value or value.startswith("mailto:"):
        return value
    parsed = urlsplit(value)
    query = sorted((key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                   if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"})
    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit(("https", host, parsed.path.rstrip("/") or "/", urlencode(query), ""))


FIELDS = (
    "title", "company", "location", "modality", "sector", "schedule", "contract_type",
    "requirements", "description", "salary_amount", "salary_currency", "salary_period",
    "salary_source_evidence", "source_url", "source_name", "original_text", "image_path",
    "application_url", "original_date", "last_checked_at", "expires_at",
)
MATERIAL_FIELDS = ("title", "company", "application_url", "location", "modality", "contract_type",
                   "schedule", "salary_amount", "salary_currency", "salary_period", "requirements", "description", "expires_at")
TRUSTED_IMPORT_ACTORS = ("administrador", "recopilador_autorizado")


def _list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(str(item)[:200] for item in value if item))[:40]


def _normalize(data):
    cleaned = {field: _text(data.get(field), 20000 if field in {"original_text", "description", "requirements"} else 2048) for field in FIELDS}
    if not cleaned["title"]:
        raise ValueError("Indicá el puesto antes de incorporar una oferta.")
    cleaned["title"] = _text(cleaned["title"], 200)
    modality = _fold(cleaned["modality"])
    modalities = {"presencial": "presencial", "hibrida": "híbrida", "hibrido": "híbrida", "hybrid": "híbrida", "remota": "remota", "remoto": "remota", "remote": "remota"}
    if modality and modality not in modalities:
        raise ValueError("La modalidad debe ser presencial, híbrida o remota.")
    cleaned["modality"] = modalities.get(modality)
    cleaned["application_url"] = application_url(cleaned["application_url"])
    if cleaned["source_url"]:
        cleaned["source_url"] = application_url(cleaned["source_url"])
        if cleaned["source_url"].startswith("mailto:"):
            raise ValueError("La URL de la fuente debe usar HTTPS.")
    cleaned["source_canonical_url"] = canonical_url(cleaned["source_url"])
    for field in ("original_date", "last_checked_at", "expires_at"):
        cleaned[field] = _date(cleaned[field], field)
    salary = [cleaned[field] for field in ("salary_amount", "salary_currency", "salary_period")]
    if any(salary) and (not all(salary) or not cleaned["salary_source_evidence"]):
        raise ValueError("El sueldo requiere importe, moneda, período y evidencia textual de la fuente.")
    if not any(salary):
        cleaned["salary_source_evidence"] = None
    cleaned["uncertain_fields"] = _list(data.get("uncertain_fields"))
    # Cada edición recalcula señales: el operador puede corregir los datos,
    # pero no desactivar una señal automática dejando el contenido intacto.
    flags = []
    text = _fold(" ".join(cleaned.get(field) or "" for field in ("title", "requirements", "description", "original_text")))
    if re.search(r"(?:pagar|pago|abonar|transferir|deposito|depositar|inversion|costo).{0,65}(?:postul|inscrip|entrevista|seleccion|ingresar|vacante)|(?:postul|inscrip|entrevista|seleccion|ingresar|vacante).{0,65}(?:pagar|pago|abonar|transferir|deposito|depositar|inversion|costo)", text):
        flags.append("payment_requested")
    if cleaned["image_path"]:
        flags.append("image_review")
    cleaned["flags"] = flags
    return cleaned


def _audit(conn, actor, action, entity_id, detail=None):
    conn.execute("INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES (?,?,?,?,?)",
                 (actor, action, entity_id, json.dumps(detail or {}, ensure_ascii=False), now()))


def _provenance(conn, job_id, data):
    payload = json.dumps({field: data.get(field) for field in FIELDS}, ensure_ascii=False, sort_keys=True)
    fingerprint = _fingerprint(data)
    conn.execute("""INSERT OR IGNORE INTO provenance
                 (job_id,source_url,source_name,original_text,image_path,payload,fingerprint,collected_at)
                 VALUES (?,?,?,?,?,?,?,?)""",
                 (job_id, data.get("source_url"), data.get("source_name"), data.get("original_text"),
                  data.get("image_path"), payload, fingerprint, now()))


def _fingerprint(data):
    # Una comprobación posterior no convierte el mismo aviso en uno nuevo.
    content = {field: data.get(field) for field in FIELDS if field != "last_checked_at"}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _import_baseline(conn, job):
    """Última versión recibida por un actor interno, sin confundirla con la edición.

    La auditoría identifica su huella; la procedencia conserva los datos completos.
    Un aporte público nunca puede sustituir esta referencia. Las bases anteriores
    a este registro usan la versión preparada como comparación conservadora.
    """
    event = conn.execute("""SELECT detail FROM audit WHERE entity_id=?
                         AND actor IN (?,?) AND action IN ('created','duplicate_received')
                         ORDER BY id DESC LIMIT 1""", (job["id"], *TRUSTED_IMPORT_ACTORS)).fetchone()
    if event:
        detail = json.loads(event["detail"] or "{}")
        fingerprint = detail.get("source_fingerprint")
        if fingerprint:
            source = conn.execute("SELECT payload FROM provenance WHERE job_id=? AND fingerprint=?",
                                  (job["id"], fingerprint)).fetchone()
            if source:
                return json.loads(source["payload"])
    return dict(job)


def _duplicates(conn, data, exclude=None):
    result = []
    title = _fold(data["title"])
    company = _fold(data.get("company"))
    location = _fold(data.get("location"))
    description = _fold(data.get("description") or data.get("original_text"))
    for row in conn.execute("SELECT id,title,company,location,description,original_text FROM jobs ORDER BY id DESC LIMIT 1500"):
        if row["id"] == exclude:
            continue
        same_company = bool(company and company == _fold(row["company"]))
        same_place = location == _fold(row["location"])
        similar_title = SequenceMatcher(None, title, _fold(row["title"])).ratio() >= .88
        old_text = _fold(row["description"] or row["original_text"])
        similar_content = bool(len(description) > 80 and old_text and SequenceMatcher(None, description[:4000], old_text[:4000]).ratio() >= .91)
        if (same_company and same_place and similar_title) or (similar_title and similar_content):
            result.append(row["id"])
    return result


def job_dict(row):
    if row is None:
        return None
    data = dict(row)
    for field in ("flags", "uncertain_fields"):
        if field in data:
            data[field] = _list(data[field])
    return data


def create_job(conn, data, actor="comunidad"):
    cleaned = _normalize(data)
    stamp = now()
    with conn:
        # Reservar la escritura antes del control evita una carrera entre dos recolectores.
        db.editorial_lock(conn)
        if cleaned["source_canonical_url"]:
            existing = conn.execute("SELECT * FROM jobs WHERE source_canonical_url=?", (cleaned["source_canonical_url"],)).fetchone()
            if existing:
                baseline = _import_baseline(conn, existing)
                _provenance(conn, existing["id"], cleaned)
                # Una retirada de datos también exige revisión. Comparar contra
                # la fuente anterior evita retirar otra vez por una corrección
                # editorial que ya fue aprobada explícitamente.
                changed = [field for field in MATERIAL_FIELDS if cleaned.get(field) != baseline.get(field)]
                # Las contribuciones públicas jamás pueden retirar una oferta:
                # podrían contener cambios falsos o reproducir una URL ajena.
                trusted_actor = actor in TRUSTED_IMPORT_ACTORS
                if changed and existing["status"] == "approved" and trusted_actor:
                    flags = list(dict.fromkeys(_list(existing["flags"]) + ["source_changed"]))
                    conn.execute("UPDATE jobs SET status='pending', review_needed=1, approved_at=NULL, approved_by=NULL, flags=?, updated_at=? WHERE id=?",
                                 (json.dumps(flags), stamp, existing["id"]))
                _audit(conn, actor, "duplicate_received", existing["id"], {
                    "material_changes": changed, "trusted_actor": trusted_actor,
                    "source_fingerprint": _fingerprint(cleaned),
                })
                return existing["id"], [existing["id"]]
        # Huella de la copia saneada: repetir una imagen conserva su procedencia
        # aunque cambie el nombre del archivo subido o la URL del aporte.
        if cleaned['image_path'] and re.fullmatch(r'[0-9a-f]{64}\.jpg', cleaned['image_path']):
            repeated_image = conn.execute('SELECT id FROM jobs WHERE image_path=? ORDER BY id LIMIT 1',
                                          (cleaned['image_path'],)).fetchone()
            if repeated_image:
                _provenance(conn, repeated_image['id'], cleaned)
                _audit(conn, actor, 'duplicate_received', repeated_image['id'], {'exact_image': True})
                return repeated_image['id'], [repeated_image['id']]
        if not cleaned['source_canonical_url']:
            repeated = conn.execute("SELECT p.job_id FROM provenance p JOIN jobs j ON j.id=p.job_id WHERE p.fingerprint=? AND j.source_canonical_url IS NULL LIMIT 1", (_fingerprint(cleaned),)).fetchone()
            if repeated:
                _audit(conn, actor, "duplicate_received", repeated["job_id"], {"exact_content": True})
                return repeated["job_id"], [repeated["job_id"]]
        duplicate_ids = _duplicates(conn, cleaned)
        if duplicate_ids:
            cleaned["flags"].append("possible_duplicate")
        columns = list(FIELDS) + ["source_canonical_url", "flags", "uncertain_fields", "collected_at", "created_at", "updated_at"]
        values = [cleaned.get(field) for field in columns]
        for field in ("flags", "uncertain_fields"):
            values[columns.index(field)] = json.dumps(cleaned[field], ensure_ascii=False)
        for field in ("collected_at", "created_at", "updated_at"):
            values[columns.index(field)] = stamp
        cursor = conn.execute(f"INSERT INTO jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
        job_id = cursor.lastrowid
        _provenance(conn, job_id, cleaned)
        _audit(conn, actor, "created", job_id, {
            "duplicate_ids": duplicate_ids, "source_fingerprint": _fingerprint(cleaned),
        })
    return job_id, duplicate_ids


def edit_job(conn, job_id, data, actor):
    with conn:
        db.editorial_lock(conn)
        existing = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if existing is None:
            raise ValueError("La oferta no existe.")
        merged = dict(existing)
        merged.update({key: value for key, value in data.items() if key in FIELDS or key == "uncertain_fields"})
        cleaned = _normalize(merged)
        duplicate_ids = _duplicates(conn, cleaned, exclude=job_id)
        if duplicate_ids:
            cleaned["flags"].append("possible_duplicate")
        if cleaned["source_canonical_url"]:
            other = conn.execute("SELECT id FROM jobs WHERE source_canonical_url=? AND id != ?", (cleaned["source_canonical_url"], job_id)).fetchone()
            if other:
                raise ValueError("Esa URL ya pertenece a otra oferta. Revisá el posible duplicado.")
        columns = list(FIELDS) + ["source_canonical_url", "flags", "uncertain_fields"]
        values = [json.dumps(cleaned[field], ensure_ascii=False) if field in {"flags", "uncertain_fields"} else cleaned[field] for field in columns]
        values.extend([now(), job_id])
        conn.execute(f"UPDATE jobs SET {','.join(field + '=?' for field in columns)},status='pending',approved_at=NULL,approved_by=NULL,review_needed=0,updated_at=? WHERE id=?", values)
        _provenance(conn, job_id, cleaned)
        _audit(conn, actor, "edited_for_review", job_id, {"duplicate_ids": duplicate_ids})
    return job_id


def transition_job(conn, job_id, action, actor, acknowledge=False):
    states = {"approve": "approved", "reject": "rejected", "archive": "archived", "expire": "expired"}
    if action not in states:
        raise ValueError("La acción solicitada no es válida.")
    if not _text(actor, 200):
        raise ValueError("Es necesario identificar al administrador.")
    with conn:
        db.editorial_lock(conn)
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise ValueError("La oferta no existe.")
        stamp = now()
        if action == "approve":
            if job['title'] == 'Aviso pendiente de transcripción':
                raise ValueError('Transcribí el puesto real de la fuente antes de aprobar. El título interno no puede publicarse.')
            if not application_url(job["application_url"]):
                raise ValueError("La aprobación requiere un enlace de postulación, WhatsApp o correo válido.")
            if job["expires_at"] and job["expires_at"] <= stamp:
                raise ValueError("La oferta ya venció; corregí la fecha antes de aprobarla.")
            if (_list(job["flags"]) or _list(job["uncertain_fields"]) or job["review_needed"]) and not acknowledge:
                raise ValueError("Revisá y reconocé las alertas, los posibles duplicados y los datos inciertos antes de aprobar.")
            # La procedencia nueva queda conservada hasta que un operador la revise.
            conn.execute("UPDATE jobs SET status='approved',approved_at=?,approved_by=?,review_needed=0,last_checked_at=?,updated_at=? WHERE id=?", (stamp, actor, stamp, stamp, job_id))
        else:
            conn.execute("UPDATE jobs SET status=?,approved_at=NULL,approved_by=NULL,review_needed=0,updated_at=? WHERE id=?", (states[action], stamp, job_id))
        _audit(conn, actor, action, job_id, {"acknowledged": bool(acknowledge), "previous_status": job["status"]})
    return job_id


def public_jobs(conn, filters=None):
    filters = filters or {}
    conditions = ["status='approved'", "(expires_at IS NULL OR expires_at > ?)"]
    values = [now()]
    # LIKE trata % y _ como comodines; se escapan para búsquedas literales.
    q = _text(filters.get("q"), 200)
    if q:
        pattern = "%" + _fold(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append("(fold(title) LIKE ? ESCAPE '\\' OR fold(company) LIKE ? ESCAPE '\\' OR fold(description) LIKE ? ESCAPE '\\' OR fold(requirements) LIKE ? ESCAPE '\\' OR fold(sector) LIKE ? ESCAPE '\\')")
        values.extend([pattern] * 5)
    for field in ("location", "sector", "modality", "schedule"):
        value = _text(filters.get(field), 200)
        if value:
            conditions.append('fold(' + field + ') = fold(?)')
            values.append(value)
    days = filters.get("days") or filters.get("date_days")
    if days:
        try:
            days = int(days)
        except (TypeError, ValueError) as exc:
            raise ValueError("El filtro de fecha debe indicar una cantidad de días.") from exc
        if not 1 <= days <= 3650:
            raise ValueError("El filtro de fecha debe estar entre 1 y 3650 días.")
        conditions.append("collected_at >= ?")
        values.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds"))
    rows = conn.execute("SELECT * FROM jobs WHERE " + " AND ".join(conditions) + " ORDER BY collected_at DESC,id DESC", values).fetchall()
    return [job_dict(row) for row in rows]


def public_job(conn, job_id):
    return job_dict(conn.execute("SELECT * FROM jobs WHERE id=? AND status='approved' AND (expires_at IS NULL OR expires_at>?)", (job_id, now())).fetchone())


def expire_jobs(conn, review_days=30):
    try:
        review_days = int(review_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("La antigüedad de revisión debe ser un número de días.") from exc
    if review_days < 1:
        raise ValueError("La antigüedad de revisión debe ser mayor a cero.")
    stamp = now()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=review_days)).isoformat(timespec="seconds")
    with conn:
        expired = conn.execute("SELECT id FROM jobs WHERE status IN ('pending','approved') AND expires_at IS NOT NULL AND expires_at<=?", (stamp,)).fetchall()
        for row in expired:
            conn.execute("UPDATE jobs SET status='expired',review_needed=0,approved_at=NULL,approved_by=NULL,updated_at=? WHERE id=?", (stamp, row["id"]))
            _audit(conn, "sistema", "explicit_expiration", row["id"])
        stale = conn.execute("SELECT id FROM jobs WHERE status='approved' AND expires_at IS NULL AND review_needed=0 AND COALESCE(last_checked_at,collected_at)<=?", (cutoff,)).fetchall()
        for row in stale:
            conn.execute("UPDATE jobs SET review_needed=1,updated_at=? WHERE id=?", (stamp, row["id"]))
            _audit(conn, "sistema", "age_review_requested", row["id"])
    return {"expired": len(expired), "review_requested": len(stale)}
