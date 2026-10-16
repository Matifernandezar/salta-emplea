# Fuentes y nombre provisional

Consulta documental: **16 de octubre de 2026, UTC**. Esta revisión identifica vías posibles; no demuestra cobertura total, vacantes vigentes ni una automatización operativa. No se contactó a ninguna organización.

## Primera API candidata: Jobicy

La [documentación oficial](https://jobicy.com/jobs-rss-feed) autoriza usar avisos en productos, bolsas de empleo y boletines sin permiso individual, conservando atribución y URL canónica. La API pública no exige clave; su enlace dirige a Jobicy. Los enlaces directos al ATS pertenecen a una modalidad comercial que requiere credenciales y revisión de precio antes de contratar.

Contrato documentado: `GET /api/v2/remote-jobs`, filtros `geo`, `industry`, `tag`, `count`; consultar taxonomías mediante `?get=locations` y `?get=industries`. La respuesta contiene `jobs`, `nextCursor`, `hasMore`; cada aviso puede incluir `id`, `url`, `jobTitle`, `companyName`, `jobIndustry`, `jobType`, `jobGeo`, `jobDescription`, `pubDate` y sueldo con moneda/período cuando existe. Revisar elegibilidad geográfica de cada aviso; “remoto” no garantiza acceso desde Salta.

La documentación limita cada sincronización automática a una por hora, ofrece una ventana de siete días con tres horas de demora y un endpoint `/status` con `active`, `closed`, `unknown`. Desaparecer del feed no significa cierre.

**Comprobación pendiente:** no se obtuvo una respuesta HTTP real del endpoint en este entorno. El intento directo encontró una restricción de red y el intento con permisos adicionales fue interrumpido. El adaptador debe permanecer deshabilitado hasta verificar acceso, taxonomías, datos y circuito real. Las pruebas con fixtures no prueban integración real.

El código incluye comprobación del estado documentado, probada con fixtures: solo `closed` archiva; `unknown` y errores solicitan revisión. No se comprobó este endpoint con un servicio real. El adaptador procesa una página de hasta 100 avisos por corrida, sin paginación ni garantía de cobertura.

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
