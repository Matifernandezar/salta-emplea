# Guía simple de administración

## Entrar y publicar la primera oferta

1. Instalar según el README, generar clave y hash de contraseña y guardarlos en `.env`. Sin hash no se puede ingresar al panel. No hay contraseña de fábrica.
2. Abrir `/admin/ingresar`. Entrar y elegir **Incorporar oferta**. También podés recibir aportes desde `/publicar`, sin cuentas públicas.
3. Copiar el enlace, el texto original o una imagen JPG/PNG/WEBP. Completar solo datos respaldados por la fuente. Un aporte solo con enlace o imagen queda con un título interno pendiente; ese título no se puede publicar.
4. Comparar **Aviso original** y **Versión preparada**. Transcribir el puesto y revisar contacto, empresa, condiciones, residencia compatible con Salta y fechas. Las imágenes son privadas y requieren transcripción humana: no hay OCR conectado. Los datos inciertos se enumeran para revisión.
5. Guardar. Revisar duplicados y señales de posibles pedidos de pago. El sueldo exige importe/rango, moneda, período y evidencia textual. Los campos ausentes aparecerán como **No informado**.
6. Marcar el reconocimiento de alertas cuando corresponda y elegir **Aprobar y publicar**. Aprobar requiere un enlace HTTPS, WhatsApp con número internacional o `mailto:` válido. No es una verificación formal de la empresa.
7. Abrir la publicación y comprobar el destino de **Postularme**. La postulación ocurre fuera del sitio; no se cargan CV. Una aprobación registrada prueba la decisión editorial; no garantiza contratación ni confirma automáticamente la legitimidad de la empresa.

**Cualquier edición vuelve a pendiente**, incluso cambios pequeños. Guardar y volver a aprobar para actualizar. Cambios sensibles detectados por el recopilador autorizado también retiran la publicación hasta revisión. Un aporte de la comunidad que repite una URL conserva su procedencia y no puede despublicar un aviso aprobado.

## Duplicados, vigencia y reportes

Una URL canónica repetida conserva un solo aviso y su procedencia; se eliminan parámetros de seguimiento conocidos para compararla. Contenido idéntico sin URL también se reconoce. Empresa, puesto, localidad y similitud señalan candidatos a duplicado, sujetos a revisión. Esta comparación tiene un límite de 1.500 avisos recientes para mantener bajo el costo; ampliar el índice antes de crecer mucho.

Se puede **Rechazar**, **Archivar** o **Marcar vencida** desde la revisión. Una fecha de cierre explícita se aplica automáticamente; una fecha sin hora incluye todo ese día en Salta. Un estado explícito `closed` de Jobicy archiva. `unknown`, un error de red o la ausencia del feed no significan cierre.

En Configuración, elegir a cuántos días pedir revisión si no hay cierre: por defecto 30. Pedir revisión por antigüedad no retira por sí solo el aviso; el detalle público lo advierte. Reportes públicos aceptan errores, cierres, sospechas y pedidos de retiro; el panel los lista. Contrastarlos y editar o archivar el aviso. Si el pedido exige respuesta, usar el contacto aportado por el canal que el responsable defina; el sistema no responde automáticamente.

## Fuentes

La base inicial no trae fuentes habilitadas. Ver `FUENTES.md` antes de dar de alta una.

- Registrar nombre, URL, método, frecuencia y URL de condiciones. Marcar autorización únicamente después de revisarla. Se puede deshabilitar cada fuente desde su formulario.
- El método **manual** es un registro de seguimiento: no simula una consulta automática. Usar Incorporar oferta.
- El adaptador **Jobicy** acepta únicamente su URL oficial. Está probado con fixtures; falta verificar acceso real. No habilitarlo hasta completar esa prueba. Retiene atribución y URL original, importa hasta 100 resultados por pasada y no recorre paginación: no promete cobertura total. Solo considera geografías explícitas compatibles y exige revisión humana de residencia y zona horaria.
- La frecuencia mínima implementada es seis horas. Un error se registra y se vuelve a intentar en la próxima ventana configurada. La consulta de estados revisa hasta 100 avisos almacenados, priorizando la comprobación más antigua. Conserva identificación de la fuente en el original recibido.

