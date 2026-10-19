# Salta Emplea — nombre provisional

Web de avisos laborales para Salta y oportunidades remotas compatibles. Servicio gratuito, sin cuentas para candidatos, CV ni pagos. HTML liviano y Flask; PostgreSQL para Vercel y SQLite para desarrollo local. Los avisos entran pendientes y requieren aprobación del administrador; editar una publicación revoca su aprobación.

## Sitio publicado

[Abrir Salta Emplea](https://saltaemplea.com) · [Ingresar al panel](https://saltaemplea.com/admin/ingresar) · [Guía de administración](docs/OPERACION.md).

Desde el 18/10/2026 Vercel ejecuta la aplicación Flask desde la raíz de este [repositorio](https://github.com/Matifernandezar/salta-emplea), con PostgreSQL de Neon. El build aplicó migraciones sin datos de prueba y `/salud` confirmó una conexión SQL real. Están habilitados el buscador, los filtros, los aportes pendientes y el acceso privado al panel. La base comienza sin ofertas publicadas; ninguna tarea aprueba avisos.

El titular configuró sus claves directamente como Secret en Production. No se leyeron sus valores. Para ingresar se usa la contraseña elegida en el configurador privado. La prueba de ingreso con esa contraseña y la primera aprobación real quedan a cargo del titular: las verificaciones automáticas en producción no publican avisos ni acceden a su sesión.

## Automatización y verificación

El panel `/admin/automatizacion` permite comprobar configuración, revisar corridas y ejecutar lotes manuales de recopilación, vigencia y correo. La revisión editorial compara versiones recibidas con los datos preparados. Cada fuente requiere revisión de condiciones y autorización explícita. Jobicy fue autorizado por el titular y completó una primera consulta real en producción: 100 avisos recibidos y cinco incorporados pendientes el 19/10/2026. Los detalles y límites están en VALIDACION.md.

La configuración principal prepara recopilación, vigencia y correo una vez por día, sin cambiar planes. Se observó la primera recopilación persistida de Jobicy; la configuración diaria y los resultados se documentan por separado en VALIDACION.md. La alternativa frecuente permanece en `deploy/vercel-programado.json`. El titular autorizó Jobicy el 19/10; su registro inicial es idempotente y no vuelve a activar fuentes pausadas. El correo sigue deshabilitado hasta configurar y probar proveedor/remitente. WhatsApp y redes preparan enlaces manuales para ofertas aprobadas; no hay publicación automática conectada.

Los resultados actuales de PostgreSQL y Chromium se registran en la [validación por fase](docs/VALIDACION.md), con enlaces a las corridas y sus límites. El navegador comprueba el circuito editorial e imágenes con proveedor OCR sustituido en bases temporales y consulta producción solo en lectura, en celular y escritorio. No demuestra una lectura real con Google. Ver [QA de navegador](docs/QA-NAVEGADOR.md), [Vercel](docs/VERCEL.md) y [presupuesto vigente](docs/COSTOS.md).

Preparación operativa del 19/10: cuotas y reservas de correo, webhook firmado de rebotes/supresiones, diagnóstico privado de corridas y cola, identidad legal configurable, metadatos y sitemap. El dominio web saltaemplea.com tiene DNS y HTTPS verificados. El responsable es Matías Fernández, con su perfil de LinkedIn como contacto y sin teléfono ni correo personal públicos. El correo de alertas sigue pendiente de cuenta, verificación DNS del remitente y prueba autorizada; la conexión web del dominio no verifica el envío de correo. La [recuperación PostgreSQL](docs/RESPALDOS.md) y la [retención manual](docs/RETENCION.md) tienen comandos específicos; no instalan backups externos ni borrados de producción.

El diagnóstico `python -m salta_emplea.cli check-production --with-crons` muestra nombres y estados, sin valores secretos. `--check-database` agrega consultas de solo lectura de conexión y esquema; no migra ni envía correo. No usar SQLite en Vercel: el arranque lo rechaza.

La carpeta `vista-previa/` conserva la publicación estática anterior, pero ya no se despliega. El [generador privado descargable](docs/CONFIGURAR-ACCESO.md) sigue disponible en el repositorio para cambios coordinados de acceso.

## Fuentes elegidas y lectura de imágenes

Instagram **@empleosalta12**, Computrabajo y LinkedIn figuran como referencias preparadas en Fuentes, con acceso automático pendiente. Registrarlas no conecta sus publicaciones ni concede permiso de reutilización. Ver [estado y condiciones](docs/FUENTES-ELEGIDAS.md).

Al incorporar texto pegado se preparan campos con etiquetas explícitas, sin proveedor externo ni publicación. Las imágenes iguales se reconocen por la huella de una copia saneada; quedan privadas para revisión. El módulo opcional de lectura usa Google Cloud Vision únicamente con configuración completa, consentimiento para esa imagen y cupo disponible. Conserva texto y evidencia, completa campos vacíos y nunca aprueba ni reemplaza correcciones concurrentes. Sueldos y fechas requieren revisión manual.

La lectura externa está **pausada por decisión del titular desde el 19/10**: se deshabilitó `OCR_ENABLED` y se redesplegó sin leer ni retirar la clave, el cupo de 999 ni el historial. El formulario público ya no ofrece consentimiento de envío a Google. La primera prueba anterior fue rechazada y no hay lectura real exitosa. El ensayo [OCR sin API de pago](docs/OCR-SIN-API.md) encontró errores de tildes y orden de lectura; permanece la transcripción manual. La tarea `extract` no consulta Google mientras esté pausada y no conecta las tres fuentes.

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

Consultar [arquitectura](docs/ARQUITECTURA.md), [costos](docs/COSTOS.md), [fuentes](docs/FUENTES.md) y [operación](docs/OPERACION.md). Esta alternativa no está desplegada. La publicación actual usa Flask y Neon en Vercel. No se contrató ni cambió ningún plan durante la activación.

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

GitHub Actions ejecuta un [circuito real en Chromium](docs/QA-NAVEGADOR.md) para celular y escritorio, y una [comprobación aislada de Jobicy](docs/FUENTES.md). Son verificaciones separadas: consultar el resultado de cada corrida antes de afirmar que pasaron. La comprobación de fuente limita la frecuencia, no publica avisos y no habilita producción. El navegador conserva solo capturas públicas, sin sesiones ni datos del panel.

## Operación y recuperación

```bash
.venv/bin/python -m salta_emplea.cli tasks --only expire
.venv/bin/python -m salta_emplea.cli tasks --only collect
.venv/bin/python -m salta_emplea.cli tasks --only mail
.venv/bin/python -m salta_emplea.cli backup backups/respaldo-nuevo.sqlite3
```

Los comandos de tareas ejecutan una corrida, no instalan cron. Para restaurar: detener web y trabajador, preservar una copia del estado actual, reemplazar la base por el respaldo validado y retirar archivos WAL/SHM de la base detenida; restaurar también `uploads`, reiniciar y comprobar `/salud` y el panel. Probar la restauración en una instancia separada antes de depender del respaldo. Consultar [guía de administración](docs/OPERACION.md).
