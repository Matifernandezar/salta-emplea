# Respaldos y recuperación PostgreSQL

La producción de Salta Emplea usa PostgreSQL; el comando histórico `backup` de SQLite **no respalda esa base**. En PostgreSQL, las imágenes privadas también están en la tabla `uploads`, por lo que quedan incluidas en `pg_dump` junto con ofertas, procedencia, decisiones, suscriptores e historial de envíos. No se necesitan archivos efímeros de Vercel para recuperar esas imágenes.

Esta entrega añade una utilidad local y un ensayo automatizado con PostgreSQL 17. **No instala una programación de copias, destino externo, cifrado, retención ni alertas de respaldo en producción. Tampoco acredita que se haya respaldado o restaurado la base real.** La recuperación temporal que ofrezca Neon es una ayuda adicional; no sustituye una copia independiente y protegida.

## Requisitos y separación de entornos

- Ejecutar el respaldo desde una máquina administrativa protegida, fuera de una petición HTTP o función efímera de Vercel.
- Instalar `pg_dump` y `pg_restore` 17 o posteriores. El cliente de respaldo debe ser compatible con la versión del servidor; un servidor posterior requiere actualizar el cliente. Para restaurar, usar un cliente al menos tan nuevo como el que creó el archivo.
- Instalar las dependencias del proyecto y obtener el código del commit que se desea operar.
- Configurar `DATABASE_URL` únicamente mediante el entorno privado de esa máquina. No colocar una URL con contraseña en argumentos, historial del shell, capturas o documentación. Usar la conexión directa del proveedor para el respaldo cuando esté disponible; no asumir que un pooler admite todas las operaciones de `pg_dump`.
- Usar una cuenta de PostgreSQL con solo los permisos necesarios para leer los objetos de la aplicación y realizar el respaldo; evitar la cuenta de administración general.
- Crear un directorio privado fuera del checkout, con permisos `0700` y espacio suficiente. `backups/` está ignorado por Git, pero una copia fuera del repositorio reduce errores humanos. No subir archivos de respaldo a GitHub, artefactos públicos o carpetas compartidas.

La biblioteca recibe la conexión por configuración privada y pasa sus campos a las variables de libpq. Nunca coloca host, usuario, contraseña o URL entre los argumentos del proceso, ni hereda claves de correo/Google del entorno de la aplicación. Se descartan `stderr` y mensajes externos del cliente; los errores expuestos son códigos y textos fijos. Las variables de entorno también son accesibles al sistema y a procesos con permisos suficientes: utilizar una máquina confiable y un gestor privado de secretos.

Se admiten conexiones PostgreSQL con parámetros habituales de TLS y `channel_binding`; se rechazan servicios y opciones arbitrarias como `service` y `options`. Si la conexión actual depende de ellos, revisar una conexión directa compatible sin quitar TLS ni exponer credenciales.

## Crear y comprobar una copia

La interfaz de biblioteca, que no inicia Flask ni tareas, es:

```python
import os
from salta_emplea.backup import backup_postgres, verify_archive

backup_postgres(os.environ["DATABASE_URL"], "/ruta/privada/respaldo-nuevo.dump")
verify_archive("/ruta/privada/respaldo-nuevo.dump")
```

Los nombres de archivo son ejemplos; las credenciales nunca van en el script. Crear el directorio antes: la utilidad no crea directorios ni sobrescribe archivos existentes.

También están disponibles estos comandos administrativos, antes de iniciar Flask:

```bash
python -m salta_emplea.cli backup-postgres /ruta/privada/respaldo-nuevo.dump
python -m salta_emplea.cli verify-backup /ruta/privada/respaldo-nuevo.dump
python -m salta_emplea.cli restore-postgres-isolated /ruta/privada/respaldo-nuevo.dump --confirm-isolation
```

El primer comando lee `DATABASE_URL` del entorno privado; el último lee `POSTGRES_RESTORE_URL`. El indicador `--confirm-isolation` confirma la revisión manual del servidor aislado, la red y el rol; no realiza ese aislamiento. Ninguno acepta una URL con credenciales como argumento ni arranca la aplicación. Revisar las condiciones de restauración que siguen antes de ejecutarlo.

