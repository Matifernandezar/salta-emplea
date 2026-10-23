"""Contrato sintético con transporte Apify sustituido; no acredita acceso real."""
import copy
import json
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from salta_emplea import apify_computrabajo as apify, db, domain
from salta_emplea.app import create_app

FIXTURE = Path(__file__).parent / 'fixtures/apify_computrabajo_contract.json'
SECRET = 'PRUEBA-webhook-no-es-una-credencial-real'
TOKEN = 'PRUEBA-token-apify-ficticio'
ACTOR_ID = 'ActorPRUEBA000001'


@pytest.fixture
def records():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr('salta_emplea.app.load_env', lambda: None)
    return create_app({'TESTING': True, 'APP_ENV': 'development', 'SERVERLESS': False,
                       'SECRET_KEY': 'PRUEBA-sesion-no-real', 'DATABASE_URL': '',
                       'DATABASE_PATH': str(tmp_path / 'PRUEBA.sqlite'),
                       'UPLOAD_DIR': str(tmp_path / 'uploads'),
                       'APIFY_API_TOKEN': TOKEN, 'APIFY_WEBHOOK_SECRET': SECRET,
                       'APIFY_COMPUTRABAJO_ACTOR_ID': apify.ACTOR})


@pytest.fixture
def conn(app):
    connection = db.connect(app.config['DATABASE_TARGET'])
    yield connection
    connection.close()


@pytest.fixture
def provider(monkeypatch, records):
    state = {'records': records, 'calls': [], 'status': 'SUCCEEDED', 'actor': ACTOR_ID}

    def fetch(path, token, deadline, max_bytes=apify.MAX_BYTES):
        assert token == TOKEN and deadline > time.monotonic()
        state['calls'].append(path)
        if path.startswith('acts/'):
            return {'data': {'id': ACTOR_ID, 'username': 'unfenced-group',
                             'name': 'computrabajo-com-job-scraper'}}
        if path.startswith('actor-runs/'):
            return {'data': {'id': path.split('/')[1], 'actId': state['actor'],
                             'status': state['status'], 'defaultDatasetId': 'DatasetPRUEBA01'}}
        assert path == 'datasets/DatasetPRUEBA01/items?format=json&limit=51&clean=false'
        return copy.deepcopy(state['records'])

    monkeypatch.setattr(apify, 'fetch_json', fetch)
    return state


def notify(app, run='RunPRUEBA01', **kwargs):
    payload = {'eventType': 'ACTOR.RUN.SUCCEEDED', 'resource': {'id': run}}
    return app.test_client().post('/api/webhooks/apify/computrabajo',
                                  json=payload, headers={'Authorization': 'Bearer ' + SECRET}, **kwargs)


def jobs(conn):
    return [dict(row) for row in conn.execute('SELECT * FROM jobs ORDER BY id')]


def test_cinco_nuevas_pendientes_fechas_evidencia_y_resumen(app, conn, provider):
    response = notify(app)
    assert response.status_code == 200 and response.json['imported'] == 5
    assert len(jobs(conn)) == 5
    assert all(row['status'] == 'pending' and row['approved_at'] is None for row in jobs(conn))
    assert all(row['original_date'] is None and row['expires_at'] is None for row in jobs(conn))
    assert all(row['source_url'] == row['application_url'] for row in jobs(conn))
    assert all(len(row['description']) <= 600 for row in jobs(conn))
    assert len(conn.execute('SELECT * FROM provenance').fetchall()) == 5
    metadata = conn.execute('SELECT * FROM external_jobs LIMIT 1').fetchone()
    assert metadata['scraped_at'] == '2026-10-23T10:00:00+00:00'
    assert metadata['first_received_at'] and metadata['last_received_at']
    assert metadata['publish_date_text'] == 'Hace 8 horas'
    assert domain.public_jobs(conn) == []
    assert conn.execute('SELECT status FROM task_runs').fetchone()[0] == 'succeeded'


def test_otro_webhook_mismo_dataset_importa_cero(app, conn, provider):
    assert notify(app).json['imported'] == 5
    result = notify(app, 'RunPRUEBA02').json
    assert result['imported'] == 0 and result['existing'] == 5 and result['changed'] == 0
    assert len(jobs(conn)) == 5


def test_reintento_mismo_webhook_no_descarga_ni_duplica(app, conn, provider):
    assert notify(app).json['imported'] == 5
    count = len(provider['calls'])
    result = notify(app).json
    assert result['status'] == 'already_processed' and result['imported'] == 0
    assert len(provider['calls']) == count
    assert len(jobs(conn)) == 5
    assert conn.execute('SELECT attempts FROM apify_import_runs').fetchone()[0] == 1


