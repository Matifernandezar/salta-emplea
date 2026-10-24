"""Lectura opcional de imágenes con reservas persistentes; nunca aprueba avisos.

Las reservas, permisos y resultados viven en auditoría, con la huella de la
imagen. Una reserva inconclusa bloquea reenvíos: no se repite un cobro incierto.
El bloqueo compartido de tasks serializa todos los puntos de entrada.
"""
import hashlib
import json
import re
import time
from pathlib import Path

from . import db, domain, extraction, claude_extraction


ACTIONS = ('ocr_reserved', 'ocr_completed', 'ocr_failed')
_PENDING_SQL = """FROM jobs j WHERE j.status='pending' AND j.image_path IS NOT NULL
    AND EXISTS (SELECT 1 FROM audit a WHERE a.entity_id=j.id AND a.action='ocr_authorized'
        AND a.detail LIKE '%"image_path": "' || j.image_path || '"%')
    AND (NOT EXISTS (SELECT 1 FROM audit a WHERE a.entity_id=j.id
        AND a.action IN ('ocr_reserved','ocr_completed','ocr_failed')
        AND a.detail LIKE '%"image_path": "' || j.image_path || '"%') OR EXISTS (
        SELECT 1 FROM audit r WHERE r.entity_id=j.id AND r.action='ocr_retry_authorized'
        AND r.detail LIKE '%"image_path": "' || j.image_path || '"%'
        AND r.id > COALESCE((SELECT MAX(a.id) FROM audit a WHERE a.entity_id=j.id
            AND a.action IN ('ocr_reserved','ocr_completed','ocr_failed')
            AND a.detail LIKE '%"image_path": "' || j.image_path || '"%'),0)))"""


def monthly_limit(config):
    try:
        return max(0, min(1000, int(config.get('OCR_MONTHLY_LIMIT', 100))))
    except (TypeError, ValueError):
        return 0


def provider(config):
    return config.get('OCR_PROVIDER') or ('anthropic' if config.get('ANTHROPIC_API_KEY') else 'google_vision')


def key_present(config):
    return bool(config.get('ANTHROPIC_API_KEY') if provider(config) == 'anthropic'
                else config.get('GOOGLE_VISION_API_KEY'))


def enabled(config):
    # La clave de Claude habilita el circuito manual salvo desactivación explícita.
    value = config.get('OCR_ENABLED')
    return value in (True, 1, '1') or (value is None and provider(config) == 'anthropic')


def provider_label(config):
    return 'Claude (Anthropic)' if provider(config) == 'anthropic' else 'Google Cloud Vision'


def configured(config):
    return (enabled(config)
            and key_present(config) and provider(config) in ('anthropic', 'google_vision')
            and config.get('APP_ENV') == 'production' and monthly_limit(config) > 0)


def _event(conn, job_id, action, detail, actor='lector_imagenes'):
    conn.execute('INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES (?,?,?,?,?)',
                 (actor, action, job_id, json.dumps(detail, ensure_ascii=False), domain.now()))


def image_bytes(conn, config, image_path):
    if not isinstance(image_path, str) or not re.fullmatch(r'(?:[0-9a-f]{48}|[0-9a-f]{64})\.jpg', image_path):
        raise ValueError('Referencia de imagen no válida.')
    if db.is_postgres(config.get('DATABASE_TARGET') or config.get('DATABASE_URL')):
        row = conn.execute('SELECT data FROM uploads WHERE name=?', (image_path,)).fetchone()
        if row is None:
            raise ValueError('La imagen no está disponible.')
        content = bytes(row['data'])
    else:
        with (Path(config['UPLOAD_DIR']) / image_path).open('rb') as stream:
            content = stream.read(4 * 1024 * 1024 + 1)
    if not content or len(content) > 4 * 1024 * 1024:
        raise ValueError('La imagen no tiene un tamaño compatible.')
    return content


def _details(conn, job_id, actions, image_path=None):
    placeholders = ','.join('?' for _ in actions)
    condition = ' AND detail LIKE ?' if image_path is not None else ''
    parameters = (job_id, *actions, *([_path_pattern(image_path)] if image_path is not None else []))
    for row in conn.execute(f'SELECT id,action,detail FROM audit WHERE entity_id=? AND action IN ({placeholders})' + condition + ' ORDER BY id DESC LIMIT 100', parameters):
        try:
            detail = json.loads(row['detail'])
            if isinstance(detail, dict):
                yield row['action'], dict(detail, event_id=row['id'])
        except (ValueError, TypeError):
            continue


