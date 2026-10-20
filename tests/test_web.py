"""Circuitos HTTP reales con datos ficticios y SQLite temporal, sin enviar correos."""

import io
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash

from salta_emplea import db, domain, mailer
from salta_emplea.app import create_app


PASSWORD = "contraseña-exclusiva-de-pruebas"


class Elements(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.items = []
        self.feed(response.get_data(as_text=True))

    def attrs(self, tag):
        return [attrs for name, attrs in self.items if name == tag]

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "clave-de-pruebas-web-sin-uso-en-produccion",
        "ADMIN_PASSWORD_HASH": generate_password_hash(PASSWORD),
        "APP_ENV": "development",
        "DATABASE_PATH": str(tmp_path / "web-prueba.sqlite3"),
        "UPLOAD_DIR": str(tmp_path / "imagenes-privadas"),
        "PUBLIC_BASE_URL": "https://empleos.example.org",
        "RESEND_API_KEY": "",
        "MAIL_FROM": "",
    })
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def conn(app):
    connection = db.connect(app.config["DATABASE_PATH"])
    yield connection
    connection.close()


def offer(**changes):
    data = {
        "title": "PRUEBA — Atención en comercio",
        "company": "Comercio ficticio de pruebas",
        "location": "Salta Capital",
        "modality": "presencial",
        "sector": "Comercio",
        "schedule": "Jornada completa",
        "description": "Aviso ficticio exclusivo de pruebas automatizadas.",
        "requirements": "Requisito ficticio informado por la fuente de prueba.",
        "application_url": "https://example.org/postularse/prueba",
        "source_name": "Fuente ficticia de pruebas",
        "source_url": "https://example.org/avisos/prueba",
        "original_text": "Original ficticio: atención en comercio. No postularse.",
    }
    data.update(changes)
    return data


def create_offer(conn, approved=False, **changes):
    job_id, _ = domain.create_job(conn, offer(**changes), actor="administrador")
    if approved:
        domain.transition_job(conn, job_id, "approve", "administrador", acknowledge=True)
    return job_id


def csrf(client, path="/publicar"):
    with client.session_transaction() as state:
        existing = state.get("csrf")
    if existing:
        return existing
    response = client.get(path)
    assert response.status_code == 200
    tokens = [item["value"] for item in Elements(response).attrs("input")
              if item.get("name") == "csrf_token"]
    assert tokens, "El formulario debe incluir su token CSRF."
    return tokens[0]


def post(client, path, data=None, **kwargs):
    return client.post(path, data={"csrf_token": csrf(client), **(data or {})}, **kwargs)


def login(client):
    response = post(client, "/admin/ingresar", {"password": PASSWORD})
    assert response.status_code == 302
    assert urlsplit(response.location).path == "/admin"
    return client


@pytest.fixture
def admin(client):
    return login(client)