def test_cincuenta_con_cuarenta_existentes_importa_diez(app, conn, provider):
    template = provider['records'][0]
    records = []
    for number in range(50):
        identity = f'{number + 1:032x}'
        record = dict(template, jobId=identity, title=f'PRUEBA — Puesto {number}',
                      jobUrl=template['jobUrl'].rsplit('-', 1)[0] + '-' + identity)
        records.append(record)
    provider['records'] = records[:40]
    assert notify(app).json['imported'] == 40
    provider['records'] = records
    response = notify(app, 'RunPRUEBA02')
    assert response.status_code == 200
    assert response.json['imported'] == 10 and response.json['existing'] == 40
    assert len(jobs(conn)) == 50
    assert notify(app, 'RunPRUEBA03').json['imported'] == 0


def test_cta_exacto_original_no_apply_url_ni_fecha_iso(app, conn, provider):
    assert notify(app).status_code == 200
    row = jobs(conn)[0]
    domain.transition_job(conn, row['id'], 'approve', 'administrador', acknowledge=True)
    response = app.test_client().get(f"/ofertas/{row['id']}")
    html = response.get_data(as_text=True)
    assert 'Ver oferta y postularme en Computrabajo' in html
    assert f'href="{row["source_url"]}"' in html
    assert 'candidato.ar.computrabajo.com' not in html
    assert '2099-12-31' not in html
    assert '2099-12-31' not in conn.execute('SELECT payload FROM provenance LIMIT 1').fetchone()[0]


def test_job_url_de_candidato_se_rechaza_aunque_apply_url_sea_valida(app, conn, provider):
    provider['records'] = [dict(provider['records'][0], jobUrl=provider['records'][0]['applyUrl'])]
    result = notify(app).json
    assert result['imported'] == 0 and result['reasons'] == {'invalid_job_url': 1}
    assert jobs(conn) == []


def test_html_se_elimina_y_nunca_se_guarda_descripcion_completa(app, conn, provider):
    provider['records'] = [dict(provider['records'][0], descriptionText='<p>Texto <b>visible</b></p><script>PELIGRO</script>' + 'palabra ' * 500)]
    assert notify(app).json['imported'] == 1
    row = jobs(conn)[0]
    assert row['description'].startswith('Texto visible')
    assert len(row['description']) <= 600 and row['description'].endswith('…')
    assert '<' not in row['description'] and 'PELIGRO' not in row['original_text']
    assert len(row['original_text']) <= 600


def test_cambio_hash_devuelve_pendiente_y_conserva_correcciones_y_mismo_id(app, conn, provider):
    provider['records'] = [provider['records'][0]]
    notify(app)
    row = jobs(conn)[0]
    domain.edit_job(conn, row['id'], {'title': 'PRUEBA: título corregido', 'description': 'Resumen corregido.'}, 'administrador')
    domain.transition_job(conn, row['id'], 'approve', 'administrador', acknowledge=True)
    assert notify(app, 'RunPRUEBA02').json['changed'] == 0
    assert jobs(conn)[0]['status'] == 'approved'
    provider['records'][0]['contentHash'] = 'cambiomaterial001'
    provider['records'][0]['jobUrl'] += '?version=2'
    result = notify(app, 'RunPRUEBA03').json
    assert result['changed'] == 1 and result['imported'] == 0
    current = jobs(conn)[0]
    assert current['id'] == row['id'] and len(jobs(conn)) == 1
    assert current['title'] == 'PRUEBA: título corregido' and current['description'] == 'Resumen corregido.'
    assert current['status'] == 'pending' and current['review_needed'] == 1 and current['approved_at'] is None
    assert 'source_changed' in current['flags']
    assert conn.execute('SELECT count(*) FROM provenance').fetchone()[0] >= 3
    domain.transition_job(conn, row['id'], 'approve', 'administrador', acknowledge=True)
    assert notify(app, 'RunPRUEBA04').json['changed'] == 0
    assert jobs(conn)[0]['status'] == 'approved'


def test_cambio_fuera_del_resumen_se_detecta_y_caida_no_archiva(app, conn, provider):
    provider['records'] = [dict(provider['records'][0], descriptionText='palabra ' * 200)]
    notify(app)
    row = jobs(conn)[0]
    domain.transition_job(conn, row['id'], 'approve', 'administrador', acknowledge=True)
    provider['records'][0]['descriptionText'] += 'Condición diferente al final.'
    assert notify(app, 'RunPRUEBA02').json['changed'] == 1  # Incluso si el actor repite su hash.
    assert jobs(conn)[0]['description'] == row['description']
    domain.transition_job(conn, row['id'], 'approve', 'administrador', acknowledge=True)
    provider['records'] = []
    assert notify(app, 'RunPRUEBA03').json['imported'] == 0
    assert jobs(conn)[0]['status'] == 'approved'
    provider['status'] = 'FAILED'
    assert notify(app, 'RunPRUEBA04').status_code == 409
    assert jobs(conn)[0]['status'] == 'approved'


