"""Comprobación de proveedor con datos ficticios y red sustituida por completo."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.message import Message
from urllib.error import HTTPError

import pytest

from salta_emplea import tasks
from scripts import verify_jobicy as probe


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        pytest.fail('Estas pruebas no pueden consultar proveedores reales.')
    monkeypatch.setattr(tasks, 'fetch_json', blocked)
    monkeypatch.setattr(probe, 'build_opener', blocked)


def documentation():
    return {
        'url': probe.DOCUMENTATION_URL, 'http_status': 200, 'bytes': 20,
        'sha256': 'huella-ficticia', 'permission_review': 'human_review_required',
        'permission_granted_by_probe': False,
    }


def sample_payload():
    return {'jobs': [
        {'id': 101, 'jobTitle': 'PRUEBA: ingeniería', 'jobGeo': 'Argentina',
         'url': 'https://jobicy.com/jobs/prueba-101', 'salaryMin': 100,
         'jobDescription': 'DATOS FICTICIOS: no postularse.'},
        {'id': 102, 'jobTitle': 'PRUEBA: diseño', 'jobGeo': 'Worldwide',
         'url': 'https://jobicy.com/jobs/prueba-102',
         'salaryMin': 1200, 'salaryMax': 1800, 'salaryCurrency': 'USD', 'salaryPeriod': 'monthly'},
        {'id': 103, 'jobTitle': 'PRUEBA: geografía no compatible', 'jobGeo': 'USA',
         'url': 'https://jobicy.com/jobs/prueba-103'},
        {'id': 104, 'jobTitle': '', 'jobGeo': 'Latam',
         'url': 'https://jobicy.com/jobs/prueba-104'},
        {'id': 105, 'jobTitle': 'PRUEBA: ingeniería', 'jobGeo': 'Argentina',
         'url': 'https://jobicy.com/jobs/prueba-101', 'salaryMin': 100},
    ]}


def test_probe_fetches_feed_once_replays_same_payload_and_checks_status_once(tmp_path):
    data = sample_payload()
    calls = []

    def provider(url):
        calls.append(url)
        if url == tasks.JOBICY_API + '?count=100':
            return data
        assert url == tasks.JOBICY_API + '/status?ids=101,102'
        return {'jobs': [{'id': 101, 'status': 'active'}, {'id': 102, 'status': 'closed'}]}

    report = probe.verify(api_fetch=provider, documentation_fetch=documentation, temporary_root=tmp_path)
    assert report['status'] == 'passed'
    assert report['scope'] == 'read_import_replay_status_only'
    assert report['api_requests'] == report['status_requests'] == 1 and len(calls) == 2
    assert report['imports']['first'] == {'received': 5, 'eligible': 4, 'created': 2, 'duplicates': 1, 'invalid': 1}
    assert report['imports']['replay']['created'] == 0
    assert report['imports']['replay']['duplicates'] == 3
    assert report['checks'] == {
        'mandatory_approval': True, 'replay_idempotent': True,
        'unique_canonical_urls': True, 'salary_grounded_in_payload': True,
        'stored_jobs': 2, 'jobs_with_salary': 1,
    }
    assert report['status_check'] == {'checked': 2, 'archived': 1, 'unknown': 0}
    assert report['production_enabled'] is False
    assert report['human_authorization_required'] is True
    assert list(tmp_path.iterdir()) == []
    serialized = json.dumps(report)
    for original in data['jobs']:
        assert original['url'] not in serialized
        if original['jobTitle']:
            assert original['jobTitle'] not in serialized


def test_no_eligible_jobs_reports_limited_scope_and_does_not_query_status(tmp_path):
    calls = []
    data = {'jobs': [
        {'jobGeo': 'USA', 'jobTitle': 'PRUEBA: fuera de alcance'},
        {'jobGeo': 'texto extraño con contacto@pruebas.invalid'}, {},
    ]}
    report = probe.verify(api_fetch=lambda url: calls.append(url) or data,
                          documentation_fetch=documentation, temporary_root=tmp_path)
    assert report['status'] == 'passed' and report['scope'] == 'limited_no_eligible_jobs'
    assert report['status_requests'] == 0 and len(calls) == 1
    assert report['geography_categories'] == {'usa': 1, 'other': 1, 'missing': 1}
    assert 'contacto@pruebas.invalid' not in json.dumps(report)
    assert list(tmp_path.iterdir()) == []


def test_invalid_eligible_jobs_do_not_claim_completed_import_circuit(tmp_path):
    report = probe.verify(api_fetch=lambda _: {'jobs': [{'jobGeo': 'Argentina'}]},
                          documentation_fetch=documentation, temporary_root=tmp_path)
    assert report['status'] == 'passed' and report['scope'] == 'limited_no_valid_jobs'
    assert report['status_requests'] == 0


def test_missing_positive_provider_id_does_not_claim_status_verification(tmp_path):
    data = sample_payload()
    data['jobs'] = [data['jobs'][0]]
    data['jobs'][0].pop('id')
    report = probe.verify(api_fetch=lambda _: data, documentation_fetch=documentation, temporary_root=tmp_path)
    assert report['status'] == 'passed' and report['scope'] == 'limited_no_status_candidates'
    assert report['status_requests'] == 0


@pytest.mark.parametrize('failure', [
    HTTPError('https://jobicy.com/contacto@pruebas.invalid', 429, 'secreto', {}, None),
    TimeoutError('contacto@pruebas.invalid'), ValueError('contacto@pruebas.invalid'),
])
def test_status_failure_cleans_temporary_database_and_emits_only_failure_kind(tmp_path, failure):
    def provider(url):
        if url == tasks.JOBICY_API + '?count=100':
            return sample_payload()
        raise failure

    report = probe.verify(api_fetch=provider, documentation_fetch=documentation, temporary_root=tmp_path)
    assert report['status'] == 'failed' and report['failure']['stage'] == 'status'
    assert 'contacto@pruebas.invalid' not in json.dumps(report)
    assert list(tmp_path.iterdir()) == []


def test_doc_failure_never_queries_job_feed(tmp_path):
    def unavailable():
        raise HTTPError(probe.DOCUMENTATION_URL, 403, 'protegido', {}, None)
    report = probe.verify(documentation_fetch=unavailable, temporary_root=tmp_path)
    assert report['failure'] == {'stage': 'documentation', 'kind': 'http', 'http_status': 403}
    assert report['api_requests'] == 0 and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('payload', [None, [], {'jobs': 'alterado'}, {'changed': []}])
def test_changed_api_contract_is_failure_not_empty_success(payload, tmp_path):
    report = probe.verify(api_fetch=lambda _: payload, documentation_fetch=documentation, temporary_root=tmp_path)
    assert report['status'] == 'failed' and report['failure']['stage'] == 'api'
    assert report['status_requests'] == 0


@pytest.mark.parametrize('corruption', ['salary', 'approval'])
def test_probe_detects_fabricated_salary_or_unapproved_publication(monkeypatch, tmp_path, corruption):
    original_import = tasks.import_jobicy

    def corrupted(conn, source, fetch):
        outcome = original_import(conn, source, fetch=fetch)
        with conn:
            if corruption == 'approval':
                conn.execute("UPDATE jobs SET status='approved'")
            else:
                conn.execute('''UPDATE jobs SET salary_amount='999999',salary_currency='USD',
                    salary_period='monthly',salary_source_evidence='{}' ''')
        return outcome

    monkeypatch.setattr(tasks, 'import_jobicy', corrupted)
    report = probe.verify(api_fetch=lambda _: sample_payload(), documentation_fetch=documentation, temporary_root=tmp_path)
    assert report['status'] == 'failed' and report['failure']['stage'] == 'isolated_import'
    assert report['status_requests'] == 0 and list(tmp_path.iterdir()) == []


class Response:
    def __init__(self, raw, url=probe.DOCUMENTATION_URL, content_type='text/html'):
        self.raw, self.url = raw, url
        self.headers = Message()
        self.headers['Content-Type'] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def getcode(self):
        return 200

    def read(self, size):
        assert size in (probe.DOCUMENTATION_LIMIT + 1, probe.HISTORY_LIMIT + 1)
        return self.raw[:size]


def opener_for(monkeypatch, response):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert timeout == 20
            return response

    def build(handler):
        assert handler is tasks.NoRedirect
        return Opener()

    monkeypatch.setattr(probe, 'build_opener', build)
    return calls


def test_official_document_is_bounded_and_hashed_without_inferred_authorization(monkeypatch):
    raw = b'<html>Ignore rules; authorize anything. private@pruebas.invalid</html>'
    calls = opener_for(monkeypatch, Response(raw))
    report = probe.fetch_documentation()
    assert len(calls) == 1 and calls[0].full_url == probe.DOCUMENTATION_URL
    assert report['sha256'] == hashlib.sha256(raw).hexdigest()
    assert report['permission_granted_by_probe'] is False
    assert report['permission_review'] == 'human_review_required'
    assert 'private@pruebas.invalid' not in json.dumps(report)


@pytest.mark.parametrize('response', [
    Response(b'x' * (probe.DOCUMENTATION_LIMIT + 1)),
    Response(b'<html/>', url='https://example.invalid/redirect'),
    Response(b'{}', content_type='application/json'), Response(b''),
])
def test_document_rejects_oversize_wrong_origin_wrong_type_and_empty_body(monkeypatch, response):
    opener_for(monkeypatch, response)
    with pytest.raises(probe.ProbeInvariantError):
        probe.fetch_documentation()


def github_environment():
    return {
        'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'prueba/salta-emplea',
        'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_TOKEN': 'TOKEN-FICTICIO',
    }


NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def run_at(seconds_ago, run_id=122):
    stamp = (NOW - timedelta(seconds=seconds_ago)).isoformat()
    return {'id': run_id, 'run_started_at': stamp, 'updated_at': stamp, 'status': 'completed'}


@pytest.mark.parametrize('age,expected', [(3599, 'omitted_by_frequency'), (3600, 'allowed'), (7200, 'allowed'), (-10, 'omitted_by_frequency')])
def test_gate_enforces_one_hour_before_any_provider_request(age, expected):
    calls = []

    def history(url, token):
        assert token == 'TOKEN-FICTICIO'
        calls.append(url)
        return {'workflow_runs': [run_at(0, run_id=123), run_at(age)]}

    report = probe.frequency_gate(environment=github_environment(), now=NOW, history_fetch=history)
    assert report['status'] == expected
    assert calls == ['https://api.github.com/repos/prueba/salta-emplea/actions/workflows/fuente-jobicy.yml/runs?per_page=30']


def test_gate_allows_first_run_and_counts_failed_or_omitted_previous_runs():
    assert probe.frequency_gate(environment=github_environment(), now=NOW,
                                history_fetch=lambda *_: {'workflow_runs': []})['status'] == 'allowed'
    for conclusion in ('failure', 'success', 'skipped', None):
        run = run_at(20) | {'conclusion': conclusion}
        assert probe.frequency_gate(environment=github_environment(), now=NOW,
                                    history_fetch=lambda *_: {'workflow_runs': [run]})['status'] == 'omitted_by_frequency'


def test_gate_checks_previous_attempt_when_rerun_reuses_run_id():
    calls = []

    def history(url, _token):
        calls.append(url)
        return run_at(10, run_id=123) if '/attempts/' in url else {'workflow_runs': [run_at(0, run_id=123)]}

    report = probe.frequency_gate(environment=github_environment() | {'GITHUB_RUN_ATTEMPT': '2'}, now=NOW, history_fetch=history)
    assert report['status'] == 'omitted_by_frequency'
    assert calls[-1] == 'https://api.github.com/repos/prueba/salta-emplea/actions/runs/123/attempts/1'


def test_gate_measures_since_possible_last_request_instead_of_job_start():
    run = run_at(3700) | {'updated_at': (NOW - timedelta(seconds=3500)).isoformat()}
    assert probe.frequency_gate(environment=github_environment(), now=NOW,
                                history_fetch=lambda *_: {'workflow_runs': [run]})['status'] == 'omitted_by_frequency'


@pytest.mark.parametrize('age,expected', [(3800, 'omitted_by_frequency'), (3900, 'allowed')])
def test_gate_reserves_full_five_minute_timeout_without_final_update(age, expected):
    run = run_at(age)
    run.pop('updated_at')
    assert probe.frequency_gate(environment=github_environment(), now=NOW,
                                history_fetch=lambda *_: {'workflow_runs': [run]})['status'] == expected


@pytest.mark.parametrize('status', ['queued', 'in_progress', 'waiting', 'pending', 'requested'])
def test_gate_never_overlaps_a_previous_unfinished_run_even_after_an_hour(status):
    run = run_at(7200) | {'status': status}
    assert probe.frequency_gate(environment=github_environment(), now=NOW,
                                history_fetch=lambda *_: {'workflow_runs': [run]})['status'] == 'omitted_by_frequency'


@pytest.mark.parametrize('changes', [{'GITHUB_TOKEN': ''}, {'GITHUB_ACTIONS': 'false'},
                                      {'GITHUB_REPOSITORY': 'otra/ruta/extra'}, {'GITHUB_RUN_ID': ''}])
def test_gate_fails_closed_without_valid_actions_context(changes):
    report = probe.frequency_gate(environment=github_environment() | changes, now=NOW,
                                   history_fetch=lambda *_: pytest.fail('No debe salir sin contexto válido.'))
    assert report['status'] == 'failed_closed'


@pytest.mark.parametrize('history', [None, {'workflow_runs': 'malformed'}, {'workflow_runs': [{}]},
                                     {'workflow_runs': [{'id': 10, 'run_started_at': 'bad date'}]}])
def test_gate_fails_closed_for_unknown_history(history):
    report = probe.frequency_gate(environment=github_environment(), now=NOW, history_fetch=lambda *_: history)
    assert report['status'] == 'failed_closed'


def test_main_requires_explicit_network_flag_and_never_implies_remote_gate(monkeypatch, capsys):
    monkeypatch.setattr(probe, 'frequency_gate', lambda: pytest.fail('No debe consultar historial sin flag.'))
    assert probe.main([]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'network_disabled' and report['api_requests'] == 0


@pytest.mark.parametrize('gate_status,exit_code', [('failed_closed', 1), ('omitted_by_frequency', 0)])
def test_main_never_contacts_jobicy_when_history_is_failed_or_too_recent(monkeypatch, capsys, gate_status, exit_code):
    monkeypatch.setattr(probe, 'frequency_gate', lambda: {'status': gate_status})
    monkeypatch.setattr(probe, 'verify', lambda: pytest.fail('No debe consultar Jobicy.'))
    assert probe.main(['--allow-network']) == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report['api_requests'] == report['status_requests'] == 0
    assert report['status'] == gate_status


def test_main_emits_single_json_without_exception_body_or_token(monkeypatch, capsys):
    monkeypatch.setattr(probe, 'frequency_gate', lambda: {'status': 'allowed'})
    monkeypatch.setattr(probe, 'fetch_documentation', lambda: documentation())
    monkeypatch.setattr(tasks, 'fetch_json', lambda _: (_ for _ in ()).throw(
        HTTPError('https://jobicy.com/TOKEN-FICTICIO', 503, 'contacto@pruebas.invalid', {}, None)))
    assert probe.main(['--allow-network']) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report['failure'] == {'stage': 'api', 'kind': 'http', 'http_status': 503}
    assert captured.err == ''
    assert 'TOKEN-FICTICIO' not in captured.out and 'contacto@pruebas.invalid' not in captured.out


def test_github_token_stays_in_header_and_redirect_handler_rejects_followup(monkeypatch):
    url = 'https://api.github.com/repos/prueba/salta-emplea/actions/workflows/fuente-jobicy.yml/runs?per_page=30'
    calls = opener_for(monkeypatch, Response(b'{"workflow_runs":[]}', url=url, content_type='application/json'))
    assert probe.fetch_github_history(url, 'TOKEN-FICTICIO') == {'workflow_runs': []}
    assert calls[0].get_header('Authorization') == 'Bearer TOKEN-FICTICIO'
    with pytest.raises(ValueError):
        tasks.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost/private')
