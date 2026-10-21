# Alertas por correo

**Preparación retomada por el titular, 20/10/2026:** pidió una guía para conectar el correo. Todavía no hay cuenta, remitente ni credenciales Resend configurados en Production, según la consulta de metadatos sin secretos. Se puede preparar cuenta y DNS; no se autorizó un destinatario ni se enviaron pruebas reales. Los envíos continúan pausados hasta completar la configuración y acordar esa prueba.

Estado de esta fase, 20/10/2026: el circuito de consentimiento, la bandeja persistente, los límites y la recepción firmada de supresiones están implementados y probados con datos locales y proveedor sustituido. **No se enviaron correos reales en esta fase.** El dominio web saltaemplea.com ya tiene DNS y HTTPS verificados; sus servidores DNS están en Vercel. Faltan la cuenta Resend, verificación específica del subdominio para enviar correo, remitente, configuración privada y autorización de un destinatario para comprobar recepción. La configuración por sí sola no demuestra entrega.

El formulario de producción permanece cerrado mientras falten datos públicos válidos del responsable y contacto, o la configuración del remitente no sea apta. No registra direcciones en ese estado. La baja revoca el enlace de confirmación anterior; una nueva solicitud genera otro token. Una confirmación incierta se concilia antes de preparar otra.

## Validación de la preparación, 20/10/2026

