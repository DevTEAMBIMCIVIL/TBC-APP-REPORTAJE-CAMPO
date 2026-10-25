"""Prueba de tools/reconstruir-desde-pdf.py con un lote como el de una carpeta real: copias del mismo PDF («(1)»), la
misma acta compartida otra vez (otro PDF con el mismo texto y las mismas fotos), un PDF de la primera app (anterior a la
v2.3), un PDF que no es un acta, PDF protegidos y archivos que no son PDF. Cada acta se reconstruye una sola vez, desde
el PDF más antiguo (también si el otro PDF se rehízo desde un acta reconstruida: firma redibujada y, en la v3.2, sin
anotaciones); de los que no se pueden reconstruir se dice por qué; y el ZIP se importa sin duplicar ninguna acta.

Uso (desde la raíz del repo; además de los requisitos de las otras pruebas: pip install pdfplumber scikit-image):
    python tests/e2e_reconstruccion_lote.py
"""
import base64
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import zipfile

from PIL import Image
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from comun import RAIZ, SALIDA, Resultados, abrir, cerrar_aviso, contexto_movil, servidor, texto_pdf, vigilar_red  # noqa: E402
from generar_fotos import generar  # noqa: E402

HERRAMIENTA = RAIZ / "tools" / "reconstruir-desde-pdf.py"
DIR = SALIDA / "reconstruccion-lote"

# Dos actas emitidas del mismo expediente (se inyectan tal como las guarda la app, con el esquema de la v3.1.3: las
# versiones posteriores las adaptan al leerlas). Firma del técnico: trazos en un lienzo de 300 × 150. Con la v3.2, la
# AV-02 es de la v3.2 y lleva una foto anotada (un texto que se sale de la foto por un lado, como el de una esquina).
INYECTAR = r"""async ({ foto }) => {
  const blob = await (await fetch(foto)).blob();
  const trazo = puntos => ({ refW: 300, refH: 150, puntos });
  const firma = [trazo([[20, 100], [60, 30], [100, 110], [140, 25], [190, 105], [240, 40]]), trazo([[30, 130], [150, 126], [270, 132]])];
  const acta = (n, hora) => ({
    id: `lote-av0${n}`, esquema: 4, estado: 'emitida', fase: 8, versionEmision: '3.1.3', revision: 0,
    creada: `2026-10-2${n}T07:40:00.000Z`, modificada: `2026-10-2${n}T09:30:00.000Z`, emitida: `2026-10-2${n}T09:30:00.000Z`,
    revisiones: [{ rev: 0, fecha: `2026-10-2${n}T09:30:00.000Z`, motivo: 'Emisión inicial' }],
    datos: { actaNum: `LOT-AV-0${n}`, numAuto: true, tecnico: 'Blas González', cargoTecnico: 'Director de Obra', expediente: 'LOT',
             objeto: 'tajos', descripcion: `Visita ${n} a la obra`, fecha: `2026-10-2${n}`, hora },
    gps: { lat: '37.389210', lng: '-5.984460', acc: 8, hora: `2026-10-2${n}T07:46:00.000Z` },
    sinGps: { activo: false, referencia: '', lat: '', lng: '' }, condiciones: { meteo: ['nuboso'], temperatura: '18' },
    seguimiento: [], seguimientoOrigen: null, seguimientoNotas: [], seguimientoGuardado: null,
    asistentes: [], firmasAsistentes: {}, observaciones: `Observaciones de la visita ${n}.`,
    indicaciones: [{ id: `ind-lote-${n}`, texto: `Indicación de la visita ${n}`, responsable: 'Constructora Sur', plazo: '2026-10-30' }],
    fotos: [{ id: `foto-lote-${n}`, ancho: 1200, alto: 900, hora: `2026-10-2${n} ${hora}`, horaFuente: 'movil',
              comentario: `Foto de la visita ${n}`, gps: { lat: '37.389211', lng: '-5.984461', acc: 6, fuente: 'movil' } }],
    firma });
  const actas = [acta(1, '09:45'), acta(2, '10:15')];
  if (typeof FASE !== 'undefined') {
    Object.assign(actas[1], { esquema: ESQUEMA, fase: ULTIMA_FASE, versionEmision: VERSION, comprobaciones: [] });
    actas[1].fotos[0].anotaciones = [{ tipo: 'flecha', color: 'rojo', puntos: [[0.2, 0.3], [0.5, 0.6]], texto: '' },
                                     { tipo: 'texto', color: 'amarillo', puntos: [[0.02, 0.5]], texto: 'Nido de grava' }];
  }
  for (const a of actas) {
    for (const f of a.fotos) await Almacen.guardarFoto(f.id, a.id, blob);
    await Almacen.guardarActa(a);
  }
  return actas.map(a => a.id);
}"""

