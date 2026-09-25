"""Scripture desktop app — QApplication bootstrap, system tray, and overlay show.

This module wires the Python `AppController` into the Qt Quick UI (`main.qml`)
and owns the only pieces the QML cannot: the tray icon and the Quit path. The
rest of the widget logic lives in `controller.py` so it is UI-agnostic.

Run with `python -m scripture`, or `python -m scripture --smoke` for a
headless load test (`QT_QPA_PLATFORM=offscreen`).
"""

import os
import sys
import tempfile
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QMetaObject, QStandardPaths, QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtQuick import QQuickView
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import __version__
from .controller import AppController
from .secure_files import create_owner_only_directory, restrict_owner_only
from .single_instance import SingleInstance
from .updater import UpdateChecker, cleanup_stale_update_helpers, recover_interrupted_update, run_update_helper


STARTUP_LOG_NAME = "startup-error.log"
STARTUP_LOG_MAX_BYTES = 1024 * 1024
STARTUP_LOG_BACKUPS = 3


def _rotate_startup_log(path: Path) -> None:
    try:
        if path.stat().st_size < STARTUP_LOG_MAX_BYTES:
            return
        oldest = Path(str(path) + "." + str(STARTUP_LOG_BACKUPS))
        if oldest.exists():
            oldest.unlink()
        for index in range(STARTUP_LOG_BACKUPS - 1, 0, -1):
            source = Path(str(path) + "." + str(index))
            if source.exists():
                os.replace(source, Path(str(path) + "." + str(index + 1)))
        os.replace(path, Path(str(path) + ".1"))
    except OSError:
        pass


def _startup_log(message: str) -> None:
    if not getattr(sys, "frozen", False):
        print(message, file=sys.stderr)
        return
    try:
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if not base:
            return
        path = Path(base) / STARTUP_LOG_NAME
        create_owner_only_directory(path.parent)
        _rotate_startup_log(path)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (stamp, str(message).rstrip()))
        restrict_owner_only(path)
    except OSError:
        pass


class SettingsView(QQuickView):
    """The settings dialog as an independent top-level window.

    Visibility is driven from Python so the dialog is a real, editable window
    that opens on its own — it is never hidden behind the full-screen overlay.
    It shares the overlay's QQml engine so the `scripture` singleton resolves.
    The window's X button reports the close back through `on_closed`.
    """

    def __init__(self, controller, engine, parent=None):
        super().__init__(engine, None)
        self._controller = controller
        self.setResizeMode(QQuickView.SizeRootObjectToView)
        qml_file = Path(__file__).parent / "qml" / "settings.qml"
        self.setSource(QUrl.fromLocalFile(str(qml_file)))
        self.setFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._controller.settingsOpen = False
        event.accept()
        super().closeEvent(event)


def _make_icon() -> QIcon:
    """A small dark rounded square with a gold cross (tray + window icon)."""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0d1b2a"))
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 12, 12)

    painter.setBrush(QColor("#f5c542"))
    r = size / 22
    painter.drawRoundedRect(size * 0.43, size * 0.15, size * 0.14, size * 0.62, r, r)
    painter.drawRoundedRect(size * 0.32, size * 0.30, size * 0.36, size * 0.14, r, r)
    painter.end()
    return QIcon(pm)


def _engine_errors_capture(engine):
    """Connect to the engine's `warnings` signal and return a reader callable."""
    captured = []

    def _on_warnings(warnings):
        for w in warnings:
            try:
                captured.append(str(w.toString()))
            except Exception:
                captured.append(repr(w))

    try:
        engine.warnings.connect(_on_warnings)
    except Exception:
        pass
    return lambda: ":\n" + "\n".join(captured) if captured else ""


def _qml_message_capture():
    """Install a Qt message handler that captures QML messages during load.

    Returns (buf, uninstall) where uninstall restores the previous handler.
    Call uninstall after engine.load so messages do not accumulate forever.
    """
    buf = []

    def handler(mode, context, message):
        cat = context.category if context else "(none)"
        if context is not None and context.file:
            loc = f"{context.file}:{context.line}"
        else:
            loc = "-"
        buf.append(f"[{mode}] {cat} {loc}: {message}")

    from PySide6.QtCore import qInstallMessageHandler

    previous = qInstallMessageHandler(handler)

    def uninstall():
        qInstallMessageHandler(previous)

    return buf, uninstall


def _bundled_qml_modules() -> str:
    """List the QML module dirs actually present in a frozen bundle."""
    if not getattr(sys, "frozen", False):
        return ""
    root = Path(getattr(sys, "_MEIPASS", "/"))
    qml_root = root / "PySide6" / "qml"
    if not qml_root.exists():
        return "(no PySide6/qml in bundle)"
    modules = sorted(p.relative_to(qml_root) for p in qml_root.rglob("qmldir"))
    return "bundled modules:\n" + "\n".join(
        "  " + str(m.parent).replace("\\", "/") for m in modules
    )


