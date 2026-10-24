"""Transcripción opcional y preparación conservadora de avisos externos.

Este módulo no lee credenciales del entorno, no programa tareas ni publica.
El caller debe habilitar el proveedor expresamente antes de llamar a OCR.
Los avisos, incluidos sus enlaces e instrucciones, se tratan sólo como texto.
"""

import base64
import json
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .domain import application_url


VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_ERROR_RESPONSE_BYTES = 64 * 1024
MAX_TEXT_CHARS = 20000
REQUEST_TIMEOUT = 20

_ERROR_MESSAGES = {
    "anthropic_credentials_rejected": "Claude rechazó el acceso. Revisá ANTHROPIC_API_KEY y los permisos de la clave en Vercel.",
    "anthropic_billing_rejected": "Claude rechazó la facturación. Revisá el saldo y los límites de tu cuenta de Anthropic.",
    "anthropic_model_rejected": "El modelo de Claude no está disponible. Revisá ANTHROPIC_MODEL y el acceso de tu cuenta.",
    "not_configured": "La lectura de imágenes no está configurada.",
    "invalid_image": "La imagen debe ser JPEG, PNG o WebP.",
    "image_too_large": "La imagen excede el máximo de 4 MB.",
    "invalid_response": "El proveedor devolvió una respuesta que requiere revisión.",
    "response_too_large": "La respuesta del proveedor excede el máximo permitido.",
    "redirect_rejected": "El proveedor intentó redirigir la solicitud.",
    "credentials_rejected": "Google rechazó el acceso. Revisá que Cloud Vision API y la facturación estén activas en el proyecto de la clave, y comprobá sus restricciones.",
    "api_key_invalid": "Google indicó que la clave no es válida. Revisá GOOGLE_VISION_API_KEY en Vercel y redesplegá la aplicación.",
    "api_key_expired": "Google indicó que la clave venció. Reemplazá GOOGLE_VISION_API_KEY en Vercel y redesplegá la aplicación.",
    "api_key_restricted": "Las restricciones de la clave impiden usar Vision. Revisá en Google Cloud que permitan Cloud Vision API y llamadas desde el servidor de Vercel.",
    "service_disabled": "Cloud Vision API está deshabilitada para el proyecto de la clave. Habilitala en ese proyecto de Google Cloud.",
    "billing_disabled": "Google indicó que la facturación del proyecto de la clave está deshabilitada. Revisá su cuenta de facturación en Google Cloud.",
    "quota_exceeded": "El proveedor indicó un límite de uso.",
    "provider_unavailable": "El proveedor no está disponible.",
    "provider_rejected": "El proveedor no pudo procesar la imagen.",
    "network_error": "No se pudo completar la conexión con el proveedor.",
    "timeout": "La lectura de la imagen superó el tiempo máximo.",
    "invalid_text": "El texto recibido no tiene un formato válido.",
}

# Estos rechazos pueden volver a intentarse únicamente mediante una acción
# explícita, una vez corregida la configuración. No implican un reintento
# automático ni permiten deducir nada del texto libre recibido del proveedor.
REJECTED_CODES = frozenset({
    "anthropic_credentials_rejected", "anthropic_billing_rejected", "anthropic_model_rejected",
    "credentials_rejected", "api_key_invalid", "api_key_expired",
    "api_key_restricted", "service_disabled", "billing_disabled",
})

_GOOGLE_REJECTION_REASONS = {
    "API_KEY_INVALID": "api_key_invalid",
    "API_KEY_EXPIRED": "api_key_expired",
    "API_KEY_SERVICE_BLOCKED": "api_key_restricted",
    "API_KEY_HTTP_REFERRER_BLOCKED": "api_key_restricted",
    "API_KEY_IP_ADDRESS_BLOCKED": "api_key_restricted",
    "API_KEY_ANDROID_APP_BLOCKED": "api_key_restricted",
    "API_KEY_IOS_APP_BLOCKED": "api_key_restricted",
    "SERVICE_DISABLED": "service_disabled",
    "BILLING_DISABLED": "billing_disabled",
}


