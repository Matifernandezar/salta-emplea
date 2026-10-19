# Lectura de imágenes sin una API de pago

Evaluación técnica del **19/10/2026**. Estado: **ensayo local, no integrado en producción**. No se hicieron llamadas a Google ni a otro proveedor OCR; no se instalaron servicios o modelos. Google Vision permanece en pausa por decisión del titular. La pausa efectiva requiere desplegar `OCR_ENABLED` desactivado; conservar clave, historial y reservas no reactiva lecturas por sí solo.

## Decisión para esta entrega

Conservar la **carga de imagen privada y transcripción manual** como alternativa operativa. El ensayo demuestra que hay opciones sin tarifa por API, pero no demuestra precisión suficiente en español ni funcionamiento en el alojamiento actual. No presentar esta evaluación como una nueva integración terminada.

Si se retoma OCR, el primer candidato es un lector opcional **solo en el panel privado**, ejecutado en el navegador, después de una prueba con modelo español y teléfonos reales. Evita incorporar un servicio persistente nuevo, pero consume descarga, memoria, CPU y batería del dispositivo. La alternativa de servidor exige empaquetado y medición propios. Ninguna opción debe aprobar avisos ni publicar imágenes automáticamente.

## Evidencia reproducible

El entorno de desarrollo ya traía Tesseract **5.5.0**, con `eng` y `osd`; **no tenía `spa`**. También tenía Tesseract.js **7.0.0** y su núcleo, pero no el modelo español. No se descargaron dependencias para completar este ensayo.

Se generaron con Pillow tres imágenes propias rotuladas **PRUEBA — NO ES UNA OFERTA REAL**. No se incorporaron a ninguna base de datos ni se publicaron. Se inspeccionaron visualmente: texto pequeño de 17 px; texto de 25 px con desenfoque gaussiano de 1,2 px; flyer de dos columnas con encabezado y pie. El texto incluye tildes, localidad, modalidad, horario, importe, moneda, período, correo `example.test` y fecha ficticios.

Medición final local: Linux x86_64, modelo **inglés**, segmentación automática `--psm 3`, fuente DejaVu Sans. Una pasada por caso; no es un promedio ni un estudio representativo.

| Caso | Dimensiones | PNG | Tiempo transcurrido | CPU de procesos hijos | Error de caracteres | Error de palabras |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Texto pequeño | 1000 × 500 | 35.010 bytes | 0,890 s | 1,147 s | 1,91 % | 8,77 % |
| Desenfoque | 1000 × 650 | 119.481 bytes | 0,985 s | 1,355 s | 1,09 % | 7,02 % |
| Dos columnas | 1100 × 750 | 52.861 bytes | 1,015 s | 1,325 s | 47,14 % | 47,73 % |

El error usa distancia de edición frente a la transcripción conocida. Se normalizan mayúsculas, espacios y Unicode NFC; **no** se eliminan tildes, signos ni el orden de lectura. En el flyer el motor colocó el pie antes de la columna derecha: esa alteración aumenta el error de secuencia, aunque muchas palabras individuales se reconozcan. No interpretar el complemento del error como una exactitud general del producto.

Los tres casos conservaron literalmente `850.000`, `pruebas@example.test` y `31/12/2026`, pero fallaron las palabras con tildes seleccionadas (`atención`, `administración` u `organización`). Por ejemplo, `atención` se convirtió en `atencién`. **Tres coincidencias de importe/contacto/fecha no garantizan que esos campos se lean bien en avisos reales.** El modelo inglés limita expresamente esta evaluación de textos en español.

Pico observado de procesos hijos durante todo el ensayo: **35.824 KiB**. No incluye el consumo completo de Python/Pillow, no es una medición por imagen y **no** mide navegador ni Vercel. Tesseract utilizó varios hilos; por eso la suma de CPU puede superar el tiempo transcurrido. El servidor local dispone de optimizaciones que no deben suponerse presentes en un teléfono o una función de producción.

Para repetir, con dependencias ya instaladas y un directorio nuevo fuera del repositorio:

```bash
.venv/bin/python scripts/benchmark_ocr_local.py --output /tmp/salta-ocr-ensayo-propio --language eng
```

El script guarda las tres imágenes, sus transcripciones esperadas, resultados OCR y `resultado.json`. No usa red, credenciales, Flask ni bases de datos; rechaza modelos ausentes y destinos existentes. Si el sistema ya tiene un modelo español revisado, repetir con `--language spa`; el script no lo instala. Mantener los resultados como material de prueba, fuera de producción.

## Comparación de alternativas

