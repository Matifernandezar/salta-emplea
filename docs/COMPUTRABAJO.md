# Computrabajo: acceso pendiente y circuito manual revisable

Revisión: **22/10/2026, UTC**. Esta entrega prepara código y PR; no activa consultas, fusiona cambios ni modifica producción. La búsqueda automática **no está implementada ni verificada**: falta acceso permitido y una respuesta real sobre la que construir el adaptador.

## Decisión y evidencia de acceso real

El agente de acceso hizo tres búsquedas dirigidas, priorizando documentación oficial de lectura y evaluando un único proveedor alternativo. No encontró una API/feed oficial utilizable para consultar y reutilizar ofertas ajenas. Esto no prueba que no exista una integración privada por acuerdo.

- [Aviso legal de Computrabajo Argentina](https://ar.computrabajo.com/avisolegal/): la apertura real devolvió comprobación JavaScript/antirrobot. No se leyó el texto completo ni se eludió el control. Enlazar al original no concede permiso para extraer o copiar contenido.
- [Techmap: datos de Computrabajo](https://jobdatafeeds.com/data/portals/computrabajo) y [quickstart oficial del proveedor](https://api.techmap.io/quickstart): documentan selección del portal y exigen suscripción/clave RapidAPI. No se aportó acceso existente; no se crearon cuentas ni se consultó una muestra de avisos.
- [Facturación de Techmap](https://api.techmap.io/errors-and-billing): anuncia Basic USD 0 con 100 consultas mensuales y excedentes automáticos de USD 0,06 por consulta. No es un tope de gasto ni una contratación recomendada. Impuestos, consumo compartido y límites de la cuenta concreta no comprobados. No se contrató ni habilitó consumo.
- [Términos de Techmap](https://jobdatafeeds.com/terms), versión 08/06/2026: los derechos sobre datos dependen del acuerdo de suscripción. Una oferta comercial de datos no acredita por sí sola autorización de Computrabajo para republicarlos en este sitio.
- [Campos](https://api.techmap.io/field-reference) y [paginación](https://api.techmap.io/pagination-and-limits): describen `result`, `title`, `company`, `city`, `state`, `portal`, `source`, fechas y `jsonLD.description/url`; páginas de diez resultados con `page` desde uno o cursor. Son documentación, no un contrato validado mediante respuesta real. No se comprobó cobertura de Salta, URL original concreta ni actualización efectiva.

No se usaron proxies alternativos, resolución de captchas, sesiones privadas ni cuentas nuevas. No se pidió ampliar privilegios ni entregar secretos por chat. No se agregaron otras fuentes.

## Qué sí hace el código

`salta_emplea/computrabajo.py` es una política **local de aportes manuales**, sin cliente HTTP, adaptador o consulta de vigencia. `source_catalog.py` sigue siendo un catálogo de referencias. El colector existente conserva Jobicy sin cambiar su acceso o comportamiento.

En `/admin/fuentes` y `/admin/automatizacion` se muestra el bloqueo accionable, última corrida registrada si existe y ausencia de programación de Computrabajo. No se inventa próxima ejecución. El botón específico de recopilación está deshabilitado y no apunta a un endpoint ficticio. El servidor rechaza activaciones incompatibles aunque se manipule el formulario. La referencia se guarda manual/deshabilitada; su pausa persiste en la base entre despliegues.

El enlace «Incorporar aviso de Computrabajo» abre `/admin/nueva?source_preset=computrabajo-salta`, con la fuente preparada y sin inventar una URL de aviso. El titular aporta solo información que puede reutilizar y comprueba la localidad real en Salta; el sistema no deduce geografía por encontrar la palabra «salta» en un texto. No existe filtrado geográfico automático de Computrabajo sin un contrato de lectura comprobado. Una vacante remota requiere revisar expresamente residencia y restricciones, sin asumir elegibilidad mundial.

El aporte conserva un resumen plano de hasta 600 caracteres, requisitos breves de hasta 600 si constan y evidencia textual opcional de hasta 2000. Se rechazan HTML, imágenes y textos que excedan esos límites, sin recortarlos silenciosamente. No se descargan imágenes ni descripciones completas. Los datos no aportados siguen ausentes; se muestran con la política «No informado» del sitio.

El enlace debe ser HTTPS, host exacto `ar.computrabajo.com`, puerto estándar y ruta de detalle `/ofertas-de-trabajo/oferta-de-trabajo-…`, sin credenciales, controles o rutas de listado. Esta validación comprueba estructura, no existencia o vigencia remota. Se eliminan fragmento y seguimiento conocido (`utm_`, `fbclid`, `gclid`); se conservan otros parámetros, incluso repetidos/vacíos, para no cambiar identidad sin evidencia. Una postulación alternativa se rechaza: el destino debe coincidir con el original canónico.

No se abre ninguna de esas URLs desde el servidor. Una ficha aprobada muestra la fuente y «Ver oferta y postularme», con `target="_blank"` y `rel="noopener noreferrer"`. Computrabajo puede exigir su propio registro. Salta Emplea no recibe CV ni gestiona la postulación.

## Contrato interno y garantías reutilizadas

Se usan `jobs`, `provenance`, `audit` y `sources`; no hay segunda base ni migraciones nuevas.

| Dato | Campo/decisión existente |
|---|---|
| Fuente y evidencia | `source_name`, `source_url`, `original_text`, `provenance.payload` |
| Identidad estable | `source_canonical_url` único en SQLite y PostgreSQL; ID externo pendiente de contrato real |
| Cargo, empresa y localidad | `title`, `company`, `location`; sin inventar faltantes |
| Fecha original | `original_date` solo aportada por la fuente; no se deduce de incorporación |
| Resumen permitido | `description` breve; no descripción completa copiada |
| Detección | `collected_at`, generada por el circuito existente |
| Última revisión | `last_checked_at`; distinguir revisión editorial de una consulta remota no realizada |
| Estado | `pending` al crear; aprobación exclusiva del titular por el panel |

`domain.create_job` conserva procedencia, bloqueo editorial compartido y unicidad por URL. Repetir una versión no duplica el aviso ni sustituye correcciones; un cambio material recibido por actor interno retira la aprobación sin reemplazar silenciosamente la versión preparada. Un aporte público no puede retirar una publicación legítima. Reincorporar un archivado no lo reabre. La aprobación también valida enlaces de filas anteriores a esta política.

Una ausencia en un listado, un bloqueo o un fallo no se transforman en cierre. Este cambio no implementa un comprobador remoto de Computrabajo; conserva el vencimiento explícito y la política editorial de antigüedad existentes.

## Pruebas y alcance

Las fixtures son **aportes manuales sintéticos PRUEBA**, con URLs ficticias bajo la estructura del portal. No son respuestas de API ni evidencia de cobertura o permiso. Se prueban dos incorporaciones del mismo aporte, aprobación obligatoria, procedencia, conservación de correcciones, cambio material, no reapertura, aporte público falso, límites y enlaces maliciosos. El colector no consulta Computrabajo aunque existan booleanos locales activos.

Los casos PostgreSQL usan el servicio aislado de CI y un esquema aleatorio eliminado al terminar; incluyen incorporación concurrente y conservación de corrección editorial. No usan Neon ni secretos de producción. Los tests de HTTP/panel comprueban autenticación, CSRF, botón deshabilitado, referencia persistente y CTA original.

El circuito Chromium crea una base temporal, usa datos PRUEBA y revisa fuente, edición, aprobación y ficha a 390 y 1440 px. Bloquea toda solicitud fuera del servidor local: no abre el enlace externo ni demuestra acceso a Computrabajo. Solo exporta capturas públicas de la ficha de prueba; no conserva sesión ni capturas del panel. La regresión existente puede consultar la web pública en lectura, sin presentar esta rama como desplegada.

Comandos desde la raíz del checkout, también en PowerShell con `.venv\Scripts\python.exe` en lugar de `.venv/bin/python`:

```text
.venv/bin/python -m pytest -q tests/test_computrabajo.py tests/test_computrabajo_editorial.py tests/test_computrabajo_ui.py
.venv/bin/python -m pytest -q tests/test_postgres.py
.venv/bin/python scripts/browser_check.py
```

PostgreSQL requiere `POSTGRES_TEST_URL` hacia una base aislada; no usar la de producción. Browser requiere `requirements-browser.txt` y Chromium instalado por Playwright. Las pruebas específicas de timeout, 429, bloqueo, paginación, cursor y cierre remoto quedan pendientes hasta existir un adaptador sobre acceso real; no se simula su cumplimiento con el flujo manual.

## Requisito mínimo para continuar y programación

1. Aportar un mecanismo de lectura permitido para este proyecto: API/feed oficial o acuerdo aplicable con un proveedor. Comprobar que autoriza almacenar y mostrar resumen, datos y enlace original, sin asumir que la venta de acceso otorga derechos ajenos.
2. Configurar las credenciales directamente en el proveedor y el campo privado del alojamiento, con alcance mínimo. No hay variables de Computrabajo añadidas ni una clave cuya sola presencia active un adaptador inexistente. Las variables necesarias se definirán únicamente contra el método elegido.
3. Verificar una muestra pequeña autorizada con ubicación estructurada Salta, ID/URL original, fechas, paginación, límites y señales de cierre. Guardar su payload de forma privada y reprocesarlo sin nuevas consultas para probar idempotencia.
4. Implementar el adaptador en el colector existente, con límites de tamaño/tiempo/páginas, reservas persistentes, tratamiento de `Retry-After`, pausa ante bloqueo y comprobaciones PostgreSQL. Solo entonces revisar y autorizar activación.

La configuración del repositorio conserva su cron diario existente; no se añadió un horario de Computrabajo ni se cambió ningún plan. El conector de lectura de cuenta no expuso el plan de facturación vigente: no se afirma que una frecuencia nueva esté autorizada por él. Antes de elegirla, contrastar cuotas del acceso real y [límites actuales de Vercel Cron](https://vercel.com/docs/cron-jobs/usage-and-pricing). Una alternativa frecuente en otro servicio exigiría presupuesto y aprobación concretos; no se contrató ninguna.

Para mantener esta entrega como PR sin despliegue, `vercel.json` deshabilita despliegues Git únicamente para `codex/computrabajo-acceso-y-revision`, según la [configuración oficial](https://vercel.com/docs/project-configuration/git-configuration). No cambia `main`, otros entornos ni los cron de producción. No fusionar ni desplegar esta PR como parte de esta tarea.
