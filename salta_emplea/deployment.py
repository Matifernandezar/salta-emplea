"""Diagnóstico de producción sin iniciar la app ni revelar configuración.

La validación local no comprueba que un dominio, una cuenta de correo o una
credencial funcionen. La conexión PostgreSQL es siempre una opción explícita y
usa una transacción de solo lectura; nunca ejecuta migraciones.
"""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from . import mailer


_TABLES = frozenset({
    'schema_migrations', 'jobs', 'provenance', 'sources', 'reports',
    'subscribers', 'outbox', 'deliveries', 'ads', 'settings', 'audit',
    'rate_limits', 'task_runs', 'uploads', 'task_locks',
})


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    message: str

    @property
    def failed(self):
        return self.status == 'ERROR'


def _value(config, name):
    value = config.get(name, '')
    return value if isinstance(value, str) else ''


def _strong_secret(value):
    # Se detectan valores triviales; esto no pretende medir entropía real.
    return (len(value) >= 32 and len(set(value)) >= 12
            and not any(char.isspace() for char in value)
            and not any(word in value.lower() for word in (
                'cambiar', 'change-me', 'changeme', 'replace-me', 'your-secret',
            )))


def _password_hash(value):
    """Valida formatos de Werkzeug sin calcular un hash costoso ni probar claves."""
    parts = value.split('$')
    if len(parts) != 3:
        return False
    method, salt, digest = parts
    if not re.fullmatch(r'[A-Za-z0-9]{1,128}', salt):
        return False
    if not re.fullmatch(r'[0-9a-f]+', digest):
        return False
    scrypt = re.fullmatch(r'scrypt:([0-9]{1,8}):([0-9]{1,4}):([0-9]{1,4})', method)
    if scrypt:
        n, r, p = map(int, scrypt.groups())
        return (n > 1 and n & (n - 1) == 0 and r > 0 and p > 0
                and 132 * n * r * p < 2**31 and len(digest) == 128)
    pbkdf2 = re.fullmatch(r'pbkdf2:(sha256|sha512):([0-9]{1,9})', method)
    return bool(pbkdf2 and int(pbkdf2[2]) > 0
                and len(digest) == {'sha256': 64, 'sha512': 128}[pbkdf2[1]])


def _https_origin(value):
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return False
    if any(char in value for char in ('\\', '?', '#')):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return bool(parsed.scheme == 'https' and parsed.hostname
                    and parsed.username is None and parsed.password is None
                    and parsed.path in ('', '/') and not parsed.query
                    and not parsed.fragment and (port is None or 1 <= port <= 65535))
    except ValueError:
        return False


def _postgres_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return bool(parsed.scheme in ('postgres', 'postgresql')
                    and parsed.hostname and parsed.path not in ('', '/')
                    and not parsed.fragment and not any(char.isspace() for char in value)
                    and (port is None or 1 <= port <= 65535))
    except ValueError:
        return False


def _database_checks(target):
    """Solo SELECT. Los errores del proveedor jamás se incorporan al resultado."""
    connection = None
    try:
        import psycopg

        connection = psycopg.connect(
            target, connect_timeout=5, autocommit=False,
            options='-c default_transaction_read_only=on -c statement_timeout=5000',
            application_name='salta_emplea_check',
        )
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        results = [Check('DATABASE_CONNECTION', 'OK', 'Conexión comprobada en modo de solo lectura.')]
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT table_name FROM information_schema.tables '
                               "WHERE table_schema=current_schema() AND table_type='BASE TABLE'")
                tables = {row[0] for row in cursor.fetchall()}
                if not _TABLES <= tables:
                    return results + [Check('DATABASE_SCHEMA', 'ERROR',
                        'Faltan tablas del esquema; aplicar la migración con el comando init por separado.')]
                cursor.execute('SELECT version FROM schema_migrations ORDER BY version')
                versions = [row[0] for row in cursor.fetchall()]
                if versions != [1]:
                    return results + [Check('DATABASE_SCHEMA', 'ERROR',
                        'La versión del esquema no coincide con esta aplicación; revisar las migraciones.')]
            return results + [Check('DATABASE_SCHEMA', 'OK', 'Tablas y versión del esquema comprobadas.')]
        except Exception:
            return results + [Check('DATABASE_SCHEMA', 'ERROR',
                'No se pudo comprobar el esquema; revisar permisos y migraciones por separado.')]
    except Exception:
        return [Check('DATABASE_CONNECTION', 'ERROR',
            'No se pudo comprobar la conexión; revisar acceso, credenciales y disponibilidad.')]
    finally:
        if connection is not None:
            # Cerrar descarta la transacción de lectura; no hay commit ni DDL.
            try:
                connection.close()
            except Exception:
                pass


