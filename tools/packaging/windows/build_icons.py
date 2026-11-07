"""!
@file packaging/windows/build_icons.py
@brief Genera le icone del portable e dell'interfaccia web dal marchio SVG condiviso.

Rasterizza `anonymizer.svg` con Qt in modalità offscreen nei PNG a 256 e 512
pixel e ne ricava l'icona Windows multi-risoluzione `anonymizer.ico`.
"""

import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

## Cartella delle risorse statiche web, sorgente e destinazione delle icone.
STATIC = Path(__file__).resolve().parents[3] / "src" / "anonymizer" / "web" / "static"
## Risoluzioni incluse nel file ICO.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main():
    """!
    @brief Rasterizza l'SVG e scrive i PNG e l'ICO nella cartella statica.
    @throws ValueError Se l'SVG di origine non è valido.
    @throws OSError Se un PNG non può essere scritto.
    """
    application = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(STATIC / "anonymizer.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid source SVG")
    for size in (256, 512):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            renderer.render(painter)
        finally:
            painter.end()
        if not image.save(str(STATIC / f"anonymizer-{size}.png")):
            raise OSError("Unable to write PNG icon")
    with Image.open(STATIC / "anonymizer-512.png") as image:
        image.save(STATIC / "anonymizer.ico", format="ICO", sizes=[(size, size) for size in SIZES])
    application.processEvents()


if __name__ == "__main__":
    main()