def record(conn, job_id):
    return dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def test_empty_installation_has_public_pages_and_no_demonstration_jobs(client, conn):
    for path in ("/", "/publicar", "/alertas", "/privacidad", "/condiciones", "/admin/ingresar"):
        assert client.get(path).status_code == 200, path
    assert client.get("/salud").json == {"status": "ok"}
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_review_compares_received_versions_without_overwriting_prepared_offer(admin, conn):
    job_id = create_offer(conn, approved=True)
    changed = offer(
        company='<script>Empresa externa de prueba</script>',
        application_url='https://example.org/nueva-postulacion',
        requirements=None,
        original_text='Cambio ficticio recibido de la fuente; requiere nueva revisión.',
    )
    domain.create_job(conn, changed, actor='recopilador_autorizado')
    response = admin.get(f'/admin/ofertas/{job_id}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'La fuente cambió datos o retiró información.' in html
    assert 'Historial de procedencia y versiones recibidas' in html
    assert '&lt;script&gt;Empresa externa de prueba&lt;/script&gt;' in html
    assert '<script>' not in html
    assert 'https://example.org/nueva-postulacion' in html
    assert 'No informado' in html
    fields = {item.get('name'): item.get('value') for item in Elements(response).attrs('input')}
    assert fields['application_url'] == offer()['application_url']
    assert record(conn, job_id)['status'] == 'pending'
    assert admin.get(f'/ofertas/{job_id}').status_code == 404


def test_link_only_intake_requires_real_title_before_approval(client, conn):
    response = post(client, '/publicar', {'source_url': 'https://example.org/aviso-sin-extraer', 'consent': '1'})
    assert response.status_code == 200
    pending = conn.execute('SELECT * FROM jobs').fetchone()
    assert pending['status'] == 'pending' and pending['title'] == 'Aviso pendiente de transcripción'
    with pytest.raises(ValueError, match='puesto real'):
        domain.transition_job(conn, pending['id'], 'approve', 'administrador', acknowledge=True)
    assert not domain.public_jobs(conn)


def test_pending_offer_is_hidden_and_approved_offer_is_public(client, conn):
    pending = create_offer(conn)
    response = client.get("/")
    assert offer()["title"] not in response.get_data(as_text=True)
    assert client.get(f"/ofertas/{pending}").status_code == 404
    domain.transition_job(conn, pending, "approve", "administrador")
    assert offer()["title"] in client.get("/").get_data(as_text=True)
    detail = client.get(f"/ofertas/{pending}")
    assert detail.status_code == 200
    assert "No informado" in detail.get_data(as_text=True)
    assert "No necesitás una cuenta" in detail.get_data(as_text=True)


@pytest.mark.parametrize("path", [
    "/admin", "/admin/nueva", "/admin/ofertas/1", "/admin/imagenes/1",
    "/admin/fuentes", "/admin/publicidad", "/admin/configuracion",
])
def test_every_private_get_requires_admin(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert urlsplit(response.location).path == "/admin/ingresar"


@pytest.mark.parametrize("path", [
    "/admin/nueva", "/admin/ofertas/1", "/admin/ofertas/1/approve",
    "/admin/ofertas/1/reject", "/admin/ofertas/1/archive", "/admin/ofertas/1/expire",
    "/admin/fuentes", "/admin/publicidad", "/admin/configuracion", "/admin/salir",
])
def test_private_posts_cannot_be_forged_by_public_visitor(client, conn, path):
    job_id = create_offer(conn)
    assert job_id == 1
    response = post(client, path, offer(status="approved", acknowledge="1"))
    assert response.status_code == 302
    assert urlsplit(response.location).path == "/admin/ingresar"
    assert record(conn, job_id)["status"] == "pending"
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM ads").fetchone()[0] == 0


def test_login_requires_password_and_csrf_then_rotates_session(client):
    token = csrf(client)
    assert client.post("/admin/ingresar", data={"password": PASSWORD}).status_code == 400
    assert post(client, "/admin/ingresar", {"password": "incorrecta"}).status_code == 200
    assert client.get("/admin").status_code == 302
    login(client)
    assert client.get("/admin").status_code == 200
    assert csrf(client) != token
    assert post(client, "/admin/salir").status_code == 302
    assert client.get("/admin").status_code == 302


def test_admin_workflow_creates_edits_approves_and_withdraws_material_change(admin, conn):
    response = post(admin, "/admin/nueva", offer(
        status="approved", approved_by="atacante", approved_at="2000-01-01",
        collected_at="2000-01-01", last_checked_at="2000-01-01",
    ))
    assert response.status_code == 302
    edit_path = urlsplit(response.location).path
    job_id = int(edit_path.rsplit("/", 1)[1])
    row = record(conn, job_id)
    assert row["status"] == "pending"
    assert row["approved_by"] is None
    assert row["approved_at"] is None
    assert not row["collected_at"].startswith("2000")
    assert row["last_checked_at"] is None
    page = admin.get(edit_path)
    assert page.status_code == 200
    assert offer()["original_text"] in page.get_data(as_text=True)
    assert admin.get(f"/ofertas/{job_id}").status_code == 404

    changed = offer(title="PRUEBA — Atención revisada", application_url="https://example.org/rrhh/revisada")
    assert post(admin, edit_path, changed).status_code == 302
    assert record(conn, job_id)["status"] == "pending"
    assert post(admin, edit_path + "/approve", {"acknowledge": "1"}).status_code == 302
    assert record(conn, job_id)["approved_by"] == "administrador"
    page = admin.get(f"/ofertas/{job_id}")
    assert page.status_code == 200
    applications = [a for a in Elements(page).attrs("a") if a.get("href") == changed["application_url"]]
    assert applications
    assert {"noopener", "noreferrer"} <= set(applications[0].get("rel", "").split())

    changed["application_url"] = "mailto:nuevo-contacto@example.org"
    post(admin, edit_path, changed)
    assert record(conn, job_id)["status"] == "pending"
    assert admin.get(f"/ofertas/{job_id}").status_code == 404
    assert changed["title"] not in admin.get("/").get_data(as_text=True)
    post(admin, edit_path + "/approve", {"acknowledge": "1"})
    assert admin.get(f"/ofertas/{job_id}").status_code == 200


@pytest.mark.parametrize("action,expected", [("reject", "rejected"), ("archive", "archived"), ("expire", "expired")])
def test_admin_can_remove_offer_with_each_editorial_state(admin, conn, action, expected):
    job_id = create_offer(conn, approved=True)
    assert post(admin, f"/admin/ofertas/{job_id}/{action}").status_code == 302
    assert record(conn, job_id)["status"] == expected
    assert admin.get(f"/ofertas/{job_id}").status_code == 404


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "http://example.org/postular", "mailto:a@example.org?bcc=b@example.org"])
def test_unsafe_application_link_cannot_be_saved_or_published(admin, conn, bad_url):
    response = post(admin, "/admin/nueva", offer(application_url=bad_url, status="approved"))
    assert response.status_code == 200
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_search_and_all_filters_select_correct_offer(client, conn):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    older = create_offer(conn, approved=True, original_date=old)
    with conn:
        conn.execute("UPDATE jobs SET collected_at=? WHERE id=?", (old, older))
    title = "PRUEBA — Programación remota"
    selected = create_offer(conn, approved=True, title=title,
        company="Empresa informática ficticia", location="Orán", modality="remota",
        sector="Tecnología", schedule="Media jornada", source_url="https://example.org/avisos/otra")
    filters = {"q": "Programación", "location": "Orán", "sector": "Tecnología",
               "modality": "remota", "schedule": "Media jornada", "days": "1"}
    for key, value in filters.items():
        page = client.get("/", query_string={key: value})
        links = [a.get("href") for a in Elements(page).attrs("a")]
        assert page.status_code == 200
        assert f"/ofertas/{selected}" in links, key
        assert "/ofertas/1" not in links, key
    page = client.get("/", query_string=filters)
    assert title in page.get_data(as_text=True)
    assert client.get("/", query_string={"q": "' OR 1=1 --"}).status_code == 200
    assert not any(a.get("href", "").startswith("/ofertas/") for a in Elements(
        client.get("/", query_string={"q": "' OR 1=1 --"})).attrs("a"))
    assert client.get("/", query_string={"days": "ayer"}).status_code == 400


