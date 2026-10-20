"""Comprueba la portada en Chromium aislado: solo avisos PRUEBA y red simulada.

No consulta producción, carga .env, envía correo ni llama a Google. Las capturas
son evidencia de laboratorio; no miden usuarios reales ni indexación en Google.
"""

import argparse
import base64
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright

from salta_emplea import db, domain
from scripts.browser_check import isolated_server, no_horizontal_overflow, open_search_filters

APPLICATION = 'https://example.test/postularse/PRUEBA-portada'
TITLE = 'PRUEBA — Auxiliar de Administración'
LOCATION = 'San Ramón de la Nueva Orán'
SECTOR = 'Administración'
SCHEDULE = 'Jornada parcial'
WIDTHS = (360, 390, 768, 1024, 1440)
CANONICAL_ORIGIN = 'https://preview.example.test'
PREVIEW_FILES = ('portada-390.png', 'portada-1440.png')


def seed_jobs(app):
    """Cinco avisos ficticios; tres activos, un pendiente y uno cerrado."""
    connection = db.connect(app.config['DATABASE_TARGET'])
    ids = {}
    fixtures = (
        ('administration', TITLE, 'PRUEBA Árbol', LOCATION, SECTOR, 'presencial', SCHEDULE),
        ('commerce', 'PRUEBA — Atención en comercio', 'PRUEBA Comercio local',
         'Salta Capital', 'Comercio', 'presencial', 'Jornada completa'),
        ('remote', 'PRUEBA — Soporte remoto', 'PRUEBA Equipo remoto',
         None, 'Tecnología y soporte', 'remota', None),
        ('pending', 'PRUEBA — Aviso pendiente', 'PRUEBA Sin publicar',
         'Salta Capital', 'Comercio', 'presencial', 'Jornada completa'),
        ('closed', 'PRUEBA — Aviso cerrado', 'PRUEBA Cerrada',
         'Salta Capital', 'Administración', 'presencial', 'Jornada completa'),
    )
    try:
        for key, title, company, location, sector, modality, schedule in fixtures:
            data = {
                'title': title, 'company': company, 'location': location,
                'sector': sector, 'modality': modality, 'schedule': schedule,
                'description': 'PRUEBA: aviso ficticio exclusivo del laboratorio de portada. No postularse.',
                'requirements': 'PRUEBA: requisitos de la fuente ficticia, sin datos de candidatos.',
                'application_url': APPLICATION, 'source_name': 'PRUEBA propia de QA',
                'source_url': f'https://example.test/avisos/PRUEBA-{key}',
                'original_text': f'PRUEBA {key}: contenido ficticio, no publicable.',
            }
            if key == 'remote':
                data['uncertain_fields'] = ['residencia y horario remoto']
            job_id, _ = domain.create_job(connection, data, actor='administrador')
            ids[key] = job_id
            if key != 'pending':
                domain.transition_job(connection, job_id, 'approve', 'administrador', acknowledge=True)
            if key == 'closed':
                domain.transition_job(connection, job_id, 'expire', 'administrador')
    finally:
        connection.close()
    return ids


def assert_primary_controls(page, width):
    controls = [page.locator('input[name="q"]'), page.locator('select[name="location"]'),
                page.get_by_role('button', name='Buscar empleos', exact=True)]
    measurements = []
    for control in controls:
        expect(control).to_be_visible()
        box = control.bounding_box()
        assert box and box['height'] >= 44, f'Objetivo táctil menor a 44 px: {box}'
        assert box['x'] >= -1 and box['x'] + box['width'] <= width + 1, box
        font_size = control.evaluate('(node) => parseFloat(getComputedStyle(node).fontSize)')
        assert font_size >= 16, f'Campo/acción menor a 16 px: {font_size}'
        measurements.append({'height': round(box['height'], 2), 'font_px': font_size})
    return measurements


