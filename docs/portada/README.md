# Portada de Salta Emplea

Entrega de diseño e implementación del 20 de octubre de 2026. Usa Flask y HTML renderizado en servidor; no cambia el esquema de datos ni agrega dependencias de interfaz.

## Decisiones y recorrido

La acción principal es buscar, filtrar, abrir una ficha y consultar su canal de postulación. El buscador muestra puesto/palabra y ubicación antes de los filtros adicionales. Las ofertas aparecen antes de los módulos secundarios en el orden del documento. Publicar una oferta es una acción secundaria que conserva el formulario existente.

Se conserva la marca y su símbolo. La identidad usa verde profundo, superficies claras, tipografía del sistema, contenedor de 1120 px, foco visible y controles táctiles. No descarga fuentes ni imágenes decorativas. La navegación móvil permanece visible y se adapta sin un menú dependiente de JavaScript.

Las tarjetas muestran datos persistidos y la fecha de incorporación, que no sustituye la fecha original del aviso. El orden es la última incorporación. Empresa, localidad, jornada y otros datos ausentes conservan el tratamiento «No informado». Una revisión editorial no se presenta como certificación empresarial.

## Secciones, intención y destinos

| Sección | Necesidad | Destino real |
| --- | --- | --- |
| Portada y buscador | Trabajo y empleos en Salta | `/`, con filtros GET existentes |
| Ofertas recientes | Consultar oportunidades publicadas | `/ofertas/{id}` existente |
| Rubros | Explorar un sector informado | `/?sector=…#ofertas` |
| Localidades | Explorar lugares de trabajo físicos | `/?location=…#ofertas` |
| Medio tiempo | Jornada explícitamente informada | Filtro por la jornada disponible, solo cuando existe |
| Guía de CV | Preparar la primera postulación | `/guias/cv-sin-experiencia` |
| Guía de postulación | Escribir un mensaje y revisar el destino | `/guias/como-postularse` |
| Guía de riesgos | Reconocer señales y reportar | `/guias/ofertas-laborales-falsas` |
| Empleadores | Aportar una búsqueda para revisión | `/publicar` |
| Contacto y privacidad | Pedir ayuda o conocer el tratamiento de datos | Enlaces existentes con identidad configurada |

Rubros, localidades y cantidades salen de ofertas ya publicables. Las localidades excluyen filas remotas. No se inventan categorías para completar el diseño. No se agrega un acceso «Sin experiencia» porque el modelo actual no conserva una comprobación estructurada de admisión de principiantes. Tampoco se ofrece un acceso remoto como si garantizara elegibilidad de residencia: ese dato aún requiere revisión editorial. Se conserva el filtro de modalidad existente y la advertencia de comprobar residencia y horarios.

La búsqueda tolera acentos y consulta también el rubro. Los filtros se conservan en la URL; se puede quitar uno sin perder los demás. Un estado vacío general y una búsqueda sin coincidencias tienen mensajes y acciones diferentes. Los errores de parámetros conservan la validación existente.

## SEO y accesibilidad

La portada tiene un H1, encabezados H2 por sección y cargos H3. Title: «Trabajo en Salta y ofertas de empleo | Salta Emplea». Metadatos y contenido principal se renderizan sin JavaScript. Las tres guías tienen URL, canonical y metadatos propios, enlaces HTML y presencia en el sitemap. No se añade JobPosting a listados o guías.

Las búsquedas y variaciones de filtros conservan la política existente de noindex. No se generan páginas indexables para todas las combinaciones. La navegación conserva URLs de fichas y formularios ya publicados.

Campos con etiquetas visibles y fuente móvil de al menos 16 px; controles con foco y acciones sin hover. El resultado tiene un estado accesible y filtros con nombres que explican qué se elimina. El CSS respeta movimiento reducido. Los anuncios solo ocupan lugar cuando existe una configuración vigente, mantienen el rótulo «Publicidad» y enlaces patrocinados. Las imágenes publicitarias reservan dimensiones.

## Archivos principales

- `salta_emplea/homepage.py`: filtros y navegación derivados del inventario.
- `salta_emplea/guides.py`, `templates/guide.html`: tres guías propias.
- `templates/index.html`, `base.html`, `_macros.html`, `static/style.css`: portada, navegación y componentes.
- `app.py`, `domain.py`, `public_metadata.py`: contexto, búsqueda y metadatos.
- `tests/test_homepage_backend.py`, `tests/test_public_metadata.py`: comprobaciones de filtros, permisos editoriales y SEO.
- `scripts/check_homepage.py`, `.github/workflows/navegador.yml`: circuito aislado en Chromium y capturas.

