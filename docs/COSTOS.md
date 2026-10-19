# Costos y cuentas pendientes

## Presupuesto vigente — 19/10/2026

La plataforma activa usa Flask, Vercel y PostgreSQL en Neon. El titular fijó un máximo de **USD 30 mensuales** y dejó Google Vision en pausa. No se contrató ni cambió ningún plan. Las herramientas disponibles no devuelven el plan de facturación del equipo de Vercel: no se lo infiere del hecho de poder desplegar.

| Servicio | Precio de lista mensual | Capacidad y pendientes |
| --- | --- | --- |
| [Vercel Pro](https://vercel.com/docs/plans/pro-plan) | USD 20 | Un asiento para desplegar y USD 20 de crédito de uso; excedentes, otros asientos e impuestos aparte. Plan real pendiente de comprobar. |
| [Neon Free](https://neon.com/pricing) | USD 0 | 1 GB, 100 CU-h por proyecto/mes y 5 GB de transferencia. Las imágenes privadas consumen base; vigilar cuotas. Recuperación limitada, no copia independiente. |
| [Resend Free](https://resend.com/pricing) | USD 0 | 3000 correos/mes, 100/día y tres dominios. Confirmaciones y pruebas cuentan. Requiere dominio y remitente verificados. |
| Dominio, copias externas y monitoreo | Pendiente de cotización concreta | Registrar pago inicial, renovación, almacenamiento y transferencia, sin prometer un precio para un nombre no elegido. |

La base nominal de Pro más ambos planes gratuitos es USD 20, **antes de dominio, impuestos, respaldos y excesos**; no garantiza una factura final menor a USD 30. No se puede sumar Resend Pro de USD 20 manteniendo ese presupuesto junto con Vercel Pro. Al acercarse a cuotas hay que espaciar resúmenes y conservar pendientes, no ampliar planes automáticamente.

[Vercel Hobby](https://vercel.com/docs/plans/hobby) admite uso personal no comercial; no asumir compatibilidad con la publicidad local prevista. [Cron](https://vercel.com/docs/cron-jobs/usage-and-pricing) permite en Hobby una ejecución diaria por tarea y en Pro hasta una por minuto; las funciones siguen consumiendo recursos. La propuesta de programación frecuente no se instaló sin verificar plan y dependencias.

Los límites locales de correo reservan capacidad para confirmaciones y cuentan intentos fallidos o inciertos conservadoramente. No contabilizan otros consumidores de la misma cuenta ni sustituyen las cuotas o el ciclo del proveedor. Los presupuestos y alertas tampoco son un corte universal del gasto de todos los servicios.

Antes de contratar, presentar la pantalla y condiciones vigentes, impuestos conocidos, costo fijo, unidades variables, límites, precio anual de dominio y renovación. Solicitar aprobación del costo concreto como último paso; tener un presupuesto no autoriza el pago. La configuración privada se completa por nombre de variable, sin compartir claves. Ver [CORREO.md](CORREO.md), [RESPALDOS.md](RESPALDOS.md) y [OCR-SIN-API.md](OCR-SIN-API.md).

## Antecedente de servidor propio — no es la contratación vigente

Consulta: **16/10/2026**. Importes en USD, antes de impuestos, conversión y dominio. No se contrató ningún servicio. Las tarifas deben reconfirmarse en la pantalla de contratación.

## Precios oficiales verificados

| Servicio | Fijo mensual | Límites y variables |
| --- | --- | --- |
| DigitalOcean Basic Regular, 1 GiB / 1 CPU | USD 6 | 25 GiB SSD y 1.000 GiB de transferencia incluidos |
| DigitalOcean Basic Regular, 2 GiB / 1 CPU | USD 12 | 50 GiB SSD y 2.000 GiB de transferencia incluidos |
| Backups DigitalOcean por porcentaje | Semanal: +20%; diario: +30% del servidor | Son imágenes del servidor; complementar con backup consistente de SQLite y uploads |
| Resend Free | USD 0 | 3.000 correos/mes, máximo 100/día |
| Resend Pro | USD 20 | 50.000 correos/mes; exceso USD 0,90 por bloque de 1.000, si se habilita |

Evidencia: [tabla oficial de Droplets](https://www.digitalocean.com/pricing/droplets), [tarifas oficiales de backups](https://docs.digitalocean.com/products/backups/details/pricing/), [tarifa oficial de Resend](https://resend.com/pricing?product=transactional) y [anuncio de excedentes de Resend](https://resend.com/changelog/pay-as-you-go-pricing). La página de precios de Resend expone sus tarjetas de forma irregular; los valores se contrastaron con resultados indexados del propio proveedor y su anuncio oficial. No se usaron precios de terceros.

La [guía de correo de Resend](https://resend.com/pricing) permite newsletters por `/emails` con consentimiento, enlace visible de baja y encabezados de baja. Este código utiliza ese mecanismo; cada destinatario consume un correo. No utiliza Broadcasts ni sus tarifas por contactos.

## Presupuesto sugerido y crecimiento

Para una primera producción sugiero **2 GiB, backup diario y Resend Pro: USD 35,60/mes**, más dominio, impuestos y una copia externa si se contrata por separado. Es una propuesta, no una compra. Los 2 GiB dan margen para sistema operativo, dos procesos web y tratamiento de imágenes. Falta medir carga real: ese margen no es una garantía de capacidad.

Para una prueba pequeña: servidor de 1 GiB con backup diario y correo gratuito resulta en **USD 7,80/mes**, más los mismos extras. El límite de 100 correos diarios hace que no sea apropiado para un boletín de cientos de destinatarios a la vez. El prototipo local no requiere nuevas contrataciones.

Ejemplo de volumen, no audiencia existente: 1.000 suscriptores semanales generan aproximadamente 4.000 envíos en cuatro semanas, más confirmaciones. Diez mil suscriptores diarios podrían generar 300.000 al mes: a la tarifa Pro base y su exceso serían aproximadamente USD 245 de correo, sujeto al plan contratado y alternativas que convenga recotizar. No habilitar excedentes automáticamente sin decidir un presupuesto. A mayor volumen también crecen imágenes, copias, transferencia y tiempo del trabajador. Antes de varias réplicas, migrar SQLite a PostgreSQL; no compartir su archivo por red.

## Cuentas y permisos

- Servidor propio alternativo: cuenta del proveedor, región, facturación, SSH, DNS, HTTPS y actualizaciones. No está desplegado; el alojamiento público elegido es Vercel. Docker/Compose requieren prueba en ese servidor alternativo.
- Correo: cuenta Resend, dominio remitente validado por DNS, API y remitente autorizados; prueba real de confirmación, recepción, resumen y baja. El webhook firmado de rebotes, quejas y supresiones está implementado; todavía no está conectado a una cuenta real. Variables por nombre en `.env.example`, sin secretos.
- WhatsApp: compartir manualmente no requiere contratar la API. La automatización futura necesita activos propios de Meta, número, permisos, credenciales, consentimiento y posibles plantillas. Precio por país/categoría y proveedor: **pendiente**, consultar [tarifario oficial](https://business.whatsapp.com/products/platform-pricing). No se verificó publicación a canales o grupos mediante API compatible; no se promete.
- Facebook/Instagram: identificar páginas/cuentas propias, tipo de cuenta, aplicación, permisos y revisión vigentes. Requisitos exactos, cuotas y costos de intermediario: **pendientes** en [Meta for Developers](https://developers.facebook.com/). Se entrega difusión manual; no adaptador automático simulado.
- IA/OCR: no se contrató ni habilitó un proveedor. El módulo opcional de Cloud Vision y sus costos verificados se documentan en [LECTURA-DE-IMAGENES.md](LECTURA-DE-IMAGENES.md); empieza deshabilitado y las pruebas usan respuestas sustituidas. El texto pegado se prepara con reglas locales, sin costo de proveedor.

## Dominio y nombre

Salta Emplea es un nombre provisional. El titular confirmó la compra de saltaemplea.com y su DNS/HTTPS se verificaron el 19/10; no se realizó una compra por herramientas ni se informó el importe realmente pagado. Revisar precio y fecha de renovación en el registrador del titular. Los antecedentes de marca en [INPI](https://www.argentina.gob.ar/inpi) y disponibilidad de variantes en [NIC Argentina](https://nic.ar/) no se comprobaron. Dominio, impuestos y asesoramiento de marca no están incluidos en los totales.

Los precios del servidor propio son antecedentes y no deben sumarse a Vercel ni presentarse como cotización actual. La arquitectura activa y el presupuesto elegido se describen al principio de este documento.
