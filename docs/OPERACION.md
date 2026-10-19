# Guía simple de administración

El sitio activo es https://salta-emplea.vercel.app. Para GitHub/Vercel, seguir primero VERCEL.md: la persistencia usa PostgreSQL y las tareas se ejecutan manualmente desde el panel hasta habilitar un programador. SQLite, archivos locales y cron del servidor descritos abajo siguen siendo la alternativa para desarrollo o servidor propio. En PostgreSQL las imágenes privadas están en la base, y el bloqueo de tareas es un lease compartido. `DATABASE_URL` selecciona ese modo; el comando de respaldo SQLite no se aplica a PostgreSQL.

## Entrar y publicar la primera oferta

1. En el sitio publicado, abrir https://salta-emplea.vercel.app/admin/ingresar y usar la contraseña elegida al preparar el acceso privado. No hay contraseña de fábrica. Para instalar otra copia local, seguir el README y configurar su propio `.env`.
2. Abrir `/admin/ingresar`. Entrar y elegir **Incorporar oferta**. También podés recibir aportes desde `/publicar`, sin cuentas públicas.
3. Copiar el enlace, el texto original o una imagen JPG/PNG/WEBP. Un texto con etiquetas como “Puesto:” o “Correo:” permite preparar esos campos al incorporar el aviso, sin consultar a un proveedor externo. Completar solo datos respaldados por la fuente. Un aporte solo con enlace o imagen queda con un título interno pendiente; ese título no se puede publicar.
4. Comparar **Aviso original** y **Versión preparada**. Transcribir el puesto y revisar contacto, empresa, condiciones, residencia compatible con Salta y fechas. Las imágenes son privadas. La lectura automática es opcional y empieza deshabilitada; si falta configuración, se transcriben manualmente. Ver LECTURA-DE-IMAGENES.md. Los datos inciertos se enumeran para revisión.
5. Guardar. Revisar duplicados y señales de posibles pedidos de pago. El sueldo exige importe/rango, moneda, período y evidencia textual. Los campos ausentes aparecerán como **No informado**.
6. Marcar el reconocimiento de alertas cuando corresponda y elegir **Aprobar y publicar**. Aprobar requiere un enlace HTTPS, WhatsApp con número internacional o `mailto:` válido. No es una verificación formal de la empresa.
7. Abrir la publicación y comprobar el destino de **Postularme**. La postulación ocurre fuera del sitio; no se cargan CV. Una aprobación registrada prueba la decisión editorial; no garantiza contratación ni confirma automáticamente la legitimidad de la empresa.

**Cualquier edición vuelve a pendiente**, incluso cambios pequeños. Guardar y volver a aprobar para actualizar. Cambios sensibles detectados por el recopilador autorizado también retiran la publicación hasta revisión. Un aporte de la comunidad que repite una URL conserva su procedencia y no puede despublicar un aviso aprobado.

En **Historial de procedencia y versiones recibidas → Comparar datos recibidos** podés consultar empresa, postulación, condiciones y datos ausentes de cada versión. Los aportes nunca reemplazan automáticamente los campos preparados. Si una fuente quita un contacto o condición, también vuelve a revisión. Repetir la misma versión respeta las correcciones editoriales ya aprobadas.

## Duplicados, vigencia y reportes

Una URL canónica repetida conserva un solo aviso y su procedencia; se eliminan parámetros de seguimiento conocidos para compararla. Contenido idéntico sin URL también se reconoce. Empresa, puesto, localidad y similitud señalan candidatos a duplicado, sujetos a revisión. Esta comparación tiene un límite de 1.500 avisos recientes para mantener bajo el costo; ampliar el índice antes de crecer mucho.

Se puede **Rechazar**, **Archivar** o **Marcar vencida** desde la revisión. Una fecha de cierre explícita se aplica automáticamente; una fecha sin hora incluye todo ese día en Salta. Un estado explícito `closed` de Jobicy archiva. `unknown`, un error de red o la ausencia del feed no significan cierre.

En Configuración, elegir a cuántos días pedir revisión si no hay cierre: por defecto 30. Pedir revisión por antigüedad no retira por sí solo el aviso; el detalle público lo advierte. Reportes públicos aceptan errores, cierres, sospechas y pedidos de retiro; el panel los lista. Contrastarlos y editar o archivar el aviso. Si el pedido exige respuesta, usar el contacto aportado por el canal que el responsable defina; el sistema no responde automáticamente.

