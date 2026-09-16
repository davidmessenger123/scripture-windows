# Custom PyInstaller hook for PySide6.QtQml.
#
# Replaces the stock hook (PyInstaller/hooks/hook-PySide6.QtQml.py) so only the
# QML modules the app actually imports are bundled. The stock hook calls
# collect_qtqml_files(), which gathers *every* directory under the wheel's qml/
# import path that ships a qmldir — QtWebEngine, QtQuick3D, QtCharts, Qt3D,
# QtMultimedia, QtLocation, QtWayland, even the whole QtQuick VirtualKeyboard —
# whether or not the app uses them. Those QML plugins link Qt shared libraries,
# which is how a small app ends up shipping a ~200 MB libQt6WebEngineCore plus
# Quick3D/Charts/Graphs/3D/Pdf/Media runtimes it never touches.
#
# The app imports only QtQuick, QtQuick.Controls and QtQuick.Layouts, so we keep
# exactly that family: QtQml plus the QtQuick core, Templates, Controls (root +
# Basic and Fusion styles, which are what the app resolves to at runtime — the
# platform "Windows" style does not ship in the PySide6 wheel — plus the shared
# internal impl), Dialogs, Layouts, Window and a few small helper modules.
# Everything else is dropped: the bigger optional Control styles (Material,
# Imagine, Universal, FluentWinUI3) and the standalone VirtualKeyboard, Pdf,
# Scene3D, VectorImage and Effects-adjacent modules, along with the Qt shared
# libraries they would otherwise drag in. The Basic style was what the app
# already rendered with, so the look is unchanged.
#
# This works because PyInstaller allows only one hook per module, ordered by
# priority; user hooks (priority 1000) replace the built-in one (priority -2000).
# The hook is wired in via `hookspath` in Scripture.spec.

# The QtQml module's plugin collection also pulls in the QML *debugger* plugins
# under Qt/plugins/qmltooling (qmldbg_*). They are only for QML tooling, not
# runtime, and one of them (qmldbg_quick3dprofiler) drags the whole
# libQt6Quick3DUtils dependency in, so they are dropped below.

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()

_QML_ROOT_KEEP = ("builtins.qmltypes", "jsroot.qmltypes")

_QML_MODULE_LEAVES_UNDER_QTQUICK = {
    "Dialogs",
    "Effects",
    "Layouts",
    "LocalStorage",
    "Particles",
    "Shapes",
    "Templates",
    "Timeline",
    "Window",
}

_QML_CONTROLS_DROP = {"designer", "FluentWinUI3", "Imagine", "Material", "Universal"}


def _keep_qml(candidates):
    """Filter (src, dest) lists from collect_qtqml_files to the allowlist."""
    kept = []
    for src, dest in candidates:
        normalized = src.replace("\\", "/")
        after_qml = normalized.split("/qml/", 1)[1] if "/qml/" in normalized else ""

        if after_qml in _QML_ROOT_KEEP:
            kept.append((src, dest))
            continue

        segments = after_qml.split("/")
        if segments[0] == "QtQml":
            kept.append((src, dest))  # whole QtQml (core, Models, WorkerScript)
        elif segments[0] == "QtQuick":
            if len(segments) == 1:
                kept.append((src, dest))  # QtQuick/ root module files
            elif segments[1] == "Controls" and segments[2] not in _QML_CONTROLS_DROP:
                kept.append((src, dest))  # module root + Basic/Fusion/impl styles
            elif segments[1] in _QML_MODULE_LEAVES_UNDER_QTQUICK:
                kept.append((src, dest))
    return kept


def _drop_qmltooling(candidates):
    """Drop QML debugger plugins (Qt/plugins/qmltooling) from any of the lists.

    They are debugging tooling only, and qmldbg_quick3dprofiler alone would pull
    libQt6Quick3DUtils (and Quick3D deps) back into the bundle.
    """
    kept = []
    for src, dest in candidates:
        if "/plugins/qmltooling" in dest.replace("\\", "/"):
            continue
        kept.append((src, dest))
    return kept


qml_binaries = _keep_qml(qml_binaries)
qml_datas = _keep_qml(qml_datas)

# The QtQml module's own plugin set (collected via add_qt6_dependencies
# -> collect_module) includes qmltooling too, so filter every list we got.
binaries = _drop_qmltooling(binaries)
datas = _drop_qmltooling(datas)

binaries += qml_binaries
datas += qml_datas