def contrast_samples(page):
    """Contraste de texto calculado sobre sus capas de fondo reales."""
    result = page.evaluate('''() => {
        const rgba = value => {
            const numbers = value.match(/[\\d.]+/g).map(Number);
            return [...numbers.slice(0, 3), numbers.length > 3 ? numbers[3] : 1];
        };
        const mix = (front, back) => front.slice(0, 3).map((v, i) =>
            v * front[3] + back[i] * (1 - front[3]));
        const background = node => {
            const stack = [];
            for (let item = node; item; item = item.parentElement) stack.push(item);
            let color = [255, 255, 255];
            for (const item of stack.reverse()) color = mix(rgba(getComputedStyle(item).backgroundColor), color);
            return color;
        };
        const luminance = rgb => rgb.map(v => v / 255).map(v =>
            v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
            .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
        const samples = [];
        for (const selector of ['.home-intro', '.search-reassurance', '.company',
                                '.badge-modality', '.main-nav a', '.search-primary button']) {
            const node = document.querySelector(selector);
            if (!node || !node.getClientRects().length) continue;
            const style = getComputedStyle(node), bg = background(node);
            const fg = mix(rgba(style.color), bg);
            const light = luminance(fg), dark = luminance(bg);
            const ratio = (Math.max(light, dark) + .05) / (Math.min(light, dark) + .05);
            const large = parseFloat(style.fontSize) >= 24 ||
                (parseFloat(style.fontSize) >= 18.66 && parseInt(style.fontWeight) >= 700);
            samples.push({selector, ratio: Math.round(ratio * 100) / 100,
                          minimum: large ? 3 : 4.5, color: style.color});
        }
        return samples;
    }''')
    assert result, 'No se obtuvieron muestras de contraste.'
    assert all(row['ratio'] >= row['minimum'] for row in result), result
    return result


def assert_keyboard(page):
    page.keyboard.press('Tab')
    skip = page.get_by_role('link', name='Ir al contenido', exact=True)
    expect(skip).to_be_focused()
    expect(skip).to_be_visible()
    button = page.get_by_role('button', name='Buscar empleos', exact=True)
    for _ in range(30):
        if button.evaluate('(node) => node === document.activeElement'):
            break
        page.keyboard.press('Tab')
    expect(button).to_be_focused()
    focus = button.evaluate('''node => {
        const style = getComputedStyle(node);
        return {outline: parseFloat(style.outlineWidth), shadow: style.boxShadow};
    }''')
    assert focus['outline'] > 0 or focus['shadow'] != 'none', 'La acción enfocada no tiene foco visible.'


def remove_filter(page, name, previous):
    candidates = page.locator('.active-filters a').evaluate_all('(nodes) => nodes.map(node => node.href)')
    chosen = None
    for target in candidates:
        query = parse_qs(urlsplit(target).query)
        if name not in query and all(query.get(key) == [value] for key, value in previous.items() if key != name):
            chosen = target
            break
    assert chosen, f'No hay enlace que quite solamente {name} y conserve los demás filtros.'
    link = None
    # El href puede ser relativo; localizar el mismo nodo por su URL resuelta.
    for candidate in page.locator('.active-filters a').all():
        if candidate.evaluate('(node) => node.href') == chosen:
            link = candidate
            break
    assert link is not None
    with page.expect_navigation() as navigation:
        link.click()
    assert navigation.value.status == 200
    query = parse_qs(urlsplit(page.url).query)
    assert name not in query
    assert all(query.get(key) == [value] for key, value in previous.items() if key != name)


