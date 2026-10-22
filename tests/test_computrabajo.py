"""Datos manuales ficticios: no representan respuestas ni acceso a una API."""

import socket
import sqlite3
import urllib.request

import pytest

from salta_emplea import computrabajo


DETAIL = "https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-prueba-ficticia-123"


def manual_offer(**changes):
    data = {
        "title": "PRUEBA LOCAL — Puesto ficticio",
        "description": "Resumen ficticio para validar el aporte manual; no postularse.",
        "source_url": DETAIL,
    }
    data.update(changes)
    return data


@pytest.mark.parametrize("source_url", [DETAIL, DETAIL.replace("ar.computrabajo.com", "AR.COMPUTRABAJO.COM"), "https://ar.computrabajo.com/trabajo-en-salta"])
def test_recognizes_exact_source_host_without_claiming_valid_detail(source_url):
    assert computrabajo.is_computrabajo_offer({"source_url": source_url})


@pytest.mark.parametrize("source_url", [
    "https://ar.computrabajo.com.ejemplo.invalid/ofertas-de-trabajo/oferta-de-trabajo-falsa",
    "https://falsoar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-falsa",
    "https://ejemplo.invalid/?origen=ar.computrabajo.com",
    "https://ar.computrabajo.com%2e.ejemplo.invalid/",
    "https://[host-invalido/", None,
])
def test_detection_does_not_accept_suffix_hosts(source_url):
    assert not computrabajo.is_computrabajo_offer({"source_url": source_url})


def test_declared_name_also_enforces_source_policy():
    assert computrabajo.is_computrabajo_offer({"source_name": " Computrabajo · aporte manual ", "source_url": "https://ejemplo.invalid/"})
    with pytest.raises(ValueError):
        computrabajo.normalize_manual_offer(manual_offer(source_name="Computrabajo", source_url="https://ejemplo.invalid/"))


def test_canonical_original_removes_tracking_but_preserves_identity_parameters():
    supplied = DETAIL.replace("ar.computrabajo.com", "AR.COMPUTRABAJO.COM:443") + "/?utm_source=prueba&ID=7&fbclid=a&gclid=b&UTM_MEDIUM=local&id=9&id=8&v=#fragmento"
    assert computrabajo.valid_original_url(supplied) == DETAIL + "?ID=7&id=9&id=8&v="


def test_unknown_parameter_order_and_representation_are_part_of_identity():
    first = DETAIL + "?id=2&id=1&v=&flag&text=a%20b&UTM_SOURCE=prueba&z=+"
    second = DETAIL + "?id=1&id=2&v=&flag&text=a%20b&z=+"
    assert computrabajo.valid_original_url(first) == DETAIL + "?id=2&id=1&v=&flag&text=a%20b&z=+"
    assert computrabajo.valid_original_url(first) != computrabajo.valid_original_url(second)
    with pytest.raises(ValueError, match="mismo enlace original"):
        computrabajo.normalize_manual_offer(manual_offer(source_url=first, application_url=second))


def test_only_tracking_parameters_are_removed_even_when_keys_are_encoded():
    supplied = DETAIL + "?id=2&utm%5Fsource=prueba&&id=1&%66bclid=prueba&v&gclid=prueba"
    assert computrabajo.valid_original_url(supplied) == DETAIL + "?id=2&&id=1&v"


@pytest.mark.parametrize("url", [
    None, "", "http://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-falsa",
    "https://ar.computrabajo.com/", "https://ar.computrabajo.com/ofertas-de-trabajo/",
    "https://ar.computrabajo.com/ofertas-de-trabajo/empleos-en-salta",
    "https://ar.computrabajo.com/trabajo-en-salta",
    "https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-",
    "https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-...",
    DETAIL + "/otra", DETAIL + "//", DETAIL + "%2f..",
    DETAIL.replace("https://", "https://usuario:clave@"),
    DETAIL.replace("https://", "https://@"),
    DETAIL.replace(".com/", ".com:444/"), DETAIL.replace(".com/", ".com:80/"),
    DETAIL.replace(".com/", ".com./"), DETAIL.replace(".com/", ".com%2e/"),
    DETAIL.replace(".com/", ".com.ejemplo.invalid/"),
    DETAIL.replace(".com/", ".com\\@ejemplo.invalid/"),
    "\n" + DETAIL, DETAIL + "\t", DETAIL + "%0d%0a", DETAIL + "%5c", DETAIL + "%zz",
    DETAIL + "?dato=%FF", "javascript:alert(1)", "mailto:pruebas@example.org",
])
def test_original_url_fails_closed(url):
    with pytest.raises(ValueError):
        computrabajo.valid_original_url(url)


