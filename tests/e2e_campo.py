"""Pruebas del bloque B (robustez en campo) y de la app instalable sin cobertura, en un Pixel 7 emulado.

Uso (desde la raíz del repo, con los mismos requisitos que e2e_acta.py):
    python tests/e2e_campo.py
"""
import pathlib
import re
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from comun import (RAIZ, SALIDA, TECNICO, Resultados, abrir, cerrar_aviso, colocaciones_de_imagenes,  # noqa: E402
                   contexto_movil, desviacion_maxima, esperar_fotos, firmar, rellenar_identificacion,
                   servidor, texto_pdf, vigilar_red)
from generar_fotos import generar, generar_con_exif  # noqa: E402


def emitir(contexto, pagina, ruta_pdf):
    """Desde cualquier fase anterior a las firmas: avanza, firma, emite y guarda el PDF."""
    while pagina.evaluate("state.fase") < 6:
        pagina.click("#btnNext")
    firmar(contexto.new_cdp_session(pagina), pagina)
    pagina.click("#btnNext")
    pagina.click("#btnNext")
    with pagina.expect_download(timeout=120000) as descarga:
        pagina.click("#btnDescargar")
    descarga.value.save_as(str(ruta_pdf))
    pagina.wait_for_function("state.acta.estado === 'emitida'")


def contar_actas(pagina):
    pagina.click("button.header-btn")
    pagina.wait_for_selector("#panelActas.open")
    pagina.wait_for_timeout(200)
    return pagina.locator(".acta-card").count()


