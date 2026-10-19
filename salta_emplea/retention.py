"""Vista previa y limpieza manual, acotada y conservadora de datos auxiliares.

No hay programación ni borrado de ofertas, historial, correos intentados o
archivos. La autorización de aplicación es un booleano del llamador, nunca un
texto recibido de un formulario ni una variable que active borrados por sí sola.
"""

import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db


DEFAULT_UNCONFIRMED_DAYS = 30
DEFAULT_BATCH_LIMIT = 100
DEFAULT_SCAN_LIMIT = 1000
MAX_CONFIRMATIONS_PER_SUBSCRIBER = 20
_IMAGE_NAME = re.compile(r'(?:[0-9a-f]{48}|[0-9a-f]{64})\.jpg')


def _now():
    return datetime.now(timezone.utc)


def _integer(config, name, default, minimum, maximum):
    value = config.get(name, default)
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,8}', str(value)):
        raise ValueError('Configuración de retención no válida: ' + name)
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError('Configuración de retención fuera de rango: ' + name)
    return value


def _policy(config):
    return {
        'unconfirmed_days': _integer(config, 'RETENTION_UNCONFIRMED_DAYS', DEFAULT_UNCONFIRMED_DAYS, 30, 3650),
        'batch_limit': _integer(config, 'RETENTION_BATCH_LIMIT', DEFAULT_BATCH_LIMIT, 1, 1000),
        'scan_limit': _integer(config, 'RETENTION_SCAN_LIMIT', DEFAULT_SCAN_LIMIT, 1, 10000),
    }


def _old_timestamp(value, cutoff):
    try:
        timestamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return timestamp.tzinfo is not None and timestamp < cutoff
    except (ValueError, TypeError):
        return False


def _safe_confirmations(conn, subscriber, cutoff):
    """None protege al suscriptor; una lista vacía puede eliminarse sin cascada."""
    if (subscriber['status'] != 'pending' or subscriber['confirmed_at'] is not None or
            subscriber['last_sent_at'] is not None or not _old_timestamp(subscriber['created_at'], cutoff)):
        return None
    subscriber_id = subscriber['id']
    if conn.execute('SELECT 1 FROM deliveries WHERE subscriber_id=? LIMIT 1', (subscriber_id,)).fetchone():
        return None
    rows = conn.execute(
        'SELECT id,kind,status,attempts,first_attempt_at,sent_at,created_at FROM outbox '
        'WHERE subscriber_id=? ORDER BY id LIMIT ?',
        (subscriber_id, MAX_CONFIRMATIONS_PER_SUBSCRIBER + 1),
    ).fetchall()
    if len(rows) > MAX_CONFIRMATIONS_PER_SUBSCRIBER:
        return None
    for row in rows:
        if (row['kind'] != 'confirmation' or row['status'] not in ('pending', 'cancelled') or
                row['attempts'] != 0 or row['first_attempt_at'] is not None or row['sent_at'] is not None or
                not _old_timestamp(row['created_at'], cutoff)):
            return None
        # El ledger prevalece sobre campos que alguien pudiera haber reiniciado.
        if conn.execute("SELECT 1 FROM audit WHERE action='mail_reserved' AND entity_id=? LIMIT 1", (row['id'],)).fetchone():
            return None
        if conn.execute('SELECT 1 FROM deliveries WHERE outbox_id=? LIMIT 1', (row['id'],)).fetchone():
            return None
    return [row['id'] for row in rows]


def _image_reference(conn, name):
    if conn.execute('SELECT 1 FROM jobs WHERE image_path=? UNION ALL '
                    'SELECT 1 FROM provenance WHERE image_path=? LIMIT 1', (name, name)).fetchone():
        return 'editorial_references'
    # No se interpreta ni ejecuta el contenido externo. Una coincidencia amplia
    # conserva material antes que perder una reserva o una evidencia de OCR.
    if conn.execute("SELECT 1 FROM audit WHERE action LIKE 'ocr_%' AND detail LIKE ? LIMIT 1",
                    ('%' + name + '%',)).fetchone():
        return 'ocr_ledger_references'
    return 'unreferenced_needs_review'


