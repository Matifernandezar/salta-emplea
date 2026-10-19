# Retención y limpieza manual

La limpieza no está programada ni habilita borrados en producción por instalar el módulo. Debe revisarse una vista previa, disponer de un respaldo y aprobar una aplicación concreta. No se ejecutó una limpieza de producción durante el desarrollo.

## Qué se puede eliminar

La propuesta inicial elimina huellas de límites de solicitudes cuando su contador ya venció, y solicitudes de suscripción que llevan **más de 30 días sin confirmar**. Los enlaces de confirmación vencen a las 48 horas; los 30 días ofrecen un margen adicional antes de limpiar solicitudes abandonadas. El plazo puede aumentarse, nunca reducirse por debajo de 30 días con este módulo.

Un suscriptor es elegible únicamente si permanece pendiente, no registra confirmación ni envío y no tiene reservas de entrega. Si hay correos asociados, solo se eliminan confirmaciones antiguas en estado pendiente o cancelado que **nunca se intentaron enviar**. Se comprueban también las referencias desde `deliveries` y el registro `mail_reserved`, aunque alguien hubiera reiniciado los campos de intentos de la bandeja. Una confirmación reciente protege al suscriptor aunque la primera solicitud sea antigua.

No se eliminan suscripciones confirmadas o dadas de baja, ofertas, versiones, reportes, auditorías, reservas de OCR, reservas de correo, entregas inciertas, registros de webhooks, supresiones ni registros de respaldos. Suprimir estos registros podría permitir reenvíos, consultas o lecturas repetidas y perder evidencia editorial. Una solicitud individual de eliminación requiere un procedimiento específico que contemple estos registros; esta herramienta no lo reemplaza.

Si los datos tienen fechas inválidas, una historia de más de 20 confirmaciones o referencias que no se pueden resolver con certeza, se conservan para revisión.

## Configuración

Documentar y cargar estas variables por nombre en la configuración de la aplicación:

| Nombre | Propuesta inicial | Rango admitido | Motivo |
| --- | --- | --- | --- |
| `RETENTION_UNCONFIRMED_DAYS` | 30 días | 30 a 3650 | Dejar margen después del vencimiento de confirmación. |
| `RETENTION_BATCH_LIMIT` | 100 filas | 1 a 1000 | Acotar cada aplicación contando suscriptores y correos eliminados juntos. |
| `RETENTION_SCAN_LIMIT` | 1000 registros por categoría | 1 a 10000 | Evitar recorridos ilimitados en una ejecución manual. |

Los valores fuera de rango detienen la operación; no se interpretan como ausencia de límites. Los límites de solicitudes se procesan antes que las suscripciones. Si un suscriptor y sus confirmaciones no caben completos en el presupuesto de filas, permanece intacto. Una fila de auditoría agregada al aplicar cambios no forma parte del presupuesto de filas eliminadas.

La respuesta indica si el recorrido quedó truncado. En ese caso los conteos describen la muestra examinada, no toda la base. Un lote repetido puede avanzar al retirar registros elegibles, pero una acumulación de datos protegidos o inválidos puede requerir revisión específica; aumentar el límite no debe hacerse a ciegas.

`RETENTION_APPLY_CONFIRMED` es un booleano interno que el CLI debe establecer únicamente después de la confirmación explícita. No debe incorporarse como variable de entorno que active borrados, ni aceptarse desde formularios o contenido externo.

## Interfaz y operación

El módulo expone `preview(conn, config)` y `apply(conn, config)`. El CLI integra `python -m salta_emplea.cli retention-preview` (solo lectura) y `python -m salta_emplea.cli retention-apply --confirm-deletion` (aplicación explícita). Sin la opción de confirmación, la aplicación se rechaza. No ejecutar este último comando en producción sin revisar una limpieza concreta y su respaldo.

1. Comprobar el entorno y la base seleccionada, sin mostrar la URL privada. Revisar la autorización del titular para esa limpieza concreta.
2. Tener un respaldo PostgreSQL consistente y un procedimiento de restauración previamente probado; el backup SQLite no cubre producción. Consultar [RESPALDOS.md](RESPALDOS.md).
3. Ejecutar la vista previa. Devuelve política, antigüedad de corte, registros examinados, candidatos, selecciones acotadas y elementos protegidos. No muestra direcciones de correo, tokens, nombres de archivos ni huellas de red.
4. Revisar los conteos y aplicar de forma explícita. La aplicación calcula nuevamente el plan dentro de la transacción; no acepta IDs guardados de una vista previa antigua.
5. Revisar los conteos realmente eliminados y el evento `retention_applied`. Si no hay cambios, repetir la aplicación es una operación sin efecto y no agrega otro evento.

Las eliminaciones de confirmaciones y suscriptores se realizan explícitamente, sin cascadas. El módulo usa los bloqueos compartidos de correo y edición, y en PostgreSQL bloquea cada fila de suscriptor antes de revalidarla. Un error revierte el lote completo. Las rutas que modifican consentimiento deben seguir respetando el bloqueo de correo al integrarse con este circuito.

## Imágenes: inventario, sin eliminación

La vista previa inventaría nombres de `uploads` en PostgreSQL o entradas directas del directorio privado local. No lee el contenido de archivos, no recorre subcarpetas ni sigue enlaces simbólicos. Clasifica referencias editoriales, referencias en el historial de OCR y elementos sin referencia identificada que necesitan revisión. Si no puede acceder al directorio, informa que el inventario no está disponible.

**No se elimina ninguna imagen**, ni siquiera cuando el inventario no encuentra referencias. Las versiones, los registros históricos, permisos de extracción o una operación concurrente pueden necesitarla. No se debe borrar una reserva de OCR para convertir la imagen en huérfana o habilitar un nuevo intento.

Habilitar eliminación de imágenes exigiría un diseño adicional: referencias completas, exclusión de cargas en curso, retención aprobada, comprobación contra respaldos, protección frente a enlaces simbólicos y recuperación verificable. Mientras eso no exista, el resultado es una lista agregada de pendientes de revisión.

## Evidencia y límites

Las pruebas aisladas cubren vista previa sin escrituras, autorización explícita, fechas y límites inválidos, preservación de correos intentados o inciertos, reservas, supresiones, referencias cruzadas, presupuesto de filas, reejecución y rollback. El inventario prueba referencias editoriales y OCR y que no se abran archivos ni sigan enlaces.

Existe una prueba adicional con PostgreSQL real mediante `POSTGRES_TEST_URL`: crea un esquema de prueba aleatorio, verifica el bloqueo compartido de correo, conserva imágenes y reservas y lo elimina al terminar. Si esa variable no está configurada, se omite y debe informarse. Ninguna de estas pruebas constituye una limpieza real de producción ni una política legal definitiva de conservación.
