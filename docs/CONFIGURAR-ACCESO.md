# Preparar el acceso privado

Esta herramienta genera localmente las tres variables que protegen el panel y las tareas de Salta Emplea. La contraseña la elige el titular; no debe enviarla al chat.

1. Abrí [Preparar acceso privado](https://salta-emplea.vercel.app/configurar-acceso) con Chrome, Edge o Firefox actualizado. Es una página estática: el cálculo ocurre solamente en tu navegador, sin enviar los valores generados.
2. Como alternativa sin conexión, descargá [configurar-acceso.html](../instalacion/configurar-acceso.html) desde GitHub usando **Download raw file / Descargar archivo sin procesar** y abrilo con el navegador. Conservá la extensión `.html`; no hace falta instalar ni iniciar un servidor.
3. Elegí una contraseña exclusiva de al menos 12 caracteres, repetila y guardala en tu gestor de contraseñas. Presioná **Generar configuración privada**.
4. Abrí [las variables de entorno del proyecto](https://vercel.com/matias-projects-2dbf9656/salta-emplea/settings/environment-variables).
5. Agregá cada nombre con su valor correspondiente: `SECRET_KEY`, `ADMIN_PASSWORD_HASH` y `CRON_SECRET`. Seleccioná **Production** y **Secret / Sensitive** para los tres. No compartas sus valores ni capturas de esa pantalla.
6. Cerrá la pestaña del archivo cuando termines. Avisá solamente **«Acceso configurado»** para continuar con el despliegue. No borres ni cambies las variables de conexión de PostgreSQL.

La herramienta no hace solicitudes de red, no usa almacenamiento del navegador y no contiene dependencias externas. Las claves se generan únicamente al presionar el botón. Los botones de selección permiten copiar manualmente; no acceden al portapapeles. El enlace a Vercel abre otra pestaña solamente cuando lo elegís.

`SECRET_KEY` y `CRON_SECRET` usan cada una 32 bytes aleatorios de WebCrypto. `ADMIN_PASSWORD_HASH` se deriva con PBKDF2, SHA-256, un millón de iteraciones y una sal aleatoria; el formato es compatible con Werkzeug. La contraseña escrita se vacía de los campos al finalizar. Esto no permite recuperar una contraseña olvidada: para cambiarla hay que generar y configurar un hash nuevo.

Los resultados permanecen visibles en la pestaña hasta cerrarla. No se incluyen en la URL ni se guardan en un archivo. No regeneres ni reemplaces claves de una app activa sin coordinarlo: cambiar `SECRET_KEY` invalida las sesiones y cambiar `CRON_SECRET` requiere actualizar cualquier cliente autorizado.

Estas variables no sustituyen `DATABASE_URL` ni configuran el proveedor de correo. Las alertas requieren posteriormente `RESEND_API_KEY` y `MAIL_FROM`, con un remitente autorizado y una prueba real de entrega.

## Verificación del desarrollo

Comprobación real aprobada el 18/10/2026 en [GitHub Actions](https://github.com/Matifernandezar/salta-emplea/actions/runs/39099346331), tanto para el archivo local como para la página HTTPS publicada. Se usaron valores ficticios, sin capturas del configurador ni registro de sus resultados.

`scripts/browser_check.py` incluye `check_access_helper(browser)` para comprobar el archivo en Chromium, sin servidor ni solicitudes externas. Usa exclusivamente una contraseña ficticia marcada `PRUEBA`, verifica el hash con Werkzeug y repite la generación para comprobar que cambian las claves y la sal. No imprime resultados secretos ni toma capturas de esta herramienta.

La política de seguridad incorporada autoriza únicamente los hashes del CSS y JavaScript de este archivo. Si modificás esos bloques, recalculá sus hashes SHA-256 en base64 y actualizá la etiqueta `Content-Security-Policy` antes de repetir la prueba en navegador.