class ExtractionError(Exception):
    """Error con código y mensaje fijos; nunca incorpora respuestas ni secretos."""

    def __init__(self, code):
        self.code = code if code in _ERROR_MESSAGES else "provider_rejected"
        super().__init__(_ERROR_MESSAGES[self.code])


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _image_format(image):
    if image.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(image) >= 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "webp"
    return None


def _http_error(code):
    if code in {301, 302, 303, 307, 308}:
        return "redirect_rejected"
    if code in {401, 403}:
        return "credentials_rejected"
    if code == 429:
        return "quota_exceeded"
    if isinstance(code, int) and 500 <= code < 600:
        return "provider_unavailable"
    return "provider_rejected"


def _fold(value):
    return " ".join("".join(
        character for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold().split())


def _external_instructions(text):
    folded = _fold(text)
    patterns = (
        r"\b(?:ignore|disregard|ignora|ignorar|ignoren|omite|omiti)\b.{0,100}"
        r"\b(?:instrucciones|instructions|sistema|system|previous|anteriores)\b",
        r"\b(?:system prompt|developer message|mensaje de sistema)\b",
        r"\b(?:ejecuta|ejecutar|execute|run)\b.{0,80}"
        r"(?:comando|command|shell|curl|wget|subprocess|os\.system)",
        r"\b(?:publica|aprueba|approve|publish)\b.{0,80}"
        r"(?:sin revision|automaticamente|directamente|without review)",
    )
    return any(re.search(pattern, folded) for pattern in patterns)


def _valid_text(text):
    return not any(
        (ord(character) < 32 and character not in "\t\r\n")
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in text
    )


def _complete_prefix(text):
    """Nunca convierte una línea cortada en un contacto aparentemente válido."""
    prefix = text[:MAX_TEXT_CHARS]
    return prefix if len(text) <= MAX_TEXT_CHARS or prefix.endswith("\n") else prefix.rpartition("\n")[0]


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _invalid_json_constant(value):
    raise ValueError("invalid_constant")


def _provider_rejection(error, fallback="provider_rejected"):
    """Clasifica exclusivamente ErrorInfo oficiales; descarta texto y metadata.

    Los códigos numéricos del cuerpo corresponden al proveedor, no al estado
    HTTP. Tampoco se buscan palabras dentro de mensajes, URLs o metadatos.
    """
    if not isinstance(error, dict) or not isinstance(error.get("details"), list):
        return fallback
    codes = set()
    for detail in error["details"]:
        if not isinstance(detail, dict):
            continue
        if (detail.get("@type") != "type.googleapis.com/google.rpc.ErrorInfo"
                or detail.get("domain") != "googleapis.com"):
            continue
        reason = detail.get("reason")
        if not isinstance(reason, str) or reason not in _GOOGLE_REJECTION_REASONS:
            continue
        codes.add(_GOOGLE_REJECTION_REASONS[reason])
    return next(iter(codes)) if len(codes) == 1 else fallback


def _http_response_error(response, status):
    """Lee como máximo 64 KiB más un byte testigo, sin exponer el cuerpo."""
    fallback = _http_error(status)
    if not isinstance(status, int) or status < 400:
        return fallback
    try:
        raw = response.read(MAX_ERROR_RESPONSE_BYTES + 1)
        if not isinstance(raw, bytes) or len(raw) > MAX_ERROR_RESPONSE_BYTES:
            return fallback
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object,
                             parse_constant=_invalid_json_constant)
        if isinstance(payload, dict):
            return _provider_rejection(payload.get("error"), fallback)
    except Exception:
        # El error HTTP ya está confirmado. Un cuerpo ilegible, vacío o que
        # falla al leer no lo convierte en un fallo ambiguo de transporte.
        pass
    return fallback


