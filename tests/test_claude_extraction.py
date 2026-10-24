"""Claude sustituido: no se usan credenciales ni solicitudes reales."""
import json
from urllib.error import HTTPError, URLError

import pytest

from salta_emplea import claude_extraction as claude, extraction, image_pipeline, tasks
from test_extraction import Response, PNG, KEY
from test_image_pipeline import setup, add_image, png


def data():
    return {'text': 'Buscamos Cajero\nSalta Capital\ncv@example.test', 'fields': {
        'title': {'value': 'Cajero', 'evidence': 'Buscamos Cajero'},
        'location': {'value': 'Salta Capital', 'evidence': 'Salta Capital'},
        'application_url': {'value': 'cv@example.test', 'evidence': 'cv@example.test'}}}


def payload(value=None):
    return {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'name': 'extract_job',
                                                 'input': data() if value is None else value}]}


def test_request_is_single_private_fixed_and_returns_validated_fields():
    calls = []
    def opener(request, timeout):
        calls.append(request)
        assert request.full_url == claude.URL and timeout == 20
        assert request.get_header('X-api-key') == KEY
        assert KEY.encode() not in request.data
        body = json.loads(request.data)
        assert body['model'] == claude.DEFAULT_MODEL
        assert body['messages'][0]['content'][0]['source']['media_type'] == 'image/png'
        return Response(payload())
    result = claude.extract_image(PNG, KEY, opener=opener)
    assert result['prepared']['fields']['title'] == 'Cajero'
    assert result['prepared']['fields']['application_url'] == 'mailto:cv@example.test'
    assert 'company' not in result['prepared']['fields'] and len(calls) == 1


def test_unsubstantiated_values_and_contacts_are_omitted():
    value = data()
    value['fields']['company'] = {'value': 'Inventada', 'evidence': 'Buscamos Cajero'}
    value['fields']['application_url'] = {'value': 'javascript:alert(1)', 'evidence': 'javascript:alert(1)'}
    value['text'] += '\njavascript:alert(1)'
    result = claude._prepared(value)['prepared']
    assert 'company' not in result['fields'] and 'application_url' not in result['fields']
    assert {'company', 'application_url'} <= set(result['uncertain_fields'])


@pytest.mark.parametrize('status,code', [(401,'anthropic_credentials_rejected'),
    (403,'anthropic_credentials_rejected'), (402,'anthropic_billing_rejected'),
    (404,'anthropic_model_rejected'), (429,'quota_exceeded'), (529,'provider_unavailable'),
    (302,'redirect_rejected')])
def test_http_failures_do_not_expose_secrets_or_retry(status, code):
    calls = []
    def opener(*args, **kwargs):
        calls.append(1)
        raise HTTPError(claude.URL, status, KEY, {}, None)
    with pytest.raises(extraction.ExtractionError) as error:
        claude.extract_image(PNG, KEY, opener=opener)
    assert error.value.code == code and KEY not in str(error.value) and len(calls) == 1


@pytest.mark.parametrize('value', [None, [], {}, {'text': '', 'fields': {'salary_amount': 1}}])
def test_invalid_structure_is_rejected(value):
    with pytest.raises(extraction.ExtractionError):
        claude._prepared(value)


@pytest.mark.parametrize('stop', ['max_tokens', 'end_turn', 'refusal'])
def test_incomplete_or_refused_response_is_not_applied(stop):
    response = payload(); response['stop_reason'] = stop
    with pytest.raises(extraction.ExtractionError):
        claude.extract_image(PNG, KEY, opener=lambda *a, **k: Response(response))


def cfg(app):
    return dict(app.config, APP_ENV='production', OCR_ENABLED='1', ANTHROPIC_API_KEY=KEY,
                ANTHROPIC_MODEL=claude.DEFAULT_MODEL)


def test_pipeline_preserves_edits_and_only_processes_once(setup, monkeypatch):
    app, conn, _ = setup
    config = cfg(app)
    job_id, name = add_image(app, conn, company='Empresa corregida')
    calls = []
    def provider(*args):
        calls.append(1)
        return claude._prepared(data())
    monkeypatch.setattr(claude, 'extract_image', provider)
    image_pipeline.authorize(conn, job_id, config, 'administrador')
    assert tasks.run_tasks(conn, config, only='extract')['images']['prepared'] == 1
    job = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    assert job['title'] == 'Cajero' and job['company'] == 'Empresa corregida'
    assert job['status'] == 'pending' and job['approved_at'] is None
    assert tasks.run_tasks(conn, config, only='extract')['images']['processed'] == 0
    assert len(calls) == 1
    assert image_pipeline.result_for(conn, job_id, name)['provider'] == 'anthropic'


