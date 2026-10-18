# Instagram, Computrabajo y LinkedIn

Estado revisado el **18 de octubre de 2026, UTC**. El usuario eligió estas tres fuentes y confirmó que **@empleosalta12 pertenece a otra persona**. Esta selección no demuestra permiso de extracción, acceso a una API ni derecho a republicar imágenes. No se contactó al titular de la cuenta ni a los portales.

El catálogo de `salta_emplea/source_catalog.py` guarda referencias locales para el panel. No hace solicitudes de red, no crea ofertas y no habilita recopilaciones. Todas las opciones tienen método manual, estado deshabilitado, `authorized=False` y `automation_ready=False`. El registro de una referencia en el panel tampoco equivale a habilitar una integración.

## Estado por fuente

| Fuente | Comprobado | Pendiente para recopilar automáticamente |
|---|---|---|
| [Instagram @empleosalta12](https://www.instagram.com/empleosalta12/) | La cuenta es ajena, según el usuario. La colección oficial de Meta para Instagram con Facebook Login contempla consultas de metadatos de otras cuentas Business/Creator. No se comprobó el tipo de esta cuenta ni acceso a sus publicaciones o imágenes. | Verificar elegibilidad de ambas cuentas, campos de publicaciones disponibles, permisos y revisión de la aplicación, límites y autorización de reutilización. No hay conexión activa. |
| [Computrabajo en Salta](https://ar.computrabajo.com/trabajo-en-salta) | Al abrir el aviso legal en esta revisión, la herramienta recibió una pantalla que exige JavaScript y comprobar que no se es un robot. No pudo leerse el documento completo ni verificarse una API de búsqueda disponible para este proyecto. | Conseguir y revisar las condiciones vigentes y un mecanismo oficial o autorización expresa. No se intentó superar la comprobación del sitio. |
| [LinkedIn Empleos](https://www.linkedin.com/jobs/) | El acuerdo de usuario, sección 8.2, restringe scraping y copia automatizada de información. Su documentación de Job Posting describe publicación de empleos mediante integraciones, no una API general para buscar avisos ajenos. | Acceso oficial de lectura y autorización de reutilización. Una integración para publicar ofertas no resuelve la búsqueda solicitada. |

El documento [FUENTES.md](FUENTES.md) conserva una revisión anterior, del 16/10, que encontró un resultado indexado del aviso legal de Computrabajo sobre robots/crawlers. La lectura actual no permitió confirmar el texto completo ni su versión: no se presenta ese fragmento previo como una nueva verificación jurídica.

## Trabajo disponible mientras se resuelven los accesos

Se puede conservar el enlace de cada aviso y preparar su versión para revisión. El texto o la imagen deben aportarse con permiso de uso; que un aviso sea público no concede por sí solo permiso para copiarlo. El acceso manual nunca debe eludir inicios de sesión, captchas o bloqueos.

Una imagen enviada por un empleador o por la comunidad debe mantenerse como original privado durante la revisión. Su extracción de texto y campos debe mostrar las dudas y no inventar datos. La elección de estas fuentes no acredita que exista ya una lectura automática de imágenes conectada. Ningún original, enlace o texto importado puede ejecutar instrucciones dentro del sistema.

Toda oferta nueva sigue pendiente hasta aprobación del administrador. Un cambio material debe devolverla a revisión. No se activará una consulta periódica a estas fuentes hasta comprobar acceso, términos, frecuencia y credenciales reales.

## Referencias oficiales y alcance de la consulta

- [Meta: Instagram API with Facebook Login, colección oficial en Postman](https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login). La documentación específica de Business Discovery respondió con límite de solicitudes (429) durante la revisión; no se verificó un circuito real de lectura de medios.
- [Meta: condiciones de recopilación automatizada](https://www.facebook.com/legal/automated_data_collection_terms). Revisar sus condiciones aplicables antes de conectar una fuente.
- [Computrabajo: aviso legal](https://ar.computrabajo.com/avisolegal/). Su contenido quedó sin comprobar en esta consulta por la pantalla de acceso descrita.
- [LinkedIn: acuerdo de usuario, sección 8.2](https://www.linkedin.com/legal/user-agreement#dos). Consultado para las restricciones de extracción automatizada.
- [Microsoft Learn: LinkedIn Job Posting](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/overview). Describe integración de publicación de empleos; no acredita búsqueda o descarga de ofertas ajenas.

No se crearon cuentas, compraron servicios, enviaron mensajes ni habilitaron fuentes de producción para esta evaluación.
