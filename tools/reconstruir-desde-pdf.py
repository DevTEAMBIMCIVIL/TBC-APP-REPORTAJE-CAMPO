"""Reconstruye actas emitidas a partir de sus PDF, en el formato de importación de la app (como «Exportar»: un ZIP
con <carpeta>/acta.json y <carpeta>/fotos/NN.jpg). Sirve para recuperar actas que ya no están en ningún teléfono.

Lee los PDF de la v2.3 a la v3.1.x («Acta de Visita de Inspección» o «Acta de Campo»; los de la v2.2 y anteriores
tienen otro formato). Del PDF se toman: número y revisión, técnico y su cargo, expediente, objeto (con su tipo de la
lista desde la v3.1), fecha y hora, condiciones, GPS de la visita (o la referencia sin cobertura), asistentes y si
firman, observaciones, seguimiento de indicaciones anteriores, indicaciones, fotos (el JPEG incrustado, tal cual, con
su hora, GPS y comentario), firmas (la imagen se convierte en trazos) y el control de revisiones. Las actas quedan
emitidas con la versión con la que se emitieron (`versionEmision`), así que la app rehace su PDF como se distribuyó.

Si se reconstruyen juntas varias actas de un expediente, el seguimiento queda enlazado con las indicaciones de las
actas anteriores del lote (mismos id), como en la app. Si el acta de origen no está en el lote, la indicación del
seguimiento sale igual en el PDF, pero el registro no la enlaza con la original.

Uso:   python tools/reconstruir-desde-pdf.py <carpeta_salida> <pdf> [<pdf> …]
Crea:  Actas_reconstruidas.zip (todas) y Acta_<nº>_Rev<N>_reconstruida.zip (una por acta), para «Mis actas → Importar».
Repetidos: un PDF que repite otro de la lista (el mismo archivo, o la misma acta compartida otra vez: mismo texto y
           mismas fotos) se reconstruye una sola vez, desde el más antiguo: el ZIP no lleva la misma acta dos veces.
No se reconstruyen, y se dice por qué: los PDF de la v2.2 y anteriores, los que no son actas de la app, los protegidos
(cifrados) y los archivos que no son PDF o están dañados.
Requisitos: pip install pdfplumber pypdf pillow numpy scikit-image   (scikit-image trae scipy)
"""
import datetime as dt
import hashlib
import io
import json
import logging
import os
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
import pdfplumber
from PIL import Image
from pypdf import PdfReader
from scipy import ndimage
from skimage.morphology import skeletonize

logging.getLogger("pypdf").setLevel(logging.ERROR)   # sin sus avisos en la consola: cada PDF dice su motivo

MM = 72 / 25.4                       # puntos por mm
EMPRESA = "TEAMBIMCIVIL"
EMPRESA_TECNICO = "TEAMBIMCIVIL S.L."      # empresa del técnico en el PDF desde la v3.1.3
UTM = "UTM ETRS89"                         # coordenadas UTM de la visita y de las fotos en el PDF desde la v3.1.4
TITULOS = ("ACTA DE VISITA DE INSPECCIÓN", "ACTA DE CAMPO")
# Deben coincidir con las listas de index.html (la prueba lo comprueba).
METEO = {"Despejado": "despejado", "Nuboso": "nuboso", "Lluvia": "lluvia", "Viento": "viento", "Niebla": "niebla",
         "Calor": "calor", "Frío": "frio"}
OBJETOS = {"Licitación de Obra": "licitacion", "Inspección de Tajos de Obra": "tajos", "Inventario": "inventario",
           "Estudio de Patología": "patologia"}
BANDA = re.compile(r"^(\d+) · (DATOS GENERALES|ASISTENTES|OBSERVACIONES GENERALES|SEGUIMIENTO DE INDICACIONES ANTERIORES|"
                   r"INDICACIONES|REPORTAJE FOTOGRÁFICO \((\d+)\)|FIRMAS|CONTROL DE REVISIONES)$")
ETIQUETAS = ["Nº DE ACTA", "TÉCNICO", "EXPEDIENTE", "OBJETO", "FECHA Y HORA", "CONDICIONES", "LOCALIZACIÓN GPS", UTM]
ANCHO_PARRAFO = 178.0                # ancho al que jsPDF parte los párrafos (mm)
ANCHO_VALOR = 128.0                  # ancho de los valores de Datos generales (mm)
ANCHO_PIE = 87.0                     # ancho de la celda de cada foto (mm)
VER_MAPA = re.compile(r"\s*(·\s*)?Ver en el mapa$")


# ── Lectura del PDF ──────────────────────────────────────────────────────────────────────────────

def texto_de(chars):
    """Texto de unos caracteres de la misma línea; los espacios se deducen de los huecos (la fuente no los marca)."""
    salida, previo = [], None
    for c in sorted(chars, key=lambda c: c["x0"]):
        if not c["t"].strip():
            continue
        if previo is not None:
            espacio = 0.278 * c["size"] * 0.3528          # ancho del espacio de la fuente (mm)
            hueco = c["x0"] - previo["x1"]
            if hueco > 0.5 * espacio:
                salida.append(" " * max(1, round(hueco / espacio)))
        salida.append(c["t"])
        previo = c
    return "".join(salida)


def lineas_de_pagina(pagina):
    """Líneas de texto del contenido (sin cabecera ni pie), con sus caracteres en mm."""
    salida = []
    for linea in pagina.extract_text_lines(return_chars=True, strip=False):
        top = linea["top"] / MM
        if top < 33 or top > 284:            # cabecera (0-32 mm) y pie (285-297 mm)
            continue
        chars = [{"t": c["text"], "x0": c["x0"] / MM, "x1": c["x1"] / MM, "size": round(c["size"], 1),
                  "top": c["top"] / MM} for c in linea["chars"]]
        salida.append({"top": top, "chars": chars, "size": chars[0]["size"], "texto": texto_de(chars)})
    return salida


