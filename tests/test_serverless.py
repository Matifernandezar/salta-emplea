"""Contratos de Vercel sin usar servicios, secretos ni datos reales."""
from pathlib import Path

import pytest

from salta_emplea import create_app, db


def configuration(tmp_path, **overrides):
    return {
        'TESTING': True, 'SECRET_KEY': 'clave-ficticia-de-pruebas-serverless-sin-uso-real',
        'ADMIN_PASSWORD_HASH': 'hash-ficticio-solo-valida-configuracion',
        'APP_ENV': 'development', 'SERVERLESS': False, 'DATABASE_URL': '',
        'DATABASE_PATH': str(tmp_path / 'test.sqlite3'), 'UPLOAD_DIR': str(tmp_path / 'uploads'),
        'PUBLIC_BASE_URL': 'https://example.test', 'CRON_SECRET': 'secreto-ficticio-de-cron',
        **overrides,
    }


def test_vercel_refuses_ephemeral_sqlite(tmp_path):
    with pytest.raises(RuntimeError, match='PostgreSQL persistente'):
        create_app(configuration(tmp_path, SERVERLESS=True))
    assert not (tmp_path / 'test.sqlite3').exists()


def test_postgres_startup_never_migrates_or_creates_local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'init_db', lambda *_: pytest.fail('El arranque no migra PostgreSQL.'))
    monkeypatch.setattr(db, 'connect', lambda *_: pytest.fail('El arranque no abre conexión.'))
    app = create_app(configuration(tmp_path, SERVERLESS=True, DATABASE_URL='postgresql://prueba@localhost/prueba'))
    assert app.config['SESSION_COOKIE_SECURE']
    assert not (tmp_path / 'uploads').exists()
    assert not (tmp_path / 'test.sqlite3').exists()


@pytest.mark.parametrize('header', [None, '', 'Bearer incorrecto', 'Bearer sécreto-no-válido'])
def test_cron_rejects_unauthorized_requests(tmp_path, header, monkeypatch):
    from salta_emplea import tasks
    app = create_app(configuration(tmp_path))
    monkeypatch.setattr(tasks, 'run_tasks', lambda *_args, **_kwargs: pytest.fail('No debe ejecutar tareas.'))
    response = app.test_client().get('/api/cron/mail', headers={'Authorization': header} if header else {})
    assert response.status_code == 401


def test_cron_authenticates_and_exposes_only_known_tasks(tmp_path, monkeypatch):
    from salta_emplea import tasks
    app = create_app(configuration(tmp_path))
    calls = []
    monkeypatch.setattr(tasks, 'run_tasks', lambda conn, config, only: calls.append(only) or {'sources': []})
    client = app.test_client()
    assert client.get('/api/cron/collect', headers={'Authorization': 'Bearer secreto-ficticio-de-cron'}).status_code == 200
    assert calls == ['collect']
    assert client.get('/api/cron/approve', headers={'Authorization': 'Bearer secreto-ficticio-de-cron'}).status_code == 404
    assert client.post('/api/cron/mail').status_code in (400, 405)
