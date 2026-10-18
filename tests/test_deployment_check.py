"""El diagnóstico incompleto nunca arranca servicios ni expone credenciales."""
import sys

import pytest
from werkzeug.security import generate_password_hash

from salta_emplea import cli
from salta_emplea.deployment import check_production


@pytest.fixture
def configured():
    return {
        'SECRET_KEY': 'f52484e28c935b570c61eb83ad54a1e8ec5d434051ced7498712fbe57123c52d',
        'ADMIN_PASSWORD_HASH': generate_password_hash('contraseña-ficticia-solo-de-pruebas'),
        'PUBLIC_BASE_URL': 'https://example.test',
        'DATABASE_URL': 'postgresql://usuario:clave-privada@example.test/salta',
        'CRON_SECRET': '1cb8562e831f6adf6903248eeb71b46dd423ebd7292031cfda9311f31918fa506',
    }


def by_name(checks):
    return {check.name: check for check in checks}


def test_incomplete_configuration_is_diagnostic_not_exception():
    checks = by_name(check_production({}))
    for name in ('SECRET_KEY', 'ADMIN_PASSWORD_HASH', 'PUBLIC_BASE_URL', 'DATABASE_URL'):
        assert checks[name].failed
    assert checks['CRON_SECRET'].status == 'PENDIENTE'
    assert checks['RESEND_API_KEY'].status == checks['MAIL_FROM'].status == 'PENDIENTE'
    assert checks['DATABASE_CONNECTION'].status == 'SIN COMPROBAR'


