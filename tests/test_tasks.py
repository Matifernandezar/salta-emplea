"""Pruebas del adaptador con fixtures explícitos, nunca vacantes reales."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from salta_emplea import db, domain, tasks


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / 'prueba.sqlite3'
    db.init_db(path)
    connection = db.connect(path)
    yield connection
    connection.close()


def source():
    return {'id': 1, 'name': 'FUENTE DE PRUEBA', 'url': tasks.JOBICY_API,
            'method': 'jobicy', 'authorized': 1, 'status': 'active', 'frequency_hours': 24}


def payload():
    return {'jobs': [
        {'id': 1, 'jobTitle': 'OFERTA DE PRUEBA', 'companyName': 'Empresa de prueba',
         'jobGeo': 'Argentina', 'url': 'https://jobicy.com/jobs/oferta-de-prueba',
         'jobDescription': '<p>Texto externo <script>instrucciones falsas</script></p>',
         'pubDate': '2026-10-10 10:00:00', 'jobIndustry': ['Desarrollo'],
         'salaryMin': 100000},
        {'id': 2, 'jobTitle': 'PRUEBA USA', 'jobGeo': 'USA', 'url': 'https://jobicy.com/jobs/prueba-usa'},
        {'id': 3, 'jobTitle': 'PRUEBA GEO AUSENTE', 'url': 'https://jobicy.com/jobs/prueba-sin-geo'}]}


def test_import_repeated_requires_approval_no_invented_salary(conn):
    first = tasks.import_jobicy(conn, source(), lambda _: payload())
    second = tasks.import_jobicy(conn, source(), lambda _: payload())
    assert first == {'received': 3, 'eligible': 1, 'created': 1, 'duplicates': 0, 'invalid': 0}
    assert second['created'] == 0 and second['duplicates'] == 1
    job = conn.execute('SELECT * FROM jobs').fetchone()
    assert job['status'] == 'pending' and job['salary_amount'] is None
    assert job['requirements'] is None and job['location'] is None
    assert '<script>' not in job['description']
    assert json.loads(job['uncertain_fields'])
    assert not domain.public_jobs(conn)


def test_disabled_source_never_fetches(conn):
    disabled = source() | {'authorized': 0}
    with pytest.raises(ValueError):
        tasks.import_jobicy(conn, disabled, lambda _: pytest.fail('No debe consultar una fuente sin permiso'))


def test_incompatible_schema_is_not_silent_success(conn):
    with pytest.raises(ValueError):
        tasks.import_jobicy(conn, source(), lambda _: {'changed': []})


def test_errors_request_review_without_closing(conn, monkeypatch):
    current = domain.now()
    with conn:
        conn.execute('INSERT INTO sources(name,url,method,status,authorized,frequency_hours) VALUES (?,?,?,?,?,?)', ('FUENTE DE PRUEBA', tasks.JOBICY_API, 'jobicy', 'active', 1, 24))
    job_id, _ = domain.create_job(conn, {'title': 'PRUEBA', 'application_url': 'https://example.com/apply', 'source_name': 'Jobicy · FUENTE DE PRUEBA'})
    domain.transition_job(conn, job_id, 'approve', 'administrador')
    def broken(*_):
        raise TimeoutError('error de prueba')
    monkeypatch.setattr(tasks, 'import_jobicy', broken)
    tasks.run_tasks(conn, {'SECRET_KEY': 'prueba'}, only='collect')
    job = conn.execute('SELECT status,review_needed FROM jobs WHERE id=?', (job_id,)).fetchone()
    assert job['status'] == 'approved' and job['review_needed'] == 1
    assert conn.execute('SELECT status FROM task_runs ORDER BY id DESC').fetchone()[0] == 'partial'
    assert 'No se infiere cierre' in conn.execute('SELECT last_result FROM sources').fetchone()[0]


def test_source_window_prevents_repeated_requests(conn, monkeypatch):
    with conn:
        conn.execute('INSERT INTO sources(name,url,method,status,authorized,frequency_hours,last_run_at) VALUES (?,?,?,?,?,?,?)', ('FUENTE DE PRUEBA', tasks.JOBICY_API, 'jobicy', 'active', 1, 24, domain.now()))
    monkeypatch.setattr(tasks, 'import_jobicy', lambda *_: pytest.fail('Frecuencia de fuente debe respetarse'))
    assert tasks.run_tasks(conn, {'SECRET_KEY': 'prueba'}, only='collect')['sources'] == []


def test_no_sources_or_email_credentials_is_honest(conn):
    result = tasks.run_tasks(conn, {'SECRET_KEY': 'prueba', 'APP_ENV': 'development'})
    assert result['sources'] == [] and result['mail']['sent'] == 0
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0


def test_migrations_and_backup_preserve_data(conn, tmp_path):
    import sqlite3
    job_id, _ = domain.create_job(conn, {'title': 'PRUEBA DE PERSISTENCIA'})
    target_path = tmp_path / 'backup.sqlite3'
    with sqlite3.connect(target_path) as target:
        conn.backup(target)
    db.init_db(target_path)
    restored = db.connect(target_path)
    assert restored.execute('SELECT title FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'PRUEBA DE PERSISTENCIA'
    restored.close()


def test_redirects_are_rejected_before_contacting_target():
    with pytest.raises(ValueError):
        tasks.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/private')


@pytest.mark.parametrize('remote_status,expected,review', [('closed','archived',0), ('unknown','approved',1), ('active','approved',0)])
def test_reliable_status_closes_only_explicit_closed(conn, remote_status, expected, review):
    tasks.import_jobicy(conn, source(), lambda _: payload())
    job_id = conn.execute('SELECT id FROM jobs').fetchone()[0]
    domain.transition_job(conn, job_id, 'approve', 'administrador', acknowledge=True)
    result = tasks.check_jobicy_status(conn, source(), lambda _: {'jobs': [{'id': 1, 'status': remote_status}]})
    row = conn.execute('SELECT status,review_needed FROM jobs').fetchone()
    assert row['status'] == expected and row['review_needed'] == review
    assert result['archived'] == (1 if remote_status == 'closed' else 0)


def test_salary_only_when_all_source_fields_present(conn):
    data = payload()
    data['jobs'][0].update(salaryMin=1000, salaryMax=1500, salaryCurrency='USD', salaryPeriod='monthly')
    tasks.import_jobicy(conn, source(), lambda _: data)
    row = conn.execute('SELECT salary_amount,salary_currency,salary_period,salary_source_evidence FROM jobs').fetchone()
    assert row['salary_amount'] == '1000–1500' and row['salary_currency'] == 'USD' and row['salary_period'] == 'monthly'
    assert json.loads(row['salary_source_evidence'])['salaryMin'] == 1000
