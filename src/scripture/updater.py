"""GitHub release update check + self-update for the Scripture desktop app.

On startup (frozen builds only) the updater asks the GitHub API for the latest
non-prerelease tag and compares it to the built-in version. A newer release
surfaces as `updateAvailable` / `updateTag` / `updateUrl` for the tray balloon
and the in-app update chip.

Clicking the update chip (or the tray balloon) calls `download()`: the new
`Scripture.exe` asset is streamed to a temp file with `updateProgress` exposed
to QML. When it lands, `apply()` writes a tiny detached .cmd helper that waits
for this process to exit (a running onefile exe is locked on Windows), swaps
the new exe over the running one, relaunches it, and cleans itself up. The app
then exits via the `quitRequested` signal.

Checks and downloads are quiet: any network or parse failure leaves state
untouched and never blocks or crashes the app. Non-frozen (dev) builds offer
the browser fallback only.
"""

import json
import os
import subprocess
import sys
import tempfile

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

REPO = "davidmessenger123/scripture-windows"
API_URL = "https://api.github.com/repos/" + REPO + "/releases/latest"
RELEASE_URL = "https://github.com/" + REPO + "/releases"
ASSET_NAME = "Scripture.exe"
CHECK_TIMEOUT_MS = 10000
DOWNLOAD_TIMEOUT_MS = 120000


def tag_tuple(tag: str) -> tuple:
    """'v0.1.2' / '0.1.2' -> (0, 1, 2); anything unparseable -> ()."""
    parts = []
    for chunk in tag.lstrip("vV").split(".")[:3]:
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts)


