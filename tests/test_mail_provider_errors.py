"""Diagnóstico offline: datos ficticios y respuestas del proveedor sustituidas."""

from io import BytesIO
import json
from urllib.error import HTTPError

import pytest

from salta_emplea.mail_provider_errors import MAX_ERROR_BYTES, provider_error


PRIVATE = "PRUEBA-CLAVE-PRIVADA persona@example.test https://example.test/token-privado"


def error(code, payload):
    raw = json.dumps(payload).encode() if isinstance(payload, (dict, list)) else payload
    return HTTPError("https://example.test/proveedor", code, "PRUEBA: " + PRIVATE,
                     {}, BytesIO(raw) if raw is not None else None)


@pytest.mark.parametrize("code,name,message,expected", [
    (403, "restricted_api_key", PRIVATE, "La clave no está activa"),
    (403, "suspended_api_key", PRIVATE, "La clave está suspendida"),
    (403, "invalid_permission", PRIVATE, "Faltan permisos"),
    (403, "validation_error", "The example.test domain is not verified. " + PRIVATE, "dominio del remitente no figura verificado"),
    (403, "validation_error", "You can only send testing emails to your own email address. " + PRIVATE, "remitente de prueba"),
    (403, "validation_error", "This key is not authorized to send emails from example.test. " + PRIVATE, "dominio asignado a la clave"),
    (401, "missing_api_key", PRIVATE, "Revisar la clave de envío"),
    (401, "validation_error", PRIVATE, "Revisar la clave de envío"),
])
def test_causas_reconocidas_solo_devuelven_texto_fijo(code, name, message, expected):
    result = provider_error(error(code, {"statusCode": code, "name": name, "message": message}))
    assert result.startswith(f"Proveedor respondió HTTP {code}.")
    assert expected in result
    for value in (PRIVATE, "persona@example.test", "https://example.test", "token-privado", name):
        assert value not in result


@pytest.mark.parametrize("raw", [
    b"error code: 1010", b"<html><title>ERROR CODE: 1010</title></html>",
])
def test_1010_se_identifica_sin_interpretar_html(raw):
    result = provider_error(error(403, raw))
    assert "1010" in result and "User-Agent" in result
    assert "<html>" not in result


@pytest.mark.parametrize("code,payload", [
    (403, {"name": PRIVATE, "message": PRIVATE}),
    (403, {"name": "validation_error", "message": PRIVATE}),
    (403, {"statusCode": 401, "name": "restricted_api_key"}),
    (403, {"statusCode": "403", "name": "restricted_api_key"}),
    (401, {"name": "suspended_api_key"}),
    (500, {"name": "suspended_api_key"}),
    (403, {"name": "validation_error", "message": [PRIVATE]}),
    (403, [PRIVATE]),
    (403, b'{"name": "restricted_api_key", "name": "suspended_api_key"}'),
    (403, b"\xff"),
    (403, b"{json incompleto"),
    (403, None),
    (403, b"error code: 10101"),
    (401, b"error code: 1010"),
])
def test_desconocidos_o_incoherentes_conservan_solo_estado_y_ayuda(code, payload):
    result = provider_error(error(code, payload))
    assert result == f"Proveedor respondió HTTP {code}. Revisá el motivo en Resend → Logs antes de volver a intentar."


def test_no_lee_mas_del_limite_y_descarta_cuerpo_excesivo():
    class Bounded(BytesIO):
        def read(self, size):
            assert size == MAX_ERROR_BYTES + 1
            return b"error code: 1010".ljust(size, b" ")

    result = provider_error(HTTPError("https://example.test", 403, PRIVATE, {}, Bounded()))
    assert "Resend → Logs" in result and "1010" not in result


@pytest.mark.parametrize("exception", [OSError(PRIVATE), ValueError(PRIVATE), RuntimeError(PRIVATE)])
def test_lectura_fallida_no_expone_error_ni_cambia_diagnostico(exception):
    class Broken(BytesIO):
        def read(self, _size):
            raise exception

    result = provider_error(HTTPError("https://example.test", 403, PRIVATE, {}, Broken()))
    assert result == "Proveedor respondió HTTP 403. Revisá el motivo en Resend → Logs antes de volver a intentar."


@pytest.mark.parametrize("exception", [KeyboardInterrupt(), SystemExit(1)])
def test_interrupciones_no_se_ocultan(exception):
    class Interrupted(BytesIO):
        def read(self, _size):
            raise exception

    with pytest.raises(type(exception)):
        provider_error(HTTPError("https://example.test", 403, PRIVATE, {}, Interrupted()))
