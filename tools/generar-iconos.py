"""Genera los iconos de la app instalable (carpeta icons/) a partir del logotipo de la cabecera.

Uso:
    pip install pillow
    python tools/generar-iconos.py
"""
import pathlib

from PIL import Image, ImageDraw

DESTINO = pathlib.Path(__file__).resolve().parent.parent / "icons"
FONDO = (26, 26, 26)          # --negro
ROJO, GRIS = (204, 34, 34), (136, 136, 136)
# Rectángulos del logotipo (viewBox 36×36 del SVG de la cabecera): x, y, ancho, alto, color
LOGO = [(4, 4, 10, 3, ROJO), (8, 4, 3, 12, ROJO), (16, 4, 3, 12, GRIS), (16, 13, 10, 3, GRIS),
        (4, 18, 10, 3, GRIS), (4, 18, 3, 10, GRIS), (18, 18, 10, 3, ROJO), (25, 18, 3, 10, ROJO)]
X0, Y0, LADO = 4, 4, 24       # el dibujo ocupa de 4 a 28 en ambos ejes

ICONOS = {  # archivo: (lado en px, fracción del icono que ocupa el logotipo)
    "icono-192.png": (192, 0.62),
    "icono-512.png": (512, 0.62),
    "icono-maskable-512.png": (512, 0.46),   # dentro de la zona segura del 80 %
    "apple-touch-icon.png": (180, 0.60),
}


def dibujar(lado: int, fraccion: float) -> Image.Image:
    escala = 4                                  # se dibuja a 4× y se reduce: bordes suaves
    grande = lado * escala
    img = Image.new("RGB", (grande, grande), FONDO)
    dibujo = ImageDraw.Draw(img)
    k = grande * fraccion / LADO
    margen = (grande - LADO * k) / 2
    for x, y, w, h, color in LOGO:
        x1, y1 = margen + (x - X0) * k, margen + (y - Y0) * k
        dibujo.rectangle([x1, y1, x1 + w * k - 1, y1 + h * k - 1], fill=color)
    return img.resize((lado, lado), Image.LANCZOS)


if __name__ == "__main__":
    DESTINO.mkdir(exist_ok=True)
    for nombre, (lado, fraccion) in ICONOS.items():
        dibujar(lado, fraccion).save(DESTINO / nombre, optimize=True)
        print(DESTINO / nombre)
