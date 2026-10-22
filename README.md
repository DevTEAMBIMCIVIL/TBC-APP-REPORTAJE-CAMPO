# Acta de Visita de Campo · TEAMBIMCIVIL

App web para el móvil que guía al técnico en 8 fases (identificación, asistentes, fotos, notas, observaciones e indicaciones, firmas, revisión y emisión), genera el acta en PDF y la comparte desde el propio teléfono. No necesita servidor ni base de datos: las actas se guardan solo en el teléfono, y se pueden copiar, exportar e importar en archivos ZIP.

## Uso

- **Dirección oficial:** https://devteambimcivil.github.io/TBC-APP-REPORTAJE-CAMPO/
- Ábrela siempre desde esa dirección en Chrome (Android) o Safari (iPhone). Si se abre el archivo `index.html` recibido por WhatsApp o correo, el GPS, el guardado y la instalación no funcionan (la app lo avisa).
- **Instalarla:** en «📂 Mis actas → Instalar la app», o en el menú ⋮ de Chrome → «Instalar aplicación». Una vez instalada se abre y genera el PDF **sin cobertura**.
- **Numeración:** al escribir el expediente, la app propone el siguiente número de ese expediente en el teléfono (`<expediente>-AV-01`, `-AV-02`…), contando también las actas importadas. Se puede escribir a mano; si se borra, vuelve el automático.
- **Asistentes y firmas:** el técnico firma siempre; cada asistente marcado firma en su recuadro o consta «No firma». Se pueden recuperar asistentes de visitas anteriores del mismo expediente.
- **Compartir el PDF:** en la fase de Emisión el PDF se prepara solo; «📤 Compartir PDF» abre el menú del teléfono (WhatsApp, correo, Drive, Teams…) con el PDF adjunto y un texto con el número, el expediente, la fecha y el técnico. «📥 Descargar PDF» lo guarda en Descargas. Si el navegador no permite compartir archivos, solo aparece «Descargar PDF».
- **Mis actas (📂):** borradores y actas emitidas del teléfono. Un acta queda **emitida** al compartir o descargar su PDF y desde entonces es de solo lectura. «Corregir» crea la **revisión siguiente con el mismo número** (Rev. 1, 2…), pide el motivo y hay que volver a recoger las firmas; al emitirla, la anterior queda «Sustituida». «Nueva visita» crea un acta con el mismo técnico, expediente y asistentes.
- **Copia de seguridad:** «Mis actas → 💾 Hacer copia» guarda en Descargas un `.zip` con todas las actas (datos, firmas y fotos). Para que sirva si se pierde el teléfono, hay que guardarlo fuera de él (Drive, correo o el PC). Mis actas muestra la fecha de la última copia y avisa, con un punto rojo en 📂, si pasan más de 7 días con cambios sin copiar.
- **Exportar e importar:** «📤 Exportar» en cada acta crea un `.zip` para pasarla a otro teléfono o al PC; «📥 Importar» lo abre, y también restaura una copia de seguridad. Si el acta ya está en el teléfono, se conserva la versión más reciente y una emitida nunca se sobrescribe. Al importar una revisión emitida, la anterior queda «Sustituida». La app avisa si una importada repite el número de otra acta.
- **Compartir la app:** «Mis actas → 🔗 Compartir el enlace de la app» envía la dirección oficial (nunca el archivo).
- **Sin señal GPS** (interior, sótano, túnel): marca «Sin cobertura GPS» e indica una referencia (PK, dirección o estancia) y, si se quiere, coordenadas manuales.
- **Prueba en el PC:** ejecuta `python -m http.server 8000` en la raíz del repo y abre http://localhost:8000.

## Configuración

- **Formato del SGC (ISO 9001):** en `index.html`, constante `FORMATO_SGC = { nombre: 'Acta de Visita de Inspección', codigo: '', revision: '' }`. El nombre es el título del PDF y figura en el bloque de control de cada página; si el formato llega a tener código y revisión, se escriben ahí y se añaden a continuación del nombre.

## Estructura

