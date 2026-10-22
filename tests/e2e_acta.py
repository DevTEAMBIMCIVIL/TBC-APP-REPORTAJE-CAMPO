"""Prueba de extremo a extremo de la app en un móvil emulado (Chromium, Pixel 7).

Requisitos (una vez):
    pip install playwright pypdf pillow
    python -m playwright install chromium

Uso (desde la raíz del repo):
    python tests/e2e_acta.py

Deja el PDF y las capturas en tests/salida/. Devuelve código 1 si falla alguna comprobación.
"""
import functools
import http.server
import pathlib
import re
import sys
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from generar_fotos import generar  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "tests" / "salida"
PUERTO = 8765
URL = f"http://localhost:{PUERTO}/index.html"

COMENTARIO_LARGO = (
    "Fisura longitudinal en la viga principal del lado norte, con abertura aproximada de 0,3 mm y "
    "longitud visible de 1,20 m. Se aprecian manchas de humedad en el entorno y desprendimiento "
    "puntual del recubrimiento con armadura vista y principio de oxidación. Se recomienda "
    "picado, pasivado de armaduras y reparación con mortero R4, así como seguimiento con testigos.")
DESCRIPCION_LARGA = (
    "Inspección de estructura existente para legalización de vivienda unifamiliar, revisión de "
    "cimentación, forjados y cubierta, con toma de fotografías de patologías")
COMENTARIO_SIMBOLOS = "<img src=x onerror=\"window.__xss=1\"> Ø16 cada 20 cm; f'ck ≥ 25 N/mm² & ±2 °C"

resultados = []


def comprobar(nombre, condicion, detalle=""):
    resultados.append((bool(condicion), nombre, detalle))
    print(f"{'OK   ' if condicion else 'FALLO'} {nombre}" + (f"  ({detalle})" if detalle else ""), flush=True)


def normalizar(texto):
    return re.sub(r"\s+", " ", texto).strip()


def servidor():
    manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(RAIZ))
    manejador.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PUERTO), manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def colocaciones_de_imagenes(ruta_pdf):
    """[(página, nombre, ancho_pt, alto_pt, ancho_px, alto_px, filtro, bytes)] de cada imagen dibujada."""
    lector, salida = PdfReader(str(ruta_pdf)), []
    for n, pagina in enumerate(lector.pages, 1):
        contenido = pagina.get_contents().get_data().decode("latin-1")
        xobjetos = pagina["/Resources"].get("/XObject", {})
        for m in re.finditer(r"([\d.]+) 0 0 ([\d.]+) [\d.-]+ [\d.-]+ cm\s*/(\S+) Do", contenido):
            xo = xobjetos["/" + m[3]].get_object()
            salida.append((n, m[3], float(m[1]), float(m[2]), int(xo["/Width"]), int(xo["/Height"]),
                           str(xo.get("/Filter")), len(xo.get_data())))
    return lector, salida


def firmar(cdp, pagina, desplazamiento=0):
    caja = pagina.locator("#sigCanvas").bounding_box()
    x0, y0 = caja["x"] + 30 + desplazamiento, caja["y"] + 40
    puntos = [(x0 + i * 12, y0 + (25 if i % 2 else 0) + i * 2) for i in range(22)]
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": puntos[0][0], "y": puntos[0][1]}]})
    for x, y in puntos[1:]:
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


LIENZO_CON_TINTA = """(() => { const c = document.getElementById('sigCanvas');
  if (!c.width || !c.height) return false;
  return c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some((v, i) => i % 4 === 3 && v > 0); })()"""


