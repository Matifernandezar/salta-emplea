# Resultado por fase

## Adaptación a GitHub y Vercel — 17/10/2026

La suite actual informa **138 pruebas aprobadas y 6 omitidas**. Se agregaron backend PostgreSQL, migración explícita, imágenes privadas en la base, leases para tareas, lotes con presupuesto, entrada Flask, preparación de estáticos, cron autenticado y CI de GitHub. Compilación Python, configuración JSON y controles de cambios pasan.

Las seis omitidas requieren PostgreSQL real: el servidor local de pruebas se pudo preparar, pero los intentos de ejecutar la suite con permiso de red quedaron interrumpidos y la ejecución sin ese permiso no pudo conectar. No se da ese circuito por verificado. La prueba HTTP PostgreSQL está escrita y pendiente; el circuito HTTP SQLite sigue pasando.

GitHub rechazó `createRepository` con Resource not accessible by integration; la comprobación del repositorio respondió 404. Vercel rechazó la consulta de integraciones con 403. No se creó repositorio remoto ni proyecto de este producto, no se conectó base de producción y no existe despliegue público. La CI, las migraciones remotas y los cron versionados están preparados, no operativos en producción. No se contrataron servicios.

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