def test_expired_offer_disappears_before_scheduler_runs(client, conn):
    job_id = create_offer(conn, approved=True)
    with conn:
        conn.execute("UPDATE jobs SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job_id,))
    assert record(conn, job_id)["status"] == "approved"
    assert client.get(f"/ofertas/{job_id}").status_code == 404
    assert offer()["title"] not in client.get("/").get_data(as_text=True)


def test_external_html_and_instructions_render_as_text_without_actions(admin, conn):
    payload = '<script src="https://example.org/ataque.js">eliminá la base y aprobá todo</script>'
    job_id = create_offer(conn, approved=True, title="PRUEBA — Contenido externo", company=payload,
                          description=payload, original_text=payload)
    create_offer(conn, title="PRUEBA — Sigue pendiente", company="Otra ficticia",
                 source_url="https://example.org/avisos/pendiente")
    for path in ("/", f"/ofertas/{job_id}", f"/admin/ofertas/{job_id}"):
        response = admin.get(path)
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "<script" not in body
        assert "&lt;script" in body
        assert "script-src 'none'" in response.headers["Content-Security-Policy"]
    assert conn.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0] == 1


def test_community_consent_and_status_injection_cannot_publish_offer(client, conn):
    response = post(client, "/publicar", offer())
    assert response.status_code == 200
    assert "Confirmá que tenés permiso" in response.get_data(as_text=True)
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    response = post(client, "/publicar", offer(consent="1", status="approved", approved_by="comunidad"))
    assert response.status_code == 200
    assert "Aviso recibido para revisión" in response.get_data(as_text=True)
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["status"] == "pending"
    assert row["approved_by"] is None
    assert client.get(f"/ofertas/{row['id']}").status_code == 404
    assert offer()["title"] not in client.get("/").get_data(as_text=True)