# PDF de la primera app (hasta la v2.2): título «ACTA DE VISITA DE CAMPO», datos sin secciones numeradas y firma en PNG,
# como los de la carpeta de Blas del 22/10/2026. Y un PDF cualquiera, que no es un acta.
OTROS_PDF = r"""async ({ foto }) => {
  const { jsPDF } = window.jspdf;
  const firmaPng = () => {
    const lienzo = document.createElement('canvas');
    lienzo.width = 300; lienzo.height = 120;
    const c = lienzo.getContext('2d');
    c.lineWidth = 3; c.beginPath(); c.moveTo(20, 90); c.lineTo(120, 30); c.lineTo(250, 100); c.stroke();
    return lienzo.toDataURL('image/png');
  };
  const antigua = new jsPDF({ unit: 'mm', format: 'a4' });
  antigua.setFillColor(20, 20, 20); antigua.rect(0, 0, 210, 26, 'F');
  antigua.setTextColor(255, 255, 255); antigua.setFontSize(18); antigua.text('TEAMBIMCIVIL', 15, 13);
  antigua.setFontSize(10); antigua.text('ACTA 001', 195, 13, { align: 'right' });
  antigua.setFontSize(7); antigua.text('ENGINEERING, TRAINING & CONSULTANCY', 15, 19);
  antigua.setTextColor(0, 0, 0); antigua.setFontSize(16); antigua.text('ACTA DE VISITA DE CAMPO', 15, 40);
  antigua.setFontSize(9);
  [['Nº DE ACTA', '001'], ['TÉCNICO', 'bgg'], ['EXPEDIENTE', '168'], ['DESCRIPCIÓN', 'Prueba de la app'],
   ['FECHA', '2026-10-22'], ['HORA', '20:32']].forEach(([k, v], i) => { antigua.text(k, 15, 50 + 6 * i); antigua.text(v, 60, 50 + 6 * i); });
  antigua.text('FIRMA DEL TÉCNICO', 15, 100);
  antigua.addImage(firmaPng(), 'PNG', 15, 104, 60, 24);
  const otro = new jsPDF({ unit: 'mm', format: 'a4' });
  otro.setFontSize(16); otro.text('Presupuesto de obra', 15, 40);
  otro.setFontSize(9); otro.text('Capítulo 1 · Movimiento de tierras', 15, 50);
  const datos = await (await fetch(foto)).blob();
  const url = await new Promise(ok => { const r = new FileReader(); r.onload = () => ok(r.result); r.readAsDataURL(datos); });
  otro.addImage(url, 'JPEG', 15, 60, 80, 60);
  return [btoa(antigua.output()), btoa(otro.output())];
}"""


def descargar_pdf(pg, acta_id, ruta):
    pg.evaluate(f"abrirActaGuardada('{acta_id}')")
    pg.wait_for_function(f"state.acta.id === '{acta_id}' && state.fase === ULTIMA_FASE")
    pg.wait_for_function("document.getElementById('emitPdfEstado').textContent.startsWith('PDF listo')", timeout=60000)
    with pg.expect_download(timeout=60000) as d:
        pg.click("#btnDescargar")
    d.value.save_as(str(ruta))
    cerrar_aviso(pg)


def huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def reconstruir(salida, rutas):
    if salida.exists():
        shutil.rmtree(salida)
    return subprocess.run([sys.executable, str(HERRAMIENTA), str(salida)] + [str(r) for r in rutas],
                          capture_output=True, text=True, encoding="utf-8", timeout=600,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def lineas(salida, marca, archivo):
    return [l for l in salida.stdout.splitlines() if l.startswith(f"{marca}  ") and l[5:].startswith(f"{archivo}:")]


def main():
    r = Resultados()
    if DIR.exists():
        shutil.rmtree(DIR)
    (DIR / "pdf").mkdir(parents=True)
    horizontal, _, _ = generar(SALIDA / "fotos")
    Image.open(horizontal).resize((1200, 900)).save(DIR / "foto.jpg", quality=75)
    foto = f"tests/salida/{DIR.name}/foto.jpg"
    pdf = {nombre: DIR / "pdf" / nombre for nombre in
           ("AV-01-compartido.pdf", "AV-01.pdf", "AV-02.pdf", "AV-02 (1).pdf", "primera-app.pdf", "presupuesto.pdf")}
    srv = servidor()
    externas, errores = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # ══ Teléfono A: dos actas emitidas; la AV-01 se comparte dos veces (dos PDF distintos de la misma acta) ══
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pa = abrir(ctx, errores)
        ids = pa.evaluate(INYECTAR, {"foto": foto})
        v32 = pa.evaluate("typeof FASE !== 'undefined'")
        descargar_pdf(pa, ids[0], pdf["AV-01-compartido.pdf"])
        descargar_pdf(pa, ids[1], pdf["AV-02.pdf"])
        time.sleep(1.2)                              # la fecha de creación del PDF va en segundos
        descargar_pdf(pa, ids[0], pdf["AV-01.pdf"])
        shutil.copyfile(pdf["AV-02.pdf"], pdf["AV-02 (1).pdf"])
        antigua, otro = pa.evaluate(OTROS_PDF, {"foto": foto})
        pdf["primera-app.pdf"].write_bytes(base64.b64decode(antigua))
        pdf["presupuesto.pdf"].write_bytes(base64.b64decode(otro))
        ctx.close()
        r.comprobar("Teléfono A: la AV-01 compartida dos veces da dos PDF distintos con el mismo texto; la «(1)» es una copia",
                    huella(pdf["AV-01.pdf"]) != huella(pdf["AV-01-compartido.pdf"])
                    and texto_pdf(pdf["AV-01.pdf"]) == texto_pdf(pdf["AV-01-compartido.pdf"])
                    and "LOT-AV-01" in texto_pdf(pdf["AV-01.pdf"]) and huella(pdf["AV-02 (1).pdf"]) == huella(pdf["AV-02.pdf"])
                    and ("Foto 1 · anotada" in texto_pdf(pdf["AV-02.pdf"])) == v32, "v3.2: la AV-02 con una foto anotada" if v32 else "")
        r.comprobar("PDF de la primera app («ACTA DE VISITA DE CAMPO», firma en PNG) y un PDF que no es un acta",
                    "ACTA DE VISITA DE CAMPO" in texto_pdf(pdf["primera-app.pdf"])
                    and "Presupuesto de obra" in texto_pdf(pdf["presupuesto.pdf"]))

        # ══ El lote, con los repetidos delante de los originales y una ruta dos veces ══
        orden = ["AV-01.pdf", "AV-02 (1).pdf", "AV-01-compartido.pdf", "AV-02.pdf", "primera-app.pdf", "presupuesto.pdf", "AV-02.pdf"]
        s = reconstruir(DIR / "zip", [pdf[n] for n in orden])
        print(s.stdout.strip())
        ok = [l.split(":")[0][5:] for l in s.stdout.splitlines() if l.startswith("OK   ")]
        rep = [l for l in s.stdout.splitlines() if l.startswith("REP  ")]
        r.comprobar("La misma acta en otro PDF: se reconstruye una vez, desde el más antiguo (aunque vaya después en la lista "
                    "y tenga un nombre más largo)",
                    lineas(s, "REP", "AV-01.pdf") == ["REP  AV-01.pdf: es la misma acta que AV-01-compartido.pdf (mismo texto y "
                                                       "mismas fotos), el PDF más antiguo: se reconstruye una sola vez"]
                    and "AV-01-compartido.pdf" in ok and "AV-01.pdf" not in ok,
                    "; ".join(lineas(s, "REP", "AV-01.pdf")) or s.stderr[-300:])
        r.comprobar("Una copia del mismo archivo y una ruta repetida: una sola vez, con el nombre original (no la «(1)»)",
                    lineas(s, "REP", "AV-02 (1).pdf") == ["REP  AV-02 (1).pdf: es una copia de AV-02.pdf (el mismo archivo): "
                                                           "se reconstruye una sola vez"]
                    and lineas(s, "REP", "AV-02.pdf") == ["REP  AV-02.pdf: está dos veces en la lista: se reconstruye una sola vez"]
                    and ok.count("AV-02.pdf") == 1 and len(rep) == 3, f"{len(rep)} repetidos")
        r.comprobar("PDF de la primera app: se dice que es anterior a la v2.3 (aunque lleve la firma en PNG)",
                    lineas(s, "NO", "primera-app.pdf") == ["NO   primera-app.pdf: es de una versión de la app anterior a la v2.3 "
                                                           "(«Acta de Visita de Campo»): ese formato no se puede reconstruir"],
                    "; ".join(lineas(s, "NO", "primera-app.pdf")))
        r.comprobar("PDF que no es un acta: se dice que no es un acta de la app",
                    lineas(s, "NO", "presupuesto.pdf") == ["NO   presupuesto.pdf: no es un acta de la app: no lleva el título "
                                                           "«Acta de Campo» ni «Acta de Visita de Inspección»"],
                    "; ".join(lineas(s, "NO", "presupuesto.pdf")))
        r.comprobar("Resumen: 2 reconstruidas, 3 repetidos sin duplicar y 2 sin reconstruir (código 1 por los que no se pueden)",
                    s.returncode == 1 and s.stdout.strip().splitlines()[-1].startswith("2 acta(s) reconstruida(s) en ")
                    and s.stdout.strip().endswith(" · 3 PDF repetido(s), sin duplicar · 2 PDF sin reconstruir"),
                    s.stdout.strip().splitlines()[-1] if s.stdout.strip() else s.stderr[-300:])
        with zipfile.ZipFile(DIR / "zip" / "Actas_reconstruidas.zip") as z:
            fichas = [json.loads(z.read(n)) for n in z.namelist() if n.endswith("acta.json")]
        sueltos = sorted(f.name for f in (DIR / "zip").glob("Acta_*_reconstruida.zip"))
        r.comprobar("ZIP sin actas repetidas: las 2, cada una desde su PDF más antiguo, y un .zip por acta",
                    sorted((f["acta"]["datos"]["actaNum"], f["reconstruida"]["archivo"]) for f in fichas)
                    == [("LOT-AV-01", "AV-01-compartido.pdf"), ("LOT-AV-02", "AV-02.pdf")]
                    and sueltos == ["Acta_LOT-AV-01_Rev0_reconstruida.zip", "Acta_LOT-AV-02_Rev0_reconstruida.zip"],
                    f"{[(f['acta']['datos']['actaNum'], f['reconstruida']['archivo']) for f in fichas]} · {sueltos}")
        s2 = reconstruir(DIR / "zip2", [pdf[n] for n in ("AV-01.pdf", "AV-01-compartido.pdf", "AV-02.pdf", "AV-02 (1).pdf")])
        r.comprobar("Un lote con repetidos y sin errores termina bien (código 0): los repetidos no son fallos",
                    s2.returncode == 0 and s2.stdout.strip().endswith(" · 2 PDF repetido(s), sin duplicar")
                    and "sin reconstruir" not in s2.stdout, s2.stdout.strip().splitlines()[-1] if s2.stdout.strip() else s2.stderr[-300:])

        # ══ Archivos que no se pueden leer como actas ══
        raros = DIR / "raros"
        (raros / "carpeta").mkdir(parents=True)
        (raros / "vacío.pdf").write_bytes(b"")
        (raros / "nota.pdf").write_text("Esto no es un PDF", encoding="utf-8")
        (raros / "dañado.pdf").write_bytes(pdf["AV-02.pdf"].read_bytes()[:30000])
        sin_fecha = PdfWriter(clone_from=str(pdf["presupuesto.pdf"]))
        sin_fecha._info = None
        sin_fecha.write(str(raros / "sin-fecha.pdf"))
        for nombre, usuario in (("protegido.pdf", ""), ("con-contraseña.pdf", "1234")):    # solo contra cambios / al abrir
            protegido = PdfWriter(clone_from=str(pdf["AV-02.pdf"]))
            protegido.encrypt(user_password=usuario, owner_password="tbc", algorithm="AES-128")
            protegido.write(str(raros / nombre))
        s4 = reconstruir(DIR / "zip4", [raros / n for n in ("vacío.pdf", "nota.pdf", "dañado.pdf", "carpeta", "*.pdf",
                                                            "sin-fecha.pdf", "protegido.pdf", "con-contraseña.pdf")])
        motivos = {l[5:].split(": ", 1)[0]: l[5:].split(": ", 1)[1] for l in s4.stdout.splitlines() if l.startswith("NO   ")}
        r.comprobar("Archivos que no son PDF o están dañados: se dice por qué, sin mensajes de pypdf en la consola",
                    motivos.get("vacío.pdf") == "no es un PDF (el archivo está vacío)" and motivos.get("nota.pdf") == "no es un PDF"
                    and motivos.get("dañado.pdf") == "el PDF está dañado: no se puede abrir" and not s4.stderr.strip(),
                    str(motivos) + (f" · stderr: {s4.stderr.strip()[:200]}" if s4.stderr.strip() else ""))
        r.comprobar("Una carpeta, un «*.pdf» que cmd no expande y un PDF sin fecha que no es un acta: se dice qué pasa",
                    motivos.get("carpeta", "").startswith("es una carpeta: hay que pasar sus PDF")
                    and motivos.get("*.pdf", "").startswith("no existe ese archivo: cmd no expande «*» ni «?»")
                    and motivos.get("sin-fecha.pdf", "").startswith("no es un acta de la app")
                    and PdfReader(str(raros / "sin-fecha.pdf")).metadata is None
                    and s4.returncode == 1 and s4.stdout.strip().endswith(" · 8 PDF sin reconstruir"), str(motivos))
        protegido = "el PDF está protegido (cifrado): hace falta una copia sin protección"
        r.comprobar("PDF protegidos, con contraseña o solo contra cambios: se dice que están protegidos",
                    motivos.get("protegido.pdf") == protegido and motivos.get("con-contraseña.pdf") == protegido, str(motivos))
        # El mismo nombre en dos carpetas (Descargas y WhatsApp, p. ej.): el aviso dice cuál es cuál
        (DIR / "otra").mkdir()
        shutil.copyfile(pdf["AV-01-compartido.pdf"], DIR / "otra" / "AV-01-compartido.pdf")
        s5 = reconstruir(DIR / "zip5", [pdf["AV-01-compartido.pdf"], DIR / "otra" / "AV-01-compartido.pdf"])
        primero, copia = str(pathlib.Path("pdf") / "AV-01-compartido.pdf"), str(pathlib.Path("otra") / "AV-01-compartido.pdf")
        r.comprobar("El mismo nombre en dos carpetas: el aviso dice de qué carpeta es cada uno",
                    [l for l in s5.stdout.splitlines() if l.startswith("REP")]
                    == [f"REP  {copia}: es una copia de {primero} (el mismo archivo): se reconstruye una sola vez"]
                    and s5.returncode == 0, "; ".join(l for l in s5.stdout.splitlines() if l[:3] in ("REP", "OK ")))

        # ══ Teléfono B: importa el ZIP y vuelve a generar el PDF ══
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pb = abrir(ctx, errores)
        pb.set_input_files("#importInput", str(DIR / "zip" / "Actas_reconstruidas.zip"))
        pb.wait_for_selector("#alertOverlay.open", timeout=60000)
        aviso = cerrar_aviso(pb) or ""
        r.comprobar("Teléfono B: importa las 2 actas, sin «número repetido»",
                    aviso == "Importación terminada | 2 acta(s) nueva(s).", aviso)
        en_b = {a["datos"]["actaNum"]: a["id"] for a in pb.evaluate("Almacen.listarActas()")}
        descargar_pdf(pb, en_b["LOT-AV-01"], DIR / "regenerada-AV-01.pdf")
        r.comprobar("La AV-01 reconstruida vuelve a generar el mismo PDF (texto)",
                    len(en_b) == 2 and texto_pdf(DIR / "regenerada-AV-01.pdf") == texto_pdf(pdf["AV-01-compartido.pdf"]))
        descargar_pdf(pb, en_b["LOT-AV-02"], DIR / "regenerada-AV-02.pdf")
        s3 = reconstruir(DIR / "zip3", [DIR / "regenerada-AV-02.pdf", pdf["AV-02.pdf"]])
        r.comprobar("El PDF rehecho desde un acta reconstruida (firma redibujada, otra fecha; en la v3.2, sin las anotaciones) "
                    "es la misma acta: se reconstruye una vez, desde el original",
                    lineas(s3, "REP", "regenerada-AV-02.pdf") == ["REP  regenerada-AV-02.pdf: es la misma acta que AV-02.pdf (mismo "
                                                                   "texto y mismas fotos), el PDF más antiguo: se reconstruye una sola vez"]
                    and s3.returncode == 0 and (("Foto 1 · anotada" in texto_pdf(pdf["AV-02.pdf"]))
                                                != ("anotada" in texto_pdf(DIR / "regenerada-AV-02.pdf")) if v32 else True),
                    "; ".join(l for l in s3.stdout.splitlines() if l[:3] in ("REP", "OK ", "NO ")) or s3.stderr[-300:])
        pb.set_input_files("#importInput", str(DIR / "zip" / "Actas_reconstruidas.zip"))
        pb.wait_for_selector("#alertOverlay.open", timeout=60000)
        otra_vez = cerrar_aviso(pb) or ""
        r.comprobar("Importar otra vez el mismo ZIP no duplica: «2 ya estaba(n) en el teléfono»",
                    otra_vez == "Importación terminada | 2 ya estaba(n) en el teléfono."
                    and len(pb.evaluate("Almacen.listarActas()")) == 2, otra_vez)
        ctx.close()

        r.comprobar("Sin peticiones a internet", not externas, "; ".join(externas[:3]))
        r.comprobar("Sin errores JS", not errores, "; ".join(errores[:3]))
        navegador.close()
    srv.shutdown()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
