"""Comprobación real, acotada y aislada de Jobicy; nunca publica ni conserva avisos.

La descarga documental aporta una huella para revisión humana, no concede permiso.
La autorización de la fuente de ensayo existe solo en memoria y en una SQLite
temporal; no se lee configuración, credenciales ni la base de la aplicación.
"""
import argparse
import hashlib
import json
import math
import os
import re
import socket
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from salta_emplea import db, domain, tasks

DOCUMENTATION_URL = 'https://jobicy.com/jobs-rss-feed'
DOCUMENTATION_LIMIT = 2_000_000
HISTORY_LIMIT = 1_000_000
GEOGRAPHIES = {
    'anywhere', 'worldwide', 'argentina', 'latin america', 'latam',
    'south america', 'global', 'usa', 'united states', 'europe', 'uk',
    'united kingdom', 'canada', 'australia', 'germany', 'france', 'spain',
}


class ProbeInvariantError(ValueError):
    """Una garantía editorial o el contrato del proveedor no se cumplió."""


def fetch_github_history(url, token):
    """Lectura mínima del historial propio; token efímero solo en cabecera."""
    request = Request(url, headers={
        'User-Agent': 'SaltaEmplea/0.1 (limite de consulta Jobicy)',
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer ' + token,
        'X-GitHub-Api-Version': '2022-11-28',
    })
    with build_opener(tasks.NoRedirect).open(request, timeout=20) as response:
        if response.geturl() != url or response.getcode() != 200:
            raise ProbeInvariantError('history_response')
        raw = response.read(HISTORY_LIMIT + 1)
        if len(raw) > HISTORY_LIMIT:
            raise ProbeInvariantError('history_size')
        return json.loads(raw)


def frequency_gate(*, environment=None, now=None, history_fetch=None):
    """Fail closed si no se puede confirmar una hora desde el último intento."""
    environment = os.environ if environment is None else environment
    now = now or datetime.now(timezone.utc)
    fetch = history_fetch or fetch_github_history
    try:
        repository = environment.get('GITHUB_REPOSITORY', '')
        run_id = environment.get('GITHUB_RUN_ID', '')
        token = environment.get('GITHUB_TOKEN', '')
        attempt = environment.get('GITHUB_RUN_ATTEMPT', '1')
        if (environment.get('GITHUB_ACTIONS') != 'true' or not token
                or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
                or not re.fullmatch(r'[1-9][0-9]*', run_id)
                or not re.fullmatch(r'[1-9][0-9]*', attempt)):
            raise ProbeInvariantError('history_environment')
        base = 'https://api.github.com/repos/' + repository + '/actions/'
        history = fetch(base + 'workflows/fuente-jobicy.yml/runs?per_page=30', token)
        if not isinstance(history, dict) or not isinstance(history.get('workflow_runs'), list):
            raise ProbeInvariantError('history_contract')
        previous = []
        for run in history['workflow_runs']:
            if not isinstance(run, dict) or type(run.get('id')) is not int:
                raise ProbeInvariantError('history_contract')
            if str(run['id']) != run_id:
                previous.append(run)
        if int(attempt) > 1:
            # Reruns conservan run_id: el historial de runs no incluye su intento anterior.
            earlier = fetch(base + 'runs/' + run_id + '/attempts/' + str(int(attempt) - 1), token)
            if not isinstance(earlier, dict) or str(earlier.get('id')) != run_id:
                raise ProbeInvariantError('history_attempt_contract')
            previous.append(earlier)
        for run in previous:
            if run.get('status') in ('queued', 'in_progress', 'waiting', 'pending', 'requested'):
                return {'status': 'omitted_by_frequency', 'minimum_interval_seconds': 3600}
            stamp = run.get('run_started_at') or run.get('created_at')
            if not isinstance(stamp, str):
                raise ProbeInvariantError('history_date')
            started = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if started.tzinfo is None:
                raise ProbeInvariantError('history_date')
            # Una consulta puede ocurrir después del inicio del job. El update
            # final es una cota conservadora; sin él se reserva todo el timeout.
            if run.get('updated_at'):
                finished = datetime.fromisoformat(run['updated_at'].replace('Z', '+00:00'))
                if finished.tzinfo is None:
                    raise ProbeInvariantError('history_date')
                last_possible_request = max(started, finished)
            else:
                last_possible_request = started + timedelta(minutes=5)
            if (now - last_possible_request).total_seconds() < 3600:
                return {'status': 'omitted_by_frequency', 'minimum_interval_seconds': 3600}
        return {'status': 'allowed', 'minimum_interval_seconds': 3600}
    except Exception as exc:
        return {'status': 'failed_closed', 'failure': _failure(exc, 'github_history')}


