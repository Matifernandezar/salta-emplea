# Extracción de avisos con Claude

## Configuración

En el proyecto Vercel `salta-emplea`, configurar en Production:

- `ANTHROPIC_API_KEY`: clave privada de Anthropic (Secret).
- `ANTHROPIC_MODEL`: `claude-haiku-5-5`.
- `OCR_ENABLED`: `1`. Una pausa explícita `0` siempre prevalece.
- `OCR_MONTHLY_LIMIT`: cupo de intentos mensuales compartido con el circuito anterior; valor predeterminado 100, máximo 1000. No equivale a un presupuesto monetario.
- `OCR_PROVIDER`: opcional, `anthropic` o `google_vision`. Si está vacío, se elige Claude cuando hay clave de Anthropic.

No usar prefijos públicos para la clave. Los cambios requieren un nuevo despliegue. La existencia de las variables no demuestra que el saldo, la clave o el acceso al modelo sean válidos.

## Uso desde el panel

1. Entrar a `/admin`, incorporar una oferta con imagen y guardar para revisión.
2. Abrir la oferta pendiente. Junto a la imagen, autorizar el envío a Claude y tocar **Leer imagen y preparar datos**.
3. Revisar el original, la transcripción, los campos y sus respaldos. El texto extraído es una propuesta de Claude y puede contener errores.
4. Guardar las correcciones y aprobar mediante la acción editorial existente.

La carga inicial permite autorizar la lectura; en ese caso se puede ejecutar el lote desde Automatización. Cada lote procesa como máximo una imagen. No se agrega ningún cron.

Claude solo puede recibir imágenes autorizadas desde administración. Los permisos anteriores para Google no autorizan el envío a Claude. Los resultados y reservas históricos se conservan. Una imagen con rechazo inequívoco admite hasta tres intentos manuales tras confirmar que se corrigió el acceso; una reserva inconclusa no se reenvía.

## Comportamiento

- Una única solicitud a Messages API por intento, sin redirecciones ni reintentos automáticos.
- Imagen enviada en base64; no se envían conversaciones, claves adicionales ni datos de otras ofertas.
- Respuesta estructurada mediante una herramienta declarativa que **no se ejecuta**: solo entrega datos.
- Valores ausentes o sin respaldo literal se omiten; contactos y modalidad se validan.
- Completa únicamente campos vacíos y el título provisional. Conserva correcciones, fuente, imagen, texto original, salario y fechas.
- Nunca aprueba ni publica automáticamente.
- Se reutilizan permisos de administrador, CSRF, límite de solicitudes, cupo persistente y bloqueo compartido existentes.
- Los errores guardan códigos fijos y no cuerpos del proveedor ni credenciales.

## Validación pendiente en producción

Las pruebas automáticas sustituyen al proveedor. Falta una lectura de una imagen autorizada con la clave real para verificar acceso, latencia, calidad de transcripción y consumo de Anthropic. No confundir pruebas sustituidas con éxito del proveedor real.

Referencias: [Vision](https://platform.claude.com/docs/en/build-with-claude/vision), [Tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview), [Haiku](https://platform.claude.com/docs/en/models/haiku-5-5/overview).