def celda(chars, x_min, x_max):
    sel = [c for c in chars if x_min <= c["x0"] < x_max and c["t"].strip()]
    if not sel:
        return None
    sel.sort(key=lambda c: c["x0"])
    palabra = [sel[0]]                        # primera palabra: hasta el primer hueco de un espacio
    for c in sel[1:]:
        if c["x0"] - palabra[-1]["x1"] > 0.5 * 0.278 * c["size"] * 0.3528:
            break
        palabra.append(c)
    return {"texto": texto_de(sel).strip(), "x0": sel[0]["x0"], "x1": sel[-1]["x1"],
            "primera": palabra[-1]["x1"] - palabra[0]["x0"]}


def unir(partes, ancho):
    """Une las líneas de un texto partido por jsPDF: espacio si se partió por ancho, salto de línea si no."""
    partes = [p for p in partes if p]
    if not partes:
        return ""
    texto = partes[0]["texto"]
    for anterior, siguiente in zip(partes, partes[1:]):
        cabia = (anterior["x1"] - anterior["x0"]) + siguiente["primera"] + 1.2 < ancho
        texto += ("\n" if cabia else " ") + siguiente["texto"]
    return texto


def version(texto):
    m = re.search(r"v(\d+(?:\.\d+){1,2})", texto or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def leer_pdf(ruta):
    lector = abrir_pdf(ruta)
    meta = lector.metadata or {}
    creacion = str(meta.get("/CreationDate", ""))
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:([+-])(\d{2})'(\d{2})'|Z)?", creacion)
    if not m:
        with pdfplumber.open(str(ruta)) as pdf:
            comprobar_formato(pdf)               # si además no es un acta, se dice eso
        raise ValueError("el PDF no tiene fecha de creación")
    a, mes, d, h, mi, s, signo, th, tm = m.groups()
    zona = dt.timezone((1 if signo != "-" else -1) * dt.timedelta(hours=int(th or 0), minutes=int(tm or 0)))
    enlaces = sum(1 for pagina in lector.pages for anot in (pagina.get("/Annots") or [])
                  if "/URI" in (anot.get_object().get("/A") or {}))
    info = {"archivo": ruta.name, "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
            "creado": dt.datetime(int(a), int(mes), int(d), int(h), int(mi), int(s), tzinfo=zona), "zona": zona,
            "creador": str(meta.get("/Creator", "")), "enlaces": enlaces, "secciones": {}, "orden": [],
            "fotos_img": [], "firmas_img": [], "titulo": None, "emitida_dia": None, "separadores": {}}
    lineas = []
    with pdfplumber.open(str(ruta)) as pdf:
        comprobar_formato(pdf)                   # un PDF de la v2.2 o anterior, o que no es un acta: se dice de entrada
        for n, pagina in enumerate(pdf.pages, 1):
            for linea in pagina.extract_text_lines(strip=False):        # bloque de control: «Emitida dd/mm/aaaa»
                e = re.search(r"Emitida (\d{2})/(\d{2})/(\d{4})", linea["text"])
                if e and info["emitida_dia"] is None:
                    info["emitida_dia"] = f"{e.group(3)}-{e.group(2)}-{e.group(1)}"
            for linea in lineas_de_pagina(pagina):
                linea["pagina"] = n
                lineas.append(linea)
            # Líneas grises bajo cada fila de las tablas (de margen a margen): separan las filas aunque las celdas
            # salten de línea.
            info["separadores"][n] = sorted(l["top"] / MM for l in pagina.lines if abs(l["top"] - l["bottom"]) < 0.5
                                            and abs(l["x0"] / MM - 15) < 0.5 and abs(l["x1"] / MM - 195) < 0.5)
            for im in pagina.images:
                datos = im["stream"].get_rawdata()
                if datos[:2] != b"\xff\xd8":
                    raise ValueError("imagen que no es JPEG")
                ancho, alto = im["srcsize"]
                registro = {"pagina": n, "top": im["top"] / MM, "x0": im["x0"] / MM, "datos": datos, "ancho": ancho, "alto": alto}
                (info["firmas_img"] if (ancho, alto) == (750, 300) else info["fotos_img"]).append(registro)
    actual = None
    for linea in lineas:
        texto = linea["texto"].strip()
        if linea["size"] == 16.0 and texto in TITULOS and info["titulo"] is None:
            info["titulo"] = texto
            continue
        b = BANDA.match(texto) if linea["size"] == 9.0 and abs(linea["chars"][0]["x0"] - 18) < 1 else None
        if b:
            actual = b.group(2).split(" (")[0]
            info["secciones"][actual] = {"lineas": [], "n": int(b.group(3)) if b.group(3) else None, "numero": int(b.group(1))}
            info["orden"].append(actual)
            continue
        if actual:
            info["secciones"][actual]["lineas"].append(linea)
        else:
            raise ValueError(f"texto inesperado antes de las secciones: {texto!r}")
    if info["titulo"] is None:
        raise ValueError("no es un acta de la app de la v2.3 o posterior (título no reconocido)")
    return info


# Título de los PDF de la primera app (hasta la v2.2): otro formato, que no se puede reconstruir.
TITULO_ANTIGUO = "ACTA DE VISITA DE CAMPO"


def comprobar_formato(pdf):
    """Que el PDF es un acta de la app de la v2.3 en adelante, por el título de su primera página. Si no lo es, se dice
    por qué antes de leer sus secciones y sus imágenes."""
    lineas = pdf.pages[0].extract_text_lines(return_chars=True, strip=False) if pdf.pages else []
    textos = [texto_de([{"t": c["text"], "x0": c["x0"] / MM, "x1": c["x1"] / MM, "size": c["size"]}
                        for c in linea["chars"]]).strip() for linea in lineas]
    if any(t in TITULOS for t in textos):
        return
    if any(TITULO_ANTIGUO in t for t in textos):
        raise ValueError("es de una versión de la app anterior a la v2.3 («Acta de Visita de Campo»): "
                         "ese formato no se puede reconstruir")
    raise ValueError("no es un acta de la app: no lleva el título «Acta de Campo» ni «Acta de Visita de Inspección»")


