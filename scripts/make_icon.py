"""Render the Scripture cross icon to assets/app.ico.

Windows installers and PyInstaller want an .ico. Qt's ICO *read* plugin is
reliable, but write support is not guaranteed, so this renders the same
gold-cross-on-dark art that the tray icon uses, encodes it as a single 256x256
PNG, and wraps that PNG in the small ICO container format (which Windows
accepts). Re-run with the repo root as CWD whenever the icon art changes.

Usage:  python scripts/make_icon.py
"""

import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QImageWriter, QPainter

SIZE = 256
OUT = Path(__file__).resolve().parent.parent / "assets" / "app.ico"


def draw_cross(painter: QPainter, size: float) -> None:
    """A Latin cross centered in the square, with a long lower arm."""
    painter.setBrush(QColor("#f5c542"))
    r = size / 22
    painter.drawRoundedRect(
        size * 0.43, size * 0.15, size * 0.14, size * 0.62, r, r
    )  # vertical beam
    painter.drawRoundedRect(
        size * 0.32, size * 0.30, size * 0.36, size * 0.14, r, r
    )  # horizontal beam


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

    draw_cross(painter, SIZE)
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