| Ruta | Contenido |
|---|---|
| `index.html` | La app: HTML, CSS y JavaScript en un solo archivo (también el lector y escritor de ZIP, sin librerías) |
| `sw.js` | Service worker: guarda la versión publicada en el teléfono para usarla sin cobertura |
| `manifest.webmanifest` | Datos para instalar la app (nombre, iconos, colores) |
| `icons/` | Iconos de la app instalada (generados con `tools/generar-iconos.py`) |
| `lib/jspdf.umd.min.js` | jsPDF 4.2.1 (licencia MIT), en local para no depender de un CDN |
| `lib/fuentes-pdf.js` | Fuente «ActaSans» del PDF, con acentos, símbolos (Ø ≥ ± ² °) y letras griegas |
| `lib/OFL.txt` | Licencia de la fuente: SIL Open Font License 1.1 (derivada de Liberation Sans 2.1.5) |
| `tools/` | Generadores de la fuente (`pip install fonttools`) y de los iconos (`pip install pillow`) |
| `tests/` | Pruebas automáticas de extremo a extremo en un móvil emulado |

**Archivos ZIP de la app:** una carpeta por acta (`<número>_Rev<N>/`) con `acta.json` (datos, asistentes, acuerdos y firmas; `"formato": "tbc-acta"`) y `fotos/01.jpg…`, más un `LEEME.txt`. Al importar, la app comprueba el CRC de cada archivo y valida cada campo; un acta dañada o manipulada se descarta sin afectar a las demás.

## Publicar una versión nueva

1. Cambia `VERSION` en `index.html` **y** en `sw.js` (deben coincidir; la prueba lo comprueba).
2. Pasa las pruebas, haz commit y push. GitHub Pages publica en un par de minutos.
3. Los teléfonos que ya tienen la app descargan la versión nueva al abrirla con cobertura y muestran el aviso «Hay una versión nueva → Actualizar». Lo que estuviera a medias está guardado, así que se puede actualizar sin perder nada. Las actas guardadas con versiones anteriores se adaptan solas al abrirlas.

## Pruebas

```
pip install playwright pypdf pillow
python -m playwright install chromium
python tests/e2e_acta.py          # flujo completo y PDF (23 comprobaciones)
python tests/e2e_campo.py         # robustez en campo y uso sin cobertura (35 comprobaciones)
python tests/e2e_contenido.py     # numeración, asistentes, acuerdos, firmas, revisiones y migración (31 comprobaciones)
python tests/e2e_distribucion.py  # compartir el PDF, copia de seguridad, exportar e importar (41 comprobaciones)
```

Recorren la app en un Pixel 7 emulado (GPS simulado, fotos horizontales, verticales, cuadradas y con datos de cámara; Web Share simulado como en Chrome para Android) y analizan los PDF y los ZIP generados. Dejan los PDF, los ZIP y las capturas en `tests/salida/`.

## Versiones

| Versión | Cambios |
|---|---|
| v1.0 | App original: archivo único con jsPDF cargado desde CDN. |
| v2.0 | **Bloque A (correcciones):** firma que funciona siempre y se conserva al girar el móvil; revisión actualizada; PDF fiel (fotos sin deformar, textos completos, símbolos técnicos, firma comprimida); fecha local; orden de las fotos. **Bloque E (base técnica):** navegación por fases reescrita, texto escapado, librerías locales, zoom permitido, limpieza y pruebas automáticas. |
| v2.1 | **Bloque B (robustez en campo):** autoguardado en el teléfono; «Mis actas»; actas emitidas en solo lectura; GPS en vivo; modo «sin cobertura»; avisos si se abre como archivo o falta el permiso; hasta 50 fotos con su hora y GPS. **Adelantado del bloque D:** app instalable que funciona sin cobertura. |
| v2.2 | **Bloque C (contenido del acta):** 8 fases; numeración automática por expediente; asistentes (con sugerencias de visitas anteriores); observaciones generales e indicaciones con responsable y plazo; firmas de los asistentes con «No firma»; revisiones con el mismo número, motivo y estado «Sustituida»; PDF con bloque de control en cada página (nº, revisión, formato, fecha de emisión, pág. X de Y), secciones numeradas y control de revisiones; fechas dd/mm/aaaa. |
| v2.3 | **Bloque D (distribución):** compartir el PDF con el menú del teléfono (preparado al entrar en Emisión); copia de seguridad en ZIP con aviso a los 7 días; exportar e importar actas (la versión más reciente gana, las emitidas no se sobrescriben, las revisiones importadas marcan «Sustituida» la anterior); compartir el enlace de la app. Formato del SGC «Acta de Visita de Inspección» en el título y el bloque de control del PDF; propiedades del PDF (título, autor, asunto). |

## Fuera de alcance

El plan v2 está completo (bloques A a E). Quedan fuera, porque necesitan un servidor o cuentas de empresa configuradas: la subida automática a Drive o SharePoint, el envío a destinatarios fijos y una numeración compartida entre teléfonos (hoy cada teléfono numera con sus actas y las importadas).