def test_manual_normalizer_copies_and_never_invents_missing_fields():
    supplied = manual_offer(source_name="Computrabajo · aporte", source_url=DETAIL + "?utm_source=prueba")
    before = dict(supplied)
    result = computrabajo.normalize_manual_offer(supplied)
    assert supplied == before and result is not supplied
    assert result["source_name"] == "Computrabajo"
    assert result["source_url"] == result["application_url"] == DETAIL
    for missing in ("company", "salary_amount", "salary_currency", "original_date", "expires_at", "last_checked_at", "location", "status"):
        assert missing not in result


def test_matching_application_tracking_is_canonicalized():
    result = computrabajo.normalize_manual_offer(manual_offer(application_url=DETAIL + "?utm_medium=prueba#postular"))
    assert result["application_url"] == DETAIL


@pytest.mark.parametrize("application_url", [
    DETAIL + "-otra", DETAIL + "?id=otra", "https://example.org/postularse",
    "mailto:pruebas@example.org", "https://wa.me/5493871234567",
])
def test_distinct_explicit_application_link_is_rejected(application_url):
    with pytest.raises(ValueError):
        computrabajo.normalize_manual_offer(manual_offer(application_url=application_url))


@pytest.mark.parametrize("field,limit", [("description", 600), ("requirements", 600), ("original_text", 2000)])
def test_brief_text_limits_reject_without_truncating(field, limit):
    assert computrabajo.normalize_manual_offer(manual_offer(**{field: "a" * limit}))[field] == "a" * limit
    with pytest.raises(ValueError, match=str(limit)):
        computrabajo.normalize_manual_offer(manual_offer(**{field: "a" * (limit + 1)}))


@pytest.mark.parametrize("field", ["description", "requirements", "original_text"])
@pytest.mark.parametrize("value", ["<p>Texto ficticio</p>", "&lt;img src='prueba'&gt;", "![imagen](https://example.org/foto.png)", "data:image/png;base64,ficticio", {"html": "ficticio"}])
def test_manual_text_rejects_html_and_images(field, value):
    with pytest.raises(ValueError):
        computrabajo.normalize_manual_offer(manual_offer(**{field: value}))


@pytest.mark.parametrize("field", ["image_path", "image_url", "image", "images"])
def test_manual_offer_refuses_images(field):
    with pytest.raises(ValueError, match="imágenes"):
        computrabajo.normalize_manual_offer(manual_offer(**{field: "imagen-ficticia"}))


def test_short_existing_plain_evidence_is_preserved():
    evidence = "Evidencia ficticia breve: el original informa jornada parcial."
    data = manual_offer(original_text=evidence, company="Empresa ficticia declarada", original_date="2026-10-21")
    result = computrabajo.normalize_manual_offer(data)
    assert result["original_text"] == evidence
    assert result["company"] == data["company"]
    assert result["original_date"] == data["original_date"]


def test_access_state_is_unconfigured_even_if_local_flags_claim_active_or_closed():
    expected = computrabajo.access_state()
    assert expected == {
        "state": "sin_configurar", "label": "Sin configurar", "automatic_available": False,
        "reason": computrabajo.ACCESS_REASON, "research_date": "2026-10-22",
        "last_run_at": None, "next_run_at": None,
    }
    for status in ("active", "closed", "approved"):
        source = {"status": status, "authorized": True, "enabled": True, "automatic_available": True}
        assert computrabajo.access_state(source) == expected
    assert "manualmente" in expected["reason"]


def test_access_state_only_preserves_existing_last_run_in_mapping_and_sqlite_row():
    stamp = "2026-10-21T12:00:00+00:00"
    assert computrabajo.access_state({"last_run_at": stamp, "next_run_at": stamp})["last_run_at"] == stamp
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT ? AS last_run_at", (stamp,)).fetchone()
        state = computrabajo.access_state(row)
        assert state["last_run_at"] == stamp and state["next_run_at"] is None


def test_all_operations_are_offline_and_do_not_infer_remote_status(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("La validación manual no debe usar DNS ni HTTP.")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert computrabajo.is_computrabajo_offer(manual_offer())
    assert computrabajo.valid_original_url(DETAIL) == DETAIL
    assert computrabajo.normalize_manual_offer(manual_offer())["application_url"] == DETAIL
    assert computrabajo.access_state({"status": "closed"})["automatic_available"] is False
