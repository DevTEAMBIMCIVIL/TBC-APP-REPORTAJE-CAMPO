"""Pruebas del bloque C (contenido del acta) en un Pixel 7 emulado: numeración por expediente, asistentes,
observaciones e indicaciones, firmas de varios asistentes, revisiones (ISO 9001), fechas dd/mm/aaaa,
PDF con bloque de control en cada página y migración de actas guardadas con la v2.1.

Uso (desde la raíz del repo, con los mismos requisitos que e2e_acta.py):
    python tests/e2e_contenido.py
"""
import datetime
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from comun import (SALIDA, Resultados, abrir, abrir_mis_actas, avanzar_hasta, cerrar_aviso, colocaciones_de_imagenes,  # noqa: E402
                   contexto_movil, esperar_fotos, firmar, normalizar, servidor, texto_pdf, vigilar_red)
from generar_fotos import generar  # noqa: E402

EXP = "425_2026.CON"
OBSERVACIONES = ("Se revisan los forjados de planta primera. Se observa fisuración en la viga del eje 3 "
                 "(fotos 1 y 2). Resto de elementos sin incidencias aparentes.")
SECCIONES = ["1 · DATOS GENERALES", "2 · ASISTENTES", "3 · OBSERVACIONES GENERALES", "4 · INDICACIONES",
             "5 · REPORTAJE FOTOGRÁFICO (2)", "6 · FIRMAS", "7 · CONTROL DE REVISIONES"]


def descargar(pagina, ruta):
    with pagina.expect_download(timeout=60000) as descarga:
        pagina.click("button.btn-primary:has-text('Descargar')")
    descarga.value.save_as(str(ruta))
    return descarga.value.suggested_filename


def pasar_firmas_aceptando(pagina, mensajes):
    """Pulsa «Siguiente» en la fase de firmas aceptando el aviso de firmas pendientes."""
    def aceptar(dialogo):
        mensajes.append(dialogo.message)
        dialogo.accept()
    pagina.once("dialog", aceptar)
    pagina.click("#btnNext")


