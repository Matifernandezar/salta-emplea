# Arquitectura y fases

Decisión previa a implementar, 16/10/2026. Repositorio e infraestructura iniciales: espacio vacío; sin secretos, identidades de nube ni servicios contratados.

## Arquitectura propuesta

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

## Dependencias sin configurar

Dominio y revisión de marca (Salta Emplea es provisional); servidor con disco persistente y HTTPS; contraseña del administrador y clave de sesión; dominio de correo validado y cuenta del proveedor; cron del servidor; acuerdos de fuentes; cuentas propias y permisos de Meta para futura difusión automática. No se contrata nada en esta fase. Los precios y límites verificados se documentan en COSTOS.md.

## Límites de operación

Un cron real y un correo real no se consideran operativos por tener código: requieren configuración y prueba de ida y vuelta. Nunca se infiere cierre por errores de red. Los reintentos de red son acotados; las entregas de correo ambiguas se detienen para evitar repeticiones. Backups con SQLite backup API, prueba de restauración y política de retención. Evitar almacenar postulaciones o datos de candidatos.