## Fuentes

La base inicial no trae fuentes habilitadas. Ver `FUENTES.md` antes de dar de alta una. Las tarjetas de Instagram @empleosalta12, Computrabajo y LinkedIn permiten registrar referencias manuales sin activar consultas; ver `FUENTES-ELEGIDAS.md`.

- Registrar nombre, URL, método, frecuencia y URL de condiciones. Marcar autorización únicamente después de revisarla. Se puede deshabilitar cada fuente desde su formulario.
- El método **manual** es un registro de seguimiento: no simula una consulta automática. Usar Incorporar oferta.
- El adaptador **Jobicy** acepta únicamente su URL oficial. Pasó la comprobación real aislada documentada en FUENTES.md. Eso no habilita la fuente en producción: revisar condiciones y autorización antes de activarla. Retiene atribución y URL original, importa hasta 100 resultados por pasada y no recorre paginación: no promete cobertura total. Solo considera geografías explícitas compatibles y exige revisión humana de residencia y zona horaria.
- La frecuencia mínima implementada es seis horas. Un error se registra y se vuelve a intentar en la próxima ventana configurada. La consulta de estados revisa hasta 100 avisos almacenados, priorizando la comprobación más antigua. Conserva identificación de la fuente en el original recibido.

No ingresar credenciales en textos de avisos. No ejecutar instrucciones incluidas en contenido externo. No usar scraping para fuentes restringidas ni sesiones de terceros.

## Alertas y difusión

Las alertas públicas permanecen pendientes de configuración si falta proveedor, remitente o URL pública. En ese estado no se registra el correo. En desarrollo el trabajador no envía.

Para habilitar producción: validar el dominio remitente en Resend, configurar las variables, iniciar el programador y probar con una dirección propia autorizada: solicitud → correo de confirmación → confirmación explícita → oferta aprobada → resumen → baja → ausencia de nuevos envíos. Probar también carpeta de spam y supresiones del proveedor. No afirmar entrega por una aceptación de API: contrastar recepción.

La suscripción permite localidad, rubro, modalidad y frecuencia diaria/semanal; los filtros de localidad/rubro comparan el valor completo, ignorando mayúsculas, por lo que conviene copiar el nombre usado en el buscador. El consentimiento se confirma antes de alertar. La cola reserva cada pareja destinatario/oferta y comprueba aprobación, vigencia y consentimiento antes de enviar. La baja visible y de un clic cancela pendientes. Los registros privados permiten diagnosticar envíos sin inventar métricas.

La preparación de producción incorpora cuotas diarias/mensuales y reserva de capacidad para confirmaciones. Los intentos quedan contados aunque fallen; al llegar al cupo los pendientes se conservan. La baja revoca el token de confirmación anterior; una nueva solicitud necesita un nonce nuevo. Los resultados inciertos requieren conciliación. El webhook firmado `/api/webhooks/resend` bloquea reactivaciones por rebotes o quejas y deduplica eventos; falta configurar y verificar el proveedor real. Ver CORREO.md. Tener claves presentes no garantiza remitente válido ni recepción.

El panel Automatización también muestra antigüedad de corridas, llamadas autenticadas por tarea y cola pendiente. Este diagnóstico no certifica el origen de las llamadas ni instala un programador o monitoreo externo. Los backups PostgreSQL se operan con los comandos de RESPALDOS.md; `retention-preview` no escribe y `retention-apply --confirm-deletion` requiere revisar una limpieza concreta. No se hicieron borrados de producción ni se eliminan imágenes con esa herramienta.

WhatsApp y redes ofrecen texto/enlace manual solo para ofertas aprobadas y activas. Habilitar o deshabilitar cada preparación desde Configuración. Eso no activa una publicación automática. Publicar exclusivamente en canales propios y autorizados. Los adaptadores oficiales futuros, sus permisos y costos están pendientes en `COSTOS.md`.

## Publicidad

Abrir Publicidad; cargar nombre, URL HTTPS de imagen, destino, ubicación y fechas. Activar cuando corresponda. El sitio muestra **Publicidad** y respeta la ventana de fechas. Editar o desactivar desde la misma pantalla. Negociación y cobro son manuales. No hay medición de audiencia ni anuncios mezclados con avisos laborales. Usar imágenes optimizadas y con permiso; su alojamiento externo puede registrar visitas.

