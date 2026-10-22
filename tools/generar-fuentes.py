"""Genera lib/fuentes-pdf.js: la fuente «ActaSans» que usa el PDF del acta.

ActaSans es Liberation Sans 2.1.5 (SIL OFL 1.1) recortada a los caracteres que
necesita un acta técnica en español (acentos, símbolos y letras griegas) y
renombrada, porque «Liberation» es un nombre reservado de la licencia.

Uso:
    pip install fonttools
    python tools/generar-fuentes.py [carpeta con LiberationSans-*.ttf]

Por defecto busca las fuentes en /usr/share/fonts/truetype/liberation.
"""
import base64
import io
import pathlib
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

ORIGEN = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/liberation")
DESTINO = pathlib.Path(__file__).resolve().parent.parent / "lib" / "fuentes-pdf.js"
FAMILIA = "ActaSans"
ESTILOS = {  # estilo jsPDF -> (archivo origen, sufijo)
    "normal": ("LiberationSans-Regular.ttf", "Regular"),
    "bold": ("LiberationSans-Bold.ttf", "Bold"),
    "italic": ("LiberationSans-Italic.ttf", "Italic"),
}
# Caracteres incluidos: latín básico y ampliado, griego, puntuación tipográfica,
# superíndices, €, flechas y operadores matemáticos habituales en obra.
RANGOS = [(0x20, 0x7E), (0xA0, 0x17F), (0x391, 0x3A9), (0x3B1, 0x3C9), (0x2010, 0x2027),
          (0x2030, 0x2030), (0x2032, 0x2033), (0x2039, 0x203A), (0x2070, 0x209F), (0x20AC, 0x20AC),
          (0x2116, 0x2116), (0x2122, 0x2122), (0x2126, 0x2126), (0x2190, 0x2199)]
SUELTOS = [0x2202, 0x2205, 0x2206, 0x220F, 0x2211, 0x2212, 0x2219, 0x221A, 0x221E, 0x222B,
           0x2248, 0x2260, 0x2261, 0x2264, 0x2265, 0x25A0, 0x25A1, 0x25CB, 0x25CF]
UNICODES = sorted({c for a, b in RANGOS for c in range(a, b + 1)} | set(SUELTOS))


def recortar(ruta: pathlib.Path, sufijo: str) -> bytes:
    fuente = TTFont(ruta)
    opciones = subset.Options()
    opciones.layout_features = []      # jsPDF no usa tablas OpenType de maquetación
    opciones.hinting = False
    opciones.glyph_names = False
    opciones.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    opciones.notdef_outline = True
    sub = subset.Subsetter(opciones)
    sub.populate(unicodes=UNICODES)
    sub.subset(fuente)
    nombre_completo = f"{FAMILIA} {sufijo}" if sufijo != "Regular" else FAMILIA
    for registro in fuente["name"].names:
        if registro.nameID == 1:
            registro.string = FAMILIA
        elif registro.nameID == 3:
            registro.string = f"{FAMILIA}-{sufijo};TEAMBIMCIVIL"
        elif registro.nameID == 4:
            registro.string = nombre_completo
        elif registro.nameID == 6:
            registro.string = f"{FAMILIA}-{sufijo}"
    salida = io.BytesIO()
    fuente.save(salida)
    return salida.getvalue()


def main() -> None:
    bloques, total = [], 0
    for estilo, (archivo, sufijo) in ESTILOS.items():
        datos = recortar(ORIGEN / archivo, sufijo)
        total += len(datos)
        b64 = base64.b64encode(datos).decode("ascii")
        bloques.append(f'    {{ estilo: "{estilo}", archivo: "{FAMILIA}-{sufijo}.ttf", datos: "{b64}" }}')
        print(f"{estilo:7s} {len(datos) / 1024:6.1f} KB")
    js = (
        "/* Fuente «ActaSans» para el PDF del acta (generado por tools/generar-fuentes.py; no editar a mano).\n"
        " * Derivada de Liberation Sans 2.1.5: (c) 2010 Google Corporation, (c) 2012 Red Hat, Inc.\n"
        " * Licencia SIL Open Font License 1.1: ver lib/OFL.txt. */\n"
        "(function () {\n"
        "  var FUENTES = [\n" + ",\n".join(bloques) + "\n  ];\n"
        "  window.jspdf.jsPDF.API.events.push([\"addFonts\", function () {\n"
        "    for (var i = 0; i < FUENTES.length; i++) {\n"
        "      this.addFileToVFS(FUENTES[i].archivo, FUENTES[i].datos);\n"
        f"      this.addFont(FUENTES[i].archivo, \"{FAMILIA}\", FUENTES[i].estilo);\n"
        "    }\n"
        "  }]);\n"
        "})();\n"
    )
    DESTINO.write_text(js, encoding="utf-8")
    print(f"total   {total / 1024:6.1f} KB -> {DESTINO} ({DESTINO.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
