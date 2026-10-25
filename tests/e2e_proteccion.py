"""Pruebas de la v3.1.2 (protección de las actas) en un Pixel 7 emulado: la app abierta en dos ventanas del mismo
navegador (la atrasada no pisa lo que guarda la otra: emitida, cambiada o borrada; aviso de app abierta dos veces;
puesta al día al volver a la ventana; una Rev. emitida en el mismo milisegundo de su último guardado; quitar una foto
en la ventana atrasada; emitir un acta borrada en otra ventana; compartir el PDF mientras otra ventana la cambia;
fotos que se procesan mientras otra ventana guarda; importación que llega tarde; sin espacio para las fotos al
emitir; menú de compartir que no se cierra; PDF rehecho con el acta cambiada), copia de seguridad el mismo día en que
se emiten actas (también con la copia hecha con el PDF ya preparado y con el reloj adelantado), aviso de navegador
(Samsung Internet, Mi Browser, Brave, iPhone) y recuento en Mis actas, e importación de un PDF o de un .zip de PDF.

Uso (desde la raíz del repo, con los mismos requisitos que e2e_seguimiento.py):
    python tests/e2e_proteccion.py
"""
import contextlib
import datetime
import pathlib
import sys
import zipfile

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from comun import (SALIDA, Resultados, abrir, abrir_mis_actas, avanzar_hasta, cerrar_aviso, contexto_movil,  # noqa: E402
                   esperar_fotos, firmar, identificar, servidor, vigilar_red)
from comun import escribir_expediente  # noqa: E402
from generar_fotos import generar  # noqa: E402

UA_SAMSUNG = ("Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) "
              "SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36")
UA_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.5 Mobile/15E148 Safari/604.1")
UA_MI = ("Mozilla/5.0 (Linux; U; Android 13; es-es; 2201117TY Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Version/4.0 Chrome/112.0.5615.136 Mobile Safari/537.36 XiaoMi/MiuiBrowser/14.4.0-gn")
ESTADO = "id => Almacen.leerActa(id).then(a => a ? [a.estado, a.fotos.length, a.firma.length > 0, a.datos.expediente] : null)"
IMAGENES = "id => Almacen.fotosDeActa(id).then(f => f.length)"
MODIFICADA = "id => Almacen.leerActa(id).then(a => a && a.modificada)"


def descargar(pg, selector, ruta):
    with pg.expect_download(timeout=60000) as d:
        pg.click(selector)
    d.value.save_as(str(ruta))
    return d.value.suggested_filename


def esperar_aviso(pg, timeout=10000):
    pg.wait_for_selector("#alertOverlay.open", timeout=timeout)
    return cerrar_aviso(pg) or ""


def segunda_ventana(ctx, errores, pa, acta_id):
    """Abre la app otra vez en el mismo navegador (p. ej. el icono instalado): carga el acta en curso."""
    pb = abrir(ctx, errores)
    pb.wait_for_function(f"state.acta && state.acta.id === '{acta_id}'")
    pb.wait_for_timeout(400)
    return pb, cerrar_aviso(pb) or "", cerrar_aviso(pa) or ""


@contextlib.contextmanager
def seccion(r, nombre, abiertos):
    """Un caso que, si se queda a medias (p. ej. una espera que no se cumple), cuenta como fallo y deja seguir."""
    try:
        yield
    except Exception as e:  # noqa: BLE001
        r.comprobar(nombre, False, f"{type(e).__name__}: {str(e).splitlines()[0][:160]}")
    finally:
        for ctx in abiertos:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
        abiertos.clear()


def esperar_pdf(pg):
    pg.wait_for_function("document.getElementById('emitPdfEstado').textContent.startsWith('PDF listo')", timeout=60000)


def hasta_emision(pg, cdp, foto):
    """Desde la identificación ya rellena: GPS, una foto, firma y hasta Emisión, con el PDF preparado (sin emitir)."""
    pg.click("#gpsBtn")
    pg.wait_for_selector("#gpsStatus.ok", timeout=15000)
    pg.click("#btnNext")                           # asistentes
    pg.click("#btnNext")                           # fotos
    pg.set_input_files("#photoInput", [foto])
    esperar_fotos(pg, 1)
    pg.click("#btnNext")                           # notas
    pg.click("#btnNext")                           # acuerdos
    pg.click("#btnNext")                           # firmas
    firmar(cdp, pg)
    pg.click("#btnNext")                           # revisión
    pg.click("#btnNext")                           # emisión
    esperar_pdf(pg)
    pg.wait_for_function("!state.pendiente", timeout=5000)


