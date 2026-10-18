"""Generar una página preliminar pública sin servicios ni datos ficticios."""
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from flask import render_template
from salta_emplea import create_app


def main():
    destination = ROOT / 'vista-previa'
    (destination / 'static').mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'salta_emplea/static/style.css', destination / 'static/style.css')
    with TemporaryDirectory(prefix='salta-preview-') as temporary:
        app = create_app({
            'TESTING': True, 'SERVERLESS': False, 'APP_ENV': 'development',
            'SECRET_KEY': 'solo-render-estatico-no-existe-servidor-ni-sesiones',
            'ADMIN_PASSWORD_HASH': '', 'DATABASE_URL': '',
            'DATABASE_PATH': str(Path(temporary) / 'preview.sqlite3'),
            'UPLOAD_DIR': str(Path(temporary) / 'uploads'),
            'PUBLIC_BASE_URL': '', 'RESEND_API_KEY': '', 'MAIL_FROM': '',
        })
        banner = '<div class="notice preview-banner" role="note"><div class="container"><strong>Versión preliminar.</strong> Estamos preparando las primeras ofertas. Las alertas y el envío de avisos estarán disponibles en la próxima etapa.</div></div>'

        def save(path, html):
            html = html.replace('<form class="search-panel" method="get" action="/">', '<div class="search-panel" aria-label="Buscador disponible próximamente">').replace('</form>', '</div>')
            html = html.replace('<input ', '<input disabled ').replace('<select ', '<select disabled ').replace('<button ', '<button disabled ')
            html = html.replace('Buscar ofertas <span', 'Próximamente <span')
            html = html.replace('Las ofertas remotas deben aceptar postulantes residentes en Salta.', 'El buscador se habilitará al publicar las primeras ofertas.')
            html = html.replace('<main id="contenido">', '<main id="contenido">' + banner)
            html = html.replace('Recibir alertas', 'Alertas · próximamente').replace('Compartir una oferta', 'Publicar · próximamente')
            html = html.replace('Crear mi alerta', 'Conocer las alertas').replace('Avisame cuando haya oportunidades', 'Ver próximas funciones')
            html = html.replace('Suscripción voluntaria y baja sencilla.', 'Disponible en la próxima etapa, con confirmación y baja sencilla.')
            html = html.replace('Panel de administración', 'Administración · próximamente')
            html = html.replace('Aportar una oferta', 'Aportar · próximamente').replace('Compartí el enlace, el texto o una imagen. La revisamos antes de publicarla.', 'Pronto podrás compartir enlaces, textos e imágenes para su revisión.')
            html = html.replace('Para pedir una corrección o el retiro de un aviso, usá “Reportar un problema” en la oferta.', 'Cada oferta contará con una opción para reportar errores o solicitar su retiro.')
            output = destination / path / 'index.html' if path else destination / 'index.html'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('\n'.join(line.rstrip() for line in html.splitlines()) + '\n', encoding='utf-8')

        save('', app.test_client().get('/').get_data(as_text=True))
        pages = {
            'alertas': ('Alertas de empleo, próximamente', 'Estamos preparando las alertas por correo. Podrás elegir localidad, rubro, modalidad y frecuencia, confirmar tu dirección y darte de baja fácilmente. Esta versión preliminar no solicita ni guarda correos.'),
            'publicar': ('Las primeras oportunidades empiezan acá', 'Estamos preparando la recepción de ofertas de empresas, comercios y la comunidad. Cada aviso será revisado antes de publicarse. En esta versión preliminar todavía no se reciben avisos ni archivos. No solicitamos CV.'),
            'admin': ('Administración, próximamente', 'El espacio de revisión de ofertas estará disponible en la siguiente etapa. Esta página es una presentación preliminar del sitio.'),
            'privacidad': ('Privacidad de esta versión preliminar', 'Esta versión no recibe formularios, correos, CV ni archivos. No incluye publicidad ni herramientas de seguimiento de audiencia. El proveedor de alojamiento puede procesar registros técnicos para servir y proteger el sitio. Antes de habilitar suscripciones y aportes se publicarán el responsable, el contacto y la política correspondiente.'),
            'condiciones': ('Sobre Salta Emplea', 'Salta Emplea es un nombre provisional para un punto de encuentro laboral en toda la provincia y empleos remotos accesibles desde Salta. Esta es una versión preliminar, todavía sin ofertas publicadas. El futuro servicio centralizará avisos de terceros y no garantizará contratación. La postulación se realizará por el canal original. El nombre y el dominio todavía requieren verificación.'),
        }
        for path, (title, message) in pages.items():
            with app.test_request_context('/' + path):
                save(path, render_template('message.html', title=title, message=message))
    with (destination / 'static/style.css').open('a') as output:
        output.write('\n.preview-banner{margin:0;border-radius:0;border-width:0 0 1px;font-size:.8rem;padding:12px 0}.preview-banner .container{max-width:1160px}.search-panel :disabled{cursor:default}.search-panel button:disabled{opacity:.7}\n')
    helper = destination / 'configurar-acceso'
    helper.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'instalacion/configurar-acceso.html', helper / 'index.html')
    print('Vista preliminar generada: 6 páginas y un configurador local, sin formularios de envío.')


if __name__ == '__main__':
    main()