def run_width(browser, width, capture_folder):
    viewport = {'width': width, 'height': 900 if width < 1024 else 1000}
    with isolated_server() as (app, origin):
        app.config['PUBLIC_BASE_URL'] = CANONICAL_ORIGIN
        ids = seed_jobs(app)
        context = browser.new_context(viewport=viewport, is_mobile=width < 600,
                                      has_touch=width < 600, service_workers='block',
                                      reduced_motion='reduce')
        unexpected, applications, server_errors = [], [], []

        def guard(route):
            url = route.request.url
            if url.startswith(origin + '/'):
                route.continue_()
            elif url == APPLICATION:
                applications.append(url)
                route.fulfill(status=200, content_type='text/html; charset=utf-8',
                              body='<h1>PRUEBA: destino simulado, no se envió una postulación.</h1>')
            else:
                unexpected.append(urlsplit(url).hostname)
                route.abort()

        context.route('**/*', guard)
        context.set_default_timeout(10000)
        context.set_default_navigation_timeout(15000)
        page = context.new_page()
        page.on('response', lambda response: server_errors.append(response.status) if response.status >= 500 else None)
        try:
            response = page.goto(origin + '/')
            assert response.status == 200
            expect(page.get_by_role('heading', level=1)).to_have_text('Encontrá trabajo en Salta.')
            assert page.title() == 'Trabajo en Salta y ofertas de empleo | Salta Emplea'
            expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', CANONICAL_ORIGIN + '/')
            expect(page.locator('.job-card')).to_have_count(3)
            expect(page.get_by_role('link', name='PRUEBA — Aviso pendiente', exact=True)).to_have_count(0)
            expect(page.get_by_role('link', name='PRUEBA — Aviso cerrado', exact=True)).to_have_count(0)
            expect(page.get_by_role('link', name='Crear mi alerta', exact=True)).to_have_count(0)
            no_horizontal_overflow(page)
            measurements = assert_primary_controls(page, width)
            contrasts = contrast_samples(page)
            page.screenshot(path=str(capture_folder / f'portada-{width}.png'), full_page=True)
            assert_keyboard(page)

            page.locator('[name="q"]').fill('arbol')
            page.locator('[name="location"]').select_option(LOCATION)
            open_search_filters(page)
            filters = {'q': 'arbol', 'location': LOCATION, 'sector': SECTOR,
                       'modality': 'presencial', 'schedule': SCHEDULE, 'days': '7'}
            for name, value in filters.items():
                if name not in ('q', 'location'):
                    page.locator(f'[name="{name}"]').select_option(value)
            with page.expect_navigation() as navigation:
                page.get_by_role('button', name='Buscar empleos', exact=True).click()
            assert navigation.value.status == 200
            expect(page.locator('.job-card')).to_have_count(1)
            expect(page.get_by_role('link', name=TITLE, exact=True)).to_be_visible()
            expect(page.locator('meta[name="robots"]')).to_have_attribute('content', 'noindex, follow')
            query = parse_qs(urlsplit(page.url).query)
            assert all(query.get(key) == [value] for key, value in filters.items())
            no_horizontal_overflow(page)
            remove_filter(page, 'sector', filters)
            expect(page.locator('select[name="sector"]')).to_have_value('')
            expect(page.locator('[name="q"]')).to_have_value('arbol')
            expect(page.locator('.job-card')).to_have_count(1)
            if width in (390, 1440):
                page.screenshot(path=str(capture_folder / f'filtros-{width}.png'), full_page=True)

            page.get_by_role('link', name=TITLE, exact=True).click()
            expect(page.get_by_role('heading', level=1)).to_have_text(TITLE)
            expect(page.locator('link[rel="canonical"]')).to_have_attribute(
                'href', f'{CANONICAL_ORIGIN}/ofertas/{ids["administration"]}')
            apply = page.get_by_role('link', name='Postularme', exact=True)
            expect(apply).to_have_attribute('href', APPLICATION)
            no_horizontal_overflow(page)
            with page.expect_popup() as popup:
                apply.click()
            popup.value.wait_for_load_state('domcontentloaded')
            expect(popup.value.get_by_role('heading', level=1)).to_contain_text('PRUEBA: destino simulado')
            assert applications == [APPLICATION]
            popup.value.close()
            assert page.goto(f'{origin}/ofertas/{ids["closed"]}').status == 404
            expect(page.get_by_role('link', name='Postularme', exact=True)).to_have_count(0)

            page.goto(origin + '/')
            guide_paths = ('/guias/cv-sin-experiencia', '/guias/como-postularse',
                           '/guias/ofertas-laborales-falsas')
            for path in guide_paths:
                expect(page.locator(f'#guias h3 a[href="{path}"]')).to_have_count(1)
                guide = context.new_page()
                assert guide.goto(origin + path).status == 200
                expect(guide.get_by_role('heading', level=1)).to_have_count(1)
                no_horizontal_overflow(guide)
                guide.close()

            page.locator('[name="q"]').fill('PRUEBA-sin-coincidencias-improbable')
            page.get_by_role('button', name='Buscar empleos', exact=True).click()
            expect(page.locator('.job-card')).to_have_count(0)
            expect(page.locator('.empty-state')).to_be_visible()
            no_horizontal_overflow(page)
            if width in (390, 1440):
                page.screenshot(path=str(capture_folder / f'sin-resultados-{width}.png'), full_page=True)
            assert page.goto(origin + '/?days=no-es-numero').status == 400
            no_horizontal_overflow(page)

            connection = db.connect(app.config['DATABASE_TARGET'])
            try:
                for key in ('administration', 'commerce', 'remote'):
                    domain.transition_job(connection, ids[key], 'archive', 'administrador')
                assert connection.execute('SELECT count(*) FROM outbox').fetchone()[0] == 0
            finally:
                connection.close()
            assert page.goto(origin + '/').status == 200
            expect(page.locator('.job-card')).to_have_count(0)
            expect(page.locator('.empty-state')).to_be_visible()
            expect(page.locator('.browse-link')).to_have_count(0)
            expect(page.get_by_role('link', name='Crear mi alerta', exact=True)).to_have_count(0)
            no_horizontal_overflow(page)
            if width in (390, 1440):
                page.screenshot(path=str(capture_folder / f'inventario-vacio-{width}.png'), full_page=True)
            assert not unexpected, f'Requests externos bloqueados: {unexpected}'
            assert not server_errors, f'Respuestas 5xx: {server_errors}'
            print(f'APROBADO: portada {width}px, búsqueda/filtros/acento/baja de filtro, ficha, '
                  'postulación sustituida, guías, vacío/cero resultados/error y cierre. Sin red externa.')
            return {'width': width, 'status': 'passed', 'controls': measurements,
                    'contrast': contrasts, 'application_mock_requests': len(applications),
                    'unexpected_external_requests': len(unexpected)}
        finally:
            context.close()


