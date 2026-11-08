"""Draws the app logo and writes assets/logo.png and assets/icon.ico.

Usage: .venv\\Scripts\\python tools\\make_icons.py

The logo is a yellow rounded square with a bold "Hi" (as in Highlight) and an arrow
cursor. Each icon size is drawn separately instead of shrinking one big image, so the
16 px tray version stays crisp.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath,
                           QPen, QPolygonF)

ROOT = Path(__file__).resolve().parent.parent
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
YELLOW = QColor("#FFE234")
INK = QColor("#111111")

# Arrow cursor outline, as fractions of its height, tip at (0, 0).
CURSOR = [(0, 0), (0, 0.78), (0.2, 0.6), (0.34, 0.92), (0.47, 0.86), (0.33, 0.55), (0.58, 0.55)]


def draw_logo(p: QPainter, n: int) -> None:
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, n, n), n * 0.22, n * 0.22)
    p.fillPath(tile, YELLOW)

    font = QFont("Segoe UI", 1, QFont.Black)
    font.setPixelSize(int(n * 0.5))
    p.setFont(font)
    p.setPen(INK)
    p.drawText(QRectF(0, n * 0.04, n * 0.8, n * 0.7), Qt.AlignCenter, "Hi")

    x, y, s = n * 0.58, n * 0.48, n * 0.46
    arrow = QPainterPath()
    arrow.addPolygon(QPolygonF([QPointF(x + cx * s, y + cy * s) for cx, cy in CURSOR]))
    arrow.closeSubpath()
    p.setPen(QPen(QColor("white"), max(1.0, s * 0.07), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(INK)
    p.drawPath(arrow)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    draw_logo(p, size)
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def write_ico(images: list[QImage], path: Path) -> None:
    """Writes a multi-size .ico whose entries are PNG-compressed (supported since Windows Vista)."""
    blobs = [png_bytes(im) for im in images]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for im, blob in zip(images, blobs):
        dim = 0 if im.width() >= 256 else im.width()  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main() -> None:
    QGuiApplication(sys.argv[:1])
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    render(1024).save(str(assets / "logo.png"))
    write_ico([render(s) for s in ICO_SIZES], assets / "icon.ico")
    print(f"wrote {assets / 'logo.png'} and {assets / 'icon.ico'}")


if __name__ == "__main__":
    main()