def abrir_pdf(ruta):
    """El PDF abierto, o el motivo por el que no se puede abrir, dicho con claridad."""
    if not ruta.exists():
        comodin = any(c in ruta.name for c in "*?")
        raise ValueError("no existe ese archivo" + (": cmd no expande «*» ni «?»; en Windows, usa PowerShell "
                                                    "(ver el README)" if comodin else ""))
    if ruta.is_dir():
        raise ValueError("es una carpeta: hay que pasar sus PDF "
                         "(en PowerShell, (Get-ChildItem carpeta\\*.pdf).FullName)")
    with open(ruta, "rb") as f:
        cabecera = f.read(1024)
    if b"%PDF-" not in cabecera:
        raise ValueError("no es un PDF" + (" (el archivo está vacío)" if not cabecera else ""))
    try:
        lector = PdfReader(str(ruta))
    except Exception:
        raise ValueError("el PDF está dañado: no se puede abrir") from None
    if lector.is_encrypted:                 # con contraseña o solo contra cambios: sus fotos van cifradas
        raise ValueError("el PDF está protegido (cifrado): hace falta una copia sin protección")
    return lector


# ── Secciones ────────────────────────────────────────────────────────────────────────────────────

def datos_generales(sec):
    valores, ultima = {}, None
    for linea in sec["lineas"]:
        etiqueta = texto_de([c for c in linea["chars"] if c["x0"] < 64]).strip()
        valor = celda(linea["chars"], 64, 211)
        if etiqueta:
            if etiqueta not in ETIQUETAS:
                raise ValueError(f"dato desconocido {etiqueta!r}")
            ultima = etiqueta
            valores[ultima] = [valor] if valor else []
        elif ultima and valor:
            valores[ultima].append(valor)
    return {k: unir(v, ANCHO_VALOR) for k, v in valores.items()}


def tabla(sec, columnas, separadores):
    """Filas de una tabla (columnas: [(nombre, x_min, x_max, ancho_texto)]). Una fila acaba en la línea gris que la
    separa de la siguiente (o al cambiar de página)."""
    filas, previa = [], None
    for linea in sec["lineas"]:
        if linea["size"] != 8.5:                  # la cabecera de la tabla va en 7,5 pt
            continue
        celdas = {nombre: celda(linea["chars"], x0, x1) for nombre, x0, x1, _ in columnas}
        nueva = (previa is None or linea["pagina"] != previa["pagina"]
                 or any(previa["top"] < s < linea["top"] for s in separadores.get(linea["pagina"], [])))
        if nueva:
            filas.append({nombre: [c] if c else [] for nombre, c in celdas.items()})
        else:
            for nombre, c in celdas.items():
                if c:
                    filas[-1][nombre].append(c)
        previa = linea
    anchos = {nombre: ancho for nombre, _, _, ancho in columnas}
    return [{nombre: unir(partes, anchos[nombre]) for nombre, partes in f.items()} for f in filas]


def parrafo(sec, tam=9.0):
    lineas = [celda(l["chars"], 0, 211) for l in sec["lineas"] if l["size"] == tam]
    return unir([l for l in lineas if l], ANCHO_PARRAFO)


def fotos(sec, imagenes):
    """Fotos con su hora/GPS y comentario, en el orden del reportaje (2 por fila). Desde la v3.1.4, bajo la posición de
    cada foto va su UTM, que la app vuelve a calcular: se cuenta (sec["utm"]) y no se toma como pie."""
    metas, pies = [], []
    sec["utm"] = 0
    for linea in sec["lineas"]:
        if linea["size"] == 7.0 and not linea["texto"].strip().startswith("Foto"):
            for col, (x0, x1) in enumerate(((0, 104), (104, 211))):
                c = celda(linea["chars"], x0, x1)
                if c and c["texto"].startswith(UTM + " · "):
                    sec["utm"] += 1
                elif c:
                    metas.append({"pagina": linea["pagina"], "top": linea["top"], "col": col, "texto": c["texto"]})
        elif linea["size"] == 7.5:
            for col, (x0, x1) in enumerate(((0, 104), (104, 211))):
                c = celda(linea["chars"], x0, x1)
                if c:
                    pies.append({"pagina": linea["pagina"], "top": linea["top"], "col": col, "celda": c})
    imagenes = sorted(imagenes, key=lambda i: (i["pagina"], round(i["top"]), i["x0"]))
    metas.sort(key=lambda m: (m["pagina"], round(m["top"]), m["col"]))
    if not (len(imagenes) == len(metas) == sec["n"]):
        raise ValueError(f"fotos: {len(imagenes)} imágenes, {len(metas)} pies y {sec['n']} anunciadas")
    salida = []
    for i, (img, meta) in enumerate(zip(imagenes, metas)):
        siguiente = metas[i + 2] if i + 2 < len(metas) else None
        lineas_pie = [p["celda"] for p in pies if p["pagina"] == meta["pagina"] and p["col"] == meta["col"]
                      and p["top"] > meta["top"]
                      and not (siguiente and siguiente["pagina"] == meta["pagina"] and p["top"] > siguiente["top"])]
        comentario = unir(lineas_pie, ANCHO_PIE)
        salida.append({"img": img, "meta": meta["texto"], "comentario": "" if comentario == "(Sin comentario)" else comentario})
    return salida


def meta_foto(meta, fecha_visita):
    """«10:05 · 37.191826, -6.928519 (±8 m) (cámara)» → hora «AAAA-MM-DD HH:MM» y gps."""
    m = re.match(r"^(?:(\d{2})/(\d{2})/(\d{4}) )?(\d{2}:\d{2})? ?· (.*)$", meta)
    if not m:
        raise ValueError(f"pie de foto no reconocido: {meta!r}")
    d, mes, a, hora, donde = m.groups()
    dia = f"{a}-{mes}-{d}" if a else fecha_visita
    gps = None
    if donde != "sin GPS":
        g = re.match(r"^(-?\d+\.\d+), (-?\d+\.\d+)(?: \(±(\d+) m\))?( \(cámara\))?$", donde)
        if not g:
            raise ValueError(f"GPS de foto no reconocido: {donde!r}")
        gps = {"lat": g.group(1), "lng": g.group(2), "fuente": "camara" if g.group(4) else "movil"}
        if g.group(3):
            gps["acc"] = int(g.group(3))
    return (f"{dia} {hora}" if hora else ""), gps


