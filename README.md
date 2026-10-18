# Salta Emplea — nombre provisional

Web de avisos laborales para Salta y oportunidades remotas compatibles. Servicio gratuito, sin cuentas para candidatos, CV ni pagos. HTML liviano y Flask; PostgreSQL para Vercel y SQLite para desarrollo local. Los avisos entran pendientes y requieren aprobación del administrador; editar una publicación revoca su aprobación.

## Página pública preliminar

[Abrir Salta Emplea](https://salta-emplea.vercel.app). Vercel publica la carpeta `vista-previa/` desde este [repositorio de GitHub](https://github.com/Matifernandezar/salta-emplea). El inicio, cinco páginas informativas y los estilos responden HTTP 200 sin iniciar sesión, comprobado el 18/10/2026. La página está identificada como preliminar y comienza sin ofertas ficticias.

La búsqueda, el envío de avisos, el panel y las alertas todavía no están habilitados en esta publicación estática. Sus pantallas indican que estarán disponibles en una próxima etapa. No recibe postulaciones ni suscripciones, y no ejecuta tareas automáticas.

Para regenerar sus archivos desde las plantillas: `.venv/bin/python scripts/build_preview.py`. Revisar los cambios generados y subirlos a main para actualizar la página.

## Aplicación completa preparada para Vercel

El backend incluye PostgreSQL, imágenes privadas dentro de la base, migraciones explícitas, entrada WSGI, estáticos y cron autenticado. El panel `/admin/automatizacion` permite comprobar configuración, revisar corridas y ejecutar lotes de recopilación, vigencia y correo. Ninguna tarea aprueba ofertas. La revisión editorial permite comparar los campos de las versiones recibidas con los datos preparados.

La suite ampliada pasa 211 pruebas locales; otras seis requieren PostgreSQL real. La versión anterior había pasado las 144 pruebas con PostgreSQL 17. Ver [validación por fase](docs/VALIDACION.md) para distinguir cada ejecución. Falta conectar la base de producción y verificar allí el circuito editorial, las tareas y los servicios externos. Ver [guía de Vercel](docs/VERCEL.md) y [precios verificados](docs/VERCEL-COSTOS.md). No usar SQLite en Vercel: el arranque lo rechaza.

Antes de activar el backend, ejecutar `.venv/bin/python -m salta_emplea.cli check-production --with-crons`. El diagnóstico funciona con configuración incompleta y muestra nombres y estados, sin secretos. Agregar `--check-database` únicamente al comprobar explícitamente el acceso y esquema de la base: consulta en modo de solo lectura y no aplica migraciones ni envía correo.

## Instalación local

Requiere Python 3.12 o posterior y Linux para el bloqueo del trabajador.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m salta_emplea.cli secret-key
.venv/bin/python -m salta_emplea.cli password-hash
```

Copiar las salidas directamente a los campos correspondientes de `.env`, en un editor privado. No subirlas a Git ni compartirlas. El generador pide la contraseña de forma oculta. Proteger `.env` con permisos de lectura del propietario. El lector de configuración no ejecuta ni interpola sus valores. No hay contraseña predeterminada.

```bash
.venv/bin/python -m salta_emplea.cli init
.venv/bin/flask --app wsgi run --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000` y `/admin`. El modo de desarrollo no envía correos. La base comienza vacía. Los datos de prueba se crean únicamente en directorios temporales durante las pruebas.

## Variables

El archivo [.env.example](.env.example) documenta solamente los nombres, sin secretos. `SECRET_KEY` firma sesiones y enlaces; conservarla estable y respaldarla de forma privada. `ADMIN_PASSWORD_HASH` habilita el acceso del administrador. `DATABASE_URL` selecciona PostgreSQL; sin ella, `DATABASE_PATH` y `UPLOAD_DIR` se usan para almacenamiento local. `CRON_SECRET` protege las tareas de Vercel. `PUBLIC_BASE_URL` debe ser el origen HTTPS público del sitio. `APP_ENV` controla las comprobaciones de producción. `RESEND_API_KEY` y `MAIL_FROM` habilitan el proveedor de correo. `TRUST_PROXY` solo se activa detrás de un único proxy controlado que reemplace las cabeceras de origen. La aplicación no confía en cabeceras de proxy por defecto.

## Alternativa: producción en servidor propio

Consultar [arquitectura](docs/ARQUITECTURA.md), [costos](docs/COSTOS.md), [fuentes](docs/FUENTES.md) y [operación](docs/OPERACION.md). Esta alternativa no está desplegada. La publicación pública actual sirve únicamente la vista preliminar estática en Vercel; no se contrataron servicios de pago.

1. Elegir servidor Linux con disco persistente y copias de seguridad. Validar dominio y nombre antes de usarlos como marca disponible.
2. Configurar el entorno de producción, hash y clave fuerte; base pública HTTPS. La aplicación falla al iniciar si faltan estos datos. El correo puede permanecer deshabilitado.
3. Ejecutar `docker compose up -d --build`. El puerto queda limitado a loopback. Poner Caddy o Nginx delante para HTTPS y redirigir HTTP a HTTPS. No exponer Gunicorn directamente. Si se habilita confianza en proxy, este debe sobrescribir las cabeceras enviadas por visitantes.
4. Programar cada 15 minutos `docker compose exec -T web python -m salta_emplea.cli tasks`, desde el directorio del proyecto. Usar cron del servidor y supervisar sus resultados. El trabajador usa un bloqueo de archivo compartido, transacciones y claves únicas.
5. Completar responsable y contacto en privacidad y condiciones, validar fuentes y probar el circuito real de correo antes de anunciar el lanzamiento. No habilitar fuentes sin revisar condiciones. Los anuncios, fuentes y suscriptores iniciales están vacíos.

El Dockerfile y Compose están preparados pero su ejecución en un servidor de producción todavía requiere validación. No usar almacenamiento efímero ni varias réplicas con SQLite. El modo producción exige cookies seguras: acceder por HTTPS.

## Pruebas

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q salta_emplea
```

Las pruebas incluyen edición/reaprobación, duplicados, vencimientos, enlaces, permisos, filtros, doble consentimiento y baja, colas y reejecuciones. Los adaptadores de correo se prueban con respuestas simuladas explícitas; esto no demuestra entrega real. Ver [validación por fase](docs/VALIDACION.md).

## Operación y recuperación

```bash
.venv/bin/python -m salta_emplea.cli tasks --only expire
.venv/bin/python -m salta_emplea.cli tasks --only collect
.venv/bin/python -m salta_emplea.cli tasks --only mail
.venv/bin/python -m salta_emplea.cli backup backups/respaldo-nuevo.sqlite3
```

Los comandos de tareas ejecutan una corrida, no instalan cron. Para restaurar: detener web y trabajador, preservar una copia del estado actual, reemplazar la base por el respaldo validado y retirar archivos WAL/SHM de la base detenida; restaurar también `uploads`, reiniciar y comprobar `/salud` y el panel. Probar la restauración en una instancia separada antes de depender del respaldo. Consultar [guía de administración](docs/OPERACION.md).
