# Lectura de imágenes y preparación de avisos

La lectura de imágenes es opcional y está **pausada desde el 19/10/2026**. Se guardó `OCR_ENABLED=0` como Secret y se redesplegó la misma versión; `/publicar` respondió HTTP 200 sin la casilla de envío a Google. Se conservan la clave, el cupo de 999 y el historial, sin leer sus valores ni reiniciar reservas. No se hicieron nuevas llamadas reales al proveedor durante esta pausa.

La primera prueba anterior comunicada por el titular devolvió `credentials_rejected`; no hay una lectura real exitosa verificada. El registro antiguo no precisa si faltaba API, facturación o corregir restricciones. La alternativa [OCR sin API de pago](OCR-SIN-API.md) se evaluó localmente y no alcanzó evidencia suficiente para ofrecer lectura confiable de flyers en español. Se mantiene la carga privada y transcripción manual. Las instrucciones siguientes son para una reactivación futura decidida por el titular, no para activar ahora el servicio.

La preparación de texto pegado funciona localmente con etiquetas explícitas. No usa IA generativa ni tiene costo por consulta externa. Los datos ausentes siguen como «No informado» y ninguna preparación aprueba o publica el aviso.

## Circuito de trabajo

1. Incorporar el enlace, el texto o una imagen obtenida con autorización.
2. Autorizar expresamente la lectura externa de cada imagen. Configurar el servicio no autoriza automáticamente imágenes anteriores.
3. Ejecutar la tarea de extracción desde el panel, la línea de comandos o el endpoint protegido de tareas. No hay una programación automática activada.
4. El servicio lee una imagen por ejecución mediante `DOCUMENT_TEXT_DETECTION`. Se conserva el texto extraído como contenido externo; sus instrucciones nunca ejecutan acciones.
5. Revisar el original junto con el borrador. Corregir datos dudosos, comprobar el contacto y aprobar únicamente después de la revisión.

El OCR reconoce texto: no garantiza que una imagen sea auténtica ni que los contactos, importes o fechas estén bien leídos. No completa información inventada. La detección de duplicados y la aprobación obligatoria siguen aplicándose.

La autorización y los resultados se registran asociados a la huella del archivo. Los fallos y resultados inciertos requieren revisión; no se reintentan automáticamente. Un rechazo inequívoco de acceso permite un reintento manual acotado, como se explica abajo. Esto evita repetir solicitudes ante una respuesta cuyo resultado de facturación sea desconocido.

## Cuenta y configuración

Antes de activar el servicio, el titular debe crear o elegir un proyecto de Google Cloud, vincular una cuenta de facturación, habilitar Cloud Vision API y generar una clave con restricción de API para Cloud Vision. Los presupuestos de Google Cloud sirven como aviso; no constituyen un corte garantizado del gasto.

La llamada REST admite una clave de API. Se envía por el encabezado `x-goog-api-key`, evitando incluirla en la URL. Para esta modalidad no se necesita incorporar un flujo OAuth de usuario a Salta Emplea. La imagen se envía como contenido codificado a `https://vision.googleapis.com/v1/images:annotate`.

Variables por nombre, sin valores secretos de ejemplo:

| Variable | Uso |
| --- | --- |
| `GOOGLE_VISION_API_KEY` | Clave privada del proveedor. Guardar como Secret de producción en Vercel; nunca en GitHub, el navegador o los registros. |
| `OCR_ENABLED` | Activación explícita. La función permanece apagada de forma predeterminada; activar después de configurar y revisar el costo. |
| `OCR_MONTHLY_LIMIT` | Cupo local de intentos por mes UTC: 100 inicialmente y máximo admitido de 1000. |

La configuración inicial mantiene el lector apagado. En este proyecto el titular ya lo habilitó; el despliegue recibió la clave sin que el asistente leyera su valor. Solo con autorización para esa imagen, el archivo se transfiere a Google para su lectura. Antes de habilitarlo corresponde revisar las condiciones del proveedor y comunicar esta transferencia en la información de privacidad. Se pueden seguir incorporando texto y avisos manuales mientras esté deshabilitado.

## Precios oficiales consultados