def rellenar_identificacion(pagina):
    pagina.fill("#actaNum", "TBC-2026-0042")
    pagina.fill("#tecnico", "Blas González González")
    pagina.fill("#expediente", "425_2026.CON")
    pagina.fill("#descripcion", DESCRIPCION_LARGA)
    pagina.click("button.gps-btn")
    pagina.wait_for_selector("#gpsStatus.ok", timeout=15000)
    pagina.click("#btnNext")


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    fotos = generar(SALIDA / "fotos")
    horizontal, vertical, cuadrada = (str(f) for f in fotos)
    srv = servidor()
    externas, errores = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        contexto = navegador.new_context(
            **p.devices["Pixel 7"], locale="es-ES", timezone_id="Europe/Madrid", accept_downloads=True,
            geolocation={"latitude": 37.389210, "longitude": -5.984460, "accuracy": 8}, permissions=["geolocation"])

        def vigilar_red(ruta):
            if urlparse(ruta.request.url).hostname not in ("localhost", "127.0.0.1"):
                externas.append(ruta.request.url)
                return ruta.abort()
            return ruta.continue_()
        contexto.route("**/*", vigilar_red)

        pagina = contexto.new_page()
        pagina.on("pageerror", lambda e: errores.append(str(e)))
        pagina.goto(URL)
        pagina.wait_for_load_state("networkidle")
        comprobar("Fuente ActaSans registrada en jsPDF",
                  pagina.evaluate("Boolean(new window.jspdf.jsPDF().getFontList().ActaSans)"))
        cabecera = pagina.evaluate("document.querySelector('.header-text p').textContent")
        comprobar("Versión visible en la cabecera", cabecera.endswith(f"v{pagina.evaluate('VERSION')}"), cabecera)

        # ── Fase 1 → 2 ──
        rellenar_identificacion(pagina)
        comprobar("Fase 1 validada con GPS", pagina.evaluate("state.fase") == 2)

        # ── Fase 2: orden de las fotos ──
        pagina.set_input_files("#photoInput", [horizontal, vertical, cuadrada])
        pagina.wait_for_function("state.fotos.length === 3 && state.fotosEnProceso === 0", timeout=30000)
        dims = pagina.evaluate("state.fotos.map(f => [f.ancho, f.alto])")
        comprobar("Orden de fotos = orden de selección", dims == [[1200, 900], [1200, 1600], [1200, 1200]], str(dims))
        pagina.click("#btnNext")

        # ── Fase 3: comentarios ──
        areas = pagina.locator("textarea.comment-textarea")
        areas.nth(0).fill(COMENTARIO_LARGO)
        areas.nth(1).fill("Comentario inicial foto 2")
        areas.nth(2).fill(COMENTARIO_SIMBOLOS)
        pagina.click("#btnNext")

        # ── Fase 4: firma sin necesidad de girar ni redimensionar ──
        tam = pagina.evaluate("[sigCanvas.width, sigCanvas.height]")
        comprobar("Lienzo de firma dimensionado al entrar en la fase 4", tam[0] > 0 and tam[1] > 0, f"{tam[0]}×{tam[1]} px")
        cdp = contexto.new_cdp_session(pagina)
        firmar(cdp, pagina)
        comprobar("El trazo táctil se dibuja", pagina.evaluate(LIENZO_CON_TINTA))
        vp = pagina.viewport_size
        pagina.set_viewport_size({"width": vp["height"], "height": vp["width"]})   # girar a horizontal
        pagina.wait_for_timeout(400)
        tam_giro = pagina.evaluate("[sigCanvas.width, sigCanvas.height]")
        comprobar("La firma se conserva al girar el móvil",
                  tam_giro != tam and pagina.evaluate(LIENZO_CON_TINTA), f"{tam} → {tam_giro}")
        pagina.set_viewport_size(vp)
        pagina.wait_for_timeout(300)
        pagina.screenshot(path=str(SALIDA / "fase4_firma.png"), full_page=True)
        n_errores = len(errores)
        pagina.click("#btnNext")
        comprobar("Avanza a revisión sin errores JS", pagina.evaluate("state.fase") == 5 and len(errores) == n_errores,
                  "; ".join(errores[n_errores:]))

        # ── Fase 5: revisión construida al entrar ──
        revision = pagina.evaluate("""({
            campos: document.querySelectorAll('#reviewGeneral .review-field').length,
            fotos: document.querySelectorAll('#reviewPhotos .review-photo-row').length,
            firma: Boolean(document.querySelector('#reviewFirma img')),
            contador: document.getElementById('reviewPhotoCount').textContent,
            texto: document.getElementById('reviewPhotos').innerText })""")
        comprobar("Revisión completa al entrar (7 campos, 3 fotos, firma)",
                  revision["campos"] == 7 and revision["fotos"] == 3 and revision["firma"] and revision["contador"] == "3",
                  str({k: v for k, v in revision.items() if k != "texto"}))
        comprobar("Texto del usuario escapado (sin HTML inyectado)",
                  pagina.evaluate("window.__xss === undefined") and "<img src=x" in revision["texto"])
        pagina.screenshot(path=str(SALIDA / "fase5_revision.png"), full_page=True)

        # Volver a la fase 3, corregir y regresar: la revisión debe reflejarlo
        pagina.click("#btnBack")
        pagina.click("#btnBack")
        pagina.locator("textarea.comment-textarea").nth(1).fill("Comentario CORREGIDO foto 2")
        pagina.click("#btnNext")
        pagina.click("#btnNext")
        texto = pagina.evaluate("document.getElementById('reviewPhotos').innerText")
        comprobar("La revisión refleja los cambios hechos al volver atrás",
                  "CORREGIDO" in texto and "Comentario inicial" not in texto)

        # ── Fase 6: PDF ──
        pagina.click("#btnNext")
        with pagina.expect_download(timeout=30000) as descarga:
            pagina.click("button.btn-primary:has-text('Descargar')")
        ruta_pdf = SALIDA / "acta-prueba.pdf"
        descarga.value.save_as(str(ruta_pdf))
        lector, imagenes = colocaciones_de_imagenes(ruta_pdf)
        texto_pdf = normalizar(" ".join(pag.extract_text() for pag in lector.pages))
        fotos_pdf = [i for i in imagenes if i[6] == "/DCTDecode" and i[4] >= 900]
        desvio = max(abs((w / h) / (pw / ph) - 1) for _, _, w, h, pw, ph, _, _ in fotos_pdf)
        comprobar("Fotos del PDF sin deformar", len(fotos_pdf) == 3 and desvio < 0.01, f"desviación máx. {desvio:.2%}")
        comprobar("Comentario largo completo en el PDF", normalizar(COMENTARIO_LARGO) in texto_pdf)
        comprobar("Descripción larga completa en el PDF", normalizar(DESCRIPCION_LARGA) in texto_pdf)
        comprobar("Símbolos técnicos en el PDF (Ø ≥ ² ±)", all(s in texto_pdf for s in ("Ø16", "≥ 25 N/mm²", "±2 °C")))
        firma_pdf = [i for i in imagenes if i[4] == 750 and i[5] == 300]
        comprobar("Firma comprimida en el PDF", len(firma_pdf) == 1 and firma_pdf[0][7] < 60_000,
                  f"{firma_pdf[0][7] / 1024:.0f} KB" if firma_pdf else "no encontrada")
        tam_pdf = ruta_pdf.stat().st_size
        comprobar("Tamaño del PDF razonable (< 800 KB con 3 fotos)", tam_pdf < 800_000, f"{tam_pdf / 1024:.0f} KB")

        # ── Límite de 10 fotos y paginación con 10 fotos y comentarios largos ──
        pagina3 = contexto.new_page()
        pagina3.on("pageerror", lambda e: errores.append(str(e)))
        pagina3.goto(URL)
        pagina3.wait_for_load_state("networkidle")
        rellenar_identificacion(pagina3)
        pagina3.set_input_files("#photoInput", [horizontal, vertical, cuadrada] * 4)
        pagina3.wait_for_function("state.fotosEnProceso === 0 && state.fotos.length > 0", timeout=60000)
        comprobar("Máximo 10 fotos", pagina3.evaluate("state.fotos.length") == 10)
        pagina3.click("#btnNext")
        areas = pagina3.locator("textarea.comment-textarea")
        for i in range(10):
            areas.nth(i).fill(f"Foto {i + 1}. " + COMENTARIO_LARGO * (1 + i % 3))
        largo = pagina3.evaluate("Math.max(...state.fotos.map(f => f.comentario.length))")
        comprobar("Comentario limitado a 1.000 caracteres", largo == 1000, f"{largo}")
        pagina3.click("#btnNext")
        firmar(contexto.new_cdp_session(pagina3), pagina3)
        pagina3.click("#btnNext")
        pagina3.click("#btnNext")
        with pagina3.expect_download(timeout=60000) as descarga:
            pagina3.click("button.btn-primary:has-text('Descargar')")
        ruta_pdf10 = SALIDA / "acta-prueba-10-fotos.pdf"
        descarga.value.save_as(str(ruta_pdf10))
        lector10, imagenes10 = colocaciones_de_imagenes(ruta_pdf10)
        texto10 = normalizar(" ".join(pag.extract_text() for pag in lector10.pages))
        fotos10 = [i for i in imagenes10 if i[6] == "/DCTDecode" and i[4] >= 900]
        desvio10 = max(abs((w / h) / (pw / ph) - 1) for _, _, w, h, pw, ph, _, _ in fotos10)
        comprobar("PDF de 10 fotos: todas presentes y sin deformar", len(fotos10) == 10 and desvio10 < 0.01,
                  f"{len(lector10.pages)} páginas, desviación máx. {desvio10:.2%}")
        textos = pagina3.evaluate("state.fotos.map(f => f.comentario)")
        comprobar("PDF de 10 fotos: los 10 comentarios completos",
                  all(normalizar(t) in texto10 for t in textos))

        comprobar("Sin peticiones a internet (todo local)", not externas, "; ".join(externas[:3]))
        comprobar("Sin errores JS en toda la prueba", not errores, "; ".join(errores[:3]))
        contexto.close()

        # ── Fecha por defecto en hora local (a las 00:30 del 23/10, hora de Madrid) ──
        # En un contexto aparte: el reloj simulado afecta a todo el contexto.
        contexto_reloj = navegador.new_context(**p.devices["Pixel 7"], locale="es-ES", timezone_id="Europe/Madrid")
        pagina_reloj = contexto_reloj.new_page()
        pagina_reloj.clock.install(time="2026-10-23T00:30:00+02:00")
        pagina_reloj.goto(URL)
        pagina_reloj.wait_for_load_state("networkidle")
        fecha = pagina_reloj.evaluate("[fechaVisita.value, horaVisita.value]")
        comprobar("Fecha por defecto local a las 00:30", fecha == ["2026-10-23", "00:30"], str(fecha))
        contexto_reloj.close()
        navegador.close()
    srv.shutdown()

    fallos = [r for r in resultados if not r[0]]
    print(f"\n{len(resultados) - len(fallos)}/{len(resultados)} comprobaciones correctas. Salida en {SALIDA}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
