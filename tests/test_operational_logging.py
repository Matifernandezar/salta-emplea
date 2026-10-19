"""Registro de cron: autenticación y redacción sin llamadas a proveedores."""
import json
import logging

from salta_emplea.app import create_app
from salta_emplea.operations import source_collection_summary, task_summary


def test_summary_keeps_only_bounded_integer_counters_and_no_external_content():
    result = {'sources': [{'received': 10, 'eligible': 2, 'created': 1, 'duplicates': 1,
        'original_text': 'SECRETO EXTERNO', 'url': 'https://user:SECRETO@example.test',
        'error': 'SECRETO EXTERNO'}, {'created': True, 'received': -1, 'invalid': 'SECRETO'}],
        'mail': {'sent': 2, 'errors': False, 'recipient': 'SECRETO@example.test'},
        'skipped': 'SECRETO', 'budget_exhausted': 'SECRETO'}
    value = task_summary('collect', result)
    assert value['created'] == 1 and value['received'] == 10
    assert value['mail'] == {'sent': 2}
    assert value['skipped'] is True and value['budget_exhausted'] is False
    assert 'SECRETO' not in json.dumps(value)


def test_cron_logs_real_returned_counters_only_after_authentication(tmp_path, monkeypatch, caplog):
    from salta_emplea import tasks
    app = create_app({'TESTING': True, 'APP_ENV': 'development', 'SECRET_KEY': 'clave-local',
        'CRON_SECRET': 'cron-ficticio-no-publicar', 'DATABASE_PATH': str(tmp_path / 'cron.sqlite'),
        'UPLOAD_DIR': str(tmp_path / 'imagenes')})
    calls = []
    def run(_conn, _config, *, only):
        calls.append(only)
        return {'sources': [{'received': 10, 'eligible': 2, 'created': 2, 'duplicates': 0,
                             'original_text': 'SECRETO EXTERNO'}]}
    monkeypatch.setattr(tasks, 'run_tasks', run)
    client = app.test_client()
    with caplog.at_level(logging.INFO):
        assert client.get('/api/cron/collect').status_code == 401
        assert not calls
        assert 'SALTA_TASK' not in caplog.text
        assert client.get('/api/cron/collect', headers={
            'Authorization': 'Bearer cron-ficticio-no-publicar'}).status_code == 200
    assert calls == ['collect']
    record = next(r.message for r in caplog.records if r.message.startswith('SALTA_TASK '))
    data = json.loads(record.removeprefix('SALTA_TASK '))
    assert data['created'] == 2 and data['sources_with_result'] == 1
    assert 'SECRETO' not in record and 'cron-ficticio-no-publicar' not in record


def test_source_check_uses_persistent_counters_without_network_or_external_messages(tmp_path):
    from datetime import datetime, timezone
    from salta_emplea import db
    path = tmp_path / 'fuente.sqlite'
    db.init_db(path)
    conn = db.connect(path)
    assert source_collection_summary(conn) == {'state': 'not_configured'}
    with conn:
        conn.execute("INSERT INTO sources(name,url,method,status,authorized) VALUES "
                     "('PRUEBA','https://jobicy.com/api/v2/remote-jobs','jobicy','active',1)")
    assert source_collection_summary(conn) == {'state': 'waiting', 'active': True}
    now = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
    with conn:
        conn.execute('UPDATE sources SET last_run_at=?,last_result=?', (
            '2026-10-19T18:20:00+00:00', 'SECRETO EXTERNO: no imprimir'))
    assert source_collection_summary(conn, now=now)['state'] == 'requires_review'
    counts = dict(received=100, eligible=2, created=2, duplicates=0, invalid=0)
    with conn:
        conn.execute('UPDATE sources SET last_result=?', (json.dumps({**counts, 'body': 'SECRETO EXTERNO'}),))
    result = source_collection_summary(conn, now=now)
    assert result['state'] == 'recorded' and result['counts'] == counts
    assert 'SECRETO' not in json.dumps(result)
    conn.close()
