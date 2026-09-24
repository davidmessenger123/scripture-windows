from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import __version__, references

ESV_HOST = "https://api.esv.org"
ESV_PATH = "/v3/passage/text/"
WEB_HOST = "https://bible-api.com"
MAX_RESPONSE_BYTES = references.MAX_RESPONSE_BYTES
ESV_COMMON_QUERY = (
    "include-headings=false"
    "&include-footnotes=false"
    "&include-verse-numbers=true"
    "&include-copyright=true"
    "&include-short-copyright=false"
    "&include-passage-references=false"
)
TIMEOUT_MS = 15000


class Fetcher(QObject):
    esv_result = Signal(int, str, str, int)
    web_result = Signal(int, str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_finished)
        self._active_reply = None
        self._buffer = bytearray()
        self._received = 0
        self._failure = ""

    def abort(self) -> None:
        reply = self._active_reply
        if reply is None:
            return
        self._active_reply = None
        self._buffer.clear()
        self._received = 0
        reply.setProperty("_aborted", True)
        reply.abort()

    def fetch_esv(self, tag: int, reference: str, api_key: str) -> None:
        self.abort()
        query = references.encode_reference(reference) + "&" + ESV_COMMON_QUERY
        request = QNetworkRequest(QUrl(ESV_HOST + ESV_PATH + "?q=" + query))
        self._prepare(request, b"Token " + str(api_key or "").encode("utf-8"))
        reply = self._net.get(request)
        self._set_reply(reply, tag, "esv")

    def fetch_web(self, tag: int, reference: str, translation: str) -> None:
        self.abort()
        tr = (translation or "web").strip().lower()
        if tr not in ("web", "kjv"):
            tr = "web"
        url = WEB_HOST + "/" + references.encode_reference(reference) + "?translation=" + tr
        request = QNetworkRequest(QUrl(url))
        self._prepare(request)
        reply = self._net.get(request)
        self._set_reply(reply, tag, "web")

    def _prepare(self, request: QNetworkRequest, authorization: bytes | None = None) -> None:
        request.setTransferTimeout(TIMEOUT_MS)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setMaximumRedirectsAllowed(0)
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", ("scripture-windows/" + __version__).encode("ascii"))
        if authorization is not None:
            request.setRawHeader(b"Authorization", authorization)

    def _set_reply(self, reply: QNetworkReply, tag: int, kind: str) -> None:
        self._buffer = bytearray()
        self._received = 0
        self._failure = ""
        reply.setProperty("_tag", int(tag))
        reply.setProperty("_kind", kind)
        reply.setProperty("_aborted", False)
        reply.readyRead.connect(lambda r=reply: self._drain(r))
        reply.redirected.connect(lambda target, r=reply: self._redirect(r))
        self._active_reply = reply

    def _redirect(self, reply: QNetworkReply) -> None:
        if reply is self._active_reply:
            self._failure = "redirects are not allowed"
            reply.abort()

    def _drain(self, reply: QNetworkReply, require_active: bool = True) -> None:
        if require_active and reply is not self._active_reply:
            return
        while reply.bytesAvailable():
            remaining = MAX_RESPONSE_BYTES + 1 - self._received
            if remaining <= 0:
                self._failure = "response exceeds the %d-byte limit" % MAX_RESPONSE_BYTES
                reply.abort()
                return
            chunk = bytes(reply.read(min(65536, remaining)))
            if not chunk:
                break
            self._received += len(chunk)
            self._buffer.extend(chunk)
            if self._received > MAX_RESPONSE_BYTES:
                self._failure = "response exceeds the %d-byte limit" % MAX_RESPONSE_BYTES
                reply.abort()
                return

    def _on_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._active_reply:
            reply.deleteLater()
            return
        if reply.property("_aborted"):
            self._active_reply = None
            reply.deleteLater()
            self._buffer = bytearray()
            self._received = 0
            return
        self._active_reply = None
        self._drain(reply, require_active=False)
        kind = str(reply.property("_kind"))
        tag = int(reply.property("_tag") or 0)
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = self._failure
        data = bytes(self._buffer)
        self._buffer = bytearray()
        self._received = 0
        content_length = reply.header(QNetworkRequest.KnownHeaders.ContentLengthHeader)
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            declared = 0
        if not error and status:
            if status != 200:
                error = "server returned HTTP %s" % status
                if declared and declared != len(data):
                    error = "response size does not match Content-Length"
            elif declared and declared > MAX_RESPONSE_BYTES:
                error = "response exceeds the %d-byte limit" % MAX_RESPONSE_BYTES
            elif declared and declared != len(data):
                error = "response size does not match Content-Length"
        elif not error and reply.error() == QNetworkReply.NetworkError.NoError:
            error = "network error: response has no HTTP status"
        elif not error and reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            error = "request canceled"
        elif not error:
            error = "network error: %s" % reply.errorString()
        reply.deleteLater()
        if error and status not in {400, 404, 422}:
            data = b""
        decoded = data.decode("utf-8", "replace") if data else ""
        if kind == "esv":
            self.esv_result.emit(tag, decoded, error, int(status or 0))
        else:
            self.web_result.emit(tag, decoded, error, int(status or 0))