def test_sin_auth_no_abre_base_ni_consulta_apify(app, conn, provider):
    response = app.test_client().post('/api/webhooks/apify/computrabajo', json={})
    assert response.status_code == 401 and provider['calls'] == []
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 0


@pytest.mark.parametrize('location,accepted', [
    ('Salta, Salta', True), ('General Güemes', True), ('Orán', True),
    ('Tartagal', True), ('Cafayate', True), ('Rosario de Lerma', True),
    ('San Lorenzo, Salta', True), ('Cerrillos, Salta', True), ('Cachi', True),
    ('Rosario, Santa Fe', False), ('General Güemes, Chaco', False),
    ('Salta, Buenos Aires', False), ('San Lorenzo', False), ('Salto', False),
    ('Buenos Aires', False), ('Argentina', False), ('', False),
])
def test_filtro_geografico(location, accepted):
    assert apify.is_salta(location) is accepted


@pytest.mark.parametrize('changes,reason', [
    ({'countryCode': 'AR'}, 'outside_country'), ({'countryCode': 'mx'}, 'outside_country'),
    ({'location': '<img alt="Salta">París'}, 'outside_salta'),
    ({'jobId': ''}, 'invalid_job_id'), ({'jobId': 42}, 'invalid_job_id'),
    ({'title': ''}, 'invalid_title'), ({'jobUrl': 'http://ar.computrabajo.com/falso'}, 'invalid_job_url'),
    ({'jobUrl': 'https://ar.computrabajo.com.evil.test/oferta'}, 'invalid_job_url'),
])
def test_registros_invalidos_se_registran_sin_crear(app, conn, provider, changes, reason):
    provider['records'] = [dict(provider['records'][0], **changes)]
    response = notify(app)
    assert response.status_code == 200 and response.json['reasons'] == {reason: 1}
    assert jobs(conn) == []


def test_actor_incorrecto_y_dataset_excesivo_no_se_importan(app, conn, provider):
    provider['actor'] = 'OtroActor'
    assert notify(app).json['error'] == 'run_mismatch'
    assert not any(path.startswith('datasets/') for path in provider['calls'])
    provider['actor'] = ACTOR_ID
    provider['records'] *= 11
    assert notify(app, 'RunPRUEBA02').json['error'] == 'dataset_item_limit'
    assert jobs(conn) == []


def test_payload_excesivo_y_no_evento_rechazados(app, conn, provider):
    headers = {'Authorization': 'Bearer ' + SECRET}
    client = app.test_client()
    assert client.post('/api/webhooks/apify/computrabajo', json={'x': 'x' * 33000}, headers=headers).status_code == 413
    assert client.post('/api/webhooks/apify/computrabajo', json={'eventType': 'ACTOR.RUN.FAILED'}, headers=headers).status_code == 400
    assert provider['calls'] == []


def test_interrupcion_recupera_cursor_sin_duplicar_y_detecta_dataset_mutado(app, conn, provider, monkeypatch):
    original = apify.import_record
    calls = []
    def interrupted(*args):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError('PRUEBA: proceso interrumpido')
        return original(*args)
    monkeypatch.setattr(apify, 'import_record', interrupted)
    assert notify(app).status_code == 503
    assert len(jobs(conn)) == 2
    run = conn.execute('SELECT * FROM apify_import_runs').fetchone()
    assert run['cursor'] == 2 and run['status'] == 'failed'
    monkeypatch.setattr(apify, 'import_record', original)
    saved = copy.deepcopy(provider['records'])
    provider['records'][2]['companyName'] = 'PRUEBA: dataset alterado'
    assert notify(app).json['error'] == 'dataset_changed'
    assert len(jobs(conn)) == 2
    provider['records'] = saved
    result = notify(app).json
    assert result['imported'] == 5 and result['processed'] == 5
    assert len(jobs(conn)) == 5 and conn.execute('SELECT count(*) FROM external_jobs').fetchone()[0] == 5


class Response(BytesIO):
    status = 200
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = {'Content-Type': 'application/json', **(headers or {})}


