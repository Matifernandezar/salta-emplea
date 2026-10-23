# Computrabajo mediante Apify: recepción y aprobación

Implementación en PR #2. **No está activada ni desplegada en producción.** Apify ejecuta la búsqueda; Flask recibe su resultado terminado y descarga el dataset por la API de Apify. Vercel no scrapea Computrabajo ni inicia actores. Cada oferta nueva queda `pending` y solo el titular puede aprobarla.

## Evidencia y límites de esta entrega

El titular informó una prueba real del actor `unfenced-group/computrabajo-com-job-scraper` y comunicó sus campos. Una consulta GET real a la API pública de Apify confirmó nombre, usuario e ID `KsjqLGTcOBBib2Xic`. Eso verifica identidad, **no una importación real**.

El JSON saneado de cinco ofertas se solicitó y aún no fue aportado. `tests/fixtures/apify_computrabajo_contract.json` es una fixture **sintética de contrato**, rotulada PRUEBA, con el esquema comunicado y corroborado en la documentación. No se presenta como resultado recibido del proveedor. Falta probar con ese JSON y con una corrida propia terminada; no se iniciaron actores, crearon cuentas ni configuraron servicios de producción.

La [investigación anterior](https://github.com/Matifernandezar/salta-emplea/blob/94800b9a90215f0c26054073593b90d455661107/docs/COMPUTRABAJO.md) conserva la evaluación histórica de acceso oficial, Techmap y TheirStack. Este actor es de un tercero; su presencia en Apify no equivale a una API oficial de Computrabajo ni certifica derechos ajenos. Solo se publica el resumen y el enlace que el titular revisa, sin CV ni imágenes importadas.

## Contrato y reglas

- `jobId`: identidad persistente en `external_jobs`, con clave única por fuente e ID. IDs hexadecimales de 32 caracteres se normalizan a minúsculas. Una oferta ya existente por URL se vincula sin duplicarla.
- `jobUrl`: único origen y destino permitido. Se valida HTTPS, host exacto `ar.computrabajo.com` y ruta de detalle; se quitan fragmento y seguimiento conocido. Se conserva la identidad de otros parámetros. El CTA dice **«Ver oferta y postularme en Computrabajo»**.
- `title`, `companyName`, `location`: datos de ficha, sin completar faltantes. `countryCode` debe ser exactamente `ar`.
- Ubicación: provincia Salta explícita, o una localidad reconocida por la lista conservadora del adaptador. Se contemplan Capital, General Güemes, Tartagal, Orán, Cafayate y otras localidades; nombres ambiguos como San Lorenzo necesitan provincia. Se rechazan otras provincias explícitas. No se busca la palabra Salta en título o descripción.
- `descriptionText`: se eliminan etiquetas y contenido de scripts/estilos; se calcula un resumen determinista de hasta 600 caracteres, sin IA. No se almacena ni publica la descripción completa o HTML. El contenido es dato, nunca instrucciones ejecutables.
- `contentHash` y una huella local de los campos materiales detectan cambios incluso fuera del resumen. La nueva versión queda en procedencia/auditoría; una oferta aprobada vuelve a pendiente sin sobrescribir la preparación editorial. Rechazadas, archivadas y vencidas no se reabren.
- `scrapedAt`: se conserva como evidencia del actor cuando es un ISO con zona horaria válido. Se distingue de la recepción del servidor y de la revisión editorial. `publishDate` queda como texto privado sin interpretar.
- **`applyUrl` y `publishDateISO` se ignoran por completo**. No se guardan en procedencia ni se utilizan como destino, fecha original o vencimiento. La fecha original permanece no informada hasta revisión del titular.
- Ausencia del dataset, error, bloqueo o caída del proveedor nunca archivan ni despublican ofertas. Jobicy y los vencimientos explícitos existentes no se cambian.

## Endpoint y seguridad

`POST /api/webhooks/apify/computrabajo`

Autenticación: cabecera `Authorization` con esquema Bearer y el secreto compartido. No se acepta secreto en URL ni se usa una sesión del administrador. La comparación es de tiempo constante; el endpoint está excluido de CSRF exclusivamente porque verifica su propia autenticación. Devuelve `401` sin credencial y `503` si está sin configurar. Es privado, no indexable y sin caché.

Usar el payload estándar de Apify, evento `ACTOR.RUN.SUCCEEDED`. Se lee `resource.id`; cualquier URL o dataset declarados en el evento se ignoran. Con GET autenticados a `api.apify.com` se verifica identidad del actor, coincidencia de `actId`, ID de corrida y estado `SUCCEEDED`; de esa respuesta se obtiene `defaultDatasetId`.

Límites: webhook 32 KiB; metadatos 128 KiB por respuesta; dataset 2 MiB y hasta 50 registros. Se solicita un registro extra para detectar exceso, sin importar parcialmente un dataset de más de 50. No se siguen redirecciones; el token viaja solo en cabecera y los destinos son fijos, con IDs validados. Solo se acepta JSON sin compresión, con tiempo de red de hasta 10 segundos por operación y presupuesto de trabajo de 45 segundos.

Cada corrida tiene registro persistente, contador de intentos y resultado. El lease dura 300 segundos; si otro trabajador está activo se responde `503` para reintento. Oferta, identidad externa y cursor se confirman juntos por registro. Una interrupción conserva el avance; se verifica la huella del dataset antes de continuar para no mezclar contenidos cambiados. Una corrida ya completada responde `already_processed`, `imported: 0`, sin descargar otra vez. Hasta 12 intentos, alineados con los reintentos de Apify; después requiere intervención. Para reproducir tras corregir un fallo se puede usar una nueva corrida propia; no borrar registros de idempotencia para forzar reenvíos.

Resultados: `imported`, `existing`, `changed`, `rejected`, `processed`, y motivos acotados. Se ven en **Administración → Automatización → Registro de tareas**, tarea `apify_computrabajo`, y en `apify_import_runs`. Los fallos conservan códigos propios, sin cuerpos del proveedor, tokens ni descripciones completas. Repetir una corrida interrumpida conserva los contadores acumulados, sin duplicar ofertas. En corridas distintas: 50 con 40 conocidos → 10 importados; todos conocidos → cero.

## Preparación privada en Vercel (sin activar ahora)

Variables, documentadas solo por nombre y sin valores:

- `APIFY_API_TOKEN`
- `APIFY_COMPUTRABAJO_ACTOR_ID`
- `APIFY_WEBHOOK_SECRET`

En **Project → Settings → Environment Variables**, configurar primero un entorno de prueba con PostgreSQL propio. El token se obtiene en la sección privada de integraciones/API de Apify; usar permisos mínimos de lectura de actor, corridas y datasets que admita la cuenta. El identificador puede ser el nombre del actor indicado arriba o su ID interno confirmado. El secreto del webhook debe ser aleatorio, de al menos 32 caracteres, distinto de los demás secretos. No pegarlos en GitHub, chats, URLs o capturas.

Hay una migración **2**, aditiva, para `external_jobs` y `apify_import_runs`. Conserva las ofertas y la auditoría existentes; no carga datos de prueba. El build actual de Vercel ejecuta migraciones: antes de autorizar un futuro despliegue, preparar backup protegido de PostgreSQL y verificar restauración aislada. Para aplicarla en un entorno aislado configurado: `python -m salta_emplea.cli init`. Windows/VS Code: `.venv\Scripts\python.exe -m salta_emplea.cli init`.

Esta rama mantiene los despliegues Git deshabilitados; no se modificaron cron ni configuración privada. Un futuro despliegue/merge necesita autorización aparte. Para rollback de código, conservar una versión que acepte el esquema 2: el código anterior con migrador de versión 1 lo rechaza. No borrar tablas ni restaurar producción para ensayar recuperación.

## Task y webhook en Apify (dejar deshabilitados)

1. Abrir el actor indicado y guardar una **Task** propia. País **Argentina** (`country: ar`), URL inicial **https://ar.computrabajo.com/empleos-en-salta**, máximo **50**, detalles completos activados y evitar republicados activado. El README documenta `startUrls`, `maxItems` y `skipReposts`; revisar el formulario de la versión concreta para la opción de detalles, cuyo nombre JSON no está confirmado aquí. No usar el ejemplo por defecto de México ni limitar por una palabra de puesto. No agregar un filtro de últimas 24 horas: podría omitir oportunidades de la primera carga.
2. En la Task, crear integración **Webhook / HTTP request**, solo evento **Actor run succeeded**. Destino: la URL HTTPS del entorno autorizado más `/api/webhooks/apify/computrabajo`. Conservar el payload estándar con `eventType` y `resource`.
3. En **Headers template**, configurar `Authorization` con `Bearer` seguido del mismo secreto guardado privadamente como `APIFY_WEBHOOK_SECRET`. Pegar el secreto únicamente en ese campo privado; Apify no interpreta un nombre de variable como su valor. No poner token de API ni secreto en la URL.
4. Crear un **Schedule** diario asociado a la Task. Ejemplo: 09:00 en `America/Argentina/Salta` (12:00 UTC si la UI usa UTC); comprobar la zona y el horario que la consola muestra como próxima ejecución. Mantenerlo **deshabilitado** durante esta entrega. Guardar una Task o credenciales no prueba que exista una programación activa.
5. En una futura prueba autorizada, usar la misma versión/input que produjo la muestra del titular y un máximo pequeño. Enviar la notificación de una corrida propia terminada al entorno aislado. El botón genérico **Test** puede no contener un ID de corrida real y debe fallar en ese caso. Un Preview protegido por login puede rechazar Apify antes de Flask: resolver ese acceso en el entorno de pruebas mediante configuración oficial, sin desproteger producción.
6. Comprobar registro de tarea, cantidad, procedencia y estado pendiente. Reenviar el mismo evento: debe responder cero, sin otra descarga. Revisar y aprobar manualmente una única oferta apta, comprobar CTA y destino original. No aprobar avisos sintéticos en producción. Solo entonces considerar habilitar el Schedule, tras autorización de despliegue y gasto.

Evitar republicados reduce repeticiones del actor; la deduplicación de Salta Emplea sigue siendo obligatoria. El límite del importador es por corrida, no un presupuesto mensual ni un bloqueo de ejecuciones manuales adicionales.

## Costos y documentación primaria

No se activó consumo. El [Store del actor](https://apify.com/unfenced-group/computrabajo-com-job-scraper) muestra «desde USD 1,19/1000 resultados», mientras su README publica USD 1,49/1000. Hay una discrepancia: confirmar la tarifa de la cuenta en Apify antes de programar. Para 50 resultados × 30 días, el componente por resultados sería aproximadamente USD 1,79–2,24; **no es el costo total** ni una cotización. No se verificaron plan, créditos, cómputo, almacenamiento, transferencia, impuestos o excedentes de la cuenta. La facturación puede incluir resultados repetidos que Salta Emplea no cree como ofertas nuevas. No se contrató ningún plan ni se garantiza un tope absoluto de USD 30.

Referencias: [webhooks, cabeceras y reintentos](https://docs.apify.com/integrations/webhooks/actions), [consulta de corrida](https://docs.apify.com/api/v2/actor-run-get), [descarga de dataset](https://docs.apify.com/api/v2/dataset-items-get).

## Validación reproducible y pendiente real

`python -m pytest -q` ejecuta los casos de contrato: cinco pendientes, reimportación cero, 50/40/10, CTA original, rechazo de dominio candidato, fecha inconsistente ignorada, HTML eliminado, cambios y correcciones conservadas, autenticación, reintentos, ausencias, límites y recuperación. Los casos PostgreSQL necesitan `POSTGRES_TEST_URL` hacia una base aislada; CI crea su propio servicio, sin Neon.

`python scripts/browser_check.py` prueba HTTP local → SQL → panel → aprobación → ficha en Chromium móvil/escritorio. El transporte Apify está sustituido y las entradas son sintéticas. Solo se exportan capturas de fichas públicas con datos PRUEBA. Ninguno de estos casos demuestra recepción real de Apify.

Pendiente: incorporar el JSON real saneado y verificar el circuito Apify → webhook → dataset → PostgreSQL aislado con una corrida autorizada; revisar costos de la cuenta y configuración real del Schedule. No se declara la automatización terminada hasta completar esa prueba.