def check_production(config, *, with_crons=False, check_database=False):
    """Devuelve resultados sin valores para el backend PostgreSQL de Vercel.

    ``config`` puede estar incompleta. No se abre ninguna conexión salvo que se
    pida ``check_database`` y DATABASE_URL tenga formato válido.
    """
    checks = []
    validators = (
        ('SECRET_KEY', _strong_secret,
         'Usar una clave generada con secret-key, de al menos 32 caracteres sin patrones triviales.'),
        ('ADMIN_PASSWORD_HASH', _password_hash,
         'Usar un hash scrypt o PBKDF2 SHA-256/SHA-512 generado con password-hash.'),
        ('PUBLIC_BASE_URL', _https_origin,
         'Requiere un origen HTTPS sin credenciales, ruta, consulta ni fragmento.'),
        ('DATABASE_URL', _postgres_url,
         'Vercel requiere una URL PostgreSQL con servidor y nombre de base.'),
    )
    for name, validator, error in validators:
        valid = validator(_value(config, name))
        checks.append(Check(name, 'OK' if valid else 'ERROR',
                            'Formato local válido; servicio externo sin comprobar.' if valid else error))
    if with_crons:
        valid = _strong_secret(_value(config, 'CRON_SECRET'))
        checks.append(Check('CRON_SECRET', 'OK' if valid else 'ERROR',
            'Formato local válido; tareas sin ejecutar.' if valid else
            'Requiere una clave generada de al menos 32 caracteres para habilitar crons.'))
    else:
        checks.append(Check('CRON_SECRET', 'PENDIENTE', 'Crons no evaluados; usar --with-crons antes de habilitarlos.'))
    mail_configured = all(_value(config, name).strip() for name in ('RESEND_API_KEY', 'MAIL_FROM'))
    for name in ('RESEND_API_KEY', 'MAIL_FROM'):
        checks.append(Check(name, 'CONFIGURADO' if mail_configured else 'PENDIENTE',
            'Par de correo presente; proveedor sin comprobar. No se envió ningún mensaje.' if mail_configured else
            'Correo opcional pendiente: requiere RESEND_API_KEY y MAIL_FROM juntos.'))
    # Este comando evalúa la preparación para producción, no inicia la app ni
    # cambia su entorno. La presencia de variables no acredita el servicio.
    mail_state = mailer.delivery_readiness(dict(config, APP_ENV='production'))
    missing = {item['key']: item['message'] for item in mail_state['missing']}
    enabled = config.get('MAIL_ENABLED') == '1'
    checks.append(Check('MAIL_ENABLED', 'HABILITADO' if enabled else 'PAUSADO',
        'Habilitación local explícita; no demuestra una entrega.' if enabled else
        'Envíos pausados; cargar credenciales no habilita el correo por sí solo.'))
    checks.append(Check('RESEND_WEBHOOK_SECRET', 'PENDIENTE' if 'webhook' in missing else 'CONFIGURADO',
        missing.get('webhook', 'Formato local de firma válido; conexión y eventos reales sin comprobar.')))
    state = 'PREPARADO' if mail_state['ready'] else 'PENDIENTE' if enabled else 'PAUSADO'
    checks.append(Check('MAIL_DELIVERY', state,
        'Preparación local completa. DNS, proveedor y recepción sin comprobar; no se envió ningún mensaje.'
        if mail_state['ready'] else
        ' '.join(item['message'] for item in mail_state['missing']) +
        ' DNS, proveedor y recepción sin comprobar; no se envió ningún mensaje.'))
    if check_database:
        if _postgres_url(_value(config, 'DATABASE_URL')):
            checks.extend(_database_checks(_value(config, 'DATABASE_URL')))
        else:
            checks.append(Check('DATABASE_CONNECTION', 'PENDIENTE',
                                'No se abrió conexión porque DATABASE_URL no tiene formato válido.'))
    else:
        checks.append(Check('DATABASE_CONNECTION', 'SIN COMPROBAR',
                            'Sin conexión de red; usar --check-database para comprobar acceso y esquema.'))
    return checks
