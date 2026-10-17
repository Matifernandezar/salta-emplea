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
from PIL import Image, UnidentifiedImageError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from . import db, domain
from .config import load_env


def create_app(config=None):
    load_env()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        ADMIN_PASSWORD_HASH=os.environ.get('ADMIN_PASSWORD_HASH', ''),
        DATABASE_PATH=os.environ.get('DATABASE_PATH', str(Path(app.instance_path) / 'salta.sqlite3')),
        DATABASE_URL=os.environ.get('DATABASE_URL', ''),
        SERVERLESS=os.environ.get('VERCEL') == '1',
        CRON_SECRET=os.environ.get('CRON_SECRET', ''),
        UPLOAD_DIR=os.environ.get('UPLOAD_DIR', str(Path(app.instance_path) / 'uploads')),
        PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL', ''),
        APP_ENV=os.environ.get('APP_ENV', 'production' if os.environ.get('VERCEL') == '1' else 'development'),
        RESEND_API_KEY=os.environ.get('RESEND_API_KEY', ''),
        MAIL_FROM=os.environ.get('MAIL_FROM', ''),
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

    def limited(action, limit=10, seconds=3600):
        # Se almacena un hash salado del IP; no se confía en X-Forwarded-For sin proxy configurado.
        key = hashlib.sha256((app.config['SECRET_KEY'] + action + (request.remote_addr or 'local')).encode()).hexdigest()
        conn = connection()
        now = int(time.time())
        with conn:
            conn.execute('INSERT INTO rate_limits(key,count,reset_at) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN reset_at<? THEN 1 ELSE count+1 END, reset_at=CASE WHEN reset_at<? THEN excluded.reset_at ELSE reset_at END', (key, now+seconds, now, now))
            row = conn.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()
        if row['count'] > limit:
            abort(429, 'Demasiados intentos. Volvé a intentar más tarde.')

    @app.before_request
    def protect():
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
        return {r['key']: r['value'] for r in connection().execute('SELECT * FROM settings')}

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
        filters = request.args.to_dict()
        try:
            jobs = domain.public_jobs(conn, filters)
        except ValueError as exc:
            abort(400, str(exc))
        all_jobs = domain.public_jobs(conn)
        facets = {name: sorted({j[field] for j in all_jobs if j.get(field)}) for name, field in [('locations', 'location'), ('sectors', 'sector'), ('schedules', 'schedule')]}
        ads = [dict(r) for r in conn.execute('SELECT * FROM ads WHERE active=1 AND starts_at<=? AND ends_at>=?', (domain.now(), domain.now()))]
        return render_template('index.html', jobs=jobs, filters=filters, facets=facets, ads=ads)

    @app.get('/ofertas/<int:job_id>')
    def job_detail(job_id):
        job = domain.public_job(connection(), job_id)
        if not job:
            abort(404)
        base = app.config['PUBLIC_BASE_URL'].rstrip('/')
        job['share_url'] = base + url_for('job_detail', job_id=job_id) if base else request.base_url
        job['share_text'] = f"{job['title']} · {job.get('company') or 'Empresa no informada'} · {job.get('location') or 'Localidad no informada'}. {job['share_url']}"
        job['whatsapp_url'] = 'https://wa.me/?' + urlencode({'text': job['share_text']})
        ch = {c['key']: c['enabled'] for c in channels()}
        return render_template('job.html', job=job, channels=ch, share_url=job['share_url'], share_text=job['share_text'])

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
                img.thumbnail((2400, 2400))
                name = secrets.token_hex(24) + '.jpg'
                if db.is_postgres(app.config['DATABASE_TARGET']):
                    image_bytes = BytesIO()
                    img.convert('RGB').save(image_bytes, 'JPEG', quality=80)
                    with connection():
                        connection().execute('INSERT INTO uploads(name,data,created_at) VALUES (?,?,?)', (name, image_bytes.getvalue(), domain.now()))
                else:
                    img.convert('RGB').save(Path(app.config['UPLOAD_DIR']) / name, 'JPEG', quality=85)
                return name
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('No se pudo leer la imagen. Usá JPG, PNG o WEBP.') from exc

    def job_form(existing=None):
        data = request.form.to_dict()
        if 'uncertain_fields' in data:
            data['uncertain_fields'] = [x.strip() for x in data['uncertain_fields'].split(',') if x.strip()]
        # Estado, fechas de recopilación y aprobador nunca se toman del formulario.
        for forbidden in ('status', 'approved_at', 'approved_by', 'collected_at', 'last_checked_at'):
            data.pop(forbidden, None)
        image = save_image(request.files.get('image'))
        if image:
            data['image_path'] = image
            data['uncertain_fields'] = ['transcripción de imagen pendiente de revisión humana']
        elif existing:
            data['image_path'] = existing.get('image_path')
        if not str(data.get('title', '')).strip() and any(data.get(key) for key in ('source_url', 'original_text', 'image_path')):
            data['title'] = 'Aviso pendiente de transcripción'
            data.setdefault('uncertain_fields', []).append('Puesto pendiente de transcripción humana; publicación bloqueada hasta completarlo')
        return data

    @app.route('/publicar', methods=['GET', 'POST'])
    def submit_job():
        errors = []
        if request.method == 'POST':
            limited('submission', 5)
            if not request.form.get('consent'):
                errors.append('Confirmá que tenés permiso para compartir el contenido.')
            else:
                try:
                    job_id, duplicates = domain.create_job(connection(), job_form(), actor='comunidad')
                    return render_template('message.html', title='Aviso recibido para revisión', message='El aviso quedó pendiente. Solo el administrador puede aprobar su publicación; si ya existía, conservamos su procedencia.')
                except ValueError as exc:
                    errors.append(str(exc))
        return render_template('submit.html', data=request.form, errors=errors)

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

    @app.route('/admin/nueva', methods=['GET', 'POST'])
    @admin_required
    def admin_new():
        if request.method == 'POST':
            try:
                job_id, _ = domain.create_job(connection(), job_form(), actor='administrador')
                return redirect(url_for('admin_edit', job_id=job_id))
            except ValueError as exc:
                flash(str(exc), 'error')
        return render_template('edit.html', job=dict(request.form), duplicates=[], provenance=[])

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
        duplicates = [row_dict(r) for r in connection().execute('SELECT * FROM jobs WHERE id<>? AND lower(title)=lower(?) LIMIT 10', (job_id, job['title']))]
        return render_template('edit.html', job=job, duplicates=duplicates, provenance=provenance)

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
        return render_template('sources.html', sources=[dict(r) for r in connection().execute('SELECT * FROM sources')])

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
        return render_template('settings.html', settings=settings_dict(), channels=channels(), mail_ready=bool(app.config['RESEND_API_KEY'] and app.config['MAIL_FROM']))

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
            elif not (app.config['PUBLIC_BASE_URL'] and app.config['RESEND_API_KEY'] and app.config['MAIL_FROM']):
                return render_template('message.html', title='Alertas pendientes de configuración', message='El envío de correo todavía no está habilitado. No registramos tu dirección. Podés consultar las ofertas en la web.')
            else:
                conn = connection()
                with conn:
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
        return render_template('subscribe.html', data=request.form, mail_ready=bool(app.config['RESEND_API_KEY'] and app.config['MAIL_FROM']))

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
                connection().execute("UPDATE subscribers SET status='unsubscribed' WHERE id=?", (subscriber_id,))
                connection().execute("UPDATE outbox SET status='cancelled' WHERE subscriber_id=? AND status IN ('pending','retry')", (subscriber_id,))
            return render_template('message.html', title='Baja confirmada', message='La suscripción quedó desactivada. No recibirás nuevas alertas.')
        return render_template('confirm.html', title='Dar de baja las alertas', message='Podés cancelar tu suscripción con un clic.', action_url=request.path)

    @app.get('/privacidad')
    def privacy():
        return render_template('message.html', title='Privacidad', message='No solicitamos cuentas ni almacenamos CV. Si activás alertas, guardamos tu correo, preferencias y consentimiento para enviarte ofertas hasta tu baja. Los reportes y aportes se usan para revisar contenido. Las imágenes aportadas son privadas para revisión. La publicidad externa puede cargar imágenes del anunciante. Podés solicitar corrección, retiro o eliminación desde el reporte de una oferta. Responsable y contacto institucional: pendientes de definir antes del lanzamiento público. No enviar datos sensibles. Retención y ejercicio de derechos: consultar la guía de operación antes de publicar.')

    @app.get('/condiciones')
    def terms():
        return render_template('message.html', title='Condiciones del servicio', message='Salta Emplea es un nombre provisional para un servicio gratuito que centraliza avisos de terceros en Salta y empleos remotos accesibles desde la provincia. No garantiza la contratación ni la exactitud permanente del aviso original. La postulación se realiza con el contacto publicado. Nunca pagues para postularte. Revisá la fuente y reportá errores o pedidos de retiro. No hay verificación de empresas ni cobertura total de fuentes. Solo compartí contenido que tengas permiso de aportar. Antes del lanzamiento se completará la identificación del responsable y el contacto institucional.')

    @app.get('/salud')
    def health():
        connection().execute('SELECT 1')
        return {'status': 'ok'}

    @app.get('/api/cron/<task>')
    def cron(task):
        if task not in ('collect', 'expire', 'mail'):
            abort(404)
        secret = app.config['CRON_SECRET']
        supplied = request.headers.get('Authorization', '')
        if not secret or not hmac.compare_digest(supplied.encode(), ('Bearer ' + secret).encode()):
            abort(401)
        from .tasks import run_tasks
        result = run_tasks(connection(), app.config, only=task)
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
