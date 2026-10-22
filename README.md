# Acta de Visita de Campo · TEAMBIMCIVIL

App web para el móvil que guía al técnico en 6 fases (identificación con GPS, fotos, notas, firma, revisión y emisión) y genera el acta en PDF. No necesita servidor ni base de datos: las actas se guardan solo en el teléfono.

## Uso

- **Dirección oficial:** https://devteambimcivil.github.io/TBC-APP-REPORTAJE-CAMPO/
- Ábrela siempre desde esa dirección en Chrome (Android) o Safari (iPhone). Si se abre el archivo `index.html` recibido por WhatsApp o correo, el GPS, el guardado y la instalación no funcionan (la app lo avisa).
- **Instalarla:** en «📂 Mis actas → Instalar la app», o en el menú ⋮ de Chrome → «Instalar aplicación». Una vez instalada se abre y genera el PDF **sin cobertura**.
- **Mis actas (📂):** borradores y actas emitidas del teléfono. Un acta queda **emitida** al descargar o compartir su PDF y desde entonces es de solo lectura; para corregirla se usa «Corregir», que crea una copia editable que hay que volver a firmar. «Nueva visita» crea un acta con el mismo técnico y expediente.
- **Sin señal GPS** (interior, sótano, túnel): marca «Sin cobertura GPS» e indica una referencia (PK, dirección o estancia) y, si se quiere, coordenadas manuales.
- **Prueba en el PC:** ejecuta `python -m http.server 8000` en la raíz del repo y abre http://localhost:8000.

## Estructura

| Ruta | Contenido |
|---|---|
| `index.html` | La app: HTML, CSS y JavaScript en un solo archivo |
| `sw.js` | Service worker: guarda la versión publicada en el teléfono para usarla sin cobertura |
| `manifest.webmanifest` | Datos para instalar la app (nombre, iconos, colores) |
| `icons/` | Iconos de la app instalada (generados con `tools/generar-iconos.py`) |
| `lib/jspdf.umd.min.js` | jsPDF 4.2.1 (licencia MIT), en local para no depender de un CDN |
| `lib/fuentes-pdf.js` | Fuente «ActaSans» del PDF, con acentos, símbolos (Ø ≥ ± ² °) y letras griegas |
| `lib/OFL.txt` | Licencia de la fuente: SIL Open Font License 1.1 (derivada de Liberation Sans 2.1.5) |
| `tools/` | Generadores de la fuente (`pip install fonttools`) y de los iconos (`pip install pillow`) |
| `tests/` | Pruebas automáticas de extremo a extremo en un móvil emulado |

## Publicar una versión nueva

1. Cambia `VERSION` en `index.html` **y** en `sw.js` (deben coincidir; la prueba lo comprueba).
2. Pasa las pruebas, haz commit y push. GitHub Pages publica en un par de minutos.
3. Los teléfonos que ya tienen la app descargan la versión nueva al abrirla con cobertura y muestran el aviso «Hay una versión nueva → Actualizar». Lo que estuviera a medias está guardado, así que se puede actualizar sin perder nada.

## Pruebas

```
pip install playwright pypdf pillow
python -m playwright install chromium
python tests/e2e_acta.py      # flujo completo y PDF (23 comprobaciones)
python tests/e2e_campo.py     # bloque B y uso sin cobertura (35 comprobaciones)
```

Recorren la app en un Pixel 7 emulado (GPS simulado, fotos horizontales, verticales, cuadradas y con datos de cámara) y analizan los PDF generados. Dejan los PDF y las capturas en `tests/salida/`.

## Versiones

| Versión | Cambios |
|---|---|
| v1.0 | App original: archivo único con jsPDF cargado desde CDN. |
| v2.0 | **Bloque A (correcciones):** firma que funciona siempre y se conserva al girar el móvil; revisión actualizada; PDF fiel (fotos sin deformar, textos completos, símbolos técnicos, firma comprimida); fecha local; orden de las fotos. **Bloque E (base técnica):** navegación por fases reescrita, texto escapado, librerías locales, zoom permitido, limpieza y pruebas automáticas. |
| v2.1 | **Bloque B (robustez en campo):** autoguardado en el teléfono; «Mis actas» con corregir, nueva visita y borrar; actas emitidas en solo lectura; GPS en vivo con precisión; modo «sin cobertura» con referencia y coordenadas manuales; avisos si se abre como archivo o falta el permiso; hasta 50 fotos, cada una con su hora y GPS (de la cámara si los trae). **Adelantado del bloque D:** app instalable que funciona sin cobertura. |

## Pendiente (plan v2)

| Bloque | Contenido |
|---|---|
| C · Contenido del acta | Asistentes y varias firmas; observaciones generales; indicaciones con responsable y plazo; control ISO 9001; fechas dd/mm/aaaa; numeración automática |
| D · Distribución | Compartir el PDF directamente (WhatsApp, correo) desde el menú del móvil; exportar e importar el acta |
