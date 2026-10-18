# GitHub y Vercel

Actualización: 18/10/2026. [Salta Emplea](https://salta-emplea.vercel.app) ejecuta Flask con PostgreSQL de Neon. La publicación estática anterior se conserva en Git, pero ya no es la raíz desplegada.

## Configuración activa

- Proyecto Vercel: `salta-emplea`, equipo `matias-projects-2dbf9656`.
- Repositorio público: `Matifernandezar/salta-emplea`, rama de producción `main`.
- Root Directory: raíz del repositorio, sin subdirectorio. Framework: Flask.
- Build Command: `python scripts/prepare_vercel.py`; sin directorio de salida personalizado.
- `.python-version`: Python 3.12. `wsgi.py` exporta la aplicación.
- URL pública: https://salta-emplea.vercel.app. Panel: `/admin/ingresar`.
- `vercel.json` no programa tareas. `deploy/vercel-programado.json` es una propuesta pendiente de habilitación y validación de plan/costos.

El despliegue inicial del backend `dpl_BoajdyPMNqsY8WbxhcNuMypSrB3w`, commit `35ef8f2`, terminó READY. El registro de build confirmó migraciones PostgreSQL aplicadas sin datos de prueba. Una petición real a `/salud` devolvió HTTP 200 y `{"status":"ok"}`, que implica una consulta SQL correcta. Portada, aportes, alertas e ingreso respondieron HTTP 200; cron sin credencial respondió 401. Los resultados posteriores de navegador se registran en VALIDACION.md.

## Variables y acceso

La conexión Neon y los nombres `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, `CRON_SECRET`, `PUBLIC_BASE_URL` y `APP_ENV` figuran en Production. Las claves privadas y la conexión son Secret; se verificaron únicamente sus metadatos, sin leer valores. El titular eligió la contraseña y guardó el hash con el [generador privado](CONFIGURAR-ACCESO.md).

Las variables de Neon se limitaron a Production. Los previews y PRs no reciben acceso a esa base. Para desplegar un preview funcional hay que configurar otra base y claves exclusivas de pruebas; no ampliar el alcance de las credenciales reales. El arranque en Vercel rechaza SQLite efímero y claves incompletas.

La contraseña del titular no se conoce ni se recupera desde Vercel. El ingreso positivo con esa contraseña y la primera oferta real deben comprobarse por el titular. La CI usa credenciales ficticias y bases temporales para probar aprobación, permisos y cambios de versión.

## Qué está habilitado

Buscador y filtros, aporte de enlace/texto/imagen pendiente, panel privado, revisión/aprobación/archivo/vencimiento, registro de fuentes, publicidad y botones de ejecución manual. Las imágenes privadas se guardan en PostgreSQL; no se depende del disco efímero de una función. El build copia el CSS a `public/static` y aplica migraciones idempotentes, sin sembrar ofertas, fuentes ni suscriptores.

La base inicial está vacía. No se aprobaron ofertas automáticamente ni se cargaron ejemplos en producción. La primera oferta se incorpora desde el panel o `/publicar`, se revisa contra el original y solo entonces el titular elige **Aprobar y publicar**.

## Integraciones pendientes

- Fuentes: ninguna habilitada en producción. Revisar acceso y condiciones, registrar evidencia y autorizar antes de recopilar. La comprobación real aislada de Jobicy no concede esa autorización.
- Correo: faltan proveedor y remitente. Sin ellos, `/alertas` informa que no registra direcciones. Probar consentimiento, recepción, resumen y baja con una dirección propia antes de abrir suscripciones.
- Tareas programadas: no instaladas. Usar `/admin/automatizacion` para lotes manuales. Los endpoints cron exigen Authorization Bearer `CRON_SECRET`; la existencia de la clave no demuestra programación. Verificar plan y precios antes de habilitar el archivo opcional.
- WhatsApp y redes: textos y enlaces manuales para ofertas aprobadas. No hay proveedores automáticos ni cuentas conectadas.
- Lectura de imágenes: módulo preparado, inicialmente deshabilitado. Requiere credencial de Google Cloud Vision, habilitación y consentimiento por archivo; ver LECTURA-DE-IMAGENES.md. No se comprobó una llamada real ni se contrató el servicio.
- Operación: completar responsable/contacto en privacidad y condiciones, confirmar marca/dominio y comprobar restauración de backups en otra base. No se contrató ni cambió ningún plan.

## Actualizar y recuperar

Los cambios a main despliegan la raíz Flask conectada. Revisar pruebas, build, estado READY y `/salud`. Una falla de build conserva la publicación anterior. No modificar secretos para resolver un error sin identificar su causa; nunca copiarlos a Git o al chat.

Las migraciones de `scripts/prepare_vercel.py` se ejecutan explícitamente durante el build; las futuras deben ser aditivas y versionadas. Un rollback de código no revierte la base. Usar respaldos del proveedor o `pg_dump` y ensayar restauración en una base independiente. El comando de backup SQLite no corresponde a Neon.

La suite con PostgreSQL usa `POSTGRES_TEST_URL` y esquemas aleatorios que elimina al finalizar; jamás darle una conexión de producción. El navegador público usa solo consultas sin credenciales y no escribe ofertas ni envía correos. Los resultados y límites de cada comprobación están en VALIDACION.md.
