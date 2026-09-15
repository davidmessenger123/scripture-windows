"""Network fetch layer for the Scripture desktop app.

Faithful port of the Omarchy widget's two providers, minus the subprocess
machinery: the app talks directly to api.esv.org (ESV, key required) and
bible-api.com (WEB/KJV, keyless) over QNetworkAccessManager, so everything stays
inside the app's event loop. Responses are bounded to MAX_RESPONSE_BYTES and
requests carry a transfer timeout, mirroring the plugin's guards.
"""

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import references

ESV_HOST = "https://api.esv.org"
ESV_PATH = "/v3/passage/text/"
WEB_HOST = "https://bible-api.com"
MAX_RESPONSE_BYTES = references.MAX_RESPONSE_BYTES
ESV_COMMON_QUERY = (
    "include-headings=false"
    "&include-footnotes=false"
    "&include-verse-numbers=true"
    "&include-short-copyright=false"
    "&include-passage-references=false"
)
TIMEOUT_MS = 15000


class Fetcher(QObject):
    """Fires one of `esv_result` / `web_result` per request.

    The `tag` argument round-trips a caller-generated token so the controller
    can drop stale replies (e.g. after the user spams "Another Verse").
    """

    esv_result = Signal(int, str, str)   # tag, json text, error ("" on success)
    web_result = Signal(int, str, str)   # tag, json text, error ("" on success)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_finished)

    # -- public -----------------------------------------------------------

    def fetch_esv(self, tag: int, reference: str, api_key: str) -> None:
        query = references.encode_reference(reference) + "&" + ESV_COMMON_QUERY
        request = QNetworkRequest(QUrl(ESV_HOST + ESV_PATH + "?q=" + query))
        request.setTransferTimeout(TIMEOUT_MS)
        request.setRawHeader(b"Authorization", ("Token " + api_key).encode("ascii"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"scripture-windows/1.0")
        reply = self._net.get(request)
        reply.setProperty("_tag", tag)
        reply.setProperty("_kind", "esv")

    def fetch_web(self, tag: int, reference: str, translation: str) -> None:
        tr = (translation or "web").strip().lower()
        if tr not in ("web", "kjv"):
            tr = "web"
        slug = (reference or "").replace(" ", "+")
        request = QNetworkRequest(QUrl(WEB_HOST + "/" + slug + "?translation=" + tr))
        request.setTransferTimeout(TIMEOUT_MS)
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"scripture-windows/1.0")
        reply = self._net.get(request)
        reply.setProperty("_tag", tag)
        reply.setProperty("_kind", "web")

    # -- internal ---------------------------------------------------------

    def _on_finished(self, reply: QNetworkReply) -> None:
        kind = reply.property("_kind")
        tag = int(reply.property("_tag") or 0)
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        data = b""
        error = ""

        if reply.error() == QNetworkReply.NetworkError.NoError:
            if status is not None and status >= 400:
                error = "server returned HTTP %d" % int(status)
            else:
                data = bytes(reply.readAll())
                if len(data) > MAX_RESPONSE_BYTES:
                    error = "response exceeds the %d-byte limit" % MAX_RESPONSE_BYTES
                    data = b""
        elif reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            error = "timed out"
        else:
            error = "network error: %s" % reply.errorString()

        reply.deleteLater()

        if kind == "esv":
            self.esv_result.emit(tag, data.decode("utf-8", "replace") if data else "", error)
        else:
            self.web_result.emit(tag, data.decode("utf-8", "replace") if data else "", error)