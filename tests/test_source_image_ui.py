"""Las pantallas no ofrecen lecturas sin configuración ni interpretan texto externo."""

from html.parser import HTMLParser

import pytest
from flask import render_template

from salta_emplea.app import create_app
from salta_emplea.source_catalog import source_presets


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.items = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))

    def named(self, name):
        return [attrs for _, attrs in self.items if attrs.get('name') == name]


@pytest.fixture
def app(tmp_path):
    return create_app({
        'TESTING': True, 'APP_ENV': 'development', 'SERVERLESS': False,
        'SECRET_KEY': 'clave-ficticia-de-pruebas-de-pantallas',
        'ADMIN_PASSWORD_HASH': '', 'DATABASE_URL': '',
        'DATABASE_PATH': str(tmp_path / 'pantallas.sqlite3'),
        'UPLOAD_DIR': str(tmp_path / 'imagenes'),
        'PUBLIC_BASE_URL': 'https://example.org',
        'RESEND_API_KEY': '', 'MAIL_FROM': '', 'CRON_SECRET': '',
    })


def render(app, template, **context):
    # Se aísla la presentación; permisos y rutas se prueban mediante HTTP aparte.
    with app.test_request_context('/'):
        return render_template(template, url_for=lambda endpoint, **_kw: '/prueba/' + endpoint,
                               csrf_token=lambda: 'token-ficticio', **context)


@pytest.mark.parametrize('ready', [False, True])
@pytest.mark.parametrize('template,context', [
    ('submit.html', {'data': {}, 'errors': []}),
    ('edit.html', {'job': {}, 'duplicates': [], 'provenance': []}),
])
def test_image_consent_is_optional_and_only_offered_when_ready(app, ready, template, context):
    html = render(app, template, image_status={'ready': ready}, **context)
    fields = Elements(html).named('allow_ocr')
    assert len(fields) == int(ready)
    if ready:
        assert fields[0]['type'] == 'checkbox'
        assert 'required' not in fields[0]
        assert 'Google Cloud Vision' in html
    else:
        assert 'lectura automática no está habilitada' in html.lower()


def test_completed_image_reading_escapes_every_external_value_and_cannot_repeat(app):
    unsafe = '<script>instrucción externa de prueba</script>'
    html = render(app, 'edit.html', image_status={'ready': True},
                  job={'id': 1, 'status': 'pending', 'image_path': 'prueba.png'},
                  duplicates=[], provenance=[], image_result={
                      'status': 'completed', 'text': unsafe,
                      'fields': {'company': unsafe}, 'evidence': {'company': unsafe},
                      'uncertain_fields': [unsafe], 'applied': True,
                  })
    assert unsafe not in html
    assert html.count('&lt;script&gt;instrucción externa de prueba&lt;/script&gt;') == 4
    assert not Elements(html).named('allow_ocr')
    assert '/prueba/admin_extract_image' not in html
    assert 'Aviso original' in html
    assert 'Aprobar y publicar' in html


@pytest.mark.parametrize('status', ['pending', 'approved', 'expired'])
def test_manual_image_reading_is_only_offered_to_pending_offer_and_requires_permission(app, status):
    html = render(app, 'edit.html', image_status={'ready': True},
                  job={'id': 1, 'status': status, 'image_path': 'prueba.png'},
                  duplicates=[], provenance=[])
    fields = Elements(html).named('allow_ocr')
    assert len(fields) == int(status == 'pending')
    if fields:
        assert 'required' in fields[0]
        assert 'Tengo permiso para enviar esta imagen a Google Cloud Vision' in html


def test_source_presets_are_reference_posts_with_csrf_and_clear_pending_access(app):
    html = render(app, 'sources.html', source_presets=source_presets(), sources=[])
    elements = Elements(html)
    forms = [attrs for tag, attrs in elements.items
             if tag == 'form' and attrs.get('action') == '/prueba/admin_source_preset']
    assert len(forms) == 3
    assert all(form.get('method') == 'post' for form in forms)
    assert html.count('Registrar referencia manual') == 3
    assert 'pertenece a otra persona' in html
    assert 'no conecta sus publicaciones' in html
    assert html.count('name="csrf_token"') >= 3


@pytest.mark.parametrize('ready', [False, True])
def test_automation_does_not_claim_provider_is_working_from_configuration(app, ready):
    html = render(app, 'automation.html', image_status={
        'ready': ready, 'key_present': ready, 'enabled': ready,
        'monthly_limit': 20, 'used': 3, 'pending': 2,
    }, sources=[], task_runs=[], outbox_summary=[])
    assert '3 de 20 intentos' in html
    assert 'Pendientes con autorización: 2' in html
    assert 'nunca aprueba ni publica' in html
    if ready:
        assert 'no confirma una respuesta real del proveedor' in html
    else:
        assert 'Deshabilitada: falta habilitación' in html
    buttons = [attrs for tag, attrs in Elements(html).items if tag == 'button']
    # Salir y las cuatro tareas. Solo la última depende de OCR configurado.
    assert ('disabled' in buttons[-1]) is not ready
