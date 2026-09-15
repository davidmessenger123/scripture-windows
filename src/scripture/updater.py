"""GitHub release update check for the Scripture desktop app.

On startup (frozen builds only) the updater asks the GitHub API for the latest
non-prerelease tag and compares it to the built-in version. A newer release
surfaces as `updateAvailable` / `updateTag` / `updateUrl` for the tray balloon
and the in-app "Get it" chip. Checks are quiet: any network or parse failure
leaves the state untouched and never blocks or crashes the app.
"""

import json

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

REPO = "davidmessenger123/scripture-windows"
API_URL = "https://api.github.com/repos/" + REPO + "/releases/latest"
RELEASE_URL = "https://github.com/" + REPO + "/releases"
TIMEOUT_MS = 10000


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
    """Fetches `releases/latest` once and exposes a QML-facing update state."""

    updateChanged = Signal()

    def __init__(self, current_version: str, parent=None, api_url: str = API_URL, release_url: str = RELEASE_URL):
        super().__init__(parent)
        self._current = tag_tuple(current_version)
        self._api_url = api_url
        self._release_url = release_url
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_finished)
        self._reply = None
        self._update_tag = ""
        self._update_url = ""
        self._update_available = False

    # -- QML-facing state -------------------------------------------------

    def _updateAvailable(self) -> bool:
        return self._update_available

    def _updateTag(self) -> str:
        return self._update_tag

    def _updateUrl(self) -> str:
        return self._update_url

    updateAvailable = Property(bool, _updateAvailable, notify=updateChanged)
    updateTag = Property(str, _updateTag, notify=updateChanged)
    updateUrl = Property(str, _updateUrl, notify=updateChanged)

    # -- public -----------------------------------------------------------

    @Slot()
    def check(self) -> None:
        if self._reply is not None:
            return
        request = QNetworkRequest(QUrl(self._api_url))
        request.setTransferTimeout(TIMEOUT_MS)
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", b"scripture-windows/1.0")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        self._reply = self._net.get(request)

    @Slot()
    def open(self) -> None:
        QDesktopServices.openUrl(QUrl(self._update_url or self._release_url))

    # -- internal ---------------------------------------------------------

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
        self._update_tag = tag
        self._update_url = str(payload.get("html_url") or self._release_url)
        self._update_available = bool(tag_tuple(tag) and tag_tuple(tag) > self._current)
        self.updateChanged.emit()