Código comprobado: `bede5e7dd565ada1a5f7b858dd0da701dd5dd3b0`. [CI PostgreSQL](https://github.com/Matifernandezar/salta-emplea/actions/runs/39451555630): 859 pruebas aprobadas. [Chromium](https://github.com/Matifernandezar/salta-emplea/actions/runs/39451556782): circuito aprobado, incluidos los paneles privados de configuración y automatización en celular y escritorio, sin desplazamiento horizontal.

Las pruebas sustituyen al proveedor y comprueban pausa explícita, preservación de cola e intentos, bloqueo del alta pública mientras falta configuración, reintentos, baja y recepción de webhooks. El secreto de webhook se valida solo por formato; eso no acredita conexión. Se dejó el indicador de envío deshabilitado en la configuración de Production. No se crearon cuentas, claves, registros DNS inventados ni correos reales. La verificación externa pendiente sigue siendo dominio, permisos, evento firmado y recepción confirmada por un destinatario autorizado.

## Primer paso del titular: crear la cuenta

1. Abrir https://resend.com/signup, crear la cuenta y confirmar el correo de acceso. Ese correo es privado de la cuenta; no se convierte en contacto público del sitio.
2. Elegir el plan **Free**. El precio oficial verificado el 20/10/2026 es USD 0 mensuales, con 100 correos diarios y 3.000 mensuales. Incluye hasta tres dominios y un endpoint de webhook. No activar un plan pago, excedentes ni una contratación por este procedimiento. Si la pantalla del proveedor muestra un importe distinto, detener la contratación y revisar el costo concreto.
3. En **Domains → Add Domain**, introducir `alerts.saltaemplea.com`. Separar el envío ayuda a mantenerlo independiente del dominio de la web. Usar una región ofrecida y conservarla; la aplicación no fija una región de envío ni inventa registros.
4. Conservar los nombres, tipos y valores DNS generados. Son datos de verificación del dominio, diferentes de una clave API; pueden usarse para preparar los registros en Vercel DNS. No modificar los registros de la web ni el MX de una casilla existente.
5. Esperar el estado **Verified**. Como remitente se propone **Salta Emplea**, con la dirección `avisos@alerts.saltaemplea.com`; esta dirección no crea una casilla receptora ni reemplaza el contacto público en LinkedIn. No crear ni compartir claves todavía.

Después de verificar el dominio se prepara primero el webhook y su secreto; luego la clave API con **Sending access**, limitada al subdominio. Los secretos se guardan directamente en **Vercel → salta-emplea → Settings → Environment Variables → Production**, como Secret. Los nombres figuran abajo; no enviar los valores por chat. Mantener `MAIL_ENABLED` deshabilitado mientras se prepara la cuenta. Cargar API y remitente ya no activa el envío por sí solo: también se exige habilitación explícita, secreto de webhook con formato válido y topes positivos.

El panel privado muestra los requisitos faltantes en Configuración y Automatización. Esa comprobación es local: no consulta el proveedor ni prueba DNS, permisos, recepción o que el webhook esté conectado. Una vez que Resend muestre Verified y el destinatario autorice la prueba, habilitar expresamente el envío y desplegar. Para pausar, deshabilitar `MAIL_ENABLED` y desplegar; las variables de Vercel solo cambian el runtime de los nuevos despliegues. La pausa oculta el formulario público y conserva la cola sin nuevos intentos. El endpoint de rebotes y quejas sigue aceptando eventos firmados durante la pausa.

Agregar el dominio en Resend y publicar sus registros no crea una casilla de correo ni acredita recepción de las alertas. La prueba con un destinatario autorizado es un paso posterior.

## Preparación de la cuenta y DNS

La implementación existente usa la API oficial de Resend. No se instaló ni contrató un nuevo servicio. Antes de activar la cuenta o cambiar planes, revisar [costos](COSTOS.md) y confirmar el importe concreto con el titular.

1. El titular usa saltaemplea.com como dominio propio y su perfil exacto de LinkedIn como contacto público, sin teléfono ni correo personal públicos. El remitente de alertas es independiente de ese contacto. El subdominio de envío puede diferir del dominio donde se aloja la web; no hace falta reemplazar la URL de Vercel para enviar desde un dominio propio verificado.
2. En Resend, agregar un dominio o subdominio que el titular controle. Se recomienda separar el correo de alertas del correo habitual de la organización.
3. Copiar **los registros exactos generados por Resend** al proveedor DNS: DKIM, SPF y Return-Path. No inventar valores ni sustituir el MX del correo habitual. Evitar dos registros SPF para el mismo nombre y revisar los registros existentes antes de modificarlos.
4. Esperar la verificación de los registros en Resend. Revisar que el dominio exacto del remitente esté autorizado; un dominio raíz verificado no implica que cualquier subdominio también lo esté.
5. Revisar SPF/DKIM y alineación del dominio antes de añadir DMARC. Empezar con una política de observación (`p=none`) permite analizar el correo legítimo; avanzar a `quarantine` o `reject` después de verificar todos los emisores. Si se agrega recepción de reportes DMARC, usar una casilla real autorizada. No inventar el destino ni sobrescribir una política existente.
6. Configurar de forma privada las variables indicadas abajo y desplegar. Desactivar seguimiento de aperturas/clics si no es necesario para este servicio. La web no usa esas métricas.

La API acepta únicamente producción configurada, URL pública HTTPS válida, secreto de aplicación y remitente adecuado. El adaptador rechaza `resend.dev` y dominios reservados de prueba como remitentes de producción. Esto es una validación local; **no reemplaza la comprobación real del dominio en Resend**.

## Variables

Guardar los secretos como variables sensibles del proveedor. No compartir valores por chat, registrarlos ni incluirlos en Git.

| Variable | Función |
| --- | --- |
| `MAIL_ENABLED` | Habilitación explícita. Ausente o con cualquier valor distinto del indicador exacto de habilitación, el envío y el formulario permanecen cerrados. Predeterminado deshabilitado. |
| `MAIL_TEST_RECIPIENT` | Restricción opcional a un único destinatario expresamente autorizado. Guardar en privado solo en Production. Vacío desactiva la restricción; un valor inválido bloquea el envío. |
| `RESEND_API_KEY` | Credencial de envío, con el menor alcance disponible. |
| `MAIL_FROM` | Remitente del dominio autorizado. |
| `RESEND_WEBHOOK_SECRET` | Secreto de firma del webhook; es distinto de la clave de envío. |
| `SECRET_KEY` | Firma confirmaciones y bajas; conservar estable y respaldar en privado. |
| `PUBLIC_BASE_URL` | Origen HTTPS público de los enlaces. |
| `APP_ENV` | Solo el modo producción permite entregar correos. |
| `MAIL_DAILY_LIMIT` | Tope local de reservas por día UTC; predeterminado 100. Cero detiene envíos. |
| `MAIL_MONTHLY_LIMIT` | Tope local por mes calendario UTC; predeterminado 3.000. Cero detiene envíos. |
| `MAIL_CONFIRMATION_RESERVE_DAILY` | Capacidad diaria que los resúmenes no pueden consumir; predeterminado 10. |
| `MAIL_CONFIRMATION_RESERVE_MONTHLY` | Capacidad mensual que los resúmenes no pueden consumir; predeterminado 100. |
| `TASK_MAIL_BATCH` | Cantidad máxima por corrida; además se respetan tiempo, cuotas y bloqueo de tareas. |

El indicador de habilitación es `1`; `0` pausa. No representa la aprobación de una oferta ni sustituye el consentimiento del destinatario. El diagnóstico CLI separa presencia de variables y preparación local del envío. Un secreto con formato válido no acredita que sea real ni que el proveedor esté conectado: la conexión exige la prueba firmada real indicada más abajo.

Para una prueba limitada, configurar `MAIL_TEST_RECIPIENT` antes de habilitar el envío y desplegar ambos cambios juntos. La restricción alcanza las confirmaciones y los resúmenes, incluidas las tareas programadas. La cola de las otras direcciones permanece intacta, sin nuevos intentos ni reservas de cuota por esta prueba. El formulario informa que el servicio está en pruebas y solo registra el destinatario permitido, sin mostrar su dirección. No incluir esa dirección en documentación, Git, logs ni capturas. Configurar la restricción no demuestra entrega.

Retirar `MAIL_TEST_RECIPIENT` y desplegar únicamente después de completar la validación y de que el titular decida abrir las suscripciones públicas. Vaciarla habilita el procesamiento normal de toda la cola consentida; comprobar sus pendientes antes de esa apertura. Si se vuelve a una versión que no implemente esta restricción, pausar primero el correo y desplegar la pausa. No borrar reservas ni historial para repetir pruebas.

Si es necesario volver a una versión anterior que no conozca el indicador de pausa, primero deshabilitar la credencial de envío y desplegar esa configuración. Esas versiones no respetan `MAIL_ENABLED`. No borrar mensajes, reservas ni historial para preparar un rollback.

Un límite inválido se interpreta como cero para cerrar el envío. Las reservas de confirmación se acotan al tope correspondiente. Una reserva cero elimina esa separación; no conviene reducirla sin observar las solicitudes de suscripción.

## Cuotas y pendientes

Resend publica para Free 100 correos diarios y 3.000 mensuales, incluyendo mensajes enviados y recibidos; cada destinatario cuenta por separado. Su día es calendario UTC. Esta aplicación envía a una sola persona por petición y no configura recepción de correos.

La aplicación cuenta **cada intento saliente**, incluyendo confirmaciones, resúmenes, pruebas realizadas a través de la aplicación, fallos explícitos y respuestas inciertas. Es una cuenta conservadora: un reintento idempotente puede consumir una reserva local adicional aunque el proveedor lo deduplique. Las reservas no se borran para liberar cupo.

Antes de contactar al proveedor, la transacción de correo comprueba ambos topes y registra una reserva persistente. El bloqueo es compartido por todos los trabajadores; dos procesos no pueden gastar simultáneamente el último lugar disponible. Los mensajes con cupo agotado siguen pendientes y no consumen un intento. Las confirmaciones tienen prioridad en cada lote, y los resúmenes no pueden gastar los 10 lugares diarios y 100 mensuales reservados por defecto para ellas.

El mes local es calendario UTC. Antes de activar el proveedor, comprobar su ciclo efectivo y fijar límites conservadores. **Estos topes no cubren consumos anteriores a su instalación, pruebas desde el panel del proveedor, mensajes de otras aplicaciones, recepción habilitada en la cuenta ni cambios de plan.** Usar una cuenta/equipo dedicado, consultar Usage y restar cualquier consumo externo al presupuesto disponible. No es una garantía absoluta de facturación del proveedor. No se habilitan excedentes ni cambios de plan automáticamente.

Una confirmación en cola vence a las 48 horas: si no pudo salir a tiempo se cancela y la persona debe solicitarla nuevamente. Los resúmenes pendientes se revalidan al enviarse: solo incluyen ofertas todavía aprobadas y activas que coinciden con las preferencias actuales. Si una oferta pierde aprobación no se envía.

## Idempotencia y entregas inciertas

Cada pareja suscripción/oferta se reserva una sola vez. Resend recibe una clave de idempotencia estable y el mismo contenido para reintentos. Solo respuestas HTTP 429 y 5xx explícitas permiten hasta tres intentos, con espera creciente y dentro de 23 horas. Si cambian las ofertas después de un intento, el mensaje pasa a revisión en lugar de reutilizar una clave con otro cuerpo.

Antes de salir a la red se registra estado `uncertain`. Un timeout o una interrupción no dispara reenvío automático. Revisar el proveedor y conciliar el resultado mediante el procedimiento existente; no eliminar reservas, cambiar claves o recrear envíos a ciegas. El adaptador no sigue redirecciones para evitar reenviar la credencial a otro destino.

El estado `sent` significa aceptación HTTP del proveedor. Un evento `email.delivered` indica entrega reportada por el servidor destinatario; ninguno prueba que la persona lo encontró o lo leyó. El criterio de lanzamiento requiere recepción confirmada por el destinatario autorizado.

## Rebotes, quejas y supresión

En el panel de Resend, crear un webhook para la URL pública terminada en `/api/webhooks/resend`, con los eventos `email.bounced`, `email.complained` y `email.suppressed`. Guardar su secreto de firma en la variable privada correspondiente y desplegar. No usar la clave de envío como secreto de webhook.

El endpoint verifica el cuerpo original mediante HMAC-SHA256 del protocolo Svix, sus tres cabeceras y una tolerancia de cinco minutos en ambas direcciones. Acepta como máximo 64 KiB de JSON sin compresión, rechaza claves JSON duplicadas y no registra cuerpos, direcciones, firmas ni mensajes externos. Mantener el reloj del alojamiento sincronizado. Las firmas múltiples de rotación se verifican sin aceptar versiones desconocidas.

Una entrega repetida con el mismo identificador y cuerpo no repite efectos. El mismo identificador con otro cuerpo devuelve conflicto. La deduplicación y la desactivación del suscriptor se confirman en una sola transacción. Un evento firmado de rebote, queja o supresión:

- Desactiva la suscripción y revoca su confirmación anterior.
- Cancela los correos pendientes de esa dirección.
- Conserva una marca seudónima persistente que impide reactivarla mediante un formulario nuevo.
- Conserva los intentos y estados inciertos para revisión; no los reenvía ni los declara recibidos.

La supresión no se retira automáticamente por un evento de entrega ni por una nueva solicitud pública. Para levantarla, el titular debe comprobar el motivo en Resend, consentimiento nuevo y estado del proveedor; no se proporciona un botón público para eludirla.

El ledger guarda hashes de identificador/cuerpo, fecha y resultado fijo; las marcas de supresión guardan hash normalizado de la dirección, fecha y motivo enumerado. Son datos seudónimos, **no anónimos**: protegerlos en los backups y contemplarlos en solicitudes de eliminación. No eliminar el ledger de cuotas del período vigente para reutilizar capacidad. La retención general y eliminación se gestionan con la política de operación; no hay eliminación automática de estas marcas en esta fase.

## Prueba real que falta para el lanzamiento

Solo realizarla después de que el titular autorice expresamente un destinatario, confirme dominio/plan y configure las credenciales privadas. No enviar a terceros ni a direcciones inventadas.

El titular autorizó una dirección propia para esta prueba y confirmó el dominio verificado. La dirección se conserva solo en la configuración privada; esa autorización no acredita que los mensajes ya hayan salido o llegado. Mantener la restricción durante toda la comprobación.

1. Solicitar la suscripción desde la web con filtros y frecuencia elegidos.
2. Ejecutar el lote o esperar una corrida real del programador. Registrar solo resultado y fecha, sin dirección, enlaces privados ni contenido del correo.
3. El destinatario confirma que recibió el correo y abre el enlace; confirma mediante el formulario. Un HTTP 2xx del proveedor no reemplaza esta comprobación.
4. El titular aprueba una oferta real compatible. Preparar el resumen cuando corresponda por frecuencia y comprobar su recepción.
5. Repetir la tarea: no debe repetirse la oferta ni el resumen ya entregado.
6. Dar de baja mediante el enlace visible o la baja de un clic. Preparar otra corrida con una oferta apta: no debe salir correo nuevo para esa suscripción.
7. Verificar una entrega firmada de webhook desde Resend con un evento de prueba autorizado, su recepción en la app y su repetición sin nuevos efectos. Las pruebas locales de firma no acreditan esta conexión externa.

En local, `tests/test_mailer.py` y `tests/test_mail_webhooks.py` sustituyen el proveedor. Cubren cuotas compartidas, capacidad de confirmaciones, cambio de calendario, fallos, reservas, firmas inválidas, vector oficial Svix, repetidos, conflictos, límites y supresión. No prueban DNS, recepción real, bandeja de spam ni programación de producción.

## Referencias oficiales consultadas

Precios, cuotas, dominios, permisos API y eventos de webhook revalidados el 20/10/2026. Las referencias restantes se consultaron el 19/10/2026; volver a comprobar antes de contratar o activar:

- [Precios de Resend](https://resend.com/pricing) y [cuotas y límites](https://resend.com/docs/knowledge-base/account-quotas-and-limits).
- [Alta y verificación de dominio](https://resend.com/docs/add-a-domain) y [DMARC](https://resend.com/docs/dashboard/domains/dmarc).
- [Direcciones remitentes sin casilla receptora](https://resend.com/docs/knowledge-base/how-do-I-create-an-email-address-or-sender-in-resend) y [permisos de claves API](https://resend.com/docs/api-reference/api-keys/create-api-key).
- [Idempotencia](https://resend.com/docs/dashboard/emails/idempotency-keys).
- [Verificación de webhooks de Resend](https://resend.com/docs/webhooks/verify-webhooks-requests) y [protocolo manual oficial de Svix](https://docs.svix.com/receiving/verifying-payloads/how-manual).
- [Rebotes](https://resend.com/docs/webhooks/emails/bounced), [quejas](https://resend.com/docs/webhooks/emails/complained) y [supresiones](https://resend.com/docs/webhooks/emails/suppressed).
