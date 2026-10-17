# GitHub y Vercel

Actualización: 17/10/2026. Código preparado para Flask sobre Vercel con PostgreSQL persistente. SQLite se conserva para trabajar localmente. No se debe confundir esta preparación con un despliegue verificado.

## Estado de acceso

El titular creó [Matifernandezar/salta-emplea](https://github.com/Matifernandezar/salta-emplea). El repositorio se creó público y se conservó esa visibilidad. El código y los cinco commits iniciales en español ya se subieron a main, sin secretos, bases ni imágenes. El bloqueo previo de createRepository quedó resuelto por esa creación manual. No se modificó otro repositorio.

Vercel identifica el equipo `matias-projects-2dbf9656`. La consulta inicial de integraciones de almacenamiento recibió **403 forbidden**. No hay una credencial PostgreSQL de producción configurada ni un token de CLI Vercel; no se reutilizaron secretos de otras aplicaciones. La vinculación del proyecto y la conexión persistente se verifican por separado.

## Configuración preparada

- `.python-version` fija Python 3.12; `wsgi.py` exporta la aplicación Flask.
- `vercel.json` prepara cron de vencimientos cada hora, recopilación cada seis horas y correo cada quince minutos. Consultar el plan necesario en VERCEL-COSTOS.md. Los cron solo quedan activos cuando existe despliegue de producción.
- `scripts/prepare_vercel.py` copia el CSS a `public/static` y aplica migraciones PostgreSQL vacías e idempotentes. Requiere conexión configurada antes del build.
- `DATABASE_URL` selecciona PostgreSQL y desactiva la creación de archivos locales. En Vercel es obligatoria. Nunca usar un archivo bajo `/tmp` como base permanente.
- Las imágenes se redecodifican y guardan en PostgreSQL; la ruta de descarga sigue siendo privada. Las copias de PostgreSQL deben incluir esa tabla.
- `CRON_SECRET` se compara con Authorization Bearer; no alcanza con conocer la URL de una tarea. Nunca contiene instrucciones para aprobar ofertas.

## Pasos de publicación

1. Crear un repositorio privado `salta-emplea` en la cuenta seleccionada, o proporcionar uno nuevo y vacío autorizado. Inicializarlo con README si se va a subir mediante la API de archivos. Con CLI Git se puede subir directamente el historial local.
2. Subir la rama main con los commits en español. La configuración de CI ejecuta pruebas sin secretos de producción. Revisar archivos y confirmar que no se incluyan `.env`, bases, imágenes ni credenciales.
3. Importar ese repositorio en el equipo Vercel seleccionado. Usar Flask, raíz del repositorio y la configuración versionada. No reemplazar un proyecto existente de otro producto.
4. Conectar PostgreSQL, preferentemente mediante la integración Neon del proyecto. Usar una base exclusiva. No compartir producción con previews o pull requests. El plan gratuito tiene límites y no reemplaza una política de recuperación; ver costos antes de contratar.
5. Configurar en Production los nombres de `.env.example` que correspondan: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, `PUBLIC_BASE_URL`, `APP_ENV` y `CRON_SECRET`. Generar clave/hash con el CLI en un entorno privado; no pegarlos en el chat ni en Git. El origen público puede derivarse de `VERCEL_PROJECT_PRODUCTION_URL`, pero conviene fijarlo al dominio definitivo. El correo puede permanecer sin configurar.
6. Desplegar, revisar build y registros, y comprobar `/salud`, CSS, buscador, panel, permisos y persistencia entre peticiones. Hacer la primera prueba editorial con un aviso privado claramente identificado, sin publicarlo en producción hasta completar la revisión. Retirar los datos de prueba antes del lanzamiento.
7. Probar cada cron con su autorización y comprobar las filas resultantes. Fuentes y correo siguen deshabilitados hasta verificar sus servicios reales; no enviar alertas de prueba a suscriptores públicos.

## Validación y recuperación

La suite local no necesita servicios externos. Las integraciones PostgreSQL se activan con `POSTGRES_TEST_URL` y crean un esquema aleatorio que eliminan al terminar; jamás usar una credencial de producción. La CI usa un PostgreSQL de pruebas separado. Los casos cubren transacciones, deduplicación concurrente, leases, persistencia privada y el circuito editorial.

Con PostgreSQL usar `pg_dump` o los respaldos del proveedor; el CLI no intenta respaldarlo con la API de SQLite. Probar recuperación en una base separada. Las migraciones futuras deben ser aditivas y versionadas; un rollback del código no revierte la base.

No se guardan valores de secretos en esta guía. Un bloqueo de permisos requiere intervención del titular; repetir una llamada rechazada no concede acceso.
