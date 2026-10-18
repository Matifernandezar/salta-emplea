"""Tareas explícitas, acotadas y recuperables. No publican ofertas."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import db, domain

JOBICY_API = 'https://jobicy.com/api/v2/remote-jobs'
TASK_LOCK_NAME = 'salta-emplea-tasks'


class TaskBudgetExceeded(RuntimeError):
    """La corrida conserva el trabajo confirmado y continúa en el próximo lote."""


def _check_budget(deadline, required_seconds=0):
    if deadline is not None and time.monotonic() + required_seconds >= deadline:
        raise TaskBudgetExceeded('Presupuesto de ejecución agotado; trabajo pendiente conservado.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('La fuente intentó redirigir la consulta; requiere revisión.')


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(str(value or '')[:100_000])
    return unescape(' '.join(parser.parts)).strip()[:20_000]


def eligible_geo(value):
    """Solo candidatos con geografía explícita compatible; siempre revisión humana."""
    geo = str(value or '').strip().casefold()
    return geo in {'anywhere', 'worldwide', 'argentina', 'latin america', 'latam', 'south america', 'global'}


def fetch_json(url):
    req = Request(url, headers={'User-Agent': 'SaltaEmplea/0.1 (revision editorial; atribucion Jobicy)'})
    with build_opener(NoRedirect).open(req, timeout=20) as response:
        if response.geturl().split('?')[0] not in (JOBICY_API, JOBICY_API + '/status'):
            raise ValueError('Origen inesperado del proveedor.')
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('La respuesta excede el límite de tamaño.')
        return json.loads(raw)


def check_jobicy_status(conn, source, fetch=None, *, deadline=None):
    """Solo un `closed` explícito archiva; unknown/errores solicitan revisión."""
    if not source['authorized'] or source['status'] != 'active' or source['url'] != JOBICY_API:
        raise ValueError('Fuente sin autorización o URL incompatible.')
    candidates = {}
    for row in conn.execute("SELECT id,original_text FROM jobs WHERE source_name=? AND status IN ('approved','pending') ORDER BY COALESCE(last_checked_at,collected_at) ASC LIMIT 100", ('Jobicy · ' + source['name'],)):
        try:
            provider_id = json.loads(row['original_text'])['id']
            if type(provider_id) is int and provider_id > 0:
                candidates[provider_id] = row['id']
        except (ValueError, TypeError, KeyError):
            with conn:
                conn.execute('UPDATE jobs SET review_needed=1 WHERE id=?', (row['id'],))
    result = {'checked': 0, 'archived': 0, 'unknown': 0}
    if not candidates:
        return result
    _check_budget(deadline, 20)
    data = (fetch or fetch_json)(JOBICY_API + '/status?ids=' + ','.join(str(x) for x in candidates))
    if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
        raise ValueError('Respuesta de estado incompatible.')
    answers = {item.get('id'): item.get('status') for item in data['jobs'] if isinstance(item, dict) and type(item.get('id')) is int}
    for provider_id, job_id in candidates.items():
        _check_budget(deadline)
        status = answers.get(provider_id, 'unknown')
        if status == 'closed':
            domain.transition_job(conn, job_id, 'archive', 'recopilador_autorizado')
            result['archived'] += 1
        elif status == 'active':
            with conn:
                conn.execute('UPDATE jobs SET last_checked_at=? WHERE id=?', (domain.now(), job_id))
        else:
            with conn:
                conn.execute('UPDATE jobs SET review_needed=1 WHERE id=?', (job_id,))
            result['unknown'] += 1
        result['checked'] += 1
    return result


def _jobicy_original(row):
    """Conservar JSON válido y el ID aun cuando el original supere el límite."""
    original = json.dumps(row, ensure_ascii=False)
    if len(original) <= 20_000:
        return original, False
    provider_id = row.get('id')
    excerpt = {
        'id': provider_id if type(provider_id) is int and provider_id > 0 else None,
        'original_excerpt': original[:8_000],
        'original_truncated': True,
    }
    # El escape JSON del fragmento puede duplicar su longitud: se reserva margen.
    return json.dumps(excerpt, ensure_ascii=False), True


def import_jobicy(conn, source, fetch=None, *, deadline=None):
    if not source['authorized'] or source['status'] != 'active' or source['url'] != JOBICY_API:
        raise ValueError('Fuente sin autorización o URL incompatible.')
    _check_budget(deadline, 20)
    payload = (fetch or fetch_json)(JOBICY_API + '?count=100')
    if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
        raise ValueError('Respuesta incompatible: no hay lista jobs.')
    result = {'received': len(payload['jobs']), 'eligible': 0, 'created': 0, 'duplicates': 0, 'invalid': 0}
    for row in payload['jobs'][:100]:
        _check_budget(deadline)
        if not isinstance(row, dict) or not eligible_geo(row.get('jobGeo')):
            continue
        result['eligible'] += 1
        try:
            before = conn.execute('SELECT count(*) FROM jobs').fetchone()[0]
            description = plain(row.get('jobDescription'))
            original_text, original_truncated = _jobicy_original(row)
            data = {
                'title': plain(row.get('jobTitle')), 'company': plain(row.get('companyName')),
                'location': None, 'modality': 'remota',
                'sector': ', '.join(plain(x) for x in row.get('jobIndustry', []) if x) if isinstance(row.get('jobIndustry'), list) else plain(row.get('jobIndustry')),
                'contract_type': ', '.join(plain(x) for x in row.get('jobType', []) if x) if isinstance(row.get('jobType'), list) else plain(row.get('jobType')),
                'description': description, 'original_text': original_text,
                'source_url': row.get('url'), 'source_name': 'Jobicy · ' + source['name'],
                'application_url': row.get('url'), 'original_date': row.get('pubDate'),
                'last_checked_at': domain.now(),
                'uncertain_fields': [f"Confirmar residencia y zona horaria: {plain(row.get('jobGeo'))}", 'Revisar requisitos y condiciones en la fuente original'],
            }
            if original_truncated:
                data['uncertain_fields'].append('El original es extenso: se guardó un fragmento. Consultar el aviso completo en la fuente.')
            minimum, maximum = row.get('salaryMin'), row.get('salaryMax')
            numeric = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
            if row.get('salaryCurrency') and row.get('salaryPeriod') and (numeric(minimum) or numeric(maximum)):
                amount = f'{minimum}–{maximum}' if numeric(minimum) and numeric(maximum) else f'Desde {minimum}' if numeric(minimum) else f'Hasta {maximum}'
                data.update(salary_amount=amount, salary_currency=plain(row['salaryCurrency']), salary_period=plain(row['salaryPeriod']), salary_source_evidence=json.dumps({key: row.get(key) for key in ('salaryMin', 'salaryMax', 'salaryCurrency', 'salaryPeriod')}, ensure_ascii=False))
            # No inferir moneda, período, requisitos ni fechas ausentes.
            domain.create_job(conn, data, actor='recopilador_autorizado')
            after = conn.execute('SELECT count(*) FROM jobs').fetchone()[0]
            result['created' if after > before else 'duplicates'] += 1
        except (ValueError, TypeError, KeyError):
            result['invalid'] += 1
    return result


def run_tasks(conn, config, only=None):
    """Ejecuta un lote bajo el mismo bloqueo para CLI y cron HTTP.

    El lease es mayor que la duración máxima de la función de Vercel. Se toma
    antes de recuperar task_runs para que una corrida concurrente jamás marque
    como interrumpida a otra todavía en curso.
    """
    if only not in (None, 'collect', 'expire', 'mail'):
        raise ValueError('Tarea desconocida.')
    budget = max(1, min(int(config.get('TASK_BUDGET_SECONDS', 180)), 240))
    deadline = time.monotonic() + budget
    with db.task_lock(conn, TASK_LOCK_NAME, ttl_seconds=900) as acquired:
        if not acquired:
            return {'skipped': 'Ya hay una tarea en ejecución; se omite esta corrida.'}
        return _run_locked_tasks(conn, config, only, deadline)


def _run_locked_tasks(conn, config, only, deadline):
    from . import mailer
    # Solo quien obtuvo el bloqueo puede recuperar una corrida interrumpida.
    with conn:
        conn.execute("UPDATE task_runs SET status='interrupted',finished_at=?,detail='Proceso anterior interrumpido; se recupera con operaciones idempotentes.' WHERE status='running'", (domain.now(),))
        run_id = conn.execute("INSERT INTO task_runs(task,started_at,status) VALUES (?,?,'running')", (only or 'all', domain.now())).lastrowid
    result, failed = {}, False
    try:
        if only in (None, 'collect'):
            result['sources'] = []
            source_limit = max(1, min(int(config.get('TASK_SOURCE_BATCH', 1)), 10))
            processed = 0
            for row in conn.execute("SELECT * FROM sources WHERE status='active' AND authorized=1 AND method='jobicy' ORDER BY COALESCE(last_run_at,''),id").fetchall():
                _check_budget(deadline)
                source = dict(row)
                if source['last_run_at']:
                    due = datetime.fromisoformat(source['last_run_at']) + timedelta(hours=max(6, source['frequency_hours']))
                    if due > datetime.now(timezone.utc):
                        continue
                if processed >= source_limit:
                    result['sources_deferred'] = True
                    break
                processed += 1
                try:
                    _check_budget(deadline, 20)
                    outcome = import_jobicy(conn, source, deadline=deadline)
                    outcome['status_check'] = check_jobicy_status(conn, source, deadline=deadline)
                    message = json.dumps(outcome, ensure_ascii=False)
                    result['sources'].append({'id': source['id'], **outcome})
                except TaskBudgetExceeded:
                    # No retrasar por frecuencia una fuente que quedó a medias.
                    # Repetir la recopilación recupera lo pendiente sin publicar.
                    with conn:
                        conn.execute('UPDATE sources SET last_result=? WHERE id=?', ('Lote interrumpido por tiempo; se retomará de forma idempotente.', source['id']))
                    raise
                except Exception as exc:
                    # Un fallo temporal nunca cierra ni vence las ofertas.
                    message = 'Revisar fuente: error temporal o respuesta incompatible (' + type(exc).__name__ + '). No se infiere cierre.'
                    failed = True
                    with conn:
                        conn.execute("UPDATE jobs SET review_needed=1 WHERE source_name=?", ('Jobicy · ' + source['name'],))
                with conn:
                    conn.execute('UPDATE sources SET last_result=?,last_run_at=? WHERE id=?', (message, domain.now(), source['id']))
        if only in (None, 'expire'):
            _check_budget(deadline)
            setting = conn.execute("SELECT value FROM settings WHERE key='review_days'").fetchone()
            result['expiration'] = domain.expire_jobs(conn, int(setting[0]) if setting else 30)
        if only in (None, 'mail'):
            _check_budget(deadline)
            batch = max(1, min(int(config.get('TASK_MAIL_BATCH', 10)), 100))
            result['queue'] = mailer.queue_digests(conn, config.get('PUBLIC_BASE_URL', ''), config['SECRET_KEY'], limit=batch, deadline=deadline) if config.get('PUBLIC_BASE_URL') else {'skipped': 'PUBLIC_BASE_URL sin configurar'}
            result['mail'] = mailer.send_outbox(conn, config, limit=batch, deadline=deadline)
            failed = failed or result['mail'].get('errors', 0) > 0
            if result['queue'].get('budget_exhausted') or result['mail'].get('budget_exhausted'):
                result['budget_exhausted'] = True
                failed = True
        with conn:
            conn.execute('DELETE FROM rate_limits WHERE CAST(reset_at AS INTEGER)<?', (int(time.time())-86400,))
            conn.execute('UPDATE task_runs SET status=?,finished_at=?,detail=? WHERE id=?', ('partial' if failed else 'succeeded', domain.now(), json.dumps(result, ensure_ascii=False), run_id))
        return result
    except TaskBudgetExceeded:
        result['budget_exhausted'] = True
        with conn:
            conn.execute('UPDATE task_runs SET status=\'partial\',finished_at=?,detail=? WHERE id=?', (domain.now(), json.dumps(result, ensure_ascii=False), run_id))
        return result
    except Exception as exc:
        with conn:
            conn.execute("UPDATE task_runs SET status='failed',finished_at=?,detail=? WHERE id=?", (domain.now(), type(exc).__name__, run_id))
        raise
