# Costos y cuentas pendientes

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

- Servidor: cuenta del proveedor, región, facturación, SSH, DNS, HTTPS y responsable de actualizaciones. No hay alojamiento público configurado. El Dockerfile y Compose están preparados; falta probarlos en el servidor elegido.
- Correo: cuenta Resend, dominio remitente validado por DNS, API y remitente autorizados; URL HTTPS estable y prueba real de confirmación, alerta y baja. Las variables se enumeran por nombre en `.env.example`. No se guardan secretos en Git. Revisar rebotes/supresiones en el proveedor; no se integró webhook de rebotes.
- WhatsApp: compartir manualmente no requiere contratar la API. La automatización futura necesita activos propios de Meta, número, permisos, credenciales, consentimiento y posibles plantillas. Precio por país/categoría y proveedor: **pendiente**, consultar [tarifario oficial](https://business.whatsapp.com/products/platform-pricing). No se verificó publicación a canales o grupos mediante API compatible; no se promete.
- Facebook/Instagram: identificar páginas/cuentas propias, tipo de cuenta, aplicación, permisos y revisión vigentes. Requisitos exactos, cuotas y costos de intermediario: **pendientes** en [Meta for Developers](https://developers.facebook.com/). Se entrega difusión manual; no adaptador automático simulado.
- IA/OCR: no se contrata ni usa. Las imágenes se revisan y transcriben manualmente. Si se agrega extracción, presupuestar volumen y proveedor antes de habilitarlo.

## Dominio y nombre

Salta Emplea es provisional. Disponibilidad y aranceles de registro/renovación en [NIC Argentina](https://nic.ar/) y antecedentes en [INPI](https://www.argentina.gob.ar/inpi) siguen pendientes. Un sitio vacío o una referencia DNS no acreditan disponibilidad. Dominio, impuestos y asesoramiento de marca no están incluidos en los totales.

Sites no se adoptó: los auxiliares no estaban instalados y no se obtuvo una tarifa verificable. Cloudflare/Vercel no son necesarios para la arquitectura entregada. No se debe presentar esta estimación como presupuesto de esos servicios.
