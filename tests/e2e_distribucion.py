"""Pruebas del bloque D (distribución) en un Pixel 7 emulado: compartir el PDF con el menú del teléfono
(Web Share simulado como en Chrome para Android), alternativa sin Web Share, formato del SGC y propiedades
del PDF, copia de seguridad y exportación en ZIP, importación en otro teléfono (también de un ZIP comprimido
de nuevo en Windows), conflictos, revisiones importadas, archivos dañados o manipulados y enlace de la app.

Uso (desde la raíz del repo, con los mismos requisitos que e2e_acta.py):
    python tests/e2e_distribucion.py
"""
import base64
import copy
import json
import pathlib
import sys
import zipfile

from pypdf import PdfReader
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from comun import (SALIDA, Resultados, abrir, avanzar_hasta, cerrar_aviso, contexto_movil,  # noqa: E402
                   esperar_fotos, firmar, servidor, texto_pdf, vigilar_red)
from generar_fotos import generar  # noqa: E402

EXP = "425_2026.CON"
URL_OFICIAL = "https://devteambimcivil.github.io/TBC-APP-REPORTAJE-CAMPO/"
FORMATO = "Acta de Visita de Inspección"
ASISTENTE = {"nombre": "Juan Pérez Gómez", "empresa": "Construcciones del Sur", "cargo": "Jefe de obra"}
INDICACION = {"texto": "Picado y reparación de la viga del eje 3",
              "responsable": "Construcciones del Sur · Jefe de obra", "plazo": "2026-11-05"}

# Web Share como en Chrome para Android: solo PDF, imágenes y texto, y solo justo después de pulsar.
WEB_SHARE = r"""
(() => {
  const permitidos = /\.(pdf|jpe?g|png|webp|gif|txt|csv)$/i;
  window.__compartidos = [];
  window.__respuestaShare = 'ok';
  Object.defineProperty(navigator, 'canShare', { configurable: true, value: datos =>
    Boolean(datos) && (!datos.files || datos.files.every(f => permitidos.test(f.name))) });
  Object.defineProperty(navigator, 'share', { configurable: true, value: async datos => {
    const activa = navigator.userActivation ? navigator.userActivation.isActive : true;
    if (!activa) throw new DOMException('Sin pulsación reciente', 'NotAllowedError');
    const archivos = [];
    for (const f of datos.files || []) {
      const bytes = new Uint8Array(await f.arrayBuffer());
      let binario = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binario += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      archivos.push({ nombre: f.name, tipo: f.type, base64: btoa(binario) });
    }
    window.__compartidos.push({ title: datos.title, text: datos.text, url: datos.url, archivos, activa });
    if (window.__respuestaShare === 'cancelar') throw new DOMException('Cancelado', 'AbortError');
  } });
})();
"""
SIN_WEB_SHARE = "delete Navigator.prototype.share; delete Navigator.prototype.canShare;"

# Cuenta las generaciones del PDF y permite retrasarlas para ver el estado «Preparando…».
ESPIAR_PDF = """(() => { const original = crearPDF; window.__llamadasPDF = 0; window.__retrasoPDF = 0;
  window.crearPDF = async (...args) => {
    window.__llamadasPDF++;
    if (window.__retrasoPDF) await new Promise(r => setTimeout(r, window.__retrasoPDF));
    return original(...args);
  }; })()"""

CONTAR_FOTOS = """new Promise((ok, mal) => { const p = indexedDB.open('tbc-actas'); p.onerror = mal;
  p.onsuccess = () => { const q = p.result.transaction('fotos').objectStore('fotos').count(); q.onsuccess = () => ok(q.result); }; })"""


def telefono(p, navegador, externas, errores, web_share=True, permisos=("geolocation",)):
    ctx = contexto_movil(p, navegador, permisos=permisos)
    ctx.add_init_script(WEB_SHARE if web_share else SIN_WEB_SHARE)
    vigilar_red(ctx, externas)
    pg = abrir(ctx, errores)
    return ctx, pg, ctx.new_cdp_session(pg)


