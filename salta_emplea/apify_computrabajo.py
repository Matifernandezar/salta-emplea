"""Ingreso de datasets terminados de Apify; nunca inicia ni hace scraping.

El webhook sólo aporta una identidad de corrida. Actor, estado y dataset se
comprueban con GET autenticados al host fijo de Apify, sin seguir redirecciones.
"""
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import Blueprint, current_app, jsonify, request

from . import computrabajo, db, domain

ACTOR = 'unfenced-group/computrabajo-com-job-scraper'
SOURCE = 'computrabajo'
MAX_ITEMS = 50
MAX_BYTES = 2 * 1024 * 1024
MAX_WEBHOOK_BYTES = 32 * 1024
MAX_ATTEMPTS = 12
BUDGET_SECONDS = 45
# Localidades inequívocas habituales; cualquier otra se admite con provincia
# explícita Salta. Nombres ambiguos como San Lorenzo necesitan esa provincia.
_LOCALITIES = frozenset(domain._fold(x) for x in (
    'Salta Capital', 'General Güemes', 'Tartagal', 'Orán', 'San Ramón de la Nueva Orán',
    'Cafayate', 'Rosario de Lerma', 'Rosario de la Frontera', 'Metán', 'San José de Metán',
    'Cachi', 'Iruya', 'Aguaray', 'Embarcación', 'Pichanal', 'Tolar Grande',
    'San Antonio de los Cobres', 'Campo Quijano', 'Chicoana', 'La Caldera',
    'El Carril', 'Guachipas', 'Angastaco', 'Animaná', 'Seclantás', 'Payogasta',
    'Vaqueros', 'La Merced', 'El Quebrachal', 'Joaquín V. González', 'Las Lajitas',
    'Apolinario Saravia', 'General Mosconi', 'Coronel Moldes', 'Campo Santo',
))
_OTHER_PROVINCES = (
    'buenos aires', 'capital federal', 'caba', 'bs as', 'jujuy', 'chaco', 'formosa',
    'tucuman', 'santiago del estero', 'catamarca', 'la rioja', 'cordoba', 'santa fe',
    'corrientes', 'misiones', 'entre rios', 'san juan', 'san luis', 'mendoza',
    'la pampa', 'neuquen', 'rio negro', 'chubut', 'santa cruz', 'tierra del fuego',
)


