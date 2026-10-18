# QA con navegador real

El workflow **Circuito real en Chromium** ejecuta Playwright Python 1.56.0 en
`ubuntu-latest`, sin contenedores y sin credenciales productivas. Usa el Python 3
preinstalado del runner e informa su versión en el registro. Los cambios relevantes
de la aplicación lo activan en `push` y `pull_request`; también admite ejecución
manual desde GitHub Actions.

**Ejecución verificada: 18/10/2026.** El [workflow real](https://github.com/Matifernandezar/salta-emplea/actions/runs/39102858915)
terminó correctamente con el commit `406e50e`. Completó el circuito local en
390 × 844 y 1440 × 1000 y verificó el backend público con PostgreSQL, filtros y
permisos, sin escribir datos en producción ni detectar desborde horizontal. Las capturas
públicas están en el artefacto de esa corrida. Su inspección visual manual y las
pruebas en dispositivos físicos siguen pendientes.

## Circuito cubierto

En Chromium con tamaños de pantalla 390 × 844 y 1440 × 1000, cada corrida crea su
propia aplicación Flask, SQLite e imágenes en una carpeta temporal. El navegador:

1. Abre la página pública y comprueba que el panel exige ingresar.
2. Envía un aviso identificado como **PRUEBA** mediante el formulario real.
3. Comprueba en una sesión anónima separada que continúa pendiente, oculto en el buscador y con detalle HTTP 404.
4. Ingresa al panel con una contraseña ficticia de QA y aprueba el aviso.
5. Busca y combina localidad, rubro, modalidad, jornada y fecha; comprueba también
   una modalidad sin coincidencias.
6. Abre la oferta y hace clic en su canal de postulación. Ese destino `example.test`
   se resuelve mediante una respuesta local simulada: no se contacta a empleadores.
7. Ejecuta dos lotes reales de comprobación de vigencia desde el panel y verifica
   sus registros, sin duplicar el aviso.
8. Cambia el enlace de postulación, guarda y comprueba que vuelve a revisión y
   desaparece del sitio público.

Comprueba desborde horizontal en la portada, resultados, listado administrativo,
edición y automatización. Esto verifica dimensiones y comportamiento; no reemplaza
una revisión visual manual ni prueba dispositivos físicos, correo, recopilación
externa, el circuito editorial autenticado en producción o la programación de cron de Vercel.

El servidor escucha únicamente en loopback, con puerto libre asignado por el
sistema; termina y elimina los datos al finalizar. No lee `.env` ni utiliza secretos
del entorno. El correo permanece deshabilitado, no existen fuentes configuradas y
el navegador bloquea otros destinos externos. No guarda sesiones, trazas ni datos
del panel. Guarda únicamente capturas de la portada local pública vacía y, cuando
responde correctamente, la portada pública de Vercel en
ambos tamaños. GitHub Actions conserva estas imágenes durante tres días en el
artefacto `capturas-publicas`; nunca captura formularios, contraseña o administración.

## Ejecución

En un entorno de desarrollo que permita instalar el navegador:

```sh
python3 -m venv .venv-navegador
.venv-navegador/bin/python -m pip install -r requirements-browser.txt
.venv-navegador/bin/python -m playwright install --with-deps chromium
.venv-navegador/bin/python scripts/browser_check.py
```

El flag `--check-public` agrega consultas de solo lectura a
`https://salta-emplea.vercel.app`, sin credenciales. Reconoce la vista preliminar
histórica o comprueba el backend: salud SQL, buscador y filtros GET, páginas de
aportes/alertas/privacidad/condiciones, redirección de rutas privadas al ingreso y
rechazo HTTP 401 de los tres cron sin credencial. Con base vacía, localidad, rubro y
jornada solo pueden comprobarse con su opción vacía; el circuito aislado sí prueba
valores concretos. No envía formularios ni aprueba ofertas en producción.

Bloquea métodos de escritura, servicios de terceros y service workers en el
navegador público. Las consultas HTTP auxiliares están escritas explícitamente
como GET al mismo origen. Un error en la comprobación pública solicitada hace
fallar el workflow; los mensajes previos del circuito local conservan su resultado
separado. El helper privado se prueba como archivo local y solo se exige por HTTPS
cuando todavía se detecta la publicación preliminar.

Las capturas necesitan inspección humana; no demuestran entrega de correo,
autenticación con la contraseña del titular ni programación automática.