def main():
    r = Resultados()
    SALIDA.mkdir(parents=True, exist_ok=True)
    horizontal, vertical, cuadrada = (str(f) for f in generar(SALIDA / "fotos"))
    foto_exif = str(generar_con_exif(SALIDA / "fotos"))
    srv = servidor()
    externas, errores = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()

        # ── B1 · Autoguardado: tras recargar, el acta sigue donde estaba ──
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pg = abrir(ctx, errores)
        r.comprobar("Un acta nueva sin datos no se guarda", pg.evaluate("state.persistida") is False)
        rellenar_identificacion(pg, acta="B-001")
        pg.click("#btnNext")                       # asistentes → fotos
        pg.set_input_files("#photoInput", [horizontal, vertical])
        esperar_fotos(pg, 2)
        pg.click("#btnNext")                       # fotos → notas
        pg.locator("textarea.comment-textarea").nth(0).fill("Comentario que debe sobrevivir a la recarga")
        pg.wait_for_timeout(900)
        r.comprobar("Indicador «Guardada en el teléfono»", "Guardada" in pg.text_content("#estadoGuardado"))
        pg.reload()
        pg.wait_for_function("state.acta && state.acta.datos.actaNum === 'B-001' && state.acta.fotos.length === 2")
        restaurada = pg.evaluate("""({ fase: state.fase, fotos: state.acta.fotos.length, gps: Boolean(state.acta.gps),
            comentario: state.acta.fotos[0].comentario, tecnico: document.getElementById('tecnico').value,
            imagenes: document.querySelectorAll('#commentsContainer img').length })""")
        r.comprobar("Tras recargar, el acta sigue donde estaba (fase, datos, GPS, fotos y notas)", restaurada == {
            "fase": 4, "fotos": 2, "gps": True, "comentario": "Comentario que debe sobrevivir a la recarga",
            "tecnico": TECNICO, "imagenes": 2}, str(restaurada))

        # ── Emisión y solo lectura ──
        emitir(ctx, pg, SALIDA / "acta-B-001.pdf")
        r.comprobar("Descargar el PDF emite el acta", pg.evaluate("state.acta.estado") == "emitida")
        pg.click("#btnBack")
        r.comprobar("El acta emitida se puede revisar (fase 7) pero no volver a editar",
                    pg.evaluate("state.fase") == 7 and pg.evaluate("btnBack.style.display") == "none")
        pg.evaluate("irAFase(1)")
        aviso = cerrar_aviso(pg) or ""
        r.comprobar("Intentar editar un acta emitida avisa de que es de solo lectura",
                    "emitida" in aviso.lower() and pg.evaluate("state.fase") == 7, aviso)
        pg.reload()
        pg.wait_for_function("state.acta && state.acta.estado === 'emitida'")
        r.comprobar("Al reabrir la app, el acta emitida se muestra en solo lectura",
                    pg.evaluate("state.fase") == 8 and pg.is_visible("#btnCorregir") and "Emitida" in pg.text_content("#estadoGuardado"))

        # ── B2 · Mis actas: corregir, nueva visita y borrar ──
        n = contar_actas(pg)
        r.comprobar("Mis actas muestra el acta emitida", n == 1 and "Emitida" in pg.text_content(".acta-card"))
        pg.screenshot(path=str(SALIDA / "mis-actas.png"))
        pg.click(".acta-card button:has-text('Corregir')")
        pg.wait_for_selector("#promptOverlay.open", timeout=10000)  # motivo de la revisión
        pg.fill("#promptTexto", "Corrección de prueba")
        pg.click("#promptAceptar")
        pg.wait_for_selector("#alertOverlay.open", timeout=10000)   # aviso «Rev. 1 creada»
        cerrar_aviso(pg)
        copia = pg.evaluate("""({ estado: state.acta.estado, fotos: state.acta.fotos.length, firma: state.acta.firma.length,
            num: state.acta.datos.actaNum, rev: state.acta.revision, fase: state.fase, origen: Boolean(state.acta.corrigeA),
            comentario: state.acta.fotos[0].comentario })""")
        r.comprobar("«Corregir» crea la Rev. 1 editable con fotos y notas, sin firma", copia == {
            "estado": "borrador", "fotos": 2, "firma": 0, "num": "B-001", "rev": 1, "fase": 1, "origen": True,
            "comentario": "Comentario que debe sobrevivir a la recarga"}, str(copia))
        r.comprobar("Mis actas: emitida + copia", contar_actas(pg) == 2)
        pg.click(".acta-card.actual button:has-text('Nueva visita')")
        pg.wait_for_timeout(700)
        visita = pg.evaluate("""({ num: state.acta.datos.actaNum, tecnico: state.acta.datos.tecnico,
            expediente: state.acta.datos.expediente, fotos: state.acta.fotos.length, gps: state.acta.gps })""")
        r.comprobar("«Nueva visita» copia técnico y expediente y numera sola (sin fotos ni GPS)", visita == {
            "num": "425_2026.CON-AV-01", "tecnico": TECNICO, "expediente": "425_2026.CON",
            "fotos": 0, "gps": None}, str(visita))
        r.comprobar("Mis actas: 3 actas", contar_actas(pg) == 3)
        pg.once("dialog", lambda dialogo: dialogo.accept())
        pg.click(".acta-card.actual button.peligro")
        pg.wait_for_function("document.querySelectorAll('.acta-card').length === 2")
        r.comprobar("«Borrar» quita el acta del teléfono", pg.locator(".acta-card").count() == 2)
        pg.click(".panel-close")
        ctx.close()

        # ── B3 · GPS en vivo: muestra la precisión y se fija al llegar a ±10 m ──
        ctx = contexto_movil(p, navegador, gps={"latitude": 37.4, "longitude": -5.99, "accuracy": 45})
        pg = abrir(ctx, errores)
        pg.click("#gpsBtn")
        pg.wait_for_function("document.getElementById('gpsStatus').textContent.includes('±45 m')", timeout=10000)
        r.comprobar("GPS en vivo: muestra la precisión y ofrece «Usar esta posición»", pg.is_visible("#gpsUsarBtn"),
                    pg.text_content("#gpsStatus"))
        pg.screenshot(path=str(SALIDA / "gps-en-vivo.png"))
        ctx.set_geolocation({"latitude": 37.389210, "longitude": -5.984460, "accuracy": 6})
        try:
            pg.wait_for_selector("#gpsStatus.ok", timeout=8000)
            fijada = pg.evaluate("state.acta.gps")
            r.comprobar("Al mejorar a ±6 m la posición se fija sola", fijada and fijada["acc"] == 6, str(fijada))
        except Exception:
            r.comprobar("Al mejorar a ±6 m la posición se fija sola", False, "no llegó la actualización")
        ctx.close()

        # ── B5 · Permiso denegado: explica cómo darlo ──
        ctx = contexto_movil(p, navegador, permisos=())
        pg = abrir(ctx, errores)
        pg.click("#gpsBtn")
        pg.wait_for_selector("#gpsStatus.err", timeout=10000)
        texto = pg.text_content("#gpsStatus")
        r.comprobar("Permiso denegado: explica cómo activarlo y la opción sin cobertura",
                    "Permiso de ubicación denegado" in texto and "Sin cobertura GPS" in texto, texto[:90])

        # ── B4 · Sin cobertura: referencia obligatoria y coordenadas opcionales ──
        rellenar_identificacion(pg, acta="B-SIN-GPS", gps=False, avanzar=False)
        pg.click("#btnNext")
        r.comprobar("Sin GPS ni referencia no se puede avanzar", "Ubicación requerida" in (cerrar_aviso(pg) or ""))
        pg.check("#sinGpsCheck")
        pg.click("#btnNext")
        r.comprobar("Sin cobertura, la referencia es obligatoria", "Referencia requerida" in (cerrar_aviso(pg) or ""))
        pg.fill("#sinGpsRef", "PK 2+100, andén vía 1")
        pg.fill("#sinGpsLat", "37,38921")
        pg.fill("#sinGpsLng", "abc")
        pg.click("#btnNext")
        r.comprobar("Coordenadas manuales no válidas: se avisa", "Coordenadas no válidas" in (cerrar_aviso(pg) or ""))
        pg.screenshot(path=str(SALIDA / "sin-cobertura.png"), full_page=True)
        pg.fill("#sinGpsLng", "-5.98446")
        pg.click("#btnNext")
        r.comprobar("Con referencia y coordenadas válidas se avanza", pg.evaluate("state.fase") == 2)
        pg.click("#btnNext")                       # asistentes → fotos

        # ── B7 · Hora y GPS de la propia foto (EXIF) ──
        pg.set_input_files("#photoInput", [foto_exif])
        esperar_fotos(pg, 1)
        foto = pg.evaluate("state.acta.fotos[0]")
        r.comprobar("Se leen la hora y el GPS de la cámara (EXIF)",
                    foto["hora"] == "2026-10-21 18:05" and foto["horaFuente"] == "camara"
                    and foto["gps"] == {"lat": "37.389210", "lng": "-5.984460", "fuente": "camara"}, str(foto))
        pg.screenshot(path=str(SALIDA / "fotos-con-hora.png"))
        emitir(ctx, pg, SALIDA / "acta-sin-cobertura.pdf")
        texto = texto_pdf(SALIDA / "acta-sin-cobertura.pdf")
        r.comprobar("PDF: ubicación sin cobertura con referencia y coordenadas",
                    "Sin cobertura GPS · Ref.: PK 2+100, andén vía 1 · Coord. manuales: 37.389210, -5.984460" in texto)
        r.comprobar("PDF: hora y GPS de la cámara bajo la foto", "21/10/2026 18:05 · 37.389210, -5.984460 (cámara)" in texto)
        ctx.close()

        # ── B6 · Hasta 50 fotos, guardadas en el teléfono ──
        ctx = contexto_movil(p, navegador)
        pg = abrir(ctx, errores)
        rellenar_identificacion(pg, acta="B-50")
        pg.click("#btnNext")
        pg.set_input_files("#photoInput", [horizontal, vertical, cuadrada] * 20)
        esperar_fotos(pg, 50, espera=240000)
        aviso = cerrar_aviso(pg) or ""
        r.comprobar("Máximo 50 fotos (avisa de las que sobran)", "10 no se han añadido" in aviso, aviso)
        pg.wait_for_timeout(900)
        pg.reload()
        pg.wait_for_function("state.acta && state.acta.fotos.length === 50", timeout=60000)
        r.comprobar("Las 50 fotos se recuperan tras recargar", pg.evaluate("state.blobs.size") == 50)
        emitir(ctx, pg, SALIDA / "acta-50-fotos.pdf")
        lector, imagenes = colocaciones_de_imagenes(SALIDA / "acta-50-fotos.pdf")
        fotos_pdf, desvio = desviacion_maxima(imagenes)
        tam = (SALIDA / "acta-50-fotos.pdf").stat().st_size
        r.comprobar("PDF de 50 fotos: todas, sin deformar", len(fotos_pdf) == 50 and desvio < 0.01,
                    f"{len(lector.pages)} páginas, {tam / 1024 / 1024:.1f} MB")
        ctx.close()

        # ── B5 · Abierta como archivo (lo que pasa al recibirla por WhatsApp) ──
        ctx = contexto_movil(p, navegador)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errores.append(str(e)))
        pg.goto((RAIZ / "index.html").as_uri())
        pg.wait_for_load_state("load")
        r.comprobar("Aviso visible al abrir la app como archivo",
                    pg.is_visible("#avisoEntorno") and pg.get_attribute("#avisoEntornoEnlace", "href", timeout=5000).startswith("https://"))
        pg.click("#gpsBtn")
        r.comprobar("El GPS explica que hay que abrirla desde el enlace", "abierta como archivo" in pg.text_content("#gpsStatus"))
        ctx.close()

        # ── App instalable y sin cobertura ──
        ctx = contexto_movil(p, navegador)
        pg = abrir(ctx, errores)
        pg.wait_for_function("navigator.serviceWorker.controller !== null", timeout=20000)
        manifiesto = pg.evaluate("fetch('manifest.webmanifest').then(r => r.json())")
        tamanos = {i["sizes"] + "/" + i.get("purpose", "any") for i in manifiesto["icons"]}
        r.comprobar("Manifiesto completo para instalar la app",
                    manifiesto["display"] == "standalone" and manifiesto["start_url"] == "./"
                    and {"192x192/any", "512x512/any", "512x512/maskable"} <= tamanos)
        iconos_ok = all(Image.open(RAIZ / i["src"]).size == tuple(map(int, i["sizes"].split("x"))) for i in manifiesto["icons"])
        r.comprobar("Iconos con el tamaño declarado", iconos_ok)
        version_sw = re.search(r"const VERSION = '([^']+)'", (RAIZ / "sw.js").read_text(encoding="utf-8"))[1]
        r.comprobar("La versión de sw.js coincide con la de la app", version_sw == pg.evaluate("VERSION"), version_sw)
        ctx.set_offline(True)
        pg.reload()
        pg.wait_for_function("typeof state !== 'undefined' && state.acta !== null", timeout=15000)
        r.comprobar("Sin conexión la app se abre desde la copia del teléfono",
                    pg.evaluate("Boolean(window.jspdf && new window.jspdf.jsPDF().getFontList().ActaSans)"))
        rellenar_identificacion(pg, acta="B-OFFLINE")
        pg.click("#btnNext")
        pg.set_input_files("#photoInput", [cuadrada])
        esperar_fotos(pg, 1)
        emitir(ctx, pg, SALIDA / "acta-sin-conexion.pdf")
        r.comprobar("Sin conexión se genera el PDF", (SALIDA / "acta-sin-conexion.pdf").stat().st_size > 10_000)
        ctx.close()

        r.comprobar("Sin peticiones a internet", not externas, "; ".join(externas[:3]))
        r.comprobar("Sin errores JS", not errores, "; ".join(errores[:3]))
        navegador.close()
    srv.shutdown()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
