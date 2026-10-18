# GitHub y Vercel

Actualización: 18/10/2026. La [página preliminar](https://salta-emplea.vercel.app) está publicada en producción y accesible sin iniciar sesión. La aplicación Flask con PostgreSQL se conserva en el repositorio, pendiente de conectar y verificar en producción. SQLite se usa únicamente para trabajar localmente.

## Publicación actual

- Proyecto Vercel: `salta-emplea`, equipo `matias-projects-2dbf9656`.
- Repositorio conectado: `Matifernandezar/salta-emplea`, rama de producción `main`.
- Root Directory: `vista-previa`. Framework: Other; sitio HTML y CSS estático.
- URL pública: https://salta-emplea.vercel.app.
- Verificación pública: inicio, alertas, publicar, administración, privacidad, condiciones y CSS devuelven HTTP 200 sin credenciales. La navegación y el contenido preliminar se comprobaron por HTTP; no se obtuvo una comprobación visual en navegador.

La vista preliminar no requiere base ni secretos. No incluye ofertas ficticias, formularios activos, suscripciones ni tareas. El panel publicado es una página informativa, no el administrador del backend. Los enlaces de funciones pendientes explican su estado. `scripts/build_preview.py` genera los archivos versionados desde las plantillas, usando una base temporal vacía y servicios deshabilitados. Para actualizar el sitio, regenerar, revisar y subir los archivos a main.

La configuración de la raíz del repositorio corresponde al backend futuro; el despliegue estático utiliza `vista-previa/vercel.json`. No cambiar Root Directory hasta configurar y probar las dependencias siguientes.

## Estado de acceso

El titular creó [Matifernandezar/salta-emplea](https://github.com/Matifernandezar/salta-emplea). El repositorio se creó público y se conservó esa visibilidad. El código y los commits en español se subieron a main, sin secretos, bases ni imágenes privadas. La vinculación con Vercel y la publicación estática están verificadas. No se modificó otro repositorio.

El titular vinculó Neon el 18/10/2026. La consulta de metadatos confirma `DATABASE_URL` y otras variables de conexión como Secret. Se limitaron a Production para que los despliegues de prueba no reciban acceso a la base real. También están configurados `PUBLIC_BASE_URL` y `APP_ENV`. No se leyeron ni mostraron valores secretos. Esto confirma configuración presente, no una conexión SQL comprobada ni una migración ejecutada.

Faltan las claves de sesión, administrador y tareas. El [configurador local](CONFIGURAR-ACCESO.md) permite que el titular elija su contraseña y genere los valores dentro de su navegador, para guardarlos directamente como Secret en Vercel. El backend continúa sin activarse hasta completar la configuración y verificar el despliegue.

## Configuración preparada para el backend

- `.python-version` fija Python 3.12; `wsgi.py` exporta la aplicación Flask.
- `vercel.json` prepara la activación inicial del circuito editorial manual, sin programaciones. Los botones privados de Automatización siguen disponibles cuando se active el backend. `deploy/vercel-programado.json` conserva la propuesta de cron por hora, cada seis horas y cada quince minutos, pendiente de verificar plan y costos antes de habilitarla. No se contrató ni cambió ningún plan.
- `scripts/prepare_vercel.py` copia el CSS a `public/static` y aplica migraciones PostgreSQL vacías e idempotentes. Requiere conexión configurada antes del build.
- `DATABASE_URL` selecciona PostgreSQL y desactiva la creación de archivos locales. En Vercel es obligatoria. Nunca usar un archivo bajo `/tmp` como base permanente.
- Las imágenes se redecodifican y guardan en PostgreSQL; la ruta de descarga sigue siendo privada. Las copias de PostgreSQL deben incluir esa tabla.
- `CRON_SECRET` se compara con Authorization Bearer; no alcanza con conocer la URL de una tarea. Nunca contiene instrucciones para aprobar ofertas.

## Próxima etapa: activar la aplicación completa

1. Conservar el repositorio y el proyecto ya vinculados. La configuración de CI ejecuta pruebas sin secretos de producción. Revisar que no se incluyan `.env`, bases, imágenes privadas ni credenciales.
2. Mantener publicada la vista preliminar mientras se preparan las dependencias del backend. No indicar como activas las funciones pendientes.
3. Preparar un despliegue de prueba de Flask con la raíz del repositorio y la configuración versionada, usando una base exclusiva de pruebas. Cambiar la raíz del proyecto público únicamente después de verificar el circuito completo y configurar producción.
4. Conectar PostgreSQL, preferentemente mediante la integración Neon del proyecto. Usar una base exclusiva. No compartir producción con previews o pull requests. El plan gratuito tiene límites y no reemplaza una política de recuperación; ver costos antes de contratar.
5. Configurar en Production los nombres de `.env.example` que correspondan: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, `PUBLIC_BASE_URL`, `APP_ENV` y `CRON_SECRET`. Generar clave/hash con el CLI en un entorno privado; no pegarlos en el chat ni en Git. El origen público puede derivarse de `VERCEL_PROJECT_PRODUCTION_URL`, pero conviene fijarlo al dominio definitivo. El correo puede permanecer sin configurar.
6. Ejecutar `python -m salta_emplea.cli check-production --with-crons` en el entorno configurado. No abre conexiones ni muestra valores. Después de aplicar la migración por separado, agregar `--check-database` para comprobar acceso y tablas en modo de solo lectura. Desplegar, revisar build y registros, y comprobar `/salud`, CSS, buscador, panel, permisos y persistencia entre peticiones. Hacer la primera prueba editorial con un aviso privado claramente identificado, sin publicarlo en producción hasta completar la revisión. Retirar los datos de prueba antes del lanzamiento.
7. Probar cada cron con su autorización y comprobar las filas resultantes. El panel `/admin/automatizacion` permite iniciar lotes manuales y consultar corridas y evidencia de llamadas autenticadas. Esto no instala el programador ni certifica el proveedor de correo. Fuentes y correo siguen deshabilitados hasta verificar sus servicios reales; no enviar alertas de prueba a suscriptores públicos.

## Validación y recuperación

La suite local no necesita servicios externos. Las integraciones PostgreSQL se activan con `POSTGRES_TEST_URL` y crean un esquema aleatorio que eliminan al terminar; jamás usar una credencial de producción. La CI usa un PostgreSQL de pruebas separado. Los casos cubren transacciones, deduplicación concurrente, leases, persistencia privada y el circuito editorial.

Con PostgreSQL usar `pg_dump` o los respaldos del proveedor; el CLI no intenta respaldarlo con la API de SQLite. Probar recuperación en una base separada. Las migraciones futuras deben ser aditivas y versionadas; un rollback del código no revierte la base.

No se guardan valores de secretos en esta guía. Un bloqueo de permisos requiere intervención del titular; repetir una llamada rechazada no concede acceso.
