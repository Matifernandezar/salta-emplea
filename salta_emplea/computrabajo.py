"""Validación local de aportes manuales de Computrabajo.

Este módulo no visita enlaces, no consulta estados remotos y no contiene un
adaptador de API. Un aporte conserva sólo un resumen y su procedencia para el
circuito editorial existente.
"""

import re
from html import unescape
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


HOST = "ar.computrabajo.com"
RESEARCH_DATE = "2026-10-22"
ACCESS_REASON = (
    "No hay una API de lectura ni permisos de redistribución verificados para "
    "configurar la importación automática de Computrabajo. Podés aportar "
    "manualmente un resumen breve y el enlace original para revisión."
)


def is_computrabajo_offer(data: dict) -> bool:
    """Reconoce la procedencia declarada sin visitar ni validar su URL."""
    name = data.get("source_name")
    if isinstance(name, str) and name.strip().casefold().startswith("computrabajo"):
        return True
    value = data.get("source_url")
    if not isinstance(value, str):
        return False
    try:
        return urlsplit(value).hostname == HOST
    except ValueError:
        return False


def valid_original_url(value) -> str:
    """Devuelve el detalle original canónico; rechaza listados y otros hosts.

    Se quitan únicamente el fragmento y parámetros de seguimiento conocidos.
    Los demás parámetros, incluidos los repetidos o vacíos, se conservan.
    """
    error = "Usá el enlace HTTPS original de una oferta de ar.computrabajo.com."
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError(error)
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError(error)
    if re.search(r"%(?![0-9a-fA-F]{2})|%(?:0[0-9a-fA-F]|1[0-9a-fA-F]|7[fF]|5[cC])", value):
        raise ValueError(error)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(error) from exc
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname != HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not re.fullmatch(r"ar\.computrabajo\.com(?::443)?", parsed.netloc, re.IGNORECASE)
    ):
        raise ValueError(error)

    # Las búsquedas y listados comparten el host con los detalles. El marcador
    # público de detalle evita admitirlos como si fueran una oferta individual.
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    if not re.fullmatch(r"/ofertas-de-trabajo/oferta-de-trabajo-[^/]+", path):
        raise ValueError(error)
    decoded_path = unquote(path)
    if decoded_path.count("/") != 2 or any(part in {".", ".."} for part in decoded_path.split("/")):
        raise ValueError(error)
    if not decoded_path.removeprefix("/ofertas-de-trabajo/oferta-de-trabajo-").strip(".-"):
        raise ValueError(error)
    try:
        query = sorted(
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True, errors="strict")
            if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"}
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError(error) from exc
    return urlunsplit(("https", HOST, path, urlencode(query), ""))


def _brief_text(value, field, limit):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} debe ser texto plano.")
    value = value.strip()
    if not value:
        return None
    if len(value) > limit:
        raise ValueError(f"{field} de Computrabajo admite como máximo {limit} caracteres; escribí un resumen breve.")
    if re.search(r"</?[A-Za-z][^>]*>|<![A-Za-z-]|!\[[^\]]*\]\s*\(|data:image/", unescape(value), re.IGNORECASE):
        raise ValueError(f"{field} de Computrabajo debe contener sólo texto plano, sin HTML ni imágenes.")
    return value


def normalize_manual_offer(data: dict) -> dict:
    """Copia y valida un aporte manual sin completar datos no aportados.

    Una postulación explícita debe coincidir con el detalle original después
    de quitar seguimiento. Nunca se sustituye en silencio un contacto distinto.
    """
    normalized = dict(data)
    original = valid_original_url(data.get("source_url"))
    application = data.get("application_url")
    if application is not None and application != "":
        if valid_original_url(application) != original:
            raise ValueError("La postulación de Computrabajo debe usar el mismo enlace original de la oferta.")
    if any(data.get(field) for field in ("image_path", "image_url", "image", "images")):
        raise ValueError("Los aportes de Computrabajo no admiten imágenes; usá un resumen breve y el enlace original.")
    for field, limit in (("description", 600), ("requirements", 600), ("original_text", 2000)):
        if field in data:
            normalized[field] = _brief_text(data[field], field, limit)
    normalized.update(source_name="Computrabajo", source_url=original, application_url=original)
    return normalized


def access_state(source=None) -> dict:
    """Informa el acceso comprobado; los booleanos locales no lo habilitan."""
    last_run_at = None
    if source is not None:
        try:
            last_run_at = source["last_run_at"]
        except (KeyError, IndexError, TypeError):
            pass
    return {
        "state": "sin_configurar",
        "label": "Sin configurar",
        "automatic_available": False,
        "reason": ACCESS_REASON,
        "research_date": RESEARCH_DATE,
        "last_run_at": last_run_at,
        "next_run_at": None,
    }
