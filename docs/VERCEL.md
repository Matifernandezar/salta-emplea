# GitHub y Vercel

Actualización: 19/10/2026. [Salta Emplea](https://saltaemplea.com) ejecuta Flask con PostgreSQL de Neon. La publicación estática anterior se conserva en Git, pero ya no es la raíz desplegada.

## Configuración activa

- Proyecto Vercel: `salta-emplea`, equipo `matias-projects-2dbf9656`.
- Repositorio público: `Matifernandezar/salta-emplea`, rama de producción `main`.
- Root Directory: raíz del repositorio, sin subdirectorio. Framework: Flask.
- Build Command: `python scripts/prepare_vercel.py`; sin directorio de salida personalizado.
- `.python-version`: Python 3.12. `wsgi.py` exporta la aplicación.
- URL pública canónica: https://saltaemplea.com. Panel: `/admin/ingresar`. La dirección https://www.saltaemplea.com redirige al dominio principal mediante HTTP 308, con HTTPS comprobado. El alias anterior https://salta-emplea.vercel.app sigue conectado; los metadatos apuntan al dominio propio. El 19/10 se verificaron asociación al proyecto, DNS sin errores y HTTPS con salud SQL correcta.
- `vercel.json` prepara tres tareas diarias, compatibles técnicamente con la frecuencia diaria de Hobby y Pro: recopilación 18:20 UTC, vigencia 18:30 y correo 18:50 (15:20, 15:30 y 15:50 en Salta). Hobby puede ejecutarlas dentro de una ventana horaria; no se depende de su orden. No son prueba de ejecución hasta observar el programador. `deploy/vercel-programado.json` conserva la alternativa más frecuente, sin instalar ni contratar Pro.

El despliegue inicial del backend `dpl_BoajdyPMNqsY8WbxhcNuMypSrB3w`, commit `35ef8f2`, terminó READY. El registro de build confirmó migraciones PostgreSQL aplicadas sin datos de prueba. Una petición real a `/salud` devolvió HTTP 200 y `{"status":"ok"}`, que implica una consulta SQL correcta. Portada, aportes, alertas e ingreso respondieron HTTP 200; cron sin credencial respondió 401. Los resultados posteriores de navegador se registran en VALIDACION.md.

## Variables y acceso

La conexión Neon y los nombres `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, `CRON_SECRET`, `PUBLIC_BASE_URL` y `APP_ENV` figuran en Production. Las claves privadas y la conexión son Secret; se verificaron únicamente sus metadatos, sin leer valores. El titular eligió la contraseña y guardó el hash con el [generador privado](CONFIGURAR-ACCESO.md).

Las variables de Neon se limitaron a Production. Los previews y PRs no reciben acceso a esa base. Para desplegar un preview funcional hay que configurar otra base y claves exclusivas de pruebas; no ampliar el alcance de las credenciales reales. El arranque en Vercel rechaza SQLite efímero y claves incompletas.

La contraseña del titular no se conoce ni se recupera desde Vercel. El ingreso positivo con esa contraseña y la primera oferta real deben comprobarse por el titular. La CI usa credenciales ficticias y bases temporales para probar aprobación, permisos y cambios de versión.

## Qué está habilitado

Buscador y filtros, aporte de enlace/texto/imagen pendiente, panel privado, revisión/aprobación/archivo/vencimiento, registro de fuentes, publicidad y botones de ejecución manual. Las imágenes privadas se guardan en PostgreSQL; no se depende del disco efímero de una función. El build copia el CSS a `public/static` y aplica migraciones idempotentes, sin ofertas ni suscriptores de prueba. Con autorización explícita registra una sola vez Jobicy; no consulta ofertas durante el build ni reactiva pausas posteriores.

La base comenzó vacía. Jobicy ya incorporó cinco avisos pendientes en la primera corrida real. No se aprobaron ofertas automáticamente ni se cargaron ejemplos en producción. Los avisos recopilados se revisan desde el panel; también pueden incorporarse desde el panel o `/publicar`. Solo después de revisar el original, el titular elige **Aprobar y publicar**.

## Integraciones y pendientes

- Fuente Jobicy: autorización recibida del titular el 19/10. El build aplica una sola vez el registro mediante `ENABLE_JOBICY_SOURCE=1` y `VERCEL_ENV=production`, con atribución y fecha de revisión de condiciones. Una referencia existente se conserva para revisión; un despliegue nunca reactiva una fuente pausada. No importa avisos durante el build. La primera consulta real persistida recibió 100 avisos y creó cinco pendientes el 19/10 a las 18:51 UTC. Consultar VALIDACION.md para evidencia y límites de atribución al programador.
- Correo: en pausa por decisión del titular el 19/10; no solicitar configuración ni realizar envíos hasta que indique retomar. Faltan proveedor y remitente. Sin ellos, `/alertas` informa que no registra direcciones. Probar consentimiento, recepción, resumen y baja con una dirección propia antes de abrir suscripciones.
- Tareas: programación diaria preparada en el archivo principal. Al desplegar, comprobar que Vercel la instala y observar una ejecución iniciada por la plataforma antes de afirmar su circuito real. El panel admite lotes manuales. Cron exige Authorization Bearer `CRON_SECRET`, que Vercel inyecta sin exponer la clave. No se cambian planes ni se activa correo sin proveedor.
- WhatsApp y redes: textos y enlaces manuales para ofertas aprobadas. No hay proveedores automáticos ni cuentas conectadas.
- Lectura de imágenes: pausada el 19/10 mediante `OCR_ENABLED=0` y redespliegue `dpl_GYfrnTXaXnMzDA7hiN355ioWB84C`, READY. `/publicar` ya no ofrece envío a Google; no se hicieron nuevas llamadas ni se retiró la clave, el cupo o el historial. No hay lectura real exitosa. Ver LECTURA-DE-IMAGENES.md y OCR-SIN-API.md.
- Operación: responsable y contacto configurados con nombre y LinkedIn proporcionados por el titular; dominio web verificado. La marca sigue siendo provisional. Restauración probada en una base aislada; falta instalar y verificar el respaldo externo de producción. No se contrató ni cambió ningún plan.

## Actualizar y recuperar

Los cambios a main despliegan la raíz Flask conectada. Revisar pruebas, build, estado READY y `/salud`. Una falla de build conserva la publicación anterior. No modificar secretos para resolver un error sin identificar su causa; nunca copiarlos a Git o al chat.

Las migraciones de `scripts/prepare_vercel.py` se ejecutan explícitamente durante el build; las futuras deben ser aditivas y versionadas. Un rollback de código no revierte la base. Usar respaldos del proveedor o `pg_dump` y ensayar restauración en una base independiente. El comando de backup SQLite no corresponde a Neon.

Los comandos `backup-postgres`, `verify-backup` y `restore-postgres-isolated` operan fuera de HTTP; requieren cliente 17 y configuración privada independiente para el destino de ensayo. Ver RESPALDOS.md. No se instaló un destino externo ni un cron de respaldo de producción. La retención tiene vista previa y aplicación explícita: no se activa con un despliegue.

Variables nuevas por nombre: `PUBLIC_RESPONSIBLE_NAME`, `PUBLIC_CONTACT_EMAIL`, `PUBLIC_CONTACT_URL`, `ENABLE_JOBICY_SOURCE`, `RESEND_WEBHOOK_SECRET`, `MAIL_DAILY_LIMIT`, `MAIL_MONTHLY_LIMIT`, `MAIL_CONFIRMATION_RESERVE_DAILY`, `MAIL_CONFIRMATION_RESERVE_MONTHLY`, los umbrales `OPERATIONS_*_MAX_AGE_HOURS` y límites `RETENTION_*` de `.env.example`. Responsable indicado: Matías Fernández, sin teléfono público; el perfil LinkedIn exacto se configuró sin parámetros de seguimiento. `PUBLIC_BASE_URL` se actualizó al dominio propio después de verificar asociación, DNS y HTTPS; esa verificación no acredita el dominio remitente en Resend. No agregar `POSTGRES_RESTORE_URL` a producción: corresponde al entorno aislado.

La suite con PostgreSQL usa `POSTGRES_TEST_URL` y esquemas aleatorios que elimina al finalizar; jamás darle una conexión de producción. El navegador público usa solo consultas sin credenciales y no escribe ofertas ni envía correos. Los resultados y límites de cada comprobación están en VALIDACION.md.