Se generan dos archivos nuevos con permisos `0600`:

- El archivo `.dump`, en formato custom de PostgreSQL y consistente según la instantánea de `pg_dump`.
- Su manifiesto `.dump.json`, con versión del formato, versión principal del cliente, fecha UTC, tamaño y SHA-256. No contiene URL, credenciales ni nombres de personas.

`verify_archive` comprueba tipo de archivo, permisos, tamaño y checksum. **Un checksum confirma integridad, no procedencia, inocuidad del SQL ni capacidad de restauración.** Conservar ambos archivos juntos y hacer ensayos de restauración.

Si falla el proceso o vence su tiempo, la utilidad retira los archivos creados por ese intento sin tocar copias anteriores. También limpia al interrumpir con Ctrl+C. Un apagado abrupto o SIGKILL puede dejar un archivo sin manifiesto: no restaurarlo. Los errores al limpiar o un disco averiado requieren revisar el directorio; ningún archivo incompleto se considera un respaldo válido.

El archivo `pg_dump` **no está cifrado**. Contiene correos, cuerpos de confirmación y baja, aportes, imágenes y otros datos sensibles. Los permisos locales no reemplazan el cifrado. Antes de transferirlo, usar cifrado autenticado y guardar la clave en un gestor separado; verificar que la copia externa permita recuperar ambos archivos sin depender del mismo proveedor de la base. No borrar la copia local hasta comprobar la externa.

## Política operativa propuesta, todavía no instalada

Objetivo inicial: copia diaria, 30 días de retención, al menos una copia externa cifrada y un ensayo mensual en un entorno aislado. Esto propone un RPO de hasta 24 horas **solo cuando la ejecución y entrega de la última copia se hayan comprobado**. El RTO depende del tamaño y del ensayo medido; no se promete un tiempo de recuperación antes de medirlo.

Antes de activar esta política, el titular debe definir o aprobar un destino privado, sus límites y costos, la custodia de la clave de cifrado y un canal de aviso autorizado. Luego se instala el programador, se verifica una ejecución real y se registra éxito/fallo, antigüedad de la última copia, tamaño, checksum y fecha del último ensayo. Los mensajes no deben incluir DSN, correos ni contenido del respaldo.

La retención se aplica solamente a las copias propias que ya tengan una entrega externa comprobada. No borrar automáticamente archivos de directorios generales ni aplicar una regla de limpieza a producción. Coordinar la retención de datos personales y las solicitudes de eliminación con la política pública: una baja no elimina mágicamente una copia histórica.

## Ensayo seguro de restauración

Un archivo PostgreSQL contiene SQL ejecutable, incluso funciones y disparadores. Tratarlo como contenido no confiable. Restaurar únicamente copias propias de procedencia comprobada, con rol limitado y en un servidor de pruebas sin acceso ni secretos de producción. La utilidad **no convierte un archivo malicioso en seguro**. El aislamiento del servidor y de su red es responsabilidad del entorno; un nombre de base no prueba aislamiento.

Preparación manual:

1. Disponer de un servidor PostgreSQL desechable de pruebas y una base nueva y vacía cuyo nombre sea `salta_restore_` seguido de entre 16 y 32 caracteres hexadecimales. La utilidad no crea ni borra bases.
2. Configurar `POSTGRES_RESTORE_URL` en su entorno privado. No reutilizar la URL ni credenciales de producción. El rol restaurador debe ser propietario de esa base aislada y carecer de permisos de superusuario, creación de roles o administración de otras bases.
3. Mantener la aplicación, programadores, claves de proveedores y acceso público desconectados de esa copia.
4. Verificar los dos archivos privados y ejecutar:

```python
import os
from salta_emplea.backup import restore_postgres_isolated

restore_postgres_isolated(
    "/ruta/privada/respaldo-nuevo.dump",
    os.environ["POSTGRES_RESTORE_URL"],
    isolation_confirmed=True,
)
```