def extract_image(image_bytes, api_key, *, opener=None):
    """Transcribe una imagen mediante una única solicitud explícita de Vision.

    No sigue redirecciones ni reintenta. ``opener`` permite sustituir todo el
    transporte en pruebas; admite una función o un objeto con método ``open``.
    La credencial se envía sólo por encabezado al endpoint fijo de Google.
    """
    if not isinstance(api_key, str) or not api_key or len(api_key) > 512:
        raise ExtractionError("not_configured")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", api_key):
        raise ExtractionError("not_configured")
    if not isinstance(image_bytes, bytes) or not _image_format(image_bytes):
        raise ExtractionError("invalid_image")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ExtractionError("image_too_large")

    body = json.dumps({"requests": [{
        "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
        "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
        "imageContext": {"languageHints": ["es"]},
    }]}, separators=(",", ":")).encode("utf-8")
    request = Request(VISION_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Goog-Api-Key": api_key,
    })
    transport = opener if opener is not None else build_opener(_NoRedirect())
    open_request = transport.open if hasattr(transport, "open") else transport
    try:
        with open_request(request, timeout=REQUEST_TIMEOUT) as response:
            status = response.getcode()
            if status != 200:
                raise ExtractionError(_http_response_error(response, status))
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except ExtractionError:
        raise
    except HTTPError as exc:
        code = _http_response_error(exc, exc.code)
        exc.close()
        raise ExtractionError(code) from None
    except TimeoutError:
        raise ExtractionError("timeout") from None
    except URLError as exc:
        code = "timeout" if isinstance(exc.reason, TimeoutError) else "network_error"
        raise ExtractionError(code) from None
    except Exception:
        raise ExtractionError("network_error") from None

    if not isinstance(raw, bytes):
        raise ExtractionError("invalid_response")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ExtractionError("response_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object,
                             parse_constant=_invalid_json_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ExtractionError("invalid_response") from None
    if not isinstance(payload, dict):
        raise ExtractionError("invalid_response")
    if "error" in payload:
        code = _provider_rejection(payload["error"]) if len(raw) <= MAX_ERROR_RESPONSE_BYTES else "provider_rejected"
        raise ExtractionError(code)
    responses = payload.get("responses")
    if not isinstance(responses, list) or len(responses) != 1 or not isinstance(responses[0], dict):
        raise ExtractionError("invalid_response")
    item = responses[0]
    if "error" in item:
        code = _provider_rejection(item["error"]) if len(raw) <= MAX_ERROR_RESPONSE_BYTES else "provider_rejected"
        raise ExtractionError(code)
    annotation = item.get("fullTextAnnotation", {})
    if not isinstance(annotation, dict):
        raise ExtractionError("invalid_response")
    text = annotation.get("text", "")
    if not isinstance(text, str) or not _valid_text(text):
        raise ExtractionError("invalid_response")
    warnings = []
    if len(text) > MAX_TEXT_CHARS:
        text = _complete_prefix(text)
        warnings.append("text_truncated")
    elif not text.strip():
        warnings.append("no_text_detected")
    if _external_instructions(text):
        warnings.append("external_instructions")
    return {"text": text, "provider": "google_vision", "warnings": warnings}


_LABELS = {
    "puesto": "title", "empresa": "company", "localidad": "location",
    "rubro": "sector", "jornada": "schedule", "contratacion": "contract_type",
    "requisitos": "requirements", "descripcion": "description", "modalidad": "modality",
    "postulacion": "application_url", "postularse": "application_url",
    "correo": "application_url", "email": "application_url", "whatsapp": "application_url",
}
_FIELD_LIMITS = {
    "title": 200, "company": 2048, "location": 2048, "sector": 2048,
    "schedule": 2048, "contract_type": 2048, "requirements": MAX_TEXT_CHARS,
    "description": MAX_TEXT_CHARS, "modality": 32, "application_url": 2048,
}
_NEVER_INFERRED = (
    "salary_amount", "salary_currency", "salary_period", "original_date", "expires_at",
)
_MISSING_VALUES = {"no informado", "no informada", "sin datos", "a confirmar", "?", "-", "—", "n/a"}


def _label(line):
    match = re.match(r"^\s*([^:\n]{1,32}):\s*(.*?)\s*$", line)
    if match:
        label = _fold(match[1])
        if label in _LABELS:
            return label, match[2]
    return None


def _contact(value, label):
    """Sólo convierte un correo o teléfono completo, sin completar sus datos."""
    if label in {"correo", "email"} or "@" in value and not value.lower().startswith("https://"):
        candidate = value if value.lower().startswith("mailto:") else "mailto:" + value
        if label == "whatsapp":
            return None
    elif value.startswith("+"):
        if not re.fullmatch(r"\+[1-9][0-9 ()-]{5,30}[0-9]", value):
            return None
        number = re.sub(r"[ ()-]", "", value[1:])
        if not re.fullmatch(r"[1-9][0-9]{6,14}", number):
            return None
        candidate = "https://wa.me/" + number
    else:
        candidate = value
    try:
        validated = application_url(candidate)
    except ValueError:
        return None
    if not validated:
        return None
    if label in {"correo", "email"} and not validated.startswith("mailto:"):
        return None
    if label == "whatsapp" and urlsplit(validated).hostname not in {"wa.me", "www.wa.me"}:
        return None
    return validated


def prepare_text(text):
    """Propone campos únicamente desde etiquetas o una línea literal de búsqueda.

    ``evidence`` conserva las líneas recibidas. Un campo ausente, contradictorio
    o inválido se omite y se marca en ``uncertain_fields``. Sueldos y fechas no se
    deducen. La descripción puede ser la transcripción, con revisión señalada.
    """
    if not isinstance(text, str) or not _valid_text(text):
        raise ExtractionError("invalid_text")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    truncated = len(text) > MAX_TEXT_CHARS
    lines = _complete_prefix(text).splitlines()
    text = text[:MAX_TEXT_CHARS]
    records = {}
    title_candidates = []
    continuation_indices = set()
    for index, line in enumerate(lines):
        if index in continuation_indices:
            continue
        parsed = _label(line)
        if parsed:
            label, value = parsed
            field = _LABELS[label]
            original = [line]
            if field in {"requirements", "description"}:
                continuation = []
                for following_index, following in enumerate(lines[index + 1:], index + 1):
                    if _label(following):
                        break
                    continuation.append(following)
                    continuation_indices.add(following_index)
                value = "\n".join([value, *continuation]).strip()
                original.extend(continuation)
            records.setdefault(field, []).append((value, "\n".join(original), label))
        else:
            match = re.match(r"^\s*(?:Buscamos|Se busca|Se buscan)(?:\s*[:-]\s*|\s+)(.+?)\s*$", line, re.I)
            if match:
                title_candidates.append((match[1], line, "puesto"))
    if "title" not in records and title_candidates:
        records["title"] = title_candidates

    fields, evidence, uncertain = {}, {}, []
    for field, limit in _FIELD_LIMITS.items():
        entries = records.get(field, [])
        candidates = []
        invalid = not entries
        for value, literal, label in entries:
            if not value or len(value) > limit or _fold(value) in _MISSING_VALUES:
                invalid = True
                continue
            candidate = value
            if field == "modality":
                candidate = {"presencial": "presencial", "hibrida": "híbrida", "hibrido": "híbrida",
                             "remota": "remota", "remoto": "remota"}.get(_fold(value))
            elif field == "application_url":
                candidate = _contact(value, label)
            if not candidate:
                invalid = True
            else:
                candidates.append((candidate, literal))
        unique = {value for value, _ in candidates}
        if invalid or len(unique) != 1:
            uncertain.append(field)
            continue
        fields[field] = candidates[0][0]
        evidence[field] = "\n".join(dict.fromkeys(literal for _, literal in candidates))

    if "description" not in fields and text.strip():
        fields["description"] = text.strip()
        evidence["description"] = text.strip()
    if truncated and "description" not in uncertain:
        uncertain.append("description")
    uncertain.extend(_NEVER_INFERRED)
    if _external_instructions(text):
        uncertain.append("external_instructions")
    return {"fields": fields, "evidence": evidence, "uncertain_fields": uncertain}
