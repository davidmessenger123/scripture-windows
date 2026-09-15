"""Scripture desktop app — QApplication bootstrap, system tray, and overlay show.

This module wires the Python `AppController` into the Qt Quick UI (`main.qml`)
and owns the only pieces the QML cannot: the tray icon and the Quit path. The
rest of the widget logic lives in `controller.py` so it is UI-agnostic.

Run with `python -m scripture`, or `python -m scripture --smoke` for a
headless load test (`QT_QPA_PLATFORM=offscreen`).
"""

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .controller import AppController


def _make_icon() -> QIcon:
    """A small dark rounded square with a gold star (tray + window icon)."""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0d1b2a"))
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 12, 12)

    cx, cy, outer, inner = 32.0, 34.0, 20.0, 9.0
    points = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(-90.0 + i * 36.0)
        points.append(QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    painter.setBrush(QColor("#f5c542"))
    painter.drawPolygon(QPolygonF(points))
    painter.end()
    return QIcon(pm)


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    smoke = "--smoke" in argv
    app_args = [a for a in sys.argv[:1] + [x for x in argv if x != "--smoke"]]
    if smoke and "offscreen" not in " ".join(app_args):
        pass  # platform is chosen via QT_QPA_PLATFORM env by the caller

    app = QApplication(app_args)
    app.setApplicationName("Scripture")
    app.setOrganizationName("davidjm")
    app.setQuitOnLastWindowClosed(False)

    controller = AppController()

    # Expose the controller as the QML singleton `ScriptureRT.App` rather than a
    # context property. Context properties are not reliably visible inside
    # Window content, so singletons are the only stable QML-facing name.
    qmlRegisterSingletonInstance(AppController, "ScriptureRT", 1, 0, "App", controller)

    engine = QQmlApplicationEngine()
    qml_file = Path(__file__).parent / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        print("failed to load main.qml", file=sys.stderr)
        return 1

    if not smoke:
        tray = QSystemTrayIcon(_make_icon(), app)
        tray.setToolTip("Scripture")
        menu = QMenu()

        open_action = QAction("Open Scripture", app)
        open_action.triggered.connect(lambda: setattr(controller, "overlayOpen", True))
        close_action = QAction("Close Scripture", app)
        close_action.triggered.connect(lambda: setattr(controller, "overlayOpen", False))
        settings_action = QAction("Settings\u2026", app)
        settings_action.triggered.connect(controller.toggle_settings)
        quit_action = QAction("Quit", app)
        quit_action.triggered.connect(app.quit)

        menu.addAction(open_action)
        menu.addAction(close_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.setVisible(True)

    if smoke:
        controller.overlayOpen = True
        controller.settingsOpen = True
        QTimer.singleShot(1200, app.quit)
        print("smoke: engine loaded, controller OK", flush=True)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())