def _images(conn, config, scan_limit):
    result = dict(scanned=0, editorial_references=0, ocr_ledger_references=0,
                  unreferenced_needs_review=0, symlinks_skipped=0,
                  unrecognized_entries=0, truncated=False, unavailable=False,
                  deletion_enabled=False)
    if db.is_postgres(conn):
        names = conn.execute('SELECT name FROM uploads ORDER BY name LIMIT ?', (scan_limit + 1,)).fetchall()
        result['truncated'] = len(names) > scan_limit
        for row in names[:scan_limit]:
            result['scanned'] += 1
            if _IMAGE_NAME.fullmatch(row['name'] or ''):
                result[_image_reference(conn, row['name'])] += 1
            else:
                result['unrecognized_entries'] += 1
        return result
    directory = str(config.get('UPLOAD_DIR') or '')
    if not directory:
        return result
    path = Path(directory).absolute()
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            result['symlinks_skipped'] += 1
            return result
        if not path.exists():
            return result
        # No se abren archivos, no se siguen enlaces y no se recorre subcarpetas.
        import os
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries):
                if index >= scan_limit:
                    result['truncated'] = True
                    break
                result['scanned'] += 1
                if entry.is_symlink():
                    result['symlinks_skipped'] += 1
                elif not entry.is_file(follow_symlinks=False) or not _IMAGE_NAME.fullmatch(entry.name):
                    result['unrecognized_entries'] += 1
                else:
                    result[_image_reference(conn, entry.name)] += 1
    except OSError:
        result['unavailable'] = True
    return result


def _plan(conn, config, *, include_images=True):
    policy = _policy(config)
    instant = _now()
    cutoff = instant - timedelta(days=policy['unconfirmed_days'])
    scan_limit = policy['scan_limit']
    budget = policy['batch_limit']
    result = {'mode': 'preview', 'generated_at': instant.isoformat(timespec='seconds'),
              'cutoff': cutoff.isoformat(timespec='seconds'), 'policy': policy,
              'rate_limits': dict(scanned=0, eligible=0, selected=0, invalid=0, truncated=False),
              'subscribers': dict(scanned=0, eligible=0, selected=0, protected=0,
                                  confirmations_selected=0, truncated=False)}
    # PostgreSQL guarda BIGINT y SQLite TEXT: ordenar explícitamente la misma
    # representación sin depender de coerciones particulares del motor.
    rates = conn.execute('SELECT key,reset_at FROM rate_limits ORDER BY LENGTH(CAST(reset_at AS TEXT)),CAST(reset_at AS TEXT),key LIMIT ?',
                         (scan_limit + 1,)).fetchall()
    result['rate_limits']['truncated'] = len(rates) > scan_limit
    rate_keys = []
    for row in rates[:scan_limit]:
        result['rate_limits']['scanned'] += 1
        value = str(row['reset_at'])
        if not re.fullmatch(r'[0-9]{1,12}', value):
            result['rate_limits']['invalid'] += 1
        elif int(value) < int(instant.timestamp()):
            result['rate_limits']['eligible'] += 1
            if budget:
                rate_keys.append(row['key'])
                budget -= 1
    result['rate_limits']['selected'] = len(rate_keys)
    subscribers = conn.execute(
        "SELECT id,status,confirmed_at,last_sent_at,created_at FROM subscribers WHERE status='pending' "
        'ORDER BY created_at,id LIMIT ?', (scan_limit + 1,),
    ).fetchall()
    result['subscribers']['truncated'] = len(subscribers) > scan_limit
    subscriber_ids = []
    for subscriber in subscribers[:scan_limit]:
        result['subscribers']['scanned'] += 1
        confirmations = _safe_confirmations(conn, subscriber, cutoff)
        if confirmations is None:
            result['subscribers']['protected'] += 1
            continue
        result['subscribers']['eligible'] += 1
        cost = len(confirmations) + 1
        if cost <= budget:
            subscriber_ids.append(subscriber['id'])
            result['subscribers']['selected'] += 1
            result['subscribers']['confirmations_selected'] += len(confirmations)
            budget -= cost
    result['delete_rows_selected'] = policy['batch_limit'] - budget
    if include_images:
        result['images'] = _images(conn, config, scan_limit)
    return result, rate_keys, subscriber_ids, instant, cutoff


