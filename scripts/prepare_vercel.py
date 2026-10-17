"""Preparar estáticos y migraciones explícitas del despliegue, sin importar WSGI."""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from salta_emplea import db


def main():
    destination = ROOT / 'public' / 'static'
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'salta_emplea' / 'static' / 'style.css', destination / 'style.css')
    target = os.environ.get('DATABASE_URL', '')
    if not db.is_postgres(target):
        raise SystemExit('Configurar DATABASE_URL PostgreSQL antes de desplegar. No se usa SQLite efímero.')
    # Cada entorno debe tener su propia base; jamás compartir producción con PRs.
    db.init_db(target)
    print('Estáticos preparados y migraciones PostgreSQL aplicadas; sin datos de prueba.')


if __name__ == '__main__':
    main()
