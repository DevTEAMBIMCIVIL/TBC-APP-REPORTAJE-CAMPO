"""Fotos de prueba.

· Horizontal, vertical y cuadrada con un círculo perfecto y una cuadrícula: si el PDF deforma
  la foto, el círculo sale ovalado.
· Una foto con datos EXIF de cámara (fecha 21/10/2026 18:05 y GPS de Sevilla) para comprobar
  que la app lee la hora y la posición de la propia foto.
· Una foto con la fecha de la cámara (22/10/2026 08:15) y sin GPS, como llegan las de la galería del teléfono
  (Android y el iPhone quitan el GPS al cargarlas desde el navegador).
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont
from PIL.TiffImagePlugin import IFDRational

ESPECIFICACIONES = [  # nombre, ancho, alto, color de fondo
    ("foto_horizontal.jpg", 4032, 3024, (70, 110, 160)),
    ("foto_vertical.jpg", 3024, 4032, (150, 90, 60)),
    ("foto_cuadrada.jpg", 3000, 3000, (60, 130, 80)),
]
EXIF_FECHA = "2026:10:21 18:05:00"
EXIF_FECHA_GALERIA = "2026:10:22 08:15:00"
EXIF_GPS = {1: "N", 2: (IFDRational(37, 1), IFDRational(23, 1), IFDRational(21156, 1000)),
            3: "W", 4: (IFDRational(5, 1), IFDRational(59, 1), IFDRational(4056, 1000))}   # 37.389210, -5.984460


def _fuente():
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", 220)
    except OSError:
        return ImageFont.load_default()


def _dibujar(ancho, alto, color):
    img = Image.new("RGB", (ancho, alto), color)
    dibujo = ImageDraw.Draw(img)
    for x in range(0, ancho, 300):
        dibujo.line([(x, 0), (x, alto)], fill=(230, 230, 230), width=6)
    for y in range(0, alto, 300):
        dibujo.line([(0, y), (ancho, y)], fill=(230, 230, 230), width=6)
    r, cx, cy = min(ancho, alto) * 0.38, ancho / 2, alto / 2
    dibujo.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 0), width=40)
    dibujo.text((80, 80), f"{ancho}x{alto}", fill=(255, 255, 255), font=_fuente())
    return img


def generar(carpeta: pathlib.Path) -> list[pathlib.Path]:
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for nombre, ancho, alto, color in ESPECIFICACIONES:
        ruta = carpeta / nombre
        if not ruta.exists():
            _dibujar(ancho, alto, color).save(ruta, quality=90)
        rutas.append(ruta)
    return rutas


def generar_con_exif(carpeta: pathlib.Path) -> pathlib.Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "foto_exif.jpg"
    if not ruta.exists():
        exif = Image.Exif()
        exif[0x0132] = EXIF_FECHA
        exif.get_ifd(0x8769)[0x9003] = EXIF_FECHA
        exif.get_ifd(0x8825).update(EXIF_GPS)
        _dibujar(2000, 1500, (120, 60, 140)).save(ruta, quality=90, exif=exif)
    return ruta


def generar_galeria_sin_gps(carpeta: pathlib.Path) -> pathlib.Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "foto_galeria_sin_gps.jpg"
    if not ruta.exists():
        exif = Image.Exif()
        exif[0x0132] = EXIF_FECHA_GALERIA
        exif.get_ifd(0x8769)[0x9003] = EXIF_FECHA_GALERIA
        _dibujar(1600, 1200, (40, 120, 150)).save(ruta, quality=90, exif=exif)
    return ruta


if __name__ == "__main__":
    destino = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent / "salida" / "fotos"
    for ruta in generar(destino) + [generar_con_exif(destino), generar_galeria_sin_gps(destino)]:
        print(ruta)