def fecha_iso(ddmmaaaa):
    d, m, a = ddmmaaaa.split("/")
    return f"{a}-{m}-{d}"


def condiciones(texto):
    meteo, temperatura = [], ""
    for parte in [p.strip() for p in (texto or "").split(" · ") if p.strip()]:
        t = re.match(r"^(-?\d{1,2}(?:,\d)?) °C$", parte)
        if t:
            temperatura = t.group(1)
            continue
        for nombre in [n.strip() for n in parte.split(",")]:
            clave = next((v for k, v in METEO.items() if k.lower() == nombre.lower()), None)
            if not clave:
                raise ValueError(f"condición desconocida {nombre!r}")
            meteo.append(clave)
    orden = list(METEO.values())
    return {"meteo": sorted(meteo, key=orden.index), "temperatura": temperatura}


def objeto(texto, con_tipos, siempre_tipo):
    """«Inspección de Tajos de Obra · detalle» → (clave, detalle). Hasta la v3.0 el objeto era solo texto; desde la
    v3.1 lleva un tipo de la lista («Otro» si no empieza por ninguno). Con el formato anterior no se distingue un
    «Otro» de la v3.1 de un texto libre de la v3.0: queda como texto (el PDF sale igual)."""
    texto = "" if texto == "—" else texto
    if con_tipos:
        for nombre, clave in OBJETOS.items():
            if texto == nombre:
                return clave, ""
            if texto.startswith(nombre + " · "):
                return clave, texto[len(nombre) + 3:]
    return ("otro" if siempre_tipo and texto else ""), texto


# ── Acta en el formato de exportación ───────────────────────────────────────────────────────────

def iso_utc(momento):
    return momento.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def version_de_emision(info, hay_gps, sin_fotos):
    """La versión con la que se emitió (no la que generó el PDF: un acta se puede volver a compartir más tarde)."""
    creador = version(info["creador"]) or (2, 3)
    marcas_v3 = info["enlaces"] > 0 or "SEGUIMIENTO DE INDICACIONES ANTERIORES" in info["secciones"] or info["con_condiciones"]
    if info["titulo"] == "ACTA DE CAMPO":                  # «Acta de Campo»: desde la v3.1.1
        if info.get("con_utm"):                            # coordenadas UTM: desde la v3.1.4
            creador = max(creador, (3, 1, 4))
        elif info.get("con_coordenadas") and creador >= (3, 1, 4):
            creador = (3, 1, 3)                            # con coordenadas y sin UTM: emitida antes de la v3.1.4
        if info.get("empresa_tecnico") == EMPRESA_TECNICO:
            creador = max(creador, (3, 1, 3))
        elif creador >= (3, 1, 3):
            creador = (3, 1, 2)                            # emitida antes de la v3.1.3 y compartida después
        return ".".join(map(str, creador))
    if marcas_v3:
        return "3.0" if creador < (3, 1) else "3.1"         # enlaces, condiciones o seguimiento: v3.0 o v3.1
    if creador < (3, 0) or hay_gps:
        return None                                        # con GPS y sin enlaces: emitida con la v2.3
    if sin_fotos and info["secciones"]["FIRMAS"]["numero"] == 6:
        return None                                        # la v2.3 numeraba «6 · Firmas» aunque no hubiera fotos
    return "3.0"                                           # sin GPS ni marcas: el PDF sale igual


def esquema_de(version_emision):
    """Esquema del acta en el teléfono: 5 desde la v3.1.4 (su PDF lleva UTM y las versiones anteriores no deben importarla)."""
    return 5 if version_emision and tuple(int(x) for x in version_emision.split(".")) >= (3, 1, 4) else 4