## Reproducir las comprobaciones

Desde PowerShell en VS Code, con el proyecto instalado según el README principal:

```powershell
python -m pytest -q
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python scripts/check_homepage.py
```

El script crea una base temporal, usa avisos identificados como PRUEBA y bloquea destinos externos inesperados. No envía correo ni consulta Google Vision. Comprueba 360, 390, 768, 1024 y 1440 px, búsqueda con acentos, filtros, fichas, postulación interceptada en un destino ficticio, guías, estados vacíos y oferta cerrada. Las capturas y el JSON se escriben en `docs/portada/`; los resultados generados pertenecen al entorno de prueba y no son datos de producción.

El workflow también conserva una comprobación pública de solo lectura del sitio existente. Ese resultado no equivale a desplegar esta rama.

## Estado y límites

Las pruebas HTTP y el circuito de navegador pasaron en CI; el detalle figura en evidencia. Chromium no puede arrancar en el sandbox local por restricciones del sistema; el workflow realiza esa comprobación en un runner aislado. El intento local fallido no se presenta como una prueba aprobada.

Las alertas por correo siguen en pausa y no se ofrece un alta ficticia. Google Vision permanece deshabilitado. No se aprobaron ni modificaron ofertas de producción, no se contrataron servicios y no se cambiaron secretos. La rama de revisión no sustituye el despliegue de producción.

Antes de lanzar, el titular debe revisar y retirar cualquier aviso de prueba publicado y comprobar la elegibilidad de los remotos. Este cambio de interfaz no certifica ese inventario. No se midieron Core Web Vitals de usuarios, indexación real ni recepción de alertas.

## Evidencia

- Commit inicial comprobado: `cbe16374c22a71606dbe5ab2609430ed35c8d888`.
- Local: 779 pruebas aprobadas y 14 omitidas, dependientes de PostgreSQL.
- [CI PostgreSQL](https://github.com/Matifernandezar/salta-emplea/actions/runs/39377476575): 793 pruebas aprobadas, sin omisiones.
- [CI Chromium](https://github.com/Matifernandezar/salta-emplea/actions/runs/39377476585): circuito editorial previo y nuevo circuito de portada aprobados. Cinco anchos completados: 360, 390, 768, 1024 y 1440 px. Se comprobaron controles de 44 px, fuente de al menos 16 px, foco, muestras de contraste y ausencia de desplazamiento horizontal.
- Se inspeccionaron las capturas reales de portada de 390 y 1440 px. Las imágenes contienen solo fixtures PRUEBA. El artefacto `capturas-publicas` conserva además filtros y estados vacíos durante tres días; no es un almacenamiento permanente.
- Versión final de código: `88df9a06c69ece0d05e3bb7b343fbf8c9f69a3ef`. Después de ajustar filtros avanzados a una columna hasta 480 px y márgenes de ejemplos, [PostgreSQL volvió a aprobar 793 pruebas](https://github.com/Matifernandezar/salta-emplea/actions/runs/39377850641) y [Chromium volvió a completar los cinco anchos](https://github.com/Matifernandezar/salta-emplea/actions/runs/39377850681).
- Se inspeccionaron también las capturas finales de filtros y guía de CV en 390 px: controles apilados, filtros conservados, texto y ejemplo legibles, sin recortes de página. El circuito de postulación usa un destino interceptado de prueba; no envía una candidatura real. El OCR del circuito previo usa un proveedor sustituido y no prueba una lectura real.
- [Registro resumido de verificación](verificacion-2026-10-20.json). Las capturas recuperadas están en la carpeta local `docs/portada/capturas/`, excluida de Git para evitar confundir archivos generados con código. En GitHub se obtienen desde el artefacto del workflow indicado; caduca a los tres días.

La [propuesta de revisión](https://github.com/Matifernandezar/salta-emplea/pull/1) conserva el código y la evidencia. Vercel intentó crear automáticamente una vista previa de la rama y falló antes del despliegue: el [log del build](https://vercel.com/matias-projects-2dbf9656/salta-emplea/Gj9gDkGdLimr8dRyGXkRuKj7rCxQ) indica que falta `DATABASE_URL` PostgreSQL en Preview. Para habilitar una URL de revisión en Vercel hay que configurar una base aislada y sus variables de Preview; no corresponde compartir la base ni secretos de producción con una PR. La revisión actual se puede realizar con las capturas, CI o la instalación local. El dominio de producción no se modificó.
