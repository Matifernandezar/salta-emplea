# Fuentes y nombre provisional

Consulta documental: **16 de octubre de 2026, UTC**. Esta revisión identifica vías posibles; no demuestra cobertura total, vacantes vigentes ni una automatización operativa. No se contactó a ninguna organización.

## Primera API candidata: Jobicy

La [documentación oficial](https://jobicy.com/jobs-rss-feed) autoriza usar avisos en productos, bolsas de empleo y boletines sin permiso individual, conservando atribución y URL canónica. La API pública no exige clave; su enlace dirige a Jobicy. Los enlaces directos al ATS pertenecen a una modalidad comercial que requiere credenciales y revisión de precio antes de contratar.

Contrato documentado: `GET /api/v2/remote-jobs`, filtros `geo`, `industry`, `tag`, `count`; consultar taxonomías mediante `?get=locations` y `?get=industries`. La respuesta contiene `jobs`, `nextCursor`, `hasMore`; cada aviso puede incluir `id`, `url`, `jobTitle`, `companyName`, `jobIndustry`, `jobType`, `jobGeo`, `jobDescription`, `pubDate` y sueldo con moneda/período cuando existe. Revisar elegibilidad geográfica de cada aviso; “remoto” no garantiza acceso desde Salta.

La documentación limita cada sincronización automática a una por hora, ofrece una ventana de siete días con tres horas de demora y un endpoint `/status` con `active`, `closed`, `unknown`. Desaparecer del feed no significa cierre.

**Comprobación pendiente:** no se obtuvo una respuesta HTTP real del endpoint en este entorno. El intento directo encontró una restricción de red y el intento con permisos adicionales fue interrumpido. El adaptador debe permanecer deshabilitado hasta verificar acceso, taxonomías, datos y circuito real. Las pruebas con fixtures no prueban integración real.

El código incluye comprobación del estado documentado, probada con fixtures: solo `closed` archiva; `unknown` y errores solicitan revisión. No se comprobó este endpoint con un servicio real. El adaptador procesa una página de hasta 100 avisos por corrida, sin paginación ni garantía de cobertura.

### Nuevo método de comprobación aislada — pendiente de corrida real

El workflow separado [fuente-jobicy.yml](../.github/workflows/fuente-jobicy.yml) permite verificar acceso real desde GitHub Actions mediante ejecución manual o un cambio en ese workflow o en `scripts/verify_jobicy.py` sobre `main`. No tiene cron y su resultado no bloquea la suite de pruebas. Usa Python 3.12 y permisos de lectura de contenido e historial de Actions, sin credenciales de producción. El token efímero de GitHub se usa exclusivamente para comprobar la frecuencia y nunca se imprime.

Antes de contactar Jobicy se verifica el historial: se exige una hora desde la última actualización de una corrida completada; si no figura, se reserva además todo su timeout de cinco minutos desde el inicio. Se omite la consulta si queda una corrida anterior sin terminar, y si no se puede comprobar el historial se rechaza la ejecución. Una corrida fallida u omitida también cuenta. Se serializan las corridas y se revisa el intento anterior en caso de reejecución. No ejecutar reiteradamente para intentar eludir esta ventana.

El script descarga una vez el documento oficial con límite de tamaño, tiempo y sin seguir redirecciones. Registra únicamente URL, estado HTTP, bytes y SHA-256, con revisión humana del permiso pendiente: un documento recibido, su texto o su huella no autorizan automáticamente una fuente. Luego consulta una sola página de la API, importa **dos veces el mismo payload cacheado** en una SQLite temporal exclusiva, comprueba aprobación obligatoria, ausencia de duplicados y respaldo del sueldo, y consulta estado una sola vez si hay IDs candidatos. No aprueba ni publica ofertas; la base temporal y sus archivos se eliminan incluso ante errores. No se leen variables de base, correo ni la configuración de producción.

La salida contiene un único JSON con contadores, garantías comprobadas, categorías geográficas de una lista cerrada, huella documental y clase de fallo; no conserva puestos, empresas, contactos ni contenidos originales. Cero avisos elegibles, cero importables o ausencia de IDs de estado se informan como alcance limitado y no prueban el circuito completo. La autorización humana y el encendido en producción son pasos independientes que siguen pendientes. Ejecutar el script sin `--allow-network` no hace ninguna consulta; el flag exige además el gate verificable de GitHub Actions.

## Otras fuentes evaluadas

| Fuente | Evidencia y decisión inicial |
|---|---|
| [Oficina de Empleo municipal](https://municipalidadsalta.gob.ar/oficinadeempleo/) | Página institucional accesible y noticias oficiales enlazan su portal de empleos. El portal no fue accesible mediante la herramienta web. Sin API o permiso de redistribución verificados: incorporación manual de enlaces y autorización pendiente. |
| [Formación y Empleo provincial](https://formacionyempleo.salta.gob.ar/terminos) | Términos accesibles: prohíben extracción masiva y scrapers no autorizados. No automatizar sin acuerdo. |
| [Trabajo Minería](https://trabajomineria.salta.gob.ar/terminos-y-condiciones-de-uso/) | Sitio y términos accesibles; prohíben reproducción/distribución no autorizada. No automatizar sin autorización. |
| [Computrabajo](https://ar.computrabajo.com/avisolegal/) | Resultado indexado del aviso legal prohíbe robots/crawlers; apertura devolvió contenido insuficiente. No integrar scraping. |
| [Greenhouse](https://docs.greenhouse.io/job-board.html) / [Lever](https://github.com/lever/postings-api) | APIs oficiales documentadas para puestos publicados. No se verificaron endpoints de empleadores ni permiso general de redistribución: evaluar empresa por empresa. |
| [LinkedIn](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibition-of-scraping-software) / [Meta](https://www.facebook.com/legal/automated_data_collection_terms) | LinkedIn prohíbe scraping. Meta redirigió a acceso bloqueado; documentación de publicación respondió 429. Usar aportes manuales autorizados; automatización pendiente de permisos oficiales. |

## Nombre

**Salta Emplea sigue siendo provisional.** La búsqueda encontró una referencia DNS histórica secundaria a `saltaemplea.com.ar`; no acredita situación actual. No se verificó disponibilidad registral. Confirmar dominio en NIC Argentina y antecedentes en el [INPI](https://www.argentina.gob.ar/inpi/marcas/averigua-si-tu-marca-esta-registrada), incluyendo variantes, antes del lanzamiento. No se registró ni contrató nada.
