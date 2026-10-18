# Lectura de imágenes y preparación de avisos

La lectura de imágenes está preparada como función opcional. **Google Cloud Vision no está configurado en producción y todavía no se verificó una extracción real con ese proveedor.** No se contrató una cuenta ni se enviaron imágenes reales durante estas pruebas.

La preparación de texto pegado funciona localmente con etiquetas explícitas. No usa IA generativa ni tiene costo por consulta externa. Los datos ausentes siguen como «No informado» y ninguna preparación aprueba o publica el aviso.

## Circuito de trabajo

1. Incorporar el enlace, el texto o una imagen obtenida con autorización.
2. Autorizar expresamente la lectura externa de cada imagen. Configurar el servicio no autoriza automáticamente imágenes anteriores.
3. Ejecutar la tarea de extracción desde el panel, la línea de comandos o el endpoint protegido de tareas. No hay una programación automática activada.
4. El servicio lee una imagen por ejecución mediante `DOCUMENT_TEXT_DETECTION`. Se conserva el texto extraído como contenido externo; sus instrucciones nunca ejecutan acciones.
5. Revisar el original junto con el borrador. Corregir datos dudosos, comprobar el contacto y aprobar únicamente después de la revisión.

El OCR reconoce texto: no garantiza que una imagen sea auténtica ni que los contactos, importes o fechas estén bien leídos. No completa información inventada. La detección de duplicados y la aprobación obligatoria siguen aplicándose.

La autorización y los resultados se registran asociados a la huella del archivo. Los fallos y resultados inciertos requieren revisión; no se reintentan automáticamente. Esto evita repetir solicitudes ante una respuesta cuyo resultado de facturación sea desconocido.

## Cuenta y configuración pendientes

Antes de activar el servicio, el titular debe crear o elegir un proyecto de Google Cloud, vincular una cuenta de facturación, habilitar Cloud Vision API y generar una clave con restricción de API para Cloud Vision. Los presupuestos de Google Cloud sirven como aviso; no constituyen un corte garantizado del gasto.

La llamada REST admite una clave de API. Se envía por el encabezado `x-goog-api-key`, evitando incluirla en la URL. Para esta modalidad no se necesita incorporar un flujo OAuth de usuario a Salta Emplea. La imagen se envía como contenido codificado a `https://vision.googleapis.com/v1/images:annotate`.

Variables por nombre, sin valores secretos de ejemplo:

| Variable | Uso |
| --- | --- |
| `GOOGLE_VISION_API_KEY` | Clave privada del proveedor. Guardar como Secret de producción en Vercel; nunca en GitHub, el navegador o los registros. |
| `OCR_ENABLED` | Activación explícita. La función permanece apagada de forma predeterminada; activar después de configurar y revisar el costo. |
| `OCR_MONTHLY_LIMIT` | Cupo local de intentos por mes UTC: 100 inicialmente y máximo admitido de 1000. |

Solo después de configurar y habilitar el servicio, y con autorización para esa imagen, el archivo se transfiere a Google para su lectura. Antes de habilitarlo corresponde revisar las condiciones del proveedor y comunicar esta transferencia en la información de privacidad. Se pueden seguir incorporando texto y avisos manuales mientras esté deshabilitado.

## Precios oficiales consultados

Consulta: **18 de octubre de 2026**. Valores de lista en USD para `DOCUMENT_TEXT_DETECTION`, según la [tabla oficial de Cloud Vision](https://cloud.google.com/vision/pricing?authuser=1&hl=en). Cada imagen y cada función solicitada cuentan como una unidad facturable; las páginas de documentos también cuentan individualmente.

| Concepto | Precio de lista |
| --- | --- |
| Costo fijo de esta API | Sin cuota fija publicada; pago por uso. |
| Primeras 1000 unidades del mes | Gratis. |
| De 1001 a 5.000.000 de unidades mensuales | USD 1,50 por cada 1000 unidades. |
| Más de 5.000.000 de unidades mensuales | USD 0,60 por cada 1000 unidades. |

Google prorratea el último bloque. Por ejemplo, 1500 unidades de esta función costarían USD 0,75 si las primeras 1000 gratuitas están disponibles y no hay otros cargos. El cupo gratuito **no es una reserva exclusiva para Salta Emplea**: otras aplicaciones y usos dentro del ámbito de facturación del proveedor pueden consumirlo. Impuestos, conversión de moneda y otros servicios de Google Cloud pueden sumar cargos.

El límite local de 100 intentos mensuales reduce el uso de esta aplicación, pero no garantiza una factura de USD 0 ni controla otras claves o aplicaciones. Los intentos reservados y los posibles cargos reales del proveedor son conceptos diferentes. Conviene revisar también cuotas, consumo y alertas desde Google Cloud.

## Fuentes y permisos

Esta función no descarga automáticamente publicaciones de Instagram, LinkedIn o Computrabajo. Para esas fuentes se debe verificar una vía oficial y los permisos necesarios. La cuenta de Instagram `@empleosalta12` pertenece a otra persona; disponer de una clave OCR no concede acceso a sus publicaciones ni permiso para reutilizar sus imágenes.

Cuando una fuente no ofrezca integración autorizada, incorporar manualmente un enlace, texto o imagen con los permisos correspondientes. No eludir inicios de sesión, restricciones ni bloqueos. El permiso para leer una imagen tampoco sustituye el permiso para publicarla: conservar el original para revisión y verificar su reutilización antes de incluirla en la oferta pública.

## Validación antes de darlo por operativo

Falta probar una imagen autorizada contra el proveedor real, comprobar el texto recibido y su revisión en el panel, repetir la tarea para verificar que no duplique el procesamiento y revisar el consumo registrado por Google. Hasta completar ese circuito, presentar la conexión como **pendiente de configuración y verificación real**.

Referencias oficiales adicionales:

- [Detección de texto y requisitos de Cloud Vision](https://docs.cloud.google.com/vision/docs/ocr).
- [Autenticación con claves de API en Vision](https://docs.cloud.google.com/vision/product-search/docs/auth?hl=en).
- [Uso de claves de API y envío mediante encabezado](https://docs.cloud.google.com/docs/authentication/api-keys-use).

Esta documentación no activa ni contrata servicios.
