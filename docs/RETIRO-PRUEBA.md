# Retiro autorizado del aviso de prueba

El 20/10/2026 el titular pidió retirar el aviso de prueba que seguía publicado. Se confirmó públicamente que `/ofertas/1` contenía «Prueba 1», empresa «Prueba 2», y textos de prueba. La operación archiva ese registro; conserva contenido, procedencia e historial, y no aprueba ni modifica las ofertas reales.

El módulo `salta_emplea/launch_cleanup.py` solo actúa durante un build cuando el indicador `RETIRE_KNOWN_TEST_OFFER` está habilitado explícitamente, el entorno es producción y el origen público coincide con Salta Emplea. Exige el ID y cinco campos exactos del registro revisado. Si cambiaron, el resultado es `identity_mismatch` y no modifica nada. Si ya está privado o no existe, tampoco actúa.

El retiro, la auditoría y un marcador permanente se confirman en la misma transacción bajo bloqueo editorial. Un reintento no duplica la decisión ni vuelve a retirar el registro si el titular decide aprobarlo más adelante. No se eliminan filas ni reservas, no se consultan proveedores y no se copian secretos fuera del alojamiento.

Procedimiento de aplicación:

1. Aprobar las pruebas locales y las de PostgreSQL aislado con el indicador ausente en producción.
2. Integrar el código comprobado y habilitar el indicador solo en Production.
3. Desplegar y observar `SALTA_TEST_RETIREMENT` con resultado `archived` y cantidad uno. Si informa una identidad distinta, revisar; no relajar la coincidencia automáticamente.
4. Comprobar que `/ofertas/1` ya no es público y que la oferta real continúa accesible, junto con `/salud`.
5. Deshabilitar el indicador después de comprobar el resultado. Conservar el marcador y la auditoría.

El archivado es reversible desde el panel por decisión del titular. Un rollback de la interfaz no vuelve a publicar el aviso ni deshace esta decisión editorial. La ejecución real queda pendiente hasta registrar sus comprobaciones.
