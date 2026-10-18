# Resultado por fase

## Controles de automatización y versiones — 18/10/2026

Se agregó el panel privado `/admin/automatizacion` con configuración detectada, corridas y ejecución manual de lotes. Reutiliza la exclusión compartida con CLI/cron, limita intentos, fuente, correos y tiempo, y nunca aprueba avisos. Se registra la recepción de llamadas autenticadas al cron sin afirmar que la programación esté activa.

Las nuevas pruebas cubren permisos, CSRF, rutas de solo lectura, acciones inválidas, límites, exclusión, idempotencia y ausencia de envíos sin proveedor. Las importaciones comparan versiones recibidas sin sobrescribir datos preparados: detectar cambios o eliminación de contacto/condiciones revoca aprobación; repetir la versión respeta correcciones editoriales; aportes públicos no sustituyen la referencia confiable. Un correo pendiente se cancela antes de enviarse cuando pierde aprobación la oferta. La pantalla de revisión permite comparar los campos de cada versión, con escape del contenido externo.

`check-production` valida configuración incompleta sin arrancar Flask y sin imprimir secretos. Su opción de base es explícita y de solo lectura: verifica conexión y esquema, sin migrar ni enviar mensajes. Se probaron errores del proveedor con información sensible para comprobar que no se revele.

Resultado local de esta ampliación: **211 pruebas aprobadas y seis omitidas porque no había PostgreSQL de pruebas configurado en esa ejecución**. El intento adicional de PostgreSQL local encontró el servidor de pruebas anterior apagado; su recreación y ejecución posterior se interrumpieron. La validación posterior del commit `4e59079` en [GitHub Actions](https://github.com/Matifernandezar/salta-emplea/actions/runs/39094104057) ejecutó **217 pruebas con PostgreSQL 17 real: todas aprobadas, sin omisiones, en 14,91 segundos**. Compilación y revisión de diferencias correctas. Las pruebas de correo usan proveedores sustituidos y no acreditan recepción real.

La consulta de metadatos de Vercel no encontró variables de entorno configuradas. Siguen pendientes PostgreSQL de producción, secretos del backend, cron y proveedor de correo. El despliegue de producción del commit `4e59079` quedó READY, conservando `vista-previa/`: estos cambios no habilitan funciones inexistentes en la publicación estática. La comprobación HTTP de Jobicy y la preparación de pruebas de navegador fueron canceladas antes de obtener resultados; ambas siguen pendientes. No se contrataron servicios ni se habilitaron fuentes en producción.

## Página pública preliminar — 18/10/2026

Se publicó https://salta-emplea.vercel.app desde `vista-previa/` en el repositorio GitHub conectado. Vercel informa despliegue de producción READY. El inicio, `/alertas`, `/publicar`, `/admin`, `/privacidad`, `/condiciones` y `/static/style.css` responden HTTP 200 sin cookies ni credenciales, con contenido correcto y cabeceras de seguridad. La página está identificada como preliminar; comienza vacía, sin ofertas de prueba, y las funciones pendientes están deshabilitadas.

Está operativo el sitio estático y su navegación. Búsqueda, aportes, panel privado, alertas, recopilación y tareas no están activos en esta publicación. Su código y sus pruebas locales se conservan. No se probó visualmente en un navegador ni se verificaron servicios de producción. No se contrataron servicios de pago.

## Adaptación a GitHub y Vercel — 17/10/2026

La suite completa informa **144 pruebas aprobadas, sin omisiones**, ejecutada con PostgreSQL 17 real en un contenedor local. Se agregaron backend PostgreSQL, migración explícita, imágenes privadas en la base, leases para tareas, lotes con presupuesto, entrada Flask, preparación de estáticos, cron autenticado y CI de GitHub. Compilación Python, configuración JSON y controles de cambios pasan.

Las pruebas reales verificaron migraciones repetidas, transacciones, importación concurrente sin duplicados, leases y reservas de correo. El circuito HTTP PostgreSQL comprobó aporte con imagen privada, acceso administrativo, aprobación, búsqueda, postulación, confirmación de suscripción, reejecución de cron sin duplicados, baja y vencimiento. Detectó una referencia ambigua en el UPSERT del límite de formularios; se corrigió calificando las columnas de la tabla. Las bases de prueba se aislaron en esquemas aleatorios y se eliminaron al finalizar. Esto no verifica todavía la base de producción ni entregas de correo reales.

El titular creó el repositorio y se subió el historial local a GitHub. La primera CI usó el commit previo a la corrección de PostgreSQL; la ejecución posterior del commit `9697d6e` terminó correctamente en [GitHub Actions](https://github.com/Matifernandezar/salta-emplea/actions/runs/38991220851). Vercel había rechazado la consulta de integraciones con 403. Sigue pendiente la conexión de la base de producción y el despliegue del backend completo. El sitio estático público posterior se documenta arriba. No se contrataron servicios.

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