| Alternativa | Recursos y costo | Compatibilidad pendiente | Evaluación |
| --- | --- | --- | --- |
| Transcripción manual | Tiempo editorial, más almacenamiento/transferencia y saneado de archivos existentes | Ya disponible en el panel; contrastar cada campo | Opción conservada para lanzar |
| Tesseract.js en navegador | Sin tarifa OCR por solicitud; CPU/memoria/batería del titular y transferencia de archivos del sitio | Modelo español, memoria real de celulares, descargas, CSP y cancelación | Candidato para otra fase; no integrado |
| Tesseract en la función Flask | Sin tarifa de API; CPU, memoria, arranque y almacenamiento/transferencia según plan | Binario Linux, bibliotecas, modelo, tamaño del despliegue y recuperación ante timeout | No empaquetado ni probado en Vercel |
| Trabajador externo propio | Costo del servidor, almacenamiento, mantenimiento y monitoreo | Nueva infraestructura y traslado privado de archivos | Desproporcionado sin volumen demostrado; no contratado |

### Navegador

Tesseract.js ejecuta el motor mediante WebAssembly y trabajadores. Su instalación habitual descarga núcleo y modelos; deben fijarse versiones y servir los archivos revisados desde el mismo origen para evitar dependencias de CDN durante el uso. La documentación recomienda reutilizar un trabajador y medir la primera carga con caché vacía. [Proyecto oficial](https://github.com/naptha/tesseract.js), [instalación local](https://github.com/naptha/tesseract.js/blob/master/docs/local-installation.md), [rendimiento](https://github.com/naptha/tesseract.js/blob/master/docs/performance.md).

En los paquetes locales se midieron **62.961 bytes** para `tesseract.min.js` y **111.307 bytes** para `worker.min.js`. Los archivos alternativos del núcleo ocupan aproximadamente **2,8–4,5 MiB cada uno**, según formato y variante. No se suman todas las variantes como si el navegador descargara todas. El total comprimido de una primera sesión con `spa`, la caché y el tiempo con conexión lenta **no se midieron** porque falta ese modelo. Son costos de transferencia, además del cómputo del dispositivo; no llamar a esto “OCR gratis”.

La aplicación actual tiene `script-src 'none'`. Un lector requeriría habilitación específica y revisada de scripts locales, trabajadores y compilación WASM en la ruta privada. No reemplazar la política por permisos generales ni agregar `unsafe-inline` para facilitar la integración. La opción debe cargar solo al solicitarla, ofrecer progreso/cancelación, procesar una imagen acotada por vez y permitir seguir transcribiendo si no hay recursos. No se modificó la CSP en esta evaluación.

### Servidor y presupuesto

Vercel documenta límites de tamaño del paquete, memoria y duración; el proyecto tiene `maxDuration` de 300 s. Un `pip install` de una envoltura no aporta el ejecutable Tesseract ni sus bibliotecas/modelos. No hay evidencia de que estén incluidos en el despliegue existente. El límite publicado de Python es 500 MB sin comprimir en funciones estándar; eso **no certifica** que un paquete concreto funcione. [Límites oficiales de funciones](https://vercel.com/docs/functions/limitations).

El costo debe calcularse con el plan y región reales: invocaciones + CPU activa total + memoria provisionada × duración + transferencia y almacenamiento, además de costos fijos e impuestos aplicables. Las mediciones locales anteriores no son una cotización de Vercel. No se verificó consumo OCR de producción, ni se contrató un servicio adicional dentro del presupuesto de USD 30. Antes de integrar servidor, desplegar una prueba aislada sin claves de producción y medir tamaño, arranque, CPU/memoria y límite de tiempo.

## Licencias, privacidad y aceptación futura

Tesseract, Tesseract.js y los modelos oficiales `tessdata_fast` declaran Apache-2.0. Fijar el origen y versión exactos del modelo y conservar licencias/avisos correspondientes junto con sus dependencias; no atribuir automáticamente esa licencia a cualquier modelo de terceros. [Licencia del motor](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE), [modelos oficiales](https://github.com/tesseract-ocr/tessdata_fast).

La precisión cambia con resolución, segmentación y tratamiento de la imagen; una imagen legible para una persona puede fallar. [Guía oficial de calidad](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).

Antes de habilitar una alternativa:

1. Evaluar `spa` con flyers propios/autorizados representativos, errores de acentos, cifras, separadores, correos, teléfonos y orden de columnas; registrar transcripción y diferencias sin corregirlas silenciosamente.
2. Medir primera carga y cargas siguientes en celular de recursos modestos, con red lenta y cancelación. Definir límites de píxeles, memoria y tiempo a partir de los resultados, sin bloquear la carga manual.
3. Mantener permiso de extracción separado del permiso de publicación. Las imágenes originales siguen privadas; el texto extraído es dato externo sin capacidad de ejecutar instrucciones.
4. Guardar transcripción original, evidencia literal e incertidumbres; no completar campos sin respaldo ni sobrescribir correcciones del titular. Importes, contactos y fechas requieren contraste editorial.
5. Probar que guardar o repetir la lectura no aprueba ni publica, que la imagen solo responde con sesión autorizada y que detener el OCR conserva auditoría e historial.

La limitación de OCR no bloquea la entrega acordada: **carga y transcripción manual, fuente autorizada, aprobación y alertas**. No hay una alternativa automática validada para anunciar al público todavía.
