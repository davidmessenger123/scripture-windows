"""Render the Scripture cross icon to assets/app.icns.

macOS .app bundles and `iconutil` want an .icns (an .iconset folder plus the
Apple iconutil tool). Windows uses the sibling assets/app.ico, produced by
make_icon.py — this script draws the same gold-cross-on-dark art at every
icon size macOS asks for, writes the iconset, and runs `iconutil -c icns`.

The PyInstaller macOS spec references the output path. Run from the repo root,
on macOS (this only needs to run in CI / on a Mac):

    python scripts/make_icns.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QImageWriter, QPainter

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICONSET = ASSETS / "app.iconset"
ICNS = ASSETS / "app.icns"

SIZES = [
    (16, "icon_16x16"),
    (32, "icon_32x32"),
    (128, "icon_128x128"),
    (256, "icon_256x256"),
    (512, "icon_512x512"),
]


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


def render_png(size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0d1b2a"))
    inset = size * 4 / 64
    radius = size * 12 / 64
    painter.drawRoundedRect(inset, inset, size - 2 * inset, size - 2 * inset, radius, radius)

    draw_cross(painter, size)
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


def write_iconset() -> None:
    shutil.rmtree(ICONSET, ignore_errors=True)
    ICONSET.mkdir(parents=True)
    for base, tpl in SIZES:
        for scale, tag in ((1, ""), (2, "@2x")):
            px = base * scale
            (ICONSET / ("%s%s.png" % (tpl, tag))).write_bytes(render_png(px))


def run_iconutil() -> None:
    iconutil = "/usr/bin/iconutil"
    if not os.path.isfile(iconutil) or not os.access(iconutil, os.X_OK):
        raise RuntimeError(
            "iconutil not found; run this on macOS (CI runner or a Mac)"
        )
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for key in ("HOME", "TMPDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    subprocess.run(
        [iconutil, "-c", "icns", str(ICONSET), "-o", str(ICNS)],
        check=True,
        env=environment,
    )


def main() -> int:
    write_iconset()
    run_iconutil()
    shutil.rmtree(ICONSET, ignore_errors=True)
    print("wrote %s (%d bytes)" % (ICNS, ICNS.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())