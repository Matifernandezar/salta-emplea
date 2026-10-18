"""Operación: python -m salta_emplea.cli --help."""
import argparse
import getpass
import json
import os
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

from . import create_app, db
from .tasks import run_tasks


def main():
    parser = argparse.ArgumentParser(description='Administración de Salta Emplea')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Crear o migrar base, sin datos de prueba')
    commands.add_parser('password-hash', help='Generar hash; contraseña por entrada oculta')
    commands.add_parser('secret-key', help='Generar clave de sesión; guardar solo en entorno privado')
    production = commands.add_parser('check-production', help='Diagnóstico de Vercel sin mostrar secretos ni iniciar la app')
    production.add_argument('--with-crons', action='store_true', help='Exigir CRON_SECRET antes de habilitar tareas')
    production.add_argument('--check-database', action='store_true', help='Comprobar conexión y esquema PostgreSQL solo con SELECT')
    tasks = commands.add_parser('tasks', help='Ejecutar tareas una vez, con bloqueo exclusivo')
    tasks.add_argument('--only', choices=['collect', 'expire', 'mail', 'extract'])
    backup = commands.add_parser('backup', help='Respaldo consistente de SQLite; PostgreSQL usa pg_dump')
    backup.add_argument('destination')
    forget = commands.add_parser('forget-email', help='Eliminar correo y registros asociados a pedido del titular')
    forget.add_argument('email')
    reconcile = commands.add_parser('reconcile-mail', help='Resolver envío incierto tras verificar proveedor; nunca reenvía')
    reconcile.add_argument('id', type=int)
    reconcile.add_argument('--result', choices=['sent', 'cancelled'], required=True)
    args = parser.parse_args()
    if args.command == 'password-hash':
        password = getpass.getpass('Contraseña nueva (mínimo 12 caracteres): ')
        if len(password) < 12 or password != getpass.getpass('Repetir contraseña: '):
            parser.error('Contraseña corta o confirmación distinta.')
        print(generate_password_hash(password))
        return
    if args.command == 'secret-key':
        import secrets
        print(secrets.token_hex(32))
        return
    if args.command == 'check-production':
        from .config import load_env
        from .deployment import check_production

        try:
            load_env()
        except (OSError, ValueError):
            print('ENV_FILE: ERROR — No se pudo leer la configuración local; revisar el archivo .env.')
            return 1
        checks = check_production(os.environ, with_crons=args.with_crons,
                                  check_database=args.check_database)
        print('Diagnóstico de configuración. No inicia la app ni envía correos.')
        for check in checks:
            print(f'{check.name}: {check.status} — {check.message}')
        return int(any(check.failed for check in checks))
    app = create_app()
    database_target = app.config.get('DATABASE_TARGET') or app.config.get('DATABASE_URL') or app.config['DATABASE_PATH']
    if args.command == 'init':
        # Las migraciones PostgreSQL se ejecutan explícitamente, nunca al abrir
        # una petición web ni como efecto secundario de una tarea programada.
        db.init_db(database_target)
    if args.command == 'backup' and db.is_postgres(database_target):
        parser.error('Para PostgreSQL usá pg_dump o el respaldo del proveedor. El comando backup solo admite SQLite.')
    conn = db.connect(database_target)
    try:
        if args.command == 'init':
            print('Base preparada. No se cargaron ofertas ni suscriptores.')
        elif args.command == 'backup':
            path = Path(args.destination).resolve()
            if path == Path(app.config['DATABASE_PATH']).resolve() or path.exists():
                parser.error('Usá un destino nuevo y distinto a la base activa.')
            path.parent.mkdir(parents=True, exist_ok=True)
            old_mask = os.umask(0o077)
            try:
                target = sqlite3.connect(path)
                with target:
                    conn.backup(target)
                target.close()
            finally:
                os.umask(old_mask)
            print('Respaldo consistente creado. Incluir uploads y entorno por separado.')
        elif args.command == 'forget-email':
            with conn:
                subscriber = conn.execute('SELECT id FROM subscribers WHERE email=?', (args.email.lower(),)).fetchone()
                if subscriber:
                    for table in ('deliveries', 'outbox'):
                        conn.execute(f'DELETE FROM {table} WHERE subscriber_id=?', (subscriber['id'],))
                    conn.execute('DELETE FROM subscribers WHERE id=?', (subscriber['id'],))
                conn.execute('UPDATE reports SET contact=NULL WHERE contact=?', (args.email.lower(),))
            print('Datos de correo eliminados si existían; coordinar retención de respaldos.')
        elif args.command == 'reconcile-mail':
            with conn:
                conn.execute("UPDATE outbox SET status=?,last_error='Conciliado manualmente con el proveedor.' WHERE id=? AND status='uncertain'", (args.result, args.id))
            print('Conciliación registrada. No se enviaron mensajes.')
        elif args.command == 'tasks':
            # run_tasks comparte el mismo bloqueo con los cron HTTP y funciona
            # tanto con SQLite local como con PostgreSQL administrado.
            print(json.dumps(run_tasks(conn, app.config, args.only), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