def crear_acta(pg, cdp, fotos, hasta=8):
    """Acta numerada por expediente, con un asistente; avanza hasta la fase indicada (8 = lista para emitir)."""
    pg.fill("#tecnico", "Blas González González")
    pg.fill("#expediente", EXP)
    pg.fill("#descripcion", "Inspección de forjados y cubierta")
    pg.wait_for_function("state.acta.datos.actaNum.includes('-AV-')")
    pg.click("#gpsBtn")
    pg.wait_for_selector("#gpsStatus.ok", timeout=15000)
    pg.click("#btnNext")
    pg.evaluate("d => anadirAsistente(d)", ASISTENTE)
    pg.click("#btnNext")
    pg.set_input_files("#photoInput", fotos)
    esperar_fotos(pg, len(fotos))
    pg.click("#btnNext")
    pg.locator("textarea.comment-textarea").nth(0).fill("Fisura longitudinal en la viga del eje 3")
    if hasta <= 4:
        pg.evaluate("guardarYa()")
        return
    pg.click("#btnNext")
    pg.fill("#observaciones", "Se revisan los forjados de planta primera.")
    pg.evaluate("anadirIndicacion()")
    pg.fill("#indTexto0", INDICACION["texto"])
    pg.fill("#indResp0", INDICACION["responsable"])
    pg.fill("#indPlazo0", INDICACION["plazo"])
    pg.click("#btnNext")                       # acuerdos → firmas
    firmar_todos(cdp, pg)
    pg.click("#btnNext")                       # firmas → revisión
    if hasta <= 7:
        return
    pg.click("#btnNext")                       # revisión → emisión
    pg.wait_for_function("state.fase === 8")


def firmar_todos(cdp, pg):
    firmar(cdp, pg)
    firmar(cdp, pg, lienzo=pg.locator("canvas.firma-lienzo").first)


def esperar_pdf_listo(pg, espera=60000):
    pg.wait_for_function("document.getElementById('emitPdfEstado').textContent.startsWith('PDF listo')", timeout=espera)


def compartir(pg, selector="#btnCompartir"):
    antes = pg.evaluate("window.__compartidos.length")
    pg.click(selector)
    pg.wait_for_function(f"window.__compartidos.length > {antes}")
    return pg.evaluate("window.__compartidos[window.__compartidos.length - 1]")


def descargar(pg, selector, ruta):
    with pg.expect_download(timeout=60000) as d:
        pg.click(selector)
    d.value.save_as(str(ruta))
    return d.value.suggested_filename


def abrir_panel(pg):
    pg.evaluate("abrirMisActas()")
    pg.wait_for_selector("#panelActas.open")


def esperar_aviso(pg):
    pg.wait_for_selector("#alertOverlay.open", timeout=60000)
    return cerrar_aviso(pg)


def exportar(pg, acta_id, ruta):
    abrir_panel(pg)
    nombre = descargar(pg, f".acta-card[data-acta='{acta_id}'] button:has-text('Exportar')", ruta)
    aviso = esperar_aviso(pg)
    pg.evaluate("cerrarMisActas()")
    return nombre, aviso


def importar(pg, ruta):
    cerrar_aviso(pg)
    pg.set_input_files("#importInput", str(ruta))
    return esperar_aviso(pg)


def actas(pg):
    return {a["id"]: a for a in pg.evaluate("Almacen.listarActas()")}


def leer(pg, acta_id):
    return pg.evaluate("id => Almacen.leerActa(id)", acta_id)


def contenido(acta):
    """Lo que debe conservarse al exportar e importar (las fotos, sin su identificador interno)."""
    claves = ("estado", "emitida", "revision", "revisiones", "gps", "sinGps", "asistentes", "observaciones",
              "indicaciones", "firma", "firmasAsistentes", "corrigeA")
    datos = {k: v for k, v in acta["datos"].items() if k != "numAuto"}
    fotos = [{k: v for k, v in f.items() if k != "id"} for f in acta["fotos"]]
    return {"datos": datos, "fotos": fotos, **{k: acta.get(k) for k in claves}}