def fetch_documentation():
    """Solo el documento oficial fijo; no seguir redirecciones ni sus enlaces."""
    request = Request(DOCUMENTATION_URL, headers={
        'User-Agent': 'SaltaEmplea/0.1 (comprobacion documental aislada)',
    })
    with build_opener(tasks.NoRedirect).open(request, timeout=20) as response:
        if response.geturl() != DOCUMENTATION_URL or response.getcode() != 200:
            raise ProbeInvariantError('documentation_response')
        content_type = response.headers.get_content_type()
        if content_type not in ('text/html', 'application/xhtml+xml'):
            raise ProbeInvariantError('documentation_content_type')
        raw = response.read(DOCUMENTATION_LIMIT + 1)
        if not raw or len(raw) > DOCUMENTATION_LIMIT:
            raise ProbeInvariantError('documentation_size')
    return {
        'url': DOCUMENTATION_URL, 'http_status': 200, 'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'permission_review': 'human_review_required',
        'permission_granted_by_probe': False,
    }


def _fail_if(condition):
    if condition:
        # Los detalles externos nunca se interpolan en errores o registros.
        raise ProbeInvariantError('editorial_invariant')


def _salary_matches(job, original):
    """Cada importe almacenado debe estar respaldado por el mismo aviso recibido."""
    fields = ('salary_amount', 'salary_currency', 'salary_period', 'salary_source_evidence')
    saved = tuple(job[field] for field in fields)
    if all(value is None for value in saved):
        return True
    if not all(value is not None for value in saved):
        return False
    try:
        evidence = json.loads(job['salary_source_evidence'])
    except (TypeError, ValueError):
        return False
    keys = ('salaryMin', 'salaryMax', 'salaryCurrency', 'salaryPeriod')
    if evidence != {key: original.get(key) for key in keys}:
        return False

    def numeric(value):
        return type(value) in (int, float) and value >= 0 and math.isfinite(value)

    minimum, maximum = original.get('salaryMin'), original.get('salaryMax')
    if not original.get('salaryCurrency') or not original.get('salaryPeriod'):
        return False
    if numeric(minimum) and numeric(maximum):
        expected = f'{minimum}–{maximum}'
    elif numeric(minimum):
        expected = f'Desde {minimum}'
    elif numeric(maximum):
        expected = f'Hasta {maximum}'
    else:
        return False
    return (job['salary_amount'] == expected
            and job['salary_currency'] == tasks.plain(original['salaryCurrency'])
            and job['salary_period'] == tasks.plain(original['salaryPeriod']))


def _check_imports(conn, payload, first, second, first_count, first_provenance):
    jobs = conn.execute('SELECT * FROM jobs').fetchall()
    _fail_if(any(job['status'] != 'pending' or job['approved_at'] is not None for job in jobs))
    _fail_if(bool(domain.public_jobs(conn)))
    _fail_if(len(jobs) != first_count or second['created'] != 0)
    _fail_if(second['duplicates'] != first['created'] + first['duplicates'])
    _fail_if(second['invalid'] != first['invalid'])
    _fail_if(conn.execute('SELECT count(*) FROM provenance').fetchone()[0] != first_provenance)
    _fail_if(bool(conn.execute('''SELECT 1 FROM jobs
        WHERE source_canonical_url IS NOT NULL GROUP BY source_canonical_url
        HAVING count(*)>1 LIMIT 1''').fetchone()))
    originals = {}
    for original in payload['jobs'][:100]:
        if not isinstance(original, dict) or not tasks.eligible_geo(original.get('jobGeo')):
            continue
        try:
            canonical = domain.canonical_url(original.get('url'))
        except (TypeError, ValueError):
            continue
        originals.setdefault(canonical, []).append(original)
    for job in jobs:
        _fail_if(not any(_salary_matches(job, original)
                         for original in originals.get(job['source_canonical_url'], [])))
    return {
        'mandatory_approval': True, 'replay_idempotent': True,
        'unique_canonical_urls': True, 'salary_grounded_in_payload': True,
        'stored_jobs': len(jobs),
        'jobs_with_salary': sum(job['salary_amount'] is not None for job in jobs),
    }


