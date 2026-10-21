"""Diagnósticos cerrados de Resend; nunca conservar su respuesta externa.

Solo se inspecciona un cuerpo acotado para elegir textos escritos aquí. Los
nombres, mensajes, dominios y demás datos del proveedor no se interpolan.
"""

import json
import re
from urllib.error import HTTPError


MAX_ERROR_BYTES = 8192
_FALLBACK = " Revisá el motivo en Resend → Logs antes de volver a intentar."


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Respuesta ambigua.")
        result[key] = value
    return result


def provider_error(exc: HTTPError) -> str:
    """Clasifica sin registrar cuerpos, ejecutar instrucciones ni reintentar.

    La respuesta no permite inferir recepción del correo. Si el proveedor no
    aporta una causa reconocida y coherente, se conserva solo el estado HTTP.
    """
    code = exc.code
    if type(code) is not int or not 100 <= code <= 599:
        return "Proveedor respondió un error HTTP." + _FALLBACK
    prefix = f"Proveedor respondió HTTP {code}."
    fallback = prefix + _FALLBACK
    try:
        raw = exc.read(MAX_ERROR_BYTES + 1)
        if not isinstance(raw, bytes) or len(raw) > MAX_ERROR_BYTES:
            return fallback
        text = raw.decode("utf-8")
        try:
            data = json.loads(text, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            # Error documentado de la capa HTTP, sin interpretar HTML.
            if code == 403 and re.search(r"\berror\s+code:\s*1010\b", text, re.IGNORECASE):
                return prefix + " La capa HTTP rechazó el cliente (1010). Revisar la cabecera User-Agent."
            return fallback
        if not isinstance(data, dict):
            return fallback
        reported = data.get("statusCode", code)
        if type(reported) is not int or reported != code:
            return fallback
        name = data.get("name")
        if not isinstance(name, str):
            return fallback
        if code == 401 and name in {"missing_api_key", "validation_error"}:
            return prefix + " Revisar la clave de envío configurada en Vercel y su estado en Resend."
        if code != 403:
            return fallback
        descriptions = {
            "restricted_api_key": " La clave no está activa o no tiene el alcance requerido. Revisar su estado y dominio autorizado en Resend.",
            "suspended_api_key": " La clave está suspendida. Revisar la cuenta y contactar al soporte de Resend.",
            "invalid_permission": " Faltan permisos para enviar. Revisar el permiso de envío de la credencial en Resend.",
        }
        if name in descriptions:
            return prefix + descriptions[name]
        message = data.get("message")
        if name != "validation_error" or not isinstance(message, str):
            return fallback
        message = message.casefold()
        if "you can only send testing emails to your own email address" in message:
            return prefix + " El proveedor está aplicando restricciones del remitente de prueba. Usar un remitente del dominio propio verificado."
        if "domain is not verified" in message:
            return prefix + " El dominio del remitente no figura verificado para esta cuenta. Revisar su coincidencia exacta en Resend."
        if "not authorized to send emails from" in message:
            return prefix + " La clave no está autorizada para el dominio del remitente. Revisar el dominio asignado a la clave."
    except Exception:
        # Un diagnóstico no cambia una entrega rechazada a incierta ni revela
        # detalles de lectura, codificación o datos devueltos por el proveedor.
        return fallback
    return fallback
