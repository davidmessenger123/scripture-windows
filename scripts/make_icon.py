"""Render the Scripture star icon to assets/app.ico.

Windows installers and PyInstaller want an .ico. Qt's ICO *read* plugin is
reliable, but write support is not guaranteed, so this renders the same
frameless-star art that the tray icon uses, encodes it as a single 256x256
PNG, and wraps that PNG in the small ICO container format (which Windows
accepts). Re-run with the repo root as CWD whenever the icon art changes.

Usage:  python scripts/make_icon.py
"""

import math
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QImageWriter, QPainter, QPolygonF

SIZE = 256
OUT = Path(__file__).resolve().parent.parent / "assets" / "app.ico"


def render_png() -> bytes:
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0d1b2a"))
    inset = SIZE * 4 / 64
    radius = SIZE * 12 / 64
    painter.drawRoundedRect(inset, inset, SIZE - 2 * inset, SIZE - 2 * inset, radius, radius)

    cx, cy = SIZE / 2, SIZE * 34 / 64
    outer, inner = SIZE * 20 / 64, SIZE * 9 / 64
    points = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = math.radians(-90.0 + i * 36.0)
        points.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    painter.setBrush(QColor("#f5c542"))
    painter.drawPolygon(QPolygonF(points))
    painter.end()

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(buf, b"png")
    ok = writer.write(img)
    buf.close()
    if not ok:
        raise RuntimeError("could not encode PNG: %s" % writer.errorString())
    return bytes(ba.data())


def wrap_ico(png: bytes) -> bytes:
    header = b"\x00\x00" + b"\x01\x00" + b"\x01\x00"
    entry = (bytes([0, 0])  # 256x256 -> 0
             + b"\x00"      # palette
             + b"\x00"      # reserved
             + b"\x01\x00"  # planes
             + b"\x20\x00"  # 32 bpp
             + len(png).to_bytes(4, "little")
             + (22).to_bytes(4, "little"))
    return header + entry + png


def main() -> int:
    png = render_png()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(wrap_ico(png))
    print("wrote %s (%d bytes)" % (OUT, OUT.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())