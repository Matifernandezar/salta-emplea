"""QA Chromium con SQLite efímero y datos PRUEBA; no usa servicios productivos."""
import argparse
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.serving import make_server

from salta_emplea import db
from salta_emplea.app import create_app

PASSWORD = 'PRUEBA-contraseña-ficticia-solo-navegador'
TITLE = 'PRUEBA — Atención en comercio'
APPLICATION = 'https://example.test/postularse/prueba'
CAPTURES = Path('/tmp/salta-qa-capturas')


@contextmanager
def isolated_server():
    with TemporaryDirectory(prefix='salta-qa-navegador-') as temporary:
        # No se carga .env ni se heredan credenciales o destinos de producción.
        with patch.dict(os.environ, {}, clear=True), patch('salta_emplea.app.load_env'):
            app = create_app({
                'TESTING': True, 'SERVERLESS': False, 'APP_ENV': 'development',
                'SECRET_KEY': 'PRUEBA-clave-ficticia-aislada-de-navegador',
                'ADMIN_PASSWORD_HASH': generate_password_hash(PASSWORD),
                'DATABASE_URL': '',
                'DATABASE_PATH': str(Path(temporary) / 'prueba.sqlite3'),
                'UPLOAD_DIR': str(Path(temporary) / 'imagenes-prueba'),
                'PUBLIC_BASE_URL': '', 'RESEND_API_KEY': '', 'MAIL_FROM': '',
                'CRON_SECRET': 'PRUEBA-cron-ficticio-no-productivo',
            })
        server = make_server('127.0.0.1', 0, app, threaded=True)
        origin = f'http://127.0.0.1:{server.server_port}'
        app.config['PUBLIC_BASE_URL'] = origin
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield app, origin
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


def rows(app, query):
    connection = db.connect(app.config['DATABASE_TARGET'])
    try:
        return [dict(row) for row in connection.execute(query)]
    finally:
        connection.close()


def no_horizontal_overflow(page):
    dimensions = page.evaluate('''() => ({
        page: document.documentElement.scrollWidth, viewport: window.innerWidth
    })''')
    assert dimensions['page'] <= dimensions['viewport'] + 1, (
        f'Desborde horizontal en {urlsplit(page.url).path}: {dimensions}'
    )


