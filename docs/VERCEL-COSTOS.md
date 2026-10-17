# Vercel: requisitos y costos

Revisión de fuentes oficiales: **16 de octubre de 2026**. Importes en USD; verificar nuevamente antes de contratar. No se compraron servicios ni se crearon bases de datos durante esta revisión.

## Compatibilidad técnica

Vercel admite Flask como una Function con Fluid compute. Detecta una instancia `app` en `app.py`, `index.py`, `server.py`, `main.py`, `wsgi.py` o `asgi.py`, también dentro de `src/` o `app/`. Un módulo distinto se configura mediante `tool.vercel.entrypoint` en `pyproject.toml`. Los estáticos deben estar en `public/**`. [Documentación Flask](https://vercel.com/docs/frameworks/backend/flask).

Versiones Python admitidas: 3.12 (predeterminada), 3.13 y 3.14. Se puede fijar la versión con `.python-version` o `requires-python` en `pyproject.toml`. [Runtime Python](https://vercel.com/docs/functions/runtimes/python/python-version).

La base SQLite local y los archivos subidos requieren adaptación para una ejecución distribuida: usar PostgreSQL externo y almacenamiento persistente para imágenes. Una publicación sin esa configuración no demuestra persistencia operativa.

## Costos y límites

| Servicio | Fijo y capacidad | Variables y condiciones |
| --- | --- | --- |
| Vercel Hobby | USD 0; exclusivamente proyectos personales no comerciales | No asumir que permite este producto con publicidad. [Hobby](https://vercel.com/docs/plans/hobby). |
| Vercel Pro | USD 20/mes por plataforma; incluye un asiento para desplegar y USD 20/mes de crédito de infraestructura | Asientos adicionales USD 20/mes; excedentes según consumo e impuestos. El crédito vence cada mes. [Pro](https://vercel.com/docs/plans/pro-plan). |
| Neon Free | USD 0; 100 CU-h/mes, 1 GB de base y 5 GB de transferencia por proyecto | Adecuado para validar; límites y recuperación reducida deben revisarse antes de producción. [Neon](https://neon.com/pricing). |
| Neon Launch | Sin mínimo mensual | USD 0,106/CU-h; USD 0,35/GB-mes de base; historial USD 0,20/GB-mes. Ejemplo: 140 CU-h y 1 GB ≈ USD 15,19, más historial y otros consumos. [Neon](https://neon.com/pricing). |

Como orientación, Pro más el ejemplo de Neon suma **USD 35,19/mes**, antes de correo, imágenes, dominio, impuestos y excedentes. No es un presupuesto cerrado. El gasto crece con solicitudes, tiempo de cómputo, transferencia, volumen de base e imágenes y correos enviados. Configurar alertas y límites de gasto.

Cron está incluido: 100 tareas por proyecto. Hobby admite ejecución diaria con precisión horaria; Pro admite frecuencia mínima de un minuto. Cada ejecución consume Functions. [Cron: precios y límites](https://vercel.com/docs/cron-jobs/usage-and-pricing).

## Configuración pendiente

Se necesita acceso al repositorio GitHub desde Vercel, permisos de creación/configuración del proyecto y conexión a PostgreSQL. Configurar en Vercel los secretos de aplicación y administrador, conexión a base, URL pública y secreto de cron; nunca incluir sus valores en Git. Para correo: cuenta del proveedor, remitente y dominio autorizado. Los costos de correo, almacenamiento de imágenes y dominio deberán verificarse al elegir esos servicios. Las credenciales y el circuito real deben comprobarse antes de habilitar envíos y tareas.