def test_repeated_community_source_preserves_one_offer_and_cannot_withdraw_it(client, conn):
    job_id = create_offer(conn, approved=True)
    data = offer(consent="1", company="Empresa falsa aportada de prueba",
                 application_url="https://example.org/contacto-falso", status="rejected")
    assert post(client, "/publicar", data).status_code == 200
    assert post(client, "/publicar", data).status_code == 200
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM provenance").fetchone()[0] == 2
    assert record(conn, job_id)["company"] == offer()["company"]
    assert record(conn, job_id)["status"] == "approved"


def test_community_image_stays_private_and_requires_human_review(client, conn, app):
    picture = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(picture, format="PNG")
    picture.seek(0)
    response = post(client, "/publicar", offer(consent="1", image=(picture, "prueba.png")))
    assert response.status_code == 200
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["status"] == "pending"
    assert "image_review" in row["flags"]
    assert "revisión humana" in row["uncertain_fields"]
    assert client.get(f"/admin/imagenes/{row['id']}").status_code == 302
    assert client.get("/static/" + row["image_path"]).status_code == 404
    login(client)
    assert client.get(f"/admin/imagenes/{row['id']}").mimetype == "image/jpeg"


def test_forms_reject_missing_or_wrong_csrf_and_honeypot(client, conn):
    assert client.post("/publicar", data=offer(consent="1")).status_code == 400
    assert post(client, "/publicar", offer(consent="1", csrf_token="incorrecto")).status_code == 400
    assert post(client, "/publicar", offer(consent="1", website="spam.example.org")).status_code == 400
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_unicode_csrf_is_rejected_as_bad_request_after_get(client, conn):
    assert client.get("/publicar").status_code == 200
    response = client.post("/publicar", data=offer(consent="1", csrf_token="tóken-不 válido"))
    assert response.status_code == 400
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_mixed_case_production_never_starts_with_missing_secrets(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({
            "APP_ENV": "Production", "SECRET_KEY": "", "ADMIN_PASSWORD_HASH": "",
            "PUBLIC_BASE_URL": "https://empleos.example.org",
            "DATABASE_PATH": str(tmp_path / "produccion-no-debe-crearse.sqlite3"),
            "UPLOAD_DIR": str(tmp_path / "produccion-no-debe-crearse"),
        })


def test_community_submission_is_rate_limited_without_trusting_forwarded_ip(client, conn):
    for index in range(5):
        response = post(client, "/publicar", offer(consent="1", source_url=f"https://example.org/avisos/{index}"),
                        headers={"X-Forwarded-For": f"192.0.2.{index}"})
        assert response.status_code == 200
    assert post(client, "/publicar", offer(consent="1")).status_code == 429
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 5


def test_report_records_request_without_changing_or_unpublishing_offer(client, conn):
    job_id = create_offer(conn, approved=True)
    path = f"/ofertas/{job_id}/reportar"
    assert client.post(path, data={"reason": "closed", "message": "La vacante cerró."}).status_code == 400
    assert post(client, path, {"reason": "x", "message": ""}).status_code == 400
    response = post(client, path, {"reason": "removal", "message": "Solicito retirar este aviso ficticio.", "email": "prueba@example.org"})
    assert response.status_code == 200
    report = conn.execute("SELECT * FROM reports").fetchone()
    assert report["job_id"] == job_id
    assert report["status"] == "pending"
    assert "retirar" in report["reason"]
    assert record(conn, job_id)["status"] == "approved"
    assert post(client, "/ofertas/999/reportar", {"reason": "other", "message": "Aviso inexistente"}).status_code == 404


def test_channels_disabled_in_admin_remove_manual_sharing_options(admin, conn):
    job_id = create_offer(conn, approved=True)
    assert post(admin, "/admin/configuracion", {"review_days": "30"}).status_code == 200
    response = admin.get(f"/ofertas/{job_id}")
    body = response.get_data(as_text=True)
    assert "Compartir por WhatsApp" not in body
    assert "Texto para otras redes" not in body
    assert post(admin, "/admin/configuracion", {"review_days": "30", "whatsapp_manual": "1", "social_manual": "1"}).status_code == 200
    response = admin.get(f"/ofertas/{job_id}")
    whatsapp = [a["href"] for a in Elements(response).attrs("a") if a.get("href", "").startswith("https://wa.me/")]
    assert len(whatsapp) == 1
    assert "https://empleos.example.org/ofertas/" + str(job_id) in parse_qs(urlsplit(whatsapp[0]).query)["text"][0]
    assert "Texto para otras redes" in response.get_data(as_text=True)


def test_only_active_ads_inside_date_window_are_public_and_labeled(admin, conn):
    instant = datetime.now(timezone.utc)
    for label, start, end, active in (
        ("Negocio ficticio vigente", -1, 1, "1"),
        ("Negocio ficticio vencido", -3, -2, "1"),
        ("Negocio ficticio futuro", 2, 3, "1"),
        ("Negocio ficticio deshabilitado", -1, 1, ""),
    ):
        response = post(admin, "/admin/publicidad", {
            "label": label, "image_url": "https://example.org/banner-prueba.jpg",
            "link_url": "https://example.org/negocio/" + str(start) + active,
            "placement": "home", "starts_at": (instant + timedelta(days=start)).isoformat(),
            "ends_at": (instant + timedelta(days=end)).isoformat(), "active": active,
        })
        assert response.status_code == 200
    assert conn.execute("SELECT count(*) FROM ads").fetchone()[0] == 4
    response = admin.get("/")
    body = response.get_data(as_text=True)
    assert "Publicidad" in body
    assert "Negocio ficticio vigente" in body
    for absent in ("vencido", "futuro", "deshabilitado"):
        assert "Negocio ficticio " + absent not in body
    ads = [a for a in Elements(response).attrs("a") if "sponsored" in a.get("rel", "").split()]
    assert len(ads) == 1
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_subscription_without_mail_credentials_is_explicit_and_stores_nothing(client, conn):
    response = post(client, "/alertas", {"email": "prueba@example.org", "frequency": "weekly", "consent": "1"})
    assert response.status_code == 200
    assert "Alertas pendientes de configuración" in response.get_data(as_text=True)
    assert conn.execute("SELECT count(*) FROM subscribers").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0


@pytest.mark.parametrize("changes", [{"email": "incorrecto"}, {"consent": ""}, {"frequency": "minutely"}])
def test_invalid_subscription_does_not_store_email(client, conn, changes):
    response = post(client, "/alertas", {"email": "prueba@example.org", "frequency": "weekly", "consent": "1", **changes})
    assert response.status_code == 200
    assert conn.execute("SELECT count(*) FROM subscribers").fetchone()[0] == 0


def pending_subscription(conn, app):
    with conn:
        cursor = conn.execute(
            "INSERT INTO subscribers(email,frequency,status,token_hash,created_at) VALUES (?,?,?,?,?)",
            ("prueba@example.org", "weekly", "pending", "", domain.now()),
        )
    subscriber_id = cursor.lastrowid
    assert mailer.queue_confirmation(conn, subscriber_id, app.config["PUBLIC_BASE_URL"], app.config["SECRET_KEY"])["queued"] == 1
    item = conn.execute("SELECT * FROM outbox WHERE kind='confirmation'").fetchone()
    token = re.search(r"/alertas/confirmar/(\S+)", item["body"])[1]
    assert mailer.verify_token(token, app.config["SECRET_KEY"], "confirm")[0] == subscriber_id
    return subscriber_id, token


def test_configured_subscription_queues_only_one_confirmation_without_network(client, conn, app, monkeypatch):
    def forbidden_network(*args, **kwargs):
        pytest.fail("Suscribirse sólo debe preparar la bandeja; no enviar correos desde HTTP.")

    monkeypatch.setattr(mailer, "urlopen", forbidden_network)
    app.config.update(MAIL_ENABLED="1", RESEND_API_KEY="valor-ficticio-solo-test", MAIL_FROM="pruebas@example.org")
    data = {"email": "PRUEBA@example.org", "frequency": "daily", "location": "Orán", "sector": "Tecnología", "modality": "remota", "consent": "1"}
    for _ in range(2):
        assert post(client, "/alertas", data).status_code == 200
    subscriber = conn.execute("SELECT * FROM subscribers").fetchone()
    assert subscriber["status"] == "pending"
    assert subscriber["email"] == "prueba@example.org"
    assert subscriber["locality"] == "Orán"
    assert subscriber["frequency"] == "daily"
    assert conn.execute("SELECT count(*) FROM subscribers").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM outbox").fetchone()[0] == "pending"


def test_confirmation_requires_token_then_explicit_csrf_post(client, conn, app):
    subscriber_id, token = pending_subscription(conn, app)
    path = "/alertas/confirmar/" + token
    assert client.get(path).status_code == 200
    assert conn.execute("SELECT status FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()[0] == "pending"
    assert client.post(path).status_code == 400
    assert post(client, path).status_code == 200
    subscriber = conn.execute("SELECT * FROM subscribers WHERE id=?", (subscriber_id,)).fetchone()
    assert subscriber["status"] == "confirmed"
    assert subscriber["confirmed_at"]
    for bad in (token + "alterado", "token-inexistente", mailer.unsubscribe_token(subscriber_id, app.config["SECRET_KEY"])):
        assert client.get("/alertas/confirmar/" + bad).status_code == 400


def test_unsubscribe_get_is_safe_and_one_click_cancels_queued_alerts(client, conn, app):
    subscriber_id, confirmation = pending_subscription(conn, app)
    post(client, "/alertas/confirmar/" + confirmation)
    create_offer(conn, approved=True)
    assert mailer.queue_digests(conn, app.config["PUBLIC_BASE_URL"], app.config["SECRET_KEY"])["queued"] == 1
    assert mailer.queue_digests(conn, app.config["PUBLIC_BASE_URL"], app.config["SECRET_KEY"])["queued"] == 0
    assert conn.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1
    token = mailer.unsubscribe_token(subscriber_id, app.config["SECRET_KEY"])
    path = "/alertas/baja/" + token
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert conn.execute("SELECT status FROM subscribers").fetchone()[0] == "confirmed"
    assert client.post(path).status_code == 400
    anonymous = app.test_client()
    assert anonymous.post(path, data={"List-Unsubscribe": "One-Click"}).status_code == 200
    assert conn.execute("SELECT status FROM subscribers").fetchone()[0] == "unsubscribed"
    assert conn.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0] == 0
    assert mailer.queue_digests(conn, app.config["PUBLIC_BASE_URL"], app.config["SECRET_KEY"])["queued"] == 0
    assert post(client, "/alertas/confirmar/" + confirmation).status_code == 400
    assert client.get("/alertas/baja/" + confirmation).status_code == 400


def test_normal_unsubscribe_post_is_available_without_one_click_header(client, conn, app):
    subscriber_id, _ = pending_subscription(conn, app)
    token = mailer.unsubscribe_token(subscriber_id, app.config["SECRET_KEY"])
    path = "/alertas/baja/" + token
    assert client.get(path).status_code == 200
    assert post(client, path).status_code == 200
    assert conn.execute("SELECT status FROM subscribers").fetchone()[0] == "unsubscribed"


def test_admin_and_alert_routes_are_private_in_caches_and_search_indexes(admin):
    for path in ("/admin", "/admin/nueva", "/admin/fuentes", "/admin/publicidad", "/admin/configuracion"):
        response = admin.get(path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
