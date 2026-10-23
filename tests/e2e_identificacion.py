"""Pruebas de la v3.1 en un Pixel 7 emulado: cabecera en gris corporativo, orden de la identificación (expediente
primero), técnico, cargo y objeto de listas desplegables (con «Otro» y detalle), cargo de los asistentes, sugerencias
de expedientes, técnico y cargo recordados en el teléfono, revisión, PDF, texto compartido y registro en Excel,
migración de las actas de la v3.0 (esquema 3) e importación.

Uso (desde la raíz del repo, con los mismos requisitos que e2e_seguimiento.py):
    python tests/e2e_identificacion.py
"""
import json
import pathlib
import re
import sys

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from comun import (RAIZ, SALIDA, Resultados, abrir, abrir_mis_actas, cerrar_aviso, contexto_movil,  # noqa: E402
                   esperar_fotos, firmar, servidor, texto_pdf, vigilar_red)
from generar_fotos import generar  # noqa: E402

TECNICOS = ["Alberto de Álava", "Ana Cascajosa", "Ángel García", "Blas González", "Francisco S. Ortiz",
            "José A. Gómez", "José L. Gutiérrez"]               # en orden alfabético
CARGOS = ["Inspector de Campo", "Redactor de Estudio", "Director de Obra", "Supervisor de Obra"]
OBJETOS = ["Licitación de Obra", "Inspección de Tajos de Obra", "Inventario", "Estudio de Patología", "Otro"]
EXP = "EXP-ID"
GRIS = "rgb(136, 136, 136)"                                     # #888888
DAÑOS = "Revisión de daños tras la tormenta"
LOSA = "Hormigonado de la losa de planta 1"
OPCIONES = "id => Array.from(document.getElementById(id).options).map(o => [o.value, o.textContent])"
ESTILOS = """(() => { const c = s => getComputedStyle(document.querySelector(s));
  return { cabecera: c('.app-header').backgroundColor, pasos: c('.stepper').backgroundColor,
           titulo: c('.header-text h1').color, subtitulo: c('.header-text p').color, guardado: c('.estado-guardado').color,
           paso: c('.step-item:not(.active) .step-label').color, activo: c('.step-item.active .step-label').color,
           tema: document.querySelector('meta[name=theme-color]').content }; })()"""


def rgb(texto):
    return [int(v) for v in re.findall(r"\d+", texto)[:3]]