Consulta: **18 de octubre de 2026**. Valores de lista en USD para `DOCUMENT_TEXT_DETECTION`, según la [tabla oficial de Cloud Vision](https://cloud.google.com/vision/pricing?authuser=1&hl=en). Cada imagen y cada función solicitada cuentan como una unidad facturable; las páginas de documentos también cuentan individualmente.

| Concepto | Precio de lista |
| --- | --- |
| Costo fijo de esta API | Sin cuota fija publicada; pago por uso. |
| Primeras 1000 unidades del mes | Gratis. |
| De 1001 a 5.000.000 de unidades mensuales | USD 1,50 por cada 1000 unidades. |
| Más de 5.000.000 de unidades mensuales | USD 0,60 por cada 1000 unidades. |

Google prorratea el último bloque. Por ejemplo, 1500 unidades de esta función costarían USD 0,75 si las primeras 1000 gratuitas están disponibles y no hay otros cargos. El cupo gratuito **no es una reserva exclusiva para Salta Emplea**: otras aplicaciones y usos dentro del ámbito de facturación del proveedor pueden consumirlo. Impuestos, conversión de moneda y otros servicios de Google Cloud pueden sumar cargos.

El límite local configurado de 999 intentos mensuales reduce el uso de esta aplicación, pero no garantiza una factura de USD 0 ni controla otras claves o aplicaciones. Los intentos reservados y los posibles cargos reales del proveedor son conceptos diferentes. Conviene revisar también cuotas, consumo y alertas desde Google Cloud.

La tabla de Vision no establece una cuota mensual de USD 30. Por separado, Google indica que algunas cuentas de Cloud Billing y formas de pago requieren un **anticipo único para activar la cuenta**, variable según país y moneda; el saldo no usado se devuelve al cerrar esa cuenta, según sus condiciones. Esto no permite identificar el importe que ve el titular sin comprobar el texto de su pantalla. No confundir ese anticipo con una autorización temporal de tarjeta ni con créditos de Gemini/AI Studio. Revisar la sección de anticipos de la [documentación oficial de pagos](https://docs.cloud.google.com/billing/docs/how-to/payment-methods) antes de decidir cualquier pago. El asistente no activó una contratación ni realizó pagos.

## Resolver un rechazo de Google

En el proyecto donde se creó la clave, comprobar [Cloud Vision API habilitada](https://console.cloud.google.com/apis/library/vision.googleapis.com), [facturación vinculada](https://console.cloud.google.com/billing) y [restricciones de la clave](https://console.cloud.google.com/apis/credentials). La clave debe permitir Cloud Vision API. Esta aplicación consulta desde el servidor de Vercel; las restricciones por sitios web/HTTP referrer no corresponden. No inventar una dirección IP fija del servidor.

Las respuestas nuevas distinguen `service_disabled`, `billing_disabled`, `api_key_invalid`, `api_key_expired` y `api_key_restricted` cuando Google aporta una razón oficial reconocida. Si no hay evidencia precisa, se conserva un mensaje general; no se adivina la causa. Se descartan el texto libre, metadatos, proyectos y URLs que puedan aparecer en errores del proveedor.

Después de corregir Google, recargar el aviso pendiente y usar **Reintentar lectura tras corregir Google**. Confirmar el permiso y la revisión de configuración. Esta acción está disponible solo para rechazos de acceso definidos, con un máximo de tres intentos totales por imagen. Conserva el primer fallo y todas las reservas; cada nuevo intento cuenta en el cupo mensual. Un doble envío del mismo formulario no autoriza otra lectura y un formulario antiguo no permite reintentar un fallo nuevo.

Reservas inconclusas, timeouts, errores de red, respuestas ambiguas y lecturas completadas no permiten este reintento. No borrar auditoría, restablecer contadores ni volver a subir la imagen repetidamente para eludir estos controles. Una imagen rechazada sigue privada y la oferta requiere aprobación manual.

## Fuentes y permisos

Esta función no descarga automáticamente publicaciones de Instagram, LinkedIn o Computrabajo. Para esas fuentes se debe verificar una vía oficial y los permisos necesarios. La cuenta de Instagram `@empleosalta12` pertenece a otra persona; disponer de una clave OCR no concede acceso a sus publicaciones ni permiso para reutilizar sus imágenes.

Cuando una fuente no ofrezca integración autorizada, incorporar manualmente un enlace, texto o imagen con los permisos correspondientes. No eludir inicios de sesión, restricciones ni bloqueos. El permiso para leer una imagen tampoco sustituye el permiso para publicarla: conservar el original para revisión y verificar su reutilización antes de incluirla en la oferta pública.

## Validación antes de darlo por operativo

La [suite PostgreSQL](https://github.com/Matifernandezar/salta-emplea/actions/runs/39106820564) y el [circuito Chromium](https://github.com/Matifernandezar/salta-emplea/actions/runs/39106820499) pasaron con respuestas OCR sustituidas y datos temporales. No hubo llamadas reales a Google. Falta probar una imagen autorizada contra el proveedor real, comprobar el texto recibido y su revisión en el panel, repetir la tarea para verificar que no duplique el procesamiento y revisar el consumo registrado por Google. Hasta completar ese circuito, presentar la conexión como **pendiente de configuración y verificación real**.

Referencias oficiales adicionales:

- [Detección de texto y requisitos de Cloud Vision](https://docs.cloud.google.com/vision/docs/ocr).
- [Autenticación con claves de API en Vision](https://docs.cloud.google.com/vision/product-search/docs/auth?hl=en).
- [Uso de claves de API y envío mediante encabezado](https://docs.cloud.google.com/docs/authentication/api-keys-use).

Esta documentación no activa ni contrata servicios.