def preview(conn, config):
    """Solo SELECT e inventario de nombres: sin escrituras ni datos personales."""
    return _plan(conn, config)[0]


@contextmanager
def _transaction(conn):
    nested = conn.in_transaction
    if nested:
        conn.execute('SAVEPOINT retention_transaction')
    else:
        conn.execute('BEGIN IMMEDIATE')
    try:
        db.mailer_lock(conn)
        db.editorial_lock(conn)
        yield
    except Exception:
        if nested:
            conn.execute('ROLLBACK TO SAVEPOINT retention_transaction')
            conn.execute('RELEASE SAVEPOINT retention_transaction')
        else:
            conn.rollback()
        raise
    else:
        if nested:
            conn.execute('RELEASE SAVEPOINT retention_transaction')
        else:
            conn.commit()


def apply(conn, config):
    """Aplicación explícita; el llamador CLI debe exigir confirmación humana.

    El plan se vuelve a calcular dentro de la transacción. No recibe una lista
    antigua de IDs para evitar aplicar una vista previa que ya cambió.
    """
    if config.get('RETENTION_APPLY_CONFIRMED') is not True:
        raise ValueError('La retención requiere confirmación explícita del comando CLI.')
    with _transaction(conn):
        result, rate_keys, subscriber_ids, instant, cutoff = _plan(conn, config, include_images=False)
        removed = dict(rate_limits=0, subscribers=0, confirmations=0)
        for key in rate_keys:
            row = conn.execute('SELECT reset_at FROM rate_limits WHERE key=?', (key,)).fetchone()
            if row and re.fullmatch(r'[0-9]{1,12}', str(row['reset_at'])) and int(row['reset_at']) < int(instant.timestamp()):
                removed['rate_limits'] += conn.execute('DELETE FROM rate_limits WHERE key=? AND reset_at=?',
                                                      (key, row['reset_at'])).rowcount
        for subscriber_id in subscriber_ids:
            suffix = ' FOR UPDATE' if db.is_postgres(conn) else ''
            subscriber = conn.execute('SELECT id,status,confirmed_at,last_sent_at,created_at '
                                      'FROM subscribers WHERE id=?' + suffix, (subscriber_id,)).fetchone()
            confirmations = _safe_confirmations(conn, subscriber, cutoff) if subscriber else None
            if confirmations is None:
                continue
            # No usar ON DELETE CASCADE: cada eliminación tiene una condición.
            for outbox_id in confirmations:
                removed['confirmations'] += conn.execute('DELETE FROM outbox WHERE id=? AND subscriber_id=?',
                                                         (outbox_id, subscriber_id)).rowcount
            removed['subscribers'] += conn.execute("DELETE FROM subscribers WHERE id=? AND status='pending' "
                                                   'AND confirmed_at IS NULL AND last_sent_at IS NULL',
                                                   (subscriber_id,)).rowcount
        if any(removed.values()):
            conn.execute('INSERT INTO audit(actor,action,detail,created_at) VALUES (?,?,?,?)',
                         ('mantenimiento', 'retention_applied', json.dumps({'removed': removed, 'policy': result['policy']}),
                          instant.isoformat(timespec='seconds')))
        result.update(mode='applied', removed=removed)
        return result