def emitir(pg, cdp, foto, salida):
    """Desde la identificación ya rellena: GPS, una foto, firma y emisión (descargando el PDF)."""
    hasta_emision(pg, cdp, foto)
    descargar(pg, "#btnDescargar", salida)
    pg.wait_for_function("state.acta.estado === 'emitida'")


def nueva_en_ventana(ctx, errores, numero, expediente):
    pa = abrir(ctx, errores)
    identificar(pa, expediente=expediente, acta=numero)
    pa.wait_for_function(f"state.persistida && state.acta.datos.actaNum === '{numero}'")
    pa.evaluate("guardarYa()")
    return pa, pa.evaluate("state.acta.id")


def main():
    r = Resultados()
    SALIDA.mkdir(parents=True, exist_ok=True)
    horizontal, vertical, _ = (str(f) for f in generar(SALIDA / "fotos"))
    srv = servidor()
    externas, errores, abiertos = [], [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()

        # ══ 1 · Dos ventanas con aviso entre ellas: la otra se pone al día y no pisa al ocultarse ══
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pa, acta_id = nueva_en_ventana(ctx, errores, "7", "EXP-DV")
        pb, aviso_b, aviso_a = segunda_ventana(ctx, errores, pa, acta_id)
        r.comprobar("Dos ventanas: las dos avisan de que la app está abierta dos veces",
                    "abierta dos veces" in aviso_b and "abierta dos veces" in aviso_a, f"{aviso_b[:40]} | {aviso_a[:40]}")
        emitir(pb, ctx.new_cdp_session(pb), horizontal, SALIDA / "P-7.pdf")
        cerrar_aviso(pb)
        aviso = esperar_aviso(pa)
        r.comprobar("La otra ventana se pone al día sola: muestra el acta emitida y lo avisa",
                    "emitido en otra ventana" in aviso and pa.evaluate("[state.acta.estado, state.fase]") == ["emitida", 8], aviso)
        pa.evaluate("window.dispatchEvent(new Event('pagehide'))")
        pa.wait_for_timeout(700)
        r.comprobar("Al ocultarse, la ventana atrasada no pisa el acta emitida (antes volvía a borrador sin fotos ni firma)",
                    pb.evaluate(ESTADO, acta_id) == ["emitida", 1, True, "EXP-DV"], str(pb.evaluate(ESTADO, acta_id)))
        ctx.close()

        # ══ 2 · Sin aviso entre ventanas (canal cortado): no escribe sin cambios; con cambios, no pisa la emitida ══
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pa, acta_id = nueva_en_ventana(ctx, errores, "8", "EXP-SC")
        pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
        pa.evaluate("canalVentanas.onmessage = null")
        emitir(pb, ctx.new_cdp_session(pb), horizontal, SALIDA / "P-8.pdf")
        cerrar_aviso(pb)
        pa.evaluate("window.dispatchEvent(new Event('pagehide'))")
        pa.wait_for_timeout(700)
        r.comprobar("Sin aviso de la otra ventana: al ocultarse sin cambios pendientes no escribe nada",
                    pb.evaluate(ESTADO, acta_id) == ["emitida", 1, True, "EXP-SC"] and pa.evaluate("state.acta.estado") == "borrador")
        escribir_expediente(pa, "EXP-SC-PISA")
        aviso = esperar_aviso(pa)
        r.comprobar("…y si escribe en la copia atrasada, no pisa la emitida: muestra esa versión y lo explica",
                    "ya se había emitido en otra ventana" in aviso and pa.evaluate("state.acta.estado") == "emitida"
                    and pb.evaluate(ESTADO, acta_id) == ["emitida", 1, True, "EXP-SC"], aviso)
        ctx.close()

        # ══ 3 · Borrador cambiado en otra ventana; al volver a la ventana; borrada en otra ventana ══
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pa, acta_id = nueva_en_ventana(ctx, errores, "9", "EXP-BC")
        pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
        pa.evaluate("canalVentanas.onmessage = null")
        escribir_expediente(pb, "EXP-BC-B")
        pb.wait_for_function("!state.pendiente && state.acta.datos.expediente === 'EXP-BC-B'", timeout=5000)
        pa.fill("#descripcion", "Detalle escrito en la ventana atrasada")
        aviso = esperar_aviso(pa)
        r.comprobar("Borrador cambiado en otra ventana: no se pisa; se muestra la versión guardada y se explica",
                    "cambiada en otra ventana" in aviso and pa.evaluate("state.acta.datos.expediente") == "EXP-BC-B"
                    and pb.evaluate(ESTADO, acta_id)[3] == "EXP-BC-B", aviso)
        escribir_expediente(pb, "EXP-BC-C")
        pb.wait_for_function("!state.pendiente && state.acta.datos.expediente === 'EXP-BC-C'", timeout=5000)
        pa.evaluate("document.dispatchEvent(new Event('visibilitychange'))")     # vuelve a primer plano
        pa.wait_for_function("state.acta.datos.expediente === 'EXP-BC-C'", timeout=5000)
        r.comprobar("Al volver a la ventana, se pone al día sola (sin aviso si es un borrador)",
                    pa.evaluate("document.getElementById('expediente').value") == "EXP-BC-C"
                    and not pa.evaluate("document.getElementById('alertOverlay').classList.contains('open')"))
        pa.evaluate("() => { canalVentanas.onmessage = e => alMensajeVentana(e.data); }")
        pb.once("dialog", lambda d: d.accept())
        pb.evaluate(f"borrarActaGuardada('{acta_id}')")
        aviso = esperar_aviso(pa)
        r.comprobar("Borrada en otra ventana: la ventana lo avisa y abre un acta nueva (no la resucita)",
                    "borrado en otra ventana" in aviso and pa.evaluate("state.acta.id") != acta_id
                    and pb.evaluate(ESTADO, acta_id) is None, aviso)
        ctx.close()

        # ══ 4 · Copia de seguridad el mismo día en que se emiten actas ══
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pg, _ = nueva_en_ventana(ctx, errores, "10", "EXP-COPIA")
        emitir(pg, ctx.new_cdp_session(pg), horizontal, SALIDA / "P-10.pdf")
        cerrar_aviso(pg)
        pg.wait_for_function("!document.getElementById('emitCopia').classList.contains('hidden')", timeout=5000)
        r.comprobar("Al emitir sin copia: tarjeta «Hacer copia ahora» en Emisión y punto rojo en 📂, el mismo día",
                    "Hay 1 acta emitida sin copia de seguridad" in pg.text_content("#emitCopiaEstado")
                    and pg.evaluate("document.querySelector('.header-btn').classList.contains('pendiente')"),
                    pg.text_content("#emitCopiaEstado"))
        abrir_mis_actas(pg)
        estado = pg.text_content("#copiaEstado")
        r.comprobar("Mis actas: «⚠️ 1 acta emitida sin copia de seguridad»", estado.startswith("⚠️ 1 acta emitida sin copia de seguridad"), estado)
        pg.evaluate("cerrarMisActas()")
        descargar(pg, "#btnCopiaEmision", SALIDA / "P-copia.zip")
        aviso = esperar_aviso(pg)
        pg.evaluate("cerrarMisActas()")
        r.comprobar("Tras la copia: sin tarjeta en Emisión, sin punto rojo y Mis actas «Al día»",
                    "Copia guardada" in aviso and pg.evaluate("document.getElementById('emitCopia').classList.contains('hidden')")
                    and not pg.evaluate("document.querySelector('.header-btn').classList.contains('pendiente')")
                    and pg.text_content("#copiaEstado").startswith("✓ Al día"), aviso)
        pg.evaluate("nuevaActa()")
        identificar(pg, expediente="EXP-COPIA", acta="11")
        pg.wait_for_function("state.persistida && !state.pendiente", timeout=5000)
        pg.evaluate("actualizarAvisoCopia()")
        abrir_mis_actas(pg)
        estado = pg.text_content("#copiaEstado")
        r.comprobar("Con solo un borrador cambiado no avisa el mismo día (sigue el aviso a los 7 días)",
                    "1 acta(s) con cambios" in estado and not estado.startswith("⚠️")
                    and not pg.evaluate("document.querySelector('.header-btn').classList.contains('pendiente')"), estado)

        # ══ 5 · Navegador: recuento en Mis actas y avisos ══
        r.comprobar("Mis actas: cuántas actas hay guardadas en este navegador y cuál es",
                    pg.text_content("#panelNota").startswith("2 actas guardadas en este navegador (Chrome)"), pg.text_content("#panelNota"))
        r.comprobar("En Chrome no hay aviso de navegador al abrir", "Estás usando" not in (cerrar_aviso(pg) or ""))
        pg.evaluate("cerrarMisActas()")

        # ══ 6 · Importar un PDF o un .zip de PDF ══
        r.comprobar("Importar admite elegir un PDF", ".pdf" in pg.get_attribute("#importInput", "accept"))
        pg.set_input_files("#importInput", str(SALIDA / "P-10.pdf"))
        aviso = esperar_aviso(pg)
        r.comprobar("Un PDF: «Un PDF no se puede importar», con cómo pasar el acta (Hacer copia o Exportar)",
                    aviso.startswith("Un PDF no se puede importar") and "Hacer copia" in aviso and "Exportar" in aviso, aviso)
        with zipfile.ZipFile(SALIDA / "P-pdfs.zip", "w") as z:          # comprimido en un Mac: con sus copias ocultas
            z.write(SALIDA / "P-10.pdf", "Acta_10_2026-10-23.pdf")
            z.write(SALIDA / "P-10.pdf", "Acta_10_2026-10-23(1).pdf")
            z.writestr("__MACOSX/._Acta_10_2026-10-23.pdf", b"\x00\x05\x16\x07")
            z.writestr("__MACOSX/._Acta_10_2026-10-23(1).pdf", b"\x00\x05\x16\x07")
        pg.set_input_files("#importInput", str(SALIDA / "P-pdfs.zip"))
        aviso = esperar_aviso(pg)
        r.comprobar("Un .zip de PDF: explica que contiene PDF y no una copia de la app (sin contar las copias ocultas del Mac)",
                    "Este .zip contiene 2 PDF de actas, no una copia de la app" in aviso and "Hacer copia" in aviso, aviso)
        ctx.close()

        # ══ 7 · Samsung Internet e iPhone ══
        ctx = contexto_movil(p, navegador, user_agent=UA_SAMSUNG)
        vigilar_red(ctx, externas)
        pg = abrir(ctx, errores)
        pg.wait_for_timeout(300)
        aviso = cerrar_aviso(pg) or ""
        pg.reload()
        pg.wait_for_function("state.acta !== null")
        pg.wait_for_timeout(300)
        otra_vez = cerrar_aviso(pg)
        abrir_mis_actas(pg)
        r.comprobar("Samsung Internet: avisa de que cada navegador guarda sus actas (una vez por sesión)",
                    aviso.startswith("Estás usando Samsung Internet") and "Chrome" in aviso and otra_vez is None
                    and "(Samsung Internet)" in pg.text_content("#panelNota"), aviso)
        ctx.close()
        ctx = contexto_movil(p, navegador, user_agent=UA_IPHONE)
        vigilar_red(ctx, externas)
        pg = abrir(ctx, errores)
        pg.wait_for_timeout(300)
        aviso = cerrar_aviso(pg) or ""
        pg.reload()
        pg.wait_for_function("state.acta !== null")
        pg.wait_for_timeout(300)
        r.comprobar("iPhone: avisa una vez de que Safari y el icono guardan las actas por separado",
                    "Safari y el icono" in aviso and cerrar_aviso(pg) is None, aviso)
        ctx.close()
        avisos = []
        for opciones in ({"user_agent": UA_MI}, {"marcas": ("Brave", "Chromium", "Not_A Brand")}):
            ctx = contexto_movil(p, navegador, **opciones)    # Brave: el mismo agente de usuario que Chrome
            vigilar_red(ctx, externas)
            pg = abrir(ctx, errores)
            pg.wait_for_timeout(300)
            avisos.append(cerrar_aviso(pg) or "")
            abrir_mis_actas(pg)
            avisos.append(pg.text_content("#panelNota"))
            ctx.close()
        r.comprobar("Mi Browser y Brave (aunque se presente como Chrome) también avisan y se nombran en Mis actas",
                    avisos[0].startswith("Estás usando Mi Browser") and "(Mi Browser)" in avisos[1]
                    and avisos[2].startswith("Estás usando Brave") and "(Brave)" in avisos[3], " | ".join(a[:40] for a in avisos))

        # ══ 8 · Rev. 1 emitida en el mismo milisegundo de su último guardado (antes, la otra ventana no lo notaba
        #       y, al tocar «Atrás», la devolvía a borrador) ══
        with seccion(r, "Rev. 1 emitida en el mismo milisegundo de su último guardado", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, id0 = nueva_en_ventana(ctx, errores, "12", "EXP-REV")
            cdp = ctx.new_cdp_session(pa)
            emitir(pa, cdp, horizontal, SALIDA / "P-12.pdf")
            cerrar_aviso(pa)
            pa.click("#btnCorregir")
            pa.wait_for_selector("#promptOverlay.open", timeout=10000)
            pa.fill("#promptTexto", "Corrección de la hora de la visita")
            pa.click("#promptAceptar")
            pa.wait_for_selector("#alertOverlay.open", timeout=10000)   # «Rev. 1 creada»
            cerrar_aviso(pa)
            id1 = pa.evaluate("state.acta.id")
            pb, _, _ = segunda_ventana(ctx, errores, pa, id1)
            pc, _, _ = segunda_ventana(ctx, errores, pa, id1)
            pc.evaluate("canalVentanas.onmessage = null")              # una tercera ventana que no se entera de nada
            cerrar_aviso(pb)
            avanzar_hasta(pa, 6)
            firmar(cdp, pa)
            avanzar_hasta(pa, 7)
            pa.clock.set_fixed_time(datetime.datetime.now())          # todo en el mismo milisegundo, como en un móvil rápido
            pa.click("#btnNext")                                        # Emisión: guarda el borrador y prepara el PDF
            esperar_pdf(pa)
            pa.wait_for_function("!state.pendiente", timeout=5000)
            borrador = pa.evaluate(MODIFICADA, id1)
            pb.wait_for_function(f"state.acta.fase === 8 && state.base === '{borrador}'", timeout=5000)
            misma_hora = pa.evaluate("pdfEmision.listo.emision === state.acta.modificada")
            descargar(pa, "#btnDescargar", SALIDA / "P-12-rev1.pdf")
            pa.wait_for_function("state.acta.estado === 'emitida'")
            cerrar_aviso(pa)
            pb.wait_for_function("state.acta.estado === 'emitida'", timeout=5000)
            aviso = esperar_aviso(pb)
            r.comprobar("Rev. 1 emitida en el mismo milisegundo de su último guardado: cambia de versión y la otra ventana la muestra emitida",
                        misma_hora and pa.evaluate(MODIFICADA, id1) != borrador and "emitido en otra ventana" in aviso,
                        f"misma hora: {misma_hora} · {aviso[:50]}")
            pc.evaluate(f"Almacen.leerActa('{id1}').then(a => {{ state.base = a.modificada; }})")   # cree tener la última
            pc.fill("#descripcion", "Escrito en la ventana que no se ha enterado")
            aviso = esperar_aviso(pc)
            r.comprobar("Una ventana que cree tener la última versión tampoco pisa el acta emitida (Rev. 0 sigue sustituida)",
                        "ya se había emitido en otra ventana" in aviso and pc.evaluate("state.acta.estado") == "emitida"
                        and pa.evaluate(ESTADO, id1)[:3] == ["emitida", 1, True]
                        and pa.evaluate(f"Almacen.leerActa('{id0}').then(a => a.sustituidaPor)") == id1, aviso)

        # ══ 9 · Quitar una foto en la ventana atrasada no borra la imagen del acta emitida en la otra ══
        with seccion(r, "Quitar una foto en la ventana atrasada", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, acta_id = nueva_en_ventana(ctx, errores, "13", "EXP-FOTO")
            pa.click("#gpsBtn")
            pa.wait_for_selector("#gpsStatus.ok", timeout=15000)
            avanzar_hasta(pa, 3)
            pa.set_input_files("#photoInput", [horizontal, vertical])
            esperar_fotos(pa, 2)
            pa.wait_for_function("!state.pendiente", timeout=5000)
            pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
            pa.evaluate("canalVentanas.onmessage = null")
            cdp = ctx.new_cdp_session(pb)
            avanzar_hasta(pb, 6)
            firmar(cdp, pb)
            avanzar_hasta(pb, 8)
            esperar_pdf(pb)
            descargar(pb, "#btnDescargar", SALIDA / "P-13.pdf")
            pb.wait_for_function("state.acta.estado === 'emitida'")
            cerrar_aviso(pb)
            pa.locator("#photosGrid .remove-btn").nth(1).click()        # la ventana atrasada quita la foto 2
            aviso = esperar_aviso(pa)
            r.comprobar("Quitar una foto en la ventana atrasada: la emitida no se pisa y conserva sus 2 fotos (registro e imágenes)",
                        "ya se había emitido en otra ventana" in aviso and pa.evaluate(ESTADO, acta_id) == ["emitida", 2, True, "EXP-FOTO"]
                        and pa.evaluate(IMAGENES, acta_id) == 2 and pa.evaluate("state.acta.fotos.length") == 2, aviso)

        # ══ 10 · Emitir un acta que otra ventana ha borrado: el PDF ya se ha distribuido, así que se guarda emitida ══
        with seccion(r, "Emitir un acta borrada en otra ventana", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, acta_id = nueva_en_ventana(ctx, errores, "14", "EXP-BORRADA")
            hasta_emision(pa, ctx.new_cdp_session(pa), horizontal)
            pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
            pa.evaluate("canalVentanas.onmessage = null")
            pb.once("dialog", lambda d: d.accept())
            pb.evaluate(f"borrarActaGuardada('{acta_id}')")
            pb.wait_for_function(f"Almacen.leerActa('{acta_id}').then(a => !a)", timeout=5000)
            descargar(pa, "#btnDescargar", SALIDA / "P-14.pdf")
            pa.wait_for_function("state.acta.estado === 'emitida'")
            pa.wait_for_timeout(400)
            aviso = cerrar_aviso(pa) or ""
            r.comprobar("Emitir un acta borrada en otra ventana: queda guardada emitida, con su foto y su firma",
                        pa.evaluate(ESTADO, acta_id) == ["emitida", 1, True, "EXP-BORRADA"] and pa.evaluate(IMAGENES, acta_id) == 1
                        and pa.evaluate("state.acta.id") == acta_id and "borrado" not in aviso, aviso)

        # ══ 11 · Mientras se comparte el PDF, otra ventana cambia el acta: queda emitida la del PDF compartido ══
        with seccion(r, "Compartir mientras otra ventana cambia el acta", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, acta_id = nueva_en_ventana(ctx, errores, "15", "EXP-COMPARTIR")
            hasta_emision(pa, ctx.new_cdp_session(pa), horizontal)
            pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
            pa.evaluate("""() => { navigator.canShare = () => true;
                navigator.share = () => { window.menuAbierto = true; return new Promise(r => setTimeout(r, 1500)); }; }""")
            pa.evaluate("() => { compartirPDF(); }")                     # menú del teléfono abierto 1,5 s
            pa.wait_for_function("window.menuAbierto === true", timeout=5000)
            pb.evaluate("irAFase(1)")
            escribir_expediente(pb, "EXP-COMPARTIR-B")
            pb.wait_for_function("!state.pendiente && state.acta.datos.expediente === 'EXP-COMPARTIR-B'", timeout=5000)
            pa.wait_for_function("state.acta.estado === 'emitida'", timeout=10000)
            pb.wait_for_function("state.acta.estado === 'emitida'", timeout=5000)
            aviso = esperar_aviso(pb)
            r.comprobar("Compartir mientras otra ventana cambia el acta: se guarda emitida la del PDF y la otra ventana la muestra",
                        pa.evaluate(ESTADO, acta_id) == ["emitida", 1, True, "EXP-COMPARTIR"]
                        and pb.evaluate("state.acta.datos.expediente") == "EXP-COMPARTIR" and "emitido en otra ventana" in aviso, aviso)

        # ══ 12 · Copia hecha con el PDF ya preparado y emisión después ══
        with seccion(r, "Copia hecha con el PDF ya preparado e importación que llega tarde", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pg, acta_id = nueva_en_ventana(ctx, errores, "16", "EXP-COPIA2")
            hasta_emision(pg, ctx.new_cdp_session(pg), horizontal)
            with pg.expect_download(timeout=60000):
                pg.evaluate("() => { hacerCopiaSeguridad(); }")
            esperar_aviso(pg)
            pg.evaluate("cerrarMisActas()")
            descargar(pg, "#btnDescargar", SALIDA / "P-16.pdf")
            pg.wait_for_function("state.acta.estado === 'emitida'")
            cerrar_aviso(pg)
            pg.wait_for_function("!document.getElementById('emitCopia').classList.contains('hidden')", timeout=5000)
            r.comprobar("Copia hecha con el PDF ya preparado y emisión después: sigue avisando de la emitida sin copia",
                        "Hay 1 acta emitida sin copia de seguridad" in pg.text_content("#emitCopiaEstado")
                        and pg.evaluate("document.querySelector('.header-btn').classList.contains('pendiente')"),
                        pg.text_content("#emitCopiaEstado"))

            # ══ 13 · Importación que llega tarde: decide con la versión del teléfono en ese momento ══
            resultado = pg.evaluate(f"""async () => {{
                const emitida = await Almacen.leerActa('{acta_id}');
                const borrador = {{ ...emitida, estado: 'borrador', emitida: null, modificada: '2099-01-01T00:00:00.000Z' }};
                const decision = await Almacen.reemplazarActa(borrador, []);
                const guardada = await Almacen.leerActa('{acta_id}');
                return [decision, guardada.estado, (await Almacen.fotosDeActa('{acta_id}')).length];
            }}""")
            r.comprobar("Importar: si entretanto se ha emitido, no la pisa con el borrador importado ni le quita las fotos",
                        resultado == ["conservar", "emitida", 1], str(resultado))

        # ══ 14 · Una foto que se procesa mientras otra ventana guarda el acta no se pierde ══
        with seccion(r, "Foto procesándose mientras otra ventana guarda el acta", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, acta_id = nueva_en_ventana(ctx, errores, "17", "EXP-PROC")
            pa.click("#gpsBtn")
            pa.wait_for_selector("#gpsStatus.ok", timeout=15000)
            avanzar_hasta(pa, 3)
            pa.wait_for_function("!state.pendiente", timeout=5000)
            pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
            pa.evaluate("""() => { const original = comprimirImagen;
                comprimirImagen = archivo => new Promise(r => { window.soltarFoto = () => r(original(archivo)); }); }""")
            pa.set_input_files("#photoInput", [horizontal])
            pa.wait_for_function("typeof window.soltarFoto === 'function'", timeout=5000)
            pb.evaluate("irAFase(1)")
            escribir_expediente(pb, "EXP-PROC-B")
            pb.wait_for_function("!state.pendiente && state.acta.datos.expediente === 'EXP-PROC-B'", timeout=5000)
            pa.wait_for_function("state.acta.datos.expediente === 'EXP-PROC-B'", timeout=5000)   # A se ha puesto al día
            pa.evaluate("soltarFoto()")
            esperar_fotos(pa, 1, espera=10000)
            pa.wait_for_function("!state.pendiente", timeout=5000)
            r.comprobar("Foto procesándose mientras otra ventana guarda el acta: se añade a la versión al día y se guarda",
                        pa.evaluate(ESTADO, acta_id) == ["borrador", 1, False, "EXP-PROC-B"] and pa.evaluate(IMAGENES, acta_id) == 1,
                        str(pa.evaluate(ESTADO, acta_id)))

        # ══ 15 · Sin espacio para las fotos al emitir un acta borrada en otra ventana: el acta se guarda igual ══
        with seccion(r, "Sin espacio para las fotos al emitir un acta borrada en otra ventana", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, acta_id = nueva_en_ventana(ctx, errores, "18", "EXP-LLENO")
            hasta_emision(pa, ctx.new_cdp_session(pa), horizontal)
            pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
            pa.evaluate("canalVentanas.onmessage = null")
            pb.once("dialog", lambda d: d.accept())
            pb.evaluate(f"borrarActaGuardada('{acta_id}')")
            pb.wait_for_function(f"Almacen.leerActa('{acta_id}').then(a => !a)", timeout=5000)
            pa.evaluate("""() => { const put = IDBObjectStore.prototype.put;        // teléfono lleno: no caben imágenes
                IDBObjectStore.prototype.put = function (valor, ...resto) {
                  if (valor && valor.blob) throw new DOMException('Sin espacio', 'QuotaExceededError');
                  return put.call(this, valor, ...resto); }; }""")
            descargar(pa, "#btnDescargar", SALIDA / "P-18.pdf")
            pa.wait_for_function("state.acta.estado === 'emitida'")
            pa.wait_for_timeout(500)
            aviso = cerrar_aviso(pa) or ""
            r.comprobar("Sin espacio para volver a guardar las fotos al emitir: el acta queda guardada emitida igualmente y lo avisa",
                        pa.evaluate(ESTADO, acta_id) == ["emitida", 1, True, "EXP-LLENO"]
                        and "Emitida" in pa.text_content("#estadoGuardado") and "Fotos sin guardar" in aviso,
                        f"{pa.evaluate(ESTADO, acta_id)} · {aviso[:60]}")

        # ══ 16 · Menú de compartir que no llega a cerrarse: al tocar la app, se pone al día ══
        with seccion(r, "Menú de compartir que no se cierra", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, acta_id = nueva_en_ventana(ctx, errores, "19", "EXP-COLGADO")
            hasta_emision(pa, ctx.new_cdp_session(pa), horizontal)
            pb, _, _ = segunda_ventana(ctx, errores, pa, acta_id)
            pa.evaluate("""() => { navigator.canShare = () => true;       // un menú que no responde… hasta que se le diga
                navigator.share = () => { window.menuAbierto = true; return new Promise(r => { window.cerrarMenu = r; }); }; }""")
            pa.evaluate("() => { compartirPDF(); }")
            pa.wait_for_function("window.menuAbierto === true", timeout=5000)
            pa.evaluate("""() => { document.getElementById('btnCompartir').dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                compartirPDF(); }""")                                     # doble pulsación en «Compartir PDF»
            aviso = esperar_aviso(pa)
            r.comprobar("Doble pulsación en Compartir: avisa de que el menú sigue abierto y no deja de esperar la emisión",
                        "Menú de compartir abierto" in aviso and pa.evaluate("emisionEnCurso === state.acta"), aviso)
            pb.evaluate("irAFase(1)")
            escribir_expediente(pb, "EXP-COLGADO-B")
            pb.wait_for_function("!state.pendiente && state.acta.datos.expediente === 'EXP-COLGADO-B'", timeout=5000)
            pa.wait_for_timeout(400)
            esperando = pa.evaluate("state.acta.datos.expediente") == "EXP-COLGADO"
            pa.click("#emitActaTitle")                                   # el usuario vuelve a tocar la app
            pa.wait_for_function("state.acta.datos.expediente === 'EXP-COLGADO-B'", timeout=5000)
            r.comprobar("Menú de compartir que no se cierra: espera sin recargar y, al tocar la app, se pone al día",
                        esperando and pa.evaluate("state.acta.estado") == "borrador"
                        and pa.evaluate(ESTADO, acta_id) == ["borrador", 1, True, "EXP-COLGADO-B"], str(pa.evaluate(ESTADO, acta_id)))
            pa.evaluate("cerrarMenu()")                                  # el menú responde por fin
            aviso = esperar_aviso(pa)
            r.comprobar("…y si después responde, no emite un acta distinta de la compartida: lo avisa",
                        "PDF compartido sin emitir" in aviso and pa.evaluate(ESTADO, acta_id) == ["borrador", 1, True, "EXP-COLGADO-B"]
                        and pa.evaluate("state.acta.estado") == "borrador", aviso)

        # ══ 17 · PDF rehecho al pulsar y acta cambiada mientras se prepara: no se distribuye ni se emite ══
        with seccion(r, "PDF rehecho al pulsar y acta cambiada mientras se prepara", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pa, acta_id = nueva_en_ventana(ctx, errores, "20", "EXP-REHECHO")
            hasta_emision(pa, ctx.new_cdp_session(pa), horizontal)
            descargas = []
            pa.on("download", lambda d: descargas.append(d.suggested_filename))
            resultado = pa.evaluate("""async () => {
                Object.assign(pdfEmision, { clave: null, promesa: null, listo: null });   // hay que rehacer el PDF
                const descarga = descargarPDF();
                state.acta.observaciones = 'Cambiada mientras se preparaba el PDF';
                return descarga; }""")
            pa.wait_for_timeout(500)
            r.comprobar("Acta cambiada mientras se rehace el PDF: ni se descarga ni se emite (se vuelve a pulsar)",
                        resultado is False and not descargas and pa.evaluate(ESTADO, acta_id)[0] == "borrador"
                        and pa.evaluate("state.acta.estado") == "borrador", f"{resultado} · {descargas}")

        # ══ 18 · Copia con un acta guardada con el reloj del teléfono adelantado ══
        with seccion(r, "Copia con un acta guardada con el reloj adelantado", abiertos):
            ctx = contexto_movil(p, navegador)
            abiertos.append(ctx)
            vigilar_red(ctx, externas)
            pg, _ = nueva_en_ventana(ctx, errores, "21", "EXP-RELOJ")
            pg.evaluate("""async () => { const a = actaNueva(); a.datos.expediente = 'EXP-RELOJ'; a.datos.actaNum = '22';
                a.modificada = new Date(Date.now() + 30 * 86400000).toISOString(); await Almacen.guardarActa(a); }""")
            with pg.expect_download(timeout=60000):
                pg.evaluate("() => { hacerCopiaSeguridad(); }")
            esperar_aviso(pg)
            estado = pg.text_content("#copiaEstado")
            r.comprobar("Copia con un acta guardada con el reloj adelantado un mes: queda «Al día» (la copia anota qué versión lleva)",
                        estado.startswith("✓ Al día"), estado)

        r.comprobar("Sin peticiones a internet", not externas, "; ".join(externas[:3]))
        r.comprobar("Sin errores JS", not errores, "; ".join(errores[:3]))
        navegador.close()
    srv.shutdown()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