def contraste(a, b):
    """Relación de contraste WCAG entre dos colores CSS «rgb(…)»."""
    def lum(color):
        canales = [c / 255 for c in rgb(color)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    claro, oscuro = sorted((lum(a), lum(b)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def descargar(pg, selector, ruta):
    with pg.expect_download(timeout=60000) as d:
        pg.click(selector)
    d.value.save_as(str(ruta))
    return d.value.suggested_filename


def main():
    r = Resultados()
    SALIDA.mkdir(parents=True, exist_ok=True)
    horizontal, _, _ = (str(f) for f in generar(SALIDA / "fotos"))
    srv = servidor()
    externas, errores = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        ctx = contexto_movil(p, navegador)
        vigilar_red(ctx, externas)
        pg = abrir(ctx, errores)
        cdp = ctx.new_cdp_session(pg)
        esquema = pg.evaluate("ESQUEMA")

        # ══ Mejora 1 · Cabecera en gris corporativo ══
        estilos = pg.evaluate(ESTILOS)
        manifiesto = json.loads((RAIZ / "manifest.webmanifest").read_text(encoding="utf-8"))
        r.comprobar("Cabecera y pasos en gris corporativo #888888; también la barra del navegador y la app instalada",
                    estilos["cabecera"] == GRIS and estilos["pasos"] == GRIS and estilos["tema"].lower() == "#888888"
                    and manifiesto["theme_color"].lower() == "#888888", str({k: estilos[k] for k in ("cabecera", "pasos", "tema")}))
        contrastes = {k: round(contraste(estilos[k], GRIS), 2) for k in ("titulo", "subtitulo", "guardado", "paso", "activo")}
        r.comprobar("Sobre el gris, los textos pequeños se leen (≥ 4,5:1) y el título blanco en negrita (≥ 3:1)",
                    all(contrastes[k] >= 4.5 for k in ("subtitulo", "guardado", "paso", "activo")) and contrastes["titulo"] >= 3,
                    str(contrastes))
        abrir_mis_actas(pg)
        panel = pg.evaluate("""[getComputedStyle(document.querySelector('.panel-header')).backgroundColor,
                                getComputedStyle(document.querySelector('.panel-title')).color]""")
        r.comprobar("Mis actas: cabecera del panel en el mismo gris, con el título legible",
                    panel[0] == GRIS and contraste(panel[1], GRIS) >= 4.5, str(panel))
        pg.screenshot(path=str(SALIDA / "s31-mis-actas.png"))
        pg.evaluate("cerrarMisActas()")

        # ══ Mejora 2 · El expediente, primer campo ══
        orden = pg.evaluate("Array.from(document.querySelectorAll('#phase1 input, #phase1 select')).map(e => e.id).filter(Boolean)")
        esperado = ["expediente", "actaNum", "actaRev", "tecnico", "cargoTecnico", "cargoTecnicoOtro", "objeto", "descripcion",
                    "fechaVisita", "horaVisita"]
        r.comprobar("Identificación: expediente, nº de acta, técnico, cargo, objeto y detalle, fecha y hora, en ese orden",
                    orden[:len(esperado)] == esperado, ", ".join(orden[:10]))

        # ══ Mejoras 3, 4 y 5 · Listas desplegables ══
        tecnicos, cargos, objetos = (pg.evaluate(OPCIONES, i) for i in ("tecnico", "cargoTecnico", "objeto"))
        r.comprobar("Técnicos de TEAMBIMCIVIL en una lista, en orden alfabético y con tildes",
                    tecnicos == [["", "Elige el técnico"]] + [[t, t] for t in TECNICOS], ", ".join(t[1] for t in tecnicos))
        r.comprobar("Cargo del técnico: los 4 roles, en su orden, y «Otro»",
                    cargos == [["", "Elige el cargo"]] + [[c, c] for c in CARGOS] + [["__otro", "Otro…"]], ", ".join(c[1] for c in cargos))
        r.comprobar("Objeto de la visita: los 5 de la lista",
                    [o[1] for o in objetos] == ["Elige el objeto"] + OBJETOS and objetos[-1][0] == "otro", ", ".join(o[1] for o in objetos))

        def aviso_al_seguir():
            pg.click("#btnNext")
            return cerrar_aviso(pg) or ""

        avisos = [aviso_al_seguir()]                          # nada rellenado
        pg.fill("#expediente", EXP)
        pg.wait_for_function(f"state.acta.datos.actaNum === '{EXP}-AV-01'", timeout=5000)
        avisos.append(aviso_al_seguir())                      # falta el técnico
        pg.select_option("#tecnico", "Ana Cascajosa")
        avisos.append(aviso_al_seguir())                      # falta el cargo
        pg.select_option("#cargoTecnico", "__otro")
        otro_cargo = [pg.is_visible("#cargoTecnicoOtro"), pg.evaluate("document.activeElement.id")]
        avisos.append(aviso_al_seguir())                      # «Otro» sin escribir
        pg.fill("#cargoTecnicoOtro", "Jefe de equipo")
        avisos.append(aviso_al_seguir())                      # falta el objeto
        pg.select_option("#objeto", "otro")
        otro_objeto = [pg.text_content("#descripcionEtiqueta"), pg.evaluate("document.activeElement.id")]
        avisos.append(aviso_al_seguir())                      # «Otro» sin describir
        pg.fill("#descripcion", DAÑOS)
        avisos.append(aviso_al_seguir())                      # falta la ubicación
        claves = ["expediente", "técnico", "cargo", "cargo", "objeto", "describe el objeto", "ubicación"]
        r.comprobar("Avisos en el orden de los campos: expediente, técnico, cargo (también «Otro» vacío), objeto, «Otro» sin describir, ubicación",
                    len(avisos) == len(claves) and all(c in a.lower() for c, a in zip(claves, avisos)), " | ".join(a.split("|")[-1][:34] for a in avisos))
        r.comprobar("Cargo «Otro»: aparece un campo para escribirlo (con el cursor en él)",
                    otro_cargo == [True, "cargoTecnicoOtro"] and pg.evaluate("state.acta.datos.cargoTecnico") == "Jefe de equipo", str(otro_cargo))
        r.comprobar("Objeto «Otro»: el detalle pasa a «Describe el objeto», obligatorio",
                    "Describe el objeto" in otro_objeto[0] and otro_objeto[1] == "descripcion", str(otro_objeto))
        pg.click("#gpsBtn")
        pg.wait_for_selector("#gpsStatus.ok", timeout=15000)
        pg.click("#btnNext")                                  # → asistentes

        # ── Asistentes: el técnico con su cargo y el cargo de cada asistente de la lista ──
        r.comprobar("Asistentes: el técnico con su cargo, que ya no se pide en esta fase",
                    pg.evaluate("state.fase") == 2 and pg.text_content("#tecnicoNombreAsist") == "Ana Cascajosa"
                    and pg.text_content("#tecnicoCargoAsist") == "TEAMBIMCIVIL · Jefe de equipo"
                    and pg.locator("#phase2 select, #phase2 input").count() == 0)
        pg.click("button:has-text('Añadir asistente')")
        pg.fill("#asNombre0", "Juan Pérez")
        pg.fill("#asEmpresa0", "Constructora Sur")
        lista_asistente = pg.evaluate(OPCIONES, "asCargo0")
        pg.select_option("#asCargo0", "Supervisor de Obra")
        de_lista = pg.evaluate("[state.acta.asistentes[0].cargo, document.getElementById('asCargoOtro0').classList.contains('hidden')]")
        pg.select_option("#asCargo0", "__otro")
        foco = pg.evaluate("document.activeElement.id")
        pg.fill("#asCargoOtro0", "Encargado")
        pg.click("button:has-text('Añadir asistente')")       # se vuelve a pintar la lista
        pg.fill("#asNombre1", "Marta Ruiz")
        pg.fill("#asEmpresa1", "Propiedad")
        pg.select_option("#asCargo1", "Redactor de Estudio")
        repintado = pg.evaluate("""[document.getElementById('asCargo0').value, document.getElementById('asCargoOtro0').value,
            document.getElementById('asCargoOtro0').classList.contains('hidden'), state.acta.asistentes.map(a => a.cargo)]""")
        r.comprobar("Cargo de los asistentes: la misma lista; uno de ella o «Otro» escrito, que se conserva al repintar",
                    lista_asistente == cargos and de_lista == ["Supervisor de Obra", True] and foco == "asCargoOtro0"
                    and repintado == ["__otro", "Encargado", False, ["Encargado", "Redactor de Estudio"]], str(repintado))
        pg.screenshot(path=str(SALIDA / "s31-asistentes.png"), full_page=True)
        pg.click("#btnNext")                                  # → fotos
        pg.set_input_files("#photoInput", [horizontal])
        esperar_fotos(pg, 1)
        pg.click("#btnNext")                                  # → notas
        pg.click("#btnNext")                                  # → acuerdos
        responsables = pg.evaluate("Array.from(document.querySelectorAll('#responsablesLista option')).map(o => o.value)")
        r.comprobar("Responsables sugeridos con los cargos de la lista y los escritos",
                    responsables == ["TEAMBIMCIVIL · Jefe de equipo", "Constructora Sur · Encargado", "Propiedad · Redactor de Estudio"],
                    str(responsables))
        pg.click("#btnNext")                                  # → firmas
        firmar(cdp, pg)
        pg.once("dialog", lambda dialogo: dialogo.accept())   # los asistentes no firman: «No firma»
        pg.click("#btnNext")                                  # → revisión
        general = pg.inner_text("#reviewGeneral")
        r.comprobar("Revisión: con «Otro», el objeto es lo descrito", f"Objeto\t{DAÑOS}" in general or f"Objeto\n{DAÑOS}" in general,
                    general.replace("\n", " | ")[:160])
        pg.click("#btnNext")                                  # → emisión
        mensaje = pg.evaluate("textoCompartir()")
        ruta1 = SALIDA / "S31-AV01.pdf"
        descargar(pg, "#btnDescargar", ruta1)
        pg.wait_for_function("state.acta.estado === 'emitida'")
        acta1 = pg.evaluate("state.acta.id")
        texto1 = texto_pdf(ruta1)
        r.comprobar("PDF: técnico, objeto descrito y cargos de la lista o escritos",
                    f"OBJETO {DAÑOS}" in texto1 and "Otro ·" not in texto1 and "TÉCNICO Ana Cascajosa" in texto1
                    and all(s in texto1 for s in ("Jefe de equipo", "Encargado", "Redactor de Estudio")) and f"Objeto: {DAÑOS}" in mensaje)
        r.comprobar("Un acta emitida: técnico, cargo y objeto bloqueados",
                    pg.evaluate("['tecnico', 'cargoTecnico', 'cargoTecnicoOtro', 'objeto', 'descripcion'].every(id => document.getElementById(id).disabled)"))

        # ══ Propuestas: técnico y cargo recordados; sugerencias de expedientes ══
        abrir_mis_actas(pg)
        pg.click("#panelActas button:has-text('Nueva acta')")
        pg.wait_for_function("state.persistida === false && state.acta.datos.expediente === ''")
        nueva = pg.evaluate("""['tecnico', 'cargoTecnico', 'cargoTecnicoOtro', 'objeto', 'expediente']
            .map(id => document.getElementById(id).value)""")
        r.comprobar("Un acta nueva propone el último técnico y cargo del teléfono (no el objeto ni el expediente)",
                    nueva == ["Ana Cascajosa", "__otro", "Jefe de equipo", "", ""], str(nueva))
        pg.focus("#expediente")
        pg.wait_for_function(f"Array.from(document.querySelectorAll('#expedientesLista option')).some(o => o.value === '{EXP}')",
                             timeout=5000)
        r.comprobar("Al escribir el expediente se sugieren los ya usados en el teléfono",
                    pg.evaluate("document.getElementById('expediente').getAttribute('list')") == "expedientesLista")

        # ── «Nueva visita»: copia técnico, cargo, objeto y detalle; objeto de la lista con detalle ──
        abrir_mis_actas(pg)
        pg.click(f".acta-card[data-acta='{acta1}'] button:has-text('Nueva visita')")
        pg.wait_for_function(f"state.acta.datos.actaNum === '{EXP}-AV-02'", timeout=10000)
        copia = pg.evaluate("[state.acta.datos.tecnico, state.acta.datos.cargoTecnico, state.acta.datos.objeto, state.acta.datos.descripcion]")
        r.comprobar("«Nueva visita» copia el técnico, su cargo y el objeto con su detalle",
                    copia == ["Ana Cascajosa", "Jefe de equipo", "otro", DAÑOS], str(copia))
        pg.select_option("#tecnico", "Blas González")
        pg.select_option("#cargoTecnico", "Director de Obra")
        pg.select_option("#objeto", "tajos")
        pg.fill("#descripcion", LOSA)
        r.comprobar("Objeto de la lista con detalle: «Inspección de Tajos de Obra · detalle»",
                    pg.evaluate("textoObjeto(state.acta)") == f"Inspección de Tajos de Obra · {LOSA}"
                    and pg.is_hidden("#cargoTecnicoOtro") and "Detalle (opcional)" in pg.text_content("#descripcionEtiqueta"))
        pg.click("#gpsBtn")
        pg.wait_for_selector("#gpsStatus.ok", timeout=15000)
        pg.evaluate("window.scrollTo(0, 0)")
        pg.screenshot(path=str(SALIDA / "s31-identificacion.png"))
        pg.evaluate("guardarYa()")

        # ── Registro en Excel: objeto y detalle en columnas propias, técnico y cargo ──
        abrir_mis_actas(pg)
        descargar(pg, "#btnRegistro", SALIDA / "S31-registro.xlsx")
        cerrar_aviso(pg)
        hoja = load_workbook(SALIDA / "S31-registro.xlsx")["Actas"]
        cabecera = [c.value for c in hoja[1]]
        filas = [f[6:10] for f in hoja.iter_rows(min_row=2, values_only=True)]
        r.comprobar("Registro: columnas Objeto, Detalle, Técnico y Cargo del técnico con los valores de cada acta",
                    cabecera[6:10] == ["Objeto", "Detalle", "Técnico", "Cargo del técnico"]
                    and filas == [("Otro", DAÑOS, "Ana Cascajosa", "Jefe de equipo"),
                                  ("Inspección de Tajos de Obra", LOSA, "Blas González", "Director de Obra")], str(filas))
        pg.evaluate("cerrarMisActas()")
        ctx.close()

        # ══ Actas de la v3.0 (esquema 3): migración y PDF sin cambios ══
        ctx_c = contexto_movil(p, navegador)
        vigilar_red(ctx_c, externas)
        pc = abrir(ctx_c, errores)
        pc.evaluate("""async () => {
            const base = { esquema: 3, creada: '2026-10-20T08:00:00.000Z', modificada: '2026-10-20T09:00:00.000Z', revision: 0,
              datos: { actaNum: 'V30-AV-01', numAuto: false, tecnico: 'Blas González González', cargoTecnico: 'Dirección facultativa',
                       expediente: 'V30', descripcion: 'Texto libre de la v3.0', fecha: '2026-10-20', hora: '09:00' },
              gps: { lat: '37.389210', lng: '-5.984460', acc: 8, hora: '2026-10-20T08:05:00.000Z' },
              sinGps: { activo: false, referencia: '', lat: '', lng: '' }, condiciones: { meteo: [], temperatura: '' },
              asistentes: [], observaciones: '', seguimiento: [], seguimientoOrigen: null, seguimientoNotas: [],
              seguimientoGuardado: null, indicaciones: [], fotos: [], firmasAsistentes: {},
              firma: [{ refW: 300, refH: 150, puntos: [[10, 10], [60, 40], [120, 20], [180, 60], [240, 30]] }] };
            await Almacen.guardarActa({ ...base, id: 'acta-v30-emitida', estado: 'emitida', emitida: '2026-10-20T10:00:00.000Z',
              versionEmision: '3.0', fase: 8, revisiones: [{ rev: 0, fecha: '2026-10-20T10:00:00.000Z', motivo: 'Emisión inicial' }] });
            await Almacen.guardarActa({ ...base, id: 'acta-v30-borrador', estado: 'borrador', emitida: null, fase: 1,
              revisiones: [{ rev: 0, fecha: null, motivo: 'Emisión inicial' }], datos: { ...base.datos, actaNum: 'V30-AV-02' } });
            localStorage.setItem('tbc-acta-actual', 'acta-v30-borrador');
        }""")
        pc.reload()
        pc.wait_for_function("state.acta && state.acta.id === 'acta-v30-borrador'")
        migrada = pc.evaluate("""({ esquema: state.acta.esquema, objeto: state.acta.datos.objeto,
            tecnico: document.getElementById('tecnico').value,
            opcion: Array.from(document.getElementById('tecnico').options).some(o => o.value === 'Blas González González'),
            cargo: [document.getElementById('cargoTecnico').value, document.getElementById('cargoTecnicoOtro').value],
            detalle: document.getElementById('descripcion').value })""")
        r.comprobar("Un borrador de la v3.0 se migra: su técnico y su cargo, que no están en las listas, se muestran tal cual",
                    migrada == {"esquema": esquema, "objeto": "", "tecnico": "Blas González González", "opcion": True,
                                "cargo": ["__otro", "Dirección facultativa"], "detalle": "Texto libre de la v3.0"}, str(migrada))
        pc.click("#btnNext")
        aviso = cerrar_aviso(pc) or ""
        r.comprobar("…y al seguir pide elegir el objeto de la visita (el texto anterior queda como detalle)",
                    "Elige el objeto" in aviso and pc.evaluate("state.fase") == 1, aviso)
        pc.evaluate("abrirActaGuardada('acta-v30-emitida')")
        pc.wait_for_function("state.acta.id === 'acta-v30-emitida' && state.fase === 8")
        pc.wait_for_function("document.getElementById('emitPdfEstado').textContent.startsWith('PDF listo')", timeout=60000)
        descargar(pc, "#btnDescargar", SALIDA / "S31-v30-emitida.pdf")
        texto_v30 = texto_pdf(SALIDA / "S31-v30-emitida.pdf")
        r.comprobar("Un acta emitida con la v3.0 genera su PDF como entonces (objeto con su texto, técnico y cargo)",
                    "OBJETO Texto libre de la v3.0" in texto_v30 and "TÉCNICO Blas González González" in texto_v30
                    and "Dirección facultativa" in texto_v30)
        importado = pc.evaluate("""(() => {
            const ficha = { formato: 'tbc-acta', acta: { id: 'acta-imp-1', estado: 'borrador', datos: { objeto: 'patologia' }, fotos: [] } };
            const valido = actaDesdeArchivo(ficha).datos.objeto;
            ficha.acta.datos.objeto = '<b>xyz</b>';
            const desconocido = actaDesdeArchivo(ficha).datos.objeto;
            ficha.acta.datos.objeto = 5;
            return [valido, desconocido, actaDesdeArchivo(ficha).datos.objeto];
        })()""")
        r.comprobar("Importación: solo se acepta un objeto de la lista", importado == ["patologia", "", ""], str(importado))
        ctx_c.close()

        r.comprobar("Sin peticiones a internet", not externas, "; ".join(externas[:3]))
        r.comprobar("Sin errores JS", not errores, "; ".join(errores[:3]))
        navegador.close()
    srv.shutdown()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