def main():
    r = Resultados()
    SALIDA.mkdir(parents=True, exist_ok=True)
    horizontal, vertical, _ = (str(f) for f in generar(SALIDA / "fotos"))
    hoy = datetime.date.today().strftime("%d/%m/%Y")
    srv = servidor()
    externas, errores = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pg = abrir(ctx, errores)
        cdp = ctx.new_cdp_session(pg)

        # ── C1 · Numeración automática por expediente ──
        pg.fill("#tecnico", "Blas González González")
        pg.fill("#expediente", EXP)
        pg.wait_for_function(f"state.acta.datos.actaNum === '{EXP}-AV-01'", timeout=5000)
        r.comprobar("Número automático al indicar el expediente",
                    pg.input_value("#actaNum") == f"{EXP}-AV-01" and "1.ª acta" in pg.text_content("#numAyuda"),
                    pg.text_content("#numAyuda"))
        pg.fill("#descripcion", "Inspección de cimentación y forjados")
        pg.click("#gpsBtn")
        pg.wait_for_selector("#gpsStatus.ok", timeout=15000)
        pg.click("#btnNext")
        r.comprobar("Fase 2: asistentes, con el técnico ya incluido",
                    pg.evaluate("state.fase") == 2 and pg.text_content("#tecnicoNombreAsist") == "Blas González González")

        # ── C2 · Asistentes ──
        pg.fill("#cargoTecnico", "Dirección facultativa")
        pg.click("button:has-text('Añadir asistente')")
        pg.click("#btnNext")
        r.comprobar("Asistente sin nombre: se avisa", "Falta un nombre" in (cerrar_aviso(pg) or ""))
        datos = [("Juan Pérez", "Constructora Sur", "Jefe de obra"), ("Marta Ruiz", "Propiedad", "Promotora"),
                 ("Luis Gómez", "CSS Ingeniería", "Coordinador de seguridad")]
        for i, (nombre, empresa, cargo) in enumerate(datos):
            if i:
                pg.click("button:has-text('Añadir asistente')")
            pg.fill(f"#asNombre{i}", nombre)
            pg.fill(f"#asEmpresa{i}", empresa)
            pg.fill(f"#asCargo{i}", cargo)
        pg.uncheck("[data-asistente='1'] input[data-campo='firma']")
        asistentes = pg.evaluate("state.acta.asistentes.map(a => [a.nombre, a.firma])")
        r.comprobar("Tres asistentes con su marca de firma",
                    asistentes == [["Juan Pérez", True], ["Marta Ruiz", False], ["Luis Gómez", True]], str(asistentes))
        pg.screenshot(path=str(SALIDA / "c-asistentes.png"), full_page=True)
        pg.click("#btnNext")
        pg.set_input_files("#photoInput", [horizontal, vertical])
        esperar_fotos(pg, 2)
        avanzar_hasta(pg, 5)

        # ── C3 · Observaciones e indicaciones ──
        pg.fill("#observaciones", OBSERVACIONES)
        pg.click("button:has-text('Añadir indicación')")
        pg.click("#btnNext")
        r.comprobar("Indicación vacía: se avisa", "Indicación vacía" in (cerrar_aviso(pg) or ""))
        pg.fill("#indTexto0", "Picado, pasivado de armaduras y reparación con mortero R4 en la viga del eje 3.")
        pg.fill("#indResp0", "Constructora Sur · Jefe de obra")
        pg.fill("#indPlazo0", "2026-11-05")
        pg.click("button:has-text('Añadir indicación')")
        pg.fill("#indTexto1", "Aportar el último ensayo de esclerometría.")
        pg.fill("#indResp1", "Propiedad · Promotora")
        opciones = pg.evaluate("Array.from(document.querySelectorAll('#responsablesLista option')).map(o => o.value)")
        r.comprobar("Responsables sugeridos: técnico y asistentes", opciones == [
            "TEAMBIMCIVIL · Dirección facultativa", "Constructora Sur · Jefe de obra", "Propiedad · Promotora",
            "CSS Ingeniería · Coordinador de seguridad"], str(opciones))
        pg.screenshot(path=str(SALIDA / "c-acuerdos.png"), full_page=True)
        pg.click("#btnNext")

        # ── C4 · Firmas de varios asistentes ──
        recuadros = pg.locator("#firmasAsistentes canvas.firma-lienzo").count()
        sin_firma = pg.locator("#firmasAsistentes .no-firma-card").count()
        r.comprobar("Un recuadro por asistente que firma y «No firma» para el resto", recuadros == 2 and sin_firma == 1,
                    f"{recuadros} recuadros, {sin_firma} sin firma")
        pg.click("#btnNext")
        r.comprobar("La firma del técnico es obligatoria", "Firma requerida" in (cerrar_aviso(pg) or ""))
        firmar(cdp, pg)
        firmar(cdp, pg, lienzo=pg.locator("#firmasAsistentes .firma-asistente").nth(0).locator("canvas"))
        r.comprobar("La firma del asistente se dibuja en su recuadro",
                    pg.evaluate("state.acta.firmasAsistentes[state.acta.asistentes[0].id].trazos.length") > 0)
        pg.screenshot(path=str(SALIDA / "c-firmas.png"), full_page=True)
        mensajes = []
        pasar_firmas_aceptando(pg, mensajes)
        luis_no_firma = pg.evaluate("state.acta.firmasAsistentes[state.acta.asistentes[2].id].noFirma")
        r.comprobar("Si falta la firma de un asistente, se pregunta y consta «No firma»",
                    mensajes and "Luis Gómez" in mensajes[0] and pg.evaluate("state.fase") == 7 and luis_no_firma,
                    mensajes[0].replace("\n", " ") if mensajes else "sin aviso")

        # ── Revisión (fase 7) ──
        revision = pg.evaluate("""({ personas: document.getElementById('reviewAsistCount').textContent,
            acuerdos: document.getElementById('reviewAcuerdos').innerText,
            firmas: document.querySelectorAll('#reviewFirma img').length,
            sinFirma: document.querySelectorAll('#reviewFirma .review-sin-firma').length,
            general: document.getElementById('reviewGeneral').innerText })""")
        r.comprobar("Revisión: 4 personas, acuerdos, 2 firmas y 2 «No firma»",
                    revision["personas"] == "4" and "Picado" in revision["acuerdos"] and "05/11/2026" in revision["acuerdos"]
                    and revision["firmas"] == 2 and revision["sinFirma"] == 2,
                    str({k: v for k, v in revision.items() if k in ("personas", "firmas", "sinFirma")}))
        r.comprobar("Fechas dd/mm/aaaa en la revisión", hoy in revision["general"])
        pg.screenshot(path=str(SALIDA / "c-revision.png"), full_page=True)
        pg.click("#btnNext")

        # ── PDF de la Rev. 0 ──
        ruta0 = SALIDA / "acta-contenido-rev0.pdf"
        descargar(pg, ruta0)
        texto = texto_pdf(ruta0)
        lector, imagenes = colocaciones_de_imagenes(ruta0)
        paginas = len(lector.pages)
        r.comprobar("PDF: las 7 secciones numeradas", all(s in texto for s in SECCIONES),
                    ", ".join(s for s in SECCIONES if s not in texto))
        r.comprobar("PDF: bloque de control (nº, revisión y pág. X de N) en cada página",
                    texto.count(f"Nº {EXP}-AV-01 · Rev. 0") == paginas
                    and all(f"Pág. {i} de {paginas}" in texto for i in range(1, paginas + 1)), f"{paginas} páginas")
        r.comprobar("PDF: asistentes, observaciones e indicaciones",
                    all(s in texto for s in ("Juan Pérez", "Constructora Sur", "Marta Ruiz", normalizar(OBSERVACIONES),
                                             "Aportar el último ensayo de esclerometría.", "05/11/2026")))
        firmas_pdf = [i for i in imagenes if (i[4], i[5]) == (750, 300)]
        r.comprobar("PDF: firmas del técnico y de Juan; «NO FIRMA» para Marta y Luis",
                    len(firmas_pdf) == 2 and texto.count("NO FIRMA") == 2, f"{len(firmas_pdf)} firmas")
        r.comprobar("PDF: fechas dd/mm/aaaa (ninguna en formato ISO)",
                    hoy in texto and not re.search(r"\b20\d\d-\d\d-\d\d\b", texto))
        r.comprobar("PDF: control de revisiones con la emisión inicial", "Emisión inicial" in texto)

        # ── C1 · Siguiente acta del expediente y número a mano ──
        abrir_mis_actas(pg)
        pg.click(".acta-card.actual button:has-text('Nueva visita')")
        pg.wait_for_function(f"state.acta.datos.actaNum === '{EXP}-AV-02'", timeout=5000)
        visita = pg.evaluate("""({ asistentes: state.acta.asistentes.length, cargo: state.acta.datos.cargoTecnico,
            firmas: Object.keys(state.acta.firmasAsistentes).length })""")
        r.comprobar("«Nueva visita»: número AV-02, mismos asistentes y cargo, sin firmas",
                    visita == {"asistentes": 3, "cargo": "Dirección facultativa", "firmas": 0}, str(visita))
        pg.fill("#actaNum", "ESPECIAL-7")
        r.comprobar("Número escrito a mano: deja de ser automático",
                    pg.evaluate("state.acta.datos.numAuto") is False and "a mano" in pg.text_content("#numAyuda"))
        pg.fill("#actaNum", "")
        pg.wait_for_function(f"state.acta.datos.actaNum === '{EXP}-AV-02'", timeout=5000)
        r.comprobar("Al borrar el número vuelve el automático", pg.evaluate("state.acta.datos.numAuto") is True)

        # ── C2 · Sugerencias de asistentes de visitas anteriores ──
        abrir_mis_actas(pg)
        pg.click("#panelActas button:has-text('Nueva acta')")
        pg.wait_for_selector("#panelActas", state="hidden")            # la nueva acta ya está en pantalla
        pg.wait_for_function("state.persistida === false && state.acta.datos.expediente === ''")
        pg.fill("#tecnico", "Blas González González")
        pg.fill("#expediente", EXP)
        pg.wait_for_function(f"state.acta.datos.actaNum === '{EXP}-AV-03'", timeout=5000)
        pg.click("#gpsBtn")
        pg.wait_for_selector("#gpsStatus.ok", timeout=15000)
        pg.click("#btnNext")
        pg.wait_for_selector("#asistentesSugeridos:not(.hidden)", timeout=5000)
        chips = pg.locator("#asistentesSugeridos button").count()
        pg.click("#asistentesSugeridos button:has-text('Juan Pérez')")
        pg.wait_for_timeout(300)
        r.comprobar("Sugerencias de visitas anteriores del mismo expediente",
                    chips == 3 and pg.evaluate("state.acta.asistentes[0].nombre") == "Juan Pérez"
                    and pg.locator("#asistentesSugeridos button").count() == 2, f"{chips} sugerencias")

        # ── C5 · Revisiones: «Corregir» crea la Rev. 1 del mismo número ──
        abrir_mis_actas(pg)
        tarjeta = pg.locator(".acta-card", has_text=f"{EXP}-AV-01").first
        tarjeta.locator("button:has-text('Corregir')").click()
        pg.wait_for_selector("#promptOverlay.open")
        pg.click("#promptAceptar")
        r.comprobar("La revisión exige un motivo", "Motivo requerido" in (cerrar_aviso(pg) or ""))
        tarjeta.locator("button:has-text('Corregir')").click()
        pg.wait_for_selector("#promptOverlay.open")
        pg.fill("#promptTexto", "Corrección del plazo de la indicación 1")
        pg.click("#promptAceptar")
        pg.wait_for_selector("#alertOverlay.open", timeout=10000)
        cerrar_aviso(pg)
        rev1 = pg.evaluate("""({ num: state.acta.datos.actaNum, rev: state.acta.revision, firma: state.acta.firma.length,
            firmasAsistentes: Object.keys(state.acta.firmasAsistentes).length, asistentes: state.acta.asistentes.length,
            indicaciones: state.acta.indicaciones.length, fijo: document.getElementById('actaNum').readOnly,
            motivos: state.acta.revisiones.map(x => x.motivo), cabecera: document.getElementById('headerActaNum').textContent })""")
        r.comprobar("«Corregir»: Rev. 1 con el mismo número, todo copiado y sin firmas", rev1 == {
            "num": f"{EXP}-AV-01", "rev": 1, "firma": 0, "firmasAsistentes": 0, "asistentes": 3, "indicaciones": 2,
            "fijo": True, "motivos": ["Emisión inicial", "Corrección del plazo de la indicación 1"],
            "cabecera": f"{EXP}-AV-01 · Rev. 1"}, str(rev1))
        id_original = pg.evaluate("state.acta.corrigeA")
        avanzar_hasta(pg, 5)
        pg.fill("#indPlazo0", "2026-11-12")
        pg.click("#btnNext")
        firmar(cdp, pg)
        mensajes = []
        pasar_firmas_aceptando(pg, mensajes)
        pg.click("#btnNext")
        ruta1 = SALIDA / "acta-contenido-rev1.pdf"
        archivo = descargar(pg, ruta1)
        texto1 = texto_pdf(ruta1)
        r.comprobar("PDF de la Rev. 1: número, revisión, historial y plazo corregido",
                    f"Nº {EXP}-AV-01 · Rev. 1" in texto1 and "Corrección del plazo de la indicación 1" in texto1
                    and "Emisión inicial" in texto1 and "12/11/2026" in texto1 and "05/11/2026" not in texto1)
        r.comprobar("El nombre del archivo indica la revisión", "_Rev1_" in archivo, archivo)
        abrir_mis_actas(pg)
        original = pg.locator(f".acta-card[data-acta='{id_original}']")
        r.comprobar("La Rev. 0 queda «Sustituida» y ya no se puede corregir",
                    "Sustituida (Rev. 1)" in original.text_content() and original.locator("button:has-text('Corregir')").count() == 0)
        pg.screenshot(path=str(SALIDA / "c-mis-actas.png"))
        pg.click(".panel-close")
        ctx.close()

        # ── Migración de actas guardadas con la v2.1 ──
        ctx = contexto_movil(p, navegador)
        pg = abrir(ctx, errores)
        pg.evaluate("""async () => {
            const base = { esquema: 1, creada: '2026-10-20T08:00:00.000Z', modificada: '2026-10-20T09:00:00.000Z',
              datos: { actaNum: 'V21-001', tecnico: 'Blas González González', expediente: 'EXP-V21',
                       descripcion: 'Acta guardada con la v2.1', fecha: '2026-10-20', hora: '09:00' },
              gps: { lat: '37.389210', lng: '-5.984460', acc: 8, hora: '2026-10-20T09:01:00.000Z' },
              sinGps: { activo: false, referencia: '', lat: '', lng: '' }, fotos: [], firma: [] };
            await Almacen.guardarActa({ ...base, id: 'acta-v21-borrador', estado: 'borrador', emitida: null, fase: 2 });
            await Almacen.guardarActa({ ...base, id: 'acta-v21-emitida', estado: 'emitida',
                                        emitida: '2026-10-20T10:00:00.000Z', fase: 6 });
            localStorage.setItem('tbc-acta-actual', 'acta-v21-borrador');
        }""")
        pg.reload()
        pg.wait_for_function("state.acta && state.acta.id === 'acta-v21-borrador'")
        migrada = pg.evaluate("""({ fase: state.fase, esquema: state.acta.esquema, rev: state.acta.revision,
            asistentes: state.acta.asistentes.length, auto: state.acta.datos.numAuto, revisiones: state.acta.revisiones.length })""")
        r.comprobar("Un borrador de la v2.1 se abre migrado y en la fase equivalente (fotos)", migrada == {
            "fase": 3, "esquema": 2, "rev": 0, "asistentes": 0, "auto": False, "revisiones": 1}, str(migrada))
        pg.evaluate("abrirActaGuardada('acta-v21-emitida')")
        pg.wait_for_function("state.acta.id === 'acta-v21-emitida' && state.fase === 8")
        ruta_v21 = SALIDA / "acta-v21-migrada.pdf"
        descargar(pg, ruta_v21)
        texto_v21 = texto_pdf(ruta_v21)
        r.comprobar("Un acta emitida con la v2.1 se abre en solo lectura y vuelve a generar su PDF",
                    "Nº V21-001 · Rev. 0" in texto_v21 and "Emitida 20/10/2026" in texto_v21
                    and pg.evaluate("state.acta.estado") == "emitida")
        ctx.close()

        r.comprobar("Sin peticiones a internet", not externas, "; ".join(externas[:3]))
        r.comprobar("Sin errores JS", not errores, "; ".join(errores[:3]))
        navegador.close()
    srv.shutdown()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