## Tareas, errores y recuperación

Abrir **Automatización** en el panel privado. La pantalla muestra la base consultada, si hay configuración de correo, fuentes compatibles autorizadas, corridas recientes y la última llamada autenticada al cron. Tener claves presentes no demuestra que el proveedor funcione ni que el programador esté activo. Una llamada al cron tampoco demuestra que haya terminado: revisar el estado de la corrida.

Los botones **Recopilar ofertas**, **Comprobar vigencia**, **Procesar correos** y **Leer imágenes autorizadas** ejecutan un lote por acción. Requieren sesión y formulario vigente. Admiten seis intentos cada diez minutos, hasta una fuente por frecuencia y tres correos por lote manual, con presupuesto de un minuto. Si otra tarea ya está en curso, se omite la nueva. No habilitan fuentes ni aprueban ofertas. Sin configuración de correo los mensajes quedan pendientes, sin enviarse. La lectura procesa hasta una imagen con permiso por lote, exige proveedor configurado y límite mensual disponible. Conserva la reserva antes de consultar; una lectura fallida o inconclusa no se reenvía automáticamente. Si Google rechazó expresamente el acceso, corregir API, facturación o restricciones y usar el reintento manual del aviso: máximo tres intentos totales por imagen, todos conservados y contados. Un resultado incierto no permite reenvío. Ver LECTURA-DE-IMAGENES.md; no borrar reservas para forzar cobros nuevos.

Como alternativa, ejecutar una corrida con `python -m salta_emplea.cli tasks`. `--only collect`, `--only expire` y `--only mail` permiten aislar etapas. El código del backend prepara cron de Vercel; en un servidor propio hay que instalar el cron correspondiente. Hay exclusión compartida por archivo en SQLite o lease en PostgreSQL, transacciones, claves únicas, historial de corridas y reintentos de correo acotados. Un reinicio marca corridas inconclusas como interrumpidas y recupera el procesamiento idempotente. El backend activo incluye estos mecanismos; los lotes del panel requieren una acción explícita y no instalan un programador.

Antes del despliegue, `python -m salta_emplea.cli check-production --with-crons` valida la configuración local sin mostrar valores ni abrir conexiones. `--check-database` agrega una comprobación explícita del acceso, las tablas y la versión usando solo lectura. Un diagnóstico correcto no verifica entregas de correo, programación de tareas ni tráfico real.

Una entrega de correo incierta se detiene. Verificar el registro en Resend y conciliar sin reenviar con `python -m salta_emplea.cli reconcile-mail ID --result sent` o `--result cancelled`. No borrar reservas para forzar un reenvío. Los errores temporales confirmados admiten hasta tres intentos con espera y la misma clave dentro de 23 horas; después requieren revisión.

Hacer respaldo consistente con `python -m salta_emplea.cli backup DESTINO_NUEVO`. Guardar también uploads y configuración privada por separado, cifrar las copias externas y probar restauración. Nunca copiar solamente un archivo SQLite mientras escribe. Recomendación inicial: copia diaria, retención de 30 días; debe implementarse en el servidor y comunicarse en privacidad. No se instaló retención automática de datos ni de copias.

Para eliminar un correo solicitado por su titular: verificar la solicitud y usar `python -m salta_emplea.cli forget-email CORREO`. Elimina suscripción, bandeja, reservas y contacto de reportes coincidente. Considerar también copias con retención. Revisar y eliminar imágenes huérfanas y aportes rechazados según la política que se publique.

Excluir las rutas de confirmación y baja de logs completos de acceso; contienen tokens. No registrar cuerpos de correo ni secretos. Gunicorn está preparado con registros de errores sin access log. Configurar también el proxy. El responsable debe monitorizar caídas, tareas fallidas, espacio libre y backups; no hay servicio externo de monitoreo contratado.

## Antes del lanzamiento público

Confirmar marca y dominio; completar nombre/contacto del responsable en Privacidad y Condiciones; aprobar presupuesto; configurar HTTPS, secretos y cron; probar backup/restauración en el servidor; completar prueba real de fuentes y correo; revisar visualmente en celulares. No hay datos de demostración en la base inicial. No publicar el entorno de desarrollo.