def authorize(conn, job_id, config, actor):
    row = conn.execute('SELECT image_path,status FROM jobs WHERE id=?', (job_id,)).fetchone()
    if row is None or not row['image_path'] or row['status'] != 'pending':
        raise ValueError('La lectura requiere un aviso pendiente con imagen.')
    digest = hashlib.sha256(image_bytes(conn, config, row['image_path'])).hexdigest()
    # Un permiso previo no autoriza un archivo distinto.
    if not any(data.get('image_hash') == digest and data.get('provider', 'google_vision') == provider(config) for _, data in _details(conn, job_id, ('ocr_authorized',), row['image_path'])):
        with conn:
            _event(conn, job_id, 'ocr_authorized', {'image_hash': digest, 'image_path': row['image_path'],
                    'provider': provider(config)}, actor)
    return digest


def result_for(conn, job_id, image_path):
    if not image_path:
        return None
    for action, detail in _details(conn, job_id, ACTIONS, image_path):
        if detail.get('image_path') == image_path:
            return dict(detail, status={'ocr_reserved': 'reserved', 'ocr_completed': 'completed', 'ocr_failed': 'failed'}[action])
    return None


def _path_pattern(image_path):
    if not isinstance(image_path, str) or not re.fullmatch(r'(?:[0-9a-f]{48}|[0-9a-f]{64})\.jpg', image_path):
        # Ninguna referencia externa puede introducir comodines en el filtro.
        return '%"image_path": "referencia-no-compatible"%'
    return '%"image_path": "' + image_path + '"%'


def attempts(conn, job_id, image_path):
    return conn.execute("SELECT count(*) FROM audit WHERE entity_id=? AND action='ocr_reserved' AND detail LIKE ?",
                        (job_id, _path_pattern(image_path))).fetchone()[0]


def retry_available(conn, job_id, image_path):
    result = result_for(conn, job_id, image_path)
    return bool(result and result['status'] == 'failed'
                and result.get('error_code') in extraction.REJECTED_CODES
                and attempts(conn, job_id, image_path) < 3)


def _retry_ticket(conn, job_id, image_path, digest, result):
    if not result or not retry_available(conn, job_id, image_path) or result.get('image_hash') != digest:
        return None
    for _, ticket in _details(conn, job_id, ('ocr_retry_authorized',), image_path):
        if (ticket.get('failed_event_id') == result['event_id'] and ticket.get('image_hash') == digest
                and ticket['event_id'] > result['event_id']):
            return ticket
    return None


