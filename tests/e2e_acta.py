"""Prueba de extremo a extremo del flujo principal (fases 1 a 6 y PDF) en un móvil emulado (Pixel 7).

Requisitos (una vez):
    pip install playwright pypdf pillow
    python -m playwright install chromium

Uso (desde la raíz del repo):
    python tests/e2e_acta.py

Deja el PDF y las capturas en tests/salida/. Devuelve código 1 si falla alguna comprobación.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from comun import (COMENTARIO_LARGO, DESCRIPCION_LARGA, LIENZO_CON_TINTA, SALIDA, URL, Resultados,  # noqa: E402
                   colocaciones_de_imagenes, contexto_movil, desviacion_maxima, esperar_fotos, firmar,
                   normalizar, rellenar_identificacion, servidor, texto_pdf, vigilar_red)
from generar_fotos import generar  # noqa: E402

COMENTARIO_SIMBOLOS = "<img src=x onerror=\"window.__xss=1\"> Ø16 cada 20 cm; f'ck ≥ 25 N/mm² & ±2 °C"


def main():
    r = Resultados()
    SALIDA.mkdir(parents=True, exist_ok=True)
    horizontal, vertical, cuadrada = (str(f) for f in generar(SALIDA / "fotos"))
    srv = servidor()
    externas, errores = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        contexto = contexto_movil(p, navegador)
        vigilar_red(contexto, externas)
        pagina = contexto.new_page()
        pagina.on("pageerror", lambda e: errores.append(str(e)))
        pagina.goto(URL)
        pagina.wait_for_load_state("networkidle")
        r.comprobar("Fuente ActaSans registrada en jsPDF",
                    pagina.evaluate("Boolean(new window.jspdf.jsPDF().getFontList().ActaSans)"))
        cabecera = pagina.evaluate("document.querySelector('.header-text p').textContent")
        r.comprobar("Versión visible en la cabecera", cabecera.endswith(f"v{pagina.evaluate('VERSION')}"), cabecera)

        # ── Fase 1 → 2 ──
        rellenar_identificacion(pagina)
        r.comprobar("Fase 1 validada con GPS", pagina.evaluate("state.fase") == 2)

        # ── Fase 2: orden de las fotos y GPS de cada foto ──
        pagina.wait_for_function("gpsFotos.ultima !== null", timeout=10000)
        pagina.set_input_files("#photoInput", [horizontal, vertical, cuadrada])
        esperar_fotos(pagina, 3)
        dims = pagina.evaluate("state.acta.fotos.map(f => [f.ancho, f.alto])")
        r.comprobar("Orden de fotos = orden de selección", dims == [[1200, 900], [1200, 1600], [1200, 1200]], str(dims))
        fuentes = pagina.evaluate("state.acta.fotos.map(f => f.gps && f.gps.fuente)")
        r.comprobar("Cada foto guarda la posición del móvil", fuentes == ["movil"] * 3, str(fuentes))
        pagina.click("#btnNext")

        # ── Fase 3: comentarios ──
        areas = pagina.locator("textarea.comment-textarea")
        areas.nth(0).fill(COMENTARIO_LARGO)
        areas.nth(1).fill("Comentario inicial foto 2")
        areas.nth(2).fill(COMENTARIO_SIMBOLOS)
        pagina.click("#btnNext")

        # ── Fase 4: firma sin necesidad de girar ni redimensionar ──
        tam = pagina.evaluate("[sigCanvas.width, sigCanvas.height]")
        r.comprobar("Lienzo de firma dimensionado al entrar en la fase 4", tam[0] > 0 and tam[1] > 0, f"{tam[0]}×{tam[1]} px")
        cdp = contexto.new_cdp_session(pagina)
        firmar(cdp, pagina)
        r.comprobar("El trazo táctil se dibuja", pagina.evaluate(LIENZO_CON_TINTA))
        vp = pagina.viewport_size
        pagina.set_viewport_size({"width": vp["height"], "height": vp["width"]})   # girar a horizontal
        pagina.wait_for_timeout(400)
        tam_giro = pagina.evaluate("[sigCanvas.width, sigCanvas.height]")
        r.comprobar("La firma se conserva al girar el móvil",
                    tam_giro != tam and pagina.evaluate(LIENZO_CON_TINTA), f"{tam} → {tam_giro}")
        pagina.set_viewport_size(vp)
        pagina.wait_for_timeout(300)
        pagina.screenshot(path=str(SALIDA / "fase4_firma.png"), full_page=True)
        n_errores = len(errores)
        pagina.click("#btnNext")
        r.comprobar("Avanza a revisión sin errores JS", pagina.evaluate("state.fase") == 5 and len(errores) == n_errores,
                    "; ".join(errores[n_errores:]))

        # ── Fase 5: revisión construida al entrar ──
        revision = pagina.evaluate("""({
            campos: document.querySelectorAll('#reviewGeneral .review-field').length,
            fotos: document.querySelectorAll('#reviewPhotos .review-photo-row').length,
            firma: Boolean(document.querySelector('#reviewFirma img')),
            contador: document.getElementById('reviewPhotoCount').textContent,
            texto: document.getElementById('reviewPhotos').innerText })""")
        r.comprobar("Revisión completa al entrar (7 campos, 3 fotos, firma)",
                    revision["campos"] == 7 and revision["fotos"] == 3 and revision["firma"] and revision["contador"] == "3",
                    str({k: v for k, v in revision.items() if k != "texto"}))
        r.comprobar("Texto del usuario escapado (sin HTML inyectado)",
                    pagina.evaluate("window.__xss === undefined") and "<img src=x" in revision["texto"])
        pagina.wait_for_timeout(400)
        pagina.screenshot(path=str(SALIDA / "fase5_revision.png"), full_page=True)

        # Volver a la fase 3, corregir y regresar: la revisión debe reflejarlo
        pagina.click("#btnBack")
        pagina.click("#btnBack")
        pagina.locator("textarea.comment-textarea").nth(1).fill("Comentario CORREGIDO foto 2")
        pagina.click("#btnNext")
        pagina.click("#btnNext")
        texto = pagina.evaluate("document.getElementById('reviewPhotos').innerText")
        r.comprobar("La revisión refleja los cambios hechos al volver atrás",
                    "CORREGIDO" in texto and "Comentario inicial" not in texto)

        # ── Fase 6: PDF ──
        pagina.click("#btnNext")
        with pagina.expect_download(timeout=30000) as descarga:
            pagina.click("button.btn-primary:has-text('Descargar')")
        ruta_pdf = SALIDA / "acta-prueba.pdf"
        descarga.value.save_as(str(ruta_pdf))
        _, imagenes = colocaciones_de_imagenes(ruta_pdf)
        texto_acta = texto_pdf(ruta_pdf)
        fotos_pdf, desvio = desviacion_maxima(imagenes)
        r.comprobar("Fotos del PDF sin deformar", len(fotos_pdf) == 3 and desvio < 0.01, f"desviación máx. {desvio:.2%}")
        r.comprobar("Comentario largo completo en el PDF", normalizar(COMENTARIO_LARGO) in texto_acta)
        r.comprobar("Descripción larga completa en el PDF", normalizar(DESCRIPCION_LARGA) in texto_acta)
        r.comprobar("Símbolos técnicos en el PDF (Ø ≥ ² ±)", all(s in texto_acta for s in ("Ø16", "≥ 25 N/mm²", "±2 °C")))
        r.comprobar("Hora y GPS de cada foto en el PDF", texto_acta.count("37.389210, -5.984460 (±8 m)") == 3)
        firma_pdf = [i for i in imagenes if i[4] == 750 and i[5] == 300]
        r.comprobar("Firma comprimida en el PDF", len(firma_pdf) == 1 and firma_pdf[0][7] < 60_000,
                    f"{firma_pdf[0][7] / 1024:.0f} KB" if firma_pdf else "no encontrada")
        tam_pdf = ruta_pdf.stat().st_size
        r.comprobar("Tamaño del PDF razonable (< 800 KB con 3 fotos)", tam_pdf < 800_000, f"{tam_pdf / 1024:.0f} KB")
        r.comprobar("El acta queda emitida al descargar el PDF", pagina.evaluate("state.acta.estado") == "emitida")

        r.comprobar("Sin peticiones a internet (todo local)", not externas, "; ".join(externas[:3]))
        r.comprobar("Sin errores JS", not errores, "; ".join(errores[:3]))
        contexto.close()

        # ── Fecha por defecto en hora local (a las 00:30 del 23/10, hora de Madrid) ──
        # En un contexto aparte: el reloj simulado afecta a todo el contexto.
        contexto_reloj = contexto_movil(p, navegador)
        pagina_reloj = contexto_reloj.new_page()
        pagina_reloj.clock.install(time="2026-10-23T00:30:00+02:00")
        pagina_reloj.goto(URL)
        pagina_reloj.wait_for_load_state("networkidle")
        pagina_reloj.wait_for_function("state.acta !== null")
        fecha = pagina_reloj.evaluate("[fechaVisita.value, horaVisita.value]")
        r.comprobar("Fecha por defecto local a las 00:30", fecha == ["2026-10-23", "00:30"], str(fecha))
        contexto_reloj.close()
        navegador.close()
    srv.shutdown()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