class UpdateChecker(QObject):
    """Fetches `releases/latest` and drives the download + swap self-update."""

    updateChanged = Signal()
    downloadingChanged = Signal()
    progressChanged = Signal()
    errorChanged = Signal()
    quitRequested = Signal()

    def __init__(self, current_version: str, parent=None, api_url: str = API_URL, release_url: str = RELEASE_URL):
        super().__init__(parent)
        self._current = tag_tuple(current_version)
        self._api_url = api_url
        self._release_url = release_url
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_finished)
        self._reply = None
        self._dl_reply = None
        self._dl_file = None
        self._dl_path = ""
        self._update_tag = ""
        self._update_url = ""
        self._update_available = False
        self._asset_url = ""
        self._downloading = False
        self._progress = 0.0
        self._error = ""
        self._applied = False

    # -- QML-facing state -------------------------------------------------

    def _updateAvailable(self) -> bool:
        return self._update_available

    def _updateTag(self) -> str:
        return self._update_tag

    def _updateUrl(self) -> str:
        return self._update_url

    def _downloading(self) -> bool:
        return self._downloading

    def _updateProgress(self) -> float:
        return self._progress

    def _updateError(self) -> str:
        return self._error

    def _updateApplied(self) -> bool:
        return self._applied

    updateAvailable = Property(bool, _updateAvailable, notify=updateChanged)
    updateTag = Property(str, _updateTag, notify=updateChanged)
    updateUrl = Property(str, _updateUrl, notify=updateChanged)
    downloading = Property(bool, _downloading, notify=downloadingChanged)
    updateProgress = Property(float, _updateProgress, notify=progressChanged)
    updateError = Property(str, _updateError, notify=errorChanged)
    updateApplied = Property(bool, _updateApplied, notify=updateChanged)

    # -- public -----------------------------------------------------------

    @Slot()
    def check(self) -> None:
        if self._reply is not None:
            return
        request = QNetworkRequest(QUrl(self._api_url))
        request.setTransferTimeout(CHECK_TIMEOUT_MS)
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", b"scripture-windows/1.0")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        self._reply = self._net.get(request)

    @Slot()
    def open(self) -> None:
        QDesktopServices.openUrl(QUrl(self._update_url or self._release_url))

    @Slot()
    def download(self) -> None:
        """Download the update asset. In dev builds, fall back to the browser."""
        if self._downloading or self._applied or not self._update_available:
            return
        if not self._asset_url:
            self.open()
            return
        if not getattr(sys, "frozen", False):
            self.open()
            return
        tmp_dir = tempfile.mkdtemp(prefix="scripture-update-")
        self._dl_path = os.path.join(tmp_dir, "Scripture.new.exe")
        self._progress = 0.0
        self._error = ""
        self._downloading = True
        self.progressChanged.emit()
        self.errorChanged.emit()
        self.downloadingChanged.emit()
        request = QNetworkRequest(QUrl(self._asset_url))
        request.setTransferTimeout(DOWNLOAD_TIMEOUT_MS)
        request.setRawHeader(b"User-Agent", b"scripture-windows/1.0")
        self._dl_reply = self._net.get(request)
        self._dl_reply.downloadProgress.connect(self._on_dl_progress)
        self._dl_reply.readyRead.connect(self._on_dl_ready)
        self._dl_reply.finished.connect(self._on_dl_finished)

    @Slot()
    def apply(self) -> None:
        """Apply the just-downloaded exe via a detached helper + exit the app."""
        if self._applied or not self._dl_path or not os.path.isfile(self._dl_path):
            self._fail("Downloaded file missing; please try again.")
            return
        if not getattr(sys, "frozen", False):
            self.open()
            return
        script = self._helper_script()
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
                close_fds=True,
            )
        except OSError:
            self._fail("Could not start the installer; open the release page and install manually.")
            return
        self._applied = True
        self.updateChanged.emit()
        self.quitRequested.emit()

    # -- helper script ----------------------------------------------------

    def _helper_script(self) -> str:
        """Write and return the path to a .cmd that swaps the exe once we're gone.

        The running onefile exe locks its own file, so the helper waits for
        this process's PID to disappear, replaces the exe, relaunches it and
        deletes its own temp file.
        """
        target = os.path.normpath(sys.executable)
        pending = os.path.normpath(self._dl_path)
        body = (
            "@echo off\r\n"
            "setlocal EnableExtensions\r\n"
            'set "TARGET=@{TARGET}"\r\n'
            'set "PENDING=@{PENDING}"\r\n'
            "set APPPID=@{PID}\r\n"
            ":wait\r\n"
            'tasklist /FI "PID eq %APPPID%" | findstr /R /C:"%APPPID%" >nul\r\n'
            "if not errorlevel 1 (\r\n"
            "    timeout /t 1 /nobreak >nul\r\n"
            "    goto :wait\r\n"
            ")\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            'move /Y "%PENDING%" "%TARGET%" >nul 2>&1\r\n'
            'if errorlevel 1 (\r\n'
            '    del /q "%PENDING%" >nul 2>&1\r\n'
            '    exit /b 1\r\n'
            ")\r\n"
            'start "" "%TARGET%"\r\n'
            'del /q "%~f0" >nul 2>&1\r\n'
            "exit /b 0\r\n"
        )
        body = (
            body.replace("@{TARGET}", target)
            .replace("@{PENDING}", pending)
            .replace("@{PID}", str(os.getpid()))
        )
        handle, path = tempfile.mkstemp(prefix="scripture-apply-", suffix=".cmd")
        try:
            with os.fdopen(handle, "w", encoding="ascii") as fh:
                fh.write(body)
        except OSError:
            os.unlink(path)
            raise
        return path

    # -- internals --------------------------------------------------------

    def _on_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        data = b""
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if reply.error() == QNetworkReply.NetworkError.NoError and status == 200:
            data = bytes(reply.readAll())
        reply.deleteLater()
        if not data:
            return
        try:
            payload = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            return
        tag = str(payload.get("tag_name", "")).strip()
        if not tag:
            return
        self._asset_url = ""
        for asset in payload.get("assets", []) or []:
            if asset.get("name") == ASSET_NAME:
                self._asset_url = str(asset.get("browser_download_url") or "")
                break
        self._update_tag = tag
        self._update_url = str(payload.get("html_url") or self._release_url)
        self._update_available = bool(
            tag_tuple(tag) and tag_tuple(tag) > self._current and self._asset_url
        )
        self.updateChanged.emit()

    def _on_dl_progress(self, received: int, total: int) -> None:
        if total > 0:
            self._progress = max(0.0, min(1.0, received / total))
            self.progressChanged.emit()

    def _on_dl_ready(self) -> None:
        if self._dl_reply is None:
            return
        data = bytes(self._dl_reply.readAll())
        if not data:
            return
        try:
            if self._dl_file is None:
                self._dl_file = open(self._dl_path, "wb")
            self._dl_file.write(data)
        except OSError as exc:
            self._fail("Could not save the update: %s" % exc)

    def _on_dl_finished(self) -> None:
        reply = self._dl_reply
        self._dl_reply = None
        if self._dl_file is not None:
            try:
                self._dl_file.close()
            except OSError:
                pass
            self._dl_file = None
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        reply.deleteLater()
        if not ok or status != 200 or not os.path.isfile(self._dl_path) or os.path.getsize(self._dl_path) == 0:
            if self._downloading:
                self._fail("Download failed; open the release page and install manually.")
            return
        self._progress = 1.0
        self._downloading = False
        self.progressChanged.emit()
        self.downloadingChanged.emit()

    def _fail(self, message: str) -> None:
        self._downloading = False
        self._error = message
        if self._dl_file is not None:
            try:
                self._dl_file.close()
            except OSError:
                pass
            self._dl_file = None
        self.progressChanged.emit()
        self.downloadingChanged.emit()
        self.errorChanged.emit()