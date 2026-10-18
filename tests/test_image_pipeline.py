"""Imágenes y reservas de lectura: pruebas aisladas, sin proveedor ni publicaciones reales."""
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from salta_emplea import db, domain, extraction, image_pipeline, tasks
from salta_emplea.app import create_app


@pytest.fixture
def setup(tmp_path):
    app = create_app({'TESTING': True, 'APP_ENV': 'development', 'SERVERLESS': False,
                      'SECRET_KEY': 'secreto-exclusivo-de-pruebas-de-imagenes', 'ADMIN_PASSWORD_HASH': '',
                      'DATABASE_URL': '', 'DATABASE_PATH': str(tmp_path / 'pruebas.sqlite3'),
                      'UPLOAD_DIR': str(tmp_path / 'imagenes'), 'PUBLIC_BASE_URL': 'https://example.test',
                      'RESEND_API_KEY': '', 'MAIL_FROM': '', 'CRON_SECRET': 'cron-ficticio',
                      'GOOGLE_VISION_API_KEY': '', 'OCR_ENABLED': '0', 'OCR_MONTHLY_LIMIT': '100'})
    conn = db.connect(app.config['DATABASE_TARGET'])
    client = app.test_client()
    with client.session_transaction() as state:
        state['admin'], state['csrf'] = True, 'csrf-prueba'
    yield app, conn, client
    conn.close()


def config(app, **updates):
    return dict(app.config, APP_ENV='production', OCR_ENABLED='1',
                GOOGLE_VISION_API_KEY='clave-ficticia-no-usable', **updates)


def add_image(app, conn, *, title='Aviso pendiente de transcripción', company=None, color='red'):
    buffer = io.BytesIO()
    Image.new('RGB', (120, 100), color).save(buffer, 'JPEG', quality=85)
    content = buffer.getvalue()
    name = hashlib.sha256(content).hexdigest() + '.jpg'
    (Path(app.config['UPLOAD_DIR']) / name).write_bytes(content)
    job_id, _ = domain.create_job(conn, {'title': title, 'company': company, 'image_path': name})
    return job_id, name


def provider(monkeypatch, calls, *, during=None):
    def extract(content, key):
        calls.append(content)
        if during:
            during()
        return {'text': 'Puesto: PRUEBA — Cajero\nEmpresa: Comercio ficticio\nLocalidad: Salta Capital\nCorreo: prueba@example.test',
                'provider': 'google_vision', 'warnings': []}
    monkeypatch.setattr(extraction, 'extract_image', extract)


@pytest.mark.parametrize('updates', [dict(OCR_ENABLED='0'), dict(GOOGLE_VISION_API_KEY=''),
                                   dict(APP_ENV='development'), dict(OCR_MONTHLY_LIMIT=0),
                                   dict(OCR_MONTHLY_LIMIT='inválido')])
def test_no_configuration_never_sends_or_reserves(setup, monkeypatch, updates):
    app, conn, _ = setup
    cfg = config(app); cfg.update(updates)
    job_id, _ = add_image(app, conn)
    image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    monkeypatch.setattr(extraction, 'extract_image', lambda *_a: pytest.fail('No debe consultar.'))
    assert tasks.run_tasks(conn, cfg, only='extract')['images']['unavailable'] is True
    assert image_pipeline.usage(conn) == 0


def test_requires_permission_for_each_image_before_sending(setup, monkeypatch):
    app, conn, _ = setup
    job_id, _ = add_image(app, conn)
    calls = []; provider(monkeypatch, calls)
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['processed'] == 0
    assert image_pipeline.status(conn, config(app))['pending'] == 0
    assert calls == []
    image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    assert image_pipeline.status(conn, config(app))['pending'] == 1
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['prepared'] == 1
    assert len(calls) == 1


def test_prepares_blanks_and_keeps_pending_and_original(setup, monkeypatch):
    app, conn, _ = setup
    job_id, name = add_image(app, conn, company='Empresa ya revisada')
    with conn:
        conn.execute('UPDATE jobs SET original_text=? WHERE id=?', ('Referencia original conservada', job_id))
    image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    calls = []; provider(monkeypatch, calls)
    assert tasks.run_tasks(conn, config(app), only='collect')['images']['prepared'] == 1
    job = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    assert job['title'] == 'PRUEBA — Cajero' and job['company'] == 'Empresa ya revisada'
    assert job['application_url'] == 'mailto:prueba@example.test'
    assert job['original_text'] == 'Referencia original conservada' and job['image_path'] == name
    assert job['status'] == 'pending' and job['approved_at'] is None
    assert job['salary_amount'] is None and job['original_date'] is None
    assert domain.public_jobs(conn) == []
    result = image_pipeline.result_for(conn, job_id, name)
    assert result['status'] == 'completed' and result['applied'] is True
    assert 'Puesto:' in result['evidence']['title']
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['processed'] == 0
    assert len(calls) == 1 and image_pipeline.usage(conn) == 1
    assert image_pipeline.status(conn, config(app))['pending'] == 0


