"""Utilidades compartidas por las pruebas de extremo a extremo."""
import functools
import http.server
import pathlib
import re
import threading
from urllib.parse import urlparse

from pypdf import PdfReader

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "tests" / "salida"
PUERTO = 8765
URL = f"http://localhost:{PUERTO}/index.html"
GPS_SEVILLA = {"latitude": 37.389210, "longitude": -5.984460, "accuracy": 8}
DESCRIPCION_LARGA = (
    "Inspección de estructura existente para legalización de vivienda unifamiliar, revisión de "
    "cimentación, forjados y cubierta, con toma de fotografías de patologías")
COMENTARIO_LARGO = (
    "Fisura longitudinal en la viga principal del lado norte, con abertura aproximada de 0,3 mm y "
    "longitud visible de 1,20 m. Se aprecian manchas de humedad en el entorno y desprendimiento "
    "puntual del recubrimiento con armadura vista y principio de oxidación. Se recomienda "
    "picado, pasivado de armaduras y reparación con mortero R4, así como seguimiento con testigos.")

# Devuelve true si el lienzo de firma tiene algún píxel pintado.
LIENZO_CON_TINTA = """(() => { const c = document.getElementById('sigCanvas');
  if (!c.width || !c.height) return false;
  return c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some((v, i) => i % 4 === 3 && v > 0); })()"""


class Resultados:
    def __init__(self):
        self.lista = []

    def comprobar(self, nombre, condicion, detalle=""):
        self.lista.append((bool(condicion), nombre, detalle))
        print(f"{'OK   ' if condicion else 'FALLO'} {nombre}" + (f"  ({detalle})" if detalle else ""), flush=True)

    def resumen(self):
        fallos = [r for r in self.lista if not r[0]]
        print(f"\n{len(self.lista) - len(fallos)}/{len(self.lista)} comprobaciones correctas. Salida en {SALIDA}")
        return 1 if fallos else 0


class _ManejadorSilencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def servidor():
    manejador = functools.partial(_ManejadorSilencioso, directory=str(RAIZ))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PUERTO), manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def contexto_movil(p, navegador, permisos=("geolocation",), gps=GPS_SEVILLA, **extra):
    opciones = dict(p.devices["Pixel 7"], locale="es-ES", timezone_id="Europe/Madrid", accept_downloads=True)
    if gps:
        opciones["geolocation"] = gps
    opciones["permissions"] = list(permisos)
    opciones.update(extra)
    return navegador.new_context(**opciones)


def vigilar_red(contexto, externas):
    """Bloquea y anota cualquier petición fuera de localhost: la app debe funcionar sin internet."""
    def ruta(r):
        if urlparse(r.request.url).hostname not in ("localhost", "127.0.0.1"):
            externas.append(r.request.url)
            return r.abort()
        return r.continue_()
    contexto.route("**/*", ruta)


def normalizar(texto):
    return re.sub(r"\s+", " ", texto).strip()


def texto_pdf(ruta_pdf):
    return normalizar(" ".join(pagina.extract_text() for pagina in PdfReader(str(ruta_pdf)).pages))


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


def desviacion_maxima(imagenes, ancho_min=900):
    """Mayor diferencia relativa entre la proporción dibujada y la de la imagen (0 = sin deformar)."""
    fotos = [i for i in imagenes if i[6] == "/DCTDecode" and i[4] >= ancho_min]
    return fotos, max((abs((w / h) / (pw / ph) - 1) for _, _, w, h, pw, ph, _, _ in fotos), default=0)


def abrir(contexto, errores, url=URL):
    """Abre la app en una pestaña nueva y espera a que cargue el acta."""
    pagina = contexto.new_page()
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    pagina.goto(url)
    pagina.wait_for_load_state("networkidle")
    pagina.wait_for_function("typeof state !== 'undefined' && state.acta !== null")
    return pagina


def abrir_mis_actas(pagina):
    """Abre «Mis actas» y espera a que la lista esté actualizada y visible."""
    pagina.click("button.header-btn")
    pagina.wait_for_selector("#panelActas.open")


def avanzar_hasta(pagina, fase):
    while pagina.evaluate("state.fase") < fase:
        antes = pagina.evaluate("state.fase")
        pagina.click("#btnNext")
        if pagina.evaluate("state.fase") == antes:
            raise AssertionError(f"No se pudo pasar de la fase {antes}: {cerrar_aviso(pagina)}")


def firmar(cdp, pagina, desplazamiento=0, lienzo=None):
    """Traza una firma con eventos táctiles reales sobre el lienzo indicado (por defecto, el del técnico)."""
    lienzo = lienzo or pagina.locator("#sigCanvas")
    lienzo.evaluate("el => el.scrollIntoView({ block: 'center' })")
    caja = lienzo.bounding_box()
    x0, y0 = caja["x"] + 30 + desplazamiento, caja["y"] + 40
    puntos = [(x0 + i * 12, y0 + (25 if i % 2 else 0) + i * 2) for i in range(22)]
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": puntos[0][0], "y": puntos[0][1]}]})
    for x, y in puntos[1:]:
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


def rellenar_identificacion(pagina, acta="TBC-2026-0042", gps=True, avanzar=True):
    pagina.fill("#actaNum", acta)
    pagina.fill("#tecnico", "Blas González González")
    pagina.fill("#expediente", "425_2026.CON")
    pagina.fill("#descripcion", DESCRIPCION_LARGA)
    if gps:
        pagina.click("#gpsBtn")
        pagina.wait_for_selector("#gpsStatus.ok", timeout=15000)
    if avanzar:
        pagina.click("#btnNext")


def esperar_fotos(pagina, n, espera=60000):
    pagina.wait_for_function(f"state.fotosEnProceso === 0 && state.acta.fotos.length === {n}", timeout=espera)


def cerrar_aviso(pagina):
    """Cierra el aviso modal si está abierto y devuelve su texto (o None)."""
    texto = pagina.evaluate("""(() => { const o = document.getElementById('alertOverlay');
        return o.classList.contains('open') ? document.getElementById('alertTitle').textContent + ' | '
          + document.getElementById('alertMsg').textContent : null; })()""")
    if texto:
        pagina.evaluate("cerrarAviso()")
    return texto