def acta_desde_info(info):
    secc = info["secciones"]
    faltan = [s for s in ("DATOS GENERALES", "ASISTENTES", "OBSERVACIONES GENERALES", "INDICACIONES", "FIRMAS",
                          "CONTROL DE REVISIONES") if s not in secc]
    if faltan:
        raise ValueError(f"faltan secciones {faltan}")
    dg = datos_generales(secc["DATOS GENERALES"])
    info["con_condiciones"] = "CONDICIONES" in dg
    m = re.match(r"^(.*) · Rev\. (\d+)$", dg["Nº DE ACTA"])
    acta_num, revision = m.group(1), int(m.group(2))
    m = re.match(r"^(\d{2}/\d{2}/\d{4})(?: · (\d{2}:\d{2}))?$", dg["FECHA Y HORA"])
    fecha, hora = fecha_iso(m.group(1)), m.group(2) or ""
    ubicacion = VER_MAPA.sub("", dg["LOCALIZACIÓN GPS"]).strip()
    gps, sin_gps = None, {"activo": False, "referencia": "", "lat": "", "lng": ""}
    g = re.match(r"^Lat: (-?\d+\.\d+) +\| +Lng: (-?\d+\.\d+) +\| +Prec: ±(\d+) m$", ubicacion)
    if g:
        gps = {"lat": g.group(1), "lng": g.group(2), "acc": int(g.group(3)), "hora": None}
    else:
        s = re.match(r"^Sin cobertura GPS · Ref\.: (.*?)(?: · Coord\. manuales: (-?[\d.]+), (-?[\d.]+))?$", ubicacion, re.S)
        if not s:
            raise ValueError(f"ubicación no reconocida {ubicacion!r}")
        sin_gps = {"activo": True, "referencia": s.group(1), "lat": s.group(2) or "", "lng": s.group(3) or ""}

    filas = tabla(secc["ASISTENTES"], [("nombre", 0, 77, 58.8), ("empresa", 77, 122, 41.8), ("cargo", 122, 177, 51.8),
                                       ("firma", 177, 211, 18)], info["separadores"])
    tecnico = filas[0]
    if tecnico["empresa"] not in (EMPRESA, EMPRESA_TECNICO) or tecnico["nombre"] != dg["TÉCNICO"]:
        raise ValueError("la primera fila de asistentes no es el técnico")
    info["empresa_tecnico"] = tecnico["empresa"]

    obs = parrafo(secc["OBSERVACIONES GENERALES"])
    indicaciones = []
    lineas_ind = secc["INDICACIONES"]["lineas"]
    if not (len(lineas_ind) == 1 and lineas_ind[0]["texto"].strip() == "Sin indicaciones."):
        for i, f in enumerate(tabla(secc["INDICACIONES"], [("n", 0, 25, 6.8), ("texto", 25, 120, 91.8), ("responsable", 120, 167, 43.8),
                                                           ("plazo", 167, 211, 24.8)], info["separadores"]), 1):
            indicaciones.append({"id": f"ind-rec-{info['sha256'][:8]}-{i}", "texto": f["texto"],
                                 "responsable": "" if f["responsable"] == "—" else f["responsable"],
                                 "plazo": "" if f["plazo"] in ("", "—") else fecha_iso(f["plazo"])})

    seguimiento = []
    if "SEGUIMIENTO DE INDICACIONES ANTERIORES" in secc:
        sec = secc["SEGUIMIENTO DE INDICACIONES ANTERIORES"]
        sec = {**sec, "lineas": [l for l in sec["lineas"] if l["size"] == 8.5 or l["size"] == 7.5]}
        for i, f in enumerate(tabla(sec, [("origen", 0, 35, 16.8), ("texto", 35, 93, 54.8), ("responsable", 93, 125, 28.8),
                                          ("plazo", 125, 147, 18.8), ("estado", 147, 169, 18.8), ("comentario", 169, 211, 22.8)], info["separadores"]), 1):
            o = re.match(r"^(.*?)(?: Rev\. (\d+))?(?: · (\d+))?$", f["origen"])
            estado = {"Cumplida": "cumplida", "Anulada": "anulada"}.get(f["estado"], "pendiente")
            p = re.match(r"^(—|\d{2}/\d{2}/\d{4})(?: · nuevo (\d{2}/\d{2}/\d{4}))?$", f["plazo"])
            plazo = fecha_iso(p.group(1)) if p and p.group(1) != "—" else ""
            seguimiento.append({
                "id": f"seg-rec-{info['sha256'][:8]}-{i}", "_corto": o.group(1), "_rev": int(o.group(2) or 0),
                "origen": {"acta": o.group(1), "rev": int(o.group(2) or 0), "n": int(o.group(3) or 1), "fecha": ""},
                "texto": f["texto"], "responsable": "" if f["responsable"] == "—" else f["responsable"],
                "plazo": plazo, "plazoInicial": plazo, "estado": estado,
                "nuevoPlazo": fecha_iso(p.group(2)) if p and p.group(2) and estado == "pendiente" else "",
                "comentario": "" if f["comentario"] == "—" else f["comentario"],
            })

    lista_fotos = []
    if "REPORTAJE FOTOGRÁFICO" in secc:
        for i, f in enumerate(fotos(secc["REPORTAJE FOTOGRÁFICO"], info["fotos_img"]), 1):
            hora_foto, gps_foto = meta_foto(f["meta"], fecha)
            lista_fotos.append({"archivo": f"fotos/{i:02d}.jpg", "ancho": f["img"]["ancho"], "alto": f["img"]["alto"],
                                "comentario": f["comentario"], "hora": hora_foto,
                                "horaFuente": "camara" if gps_foto and gps_foto["fuente"] == "camara" else "movil",
                                "gps": gps_foto, "_datos": f["img"]["datos"]})
    elif info["fotos_img"]:
        raise ValueError("fotos sin sección de reportaje")

    firmas_img = sorted(info["firmas_img"], key=lambda i: (i["pagina"], round(i["top"]), i["x0"]))
    con_firma = [f for f in filas if f["firma"] == "Sí"]
    if len(firmas_img) != len(con_firma) or tecnico["firma"] != "Sí":
        raise ValueError(f"{len(firmas_img)} firmas para {len(con_firma)} firmantes")
    trazos = [vectorizar_firma(img["datos"]) for img in firmas_img]
    asistentes, firmas_asistentes, siguiente = [], {}, 1
    for j, f in enumerate(filas[1:], 1):
        aid = f"asis-rec-{info['sha256'][:8]}-{j}"
        firma = f["firma"] == "Sí"
        asistentes.append({"id": aid, "nombre": "" if f["nombre"] == "—" else f["nombre"],
                           "empresa": "" if f["empresa"] == "—" else f["empresa"],
                           "cargo": "" if f["cargo"] == "—" else f["cargo"], "firma": firma})
        if firma:
            firmas_asistentes[aid] = {"trazos": trazos[siguiente][0], "noFirma": False}
            siguiente += 1

    inicio_visita = dt.datetime.fromisoformat(f"{fecha}T{hora or '00:00'}:00").replace(tzinfo=info["zona"])
    # Emisión: el día es el del bloque de control; la hora, la de creación del PDF si es de ese día (si el PDF se volvió
    # a compartir otro día, solo consta el día: se toma la hora de la visita o las 12:00).
    dia = info["emitida_dia"] or info["creado"].date().isoformat()
    if info["creado"].date().isoformat() == dia:
        emitida = iso_utc(info["creado"])
    else:
        emitida = iso_utc(inicio_visita if dia == fecha else dt.datetime.fromisoformat(f"{dia}T12:00:00").replace(tzinfo=info["zona"]))
    revisiones = []
    for f in tabla(secc["CONTROL DE REVISIONES"], [("rev", 0, 29, 10.8), ("fecha", 29, 57, 24.8), ("motivo", 57, 211, 134.8)], info["separadores"]):
        rev, fecha_rev = int(f["rev"]), fecha_iso(f["fecha"])
        if rev == revision:
            momento = emitida
        else:      # las revisiones anteriores solo constan por su día
            base = inicio_visita if fecha_rev == fecha else dt.datetime.fromisoformat(f"{fecha_rev}T12:00:00").replace(tzinfo=info["zona"])
            momento = iso_utc(base)
        revisiones.append({"rev": rev, "fecha": momento, "motivo": f["motivo"]})
    if not revisiones or revisiones[-1]["rev"] != revision:
        raise ValueError(f"el control de revisiones no acaba en la Rev. {revision}")

    info["con_utm"] = UTM in dg or secc.get("REPORTAJE FOTOGRÁFICO", {}).get("utm", 0) > 0
    info["con_coordenadas"] = bool(gps) or bool(sin_gps["lat"]) or any(f["gps"] for f in lista_fotos)
    version_emision = version_de_emision(info, bool(gps) or any(f["gps"] for f in lista_fotos), not lista_fotos)
    clave_objeto, detalle = objeto(dg["OBJETO"], con_tipos=bool(version_emision), siempre_tipo=info["titulo"] == "ACTA DE CAMPO")
    acta = {
        "id": f"acta-rec-{info['sha256'][:12]}", "esquema": esquema_de(version_emision), "estado": "emitida", "emitida": emitida,
        "creada": iso_utc(inicio_visita), "modificada": emitida, "fase": 8, "revision": revision, "revisiones": revisiones,
        "datos": {"actaNum": acta_num, "numAuto": False, "tecnico": dg["TÉCNICO"],
                  "cargoTecnico": "" if tecnico["cargo"] == "Técnico" else tecnico["cargo"], "expediente": dg["EXPEDIENTE"],
                  "objeto": clave_objeto, "descripcion": detalle, "fecha": fecha, "hora": hora},
        "gps": gps, "sinGps": sin_gps, "condiciones": condiciones(dg.get("CONDICIONES", "")),
        "asistentes": asistentes, "observaciones": "" if obs == "Sin observaciones." else obs,
        "seguimiento": seguimiento, "seguimientoOrigen": None, "seguimientoNotas": [], "seguimientoGuardado": None,
        "indicaciones": indicaciones, "fotos": lista_fotos, "firma": trazos[0][0], "firmasAsistentes": firmas_asistentes,
    }
    if version_emision:
        acta["versionEmision"] = version_emision
    return acta, [t[1] for t in trazos]