def test_never_overwrites_edit_that_happened_while_provider_answered(setup, monkeypatch):
    app, conn, _ = setup
    job_id, name = add_image(app, conn)
    image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    calls = []; provider(monkeypatch, calls, during=lambda: domain.edit_job(conn, job_id, {'title': 'PRUEBA — Corregido manualmente'}, 'administrador'))
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['prepared'] == 0
    assert conn.execute('SELECT title FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'PRUEBA — Corregido manualmente'
    assert image_pipeline.result_for(conn, job_id, name)['applied'] is False


def test_monthly_quota_counts_failed_and_successful_attempts(setup, monkeypatch):
    app, conn, _ = setup
    first, _ = add_image(app, conn)
    second, _ = add_image(app, conn, color='blue')
    for job_id in (first, second): image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    calls = []; provider(monkeypatch, calls)
    cfg = config(app, OCR_MONTHLY_LIMIT=1)
    assert tasks.run_tasks(conn, cfg, only='extract')['images']['processed'] == 1
    assert tasks.run_tasks(conn, cfg, only='extract')['images']['quota_reached'] is True
    assert len(calls) == 1


def test_provider_failure_is_persistent_redacted_and_not_retried(setup, monkeypatch):
    app, conn, _ = setup
    job_id, name = add_image(app, conn)
    image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    calls = []
    def broken(*_a):
        calls.append(1)
        raise RuntimeError('secreto-que-nunca-debe-registrarse')
    monkeypatch.setattr(extraction, 'extract_image', broken)
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['errors'] == 1
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['processed'] == 0
    assert calls == [1]
    result = image_pipeline.result_for(conn, job_id, name)
    assert result['status'] == 'failed' and result['error_code'] == 'processing_failed'
    assert all('secreto-que' not in r['detail'] for r in conn.execute('SELECT detail FROM audit'))
    assert conn.execute('SELECT status FROM task_runs ORDER BY id LIMIT 1').fetchone()[0] == 'partial'


def test_interrupted_reservation_is_not_sent_again(setup, monkeypatch):
    app, conn, _ = setup
    job_id, name = add_image(app, conn)
    digest = image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    with conn:
        image_pipeline._event(conn, job_id, 'ocr_reserved', {'image_hash': digest, 'image_path': name})
    monkeypatch.setattr(extraction, 'extract_image', lambda *_a: pytest.fail('Cobro incierto no se repite.'))
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['processed'] == 0
    assert image_pipeline.result_for(conn, job_id, name)['status'] == 'reserved'


def test_completed_or_rejected_job_never_runs_again(setup, monkeypatch):
    app, conn, _ = setup
    job_id, _ = add_image(app, conn)
    image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')
    domain.transition_job(conn, job_id, 'reject', 'administrador-prueba')
    monkeypatch.setattr(extraction, 'extract_image', lambda *_a: pytest.fail('No debe consultar rechazados.'))
    assert tasks.run_tasks(conn, config(app), only='extract')['images']['processed'] == 0
    with pytest.raises(ValueError): image_pipeline.authorize(conn, job_id, app.config, 'administrador-prueba')


def test_manual_image_endpoint_needs_admin_csrf_and_permission(setup, monkeypatch):
    app, conn, admin = setup
    job_id, _ = add_image(app, conn)
    calls = []; provider(monkeypatch, calls)
    path = f'/admin/ofertas/{job_id}/leer-imagen'
    public = app.test_client()
    with public.session_transaction() as state: state['csrf'] = 'public-token'
    assert public.post(path, data={'csrf_token': 'public-token', 'allow_ocr': '1'}).location.endswith('/admin/ingresar')
    assert admin.post(path, data={'allow_ocr': '1'}).status_code == 400
    assert admin.post(path, data={'csrf_token': 'csrf-prueba'}).status_code == 400
    assert calls == []
    assert admin.post(path, data={'csrf_token': 'csrf-prueba', 'allow_ocr': '1'}).status_code == 302
    assert calls == []  # Proveedor ausente.
    app.config.update(config(app))
    assert admin.post(path, data={'csrf_token': 'csrf-prueba', 'allow_ocr': '1'}).status_code == 302
    assert len(calls) == 1
    assert admin.post(path, data={'csrf_token': 'csrf-prueba', 'allow_ocr': '1'}).status_code == 302
    assert len(calls) == 1


def test_source_preset_registration_is_manual_private_and_idempotent(setup):
    app, conn, admin = setup
    assert conn.execute('SELECT count(*) FROM sources').fetchone()[0] == 0
    assert admin.get('/admin/fuentes').status_code == 200
    assert conn.execute('SELECT count(*) FROM sources').fetchone()[0] == 0
    path = '/admin/fuentes/preparadas/instagram-empleosalta12'
    assert admin.get(path).status_code == 405
    assert admin.post(path).status_code == 400
    for _ in range(2): assert admin.post(path, data={'csrf_token': 'csrf-prueba'}).status_code == 302
    rows = conn.execute('SELECT * FROM sources').fetchall()
    assert len(rows) == 1 and rows[0]['method'] == 'manual'
    assert rows[0]['status'] == 'disabled' and rows[0]['authorized'] == 0
    assert admin.post('/admin/fuentes/preparadas/desconocida', data={'csrf_token': 'csrf-prueba'}).status_code == 404


def png():
    content = io.BytesIO()
    Image.new('RGB', (110, 100), 'green').save(content, 'PNG')
    content.seek(0)
    return content


def test_same_uploaded_image_deduplicates_without_replacing_reviewed_offer(setup):
    app, conn, admin = setup
    for filename in ('primero.png', 'otro-nombre.png'):
        assert admin.post('/admin/nueva', data={'csrf_token': 'csrf-prueba', 'image': (png(), filename)}).status_code == 302
    jobs = conn.execute('SELECT * FROM jobs').fetchall()
    assert len(jobs) == 1 and jobs[0]['status'] == 'pending'
    assert len(list(Path(app.config['UPLOAD_DIR']).glob('*.jpg'))) == 1
    assert any(json.loads(r['detail']).get('exact_image') for r in conn.execute("SELECT detail FROM audit WHERE action='duplicate_received'"))


def test_form_cannot_reference_an_existing_private_image_by_name(setup):
    app, conn, admin = setup
    response = admin.post('/admin/nueva', data={'csrf_token': 'csrf-prueba', 'title': 'PRUEBA — Datos externos',
                                              'image_path': 'a'*64+'.jpg'})
    assert response.status_code == 302
    assert conn.execute('SELECT image_path FROM jobs').fetchone()[0] is None


def test_pasted_text_prepares_literal_fields_without_provider_or_approval(setup, monkeypatch):
    app, conn, admin = setup
    monkeypatch.setattr(extraction, 'extract_image', lambda *_a: pytest.fail('El texto no necesita proveedor.'))
    original = 'Puesto: PRUEBA — Cajero\nEmpresa: Comercio ficticio\nCorreo: prueba@example.test\nSueldo: a convenir'
    response = admin.post('/admin/nueva', data={'csrf_token': 'csrf-prueba', 'original_text': original})
    assert response.status_code == 302
    job = conn.execute('SELECT * FROM jobs').fetchone()
    assert job['title'] == 'PRUEBA — Cajero'
    assert job['company'] == 'Comercio ficticio'
    assert job['application_url'] == 'mailto:prueba@example.test'
    assert job['original_text'] == original and job['salary_amount'] is None
    assert job['status'] == 'pending' and job['approved_at'] is None
    assert domain.public_jobs(conn) == []


def test_pasted_text_does_not_replace_explicit_manual_fields(setup):
    app, conn, admin = setup
    response = admin.post('/admin/nueva', data={'csrf_token': 'csrf-prueba',
                      'title': 'PRUEBA — Puesto corregido', 'company': 'Empresa corregida',
                      'application_url': 'https://example.test/manual',
                      'original_text': 'Puesto: Otro puesto\nEmpresa: Otra empresa\nCorreo: otra@example.test'})
    assert response.status_code == 302
    job = conn.execute('SELECT * FROM jobs').fetchone()
    assert (job['title'], job['company'], job['application_url']) == (
        'PRUEBA — Puesto corregido', 'Empresa corregida', 'https://example.test/manual')