def run_circuit(browser, viewport):
    with isolated_server() as (app, origin):
        context = browser.new_context(viewport=viewport, is_mobile=viewport['width'] < 600,
                                      has_touch=viewport['width'] < 600)
        public_context = browser.new_context(viewport=viewport, is_mobile=viewport['width'] < 600,
                                             has_touch=viewport['width'] < 600)
        unexpected, applications = [], []

        def route_request(route):
            url = route.request.url
            if url.startswith(origin + '/'):
                route.continue_()
            elif url == APPLICATION:
                applications.append(url)
                route.fulfill(status=200, content_type='text/html; charset=utf-8',
                              body='<p>PRUEBA: canal original simulado, sin envío.</p>')
            else:
                unexpected.append(urlsplit(url).hostname)
                route.abort()

        context.route('**/*', route_request)
        public_context.route('**/*', route_request)
        try:
            page = context.new_page()
            assert page.goto(origin + '/').status == 200
            expect(page.get_by_role('heading', level=1)).to_contain_text('Tu próximo trabajo')
            page.screenshot(path=str(CAPTURES / f'local-publica-{viewport["width"]}.png'), full_page=True)
            no_horizontal_overflow(page)
            page.goto(origin + '/admin')
            expect(page.get_by_role('heading', name='Ingresá al panel')).to_be_visible()

            page.goto(origin + '/publicar')
            data = {
                'title': TITLE, 'company': 'PRUEBA Comercio ficticio',
                'location': 'Salta Capital', 'sector': 'Comercio',
                'schedule': 'Jornada completa', 'contract_type': 'PRUEBA temporal',
                'description': 'PRUEBA: aviso ficticio, exclusivo de QA. No postularse.',
                'requirements': 'PRUEBA: requisito transcripto de una fuente ficticia.',
                'application_url': APPLICATION, 'source_name': 'PRUEBA fuente ficticia',
                'source_url': 'https://example.test/avisos/prueba',
                'original_text': 'PRUEBA: atención en comercio. Aviso ficticio de QA.',
            }
            for name, value in data.items():
                page.locator(f'form [name="{name}"]').fill(value)
            page.locator('[name="modality"]').select_option('presencial')
            page.locator('[name="consent"]').check()
            page.get_by_role('button', name='Enviar para revisión').click()
            expect(page.get_by_role('heading', name='Aviso recibido para revisión')).to_be_visible()
            jobs = rows(app, 'SELECT id,status FROM jobs')
            assert len(jobs) == 1 and jobs[0]['status'] == 'pending'
            job_id = jobs[0]['id']
            public = public_context.new_page()
            assert public.goto(f'{origin}/ofertas/{job_id}').status == 404
            public.goto(origin + '/')
            expect(public.get_by_role('link', name=TITLE, exact=True)).to_have_count(0)

            page.goto(origin + '/admin/ingresar')
            page.locator('[name="password"]').fill(PASSWORD)
            page.get_by_role('button', name='Ingresar').click()
            expect(page.get_by_role('heading', name='Ofertas y actividad')).to_be_visible()
            no_horizontal_overflow(page)
            page.get_by_role('link', name=TITLE, exact=True).click()
            expect(page.get_by_role('heading', name='Revisar oferta')).to_be_visible()
            no_horizontal_overflow(page)
            acknowledgement = page.locator('[name="acknowledge"]')
            if acknowledgement.count():
                acknowledgement.check()
            page.get_by_role('button', name='Aprobar y publicar').click()
            expect(page.get_by_text('Aprobada', exact=True)).to_be_visible()
            assert rows(app, 'SELECT status FROM jobs')[0]['status'] == 'approved'

            public.goto(origin + '/')
            public.locator('[name="q"]').fill('atención')
            for name, value in {
                'location': 'Salta Capital', 'sector': 'Comercio',
                'modality': 'presencial', 'schedule': 'Jornada completa', 'days': '7',
            }.items():
                public.locator(f'[name="{name}"]').select_option(value)
            public.get_by_role('button', name='Buscar ofertas').click()
            expect(public.get_by_role('link', name=TITLE, exact=True)).to_be_visible()
            no_horizontal_overflow(public)
            public.locator('[name="modality"]').select_option('remota')
            public.get_by_role('button', name='Buscar ofertas').click()
            expect(public.get_by_role('link', name=TITLE, exact=True)).to_have_count(0)
            public.locator('[name="modality"]').select_option('presencial')
            public.get_by_role('button', name='Buscar ofertas').click()
            public.get_by_role('link', name=TITLE, exact=True).click()
            apply = public.get_by_role('link', name='Postularme')
            expect(apply).to_have_attribute('href', APPLICATION)
            with public.expect_popup() as popup:
                apply.click()
            popup.value.wait_for_load_state('domcontentloaded')
            expect(popup.value).to_have_url(APPLICATION)
            assert applications == [APPLICATION]
            expect(popup.value.get_by_text('PRUEBA: canal original simulado, sin envío.')).to_be_visible()
            popup.value.close()

            page.goto(origin + '/admin/automatizacion')
            expect(page.get_by_role('heading', name='Automatización', exact=True)).to_be_visible()
            no_horizontal_overflow(page)
            for _ in range(2):
                page.get_by_role('button', name='Comprobar vigencia').click()
                expect(page.get_by_role('status')).to_contain_text('Corrida registrada')
            runs = rows(app, 'SELECT task,status FROM task_runs')
            assert len(runs) == 2 and all(run == {'task': 'expire', 'status': 'succeeded'} for run in runs)
            assert len(rows(app, 'SELECT id FROM jobs')) == 1

            page.goto(f'{origin}/admin/ofertas/{job_id}')
            page.locator('[name="application_url"]').fill('https://example.test/contacto-cambiado')
            page.get_by_role('button', name='Guardar para revisión').click()
            expect(page.get_by_text('Pendiente de revisión', exact=True)).to_be_visible()
            assert rows(app, 'SELECT status FROM jobs')[0]['status'] == 'pending'
            assert public.goto(f'{origin}/ofertas/{job_id}').status == 404
            public.goto(origin + '/')
            expect(public.get_by_role('link', name=TITLE, exact=True)).to_have_count(0)
            assert not unexpected, f'La app intentó acceder a destinos externos: {unexpected}'
            print(f'APROBADO: Chromium {viewport["width"]}×{viewport["height"]}; circuito editorial y vigencia.')
        finally:
            public_context.close()
            context.close()