def enlazar_lote(actas):
    """Seguimiento: mismos id que las indicaciones de origen del lote, fecha de origen y acta de la que se cargó."""
    for acta in actas:
        exp = acta["datos"]["expediente"].strip().lower()
        prefijo = acta["datos"]["actaNum"].lower().startswith(f"{exp}-") if exp else False
        for s in acta["seguimiento"]:
            corto, rev = s.pop("_corto"), s.pop("_rev")
            candidatos = [a for a in actas if a is not acta and a["datos"]["expediente"].strip().lower() == exp and a["revision"] == rev
                          and a["datos"]["actaNum"].lower() in (corto.lower(), f"{exp}-{corto.lower()}")]
            origen = candidatos[0] if candidatos else None
            if origen:
                s["origen"]["acta"] = origen["datos"]["actaNum"]
                s["origen"]["fecha"] = origen["datos"]["fecha"]
                if s["origen"]["n"] <= len(origen["indicaciones"]):
                    s["id"] = origen["indicaciones"][s["origen"]["n"] - 1]["id"]
            elif prefijo and corto != "—":
                s["origen"]["acta"] = f"{acta['datos']['expediente']}-{corto}"
        if acta["seguimiento"]:
            anteriores = [a for a in actas if a is not acta and a["datos"]["expediente"].strip().lower() == exp
                          and a["datos"]["actaNum"] != acta["datos"]["actaNum"]
                          and (a["datos"]["fecha"], a["datos"]["hora"]) <= (acta["datos"]["fecha"], acta["datos"]["hora"])]
            if anteriores:
                f = max(anteriores, key=lambda a: (a["datos"]["fecha"], a["datos"]["hora"], a["emitida"]))
                acta["seguimientoOrigen"] = {"expediente": f["datos"]["expediente"], "actaId": f["id"], "acta": f["datos"]["actaNum"],
                                             "rev": f["revision"], "fecha": f["datos"]["fecha"], "hora": f["datos"]["hora"]}
    # Las revisiones del lote: cada una corrige a la anterior del mismo número, que queda sustituida.
    for acta in actas:
        anterior = [a for a in actas if a["datos"]["actaNum"] == acta["datos"]["actaNum"]
                    and a["datos"]["expediente"] == acta["datos"]["expediente"] and a["revision"] == acta["revision"] - 1]
        if anterior:
            acta["corrigeA"] = anterior[0]["id"]
            anterior[0]["sustituidaPor"], anterior[0]["sustituidaRev"] = acta["id"], acta["revision"]


# ── Firma: de la imagen JPEG (750 × 300) a trazos ────────────────────────────────────────────────

def vecinos(p, conjunto):
    y, x = p
    return [(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy or dx) and (y + dy, x + dx) in conjunto]


def trazar(esqueleto):
    puntos = set(zip(*np.nonzero(esqueleto)))
    grado = {p: len(vecinos(p, puntos)) for p in puntos}
    nodos = {p for p, g in grado.items() if g != 2}
    usadas, caminos = set(), []

    def recorrer(inicio, siguiente):
        camino = [inicio, siguiente]
        usadas.add(frozenset((inicio, siguiente)))
        actual, previo = siguiente, inicio
        while actual not in nodos:
            opciones = [v for v in vecinos(actual, puntos) if v != previo and frozenset((actual, v)) not in usadas]
            if not opciones:
                break
            nuevo = opciones[0]
            usadas.add(frozenset((actual, nuevo)))
            camino.append(nuevo)
            previo, actual = actual, nuevo
            if actual == inicio:
                break
        return camino

    for nodo in sorted(nodos):
        if grado[nodo] == 0:
            caminos.append([nodo])
            continue
        for v in vecinos(nodo, puntos):
            if frozenset((nodo, v)) not in usadas:
                caminos.append(recorrer(nodo, v))
    for p in sorted(puntos):                       # bucles cerrados, sin nodos
        for v in vecinos(p, puntos):
            if frozenset((p, v)) not in usadas:
                caminos.append(recorrer(p, v))
    return caminos