def _qml_import_probe(engine, qml_file) -> str:
    """Describe the frozen bundle state around the QML load, for a startup log."""
    lines = []
    if getattr(sys, "frozen", False):
        lines.append("frozen: True")
    lines.append(f"qml_file: {qml_file} exists={qml_file.exists()}")
    lines.append("importPaths: " + (", ".join(engine.importPathList()) or "(none)"))
    from PySide6.QtCore import QLibraryInfo

    lines.append(
        "LibraryPaths: "
        + ", ".join(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
    )
    return "\n".join(lines)


def _safe_cleanup_path(path: str) -> bool:
    try:
        candidate = Path(path).resolve()
        root = Path(tempfile.gettempdir()).resolve()
        return candidate.parent.parent == root and candidate.parent.name.startswith("scripture-update-helper-")
    except OSError:
        return False


def _remove_file(path: str) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass
    if _safe_cleanup_path(path):
        try:
            Path(path).parent.rmdir()
        except OSError:
            pass


@dataclass(frozen=True)
class TrayNotification:
    kind: str
    reference: str = ""
    snapshot: object = None
    update_tag: str = ""


class TrayNotificationRouter:
    def __init__(self, controller, checker):
        self._controller = controller
        self._checker = checker
        self._queue = deque()
        self._current = None
        self._handling = False
        self._lock = Lock()

    def enqueue(self, kind: str, reference: str = "", snapshot=None, update_tag: str = "") -> TrayNotification:
        item = TrayNotification(str(kind or ""), str(reference or ""), snapshot, str(update_tag or ""))
        with self._lock:
            self._queue.append(item)
        return item

    def set_pending(self, kind: str) -> TrayNotification:
        return self.enqueue(kind)

    def activate_next(self):
        with self._lock:
            if self._current is not None or not self._queue:
                return None
            self._current = self._queue.popleft()
            return self._current

    def expire(self, item: TrayNotification) -> bool:
        with self._lock:
            if self._current is not item:
                return False
            self._current = None
            return True

    def click(self) -> None:
        with self._lock:
            if self._handling or self._current is None:
                return
            item = self._current
            self._current = None
            self._handling = True
        try:
            _route_tray_click(item, self._controller, self._checker)
        finally:
            with self._lock:
                self._handling = False


def _route_tray_click(item: TrayNotification, controller, checker) -> None:
    if item.kind == "daily":
        if item.snapshot is not None:
            controller.show_daily_snapshot(item.snapshot)
        else:
            controller.show_daily_verse(item.reference)
    elif item.kind == "update":
        checker.download()


def daily_notification_body(reference: str, translation: str) -> str:
    ref = " ".join(str(reference or "").split())
    name = " ".join(str(translation or "").split())[:64]
    return "%s — %s is ready." % (ref, name or "your verse")


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "--scripture-apply-update":
        return run_update_helper(args[1:])
    try:
        return _run(args)
    except Exception:
        _startup_log(
            "Unhandled exception in main():\n" + traceback.format_exc()
        )
        if getattr(sys, "frozen", False):
            return 1
        raise


def _run(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if getattr(sys, "frozen", False) and os.name == "nt" and not recover_interrupted_update(os.path.abspath(sys.executable)):
        _startup_log("automatic update recovery could not safely resolve the replacement journal")
    cleanup_helper = ""
    if len(argv) >= 2 and argv[0] == "--scripture-cleanup-helper":
        cleanup_helper = argv[1]
        argv = argv[2:]
    smoke = "--smoke" in argv
    app_args = [a for a in sys.argv[:1] + [x for x in argv if x != "--smoke"]]
    if smoke and "offscreen" not in " ".join(app_args):
        pass  # platform is chosen via QT_QPA_PLATFORM env by the caller

    # Pin Qt Quick Controls to the "Basic" style. On Windows the platform
    # default is a native style that imports QtQuick.NativeStyle — a module the
    # PyInstaller bundle deliberately ships without (see the QtQml hook), so
    # letting it resolve would crash the frozen exe. Basic is style-agnostic and
    # is what every platform rendered before.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    app = QApplication(app_args)
    app.setApplicationName("Scripture")
    app.setOrganizationName("davidjm")
    app.setQuitOnLastWindowClosed(False)
    if cleanup_helper and _safe_cleanup_path(cleanup_helper):
        QTimer.singleShot(5000, lambda: _remove_file(cleanup_helper))
    cleanup_stale_update_helpers()
    instance_key = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or str(Path.home())
    instance = SingleInstance(instance_key, app)
    if not instance.acquire():
        return 0

    controller = AppController()
    instance.showRequested.connect(lambda: setattr(controller, "overlayOpen", True))

    # Expose the controller as the QML singleton `ScriptureRT.App` rather than a
    # context property. Context properties are not reliably visible inside
    # Window content, so singletons are the only stable QML-facing name.
    qmlRegisterSingletonInstance(AppController, "ScriptureRT", 1, 0, "App", controller)

    checker = UpdateChecker(__version__, app)
    qmlRegisterSingletonInstance(UpdateChecker, "ScriptureRT", 1, 0, "Updater", checker)

    qml_messages, uninstall_qml_messages = _qml_message_capture()
    engine = QQmlApplicationEngine()
    qml_warnings = _engine_errors_capture(engine)
    qml_file = Path(__file__).parent / "qml" / "main.qml"
    try:
        engine.load(QUrl.fromLocalFile(str(qml_file)))
    finally:
        uninstall_qml_messages()
    if not engine.rootObjects():
        _startup_log(
            "failed to load main.qml"
            + qml_warnings()
            + ("\nqml messages:\n" + "\n".join(qml_messages) if qml_messages else "")
            + "\n" + _qml_import_probe(engine, qml_file)
            + "\n" + _bundled_qml_modules()
        )
        return 1

    # Lazy: create the settings window on first open, not at startup.
    settings_view = {"view": None}

    def _ensure_settings_view():
        view = settings_view["view"]
        if view is not None:
            return view
        view = SettingsView(controller, engine)
        if view.rootObject() is None:
            _startup_log("failed to load settings.qml" + qml_warnings())
            return None
        settings_view["view"] = view
        return view

    def _sync_settings_view() -> None:
        if controller.settingsOpen:
            view = _ensure_settings_view()
            if view is None:
                controller.settingsOpen = False
                return
            screen = view.screen()
            geo = screen.availableGeometry() if screen is not None else None
            if geo is not None:
                view.setPosition(
                    geo.center().x() - view.width() // 2,
                    geo.center().y() - view.height() // 2,
                )
            view.show()
            view.raise_()
            root = view.rootObject()
            if root is not None:
                QMetaObject.invokeMethod(root, "seedSettings")
        else:
            view = settings_view["view"]
            if view is not None:
                view.hide()

    controller.settingsChanged.connect(_sync_settings_view)

    def _raise_settings_with_overlay() -> None:
        view = settings_view["view"]
        if view is not None and controller.settingsOpen:
            view.raise_()

    controller.overlayChanged.connect(_raise_settings_with_overlay)

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

        notification_router = TrayNotificationRouter(controller, checker)
        ballooned = []

        def _expire_notification(item: TrayNotification) -> None:
            if notification_router.expire(item):
                _show_next_notification()

        def _show_next_notification() -> None:
            item = notification_router.activate_next()
            if item is None:
                return
            try:
                if item.kind == "update":
                    tray.showMessage(
                        "Scripture update available",
                        "Scripture %s is available. Click to update automatically." % item.update_tag,
                        QSystemTrayIcon.MessageIcon.Information,
                        8000,
                    )
                elif item.kind == "daily":
                    if item.snapshot is None or not QSystemTrayIcon.supportsMessages():
                        controller.cancel_daily_notification_attempt()
                        _expire_notification(item)
                        return
                    tray.showMessage(
                        "Scripture",
                        daily_notification_body(item.reference, item.snapshot.translation_name),
                        QSystemTrayIcon.MessageIcon.Information,
                        8000,
                    )
                    controller.mark_daily_notification_delivered()
                else:
                    _expire_notification(item)
                    return
            except Exception:
                if item.kind == "daily":
                    controller.cancel_daily_notification_attempt()
                _expire_notification(item)
                return
            QTimer.singleShot(9000, lambda item=item: _expire_notification(item))

        def _notify_update() -> None:
            if checker.updateAvailable and checker.updateTag not in ballooned:
                ballooned.append(checker.updateTag)
                notification_router.enqueue("update", update_tag=checker.updateTag)
                _show_next_notification()

        def _notify_daily(reference: str, translation: str) -> None:
            snapshot = controller.daily_snapshot(reference)
            if not reference or snapshot is None:
                controller.cancel_daily_notification_attempt()
                return
            notification_router.enqueue("daily", reference=reference, snapshot=snapshot)
            _show_next_notification()

        def _message_clicked() -> None:
            try:
                notification_router.click()
            finally:
                _show_next_notification()

        checker.updateChanged.connect(_notify_update)
        controller.dailyNotificationReady.connect(_notify_daily)
        tray.messageClicked.connect(_message_clicked)
        controller.start_daily_events()

    updates_on = not smoke and (
        getattr(sys, "frozen", False) or os.environ.get("SCRIPTURE_FORCE_UPDATE_CHECK") == "1"
    )
    if updates_on:
        QTimer.singleShot(0, checker.check)

    def _maybe_apply_update() -> None:
        if (
            not checker.downloading
            and checker.updateProgress >= 1.0
            and checker.updateError == ""
            and not checker.updateApplied
        ):
            QTimer.singleShot(400, checker.apply)

    checker.downloadingChanged.connect(_maybe_apply_update)
    checker.quitRequested.connect(app.quit)

    if smoke:
        controller.overlayOpen = True
        controller.settingsOpen = True
        QTimer.singleShot(1200, app.quit)
        print("smoke: engine loaded, controller OK", flush=True)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())