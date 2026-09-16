# -*- mode: python ; coding: utf-8 -*-
#
# Scripture — PyInstaller build. This spec is the single source of truth for
# the bundled exe: the CI workflow and scripts/build*.ps1 invoke it instead of
# re-listing flags. Run from the repo root:
#
#   python -m PyInstaller --noconfirm --clean Scripture.spec
#
# The bundle is kept small by packaging/pyinstaller/hook-PySide6.QtQml.py,
# which allowlists the QML modules so unused Qt machinery (WebEngine, QtQuick3D,
# Charts, etc.) and its shared libraries are never collected.

import os

a = Analysis(
    ['src/scripture/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/scripture/qml', 'scripture/qml')],
    hiddenimports=['PySide6.QtQml'],
    hookspath=['packaging/pyinstaller'],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules the app never imports. Excluding them stops their hooks (and
    # any QML-plugin dependencies they could still drag in) from running.
    excludes=[
        'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
        'PySide6.QtAxContainer', 'PySide6.QtBluetooth', 'PySide6.QtCharts',
        'PySide6.QtDataVisualization', 'PySide6.QtDesigner', 'PySide6.QtGraphs',
        'PySide6.QtGraphsWidgets', 'PySide6.QtHelp', 'PySide6.QtHttpServer',
        'PySide6.QtLocation', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetworkAuth', 'PySide6.QtNfc', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtPositioning',
        'PySide6.QtPrintSupport', 'PySide6.QtQuick3D', 'PySide6.QtQuick3DUtils',
        'PySide6.QtQuick3DParticles', 'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors',
        'PySide6.QtSerialBus', 'PySide6.QtSerialPort', 'PySide6.QtSpatialAudio',
        'PySide6.QtSql', 'PySide6.QtStateMachine', 'PySide6.QtSvg',
        'PySide6.QtSvgWidgets', 'PySide6.QtTest', 'PySide6.QtTextToSpeech',
        'PySide6.QtUiTools', 'PySide6.QtWebChannel', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets', 'PySide6.QtWebView', 'PySide6.QtXml',
    ],
    noarchive=False,
    optimize=0,
)

# English-only UI: keep just the en translations instead of every locale the
# PySide6 wheel ships (the full set is ~10 MB of .qm files).
def _english_only(entries):
    kept = []
    for dest, src, typecode in entries:
        if typecode == 'DATA' and os.path.basename(dest).endswith('.qm'):
            stem = os.path.splitext(os.path.basename(dest))[0]
            lang = stem.rsplit('_', 1)[-1]
            if not lang.startswith('en'):
                continue
        kept.append((dest, src, typecode))
    return kept


a.datas = _english_only(list(a.datas))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Scripture',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
)