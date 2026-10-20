"""Cron acotado y recuperable; todos los proveedores son sustitutos locales."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from salta_emplea import cli, db, domain, mailer, tasks


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / 'cron.sqlite3'
    db.init_db(path)
    connection = db.connect(path)
    yield connection
    connection.close()


@pytest.fixture
def config():
    return {
        'APP_ENV': 'production', 'SECRET_KEY': 'solo-pruebas-sin-uso-en-produccion',
        'MAIL_ENABLED': '1', 'RESEND_WEBHOOK_SECRET': 'whsec_cHJ1ZWJhLWZpY3RpY2lhLW5vLXNlY3JldG8=',
        'RESEND_API_KEY': 'proveedor-sustituido', 'MAIL_FROM': 'alertas@pruebas.ar',
        'PUBLIC_BASE_URL': 'https://empleos.pruebas.ar',
        'TASK_BUDGET_SECONDS': 180, 'TASK_MAIL_BATCH': 10, 'TASK_SOURCE_BATCH': 1,
    }


def add_subscriber(conn, index, locality=None):
    with conn:
        return conn.execute(
            "INSERT INTO subscribers(email,locality,frequency,status,token_hash,created_at) "
            "VALUES (?,?,'daily','confirmed','',?)",
            (f'persona-prueba-{index}@pruebas.ar', locality, domain.now()),
        ).lastrowid


def add_job(conn):
    job_id, _ = domain.create_job(conn, {
        'title': 'PRUEBA: oferta del circuito de cron', 'location': 'Salta Capital',
        'application_url': 'mailto:rrhh@pruebas.ar',
    })
    domain.transition_job(conn, job_id, 'approve', 'administrador de prueba', acknowledge=True)
    return job_id


class Accepted:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def getcode(self):
        return 200


def test_blocked_task_never_recovers_another_live_run(conn, config, monkeypatch):
    with conn:
        active_id = conn.execute(
            "INSERT INTO task_runs(task,started_at,status) VALUES ('collect',?,'running')", (domain.now(),),
        ).lastrowid
    calls = []

    @contextmanager
    def occupied(connection, name, ttl_seconds):
        calls.append((connection, name, ttl_seconds))
        yield False

    monkeypatch.setattr(db, 'task_lock', occupied)
    result = tasks.run_tasks(conn, config, only='mail')
    assert 'skipped' in result
    assert calls == [(conn, tasks.TASK_LOCK_NAME, 900)]
    assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 1
    assert conn.execute('SELECT status FROM task_runs WHERE id=?', (active_id,)).fetchone()[0] == 'running'


@pytest.mark.parametrize('only', [None, 'collect', 'expire', 'mail'])
def test_every_entry_point_uses_the_same_exclusive_lock(conn, config, monkeypatch, only):
    calls = []

    @contextmanager
    def available(connection, name, ttl_seconds):
        calls.append(name)
        yield True

    monkeypatch.setattr(db, 'task_lock', available)
    monkeypatch.setattr(mailer, 'urlopen', lambda *_a, **_k: pytest.fail('No debe salir a la red.'))
    tasks.run_tasks(conn, config, only=only)
    assert calls == [tasks.TASK_LOCK_NAME]


def test_real_sqlite_lock_blocks_another_connection_and_releases_it(conn, config):
    path = conn.execute('PRAGMA database_list').fetchone()[2]
    second = db.connect(path)
    try:
        with db.task_lock(conn, tasks.TASK_LOCK_NAME) as acquired:
            assert acquired
            assert 'skipped' in tasks.run_tasks(second, config, only='expire')
            assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 0
        assert tasks.run_tasks(second, config, only='expire')['expiration'] == {'expired': 0, 'review_requested': 0}
        assert conn.execute('SELECT status FROM task_runs').fetchone()[0] == 'succeeded'
    finally:
        second.close()


def test_recovery_marks_an_old_run_only_after_obtaining_lock(conn, config):
    with conn:
        previous = conn.execute(
            "INSERT INTO task_runs(task,started_at,status) VALUES ('collect',?,'running')", (domain.now(),),
        ).lastrowid
    tasks.run_tasks(conn, config, only='expire')
    assert conn.execute('SELECT status FROM task_runs WHERE id=?', (previous,)).fetchone()[0] == 'interrupted'
    assert conn.execute('SELECT status FROM task_runs ORDER BY id DESC LIMIT 1').fetchone()[0] == 'succeeded'


def test_source_batches_progress_without_repeating_completed_sources(conn, config, monkeypatch):
    with conn:
        for index in range(3):
            conn.execute(
                "INSERT INTO sources(name,url,method,status,authorized,frequency_hours) "
                "VALUES (?,?,'jobicy','active',1,24)", (f'FUENTE DE PRUEBA {index}', tasks.JOBICY_API),
            )
    collected = []

    def collect(_conn, source, **_kwargs):
        collected.append(source['id'])
        return {'created': 0}

    monkeypatch.setattr(tasks, 'import_jobicy', collect)
    monkeypatch.setattr(tasks, 'check_jobicy_status', lambda *_a, **_k: {'checked': 0})
    for _ in range(4):
        result = tasks.run_tasks(conn, config, only='collect')
        assert len(result['sources']) <= 1
    assert collected == [1, 2, 3]


def test_budget_defers_source_without_spending_its_frequency_window(conn, config, monkeypatch):
    with conn:
        conn.execute(
            "INSERT INTO sources(name,url,method,status,authorized,frequency_hours) "
            "VALUES ('FUENTE DE PRUEBA',?,'jobicy','active',1,24)", (tasks.JOBICY_API,),
        )
    monkeypatch.setattr(tasks, 'fetch_json', lambda *_: pytest.fail('No alcanza el presupuesto para consultar.'))
    result = tasks.run_tasks(conn, config | {'TASK_BUDGET_SECONDS': 1}, only='collect')
    assert result['budget_exhausted'] is True
    assert conn.execute('SELECT last_run_at FROM sources').fetchone()[0] is None
    assert conn.execute('SELECT status FROM task_runs').fetchone()[0] == 'partial'
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0


def test_small_subscriber_batches_reach_people_after_skips(conn, config):
    add_job(conn)
    add_subscriber(conn, 1, 'Orán')
    add_subscriber(conn, 2, 'Tartagal')
    last = add_subscriber(conn, 3, 'Salta Capital')
    outcomes = [mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'], limit=1) for _ in range(4)]
    assert [outcome['queued'] for outcome in outcomes] == [0, 0, 1, 0]
    assert conn.execute('SELECT subscriber_id FROM outbox').fetchone()[0] == last
    assert conn.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM subscribers WHERE last_sent_at IS NOT NULL').fetchone()[0] == 0


def test_repeated_subscriber_batches_never_duplicate_reservations(conn, config):
    add_job(conn)
    for index in range(12):
        add_subscriber(conn, index)
    assert mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'], limit=10)['queued'] == 10
    assert mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'], limit=10)['queued'] == 2
    assert mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'], limit=10)['queued'] == 0
    assert conn.execute('SELECT count(*) FROM outbox').fetchone()[0] == 12
    assert conn.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 12


def test_queue_deadline_does_not_lose_subscribers(conn, config, monkeypatch):
    add_job(conn)
    add_subscriber(conn, 1)
    monkeypatch.setattr(mailer.time, 'monotonic', lambda: 100)
    result = mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'], deadline=99)
    assert result['budget_exhausted'] is True and result['queued'] == 0
    assert conn.execute("SELECT value FROM settings WHERE key='digest_cursor'").fetchone() is None
    assert mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'])['queued'] == 1


def test_sender_obeys_configured_batch_and_preserves_pending_messages(conn, config, monkeypatch):
    add_job(conn)
    for index in range(3):
        add_subscriber(conn, index)
    mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'])
    calls = []

    def provider(request, timeout):
        calls.append(request)
        assert not conn.in_transaction and timeout == 15
        return Accepted()

    monkeypatch.setattr(mailer, 'urlopen', provider)
    assert mailer.send_outbox(conn, config | {'TASK_MAIL_BATCH': 2})['sent'] == 2
    assert conn.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0] == 1
    assert mailer.send_outbox(conn, config | {'TASK_MAIL_BATCH': 2})['sent'] == 1
    assert mailer.send_outbox(conn, config)['sent'] == 0
    assert len(calls) == 3


def test_sender_checks_remaining_budget_before_each_attempt(conn, config, monkeypatch):
    add_job(conn)
    add_subscriber(conn, 1)
    add_subscriber(conn, 2)
    mailer.queue_digests(conn, config['PUBLIC_BASE_URL'], config['SECRET_KEY'])
    clock = [0]
    monkeypatch.setattr(mailer.time, 'monotonic', lambda: clock[0])

    def provider(request, timeout):
        assert timeout == 15
        clock[0] = 10
        return Accepted()

    monkeypatch.setattr(mailer, 'urlopen', provider)
    result = mailer.send_outbox(conn, config, deadline=20)
    assert result['sent'] == 1 and result['budget_exhausted'] is True
    remaining = conn.execute("SELECT * FROM outbox WHERE status='pending'").fetchone()
    assert remaining['attempts'] == 0 and remaining['first_attempt_at'] is None


def test_cli_refuses_sqlite_backup_for_postgres_without_disclosing_url(monkeypatch, capsys):
    target = 'postgresql://usuario:secreto-no-publicable@db.pruebas.ar/base'
    monkeypatch.setattr(cli, 'create_app', lambda: SimpleNamespace(config={'DATABASE_TARGET': target}))
    monkeypatch.setattr(cli.db, 'connect', lambda *_: pytest.fail('No debe abrir la conexión para un respaldo inválido.'))
    monkeypatch.setattr('sys.argv', ['salta-emplea', 'backup', '/tmp/prueba.sqlite3'])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert 'pg_dump' in message and 'secreto-no-publicable' not in message and target not in message


def test_cli_init_explicitly_migrates_selected_postgres_target(monkeypatch, capsys):
    target = 'postgresql://usuario:secreto-no-publicable@db.pruebas.ar/base'
    calls = []
    monkeypatch.setattr(cli, 'create_app', lambda: SimpleNamespace(config={'DATABASE_TARGET': target}))
    monkeypatch.setattr(cli.db, 'init_db', lambda selected: calls.append(('init', selected)))
    monkeypatch.setattr(cli.db, 'connect', lambda selected: SimpleNamespace(close=lambda: calls.append(('close', selected))))
    monkeypatch.setattr('sys.argv', ['salta-emplea', 'init'])
    cli.main()
    assert calls == [('init', target), ('close', target)]
    assert 'secreto-no-publicable' not in capsys.readouterr().out