def editar_observaciones(pg, acta_id, texto):
    pg.evaluate("id => abrirActaGuardada(id)", acta_id)
    pg.wait_for_function("id => state.acta.id === id", arg=acta_id)
    pg.evaluate("irAFase(5)")
    pg.fill("#observaciones", texto)
    pg.evaluate("guardarYa()")


def recomprimir(origen, destino):
    """Como al extraer la copia en Windows y volver a comprimirla: deflate, carpetas explícitas y basura de macOS."""
    with zipfile.ZipFile(origen) as zin, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zout:
        carpetas = set()
        for info in zin.infolist():
            partes = info.filename.split("/")[:-1]
            for i in range(1, len(partes) + 1):
                carpeta = "/".join(partes[:i]) + "/"
                if carpeta not in carpetas:
                    carpetas.add(carpeta)
                    zout.writestr(carpeta, b"")
            zout.writestr(info.filename, zin.read(info.filename))
        zout.writestr("__MACOSX/._LEEME.txt", b"basura")


def corromper(origen, destino, miembro):
    """Cambia un byte de los datos de un archivo del ZIP (su CRC deja de cuadrar)."""
    datos = bytearray(origen.read_bytes())
    with zipfile.ZipFile(origen) as z:
        info = z.getinfo(miembro)
    inicio = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    datos[inicio + 200] ^= 0xFF
    destino.write_bytes(bytes(datos))