class ImportFailure(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status
        super().__init__(code)  # Nunca incorporar mensajes/URLs del proveedor.


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def open_request(req, timeout):
    return build_opener(NoRedirect()).open(req, timeout=timeout)


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', value):
        raise ImportFailure('invalid_resource_id', 400)
    return value


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ImportFailure('time_budget', 503)
    return remaining


def _invalid_constant(_value):
    raise ValueError('JSON no finito')


def fetch_json(path, token, deadline, max_bytes=MAX_BYTES):
    req = Request('https://api.apify.com/v2/' + path, headers={
        'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
        'Accept-Encoding': 'identity', 'User-Agent': 'SaltaEmplea/1.0',
    }, method='GET')
    try:
        with open_request(req, timeout=min(10, _remaining(deadline))) as response:
            if response.status != 200:
                raise ImportFailure('provider_status')
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise ImportFailure('encoded_response')
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if content_type != 'application/json':
                raise ImportFailure('provider_content_type')
            size = response.headers.get('Content-Length')
            if size and (not size.isdigit() or int(size) > max_bytes):
                raise ImportFailure('response_too_large')
            chunks, length = [], 0
            while True:
                _remaining(deadline)
                chunk = response.read(min(65536, max_bytes + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > max_bytes:
                    raise ImportFailure('response_too_large')
            return json.loads(b''.join(chunks).decode('utf-8'), parse_constant=_invalid_constant)
    except HTTPError as exc:
        raise ImportFailure('provider_http_' + str(exc.code)) from None
    except (TimeoutError, URLError, OSError):
        raise ImportFailure('provider_unavailable') from None
    except (ValueError, UnicodeError, RecursionError):
        raise ImportFailure('invalid_provider_json') from None


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], []

    def handle_starttag(self, tag, _attrs):
        if tag in {'script', 'style', 'iframe', 'object', 'template'}:
            self.hidden.append(tag)
        elif not self.hidden:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        else:
            self.parts.append(' ')

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def plain_text(value, limit):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('invalid_text')
    parser = _PlainText()
    parser.feed(unescape(value))
    parser.close()
    return ' '.join(''.join(parser.parts).split())


def is_salta(value):
    if not isinstance(value, str) or not value or len(value) > 300:
        return False
    folded = domain._fold(value)
    for province in _OTHER_PROVINCES:
        if re.search(r'(?<!\w)' + re.escape(province) + r'(?!\w)', folded):
            return False
    if re.search(r'\bsalta\b', folded):
        return True
    parts = [part.strip() for part in re.split(r'[,;/|]', folded)]
    return any(part in _LOCALITIES for part in parts)


def _scraped_at(value):
    if not isinstance(value, str) or len(value) > 60:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def normalize_record(record):
    if not isinstance(record, dict):
        raise ValueError('invalid_record')
    if record.get('countryCode') != 'ar':
        raise ValueError('outside_country')
    location = plain_text(record.get('location'), 300)
    if not is_salta(location):
        raise ValueError('outside_salta')
    external_id = record.get('jobId')
    if not isinstance(external_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', external_id):
        raise ValueError('invalid_job_id')
    if re.fullmatch(r'[0-9a-fA-F]{32}', external_id):
        external_id = external_id.lower()
    try:
        original = computrabajo.valid_original_url(record.get('jobUrl'))
    except ValueError:
        raise ValueError('invalid_job_url') from None
    title = plain_text(record.get('title'), 200)
    if not title:
        raise ValueError('invalid_title')
    company = plain_text(record.get('companyName'), 200) or None
    description = plain_text(record.get('descriptionText'), 100000)
    summary = description
    if len(summary) > 600:
        summary = summary[:599].rsplit(' ', 1)[0] + '…'
    content_hash = record.get('contentHash')
    if not isinstance(content_hash, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', content_hash):
        content_hash = None
    material = {'title': title, 'company': company, 'location': location,
                'source_url': original, 'description': description}
    material_hash = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    # applyUrl y publishDateISO no se leen: no son fuente, destino ni fecha fiable.
    data = {'title': title, 'company': company, 'location': location,
            'description': summary or None, 'source_name': 'Computrabajo',
            'source_url': original, 'application_url': original,
            'original_text': summary or None}
    return data, {
        'external_id': external_id, 'content_hash': content_hash, 'material_hash': material_hash,
        'scraped_at': _scraped_at(record.get('scrapedAt')),
        'publish_date_text': plain_text(record.get('publishDate'), 100) or None,
    }


def _dataset(config, run_id, deadline):
    actor = config['APIFY_COMPUTRABAJO_ACTOR_ID']
    if actor != ACTOR and not re.fullmatch(r'[A-Za-z0-9]{1,64}', actor):
        raise ImportFailure('invalid_actor_configuration', 503)
    token = config['APIFY_API_TOKEN']
    actor_data = fetch_json('acts/' + actor.replace('/', '~'), token, deadline, 128 * 1024)
    actor_data = actor_data.get('data') if isinstance(actor_data, dict) else None
    if (not isinstance(actor_data, dict) or actor_data.get('username') != ACTOR.split('/')[0]
            or actor_data.get('name') != ACTOR.split('/')[1]):
        raise ImportFailure('actor_mismatch', 422)
    actor_id = _identifier(actor_data.get('id'))
    run = fetch_json('actor-runs/' + run_id, token, deadline, 128 * 1024)
    run = run.get('data') if isinstance(run, dict) else None
    if not isinstance(run, dict) or run.get('id') != run_id or run.get('actId') != actor_id:
        raise ImportFailure('run_mismatch', 422)
    if run.get('status') != 'SUCCEEDED':
        raise ImportFailure('run_not_succeeded', 409)
    dataset_id = _identifier(run.get('defaultDatasetId'))
    # Pedir uno extra detecta que una Task excedió el máximo sin importar parcialmente.
    query = urlencode({'format': 'json', 'limit': MAX_ITEMS + 1, 'clean': 'false'})
    items = fetch_json('datasets/' + dataset_id + '/items?' + query, token, deadline)
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ImportFailure('dataset_item_limit', 422)
    return items, dataset_id, actor_id


def _empty_result():
    return {'imported': 0, 'existing': 0, 'changed': 0, 'rejected': 0, 'processed': 0, 'reasons': {}}


def import_record(conn, record, run_id, dataset_id):
    data, metadata = normalize_record(record)
    existing = conn.execute('SELECT * FROM external_jobs WHERE source_name=? AND external_id=?',
                            (SOURCE, metadata['external_id'])).fetchone()
    if existing:
        changed = (existing['material_hash'] != metadata['material_hash'] or
                   bool(existing['content_hash'] and metadata['content_hash'] and
                        existing['content_hash'] != metadata['content_hash']))
        if changed:
            job_id, _ = domain.create_job(conn, data, 'recopilador_autorizado', in_transaction=True,
                                         existing_job_id=existing['job_id'], force_review=True)
        else:
            job_id = existing['job_id']
        outcome = 'changed' if changed else 'existing'
    else:
        found = conn.execute('SELECT id FROM jobs WHERE source_canonical_url=?', (data['source_url'],)).fetchone()
        job_id, _ = domain.create_job(conn, data, 'recopilador_autorizado', in_transaction=True)
        outcome = 'existing' if found else 'imported'
    stamp = domain.now()
    conn.execute('''INSERT INTO external_jobs
        (source_name,external_id,job_id,content_hash,material_hash,scraped_at,publish_date_text,first_received_at,last_received_at)
        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source_name,external_id) DO UPDATE SET
        content_hash=COALESCE(excluded.content_hash,external_jobs.content_hash),material_hash=excluded.material_hash,scraped_at=excluded.scraped_at,
        publish_date_text=excluded.publish_date_text,last_received_at=excluded.last_received_at''',
        (SOURCE, metadata['external_id'], job_id, metadata['content_hash'], metadata['material_hash'],
         metadata['scraped_at'], metadata['publish_date_text'], stamp, stamp))
    if outcome != 'existing':
        domain._audit(conn, 'recopilador_autorizado', 'apify_' + outcome, job_id,
                      dict(metadata, run_id=run_id, dataset_id=dataset_id))
    return outcome


def process_run(conn, config, run_id):
    deadline = time.monotonic() + BUDGET_SECONDS
    # El lease supera holgadamente el presupuesto y se recupera tras una caída.
    with db.task_lock(conn, 'apify-computrabajo', ttl_seconds=300) as acquired:
        if not acquired:
            raise ImportFailure('import_busy', 503)
        previous = conn.execute('SELECT * FROM apify_import_runs WHERE run_id=?', (run_id,)).fetchone()
        if previous and previous['status'] == 'succeeded':
            return {'status': 'already_processed', 'run_id': run_id, 'imported': 0}
        if previous and previous['attempts'] >= MAX_ATTEMPTS:
            raise ImportFailure('retry_limit', 409)
        result = json.loads(previous['result']) if previous else _empty_result()
        stamp = domain.now()
        with conn:
            if previous and previous['task_run_id']:
                conn.execute("UPDATE task_runs SET status='interrupted',finished_at=? WHERE id=? AND status='running'",
                             (stamp, previous['task_run_id']))
            task_id = conn.execute("INSERT INTO task_runs(task,started_at,status) VALUES ('apify_computrabajo',?,'running')", (stamp,)).lastrowid
            conn.execute('''INSERT INTO apify_import_runs(run_id,status,started_at,result,task_run_id)
                VALUES (?,'running',?,?,?) ON CONFLICT(run_id) DO UPDATE SET status='running',
                attempts=apify_import_runs.attempts+1,finished_at=NULL,error_code=NULL,task_run_id=excluded.task_run_id''',
                (run_id, stamp, json.dumps(result), task_id))
        try:
            items, dataset_id, actor_id = _dataset(config, run_id, deadline)
            digest = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if previous and previous['dataset_hash'] and previous['dataset_hash'] != digest:
                raise ImportFailure('dataset_changed', 409)
            with conn:
                conn.execute('UPDATE apify_import_runs SET dataset_id=?,actor_id=?,dataset_hash=? WHERE run_id=?',
                             (dataset_id, actor_id, digest, run_id))
            cursor = previous['cursor'] if previous else 0
            for index in range(cursor, len(items)):
                _remaining(deadline)
                # Un cursor confirmado junto con cada identidad permite continuar
                # sin perder avances si Vercel interrumpe el siguiente registro.
                next_result = json.loads(json.dumps(result))
                with conn:
                    db.editorial_lock(conn)
                    try:
                        outcome = import_record(conn, items[index], run_id, dataset_id)
                        next_result[outcome] += 1
                    except ValueError as exc:
                        reason = str(exc)
                        allowed = {'invalid_record', 'outside_country', 'outside_salta', 'invalid_job_id',
                                   'invalid_job_url', 'invalid_title', 'invalid_text'}
                        reason = reason if reason in allowed else 'invalid_record'
                        next_result['rejected'] += 1
                        next_result['reasons'][reason] = next_result['reasons'].get(reason, 0) + 1
                    next_result['processed'] += 1
                    conn.execute('UPDATE apify_import_runs SET cursor=?,result=? WHERE run_id=?',
                                 (index + 1, json.dumps(next_result), run_id))
                result = next_result
            with conn:
                conn.execute("UPDATE apify_import_runs SET status='succeeded',finished_at=? WHERE run_id=?", (domain.now(), run_id))
                conn.execute("UPDATE task_runs SET status='succeeded',finished_at=?,detail=? WHERE id=?",
                             (domain.now(), json.dumps(result), task_id))
                domain._audit(conn, 'recopilador_autorizado', 'apify_run_completed', None, dict(result, run_id=run_id))
            return dict(result, status='succeeded', run_id=run_id)
        except Exception as exc:
            code = exc.code if isinstance(exc, ImportFailure) else 'import_failed'
            with conn:
                conn.execute("UPDATE apify_import_runs SET status='failed',finished_at=?,error_code=? WHERE run_id=?",
                             (domain.now(), code, run_id))
                conn.execute("UPDATE task_runs SET status='failed',finished_at=?,detail=? WHERE id=?",
                             (domain.now(), json.dumps({'error': code, **result}), task_id))
            raise ImportFailure(code, exc.status if isinstance(exc, ImportFailure) else 503) from None


def create_blueprint(connection):
    blueprint = Blueprint('apify_webhooks', __name__)

    @blueprint.post('/api/webhooks/apify/computrabajo')
    def receive():
        config = current_app.config
        secret = config.get('APIFY_WEBHOOK_SECRET', '')
        if not isinstance(secret, str) or not secret.isascii() or not 32 <= len(secret) <= 256:
            return jsonify(error='not_configured'), 503
        supplied = request.headers.get('Authorization', '')
        if not supplied.isascii() or len(supplied) > 300 or not hmac.compare_digest(supplied, 'Bearer ' + secret):
            return jsonify(error='unauthorized'), 401
        if not config.get('APIFY_API_TOKEN') or not config.get('APIFY_COMPUTRABAJO_ACTOR_ID'):
            return jsonify(error='not_configured'), 503
        if request.mimetype != 'application/json':
            return jsonify(error='invalid_content_type'), 415
        if request.content_length and request.content_length > MAX_WEBHOOK_BYTES:
            return jsonify(error='payload_too_large'), 413
        raw = request.stream.read(MAX_WEBHOOK_BYTES + 1)
        if len(raw) > MAX_WEBHOOK_BYTES:
            return jsonify(error='payload_too_large'), 413
        try:
            payload = json.loads(raw, parse_constant=_invalid_constant)
            if not isinstance(payload, dict) or payload.get('eventType') != 'ACTOR.RUN.SUCCEEDED':
                raise ImportFailure('invalid_event', 400)
            resource = payload.get('resource')
            run_id = _identifier(resource.get('id') if isinstance(resource, dict) else None)
            result = process_run(connection(), config, run_id)
            return jsonify(result)
        except (ValueError, UnicodeError, RecursionError):
            return jsonify(error='invalid_payload'), 400
        except ImportFailure as exc:
            response = jsonify(error=exc.code)
            response.status_code = exc.status
            if exc.status in {502, 503}:
                response.headers['Retry-After'] = '60'
            return response

    return blueprint