def check_access_helper(browser, target=None):
    """Archivo local, contraseña PRUEBA; nunca imprime ni captura los resultados."""
    import re
    target = target or (ROOT / 'instalacion/configurar-acceso.html').as_uri()
    context = browser.new_context(viewport={'width': 390, 'height': 844})
    unexpected = []
    context.route('**/*', lambda route: route.continue_() if route.request.url == target
                  else (unexpected.append(urlsplit(route.request.url).hostname), route.abort()))
    try:
        page = context.new_page()
        page.goto(target)
        assert page.evaluate('isSecureContext && Boolean(crypto.subtle)')
        assert page.locator('#results').is_hidden()
        assert all(page.locator(f'#{field}').input_value() == '' for field in ('secret', 'hash', 'cron'))
        page.locator('#password').fill(PASSWORD)
        page.locator('#confirmation').fill(PASSWORD + '-diferente')
        page.get_by_role('button', name='Generar configuración privada').click()
        expect(page.locator('#results')).to_be_hidden()
        expect(page.get_by_role('status')).to_contain_text('repetí la misma contraseña')
        outputs = []
        for _ in range(2):
            page.locator('#password').fill(PASSWORD)
            page.locator('#confirmation').fill(PASSWORD)
            page.get_by_role('button', name='Generar configuración privada').click()
            expect(page.locator('#results')).to_be_visible(timeout=15000)
            values = {field: page.locator(f'#{field}').input_value() for field in ('secret', 'hash', 'cron')}
            assert all(re.fullmatch(r'[0-9a-f]{64}', values[field]) for field in ('secret', 'cron'))
            assert re.fullmatch(r'pbkdf2:sha256:1000000\$[0-9a-f]{32}\$[0-9a-f]{64}', values['hash'])
            assert check_password_hash(values['hash'], PASSWORD)
            assert page.locator('#password').input_value() == page.locator('#confirmation').input_value() == ''
            assert values['secret'] != values['cron']
            outputs.append(values)
            no_horizontal_overflow(page)
        assert all(outputs[0][field] != outputs[1][field] for field in ('secret', 'hash', 'cron'))
        assert outputs[0]['hash'].split('$')[1] != outputs[1]['hash'].split('$')[1]
        assert page.evaluate("async () => { try { await fetch('https://example.test/bloqueado'); return false; } catch { return true; } }")
        assert not unexpected
        print('APROBADO: helper local, PBKDF2 compatible, claves distintas, sin red ni captura.')
    finally:
        context.close()


def check_public(browser):
    """Solo lectura, sin cookies/credenciales; una falla externa no invalida QA local."""
    for viewport in ({'width': 390, 'height': 844}, {'width': 1440, 'height': 1000}):
        context = browser.new_context(viewport=viewport, is_mobile=viewport['width'] < 600,
                                      has_touch=viewport['width'] < 600)
        try:
            page = context.new_page()
            response = page.goto('https://salta-emplea.vercel.app', timeout=20000)
            assert response.status == 200
            expect(page.get_by_text('Versión preliminar.', exact=True)).to_be_visible()
            assert 'Salta' in page.title()
            page.screenshot(path=str(CAPTURES / f'vercel-publica-{viewport["width"]}.png'), full_page=True)
            no_horizontal_overflow(page)
            print(f'WEB PÚBLICA {viewport["width"]}: HTTP 200, contenido preliminar y captura; no comprueba backend.')
        except Exception as error:
            print(f'WEB PÚBLICA {viewport["width"]} PENDIENTE: acceso/contenido no confirmado ({type(error).__name__}).')
        finally:
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-public', action='store_true', help='Agregar lectura pública opcional, sin secretos.')
    args = parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for viewport in ({'width': 390, 'height': 844}, {'width': 1440, 'height': 1000}):
                run_circuit(browser, viewport)
            check_access_helper(browser)
            if args.check_public:
                check_public(browser)
                check_access_helper(browser, 'https://salta-emplea.vercel.app/configurar-acceso')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
