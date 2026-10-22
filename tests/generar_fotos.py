"""Fotos de prueba con un círculo perfecto y una cuadrícula: si el PDF deforma la foto, el círculo sale ovalado."""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

ESPECIFICACIONES = [  # nombre, ancho, alto, color de fondo
    ("foto_horizontal.jpg", 4032, 3024, (70, 110, 160)),
    ("foto_vertical.jpg", 3024, 4032, (150, 90, 60)),
    ("foto_cuadrada.jpg", 3000, 3000, (60, 130, 80)),
]


def generar(carpeta: pathlib.Path) -> list[pathlib.Path]:
    carpeta.mkdir(parents=True, exist_ok=True)
    try:
        fuente = ImageFont.truetype("DejaVuSans-Bold.ttf", 220)
    except OSError:
        fuente = ImageFont.load_default()
    rutas = []
    for nombre, ancho, alto, color in ESPECIFICACIONES:
        ruta = carpeta / nombre
        if not ruta.exists():
            img = Image.new("RGB", (ancho, alto), color)
            dibujo = ImageDraw.Draw(img)
            for x in range(0, ancho, 300):
                dibujo.line([(x, 0), (x, alto)], fill=(230, 230, 230), width=6)
            for y in range(0, alto, 300):
                dibujo.line([(0, y), (ancho, y)], fill=(230, 230, 230), width=6)
            r, cx, cy = min(ancho, alto) * 0.38, ancho / 2, alto / 2
            dibujo.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 0), width=40)
            dibujo.text((80, 80), f"{ancho}x{alto}", fill=(255, 255, 255), font=fuente)
            img.save(ruta, quality=90)
        rutas.append(ruta)
    return rutas


if __name__ == "__main__":
    destino = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent / "salida" / "fotos"
    for ruta in generar(destino):
        print(ruta)
