# -*- mode: python ; coding: utf-8 -*-
#
# Scripture — macOS PyInstaller spec. One .app bundle (onedir), signed ad-hoc
# by default; the CI workflow re-signs and notarizes with a Developer ID when
# signing secrets are configured. Run from the repo root on macOS:
#
#   python -m PyInstaller --noconfirm --clean Scripture-macos.spec
#
# The Windows build keeps Scripture.spec (single-file exe); macOS uses onedir,
# which is the only sane target for a signed/notarized bundle and avoids the
# per-launch unpacking a onefile .app would do. The Analysis below mirrors
# Scripture.spec: the same QML allowlist hook and the same Qt exclusions.

import os

APP_NAME = "Scripture"
BUNDLE_IDENTIFIER = "com.davidjm.scripture"
ASSETS_DIR = "assets"


def _current_version() -> str:
    version_path = os.path.join("src", "scripture", "VERSION")
    with open(version_path, encoding="ascii") as fh:
        return fh.read().strip()


a = Analysis(
    ["src/scripture/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[("src/scripture/qml", "scripture/qml"), ("src/scripture/VERSION", "scripture")],
    hiddenimports=["PySide6.QtQml"],
    hookspath=["packaging/pyinstaller"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
        "PySide6.QtAxContainer", "PySide6.QtBluetooth", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtDesigner", "PySide6.QtGraphs",
        "PySide6.QtGraphsWidgets", "PySide6.QtHelp", "PySide6.QtHttpServer",
        "PySide6.QtLocation", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetworkAuth", "PySide6.QtNfc", "PySide6.QtOpenGLWidgets",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
        "PySide6.QtPrintSupport", "PySide6.QtQuick3D", "PySide6.QtQuick3DUtils",
        "PySide6.QtQuick3DParticles", "PySide6.QtQuickWidgets",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
        "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
        "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtSvg",
        "PySide6.QtSvgWidgets", "PySide6.QtTest", "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools", "PySide6.QtWebChannel", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets", "PySide6.QtWebView", "PySide6.QtXml",
    ],
    noarchive=False,
    optimize=0,
)

# English-only UI: keep just the en translations instead of every locale the
# PySide6 wheel ships (the full set is ~10 MB of .qm files).
def _english_only(entries):
    kept = []
    for dest, src, typecode in entries:
        if typecode == "DATA" and os.path.basename(dest).endswith(".qm"):
            stem = os.path.splitext(os.path.basename(dest))[0]
            lang = stem.rsplit("_", 1)[-1]
            if not lang.startswith("en"):
                continue
        kept.append((dest, src, typecode))
    return kept


a.datas = _english_only(list(a.datas))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

bundle = BUNDLE(
    coll,
    name=APP_NAME + ".app",
    icon=os.path.join(ASSETS_DIR, "app.icns"),
    bundle_identifier=BUNDLE_IDENTIFIER,
    info_plist={
        "CFBundleDisplayName": "Scripture",
        "CFBundleShortVersionString": _current_version(),
        "CFBundleVersion": _current_version(),
        "CFBundleName": "Scripture",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "NSQuitAlwaysKeepsWindows": False,
    },
)