No ingresar credenciales en textos de avisos. No ejecutar instrucciones incluidas en contenido externo. No usar scraping para fuentes restringidas ni sesiones de terceros.

## Alertas y difusión

Las alertas públicas permanecen pendientes de configuración si falta proveedor, remitente o URL pública. En ese estado no se registra el correo. En desarrollo el trabajador no envía.

Para habilitar producción: validar el dominio remitente en Resend, configurar las variables, iniciar el programador y probar con una dirección propia autorizada: solicitud → correo de confirmación → confirmación explícita → oferta aprobada → resumen → baja → ausencia de nuevos envíos. Probar también carpeta de spam y supresiones del proveedor. No afirmar entrega por una aceptación de API: contrastar recepción.

La suscripción permite localidad, rubro, modalidad y frecuencia diaria/semanal; los filtros de localidad/rubro comparan el valor completo, ignorando mayúsculas, por lo que conviene copiar el nombre usado en el buscador. El consentimiento se confirma antes de alertar. La cola reserva cada pareja destinatario/oferta y comprueba aprobación, vigencia y consentimiento antes de enviar. La baja visible y de un clic cancela pendientes. Los registros privados permiten diagnosticar envíos sin inventar métricas.

WhatsApp y redes ofrecen texto/enlace manual solo para ofertas aprobadas y activas. Habilitar o deshabilitar cada preparación desde Configuración. Eso no activa una publicación automática. Publicar exclusivamente en canales propios y autorizados. Los adaptadores oficiales futuros, sus permisos y costos están pendientes en `COSTOS.md`.

## Publicidad

Abrir Publicidad; cargar nombre, URL HTTPS de imagen, destino, ubicación y fechas. Activar cuando corresponda. El sitio muestra **Publicidad** y respeta la ventana de fechas. Editar o desactivar desde la misma pantalla. Negociación y cobro son manuales. No hay medición de audiencia ni anuncios mezclados con avisos laborales. Usar imágenes optimizadas y con permiso; su alojamiento externo puede registrar visitas.

## Tareas, errores y recuperación

Ejecutar una corrida con `python -m salta_emplea.cli tasks`. `--only collect`, `--only expire` y `--only mail` permiten aislar etapas. Instalar cron en el servidor; el código no lo instala. Hay exclusión por archivo, transacciones, claves únicas, historial de corridas y reintentos de correo acotados. Revisar Fuentes, Tareas y Bandeja en el panel. Un reinicio marca corridas inconclusas como interrumpidas y recupera el procesamiento idempotente.

Una entrega de correo incierta se detiene. Verificar el registro en Resend y conciliar sin reenviar con `python -m salta_emplea.cli reconcile-mail ID --result sent` o `--result cancelled`. No borrar reservas para forzar un reenvío. Los errores temporales confirmados admiten hasta tres intentos con espera y la misma clave dentro de 23 horas; después requieren revisión.

Hacer respaldo consistente con `python -m salta_emplea.cli backup DESTINO_NUEVO`. Guardar también uploads y configuración privada por separado, cifrar las copias externas y probar restauración. Nunca copiar solamente un archivo SQLite mientras escribe. Recomendación inicial: copia diaria, retención de 30 días; debe implementarse en el servidor y comunicarse en privacidad. No se instaló retención automática de datos ni de copias.

Para eliminar un correo solicitado por su titular: verificar la solicitud y usar `python -m salta_emplea.cli forget-email CORREO`. Elimina suscripción, bandeja, reservas y contacto de reportes coincidente. Considerar también copias con retención. Revisar y eliminar imágenes huérfanas y aportes rechazados según la política que se publique.

Excluir las rutas de confirmación y baja de logs completos de acceso; contienen tokens. No registrar cuerpos de correo ni secretos. Gunicorn está preparado con registros de errores sin access log. Configurar también el proxy. El responsable debe monitorizar caídas, tareas fallidas, espacio libre y backups; no hay servicio externo de monitoreo contratado.

## Antes del lanzamiento público

Confirmar marca y dominio; completar nombre/contacto del responsable en Privacidad y Condiciones; aprobar presupuesto; configurar HTTPS, secretos y cron; probar backup/restauración en el servidor; completar prueba real de fuentes y correo; revisar visualmente en celulares. No hay datos de demostración en la base inicial. No publicar el entorno de desarrollo.
