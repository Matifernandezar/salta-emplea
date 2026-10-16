"""Operación: python -m salta_emplea.cli --help."""
import argparse
import fcntl
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
    tasks = commands.add_parser('tasks', help='Ejecutar tareas una vez, con bloqueo exclusivo')
    tasks.add_argument('--only', choices=['collect', 'expire', 'mail'])
    backup = commands.add_parser('backup', help='Respaldo consistente mediante SQLite backup API')
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
    app = create_app()
    conn = db.connect(app.config['DATABASE_PATH'])
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
            lock_path = app.config['DATABASE_PATH'] + '.tasks.lock'
            with open(lock_path, 'a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    print('Ya hay una tarea en ejecución; se omite esta corrida.')
                    return
                print(json.dumps(run_tasks(conn, app.config, args.only), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