def _failure(exc, stage):
    result = {'stage': stage}
    if isinstance(exc, HTTPError):
        result.update(kind='http', http_status=exc.code)
    elif isinstance(exc, (TimeoutError, socket.timeout)):
        result['kind'] = 'timeout'
    elif isinstance(exc, URLError):
        result['kind'] = 'network'
    elif isinstance(exc, ProbeInvariantError):
        result['kind'] = 'invariant_or_document_contract'
    elif isinstance(exc, (ValueError, TypeError, KeyError)):
        result['kind'] = 'provider_contract'
    else:
        result['kind'] = 'internal'
    return result


def verify(*, api_fetch=None, documentation_fetch=None, temporary_root=None):
    """Una lectura del feed y, si corresponde, una de estado; replay sin red."""
    fetch = api_fetch or tasks.fetch_json
    report = {
        'schema_version': 1, 'source': 'Jobicy', 'status': 'failed',
        'production_enabled': False, 'human_authorization_required': True,
        'api_requests': 0, 'status_requests': 0,
    }
    stage = 'documentation'
    try:
        report['documentation'] = (documentation_fetch or fetch_documentation)()
        stage = 'api'
        report['api_requests'] = 1
        payload = fetch(tasks.JOBICY_API + '?count=100')
        if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
            raise ProbeInvariantError('api_contract')
        geographies = Counter()
        for item in payload['jobs'][:100]:
            value = item.get('jobGeo') if isinstance(item, dict) else None
            value = str(value or '').strip().casefold()
            geographies[value if value in GEOGRAPHIES else 'other' if value else 'missing'] += 1
        report['geography_categories'] = dict(sorted(geographies.items()))
        # El replay comparte el mismo objeto recibido; no vuelve a consultar.
        def cached(url):
            _fail_if(url != tasks.JOBICY_API + '?count=100')
            return payload

        stage = 'isolated_import'
        with tempfile.TemporaryDirectory(prefix='salta-jobicy-probe-', dir=temporary_root) as folder:
            database = Path(folder) / 'exclusive-probe.sqlite3'
            db.init_db(database)
            conn = db.connect(database)
            try:
                source = {
                    'name': 'COMPROBACIÓN AISLADA', 'url': tasks.JOBICY_API,
                    'authorized': 1, 'status': 'active',
                }
                first = tasks.import_jobicy(conn, source, fetch=cached)
                first_count = conn.execute('SELECT count(*) FROM jobs').fetchone()[0]
                first_provenance = conn.execute('SELECT count(*) FROM provenance').fetchone()[0]
                second = tasks.import_jobicy(conn, source, fetch=cached)
                report['imports'] = {'first': first, 'replay': second}
                report['checks'] = _check_imports(conn, payload, first, second, first_count, first_provenance)

                stage = 'status'
                def status_fetch(url):
                    _fail_if(report['status_requests'] != 0
                             or not url.startswith(tasks.JOBICY_API + '/status?ids='))
                    report['status_requests'] += 1
                    return fetch(url)

                report['status_check'] = tasks.check_jobicy_status(conn, source, fetch=status_fetch)
                _fail_if(conn.execute("SELECT count(*) FROM jobs WHERE status='approved'").fetchone()[0] != 0)
                _fail_if(bool(domain.public_jobs(conn)))
            finally:
                conn.close()
        report['status'] = 'passed'
        if first['eligible'] == 0:
            report['scope'] = 'limited_no_eligible_jobs'
        elif first_count == 0:
            report['scope'] = 'limited_no_valid_jobs'
        elif report['status_check']['checked'] == 0:
            report['scope'] = 'limited_no_status_candidates'
        else:
            report['scope'] = 'read_import_replay_status_only'
    except Exception as exc:
        report['failure'] = _failure(exc, stage)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-network', action='store_true',
                        help='Habilitar consultas solo en GitHub Actions tras verificar la frecuencia.')
    args = parser.parse_args(argv)
    if not args.allow_network:
        report = {
            'source': 'Jobicy', 'status': 'network_disabled',
            'production_enabled': False, 'api_requests': 0, 'status_requests': 0,
        }
    else:
        gate = frequency_gate()
        if gate['status'] == 'allowed':
            report = verify()
            report['frequency_gate'] = gate
        else:
            report = {
                'source': 'Jobicy', 'status': gate['status'],
                'production_enabled': False, 'api_requests': 0, 'status_requests': 0,
                'frequency_gate': gate,
            }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report['status'] in ('passed', 'omitted_by_frequency') else 1


if __name__ == '__main__':
    raise SystemExit(main())
