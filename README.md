# Acta de Visita de Campo · TEAMBIMCIVIL

App web para el móvil que guía al técnico en 6 fases (identificación con GPS, fotos, notas, firma, revisión y emisión) y genera el acta en PDF. No necesita servidor ni base de datos: todo ocurre en el navegador del móvil.

## Uso

- **Publicada en GitHub Pages:** https://devteambimcivil.github.io/TBC-APP-REPORTAJE-CAMPO/ (cuando esté activada).
- El GPS solo funciona con **HTTPS** (GitHub Pages) o en `localhost`.
- **Prueba en el PC:** ejecuta `python -m http.server 8000` en la raíz del repo y abre http://localhost:8000.

## Estructura

| Ruta | Contenido |
|---|---|
| `index.html` | La app: HTML, CSS y JavaScript en un solo archivo |
| `lib/jspdf.umd.min.js` | jsPDF 4.2.1 (licencia MIT), en local para no depender de un CDN |
| `lib/fuentes-pdf.js` | Fuente «ActaSans» del PDF, con acentos, símbolos (Ø ≥ ± ² °) y letras griegas |
| `lib/OFL.txt` | Licencia de la fuente: SIL Open Font License 1.1 (derivada de Liberation Sans 2.1.5) |
| `tools/generar-fuentes.py` | Regenera `lib/fuentes-pdf.js` (`pip install fonttools`) |
| `tests/` | Prueba automática de extremo a extremo en un móvil emulado |

## Pruebas

```
pip install playwright pypdf pillow
python -m playwright install chromium
python tests/e2e_acta.py
```

La prueba recorre las 6 fases en un Pixel 7 emulado (GPS simulado, fotos horizontales, verticales y cuadradas) y analiza el PDF generado. Deja el PDF y las capturas de pantalla en `tests/salida/`.

## Versiones

| Versión | Cambios |
|---|---|
| v1.0 | App original: archivo único con jsPDF cargado desde CDN. |
| v2.0 | **Bloque A (correcciones):** firma que funciona siempre (antes el lienzo medía 0×0 px y bloqueaba la fase 4) y que se conserva al girar el móvil; revisión que se construye al entrar y refleja los cambios; PDF fiel (fotos sin deformar, comentarios y descripción completos con salto de línea y de página, símbolos técnicos, firma comprimida: de 1,5 MB a ~20 KB); fecha por defecto en hora local; se respeta el orden de las fotos. **Bloque E (base técnica):** navegación por fases reescrita, texto del usuario escapado, librerías locales (sin CDN), zoom permitido, limpieza de código sin uso, comentarios de hasta 1.000 caracteres y pruebas automáticas. |

## Pendiente (plan v2)

| Bloque | Contenido |
|---|---|
| B · Robustez en campo | Autoguardado e historial de actas; GPS flexible (manual o «sin cobertura» con PK); más fotos, cada una con su hora y su GPS |
| C · Contenido del acta | Asistentes y varias firmas; observaciones generales; indicaciones con responsable y plazo; control ISO 9001; fechas dd/mm/aaaa; numeración automática |
| D · Distribución | App instalable que funciona sin cobertura; compartir el PDF directamente (WhatsApp, correo); exportar e importar el acta |