def test_cliente_url_fija_get_token_en_header_y_limite_stream(monkeypatch):
    requests = []
    def opener(req, timeout):
        requests.append(req)
        assert req.full_url.startswith('https://api.apify.com/v2/')
        assert TOKEN not in req.full_url and req.get_method() == 'GET'
        assert req.get_header('Authorization') == 'Bearer ' + TOKEN
        assert 0 < timeout <= 10
        return Response(b'[' + b' ' * 100 + b']')
    monkeypatch.setattr(apify, 'open_request', opener)
    with pytest.raises(apify.ImportFailure, match='response_too_large'):
        apify.fetch_json('datasets/PRUEBA/items', TOKEN, time.monotonic() + 10, 20)
    assert len(requests) == 1


@pytest.mark.parametrize('body,headers,code', [
    (b'<html>PRUEBA</html>', {}, 'invalid_provider_json'),
    (b'[]', {'Content-Type': 'text/html'}, 'provider_content_type'),
    (b'[]', {'Content-Encoding': 'gzip'}, 'encoded_response'),
    (b'[]', {'Content-Length': '99999999'}, 'response_too_large'),
    (b'[NaN]', {}, 'invalid_provider_json'),
])
def test_respuestas_del_proveedor_invalidas(monkeypatch, body, headers, code):
    monkeypatch.setattr(apify, 'open_request', lambda *_args, **_kwargs: Response(body, headers))
    with pytest.raises(apify.ImportFailure, match=code):
        apify.fetch_json('PRUEBA', TOKEN, time.monotonic() + 10)


def test_no_sigue_redirecciones_ni_muestra_errores_con_secretos(monkeypatch):
    assert apify.NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://evil.test') is None
    def failure(*_args, **_kwargs):
        raise HTTPError('https://api.apify.com/PRUEBA', 429, TOKEN, {}, None)
    monkeypatch.setattr(apify, 'open_request', failure)
    with pytest.raises(apify.ImportFailure) as error:
        apify.fetch_json('PRUEBA', TOKEN, time.monotonic() + 10)
    assert str(error.value) == 'provider_http_429' and TOKEN not in str(error.value)


def test_migracion_desde_version_uno_conserva_ofertas_y_es_repetible(tmp_path):
    target = tmp_path / 'anterior.sqlite'
    original = sqlite3.connect(target)
    original.executescript(Path(db.__file__).with_name('schema.sql').read_text())
    original.close()
    connection = db.connect(target)
    job_id, _ = domain.create_job(connection, {'title': 'PRUEBA previa'}, 'administrador')
    connection.close()
    db.init_db(target)
    db.init_db(target)
    connection = db.connect(target)
    try:
        assert connection.execute('SELECT title FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'PRUEBA previa'
        assert connection.execute('SELECT count(*) FROM schema_migrations').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM external_jobs').fetchone()[0] == 0
    finally:
        connection.close()


def test_dataset_declarado_en_webhook_no_controla_destino(app, provider):
    payload = {'eventType': 'ACTOR.RUN.SUCCEEDED', 'resource': {
        'id': 'RunPRUEBA01', 'defaultDatasetId': 'https://127.0.0.1/privado',
        'datasetUrl': 'https://evil.test/datos'}}
    response = app.test_client().post('/api/webhooks/apify/computrabajo', json=payload,
                                      headers={'Authorization': 'Bearer ' + SECRET})
    assert response.json['imported'] == 5
    assert all('evil.test' not in path and '127.0.0.1' not in path for path in provider['calls'])


def test_lease_ocupado_y_limite_de_reintentos_no_descargan(app, conn, provider):
    with db.task_lock(conn, 'apify-computrabajo', ttl_seconds=300) as acquired:
        assert acquired
        response = notify(app)
        assert response.status_code == 503 and response.json['error'] == 'import_busy'
    assert provider['calls'] == []
    provider['status'] = 'FAILED'
    notify(app)
    with conn:
        conn.execute('UPDATE apify_import_runs SET attempts=12')
    total = len(provider['calls'])
    assert notify(app).json['error'] == 'retry_limit'
    assert len(provider['calls']) == total


def test_archivado_no_se_reabre_y_configuracion_no_pretende_programacion(app, conn, provider):
    provider['records'] = [provider['records'][0]]
    notify(app)
    row = jobs(conn)[0]
    domain.transition_job(conn, row['id'], 'archive', 'administrador')
    provider['records'][0]['contentHash'] = 'cambiomaterial001'
    assert notify(app, 'RunPRUEBA02').json['changed'] == 1
    assert jobs(conn)[0]['status'] == 'archived'
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin'] = True
    response = client.get('/admin/automatizacion')
    assert response.status_code == 200
    assert 'Apify: variables presentes' in response.get_data(as_text=True)
    assert 'Programación externa en Apify; no comprobada' in response.get_data(as_text=True)
    assert SECRET not in response.get_data(as_text=True) and TOKEN not in response.get_data(as_text=True)