def main():
    r = Resultados()
    SALIDA.mkdir(parents=True, exist_ok=True)
    horizontal, vertical, cuadrada = (str(f) for f in generar(SALIDA / "fotos"))
    srv = servidor()
    externas, errores = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()

        # ══ Teléfono A: con Web Share (como Chrome para Android) ══
        ctx_a, pa, cdp_a = telefono(p, navegador, externas, errores)
        version = pa.evaluate("VERSION")
        pa.evaluate(ESPIAR_PDF)
        crear_acta(pa, cdp_a, [horizontal, vertical], hasta=7)
        pa.evaluate("window.__retrasoPDF = 1500")
        pa.click("#btnNext")                                    # revisión → emisión
        preparando = pa.evaluate("[btnCompartir.disabled, btnDescargar.disabled, emitPdfEstado.textContent]")
        r.comprobar("D1 · Al entrar en Emisión se prepara el PDF (botones en espera)",
                    preparando[0] and preparando[1] and preparando[2].startswith("⏳ Preparando el PDF"), preparando[2])
        esperar_pdf_listo(pa)
        pa.evaluate("window.__retrasoPDF = 0")
        estado_pdf = pa.text_content("#emitPdfEstado")
        botones = pa.evaluate("""({ compartir: !btnCompartir.classList.contains('hidden') && !btnCompartir.disabled,
                                     descargar: btnDescargar.className, ayuda: emitAyuda.textContent })""")
        r.comprobar("D1 · PDF listo: «Compartir PDF» principal y «Descargar PDF» secundario",
                    botones["compartir"] and "btn-dark" in botones["descargar"] and "WhatsApp" in botones["ayuda"],
                    estado_pdf)
        pa.click("#btnBack")
        pa.click("#btnNext")
        esperar_pdf_listo(pa)
        r.comprobar("D1 · Volver a Revisión y regresar no genera el PDF otra vez", pa.evaluate("window.__llamadasPDF") == 1)

        pa.evaluate("window.__respuestaShare = 'cancelar'")
        compartir(pa)
        pa.wait_for_timeout(300)
        r.comprobar("D1 · Si se cierra el menú sin compartir, el acta sigue en borrador",
                    pa.evaluate("state.acta.estado") == "borrador")
        pa.evaluate("window.__respuestaShare = 'ok'")
        compartido = compartir(pa)
        pa.wait_for_function("state.acta.estado === 'emitida'")
        num0 = pa.evaluate("state.acta.datos.actaNum")
        rev0_id = pa.evaluate("state.acta.id")
        archivo = compartido["archivos"][0] if compartido["archivos"] else {}
        r.comprobar("D1 · Se comparte el PDF (un archivo, tipo PDF, nombre del acta)",
                    len(compartido["archivos"]) == 1 and archivo.get("tipo") == "application/pdf"
                    and archivo.get("nombre", "").startswith("Acta_425_2026_CON-AV-01_"), archivo.get("nombre"))
        r.comprobar("D1 · El menú se abre en la misma pulsación (el PDF ya estaba preparado)",
                    compartido["activa"] and pa.evaluate("window.__llamadasPDF") == 1)
        texto_msg = compartido["text"] or ""
        r.comprobar("D1 · Texto que acompaña al PDF: formato, nº, expediente, visita, técnico e indicaciones",
                    f"{FORMATO} {num0} · Rev. 0" in texto_msg and f"Expediente: {EXP}" in texto_msg
                    and "Técnico: Blas González González" in texto_msg and "Indicaciones: 1" in texto_msg
                    and compartido["title"] == f"Acta {num0} · Rev. 0", texto_msg.replace("\n", " | "))
        r.comprobar("D1 · El acta queda emitida al compartir", pa.evaluate("state.acta.estado") == "emitida")

        pdf_compartido = SALIDA / "D-compartido.pdf"
        pdf_compartido.write_bytes(base64.b64decode(archivo["base64"]))
        texto = texto_pdf(pdf_compartido)
        lector = PdfReader(str(pdf_compartido))
        paginas = len(lector.pages)
        r.comprobar("Formato SGC · Título del PDF «ACTA DE VISITA DE INSPECCIÓN»",
                    "ACTA DE VISITA DE INSPECCIÓN" in texto and "visita de campo" not in texto.lower())
        r.comprobar("Formato SGC · «Acta de Visita de Inspección» en el bloque de control de cada página",
                    texto.count(FORMATO) == paginas, f"{texto.count(FORMATO)} de {paginas} páginas")
        meta = lector.metadata or {}
        r.comprobar("D1 · Propiedades del PDF (título, autor, asunto, palabras clave) con acentos",
                    meta.get("/Title") == f"{FORMATO} {num0} · Rev. 0"
                    and meta.get("/Author") == "Blas González González · TEAMBIMCIVIL"
                    and f"Expediente {EXP}" in (meta.get("/Subject") or "")
                    and num0 in (meta.get("/Keywords") or "") and f"v{version}" in (meta.get("/Creator") or ""),
                    f"{meta.get('/Title')} | {meta.get('/Author')}")
        nombre_pdf = descargar(pa, "#btnDescargar", SALIDA / "D-descargado.pdf")
        r.comprobar("D1 · Acta emitida: el PDF descargado es el mismo que se compartió",
                    texto_pdf(SALIDA / "D-descargado.pdf") == texto and nombre_pdf == archivo["nombre"]
                    and pa.evaluate("window.__llamadasPDF") == 1, nombre_pdf)
        otra = compartir(pa)
        r.comprobar("D1 · Un acta emitida se puede volver a compartir (sigue emitida)",
                    len(otra["archivos"]) == 1 and pa.evaluate("state.acta.estado") == "emitida")

        # Exporta la Rev. 0 antes de corregirla (para importar la cadena de revisiones en otro teléfono)
        nombre_r0, aviso_r0 = exportar(pa, rev0_id, SALIDA / "D-rev0.zip")
        r.comprobar("D3 · Exportar un acta: ZIP con el número y la revisión, guardado en Descargas",
                    nombre_r0 == "Acta_425_2026_CON-AV-01_Rev0.zip" and "Descargas" in (aviso_r0 or ""), nombre_r0)

        # Rev. 1 de la misma acta, emitida con «Descargar PDF»
        pa.evaluate("id => abrirActaGuardada(id)", rev0_id)
        pa.click("#btnCorregir")
        pa.wait_for_selector("#promptOverlay.open")
        pa.fill("#promptTexto", "Corrección del plazo de la indicación 1")
        pa.click("#promptAceptar")
        esperar_aviso(pa)
        rev1_id = pa.evaluate("state.acta.id")
        avanzar_hasta(pa, 6)
        firmar_todos(cdp_a, pa)
        pa.click("#btnNext")
        pa.click("#btnNext")
        esperar_pdf_listo(pa)
        descargar(pa, "#btnDescargar", SALIDA / "D-rev1-A.pdf")
        pa.wait_for_function("state.acta.estado === 'emitida'")
        nombre_r1, _ = exportar(pa, rev1_id, SALIDA / "D-rev1.zip")

        # Un borrador con otra acta del mismo expediente
        pa.evaluate("nuevaActa()")
        pa.wait_for_function("state.fase === 1 && state.acta.datos.actaNum === ''")
        crear_acta(pa, cdp_a, [cuadrada], hasta=4)
        av02_id = pa.evaluate("state.acta.id")

        # ── D2 · Copia de seguridad ──
        abrir_panel(pa)
        estado = pa.text_content("#copiaEstado")
        r.comprobar("D2 · Mis actas indica que aún no hay copia (sin aviso si las actas son de hoy)",
                    "Aún no se ha hecho ninguna copia de las 3 acta(s)" in estado
                    and "aviso" not in pa.get_attribute("#copiaCard", "class"), estado)
        pa.evaluate("localStorage.setItem('tbc-ultima-copia', new Date(Date.now() - 10 * 86400000).toISOString())")
        pa.evaluate("cerrarMisActas()")
        pa.evaluate("actualizarAvisoCopia()")
        pa.wait_for_function("document.querySelector('.header-btn').classList.contains('pendiente')")
        abrir_panel(pa)
        estado = pa.text_content("#copiaEstado")
        r.comprobar("D2 · A los 7 días con cambios sin copia: aviso en Mis actas y punto rojo en 📂",
                    "aviso" in pa.get_attribute("#copiaCard", "class") and estado.startswith("⚠️")
                    and "3 acta(s) con cambios" in estado, estado)
        nombre_copia = descargar(pa, "#copiaCard button:has-text('Hacer copia')", SALIDA / "D-copia.zip")
        aviso_copia = esperar_aviso(pa)
        estado = pa.text_content("#copiaEstado")
        r.comprobar("D2 · Tras la copia: «Al día», sin punto rojo y aviso de guardarla fuera del teléfono",
                    estado.startswith("✓ Al día") and "al-dia" in pa.get_attribute("#copiaCard", "class")
                    and not pa.evaluate("document.querySelector('.header-btn').classList.contains('pendiente')")
                    and "Drive" in (aviso_copia or ""), f"{nombre_copia} · {estado}")

        fotos_a = sum(len(a["fotos"]) for a in actas(pa).values())
        with zipfile.ZipFile(SALIDA / "D-copia.zip") as z:
            nombres = z.namelist()
            carpetas = sorted(n.split("/")[0] for n in nombres if n.endswith("/acta.json"))
            fichas = {c: json.loads(z.read(f"{c}/acta.json")) for c in carpetas}
            fotos_zip = [n for n in nombres if "/fotos/" in n]
            jpeg = all(z.read(n)[:2] == b"\xff\xd8" for n in fotos_zip)
            enlazadas = all(f"{c}/{f['archivo']}" in nombres for c, ficha in fichas.items() for f in ficha["acta"]["fotos"])
            leeme = z.read("LEEME.txt").decode("utf-8")
            r.comprobar("D2 · ZIP íntegro (CRC correctos) y nombres en UTF-8",
                        z.testzip() is None and all(i.flag_bits & 0x800 for i in z.infolist()))
        r.comprobar("D2 · Una carpeta por acta con acta.json y sus fotos JPG",
                    carpetas == ["425_2026_CON-AV-01_Rev0", "425_2026_CON-AV-01_Rev1", "425_2026_CON-AV-02_Rev0"]
                    and len(fotos_zip) == fotos_a and jpeg and enlazadas, ", ".join(carpetas))
        r.comprobar("D2 · acta.json identifica formato, versión y app; LEEME.txt explica cómo recuperarla",
                    all(f["formato"] == "tbc-acta" and f["version"] == 1 and f["app"] == version for f in fichas.values())
                    and leeme.startswith("﻿") and "Importar" in leeme and URL_OFICIAL in leeme)

        # ── D4 · Compartir el enlace de la app (con Web Share) ──
        abrir_panel(pa)
        enlace = compartir(pa, ".panel-enlace")
        r.comprobar("D4 · «Compartir el enlace de la app» envía la dirección oficial (no el archivo)",
                    enlace["url"] == URL_OFICIAL and not enlace["archivos"], enlace["url"])
        pa.evaluate("cerrarMisActas()")

        # ══ Teléfono B: sin Web Share; restaura la copia ══
        ctx_b, pb, _ = telefono(p, navegador, externas, errores, web_share=False,
                                permisos=("geolocation", "clipboard-read", "clipboard-write"))
        aviso = importar(pb, SALIDA / "D-copia.zip")
        en_b = actas(pb)
        en_a = actas(pa)
        r.comprobar("D3 · Importar la copia en otro teléfono: 3 actas nuevas", "3 acta(s) nueva(s)" in (aviso or "")
                    and set(en_b) == set(en_a), aviso)
        r.comprobar("D3 · Se conservan estados, revisiones, firmas, acuerdos y fotos",
                    all(contenido(en_b[i]) == contenido(en_a[i]) for i in en_a)
                    and en_b[rev0_id].get("sustituidaPor") == rev1_id)
        r.comprobar("D3 · Todas las fotos importadas están en el teléfono (ninguna perdida ni sobrante)",
                    pb.evaluate(CONTAR_FOTOS) == fotos_a, f"{pb.evaluate(CONTAR_FOTOS)} de {fotos_a}")
        pb.evaluate("id => abrirActaGuardada(id)", rev1_id)
        pb.wait_for_function("state.fase === 8")
        esperar_pdf_listo(pb)
        sin_share = pb.evaluate("""({ oculto: btnCompartir.classList.contains('hidden'),
                                      principal: btnDescargar.classList.contains('btn-primary'), ayuda: emitAyuda.textContent })""")
        r.comprobar("D1 · Sin Web Share: solo «Descargar PDF» (principal) y explicación",
                    sin_share["oculto"] and sin_share["principal"] and "no permite compartir" in sin_share["ayuda"])
        descargar(pb, "#btnDescargar", SALIDA / "D-rev1-B.pdf")
        r.comprobar("D3 · El PDF del acta importada es idéntico al original",
                    texto_pdf(SALIDA / "D-rev1-B.pdf") == texto_pdf(SALIDA / "D-rev1-A.pdf"))

        aviso = importar(pb, SALIDA / "D-copia.zip")
        r.comprobar("D3 · Importar otra vez la misma copia: «ya estaban», sin duplicar",
                    "3 ya estaba(n)" in (aviso or "") and len(actas(pb)) == 3, aviso)

        editar_observaciones(pa, av02_id, "v2 de A")
        exportar(pa, av02_id, SALIDA / "D-av02.zip")
        aviso = importar(pb, SALIDA / "D-av02.zip")
        r.comprobar("D3 · Un borrador más reciente sustituye al del teléfono",
                    "1 actualizada(s)" in (aviso or "") and leer(pb, av02_id)["observaciones"] == "v2 de A", aviso)
        editar_observaciones(pb, av02_id, "v3 de B")
        aviso = importar(pb, SALIDA / "D-av02.zip")
        r.comprobar("D3 · Si el teléfono tiene una versión más reciente, se conserva",
                    "1 sin cambios" in (aviso or "") and leer(pb, av02_id)["observaciones"] == "v3 de B", aviso)

        manipulado = SALIDA / "D-rev1-borrador.zip"
        with zipfile.ZipFile(SALIDA / "D-rev1.zip") as zin, zipfile.ZipFile(manipulado, "w") as zout:
            for info in zin.infolist():
                datos = zin.read(info.filename)
                if info.filename.endswith("acta.json"):
                    ficha = json.loads(datos)
                    ficha["acta"].update(estado="borrador", emitida=None, modificada="2099-01-01T00:00:00.000Z",
                                         observaciones="MODIFICADA")
                    datos = json.dumps(ficha).encode()
                zout.writestr(info.filename, datos)
        aviso = importar(pb, manipulado)
        rev1_b = leer(pb, rev1_id)
        r.comprobar("D3 · Un acta emitida nunca se sobrescribe al importar",
                    "1 sin cambios" in (aviso or "") and rev1_b["estado"] == "emitida"
                    and rev1_b["observaciones"] != "MODIFICADA", aviso)

        cerrar_aviso(pb)
        abrir_panel(pb)
        pb.click(".panel-enlace")
        aviso = esperar_aviso(pb)
        copiado = pb.evaluate("navigator.clipboard.readText()")
        r.comprobar("D4 · Sin Web Share, el enlace de la app se copia para pegarlo", copiado == URL_OFICIAL
                    and "Enlace copiado" in (aviso or ""), aviso)
        pb.evaluate("cerrarMisActas()")
        pb.evaluate("nuevaActa()")
        pb.fill("#expediente", EXP)
        pb.wait_for_function("state.acta.datos.actaNum.includes('-AV-')")
        r.comprobar("D3 · La numeración automática cuenta las actas importadas",
                    pb.evaluate("state.acta.datos.actaNum") == f"{EXP}-AV-03", pb.evaluate("state.acta.datos.actaNum"))
        ctx_b.close()

        # ══ Teléfono C: llega la Rev. 0 y después la Rev. 1 ══
        ctx_c, pc, _ = telefono(p, navegador, externas, errores, web_share=False)
        importar(pc, SALIDA / "D-rev0.zip")
        antes = leer(pc, rev0_id)
        aviso = importar(pc, SALIDA / "D-rev1.zip")
        despues = leer(pc, rev0_id)
        abrir_panel(pc)
        tarjeta = pc.text_content(f".acta-card[data-acta='{rev0_id}']")
        r.comprobar("D3 · Al importar la Rev. 1 emitida, la Rev. 0 del teléfono queda «Sustituida»",
                    not antes.get("sustituidaPor") and despues.get("sustituidaPor") == rev1_id
                    and despues.get("sustituidaRev") == 1 and "Sustituida (Rev. 1)" in tarjeta, aviso)
        pc.evaluate("nuevaActa()")                     # otra acta con el mismo número, escrito a mano
        pc.fill("#actaNum", f"{EXP}-AV-02")
        pc.fill("#tecnico", "Otro técnico")
        pc.evaluate("guardarYa()")
        aviso = importar(pc, SALIDA / "D-av02.zip")
        r.comprobar("D3 · Avisa si un acta importada repite el número de otra del teléfono",
                    "1 acta(s) nueva(s)" in (aviso or "") and f"número repetido en actas distintas: {EXP}-AV-02" in (aviso or ""),
                    aviso)
        ctx_c.close()

        # ══ Teléfono D: la copia vuelta a comprimir en Windows ══
        ctx_d, pd, _ = telefono(p, navegador, externas, errores, web_share=False)
        recomprimir(SALIDA / "D-copia.zip", SALIDA / "D-copia-windows.zip")
        aviso = importar(pd, SALIDA / "D-copia-windows.zip")
        r.comprobar("D3 · Importa un ZIP comprimido de nuevo (Windows) con carpetas y archivos de macOS",
                    "3 acta(s) nueva(s)" in (aviso or "") and pd.evaluate(CONTAR_FOTOS) == fotos_a, aviso)
        ctx_d.close()

        # ══ Teléfono E: archivos que no son actas, dañados o manipulados ══
        ctx_e, pe, _ = telefono(p, navegador, externas, errores, web_share=False)
        aviso = importar(pe, SALIDA / "D-compartido.pdf")
        r.comprobar("D3 · Un archivo que no es ZIP se rechaza con un aviso claro",
                    "No se ha podido importar" in (aviso or "") and "no es un ZIP" in (aviso or ""), aviso)
        with zipfile.ZipFile(SALIDA / "D-vacio.zip", "w") as z:
            z.writestr("hola.txt", "nada")
        aviso = importar(pe, SALIDA / "D-vacio.zip")
        r.comprobar("D3 · Un ZIP sin actas se rechaza", "no contiene actas" in (aviso or ""), aviso)
        corromper(SALIDA / "D-copia.zip", SALIDA / "D-copia-danada.zip", "425_2026_CON-AV-02_Rev0/fotos/01.jpg")
        aviso = importar(pe, SALIDA / "D-copia-danada.zip")
        en_e = actas(pe)
        r.comprobar("D3 · Una foto dañada invalida solo su acta, sin dejar restos (CRC)",
                    "2 acta(s) nueva(s)" in (aviso or "") and "1 no válida(s)" in (aviso or "")
                    and av02_id not in en_e
                    and pe.evaluate(CONTAR_FOTOS) == sum(len(a["fotos"]) for a in en_e.values()), aviso)

        with zipfile.ZipFile(SALIDA / "D-copia.zip") as z:
            base = json.loads(z.read("425_2026_CON-AV-02_Rev0/acta.json"))
            foto = z.read("425_2026_CON-AV-02_Rev0/fotos/01.jpg")
        xss = copy.deepcopy(base)
        xss["acta"].update(id="acta-xss-1", observaciones="<b>negrita</b>",
                           firmasAsistentes={"__proto__": {"contaminado": True}}, __proto__={"contaminado": True})
        xss["acta"]["datos"].update(actaNum='XSS-01<img src=x onerror="window.__xss=1">',
                                    tecnico='<img src=x onerror="window.__xss=2">Técnico')
        xss["acta"]["asistentes"][0]["nombre"] = '<script>window.__xss=3</script>Asistente'
        ruta = copy.deepcopy(base)
        ruta["acta"]["id"] = "acta-ruta-1"
        ruta["acta"]["fotos"][0]["archivo"] = "../../secreto.jpg"
        with zipfile.ZipFile(SALIDA / "D-manipulado.zip", "w") as z:
            for carpeta, ficha in (("XSS", xss), ("RUTA", ruta)):
                z.writestr(f"{carpeta}/acta.json", json.dumps(ficha))
                z.writestr(f"{carpeta}/fotos/01.jpg", foto)
        aviso = importar(pe, SALIDA / "D-manipulado.zip")
        pe.evaluate("abrirActaGuardada('acta-xss-1')")
        pe.wait_for_function("state.acta.id === 'acta-xss-1'")
        pe.evaluate("irAFase(2)")
        pe.evaluate("irAFase(7)")
        revision = pe.inner_text("#reviewGeneral") + pe.inner_text("#reviewAsistentes")
        r.comprobar("D3 · Contenido manipulado: se importa como texto, sin ejecutar nada ni contaminar objetos",
                    "1 acta(s) nueva(s)" in (aviso or "") and "1 no válida(s)" in (aviso or "")
                    and pe.evaluate("window.__xss === undefined && ({}).contaminado === undefined")
                    and '<img src=x onerror="window.__xss=2">Técnico' in revision, aviso)
        ctx_e.close()

        r.comprobar("Sin peticiones a internet", not externas, "; ".join(externas[:3]))
        r.comprobar("Sin errores JS", not errores, "; ".join(errores[:3]))
        ctx_a.close()
        navegador.close()
    srv.shutdown()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