def simplificar(puntos, tolerancia=0.6):
    """Douglas-Peucker."""
    if len(puntos) < 3:
        return puntos
    a, b = np.array(puntos[0], float), np.array(puntos[-1], float)
    ab, pts = b - a, np.array(puntos, float)
    largo = np.hypot(*ab)
    rel = pts - a
    dist = np.hypot(rel[:, 0], rel[:, 1]) if largo == 0 else np.abs(ab[0] * rel[:, 1] - ab[1] * rel[:, 0]) / largo
    i = int(np.argmax(dist))
    if dist[i] <= tolerancia:
        return [puntos[0], puntos[-1]]
    return simplificar(puntos[:i + 1], tolerancia)[:-1] + simplificar(puntos[i:], tolerancia)


def vectorizar_firma(datos):
    gris = np.asarray(Image.open(io.BytesIO(datos)).convert("L"), dtype=np.uint8)
    alto, ancho = gris.shape
    tinta = gris < 140
    etiquetas, n = ndimage.label(tinta, structure=np.ones((3, 3)))
    if n:
        for i, t in enumerate(ndimage.sum(tinta, etiquetas, range(1, n + 1)), 1):
            if t < 12:                                 # motas del JPEG
                tinta[etiquetas == i] = False
    esqueleto = skeletonize(tinta)
    grosor = float(2 * np.median(ndimage.distance_transform_edt(tinta)[esqueleto])) if esqueleto.any() else 0
    caminos = [simplificar([(int(x), int(y)) for y, x in c]) for c in trazar(esqueleto)]
    xs = [p[0] for c in caminos for p in c]
    ys = [p[1] for c in caminos for p in c]
    # La app encaja los trazos en 750 × 300 con 8 unidades de margen y escala k ≤ 3 (firmaComoImagen): se deshace esa
    # escala para que, al volver a dibujarlos, salgan del mismo tamaño y grosor (2,5 · k).
    k = max(0.5, min(3.0, (ancho - (max(xs) - min(xs))) / 16, (alto - (max(ys) - min(ys))) / 16))
    trazos = [{"refW": round(ancho / k, 3), "refH": round(alto / k, 3), "puntos": [[round(x / k, 2), round(y / k, 2)] for x, y in c]}
              for c in caminos if c]
    return trazos, {"k": round(k, 3), "grosor_px": round(grosor, 2), "grosor_esperado": round(max(2, 2.5 * k), 2), "trazos": len(trazos)}


# ── ZIP de importación ───────────────────────────────────────────────────────────────────────────

def nombre_seguro(t):
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-zA-Z0-9-]+", "_", t))[:80]


def anadir_al_zip(z, acta, info, carpeta):
    fotos = []
    for f in acta["fotos"]:
        z.writestr(zipfile.ZipInfo(f"{carpeta}/{f['archivo']}", date_time=(2026, 1, 1, 0, 0, 0)), f["_datos"])
        fotos.append({k: v for k, v in f.items() if k != "_datos"})
    ficha = {"formato": "tbc-acta", "version": 1, "app": ".".join(map(str, version(info["creador"]) or (2, 3))),
             "exportada": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
             "reconstruida": {"desde": "PDF", "archivo": info["archivo"], "sha256": info["sha256"], "creadoPor": info["creador"],
                              "nota": "Datos y fotos tomados del PDF; las firmas se han redibujado desde sus imágenes."},
             "acta": {**acta, "fotos": fotos}}
    z.writestr(zipfile.ZipInfo(f"{carpeta}/acta.json", date_time=(2026, 1, 1, 0, 0, 0)),
               json.dumps(ficha, ensure_ascii=False, indent=1), compress_type=zipfile.ZIP_DEFLATED)


def leeme(lote):
    lineas = ["Actas de campo de TEAMBIMCIVIL reconstruidas desde sus PDF.", "",
              "Cada carpeta es un acta: acta.json (datos, asistentes, acuerdos y firmas) y fotos/ (las fotografías tal",
              "como van en el PDF). Las firmas se han redibujado desde sus imágenes. El PDF original sigue siendo el oficial.",
              "Para recuperarlas: abre la app, pulsa Mis actas > Importar y elige este archivo .zip.", "", "Actas:"]
    lineas += [f"  - {a['datos']['actaNum']} Rev. {a['revision']} · {a['datos']['expediente']} · desde {i['archivo']} "
               f"(sha256 {i['sha256'][:12]})" for a, i in lote]
    return "﻿" + "\r\n".join(lineas + ["", "App: https://devteambimcivil.github.io/TBC-APP-REPORTAJE-CAMPO/"]) + "\r\n"


def carpeta_de(acta, usadas):
    base = f"{nombre_seguro(acta['datos']['actaNum']) or 'sin-numero'}_Rev{acta['revision']}"
    nombre, n = base, 2
    while nombre.lower() in usadas:
        nombre, n = f"{base}_{n}", n + 1
    usadas.add(nombre.lower())
    return nombre


# ── PDF repetidos ───────────────────────────────────────────────────────────────────────────────

def creado_el(lector):
    """Fecha de creación del PDF (la pone la app al generarlo), o None si no la lleva."""
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:([+-])(\d{2})'(\d{2})'|Z)?",
                 str((lector.metadata or {}).get("/CreationDate", "")))
    if not m:
        return None
    a, mes, d, h, mi, s, signo, th, tm = m.groups()
    zona = dt.timezone((1 if signo != "-" else -1) * dt.timedelta(hours=int(th or 0), minutes=int(tm or 0)))
    return dt.datetime(int(a), int(mes), int(d), int(h), int(mi), int(s), tzinfo=zona)


