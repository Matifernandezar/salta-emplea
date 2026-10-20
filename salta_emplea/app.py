"""Aplicación web: todos los permisos se verifican en el servidor."""
import functools
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from . import db, domain, extraction, guides, homepage, image_pipeline, mail_webhooks, operations, public_metadata, source_catalog
from .config import load_env


def create_app(config=None):
    load_env()
    app = Flask(__name__, instance_relative_config=True)
    # Solo se registran mensajes propios y contadores de una lista cerrada.
    app.logger.setLevel(logging.INFO)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        ADMIN_PASSWORD_HASH=os.environ.get('ADMIN_PASSWORD_HASH', ''),
        DATABASE_PATH=os.environ.get('DATABASE_PATH', str(Path(app.instance_path) / 'salta.sqlite3')),
        DATABASE_URL=os.environ.get('DATABASE_URL', ''),
        SERVERLESS=os.environ.get('VERCEL') == '1',
        CRON_SECRET=os.environ.get('CRON_SECRET', ''),
        UPLOAD_DIR=os.environ.get('UPLOAD_DIR', str(Path(app.instance_path) / 'uploads')),
        PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL', ''),
        PUBLIC_RESPONSIBLE_NAME=os.environ.get('PUBLIC_RESPONSIBLE_NAME', ''),
        PUBLIC_CONTACT_EMAIL=os.environ.get('PUBLIC_CONTACT_EMAIL', ''),
        PUBLIC_CONTACT_URL=os.environ.get('PUBLIC_CONTACT_URL', ''),
        APP_ENV=os.environ.get('APP_ENV', 'production' if os.environ.get('VERCEL') == '1' else 'development'),
        MAIL_ENABLED=os.environ.get('MAIL_ENABLED', '0'),
        RESEND_API_KEY=os.environ.get('RESEND_API_KEY', ''),
        MAIL_FROM=os.environ.get('MAIL_FROM', ''),
        RESEND_WEBHOOK_SECRET=os.environ.get('RESEND_WEBHOOK_SECRET', ''),
        MAIL_DAILY_LIMIT=os.environ.get('MAIL_DAILY_LIMIT', '100'),
        MAIL_MONTHLY_LIMIT=os.environ.get('MAIL_MONTHLY_LIMIT', '3000'),
        MAIL_CONFIRMATION_RESERVE_DAILY=os.environ.get('MAIL_CONFIRMATION_RESERVE_DAILY', '10'),
        MAIL_CONFIRMATION_RESERVE_MONTHLY=os.environ.get('MAIL_CONFIRMATION_RESERVE_MONTHLY', '100'),
        RETENTION_UNCONFIRMED_DAYS=os.environ.get('RETENTION_UNCONFIRMED_DAYS', '30'),
        RETENTION_BATCH_LIMIT=os.environ.get('RETENTION_BATCH_LIMIT', '100'),
        RETENTION_SCAN_LIMIT=os.environ.get('RETENTION_SCAN_LIMIT', '1000'),
        OPERATIONS_COLLECT_MAX_AGE_HOURS=os.environ.get('OPERATIONS_COLLECT_MAX_AGE_HOURS', '48'),
        OPERATIONS_EXPIRE_MAX_AGE_HOURS=os.environ.get('OPERATIONS_EXPIRE_MAX_AGE_HOURS', '48'),
        OPERATIONS_MAIL_MAX_AGE_HOURS=os.environ.get('OPERATIONS_MAIL_MAX_AGE_HOURS', '48'),
        OPERATIONS_MAIL_QUEUE_MAX_AGE_HOURS=os.environ.get('OPERATIONS_MAIL_QUEUE_MAX_AGE_HOURS', '48'),
        GOOGLE_VISION_API_KEY=os.environ.get('GOOGLE_VISION_API_KEY', ''),
        OCR_ENABLED=os.environ.get('OCR_ENABLED', '0'),
        OCR_MONTHLY_LIMIT=os.environ.get('OCR_MONTHLY_LIMIT', '100'),
        MAX_CONTENT_LENGTH=4 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=3600,
    )
    if config:
        app.config.update(config)
    app.config['DATABASE_TARGET'] = app.config['DATABASE_URL'] or app.config['DATABASE_PATH']
    if app.config['SERVERLESS']:
        if not db.is_postgres(app.config['DATABASE_TARGET']):
            raise RuntimeError('Vercel requiere DATABASE_URL PostgreSQL persistente; SQLite local no está permitido.')
        app.config['APP_ENV'] = 'production'
        if not app.config['PUBLIC_BASE_URL']:
            origin = os.environ.get('VERCEL_PROJECT_PRODUCTION_URL', '')
            if origin and '/' not in origin and '.' in origin:
                app.config['PUBLIC_BASE_URL'] = 'https://' + origin
    app.config['APP_ENV'] = str(app.config['APP_ENV']).lower()
    production = app.config['APP_ENV'] == 'production'
    if not app.config['SECRET_KEY']:
        if production:
            raise RuntimeError('Falta SECRET_KEY en producción.')
        app.config['SECRET_KEY'] = secrets.token_hex(32)
        app.logger.warning('Desarrollo: clave efímera; las sesiones terminan al reiniciar.')
    if production and (len(app.config['SECRET_KEY']) < 32 or not app.config['ADMIN_PASSWORD_HASH'] or
                       not app.config['PUBLIC_BASE_URL'].startswith('https://')):
        raise RuntimeError('Producción requiere clave fuerte, hash de administrador y PUBLIC_BASE_URL HTTPS.')
    app.config['SESSION_COOKIE_SECURE'] = production
    if os.environ.get('TRUST_PROXY') == '1':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    if not db.is_postgres(app.config['DATABASE_TARGET']):
        Path(app.config['DATABASE_PATH']).parent.mkdir(parents=True, exist_ok=True)
        Path(app.config['UPLOAD_DIR']).mkdir(parents=True, exist_ok=True)
        db.init_db(app.config['DATABASE_PATH'])

    def connection():
        if 'db' not in g:
            g.db = db.connect(app.config['DATABASE_TARGET'])
        return g.db

    app.register_blueprint(mail_webhooks.create_blueprint(connection))

    @app.teardown_appcontext
    def close_db(_error=None):
        conn = g.pop('db', None)
        if conn is not None:
            conn.close()

    def csrf_token():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    app.jinja_env.globals['csrf_token'] = csrf_token
    app.jinja_env.filters['value'] = lambda x: x if x not in (None, '', []) else 'No informado'
    app.jinja_env.filters['date'] = lambda x: '/'.join(str(x)[:10].split('-')[::-1]) if x else 'No informado'
    def deadline_date(value, input_format=False):
        if not value:
            return '' if input_format else 'No informado'
        try:
            stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return '' if input_format else 'No informado'
        if len(str(value)) == 10:
            return stamp.strftime('%Y-%m-%d' if input_format else '%d/%m/%Y')
        stamp = stamp.astimezone(ZoneInfo('America/Argentina/Salta'))
        if (stamp.hour, stamp.minute, stamp.second) == (0, 0, 0):
            stamp -= timedelta(microseconds=1)
        return stamp.strftime('%Y-%m-%d' if input_format else '%d/%m/%Y')
    app.jinja_env.filters['deadline'] = deadline_date
    app.jinja_env.filters['deadline_input'] = lambda value: deadline_date(value, True)

    @app.context_processor
    def public_page_context():
        return {'page_meta': public_metadata.page_metadata(
            app.config, request.endpoint,
            filtered=request.endpoint == 'index' and bool(request.query_string),
            method=request.method), 'legal_identity': public_metadata.legal_identity(app.config),
            'mail_available': mail_submission_ready(),
            'preview_mode': app.config['APP_ENV'] == 'development'}

    def limited(action, limit=10, seconds=3600):
        # Se almacena un hash salado del IP; no se confía en X-Forwarded-For sin proxy configurado.
        key = hashlib.sha256((app.config['SECRET_KEY'] + action + (request.remote_addr or 'local')).encode()).hexdigest()
        conn = connection()
        now = int(time.time())
        with conn:
            conn.execute('INSERT INTO rate_limits(key,count,reset_at) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN rate_limits.reset_at<? THEN 1 ELSE rate_limits.count+1 END, reset_at=CASE WHEN rate_limits.reset_at<? THEN excluded.reset_at ELSE rate_limits.reset_at END', (key, now+seconds, now, now))
            row = conn.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()
        if row['count'] > limit:
            abort(429, 'Demasiados intentos. Volvé a intentar más tarde.')

    @app.before_request
    def protect():
        # La firma del proveedor reemplaza CSRF exclusivamente en este endpoint.
        # El blueprint la verifica antes de abrir la base o procesar datos.
        if request.endpoint == 'mail_webhooks.resend':
            return
        if request.method == 'POST':
            supplied = request.form.get('csrf_token', '')
            # La baja de un clic usa un token firmado, nunca un ID predecible.
            one_click = request.endpoint == 'unsubscribe' and request.form.get('List-Unsubscribe') == 'One-Click'
            if not one_click and (not supplied.isascii() or len(supplied) > 200 or not session.get('csrf') or not hmac.compare_digest(supplied, session['csrf'])):
                abort(400, 'El formulario venció. Recargá la página e intentá otra vez.')
            if request.form.get('website'):
                abort(400, 'Solicitud no válida.')

    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.path.startswith(('/admin', '/alertas/', '/api/cron/')):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        elif (response.status_code >= 400 or request.method not in ('GET', 'HEAD') or
              request.endpoint not in ('index', 'job_detail', 'guide_detail', 'privacy', 'terms', 'sitemap', 'robots', 'static') or
              (request.endpoint == 'index' and request.query_string) or
              (request.endpoint in ('privacy', 'terms') and not public_metadata.legal_identity(app.config)['complete'])):
            response.headers['X-Robots-Tag'] = 'noindex, follow'
        return response

    def admin_required(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('admin'):
                return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return wrapped

    def row_dict(row):
        if row is None:
            abort(404)
        result = dict(row)
        for key in ('flags', 'uncertain_fields'):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except ValueError:
                    result[key] = []
        return result

    def settings_dict():
        # El registro de webhooks y supresiones comparte la tabla: las páginas
        # públicas solo necesitan estas tres opciones, nunca todo ese historial.
        return {r['key']: r['value'] for r in connection().execute(
            "SELECT key,value FROM settings WHERE key IN ('review_days','whatsapp_manual','social_manual')")}

    def mail_configuration_state():
        from . import mailer
        state = mailer.delivery_readiness(app.config)
        if production and not public_metadata.legal_identity(app.config)['complete']:
            state['missing'].append({'key': 'responsable', 'message': 'Completar el responsable y un contacto público válido.'})
            state['ready'] = False
        return state

    def mail_submission_ready():
        if app.config.get('MAIL_ENABLED') != '1':
            return False
        if production:
            return mail_configuration_state()['ready']
        # Desarrollo prueba una bandeja inerte; send_outbox impide los envíos.
        return bool(app.config['PUBLIC_BASE_URL'] and app.config['RESEND_API_KEY'] and app.config['MAIL_FROM'])

    def channels():
        settings = settings_dict()
        return [{'key': key, 'name': label, 'enabled': settings.get(key, '1') == '1', 'mode': 'manual'} for key, label in [('whatsapp_manual', 'WhatsApp: compartir manualmente'), ('social_manual', 'Redes: copiar texto y enlace')]]

    def audit(action, entity=None, detail=''):
        with connection():
            connection().execute('INSERT INTO audit(actor,action,entity_id,detail,created_at) VALUES (?,?,?,?,?)', ('administrador', action, entity, detail, domain.now()))

    def external_url(value):
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password:
            raise ValueError('El enlace debe ser HTTPS, sin credenciales.')
        return value

    @app.get('/')
    def index():
        conn = connection()
        filters = homepage.search_filters(request.args)
        try:
            jobs = domain.public_jobs(conn, filters)
        except ValueError as exc:
            abort(400, str(exc))
        all_jobs = jobs if not filters else domain.public_jobs(conn)
        facets = homepage.facets(all_jobs, filters)
        ads = [dict(r) for r in conn.execute('SELECT * FROM ads WHERE active=1 AND starts_at<=? AND ends_at>=?', (domain.now(), domain.now()))]
        return render_template('index.html', jobs=jobs, filters=filters, facets=facets, ads=ads,
                               home=homepage.presentation(all_jobs, jobs, filters,
                                                          index_url=url_for('index')),
                               guides=guides.all_guides())

    @app.get('/guias/<slug>')
    def guide_detail(slug):
        guide = guides.get_guide(slug)
        if guide is None:
            abort(404)
        return render_template('guide.html', guide=guide,
                               related_guides=guides.all_guides(exclude=slug),
                               page_meta=public_metadata.page_metadata(app.config, 'guide_detail',
                                                                       guide=guide))

    @app.get('/ofertas/<int:job_id>')
    def job_detail(job_id):
        job = domain.public_job(connection(), job_id)
        if not job:
            abort(404)
        job['share_url'] = public_metadata.public_url(app.config, url_for('job_detail', job_id=job_id)) or url_for('job_detail', job_id=job_id)
        job['share_text'] = f"{job['title']} · {job.get('company') or 'Empresa no informada'} · {job.get('location') or 'Localidad no informada'}. {job['share_url']}"
        job['whatsapp_url'] = 'https://wa.me/?' + urlencode({'text': job['share_text']})
        ch = {c['key']: c['enabled'] for c in channels()}
        return render_template('job.html', job=job, channels=ch, share_url=job['share_url'], share_text=job['share_text'],
                               page_meta=public_metadata.page_metadata(app.config, 'job_detail', job=job))

    @app.post('/ofertas/<int:job_id>/reportar')
    def report(job_id):
        if not connection().execute('SELECT id FROM jobs WHERE id=?', (job_id,)).fetchone():
            abort(404)
        limited('report', 5)
        text = (request.form.get('reason', '') + ': ' + request.form.get('message', '')).strip()
        if len(text) < 8 or len(text) > 3000:
            abort(400, 'Describí el problema, la corrección o el retiro solicitado (8 a 3000 caracteres).')
        with connection():
            connection().execute('INSERT INTO reports(job_id,reason,contact,created_at,status) VALUES (?,?,?,?,?)', (job_id, text, request.form.get('email', '')[:254], domain.now(), 'pending'))
        return render_template('message.html', title='Recibimos tu reporte', message='El administrador revisará el aviso y la corrección o retiro solicitado.')

    def save_image(file):
        if not file or not file.filename:
            return None
        try:
            Image.MAX_IMAGE_PIXELS = 16_000_000
            with Image.open(file.stream) as img:
                if img.format not in ('JPEG', 'PNG', 'WEBP') or img.width * img.height > 16_000_000:
                    raise ValueError('Usá una imagen JPG, PNG o WEBP de hasta 16 megapíxeles.')
                img.load()
                img = ImageOps.exif_transpose(img)
                img.thumbnail((2400, 2400))
                image_buffer = BytesIO()
                img.convert('RGB').save(image_buffer, 'JPEG', quality=85)
                content = image_buffer.getvalue()
                if len(content) > 4 * 1024 * 1024:
                    raise ValueError('La copia de la imagen supera 4 MB; usá una versión más pequeña.')
                name = hashlib.sha256(content).hexdigest() + '.jpg'
                if db.is_postgres(app.config['DATABASE_TARGET']):
                    with connection():
                        connection().execute('INSERT INTO uploads(name,data,created_at) VALUES (?,?,?) ON CONFLICT(name) DO NOTHING', (name, content, domain.now()))
                else:
                    (Path(app.config['UPLOAD_DIR']) / name).write_bytes(content)
                return name
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('No se pudo leer la imagen. Usá JPG, PNG o WEBP.') from exc

    def job_form(existing=None):
        data = request.form.to_dict()
        if 'uncertain_fields' in data:
            data['uncertain_fields'] = [x.strip() for x in data['uncertain_fields'].split(',') if x.strip()]
        # Estado, fechas de recopilación y aprobador nunca se toman del formulario.
        for forbidden in ('status', 'approved_at', 'approved_by', 'collected_at', 'last_checked_at', 'image_path'):
            data.pop(forbidden, None)
        image = save_image(request.files.get('image'))
        if image:
            data['image_path'] = image
            data['uncertain_fields'] = ['transcripción de imagen pendiente de revisión humana']
        elif existing:
            data['image_path'] = existing.get('image_path')
        if not existing and str(data.get('original_text', '')).strip():
            prepared = extraction.prepare_text(data['original_text'])
            for field, value in prepared['fields'].items():
                if not str(data.get(field) or '').strip():
                    data[field] = value
            data['uncertain_fields'] = domain._list(data.get('uncertain_fields')) + prepared['uncertain_fields']
        if not str(data.get('title', '')).strip() and any(data.get(key) for key in ('source_url', 'original_text', 'image_path')):
            data['title'] = 'Aviso pendiente de transcripción'
            data.setdefault('uncertain_fields', []).append('Puesto pendiente de transcripción humana; publicación bloqueada hasta completarlo')
        return data

    def image_consent(job_id, actor, uploaded_name):
        if request.form.get('allow_ocr') == '1' and image_pipeline.configured(app.config):
            row = connection().execute('SELECT image_path,status FROM jobs WHERE id=?', (job_id,)).fetchone()
            # Un duplicado público no autoriza el archivo privado que ya existía.
            uploaded = request.files.get('image')
            if row and row['status'] == 'pending' and row['image_path'] == uploaded_name and uploaded_name and uploaded and uploaded.filename:
                image_pipeline.authorize(connection(), job_id, app.config, actor)

    @app.route('/publicar', methods=['GET', 'POST'])
    def submit_job():
        errors = []
        if request.method == 'POST':
            limited('submission', 5)
            if not request.form.get('consent'):
                errors.append('Confirmá que tenés permiso para compartir el contenido.')
            else:
                try:
                    data = job_form()
                    job_id, duplicates = domain.create_job(connection(), data, actor='comunidad')
                    image_consent(job_id, 'comunidad', data.get('image_path'))
                    return render_template('message.html', title='Aviso recibido para revisión', message='El aviso quedó pendiente. Solo el administrador puede aprobar su publicación; si ya existía, conservamos su procedencia.')
                except ValueError as exc:
                    errors.append(str(exc))
        return render_template('submit.html', data=request.form, errors=errors,
                               image_status=image_pipeline.status(connection(), app.config))

    @app.route('/admin/ingresar', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            limited('login', 8, 900)
            if app.config['ADMIN_PASSWORD_HASH'] and check_password_hash(app.config['ADMIN_PASSWORD_HASH'], request.form.get('password', '')):
                session.clear()
                session['admin'] = True
                session.permanent = True
                audit('ingreso')
                return redirect(url_for('admin'))
            flash('Credenciales incorrectas o administración sin configurar.', 'error')
        return render_template('login.html', configured=bool(app.config['ADMIN_PASSWORD_HASH']))

    @app.post('/admin/salir')
    @admin_required
    def logout():
        session.clear()
        return redirect(url_for('index'))

    @app.get('/admin')
    @admin_required
    def admin():
        conn = connection()
        status = request.args.get('status', '')
        query = 'SELECT * FROM jobs' + (' WHERE status=?' if status else '') + ' ORDER BY collected_at DESC LIMIT 200'
        jobs = [row_dict(r) for r in conn.execute(query, (status,) if status else ())]
        summary = {r['status']: r['n'] for r in conn.execute('SELECT status,count(*) n FROM jobs GROUP BY status')}
        return render_template('admin.html', jobs=jobs, summary=summary,
            sources=[dict(r) for r in conn.execute('SELECT * FROM sources')],
            reports=[dict(r) for r in conn.execute('SELECT * FROM reports ORDER BY id DESC LIMIT 100')],
            outbox=[dict(r) for r in conn.execute('SELECT id,kind,status,attempts,last_error,created_at FROM outbox ORDER BY id DESC LIMIT 30')],
            subscribers_count=conn.execute("SELECT count(*) FROM subscribers WHERE status='confirmed'").fetchone()[0],
            channels=channels(), ads=[dict(r) for r in conn.execute('SELECT * FROM ads')],
            task_runs=[dict(r) for r in conn.execute('SELECT * FROM task_runs ORDER BY id DESC LIMIT 20')])

    def automation_result(detail):
        """Resume solo contadores conocidos, sin mostrar mensajes externos ni secretos."""
        if not detail:
            return 'Sin resultado registrado.'
        try:
            result = json.loads(detail)
        except (ValueError, TypeError):
            return 'Resultado registrado; requiere revisión.'
        if not isinstance(result, dict):
            return 'Resultado registrado; requiere revisión.'
        labels = {
            'received': 'recibidos', 'eligible': 'compatibles para revisión',
            'created': 'incorporados', 'duplicates': 'duplicados', 'invalid': 'no válidos',
            'expired': 'vencidos', 'review_requested': 'revisiones solicitadas',
            'queued': 'preparados', 'sent': 'aceptados por el proveedor',
            'skipped': 'omitidos', 'errors': 'errores', 'checked': 'comprobados',
            'archived': 'archivados', 'unknown': 'sin estado confirmado',
            'processed': 'imágenes procesadas', 'prepared': 'avisos preparados',
        }
        parts = []
        for section in (result, *(result.get(key) for key in ('expiration', 'queue', 'mail', 'status_check', 'images'))):
            if isinstance(section, dict):
                parts.extend(f'{label}: {section[key]}' for key, label in labels.items()
                             if type(section.get(key)) is int and section[key] >= 0)
        sources = result.get('sources')
        if isinstance(sources, list):
            parts.append(f'fuentes procesadas: {len(sources)}')
        if result.get('budget_exhausted') is True:
            parts.append('límite de tiempo alcanzado; pendientes conservados')
        return '; '.join(parts) or 'Resultado registrado; consultá el estado de la corrida.'

    @app.get('/admin/automatizacion')
    @admin_required
    def admin_automation():
        from . import mailer
        conn = connection()
        sources = [dict(row) for row in conn.execute('SELECT * FROM sources ORDER BY name,id')]
        for source in sources:
            source['result_summary'] = automation_result(source['last_result'])
            source['collectible'] = bool(source['status'] == 'active' and source['authorized']
                                         and source['method'] == 'jobicy'
                                         and source['url'] == 'https://jobicy.com/api/v2/remote-jobs')
        runs = [dict(row) for row in conn.execute('SELECT * FROM task_runs ORDER BY id DESC LIMIT 20')]
        for run in runs:
            run['result_summary'] = automation_result(run['detail'])
        cron_last = conn.execute("SELECT created_at FROM audit WHERE actor='programador' AND action='cron_recibido' ORDER BY id DESC LIMIT 1").fetchone()
        mail_state = mail_configuration_state()
        return render_template('automation.html', sources=sources, task_runs=runs,
            database_type='PostgreSQL' if db.is_postgres(app.config['DATABASE_TARGET']) else 'SQLite',
            mail_key_present=bool(app.config['RESEND_API_KEY']),
            mail_sender_present=bool(app.config['MAIL_FROM']),
            mail_ready=mail_state['ready'], mail_status=mail_state,
            mail_quota=mailer.quota_status(conn, app.config),
            mail_webhook_ready=not any(item['key'] == 'webhook' for item in mail_state['missing']),
            operational=operations.operations_snapshot(conn, app.config),
            cron_key_present=bool(app.config['CRON_SECRET']),
            cron_last=cron_last['created_at'] if cron_last else None,
            automatic_sources=sum(source['collectible'] for source in sources),
            image_status=image_pipeline.status(conn, app.config),
            outbox_summary=[dict(row) for row in conn.execute('SELECT status,count(*) AS total FROM outbox GROUP BY status ORDER BY status')])

    @app.post('/admin/automatizacion/<task>')
    @admin_required
    def admin_run_task(task):
        if task not in ('collect', 'expire', 'mail', 'extract'):
            abort(404)
        limited('admin_automation', 6, 600)
        from . import mailer, tasks
        # Un clic nunca ejecuta todas las tareas ni aumenta los lotes configurados.
        config = dict(app.config)
        try:
            config['TASK_BUDGET_SECONDS'] = min(60, max(1, int(config.get('TASK_BUDGET_SECONDS', 180))))
            config['TASK_SOURCE_BATCH'] = 1
            config['TASK_MAIL_BATCH'] = min(3, max(1, int(config.get('TASK_MAIL_BATCH', 10))))
            result = tasks.run_tasks(connection(), config, only=task)
            audit('ejecutar_tarea_manual', detail=task)
            if 'skipped' in result:
                flash('Ya hay una tarea en ejecución. Esta corrida se omitió sin repetir el trabajo.', 'error')
            elif task == 'mail' and not mailer._valid_delivery_config(config):
                flash('Corrida registrada. No se enviaron correos: falta habilitar la configuración de envío de producción. Los pendientes se conservan.', 'success')
            elif task == 'extract' and not image_pipeline.configured(config):
                flash('La lectura de imágenes está pendiente de configuración. No se enviaron imágenes a ningún proveedor.', 'success')
            else:
                flash('Corrida registrada. Revisá su estado y resultado antes de considerarla completada.', 'success')
        except Exception as exc:
            connection().rollback()
            # No incluir str(exc) ni traceback: podrían contener URLs con credenciales.
            app.logger.error('Falló la tarea manual %s (%s).', task, type(exc).__name__)
            flash('No se pudo completar la corrida. Los registros conservan el estado; revisá la configuración antes de volver a intentar.', 'error')
        return redirect(url_for('admin_automation'))

    @app.route('/admin/nueva', methods=['GET', 'POST'])
    @admin_required
    def admin_new():
        if request.method == 'POST':
            try:
                data = job_form()
                job_id, _ = domain.create_job(connection(), data, actor='administrador')
                image_consent(job_id, 'administrador', data.get('image_path'))
                return redirect(url_for('admin_edit', job_id=job_id))
            except ValueError as exc:
                flash(str(exc), 'error')
        return render_template('edit.html', job=dict(request.form), duplicates=[], provenance=[],
                               image_status=image_pipeline.status(connection(), app.config), image_result=None)

    @app.route('/admin/ofertas/<int:job_id>', methods=['GET', 'POST'])
    @admin_required
    def admin_edit(job_id):
        job = row_dict(connection().execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
        if request.method == 'POST':
            try:
                domain.edit_job(connection(), job_id, job_form(job), actor='administrador')
                flash('Guardado. El aviso requiere aprobación antes de publicarse.', 'success')
                return redirect(url_for('admin_edit', job_id=job_id))
            except ValueError as exc:
                flash(str(exc), 'error')
        provenance = [dict(r) for r in connection().execute('SELECT * FROM provenance WHERE job_id=? ORDER BY id DESC', (job_id,))]
        for version in provenance:
            try:
                payload = json.loads(version.get('payload') or '{}')
            except (ValueError, TypeError):
                payload = {}
            version['prepared_fields'] = {
                field: payload[field] for field in domain.MATERIAL_FIELDS
                if isinstance(payload, dict) and field in payload
                and (payload[field] is None or isinstance(payload[field], str))
            }
        duplicates = [row_dict(r) for r in connection().execute('SELECT * FROM jobs WHERE id<>? AND lower(title)=lower(?) LIMIT 10', (job_id, job['title']))]
        image_result = image_pipeline.result_for(connection(), job_id, job.get('image_path'))
        return render_template('edit.html', job=job, duplicates=duplicates, provenance=provenance,
                               image_status=image_pipeline.status(connection(), app.config),
                               image_result=image_result,
                               image_error_message=str(extraction.ExtractionError(image_result.get('error_code'))) if image_result and image_result['status'] == 'failed' else '',
                               image_retry_available=job['status'] == 'pending' and image_pipeline.retry_available(connection(), job_id, job.get('image_path')))

    @app.post('/admin/ofertas/<int:job_id>/reintentar-lectura')
    @admin_required
    def admin_retry_image(job_id):
        limited('admin_automation', 6, 600)
        if request.form.get('allow_ocr') != '1' or request.form.get('configuration_checked') != '1':
            abort(400, 'Confirmá el permiso y que revisaste la configuración de Google antes de reintentar.')
        if not image_pipeline.configured(app.config):
            flash('La lectura está pendiente de configuración. No se envió ninguna imagen.', 'error')
            return redirect(url_for('admin_edit', job_id=job_id))
        from . import tasks
        try:
            submitted_id = request.form.get('failed_event_id', '')
            if not submitted_id.isascii() or not submitted_id.isdecimal() or len(submitted_id) > 20:
                raise ValueError('Recargá el aviso para obtener el resultado de lectura vigente.')
            failed_event_id = int(submitted_id)
            image_pipeline.authorize_retry(connection(), job_id, app.config, failed_event_id, 'administrador')
            result = tasks.run_tasks(connection(), dict(app.config, OCR_JOB_ID=job_id, TASK_BUDGET_SECONDS=60), only='extract')
            if result.get('images', {}).get('quota_reached'):
                flash('Se alcanzó el límite mensual. La solicitud queda registrada sin enviar la imagen.', 'error')
            elif result.get('skipped'):
                flash('Hay otra tarea en ejecución. La autorización queda pendiente para el próximo lote.', 'success')
            else:
                flash('Reintento registrado. Revisá el resultado; el aviso no se aprueba automáticamente.', 'success')
        except (ValueError, OSError) as exc:
            flash(str(exc) if isinstance(exc, ValueError) else 'La imagen no está disponible.', 'error')
        except Exception as exc:
            connection().rollback()
            app.logger.error('Falló el reintento de lectura (%s).', type(exc).__name__)
            flash('No se pudo completar el reintento. Revisá el registro antes de volver a solicitarlo.', 'error')
        return redirect(url_for('admin_edit', job_id=job_id))

    @app.post('/admin/ofertas/<int:job_id>/leer-imagen')
    @admin_required
    def admin_extract_image(job_id):
        limited('admin_automation', 6, 600)
        if request.form.get('allow_ocr') != '1':
            abort(400, 'Confirmá el permiso para analizar la imagen antes de continuar.')
        if not image_pipeline.configured(app.config):
            flash('La lectura está pendiente de configuración. No se envió ninguna imagen.', 'error')
            return redirect(url_for('admin_edit', job_id=job_id))
        from . import tasks
        try:
            image_pipeline.authorize(connection(), job_id, app.config, 'administrador')
            config = dict(app.config, OCR_JOB_ID=job_id, TASK_BUDGET_SECONDS=60)
            result = tasks.run_tasks(connection(), config, only='extract')
            audit('solicitar_lectura_imagen', entity=job_id)
            if result.get('images', {}).get('quota_reached'):
                flash('Se alcanzó el límite mensual de lecturas. No se envió la imagen.', 'error')
            else:
                flash('Solicitud registrada. Revisá el resultado de lectura; esta acción nunca aprueba ni publica el aviso.', 'success')
        except (ValueError, OSError):
            flash('No se pudo leer esta imagen. Revisá que el aviso siga pendiente y que el archivo esté disponible.', 'error')
        except Exception as exc:
            connection().rollback()
            app.logger.error('Falló la lectura de imagen (%s).', type(exc).__name__)
            flash('La lectura no pudo completarse. Revisá el resultado antes de volver a intentar.', 'error')
        return redirect(url_for('admin_edit', job_id=job_id))

    @app.post('/admin/ofertas/<int:job_id>/<action>')
    @admin_required
    def admin_transition(job_id, action):
        try:
            domain.transition_job(connection(), job_id, action, actor='administrador', acknowledge=bool(request.form.get('acknowledge')))
            flash('Estado actualizado.', 'success')
        except ValueError as exc:
            flash(str(exc), 'error')
        return redirect(url_for('admin_edit', job_id=job_id))

    @app.get('/admin/imagenes/<int:job_id>')
    @admin_required
    def admin_image(job_id):
        row = connection().execute('SELECT image_path FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row or not row['image_path']:
            abort(404)
        if db.is_postgres(app.config['DATABASE_TARGET']):
            upload = connection().execute('SELECT data FROM uploads WHERE name=?', (row['image_path'],)).fetchone()
            if not upload:
                abort(404)
            return send_file(BytesIO(bytes(upload['data'])), mimetype='image/jpeg')
        path = Path(app.config['UPLOAD_DIR']) / Path(row['image_path']).name
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype='image/jpeg')

    @app.route('/admin/fuentes', methods=['GET', 'POST'])
    @admin_required
    def admin_sources():
        if request.method == 'POST':
            try:
                data = request.form
                method = data.get('method', 'manual')
                if method not in ('manual', 'jobicy'):
                    raise ValueError('Método no compatible.')
                url = external_url(data.get('url', ''))
                if method == 'jobicy' and url != 'https://jobicy.com/api/v2/remote-jobs':
                    raise ValueError('La API compatible es https://jobicy.com/api/v2/remote-jobs.')
                frequency = max(6, int(data.get('frequency_hours', 24)))
                authorized = int(bool(data.get('authorized')))
                status = 'active' if authorized and data.get('enabled') else 'disabled'
                name = data.get('name', '').strip()[:200]
                terms = external_url(data.get('terms_url', '')) if data.get('terms_url') else None
                if not name or (method != 'manual' and not terms):
                    raise ValueError('Indicá nombre y condiciones de uso revisadas.')
                values = (name, url, method, frequency, status, terms, domain.now() if authorized else None, authorized)
                with connection():
                    if data.get('id'):
                        connection().execute('UPDATE sources SET name=?,url=?,method=?,frequency_hours=?,status=?,terms_url=?,terms_checked_at=?,authorized=? WHERE id=?', (*values, int(data['id'])))
                    else:
                        connection().execute('INSERT INTO sources(name,url,method,frequency_hours,status,terms_url,terms_checked_at,authorized) VALUES (?,?,?,?,?,?,?,?)', values)
                audit('configurar_fuente', detail=name)
                flash('Fuente guardada. La tarea CLI registra cada resultado.', 'success')
            except (ValueError, TypeError) as exc:
                flash(str(exc), 'error')
        return render_template('sources.html', sources=[dict(r) for r in connection().execute('SELECT * FROM sources')],
                               source_presets=source_catalog.source_presets())

    @app.post('/admin/fuentes/preparadas/<key>')
    @admin_required
    def admin_source_preset(key):
        try:
            preset = source_catalog.select_preset(key)
        except ValueError:
            abort(404)
        with connection():
            db.editorial_lock(connection())
            existing = connection().execute('SELECT id FROM sources WHERE url=?', (preset['url'],)).fetchone()
            if not existing:
                connection().execute("INSERT INTO sources(name,url,method,frequency_hours,status,terms_url,authorized) VALUES (?,?,'manual',24,'disabled',?,0)",
                                     (preset['name'], preset['url'], preset['terms_url']))
                audit('registrar_referencia_manual', detail=preset['name'])
        flash('Referencia registrada. No habilita recopilación ni concede permiso para reutilizar contenido.', 'success')
        return redirect(url_for('admin_sources'))

    @app.route('/admin/publicidad', methods=['GET', 'POST'])
    @admin_required
    def admin_ads():
        if request.method == 'POST':
            data = request.form
            try:
                if data.get('action') in ('delete', 'deactivate'):
                    with connection():
                        connection().execute('UPDATE ads SET active=0 WHERE id=?', (int(data['id']),))
                else:
                    image_url, link_url = external_url(data.get('image_url', '')), external_url(data.get('link_url', ''))
                    start = datetime.fromisoformat(data.get('starts_at', '')).replace(tzinfo=timezone.utc).isoformat()
                    end = datetime.fromisoformat(data.get('ends_at', '')).replace(tzinfo=timezone.utc).isoformat()
                    if start >= end:
                        raise ValueError('La fecha final debe ser posterior a la inicial.')
                    placement = data.get('placement', 'home')
                    if placement not in ('home', 'sidebar'):
                        raise ValueError('Ubicación no válida.')
                    values = (data.get('label', '')[:150] or 'Negocio local', image_url, link_url, placement, start, end, int(bool(data.get('active'))))
                    with connection():
                        if data.get('id'):
                            connection().execute('UPDATE ads SET label=?,image_url=?,link_url=?,placement=?,starts_at=?,ends_at=?,active=? WHERE id=?', (*values, int(data['id'])))
                        else:
                            connection().execute('INSERT INTO ads(label,image_url,link_url,placement,starts_at,ends_at,active) VALUES (?,?,?,?,?,?,?)', values)
                audit('configurar_publicidad')
                flash('Publicidad actualizada.', 'success')
            except (ValueError, TypeError) as exc:
                flash(str(exc), 'error')
        return render_template('ads.html', ads=[dict(r) for r in connection().execute('SELECT * FROM ads')])

    @app.route('/admin/configuracion', methods=['GET', 'POST'])
    @admin_required
    def admin_settings():
        if request.method == 'POST':
            try:
                days = int(request.form.get('review_days', 30))
                if days < 1 or days > 365:
                    raise ValueError('La revisión debe estar entre 1 y 365 días.')
                values = {'review_days': str(days), **{key: '1' if request.form.get(key) else '0' for key in ('whatsapp_manual', 'social_manual')}}
                with connection():
                    connection().executemany('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', values.items())
                audit('configurar_canales')
                flash('Configuración guardada.', 'success')
            except ValueError as exc:
                flash(str(exc), 'error')
        mail_state = mail_configuration_state()
        return render_template('settings.html', settings=settings_dict(), channels=channels(),
                               mail_ready=mail_state['ready'], mail_status=mail_state)

    @app.route('/alertas', methods=['GET', 'POST'])
    def subscribe():
        if request.method == 'POST':
            from . import mailer
            import re
            limited('subscribe', 4)
            email = request.form.get('email', '').strip().lower()
            frequency = request.form.get('frequency', 'weekly')
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email) > 254 or frequency not in ('daily', 'weekly') or not request.form.get('consent'):
                flash('Ingresá un correo válido, frecuencia y consentimiento.', 'error')
            elif not mail_submission_ready():
                return render_template('message.html', title='Alertas pendientes de configuración', message='El envío de correo todavía no está habilitado. No registramos tu dirección. Podés consultar las ofertas en la web.')
            else:
                conn = connection()
                with conn:
                    db.mailer_lock(conn)
                    row = conn.execute('SELECT * FROM subscribers WHERE email=?', (email,)).fetchone()
                    if not row:
                        cursor = conn.execute('INSERT INTO subscribers(email,locality,sector,modality,frequency,status,token_hash,created_at) VALUES (?,?,?,?,?,?,?,?)', (email, request.form.get('location', '')[:150], request.form.get('sector', '')[:150], request.form.get('modality', '')[:40], frequency, 'pending', '', domain.now()))
                        subscriber_id = cursor.lastrowid
                    elif row['status'] == 'confirmed':
                        subscriber_id = None  # No cambiar preferencias ajenas sin confirmar otra vez.
                    else:
                        subscriber_id = row['id']
                        conn.execute("UPDATE subscribers SET status='pending',locality=?,sector=?,modality=?,frequency=? WHERE id=?", (request.form.get('location', '')[:150], request.form.get('sector', '')[:150], request.form.get('modality', '')[:40], frequency, subscriber_id))
                    if subscriber_id:
                        mailer.queue_confirmation(conn, subscriber_id, app.config['PUBLIC_BASE_URL'], app.config['SECRET_KEY'])
                return render_template('message.html', title='Solicitud recibida', message='Si corresponde, recibirás un enlace para confirmar el correo. La suscripción se activa solo después de confirmarlo. Si ya estás suscripto, conservamos tus preferencias.')
        return render_template('subscribe.html', data=request.form, mail_ready=mail_submission_ready())

    @app.route('/alertas/confirmar/<token>', methods=['GET', 'POST'])
    def confirm_subscription(token):
        from . import mailer
        try:
            subscriber_id, digest = mailer.verify_token(token, app.config['SECRET_KEY'], 'confirm', max_age=48*3600)
        except Exception:
            abort(400, 'El enlace no es válido o venció. Solicitá la suscripción otra vez.')
        row = connection().execute('SELECT * FROM subscribers WHERE id=?', (subscriber_id,)).fetchone()
        if not row or not hmac.compare_digest(row['token_hash'] or '', digest) or row['status'] == 'unsubscribed':
            abort(400, 'Este enlace ya no está disponible.')
        if request.method == 'POST':
            with connection():
                db.mailer_lock(connection())
                current = connection().execute('SELECT token_hash,status,email FROM subscribers WHERE id=?', (subscriber_id,)).fetchone()
                if (not current or current['status'] == 'unsubscribed' or
                        not hmac.compare_digest(current['token_hash'] or '', digest) or
                        mailer.is_suppressed(connection(), current['email'])):
                    abort(400, 'Este enlace ya no está disponible.')
                connection().execute("UPDATE subscribers SET status='confirmed',confirmed_at=? WHERE id=?", (domain.now(), subscriber_id))
            return render_template('message.html', title='Suscripción confirmada', message='Recibirás ofertas aprobadas según tus preferencias. Cada correo incluye el enlace de baja.')
        return render_template('confirm.html', title='Confirmar suscripción', message='Confirmá que querés recibir estas alertas de empleo.', action_url=request.path)

    @app.route('/alertas/baja/<token>', methods=['GET', 'POST'])
    def unsubscribe(token):
        from . import mailer
        try:
            subscriber_id, _ = mailer.verify_token(token, app.config['SECRET_KEY'], 'unsubscribe', max_age=None)
        except Exception:
            abort(400, 'El enlace no es válido.')
        if request.method == 'POST':
            with connection():
                db.mailer_lock(connection())
                connection().execute("UPDATE subscribers SET status='unsubscribed',token_hash='' WHERE id=?", (subscriber_id,))
                connection().execute("UPDATE outbox SET status='cancelled' WHERE subscriber_id=? AND status IN ('pending','retry')", (subscriber_id,))
            return render_template('message.html', title='Baja confirmada', message='La suscripción quedó desactivada. No recibirás nuevas alertas.')
        return render_template('confirm.html', title='Dar de baja las alertas', message='Podés cancelar tu suscripción con un clic.', action_url=request.path)

    @app.get('/privacidad')
    def privacy():
        return render_template('legal.html', title='Privacidad', document='privacy',
                               ocr_paused=not image_pipeline.configured(app.config))

    @app.get('/condiciones')
    def terms():
        return render_template('legal.html', title='Condiciones del servicio', document='terms')

    @app.get('/sitemap.xml')
    def sitemap():
        try:
            content = public_metadata.sitemap_xml(app.config, domain.public_jobs(connection()))
        except ValueError:
            abort(503)
        return app.response_class(content, mimetype='application/xml')

    @app.get('/robots.txt')
    def robots():
        # Estas reglas orientan rastreadores; los permisos se controlan en servidor.
        lines = ['User-agent: *', 'Allow: /', 'Disallow: /admin', 'Disallow: /api/',
                 'Disallow: /alertas/', 'Disallow: /salud']
        sitemap_url = public_metadata.public_url(app.config, '/sitemap.xml')
        if sitemap_url:
            lines += ['', 'Sitemap: ' + sitemap_url]
        return app.response_class('\n'.join(lines) + '\n', mimetype='text/plain')

    @app.get('/salud')
    def health():
        connection().execute('SELECT 1')
        return {'status': 'ok'}

    @app.get('/api/cron/<task>')
    def cron(task):
        if task not in ('collect', 'expire', 'mail', 'extract'):
            abort(404)
        secret = app.config['CRON_SECRET']
        supplied = request.headers.get('Authorization', '')
        if not secret or not hmac.compare_digest(supplied.encode(), ('Bearer ' + secret).encode()):
            abort(401)
        with connection():
            connection().execute('INSERT INTO audit(actor,action,detail,created_at) VALUES (?,?,?,?)',
                                 ('programador', 'cron_recibido', task, domain.now()))
        from .tasks import run_tasks
        result = run_tasks(connection(), app.config, only=task)
        app.logger.info('SALTA_TASK %s', json.dumps(operations.task_summary(task, result), sort_keys=True))
        response = app.json.response(result)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def friendly_error(error):
        messages = {404: 'La oferta o página no está disponible. Puede haberse retirado o vencido.', 413: 'El archivo supera el límite de 4 MB.'}
        return render_template('message.html', title=f'Solicitud {error.code}', message=messages.get(error.code, str(error.description))), error.code

    return app
