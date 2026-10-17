# Resultado por fase

## Adaptación a GitHub y Vercel — 17/10/2026

La suite completa informa **144 pruebas aprobadas, sin omisiones**, ejecutada con PostgreSQL 17 real en un contenedor local. Se agregaron backend PostgreSQL, migración explícita, imágenes privadas en la base, leases para tareas, lotes con presupuesto, entrada Flask, preparación de estáticos, cron autenticado y CI de GitHub. Compilación Python, configuración JSON y controles de cambios pasan.

Las pruebas reales verificaron migraciones repetidas, transacciones, importación concurrente sin duplicados, leases y reservas de correo. El circuito HTTP PostgreSQL comprobó aporte con imagen privada, acceso administrativo, aprobación, búsqueda, postulación, confirmación de suscripción, reejecución de cron sin duplicados, baja y vencimiento. Detectó una referencia ambigua en el UPSERT del límite de formularios; se corrigió calificando las columnas de la tabla. Las bases de prueba se aislaron en esquemas aleatorios y se eliminaron al finalizar. Esto no verifica todavía la base de producción ni entregas de correo reales.

El titular creó el repositorio y se subió el historial local a GitHub. La primera CI usó el commit previo a la corrección de PostgreSQL; la validación del commit corregido se comprueba en Actions. Vercel había rechazado la consulta de integraciones con 403. La conexión de la base de producción y el despliegue público siguen pendientes. No se contrataron servicios.

## Validación de la primera entrega local

Verificación local: 16/10/2026. Se ejecutó `python -m pytest -q`: **111 pruebas aprobadas**. Todas las bases y ofertas de prueba están identificadas y aisladas en directorios temporales. No se enviaron mensajes ni se creó infraestructura pública.

| Fase | Qué cambió | Qué se probó y resultado | Qué falta verificar / operativo |
| --- | --- | --- | --- |
| 1. Circuito editorial | Flask, SQLite, web pública, panel, originales, aportes con enlace/texto/imagen, aprobación y postulación externa | Integración HTTP local: alta → pendiente invisible → aprobación → publicación/enlace; editar revoca aprobación; permisos, sesión, CSRF, Unicode, XSS, límites, duplicados, filtros, datos faltantes y vencimiento: pasan | Funciona en el proceso local y persiste en SQLite. Falta prueba visual en navegador y comprobación humana de destinos reales. No hay servidor publicado |
| 2. Fuentes y vigencia | Registro con autorización, frecuencia y último resultado; adaptador Jobicy; estados explícitos de cierre; revisión por antigüedad | Fixtures explícitos: importación repetida no duplica; geografía incompatible se excluye; salarios parciales no se inventan; `closed` archiva, `unknown` pide revisión y error temporal no cierra; redirecciones rechazadas: pasan | Condiciones de Jobicy revisadas documentalmente. API HTTP real interrumpida/no verificada. Ninguna fuente habilitada, ninguna tarea programada en producción. Otras fuentes manuales. Hasta 100 ofertas por pasada, sin cobertura total |
| 3. Alertas, difusión y anuncios | Doble consentimiento, preferencias/frecuencia, baja, bandeja y reservas únicas; difusión manual y anuncios por fechas/ubicación | Proveedor sustituido: confirmación, baja, aprobación al enviar, filtros, frecuencia, reejecución, concurrencia, payload estable, reintentos y entrega incierta; canales apagados, anuncios vigentes y etiquetas: pasan | No se probó recepción real, DNS, rebotes ni cuotas reales. Desarrollo nunca envía. Automáticos de WhatsApp/redes y OCR pendientes; difusión manual funciona. Publicidad no genera métricas |
| 4. Operación | Instalación, variables por nombre, CLI, backup, Docker/Compose, costos/fuentes y guía | Migraciones conservan filas; backup restaurado en base temporal; compilación Python y render SSR de todas las pantallas: pasan | Docker/Compose, cron, HTTPS, restauración del servidor y despliegue público no ejecutados. Navegador/Chromium encontró restricciones de sockets del entorno; no se obtuvo captura visual |

Los 111 casos cubren reglas relevantes y circuitos completos locales; no certifican producción, capacidad ni servicios externos. La suite no requiere credenciales. La documentación de costos distingue tarifas oficiales verificadas de partidas pendientes. El sitio no afirma disponibilidad de marca/dominio, verificación de empresas, contratación ni audiencia.

La carpeta `instance/`, cuando se genera al ejecutar, está excluida de Git. `.env`, subidas, bases y backups tampoco se incluyen. Las pruebas usan exclusivamente ofertas ficticias identificadas. Un lanzamiento requiere base sin datos de prueba y confirmación de las dependencias descriptas en `OPERACION.md`.