def authorize_retry(conn, job_id, config, failed_event_id, actor):
    """Autoriza un rechazo concreto; nunca borra reservas ni reenvía una lectura incierta."""
    with conn:
        db.editorial_lock(conn)
        job = conn.execute('SELECT image_path,status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not job or job['status'] != 'pending' or not retry_available(conn, job_id, job['image_path']):
            raise ValueError('Solo se puede reintentar un rechazo de acceso de un aviso pendiente, hasta tres intentos por imagen.')
        result = result_for(conn, job_id, job['image_path'])
        if failed_event_id != result['event_id']:
            raise ValueError('El resultado cambió. Recargá el aviso antes de solicitar otro intento.')
        digest = hashlib.sha256(image_bytes(conn, config, job['image_path'])).hexdigest()
        if digest != result.get('image_hash'):
            raise ValueError('La imagen cambió; esta autorización no corresponde al archivo actual.')
        if not _retry_ticket(conn, job_id, job['image_path'], digest, result):
            _event(conn, job_id, 'ocr_authorized', {'image_path': job['image_path'], 'image_hash': digest,
                    'provider': provider(config)}, actor)
            _event(conn, job_id, 'ocr_retry_authorized', {'image_path': job['image_path'], 'image_hash': digest,
                    'failed_event_id': result['event_id'], 'provider': provider(config)}, actor)


def usage(conn):
    start = domain.now()[:7] + '-01T00:00:00+00:00'
    return conn.execute("SELECT count(*) FROM audit WHERE action='ocr_reserved' AND created_at>=?", (start,)).fetchone()[0]


def _provider_pending(config):
    # Filtrar antes del LIMIT evita que permisos viejos de otro proveedor
    # oculten los avisos nuevos y mantiene correcto el contador del panel.
    if provider(config) != 'anthropic':
        return ''
    return """ AND EXISTS (SELECT 1 FROM audit consent WHERE consent.entity_id=j.id
        AND consent.action='ocr_authorized'
        AND consent.detail LIKE '%"provider": "anthropic"%'
        AND consent.detail LIKE '%"image_path": "' || j.image_path || '"%')"""


def status(conn, config):
    used = usage(conn)
    return {'ready': configured(config) and used < monthly_limit(config), 'enabled': enabled(config), 'provider_label': provider_label(config),
            'key_present': key_present(config), 'monthly_limit': monthly_limit(config),
            'used': used, 'pending': conn.execute('SELECT count(*) ' + _PENDING_SQL + _provider_pending(config)).fetchone()[0]}


def _snapshot(job):
    return {key: job[key] for key in (*domain.FIELDS, 'updated_at', 'status')}


def process(conn, config, *, deadline=None):
    """Debe llamarse dentro del lease de tasks. Hasta una imagen por corrida."""
    result = {'processed': 0, 'prepared': 0, 'errors': 0, 'skipped': 0}
    if not configured(config):
        return dict(result, unavailable=True)
    if usage(conn) >= monthly_limit(config):
        return dict(result, quota_reached=True)
    parameters = []
    clause = ''
    if config.get('OCR_JOB_ID') is not None:
        clause = ' AND j.id=?'
        parameters.append(int(config['OCR_JOB_ID']))
    # Solo candidatos con permiso para este archivo y sin intento previo. La
    # referencia siempre es un nombre hexadecimal generado por save_image.
    candidates = conn.execute('SELECT j.* ' + _PENDING_SQL + _provider_pending(config) + clause + ' ORDER BY j.id LIMIT 200', parameters).fetchall()
    for row in candidates:
        if deadline is not None and time.monotonic() + 22 >= deadline:
            return dict(result, budget_exhausted=True)
        job = dict(row)
        existing = result_for(conn, job['id'], job['image_path'])
        try:
            content = image_bytes(conn, config, job['image_path'])
        except (ValueError, OSError):
            result['skipped'] += 1
            continue
        digest = hashlib.sha256(content).hexdigest()
        if not any(detail.get('image_hash') == digest and detail.get('provider', 'google_vision') == provider(config) for _, detail in _details(conn, job['id'], ('ocr_authorized',), job['image_path'])):
            result['skipped'] += 1
            continue
        ticket = _retry_ticket(conn, job['id'], job['image_path'], digest, existing) if existing else None
        if existing and not ticket:
            result['skipped'] += 1
            continue
        reservation = {'image_hash': digest, 'image_path': job['image_path'], 'provider': provider(config)}
        if ticket:
            reservation.update(retry_event_id=ticket['event_id'], failed_event_id=existing['event_id'])
        # Confirmar reserva ANTES de consultar; sobrevivirá a cortes o reinicios.
        with conn:
            db.editorial_lock(conn)
            current = conn.execute('SELECT status,image_path FROM jobs WHERE id=?', (job['id'],)).fetchone()
            if not current or current['status'] != 'pending' or current['image_path'] != job['image_path']:
                result['skipped'] += 1
                continue
            _event(conn, job['id'], 'ocr_reserved', reservation)
        result['processed'] += 1
        try:
            if provider(config) == 'anthropic':
                received = claude_extraction.extract_image(content, config['ANTHROPIC_API_KEY'],
                    config.get('ANTHROPIC_MODEL') or claude_extraction.DEFAULT_MODEL)
            else:
                received = extraction.extract_image(content, config['GOOGLE_VISION_API_KEY'])
            prepared = received.get('prepared') or extraction.prepare_text(received['text'])
            detail = dict(reservation, text=received['text'], fields=prepared['fields'], evidence=prepared['evidence'],
                          uncertain_fields=prepared['uncertain_fields'], warnings=received.get('warnings', []), applied=False)
            with conn:
                db.editorial_lock(conn)
                current = conn.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone()
                if current and _snapshot(dict(current)) == _snapshot(job) and current['status'] == 'pending':
                    changes = {key: value for key, value in prepared['fields'].items()
                               if key in domain.FIELDS and value and (not current[key] or
                                  (key == 'title' and current[key] == 'Aviso pendiente de transcripción'))}
                    # La copia recibida, el sueldo y las fechas nunca se sustituyen.
                    for key in ('source_name', 'source_url', 'image_path', 'original_text', 'original_date',
                                'expires_at', 'last_checked_at', 'salary_amount', 'salary_currency', 'salary_period', 'salary_source_evidence'):
                        changes.pop(key, None)
                    if changes:
                        warnings = domain._list(current['uncertain_fields']) + prepared['uncertain_fields']
                        changes['uncertain_fields'] = list(dict.fromkeys(warnings + ['Lectura automática: contrastar cada dato con la imagen']))
                        domain.edit_job(conn, job['id'], changes, actor='lector_imagenes')
                        detail['applied'] = True
                        result['prepared'] += 1
                _event(conn, job['id'], 'ocr_completed', detail)
        except Exception as exc:
            # Nunca registrar mensajes/cuerpos del proveedor: pueden revelar claves.
            code = exc.code if isinstance(exc, extraction.ExtractionError) else 'processing_failed'
            with conn:
                _event(conn, job['id'], 'ocr_failed', dict(reservation, error_code=code))
            result['errors'] += 1
        # Sin reintentos automáticos: ante error o cobro incierto se requiere revisión.
        return result
    return result
