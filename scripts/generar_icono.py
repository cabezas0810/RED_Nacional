#!/usr/bin/env python3
"""Genera el icono de la integración en custom_components/red_movilidad/brand/.

Diseño original: el frente de un bus con su letrero de recorrido, sobre un
cuadrado redondeado. No usa el logo de RED, de Red Regional ni de Home
Assistant (las reglas de los iconos de HA lo prohíben).

Necesita Pillow:  python3 -m pip install pillow
Uso:              python3 scripts/generar_icono.py

Se dibuja a 2048 px y se reduce, para que los bordes salgan suaves.
"""

import pathlib

from PIL import Image, ImageDraw

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "custom_components" / "red_movilidad" / "brand"

# Colores: se cambian aquí y se vuelve a ejecutar el script.
FONDO = (14, 92, 110)          # petróleo
FONDO_OSCURO = (8, 60, 72)     # parabrisas y ruedas
CARROCERIA = (255, 255, 255)
ACENTO = (255, 196, 64)        # letrero y focos

LADO = 2048


def r(valor):
    """Coordenadas pensadas sobre 1000 px, escaladas al lienzo real."""
    return round(valor * LADO / 1000)


def dibujar():
    imagen = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    d = ImageDraw.Draw(imagen)

    # Fondo: cuadrado redondeado de borde a borde (sin márgenes vacíos).
    d.rounded_rectangle((0, 0, LADO - 1, LADO - 1), radius=r(220), fill=FONDO)

    # Ruedas, asomando bajo la carrocería.
    for x in (275, 625):
        d.rounded_rectangle((r(x), r(760), r(x + 100), r(860)), radius=r(30), fill=FONDO_OSCURO)

    # Espejos laterales.
    for x0, x1 in ((140, 205), (795, 860)):
        d.rounded_rectangle((r(x0), r(300), r(x1), r(430)), radius=r(28), fill=CARROCERIA)

    # Carrocería.
    d.rounded_rectangle((r(200), r(150), r(800), r(800)), radius=r(90), fill=CARROCERIA)

    # Letrero de recorrido sobre el parabrisas.
    d.rounded_rectangle((r(270), r(205), r(730), r(275)), radius=r(22), fill=ACENTO)

    # Parabrisas.
    d.rounded_rectangle((r(260), r(305), r(740), r(560)), radius=r(40), fill=FONDO_OSCURO)

    # Focos.
    for cx in (320, 680):
        d.ellipse((r(cx - 45), r(625), r(cx + 45), r(715)), fill=ACENTO)

    # Parrilla.
    d.rounded_rectangle((r(420), r(650), r(580), r(690)), radius=r(18), fill=FONDO_OSCURO)

    return imagen


def main():
    DESTINO.mkdir(parents=True, exist_ok=True)
    grande = dibujar()
    for nombre, lado in (("icon.png", 256), ("icon@2x.png", 512)):
        ruta = DESTINO / nombre
        grande.resize((lado, lado), Image.Resampling.LANCZOS).save(ruta, optimize=True)
        print(f"{ruta.relative_to(RAIZ)}  {lado}x{lado}  {ruta.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