def contenido_de(datos):
    """Huella de lo que se ve en el PDF: el texto de cada página y las fotos (sus bytes). Dos PDF de la misma acta
    generados en momentos distintos (al compartirla otra vez) solo se diferencian en la fecha de creación y el
    identificador del archivo. No cuentan las firmas, que la app vuelve a dibujar, ni el texto a la altura de las fotos:
    su etiqueta y, en la v3.2, el de sus anotaciones («Foto n · anotada»; su texto puede salirse de la foto por los
    lados), que la reconstrucción no recupera. Así, el PDF que se rehace desde un acta reconstruida es la misma acta."""
    huella = hashlib.sha256()
    with pdfplumber.open(io.BytesIO(datos)) as pdf:
        for pagina in pdf.pages:
            fotos = [im for im in pagina.images if tuple(im["srcsize"]) != (750, 300)]

            def fuera_de_las_fotos(obj, fotos=fotos):
                return obj.get("object_type") != "char" or not any(f["top"] - 3 * MM <= obj["top"] < f["bottom"] for f in fotos)

            huella.update((pagina.filter(fuera_de_las_fotos).extract_text() or "").encode("utf-8") + b"\n\f\n")
            for im in fotos:
                huella.update(hashlib.sha256(im["stream"].get_rawdata()).digest())
    return huella.hexdigest()


def sin_repetidos(rutas):
    """Quita de la lista los PDF repetidos: el mismo archivo (o la misma ruta dos veces) o la misma acta en otro PDF
    (misma huella de contenido). De cada grupo queda el más antiguo, el más cercano a la emisión; entre copias del mismo
    archivo, la de nombre más corto (la original y no la «(1)»). Se avisa de los demás. Devuelve las rutas que quedan,
    en su orden, y cuántas se quitan."""
    leidos = []
    for orden, ruta in enumerate(rutas):
        d = {"ruta": ruta, "orden": orden, "archivo": None, "contenido": None, "creado": None}
        try:
            datos = ruta.read_bytes()
            d["archivo"] = hashlib.sha256(datos).hexdigest()
            d["creado"] = creado_el(PdfReader(io.BytesIO(datos)))
            d["contenido"] = contenido_de(datos)
        except Exception:                 # un PDF que no se puede leer sigue en la lista: al leerlo se dirá por qué
            pass
        d["grupo"] = d["contenido"] or d["archivo"] or f"sin leer {orden}"
        leidos.append(d)
    nombres = [d["ruta"].name for d in leidos]
    try:
        comun = Path(os.path.commonpath([str(d["ruta"].resolve().parent) for d in leidos])) if leidos else None
    except ValueError:                    # en Windows, rutas de unidades distintas
        comun = None

    def nombre(ruta):                     # con la carpeta si ese nombre de archivo se repite en la lista
        if nombres.count(ruta.name) > 1 and comun is not None:
            try:
                return str(ruta.resolve().relative_to(comun))
            except ValueError:
                return str(ruta)
        return ruta.name

    lejano = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    primero = {}
    for d in sorted(leidos, key=lambda x: (x["creado"] or lejano, len(x["ruta"].name), x["orden"])):
        primero.setdefault(d["grupo"], d)
    quedan, quitados = [], 0
    for d in leidos:
        p = primero[d["grupo"]]
        if p is d:
            quedan.append(d["ruta"])
            continue
        quitados += 1
        if d["ruta"].resolve() == p["ruta"].resolve():
            motivo = "está dos veces en la lista"
        elif d["archivo"] == p["archivo"]:
            motivo = f"es una copia de {nombre(p['ruta'])} (el mismo archivo)"
        else:
            motivo = f"es la misma acta que {nombre(p['ruta'])} (mismo texto y mismas fotos), el PDF más antiguo"
        print(f"REP  {nombre(d['ruta'])}: {motivo}: se reconstruye una sola vez")
    return quedan, quitados


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    salida = Path(sys.argv[1])
    salida.mkdir(parents=True, exist_ok=True)
    lote, fallos = [], 0
    rutas, repetidos = sin_repetidos([Path(a) for a in sys.argv[2:]])
    for ruta in rutas:
        try:
            info = leer_pdf(ruta)
            acta, firmas = acta_desde_info(info)
        except Exception as e:                      # un PDF que no se puede leer no impide los demás
            fallos += 1
            print(f"NO   {ruta.name}: {e}")
            continue
        lote.append((acta, info))
        print(f"OK   {ruta.name}: acta {acta['datos']['actaNum']} Rev. {acta['revision']} · {acta['datos']['expediente']} · "
              f"{len(acta['fotos'])} foto(s) · {len(acta['indicaciones'])} indicación(es) · {len(acta['seguimiento'])} en seguimiento · "
              f"emitida con la v{acta.get('versionEmision', '2.3')} · firma k={firmas[0]['k']}")
    enlazar_lote([a for a, _ in lote])
    lote.sort(key=lambda r: (r[0]["datos"]["expediente"], r[0]["datos"]["fecha"], r[0]["datos"]["hora"], r[0]["revision"]))
    usadas = set()
    with zipfile.ZipFile(salida / "Actas_reconstruidas.zip", "w") as todas:
        for acta, info in lote:
            carpeta = carpeta_de(acta, usadas)
            anadir_al_zip(todas, acta, info, carpeta)
            with zipfile.ZipFile(salida / f"Acta_{carpeta}_reconstruida.zip", "w") as una:
                anadir_al_zip(una, acta, info, carpeta)
                una.writestr("LEEME.txt", leeme([(acta, info)]))
        todas.writestr("LEEME.txt", leeme(lote))
    print(f"{len(lote)} acta(s) reconstruida(s) en {salida}"
          + (f" · {repetidos} PDF repetido(s), sin duplicar" if repetidos else "")
          + (f" · {fallos} PDF sin reconstruir" if fallos else ""))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