La confirmación declara que el operador comprobó el aislamiento. La utilidad exige el prefijo reservado, rechaza un destino con objetos, comprueba el archivo y usa `pg_restore --single-transaction --exit-on-error`, sin `--clean` ni `--create`. No existe un endpoint web para restaurar. Un error de restauración requiere revisar el destino; no se reintenta automáticamente.

Tras restaurar, una transacción pone la copia en cuarentena: deshabilita fuentes, da de baja los suscriptores de esa copia, cancela la cola no finalizada y retira leases de trabajadores. No modifica la base original, no inicia la web, no envía mensajes ni consulta fuentes. Si falla esta cuarentena, la copia debe seguir desconectada y no se declara éxito. Esta defensa adicional no reemplaza la ausencia de secretos y programación en el entorno de ensayo.

Comprobar después ofertas y procedencia, claves foráneas, restricciones, imágenes privadas, migración aplicada e historial; verificar que no se haya publicado una oferta pendiente ni iniciado envíos. Registrar tamaño, duración y resultado sin datos personales. Destruir solo la base de pruebas mediante el administrador del entorno cuando termine el ensayo.

## Recuperación ante un incidente real

El ensayo acredita recuperación de datos en aislamiento; no cambia la base de producción ni realiza una promoción automática. Para recuperar el servicio:

1. Detener programadores y envíos y preservar la evidencia del incidente. Mantener Google Vision en pausa. No borrar la base original.
2. Seleccionar una copia propia anterior al incidente, comprobar integridad y ensayar su restauración aislada. Medir cuánto dato reciente falta y revisar cambios de esquema posteriores al archivo.
3. Validar qué aprobaciones, correcciones, bajas y entregas ocurrieron después del respaldo. Un respaldo antiguo puede reintroducir avisos retirados o destinatarios dados de baja. Resolverlos antes de volver a servir datos o enviar correos.
4. Preparar una nueva base y la configuración privada por un procedimiento administrativo revisado; una promoción de producción requiere autorización concreta sobre el destino. Esta utilidad no sobrescribe producción. La cuarentena cambia estados de la copia intencionalmente: no reactivar suscriptores, fuentes ni cola masivamente para imitar el estado antiguo.
5. Comprobar salud SQL, ofertas públicas, permisos del panel e imágenes, con envíos y fuentes aún detenidos. Rehabilitar solamente lo conciliado con los registros actuales. Las entregas inciertas nunca se reenvían por defecto.
6. Actualizar la conexión privada del despliegue, verificar el servicio y conservar el despliegue/base anteriores para recuperación. Coordinar el rollback con las migraciones: revertir código no revierte una migración de base.

Un dump no contiene las variables de Vercel, registros DNS, identidad del dominio ni claves del proveedor de correo. Guardar un inventario de **nombres** de variables y un procedimiento para recuperarlas desde el gestor privado del titular; nunca incluir valores secretos en la guía o el archivo de Git. Algunas claves Sensitive son de escritura única y deben rotarse si se pierden. Registrar también commit desplegado, versión del servidor y migración para poder reconstruir un entorno compatible.

## Evidencia y límites de la validación

`tests/test_backup.py` verifica con procesos sustituidos permisos, no sobrescritura, ausencia de secretos en argumentos/manifiestos, limpieza de fallos/interrupciones, integridad y restricciones de restauración. Cuando existe `POSTGRES_TEST_URL`, también crea dos bases aleatorias y un rol limitado propios, migra el esquema, incorpora datos marcados **PRUEBA**, guarda una imagen, ejecuta `pg_dump` y `pg_restore` reales y comprueba integridad, cuarentena y ausencia de cambios en el origen. No envía mensajes, no aprueba ofertas y no usa credenciales de producción.

El workflow `Pruebas de Salta Emplea` instala el cliente PostgreSQL 17 y usa su servicio desechable PostgreSQL 17. El ensayo necesita permisos administrativos solo para crear y retirar sus bases/rol de pruebas; la copia y restauración se ejecutan con el rol limitado. Sin `POSTGRES_TEST_URL`, la prueba real queda omitida y no equivale a haber ensayado PostgreSQL localmente. El resultado definitivo debe citar el run de CI que realmente terminó; el código de la prueba no es evidencia de una ejecución exitosa.
