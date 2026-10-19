"""Preparar estáticos y migraciones explícitas del despliegue, sin importar WSGI."""
import os
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from salta_emplea import db, operations, source_setup


def main():
    destination = ROOT / 'public' / 'static'
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'salta_emplea' / 'static' / 'style.css', destination / 'style.css')
    target = os.environ.get('DATABASE_URL', '')
    if not db.is_postgres(target):
        raise SystemExit('Configurar DATABASE_URL PostgreSQL antes de desplegar. No se usa SQLite efímero.')
    # Cada entorno debe tener su propia base; jamás compartir producción con PRs.
    db.init_db(target)
    # Se aplica solo una vez y con autorización explícita de producción.
    # No consulta la API, no importa ofertas ni reactiva fuentes pausadas.
    conn = db.connect(target)
    try:
        result = source_setup.configure_authorized_source(conn, os.environ)
        print('Registro de fuente autorizada: ' + result['status'])
        if os.environ.get('VERCEL_ENV') == 'production' and os.environ.get('ENABLE_JOBICY_SOURCE') == '1':
            print('SALTA_SOURCE_CHECK ' + json.dumps(operations.source_collection_summary(conn), sort_keys=True))
    finally:
        conn.close()
    print('Estáticos preparados y migraciones PostgreSQL aplicadas; sin datos de prueba.')


if __name__ == '__main__':
    main()