def emit_previews(capture_folder):
    """Exportación CLI optativa: solo dos capturas públicas con fixtures PRUEBA.

    No se exportan páginas administrativas, sesiones, claves ni datos reales.
    Los fragmentos permiten recuperar imágenes desde logs de CI cuando la
    máquina de revisión no puede iniciar Chromium. No es telemetría de la app.
    """
    for filename in PREVIEW_FILES:
        content = (capture_folder / filename).read_bytes()
        if not content.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('La captura de revisión no es un PNG válido.')
        encoded = base64.b64encode(content).decode('ascii')
        chunks = [encoded[offset:offset + 8000] for offset in range(0, len(encoded), 8000)]
        for index, chunk in enumerate(chunks, 1):
            print(f'SALTA_PREVIEW|{filename}|{index}|{len(chunks)}|{chunk}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable-path', help='Chromium ya instalado; evita descargar un navegador.')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs' / 'portada',
                        help='Carpeta de resultados y capturas de laboratorio.')
    parser.add_argument('--emit-preview', action='store_true',
                        help='Emitir dos PNG de datos PRUEBA en fragmentos base64 al aprobar el circuito.')
    args = parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    captures = args.output / 'capturas'
    captures.mkdir(parents=True, exist_ok=True)
    result = {'status': 'running', 'environment': 'isolated_local_PRUEBA',
              'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'production_requested': False, 'widths': []}
    try:
        with sync_playwright() as playwright:
            options = {'executable_path': args.executable_path} if args.executable_path else {}
            browser = playwright.chromium.launch(**options)
            result['browser_version'] = browser.version
            try:
                for width in WIDTHS:
                    result['widths'].append(run_width(browser, width, captures))
            finally:
                browser.close()
        result['status'] = 'passed'
    except Exception as exc:
        result['status'] = 'failed'
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        (args.output / 'resultados-navegador.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # El estado final se imprime incluso si una comprobación falla. No se
        # emiten capturas anteriores de otro intento cuando el circuito falla.
        print('SALTA_HOMEPAGE_RESULT|' + json.dumps({
            'status': result['status'],
            'environment': result['environment'],
            'widths_checked': [item['width'] for item in result['widths']],
            'production_requested': False,
        }, ensure_ascii=False), flush=True)
        if args.emit_preview and result['status'] == 'passed':
            emit_previews(captures)


if __name__ == '__main__':
    main()