def test_valid_local_configuration_never_opens_network(configured, monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', lambda *_args, **_kwargs: pytest.fail('Sin red por defecto.'))
    checks = check_production(configured, with_crons=True)
    assert not any(check.failed for check in checks)
    assert by_name(checks)['DATABASE_CONNECTION'].status == 'SIN COMPROBAR'


@pytest.mark.parametrize('secret', ['', 'x' * 64, 'demasiado-corta',
    'CHANGE-ME-this-is-not-a-secret-value-0123456789', 'un secreto con espacios y 0123456789abcdef'])
def test_trivial_secrets_block_production(configured, secret):
    configured['SECRET_KEY'] = configured['CRON_SECRET'] = secret
    checks = by_name(check_production(configured, with_crons=True))
    assert checks['SECRET_KEY'].failed and checks['CRON_SECRET'].failed


@pytest.mark.parametrize('origin', [
    'http://example.test', 'https://usuario:secreto@example.test',
    'https://example.test/otra-ruta', 'https://example.test?token=secreto',
    'https://example.test#secreto', 'https://example.test?',
    'https://example.test\n', 'https://example.test\\otro',
    'https://example.test:puerto', 'https://example.test:99999', 'https:///sin-servidor',
])
def test_base_url_must_be_https_origin(configured, origin):
    configured['PUBLIC_BASE_URL'] = origin
    assert by_name(check_production(configured))['PUBLIC_BASE_URL'].failed


def test_origin_allows_root_slash_and_https_port(configured):
    configured['PUBLIC_BASE_URL'] = 'https://example.test:8443/'
    assert not by_name(check_production(configured))['PUBLIC_BASE_URL'].failed


@pytest.mark.parametrize('password_hash', [
    'contraseña-en-texto-plano', 'sha256$salt$' + 'a' * 64,
    'scrypt:32768:8:1$salt$incompleto', 'scrypt:3:8:1$salt$' + 'a' * 128,
    'pbkdf2:sha256:0$salt$' + 'a' * 64,
])
def test_plain_password_and_unsupported_hashes_are_rejected(configured, password_hash):
    configured['ADMIN_PASSWORD_HASH'] = password_hash
    assert by_name(check_production(configured))['ADMIN_PASSWORD_HASH'].failed


@pytest.mark.parametrize('method', ['scrypt', 'pbkdf2:sha256:1000000', 'pbkdf2:sha512:1000000'])
def test_hashes_generated_by_supported_werkzeug_methods_pass(configured, method):
    configured['ADMIN_PASSWORD_HASH'] = generate_password_hash('clave-ficticia', method=method)
    assert not by_name(check_production(configured))['ADMIN_PASSWORD_HASH'].failed


@pytest.mark.parametrize('target', ['', '/tmp/salta.sqlite3', 'sqlite:///salta',
    'postgresql://example.test', 'postgresql://example.test/', 'postgresql:///sin-host'])
def test_vercel_rejects_non_persistent_or_incomplete_database_targets(configured, target, monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', lambda *_args, **_kwargs: pytest.fail('URL incompleta no se conecta.'))
    configured['DATABASE_URL'] = target
    checks = by_name(check_production(configured, check_database=True))
    assert checks['DATABASE_URL'].failed
    assert checks['DATABASE_CONNECTION'].status == 'PENDIENTE'


def test_mail_is_optional_and_requires_both_settings(configured):
    configured['RESEND_API_KEY'] = 'credencial-ficticia-de-correo'
    checks = by_name(check_production(configured))
    assert checks['RESEND_API_KEY'].status == checks['MAIL_FROM'].status == 'PENDIENTE'
    assert not any(check.failed for check in checks.values())
    configured['MAIL_FROM'] = 'Salta Emplea <pruebas@example.test>'
    checks = by_name(check_production(configured))
    assert checks['RESEND_API_KEY'].status == checks['MAIL_FROM'].status == 'CONFIGURADO'
    assert 'sin comprobar' in checks['MAIL_FROM'].message


class ReadOnlyConnection:
    def __init__(self, *, missing=False, version=1):
        self.statements = []
        self.closed = False
        self.missing, self.version = missing, version

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        assert statement.startswith('SELECT '), 'El diagnóstico no puede escribir.'
        self.statements.append(statement)

    def fetchone(self):
        return (1,)

    def fetchall(self):
        if 'information_schema' in self.statements[-1]:
            tables = ('schema_migrations', 'jobs', 'provenance', 'sources', 'reports',
                      'subscribers', 'outbox', 'deliveries', 'ads', 'settings', 'audit',
                      'rate_limits', 'task_runs', 'uploads', 'task_locks')
            return [(name,) for name in tables if not (self.missing and name == 'jobs')]
        return [(self.version,)]

    def close(self):
        self.closed = True


def test_database_check_is_explicit_read_only_and_never_migrates(configured, monkeypatch):
    import psycopg
    from salta_emplea import db
    connection = ReadOnlyConnection()
    calls = []
    monkeypatch.setattr(psycopg, 'connect', lambda target, **kwargs: calls.append((target, kwargs)) or connection)
    monkeypatch.setattr(db, 'init_db', lambda *_args: pytest.fail('No se ejecutan migraciones.'))
    checks = by_name(check_production(configured, check_database=True))
    assert checks['DATABASE_CONNECTION'].status == checks['DATABASE_SCHEMA'].status == 'OK'
    assert len(calls) == 1
    assert calls[0][1]['autocommit'] is False
    assert 'default_transaction_read_only=on' in calls[0][1]['options']
    assert 'statement_timeout=' in calls[0][1]['options']
    assert connection.closed


@pytest.mark.parametrize('overrides', [{'missing': True}, {'version': 2}])
def test_existing_incomplete_or_incompatible_database_is_reported(configured, monkeypatch, overrides):
    import psycopg
    connection = ReadOnlyConnection(**overrides)
    monkeypatch.setattr(psycopg, 'connect', lambda *_args, **_kwargs: connection)
    checks = by_name(check_production(configured, check_database=True))
    assert checks['DATABASE_CONNECTION'].status == 'OK'
    assert checks['DATABASE_SCHEMA'].failed
    assert connection.closed


def test_provider_errors_never_expose_url_or_credentials(configured, monkeypatch):
    import psycopg

    def unavailable(*_args, **_kwargs):
        raise RuntimeError('Error sensible: ' + configured['DATABASE_URL'])

    monkeypatch.setattr(psycopg, 'connect', unavailable)
    checks = check_production(configured, check_database=True)
    assert by_name(checks)['DATABASE_CONNECTION'].failed
    rendered = repr(checks)
    for value in configured.values():
        assert value not in rendered
    assert 'clave-privada' not in rendered


def test_cli_validates_before_create_app_and_exits_nonzero_without_leaking(configured, monkeypatch, capsys):
    from salta_emplea import config
    configured['PUBLIC_BASE_URL'] = 'https://usuario:secreto-que-no-debe-aparecer@example.test/ruta'
    monkeypatch.setattr(cli.os, 'environ', configured)
    monkeypatch.setattr(config, 'load_env', lambda: None)
    monkeypatch.setattr(cli, 'create_app', lambda: pytest.fail('El diagnóstico no inicia la app.'))
    monkeypatch.setattr(sys, 'argv', ['salta_emplea.cli', 'check-production', '--with-crons'])
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert 'PUBLIC_BASE_URL: ERROR' in captured.out
    assert 'CRON_SECRET: OK' in captured.out
    assert not captured.err
    assert 'secreto-que-no-debe-aparecer' not in captured.out
    for value in configured.values():
        assert value not in captured.out


def test_cli_success_does_not_claim_provider_verified(configured, monkeypatch, capsys):
    from salta_emplea import config
    monkeypatch.setattr(cli.os, 'environ', configured)
    monkeypatch.setattr(config, 'load_env', lambda: None)
    monkeypatch.setattr(cli, 'create_app', lambda: pytest.fail('El diagnóstico no inicia la app.'))
    monkeypatch.setattr(sys, 'argv', ['salta_emplea.cli', 'check-production'])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert 'DATABASE_CONNECTION: SIN COMPROBAR' in output
    assert 'No inicia la app ni envía correos.' in output


def test_env_file_error_is_redacted_and_exits_nonzero(monkeypatch, capsys):
    from salta_emplea import config

    def unreadable():
        raise ValueError('contenido-sensible-del-archivo')

    monkeypatch.setattr(config, 'load_env', unreadable)
    monkeypatch.setattr(cli, 'create_app', lambda: pytest.fail('El diagnóstico no inicia la app.'))
    monkeypatch.setattr(sys, 'argv', ['salta_emplea.cli', 'check-production'])
    assert cli.main() == 1
    output = capsys.readouterr().out
    assert 'ENV_FILE: ERROR' in output
    assert 'contenido-sensible' not in output
