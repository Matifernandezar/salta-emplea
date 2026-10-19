# Arquitectura y fases

## Adaptación vigente para Vercel

El usuario eligió GitHub y Vercel. Se conserva Flask y el HTML renderizado; PostgreSQL reemplaza el disco persistente en ese despliegue. SQLite queda disponible para desarrollo y servidor propio. Las imágenes originales son JPEG privados en la tabla uploads y se sirven solamente después de autenticar al administrador. Esto evita otro servicio de archivos en la primera versión; medir almacenamiento y migrar imágenes a Blob privado si el volumen lo requiere.

La base se migra explícitamente en la preparación del despliegue. Los arranques y las peticiones PostgreSQL no crean tablas ni usan almacenamiento local. Las reservas editoriales y de correo usan bloqueos transaccionales; las tareas usan un lease persistente de 900 segundos, compatible con conexiones agrupadas. Las ejecuciones tienen un presupuesto cooperativo de 180 segundos y un máximo de 300 en Vercel; los pendientes se retoman sin duplicar publicaciones o envíos. Cada entorno debe usar una base y secretos propios.

La propuesta inicial de servidor se conserva debajo como antecedente. La guía actual es VERCEL.md; precios y límites en COSTOS.md. El backend está desplegado desde el 18/10/2026; no se contrató ni cambió ningún plan desde el asistente.

Actualización 19/10: se agregaron cuotas persistentes de correo, webhook firmado con supresión y deduplicación, metadatos/sitemap, identidad legal configurable y diagnóstico operativo privado. Los comandos PostgreSQL de backup y ensayo de restauración son externos a HTTP; requieren cliente 17 y un destino privado. El plan de retención tiene vista previa y aplicación explícita, sin borrado automático ni eliminación de imágenes. No se modificó el esquema.

Google Vision está pausado. El ensayo local de Tesseract con modelo inglés no acredita lectura confiable de flyers en español ni compatibilidad con Vercel; permanece la transcripción manual. Ver OCR-SIN-API.md. Fuente aceptada, dominio/remitente, recepción de correo, programación real y respaldo externo de producción siguen pendientes; código y pruebas aisladas no los habilitan.

Decisión previa a implementar, 16/10/2026. Repositorio e infraestructura iniciales: espacio vacío; sin secretos, identidades de nube ni servicios contratados.

## Antecedente: arquitectura propuesta para servidor propio

Monolito Python 3.12 + Flask, HTML renderizado por servidor y CSS local. SQLite con WAL, claves foráneas y migraciones versionadas; un único servidor con volumen persistente. Proceso CLI de tareas invocable por cron con bloqueo y registros. Gunicorn detrás de HTTPS. Esta arquitectura evita JavaScript obligatorio y servicios separados para la primera versión. SQLite es apropiado para un nodo con pocas escrituras; antes de escalar a varias réplicas se migra a PostgreSQL y almacenamiento compartido.

Administrador con contraseña hasheada, sesión firmada, CSRF, autorización en servidor, límite de intentos y cookies seguras en producción. No hay cuentas para candidatos ni CV. Archivos de imágenes redecodificados y privados. Datos externos escapados, sin ejecutar instrucciones ni generar campos por IA. Configuración y secretos fuera de Git.

Datos: ofertas, procedencias, reportes, fuentes, suscripciones, bandeja de correos, anuncios y auditoría. Ninguna oferta sale del estado pendiente sin acción explícita del administrador. Cambios en contenido aprobado revocan su aprobación. La consulta pública y los correos verifican aprobación y vencimiento al momento de usarlos.

## Fases

1. Circuito completo: alta manual/comunitaria, normalización, duplicados, revisión con original, aprobación y postulación externa. Búsqueda y filtros, reportes, vencimiento y protección administrativa.
2. Fuentes: registro auditable y una API documentada únicamente si sus condiciones y acceso se verifican; el resto queda manual. Imágenes con transcripción humana e incertidumbre visible; OCR no habilitado sin proveedor y validación.
3. Alertas con doble confirmación, baja y deduplicación; preparación manual de difusión; publicidad separada. Canales automáticos permanecen deshabilitados hasta verificar permisos y circuito real.
4. Pruebas de integración, documentación, operación y preparación del despliegue. Sin datos ficticios en la base inicial.

## Verificación previa de fuentes

Investigación en curso, documentada en FUENTES.md antes de habilitar cualquier recolección. Los términos de Formación y Empleo de Salta y Computrabajo requieren no implementar scraping sin autorización. Remotive ofrece una API pública con condiciones y atribución; debe verificarse su acceso real y sus restricciones. Greenhouse y Lever no implican permiso de redistribución de cualquier empresa. Redes sociales: incorporación manual; no eludir login ni bloqueos.

## Dependencias del servidor alternativo, no desplegado

Para ese servidor habría que configurar disco, HTTPS, claves y cron. En el Vercel activo ya están configurados Neon y acceso administrativo; faltan dominio/correo, fuentes aceptadas y autorizadas, programación compatible, copias externas y contacto público. Salta Emplea sigue siendo provisional. Los precios vigentes se documentan en COSTOS.md.

## Límites de operación

Un cron real y un correo real no se consideran operativos por tener código: requieren configuración y prueba de ida y vuelta. Nunca se infiere cierre por errores de red. Los reintentos de red son acotados; las entregas de correo ambiguas se detienen para evitar repeticiones. Backups con SQLite backup API, prueba de restauración y política de retención. Evitar almacenar postulaciones o datos de candidatos.