def test_google_consent_does_not_authorize_claude(setup, monkeypatch):
    app, conn, _ = setup
    job_id, _ = add_image(app, conn)
    image_pipeline.authorize(conn, job_id, app.config, 'administrador')
    monkeypatch.setattr(claude, 'extract_image', lambda *a: pytest.fail('No autorizado'))
    assert tasks.run_tasks(conn, cfg(app), only='extract')['images']['processed'] == 0
    assert image_pipeline.usage(conn) == 0


def test_claude_form_requires_admin_and_consent(setup, monkeypatch):
    app, conn, client = setup
    app.config.update(cfg(app))
    job_id, _ = add_image(app, conn)
    monkeypatch.setattr(claude, 'extract_image', lambda *a: claude._prepared(data()))
    page = client.get(f'/admin/ofertas/{job_id}').data.decode()
    assert 'Claude (Anthropic)' in page
    path = f'/admin/ofertas/{job_id}/leer-imagen'
    assert client.post(path, data={'csrf_token': 'csrf-prueba'}).status_code == 400
    assert client.post(path, data={'csrf_token': 'csrf-prueba', 'allow_ocr': '1'}).status_code == 302
    assert image_pipeline.usage(conn) == 1
    with client.session_transaction() as state:
        state.pop('admin', None)
    assert client.post(path, data={'csrf_token': 'csrf-prueba', 'allow_ocr': '1'}).status_code == 302


def test_explicit_pause_overrides_claude_key(setup):
    app, _, _ = setup
    config = cfg(app); config['OCR_ENABLED'] = '0'
    assert not image_pipeline.configured(config)


def test_new_image_completes_blank_form_in_same_request_and_preserves_edits(setup, monkeypatch):
    app, conn, client = setup
    app.config.update(cfg(app))
    calls = []
    def provider(*args):
        calls.append(1)
        return claude._prepared(data())
    monkeypatch.setattr(claude, 'extract_image', provider)
    page = client.get('/admin/nueva')
    html = page.data.decode()
    assert html.index('name="image"') < html.index('name="title"')
    assert "script-src 'self'" in page.headers['Content-Security-Policy']
    response = client.post('/admin/nueva', data={'csrf_token': 'csrf-prueba',
        'allow_ocr': '1', 'company': 'Empresa ya corregida', 'image': (png(), 'aviso.png')})
    assert response.status_code == 302
    job = conn.execute('SELECT * FROM jobs').fetchone()
    assert job['title'] == 'Cajero' and job['company'] == 'Empresa ya corregida'
    assert job['status'] == 'pending' and len(calls) == 1
    assert 'Cajero' in client.get(response.location).data.decode()
    # Reenviar la misma imagen reutiliza el borrador y no repite el cobro.
    client.post('/admin/nueva', data={'csrf_token': 'csrf-prueba', 'allow_ocr': '1',
        'image': (png(), 'aviso-otra-vez.png')})
    assert len(calls) == 1 and conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 1


def test_new_image_without_permission_or_failed_provider_stays_pending(setup, monkeypatch):
    app, conn, client = setup
    app.config.update(cfg(app))
    calls = []
    def provider(*args):
        calls.append(1)
        raise extraction.ExtractionError('anthropic_credentials_rejected')
    monkeypatch.setattr(claude, 'extract_image', provider)
    response = client.post('/admin/nueva', data={'csrf_token': 'csrf-prueba',
        'image': (png(), 'aviso.png')})
    assert response.status_code == 302 and not calls
    response = client.post('/admin/nueva', data={'csrf_token': 'csrf-prueba',
        'allow_ocr': '1', 'image': (png(), 'aviso.png')})
    assert response.status_code == 302 and len(calls) == 1
    assert conn.execute('SELECT status FROM jobs').fetchone()[0] == 'pending'
    html = client.get(response.location).data.decode()
    assert 'Claude rechazó el acceso' in html
