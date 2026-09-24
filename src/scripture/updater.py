from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import __version__

REPO = "davidmessenger123/scripture-windows"
API_URL = "https://api.github.com/repos/" + REPO + "/releases/latest"
RELEASE_URL = "https://github.com/" + REPO + "/releases"
ASSET_NAME = "Scripture.exe"
CHECK_TIMEOUT_MS = 10000
DOWNLOAD_TIMEOUT_MS = 120000
MAX_UPDATE_BYTES = 256 * 1024 * 1024
MAX_CHECK_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_RETRIES = 3
SIGNATURE_TIMEOUT_SECONDS = 15
PARENT_WAIT_TIMEOUT_SECONDS = 120
MAX_SIGNATURE_BYTES = 65536
MAX_JOURNAL_BYTES = 16384
POWERSHELL_BINARY = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
JOURNAL_VERSION = 2
JOURNAL_PHASES = {"prepared", "backup_ready", "new_installed", "verified"}
RELEASE_TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
VERSION_RE = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}


@dataclass(frozen=True)
class AssetInfo:
    name: str
    url: str
    size: int
    digest: str


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: tuple
    url: str
    asset: AssetInfo


@dataclass(frozen=True)
class ProcessIdentity:
    creation_time: int
    executable: str


def tag_tuple(tag: str) -> tuple:
    value = str(tag or "").strip()
    if len(value) > 64:
        return ()
    match = VERSION_RE.fullmatch(value)
    if not match:
        return ()
    return tuple(int(part) for part in match.groups())


def normalize_digest(value: str) -> str:
    value = str(value or "").strip().lower()
    if value.startswith("sha256:"):
        value = value[7:]
    return value if SHA256_RE.fullmatch(value) else ""


def safe_url(value: str, asset: bool = False) -> bool:
    raw = str(value or "")
    if len(raw) > 4096:
        return False
    try:
        parsed = urllib.parse.urlsplit(raw)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443) or parsed.fragment:
            return False
    except ValueError:
        return False
    return host in ALLOWED_HOSTS


def platform_asset_name(system: str | None = None, machine: str | None = None, version: str = "") -> str:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == "windows":
        return ASSET_NAME
    if system == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("x86_64", "amd64") else ""
        if not arch or not tag_tuple(version):
            return ""
        return "Scripture-{0}-{1}.dmg".format(version[1:], arch)
    return ""


def sha256_file(path: str, max_bytes: int = MAX_UPDATE_BYTES) -> str:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("file exceeds the size limit")
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: str, expected_digest: str, expected_size: int, max_bytes: int = MAX_UPDATE_BYTES) -> bool:
    try:
        if expected_size <= 0 or expected_size > max_bytes or os.path.getsize(path) != expected_size:
            return False
        return normalize_digest(expected_digest) == sha256_file(path, max_bytes)
    except (OSError, ValueError):
        return False


def _process_environment() -> dict:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": r"C:\Windows\System32;C:\Windows",
        "SystemRoot": r"C:\Windows",
        "WINDIR": r"C:\Windows",
    }
    for key in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(key, "")
        if value:
            environment[key] = value
    return environment


def _run_bounded(command, env, max_bytes, timeout):
    process = None
    output = bytearray()
    failure = []
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            close_fds=True,
            bufsize=0,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    def read_output():
        try:
            output.extend(process.stdout.read(max_bytes + 1))
        except (OSError, ValueError) as exc:
            failure.append(exc)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + max(0.1, min(float(timeout), 120.0))
    status = None
    while reader.is_alive():
        if time.monotonic() >= deadline:
            status = 124
            break
        if len(output) > max_bytes:
            status = 125
            break
        time.sleep(0.01)
    if status is None and len(output) > max_bytes:
        status = 125
    if status is not None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        returncode = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        returncode = process.wait()
    reader.join(timeout=1)
    try:
        process.stdout.close()
    except (OSError, ValueError):
        pass
    if failure and status is None:
        return None
    if status is not None:
        returncode = status
    return subprocess.CompletedProcess(command, returncode, bytes(output[:max_bytes]), None)


_SIGNATURE_COMMAND = (
    "$ErrorActionPreference='Stop';"
    "$s=Get-AuthenticodeSignature -LiteralPath $env:SCRIPTURE_SIGNATURE_PATH;"
    "$subject='';$thumbprint='';"
    "if($null -ne $s.SignerCertificate){$subject=[string]$s.SignerCertificate.Subject;$thumbprint=[string]$s.SignerCertificate.Thumbprint;};"
    "[ordered]@{status=[string]$s.Status;signature_type=[string]$s.SignatureType;subject=$subject;thumbprint=$thumbprint}|ConvertTo-Json -Compress"
)


def signature_record_valid(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    status = str(record.get("status") or "").strip().casefold()
    signature_type = str(record.get("signature_type") or "").strip().casefold()
    subject = str(record.get("subject") or "").strip()
    thumbprint = str(record.get("thumbprint") or "").strip()
    return bool(
        status == "valid"
        and signature_type == "authenticode"
        and subject
        and len(subject) <= 2048
        and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", thumbprint)
    )


def authenticity_decision(is_frozen: bool, is_windows: bool, hash_verified: bool, publisher_verified: bool) -> str:
    return "replace" if is_frozen and is_windows and hash_verified and publisher_verified else "browser"


def windows_authenticode_signature(path: str) -> dict | None:
    if os.name != "nt" or not os.path.isfile(path):
        return None
    environment = _process_environment()
    environment["SCRIPTURE_SIGNATURE_PATH"] = os.path.abspath(path)
    result = _run_bounded(
        [POWERSHELL_BINARY, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", _SIGNATURE_COMMAND],
        environment,
        MAX_SIGNATURE_BYTES,
        SIGNATURE_TIMEOUT_SECONDS,
    )
    if result is None or result.returncode != 0 or len(result.stdout) > MAX_SIGNATURE_BYTES:
        return None
    try:
        record = json.loads(result.stdout.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not signature_record_valid(record):
        return None
    return {
        "subject": str(record["subject"]).strip(),
        "thumbprint": str(record["thumbprint"]).strip().upper(),
        "signature_type": str(record["signature_type"]).strip().casefold(),
    }


def windows_authenticode_publisher(path: str) -> str:
    signature = windows_authenticode_signature(path)
    return str(signature["subject"]) if signature is not None else ""


def windows_authenticode_thumbprint(path: str) -> str:
    signature = windows_authenticode_signature(path)
    return str(signature["thumbprint"]) if signature is not None else ""


def _safe_windows_authenticode_signature(path: str) -> dict | None:
    try:
        return windows_authenticode_signature(path)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError):
        return None


def matching_publisher(first: str, second: str) -> bool:
    first_value = str(first or "").strip()
    second_value = str(second or "").strip()
    return bool(first_value and second_value and first_value.casefold() == second_value.casefold())


def matching_signer(first: object, second: object) -> bool:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    first_thumbprint = str(first.get("thumbprint") or "").strip().upper()
    second_thumbprint = str(second.get("thumbprint") or "").strip().upper()
    return bool(
        matching_publisher(str(first.get("subject") or ""), str(second.get("subject") or ""))
        and first_thumbprint
        and first_thumbprint == second_thumbprint
    )


def _windows_signer_match(first: str, second: str) -> bool:
    return matching_signer(_safe_windows_authenticode_signature(first), _safe_windows_authenticode_signature(second))


def parse_release(payload: dict, release_url: str = RELEASE_URL, system: str | None = None, machine: str | None = None, max_bytes: int = MAX_UPDATE_BYTES) -> ReleaseInfo | None:
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not RELEASE_TAG_RE.fullmatch(tag):
        return None
    version = tag_tuple(tag)
    if not version or any(key in payload and not isinstance(payload[key], bool) for key in ("draft", "prerelease")):
        return None
    if payload.get("draft") is True or payload.get("prerelease") is True:
        return None
    assets = payload.get("assets")
    if not isinstance(assets, list) or len(assets) > 1000:
        return None
    target_name = platform_asset_name(system, machine, str(tag))
    if not target_name:
        return None
    found = None
    for item in assets:
        if not isinstance(item, dict) or item.get("name") != target_name:
            continue
        if found is not None:
            return None
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > max_bytes:
            return None
        digest = normalize_digest(item.get("digest") or item.get("sha256"))
        if not digest:
            return None
        verification = item.get("verification")
        if verification is not None and verification is not True:
            if not isinstance(verification, dict) or verification.get("verified") is not True:
                return None
        url = item.get("browser_download_url")
        if not safe_url(url, asset=True):
            return None
        found = AssetInfo(target_name, str(url), size, digest)
    if found is None:
        return None
    page = payload.get("html_url")
    if "html_url" in payload and not isinstance(page, str):
        return None
    if not safe_url(page):
        page = release_url
    if not safe_url(page):
        return None
    return ReleaseInfo(str(tag), version, str(page), found)


class UpdateChecker(QObject):
    updateChanged = Signal()
    downloadingChanged = Signal()
    progressChanged = Signal()
    errorChanged = Signal()
    quitRequested = Signal()

    def __init__(
        self,
        current_version: str,
        parent=None,
        api_url: str = API_URL,
        release_url: str = RELEASE_URL,
        max_asset_bytes: int = MAX_UPDATE_BYTES,
    ):
        super().__init__(parent)
        self._current = tag_tuple(current_version)
        self._api_url = api_url if safe_url(api_url) else API_URL
        self._release_url = release_url if safe_url(release_url) else RELEASE_URL
        self._max_asset_bytes = min(int(max_asset_bytes), MAX_UPDATE_BYTES)
        if self._max_asset_bytes <= 0:
            self._max_asset_bytes = MAX_UPDATE_BYTES
        self._net = QNetworkAccessManager(self)
        self._reply = None
        self._check_buffer = bytearray()
        self._check_oversized = False
        self._check_session = 0
        self._dl_reply = None
        self._dl_file = None
        self._dl_path = ""
        self._dl_dir = ""
        self._dl_session = 0
        self._dl_expected_size = 0
        self._dl_expected_digest = ""
        self._dl_received = 0
        self._dl_redirects = 0
        self._dl_attempt = 0
        self._artifact_verified = False
        self._update_tag = ""
        self._update_url = ""
        self._update_available = False
        self._asset_url = ""
        self._asset_size = 0
        self._asset_digest = ""
        self._downloading = False
        self._progress = 0.0
        self._error = ""
        self._applied = False

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

    @Slot()
    def check(self) -> None:
        if self._reply is not None:
            return
        self._check_session += 1
        self._check_buffer = bytearray()
        self._check_oversized = False
        self._reply = self._request(self._api_url, "check", self._check_session, 0, self._check_headers())

    @Slot()
    def open(self) -> None:
        target = self._update_url if safe_url(self._update_url) else self._release_url
        if safe_url(target):
            QDesktopServices.openUrl(QUrl(target))

    @Slot()
    def retry(self) -> None:
        if not self._downloading and self._update_available:
            self.download()

    @Slot()
    def download(self) -> None:
        if self._downloading or self._applied or not self._update_available:
            return
        if not self._asset_url or not self._asset_size or not normalize_digest(self._asset_digest):
            self.open()
            return
        if not self._can_auto_update():
            self.open()
            return
        if not windows_authenticode_publisher(sys.executable):
            self._fail("Automatic updates require a validly signed installed build; opening the release page.")
            self.open()
            return
        if self._dl_reply is not None:
            return
        if self._dl_attempt >= MAX_RETRIES:
            self._fail("Too many update attempts; open the release page and install manually.")
            return
        self._dl_attempt += 1
        self._artifact_verified = False
        self._cleanup_download()
        self._error = ""
        self._progress = 0.0
        self._dl_session += 1
        self._dl_received = 0
        self._dl_redirects = 0
        self._dl_expected_size = self._asset_size
        self._dl_expected_digest = self._asset_digest
        try:
            self._dl_dir = tempfile.mkdtemp(prefix="scripture-update-")
            name = "Scripture.new.exe" if platform.system().lower() == "windows" else "Scripture.new.dmg"
            self._dl_path = os.path.join(self._dl_dir, name)
            self._dl_file = open(self._dl_path, "xb")
        except OSError as exc:
            self._fail("Could not prepare the update download: %s" % exc)
            return
        self._downloading = True
        self.progressChanged.emit()
        self.errorChanged.emit()
        self.downloadingChanged.emit()
        try:
            self._dl_reply = self._request(self._asset_url, "download", self._dl_session, self._asset_size, self._download_headers())
        except (OSError, RuntimeError, ValueError) as exc:
            self._fail("Could not start the update download: %s" % exc)

    @Slot()
    def apply(self) -> None:
        if self._applied or not self._artifact_verified or not self._dl_path or not os.path.isfile(self._dl_path):
            self._fail("The downloaded update failed verification; please try again.")
            return
        if not self._can_auto_update():
            self.open()
            return
        hash_verified = verify_file(self._dl_path, self._dl_expected_digest, self._dl_expected_size, self._max_asset_bytes)
        publisher_verified = _windows_signer_match(sys.executable, self._dl_path)
        decision = authenticity_decision(
            bool(getattr(sys, "frozen", False)),
            platform.system().lower() == "windows",
            hash_verified,
            publisher_verified,
        )
        if decision != "replace":
            self._fail("The update is unsigned or has a different publisher; opening the release page.")
            self.open()
            return
        try:
            self._start_update_helper()
        except (OSError, RuntimeError, ValueError) as exc:
            self._fail("Could not start the updater: %s" % exc)
            return
        self._applied = True
        self.updateChanged.emit()
        self.quitRequested.emit()

    def _can_auto_update(self) -> bool:
        return bool(getattr(sys, "frozen", False) and platform.system().lower() == "windows")

    def _check_headers(self) -> dict:
        return {b"Accept": b"application/vnd.github+json", b"User-Agent": ("scripture-windows/" + __version__).encode("ascii"), b"X-GitHub-Api-Version": b"2022-11-28"}

    def _download_headers(self) -> dict:
        return {b"Accept": b"application/octet-stream", b"User-Agent": ("scripture-windows/" + __version__).encode("ascii")}

    def _request(self, url: str, kind: str, session: int, expected_size: int, headers: dict) -> QNetworkReply:
        if not safe_url(url, asset=(kind == "download")):
            raise ValueError("unsafe update URL")
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(CHECK_TIMEOUT_MS if kind == "check" else DOWNLOAD_TIMEOUT_MS)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setMaximumRedirectsAllowed(MAX_REDIRECTS)
        for name, value in headers.items():
            request.setRawHeader(name, value)
        reply = self._net.get(request)
        reply.setProperty("_kind", kind)
        reply.setProperty("_session", session)
        reply.setProperty("_redirects", 0)
        reply.setProperty("_redirecting", False)
        reply.readyRead.connect(lambda r=reply: self._on_ready(r))
        reply.redirected.connect(lambda target, r=reply: self._on_redirected(r, target))
        reply.finished.connect(lambda r=reply: self._on_finished(r))
        if kind == "download":
            reply.downloadProgress.connect(self._on_dl_progress)
        return reply

    def _on_dl_progress(self, received: int, total: int) -> None:
        if self._dl_reply is None or self._dl_expected_size <= 0:
            return
        if total > self._max_asset_bytes or received > self._max_asset_bytes:
            self._fail("Download exceeds the verified artifact size.")
            return
        expected = self._dl_expected_size
        self._progress = max(0.0, min(1.0, received / max(1, expected)))
        self.progressChanged.emit()

    def _on_ready(self, reply: QNetworkReply) -> None:
        kind = reply.property("_kind")
        if kind == "check" and reply is self._reply:
            self._drain_check(reply)
        elif kind == "download" and reply is self._dl_reply:
            self._drain_download(reply)

    def _drain_check(self, reply: QNetworkReply) -> None:
        while reply.bytesAvailable():
            remaining = MAX_CHECK_BYTES + 1 - len(self._check_buffer)
            if remaining <= 0:
                self._check_oversized = True
                reply.abort()
                return
            chunk = bytes(reply.read(min(65536, remaining)))
            if not chunk:
                break
            self._check_buffer.extend(chunk)
            if len(self._check_buffer) > MAX_CHECK_BYTES:
                self._check_oversized = True
                reply.abort()
                return

    def _drain_download(self, reply: QNetworkReply) -> None:
        try:
            declared = int(reply.header(QNetworkRequest.KnownHeaders.ContentLengthHeader))
        except (TypeError, ValueError):
            declared = 0
        if declared > self._max_asset_bytes or declared > self._dl_expected_size:
            self._fail("Download exceeds the verified artifact size.")
            reply.abort()
            return
        if self._dl_file is None:
            self._fail("Could not save the update.")
            reply.abort()
            return
        try:
            while reply.bytesAvailable():
                chunk = bytes(reply.read(min(65536, self._max_asset_bytes - self._dl_received + 1)))
                if not chunk:
                    break
                self._dl_received += len(chunk)
                if self._dl_received > self._max_asset_bytes or self._dl_received > self._dl_expected_size:
                    self._fail("Download exceeds the verified artifact size.")
                    reply.abort()
                    return
                self._dl_file.write(chunk)
            self._progress = min(1.0, self._dl_received / max(1, self._dl_expected_size))
            self.progressChanged.emit()
            self._dl_file.flush()
        except OSError as exc:
            self._fail("Could not save the update: %s" % exc)
            reply.abort()

    def _follow_redirect(self, reply: QNetworkReply, target: QUrl) -> bool:
        if reply is not self._reply and reply is not self._dl_reply:
            return False
        kind = str(reply.property("_kind"))
        hops = int(reply.property("_redirects") or 0) + 1
        if hops > MAX_REDIRECTS or not safe_url(target.toString(), asset=(kind == "download")):
            if kind == "download":
                self._fail("Update download redirected to an untrusted location.")
            else:
                self._reply = None
            return True
        reply.setProperty("_redirecting", True)
        if kind == "check":
            self._check_buffer = bytearray()
        else:
            if self._dl_file is None:
                self._fail("Could not save the update.")
                return True
            try:
                self._dl_file.flush()
                self._dl_file.seek(0)
                self._dl_file.truncate(0)
            except OSError:
                self._fail("Could not save the update.")
                return True
            self._dl_received = 0
        try:
            if kind == "check":
                self._reply = self._request(target.toString(), kind, self._check_session, 0, self._check_headers())
                new_reply = self._reply
            else:
                self._dl_redirects = hops
                self._dl_reply = self._request(target.toString(), kind, self._dl_session, self._dl_expected_size, self._download_headers())
                new_reply = self._dl_reply
            new_reply.setProperty("_redirects", hops)
        except (ValueError, RuntimeError):
            if kind == "download":
                self._fail("Could not follow the update download redirect.")
            else:
                self._reply = None
        return True

    def _on_redirected(self, reply: QNetworkReply, target: QUrl) -> None:
        if self._follow_redirect(reply, target):
            reply.abort()

    def _on_finished(self, reply: QNetworkReply) -> None:
        kind = str(reply.property("_kind"))
        if kind == "check":
            if reply is not self._reply:
                reply.deleteLater()
                return
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            location = reply.rawHeader("Location")
            if status in REDIRECT_STATUSES and location:
                try:
                    target = reply.url().resolved(QUrl(bytes(location).decode("ascii")))
                except (UnicodeDecodeError, ValueError):
                    target = QUrl()
                if self._follow_redirect(reply, target):
                    reply.deleteLater()
                    return
            self._reply = None
            if reply.property("_redirecting"):
                reply.deleteLater()
                return
            self._drain_check(reply)
            error = reply.error()
            data = bytes(self._check_buffer)
            self._check_buffer = bytearray()
            oversized = self._check_oversized
            self._check_oversized = False
            reply.deleteLater()
            if oversized or error != QNetworkReply.NetworkError.NoError or status != 200:
                return
            self._consume_release(data)
            return
        if kind == "download":
            if reply is not self._dl_reply:
                reply.deleteLater()
                return
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            location = reply.rawHeader("Location")
            if status in REDIRECT_STATUSES and location:
                try:
                    target = reply.url().resolved(QUrl(bytes(location).decode("ascii")))
                except (UnicodeDecodeError, ValueError):
                    target = QUrl()
                if self._follow_redirect(reply, target):
                    reply.deleteLater()
                    return
            self._dl_reply = None
            if reply.property("_redirecting"):
                reply.deleteLater()
                return
            self._finish_download(reply)

    def _consume_release(self, data: bytes) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        release = parse_release(payload, self._release_url, max_bytes=self._max_asset_bytes)
        if release is None or release.version <= self._current:
            return
        if release.tag != self._update_tag:
            if self._dl_reply is not None:
                old_reply = self._dl_reply
                self._dl_reply = None
                old_reply.abort()
            self._downloading = False
            self._cleanup_download()
            self._dl_attempt = 0
            self._error = ""
        self._update_tag = release.tag
        self._update_url = release.url
        self._asset_url = release.asset.url
        self._asset_size = release.asset.size
        self._asset_digest = release.asset.digest
        self._update_available = True
        self.updateChanged.emit()

    def _finish_download(self, reply: QNetworkReply) -> None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        content_length = reply.header(QNetworkRequest.KnownHeaders.ContentLengthHeader)
        reply.deleteLater()
        if self._dl_file is not None:
            try:
                self._dl_file.flush()
                os.fsync(self._dl_file.fileno())
                self._dl_file.close()
            except OSError as exc:
                self._dl_file = None
                self._fail("Could not save the update: %s" % exc)
                return
            self._dl_file = None
        if error != QNetworkReply.NetworkError.NoError or status != 200:
            self._fail("Download failed; open the release page and install manually.")
            return
        try:
            expected_length = int(content_length)
        except (TypeError, ValueError):
            expected_length = 0
        if expected_length and expected_length != self._dl_expected_size:
            self._fail("Download size does not match the release metadata.")
            return
        if self._dl_received != self._dl_expected_size or not verify_file(self._dl_path, self._dl_expected_digest, self._dl_expected_size, self._max_asset_bytes):
            self._fail("The downloaded update failed hash or size verification.")
            return
        self._artifact_verified = True
        self._downloading = False
        self._progress = 1.0
        self.progressChanged.emit()
        self.downloadingChanged.emit()

    def _start_update_helper(self) -> None:
        if not self._dl_dir:
            raise RuntimeError("download directory is missing")
        target = os.path.abspath(sys.executable)
        parent_identity = _process_identity(os.getpid())
        if parent_identity is None or _normalized_executable(parent_identity.executable) != _normalized_executable(target):
            raise RuntimeError("could not identify the parent process")
        helper_dir = tempfile.mkdtemp(prefix="scripture-update-helper-")
        helper_path = os.path.join(helper_dir, "Scripture-update-helper.exe")
        shutil.copyfile(sys.executable, helper_path)
        pending = os.path.abspath(self._dl_path)
        if not _windows_signer_match(target, helper_path):
            shutil.rmtree(helper_dir, ignore_errors=True)
            raise RuntimeError("the updater helper is not signed by the installed publisher")
        try:
            subprocess.Popen(
                [
                    helper_path,
                    "--scripture-apply-update",
                    target,
                    pending,
                    self._dl_expected_digest,
                    str(self._dl_expected_size),
                    str(os.getpid()),
                    str(parent_identity.creation_time),
                    parent_identity.executable,
                    helper_path,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_process_environment(),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except (OSError, subprocess.SubprocessError):
            shutil.rmtree(helper_dir, ignore_errors=True)
            raise
        self._cleanup_download(remove_path=False)
        self._dl_path = ""
        self._artifact_verified = False

    def _fail(self, message: str) -> None:
        if self._dl_reply is not None:
            reply = self._dl_reply
            self._dl_reply = None
            reply.abort()
        self._downloading = False
        self._artifact_verified = False
        self._error = str(message)
        self._cleanup_download()
        self.progressChanged.emit()
        self.downloadingChanged.emit()
        self.errorChanged.emit()

    def _cleanup_download(self, remove_path: bool = True) -> None:
        if self._dl_file is not None:
            try:
                self._dl_file.close()
            except OSError:
                pass
            self._dl_file = None
        if remove_path and self._dl_dir:
            shutil.rmtree(self._dl_dir, ignore_errors=True)
        if remove_path:
            self._dl_dir = ""
            self._dl_path = ""
        self._dl_received = 0


def _normalized_executable(path: str) -> str:
    try:
        value = os.fsdecode(os.fspath(path))
        value = os.path.normcase(os.path.realpath(os.path.abspath(value)))
        if os.name == "nt":
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
        return value
    except (OSError, TypeError, ValueError):
        return ""


def _open_windows_process(pid: int):
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        kernel32 = ctypes.WinDLL(os.path.join(system_root, "System32", "kernel32.dll"), use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x0400 | 0x1000 | 0x00100000, 0, pid)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if not handle:
        return None
    return ctypes, kernel32, handle, wintypes


def _windows_identity_from_handle(ctypes_module, kernel32, handle, wintypes):
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes_module.byref(creation),
            ctypes_module.byref(exit_time),
            ctypes_module.byref(kernel_time),
            ctypes_module.byref(user_time),
        ):
            return None
        creation_time = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        buffer = ctypes_module.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes_module.byref(length)):
            return None
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    executable = _normalized_executable(buffer.value)
    if creation_time <= 0 or not executable:
        return None
    return ProcessIdentity(creation_time, executable)


def _windows_process_identity(pid: int) -> ProcessIdentity | None:
    opened = _open_windows_process(pid)
    if opened is None:
        return None
    ctypes_module, kernel32, handle, wintypes = opened
    try:
        return _windows_identity_from_handle(ctypes_module, kernel32, handle, wintypes)
    finally:
        try:
            kernel32.CloseHandle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            pass


def _posix_process_identity(pid: int) -> ProcessIdentity | None:
    try:
        with open("/proc/{0}/stat".format(pid), "r", encoding="ascii") as handle:
            stat_line = handle.read(4096)
        separator = stat_line.rfind(")")
        if separator < 0:
            return None
        fields = stat_line[separator + 2 :].split()
        creation_time = int(fields[19])
        executable = os.readlink("/proc/{0}/exe".format(pid))
    except (IndexError, OSError, UnicodeError, ValueError):
        return None
    executable = _normalized_executable(executable)
    if creation_time < 0 or not executable:
        return None
    return ProcessIdentity(creation_time, executable)


def _process_identity(pid: int) -> ProcessIdentity | None:
    if pid <= 0 or pid > 0xFFFFFFFF:
        return None
    if os.name == "nt":
        return _windows_process_identity(pid)
    return _posix_process_identity(pid)


def _identity_matches(identity: object, creation_time: int, executable: str) -> bool:
    if not isinstance(identity, ProcessIdentity):
        return False
    expected_executable = _normalized_executable(executable)
    return bool(
        expected_executable
        and identity.creation_time == creation_time
        and _normalized_executable(identity.executable) == expected_executable
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        kernel32 = ctypes.WinDLL(os.path.join(system_root, "System32", "kernel32.dll"), use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, 0, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_parent(pid: int, creation_time: int | None = None, executable: str | None = None) -> bool:
    try:
        expected_creation = int(creation_time) if creation_time is not None else -1
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid > 0xFFFFFFFF or expected_creation < 0 or not executable or not _normalized_executable(executable):
        return False
    if os.name == "nt":
        opened = _open_windows_process(pid)
        if opened is None:
            import ctypes

            return ctypes.get_last_error() in (87, 1168)
        ctypes_module, kernel32, handle, wintypes = opened
        try:
            current = _windows_identity_from_handle(ctypes_module, kernel32, handle, wintypes)
            if current is None:
                return False
            if not _identity_matches(current, expected_creation, executable):
                return False
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            return kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0
        finally:
            try:
                kernel32.CloseHandle(handle)
            except (AttributeError, OSError, TypeError, ValueError):
                pass
    deadline = time.monotonic() + PARENT_WAIT_TIMEOUT_SECONDS
    while True:
        current = _process_identity(pid)
        if current is None:
            return not _pid_alive(pid)
        if not _identity_matches(current, expected_creation, executable):
            return False
        if not _pid_alive(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _copy_atomic(source: str, destination: str) -> None:
    with open(source, "rb") as src, open(destination, "xb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _is_update_temp_path(path: str, prefix: str) -> bool:
    try:
        candidate = Path(path).resolve()
        root = Path(tempfile.gettempdir()).resolve()
        return candidate.parent.parent == root and candidate.parent.name.startswith(prefix)
    except OSError:
        return False


def _journal_path(target: str) -> str:
    return os.path.abspath(target) + ".scripture-update-journal.json"


def _same_path(first: str, second: str) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _valid_journal(payload: object, target: str) -> dict | None:
    if not isinstance(payload, dict) or payload.get("version") != JOURNAL_VERSION:
        return None
    phase = payload.get("phase")
    update_id = payload.get("update_id")
    digest = normalize_digest(payload.get("digest"))
    size = payload.get("size")
    publisher = payload.get("publisher")
    thumbprint = str(payload.get("thumbprint") or "").strip().upper()
    backup_digest = normalize_digest(payload.get("backup_digest"))
    backup_size = payload.get("backup_size")
    recorded_target = payload.get("target")
    backup = payload.get("backup")
    staged = payload.get("staged")
    pending = payload.get("pending")
    if phase not in JOURNAL_PHASES or not isinstance(update_id, str) or not re.fullmatch(r"[0-9a-f]{32}", update_id):
        return None
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > MAX_UPDATE_BYTES or not digest:
        return None
    if not isinstance(publisher, str) or not publisher.strip() or len(publisher) > 2048:
        return None
    if not re.fullmatch(r"[0-9A-F]{40}|[0-9A-F]{64}", thumbprint):
        return None
    if not backup_digest or isinstance(backup_size, bool) or not isinstance(backup_size, int) or backup_size <= 0 or backup_size > MAX_UPDATE_BYTES:
        return None
    if not all(isinstance(value, str) and value for value in (recorded_target, backup, staged, pending)):
        return None
    target_path = os.path.abspath(target)
    if not _same_path(recorded_target, target_path):
        return None
    if not _same_path(backup, target_path + ".scripture-backup-" + update_id):
        return None
    if not _same_path(staged, target_path + ".scripture-staged-" + update_id):
        return None
    if not _is_update_temp_path(pending, "scripture-update-") or os.path.basename(os.path.dirname(pending)).startswith("scripture-update-helper-"):
        return None
    return {
        "version": JOURNAL_VERSION,
        "phase": phase,
        "update_id": update_id,
        "digest": digest,
        "size": size,
        "publisher": publisher.strip(),
        "thumbprint": thumbprint,
        "backup_digest": backup_digest,
        "backup_size": backup_size,
        "target": target_path,
        "backup": os.path.abspath(backup),
        "staged": os.path.abspath(staged),
        "pending": os.path.abspath(pending),
    }


def _read_update_journal(target: str) -> dict | None:
    path = _journal_path(target)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_JOURNAL_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("could not read the update journal") from exc
    if len(raw) > MAX_JOURNAL_BYTES:
        raise ValueError("update journal exceeds the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("update journal is invalid") from exc
    journal = _valid_journal(payload, target)
    if journal is None:
        raise ValueError("update journal failed validation")
    return journal


def _fsync_directory(path: str) -> None:
    if os.name == "nt":
        return
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_update_journal(target: str, journal: dict) -> None:
    path = _journal_path(target)
    validated = _valid_journal(journal, target)
    if validated is None:
        raise ValueError("refusing to write an invalid update journal")
    payload = (json.dumps(validated, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = -1
    temporary = ""
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path))
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
        _fsync_directory(os.path.dirname(path))
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _remove_update_journal(target: str) -> None:
    try:
        os.unlink(_journal_path(target))
    except FileNotFoundError:
        return
    _fsync_directory(os.path.dirname(os.path.abspath(target)))


def _remove_pending_update(pending: str) -> None:
    _remove(pending)
    try:
        directory = os.path.dirname(pending)
        if os.path.basename(directory).startswith("scripture-update-") and not os.path.basename(directory).startswith("scripture-update-helper-"):
            os.rmdir(directory)
    except OSError:
        pass


def _finish_update_artifacts(target: str, journal: dict) -> bool:
    _remove(journal["backup"])
    _remove(journal["staged"])
    _remove_pending_update(journal["pending"])
    if any(os.path.lexists(journal[key]) for key in ("backup", "staged", "pending")):
        return False
    _remove_update_journal(target)
    return True


def recovery_decision(
    phase: str,
    target_exists: bool,
    target_valid: bool,
    backup_valid: bool,
    candidate_valid: bool,
    target_rollback_valid: bool = False,
) -> str:
    if target_valid:
        return "commit"
    if candidate_valid:
        return "promote"
    if backup_valid:
        return "restore_backup"
    if target_rollback_valid:
        return "keep_current"
    return "abort"


def _signature_matches_journal(signature: object, journal: dict) -> bool:
    if not isinstance(signature, dict):
        return False
    return bool(
        matching_publisher(str(signature.get("subject") or ""), journal["publisher"])
        and str(signature.get("thumbprint") or "").strip().upper() == journal["thumbprint"]
    )


def _authentic_update_artifact(path: str, journal: dict) -> bool:
    return bool(
        verify_file(path, journal["digest"], journal["size"])
        and _signature_matches_journal(_safe_windows_authenticode_signature(path), journal)
    )


def _authentic_backup_artifact(path: str, journal: dict) -> bool:
    return bool(
        verify_file(path, journal["backup_digest"], journal["backup_size"])
        and _signature_matches_journal(_safe_windows_authenticode_signature(path), journal)
    )


def recover_interrupted_update(target: str) -> bool:
    target = os.path.abspath(target)
    try:
        journal = _read_update_journal(target)
    except ValueError:
        return False
    if journal is None:
        return True
    target_exists = os.path.isfile(target)
    target_signature = _safe_windows_authenticode_signature(target) if target_exists else None
    target_valid = bool(
        target_exists
        and verify_file(target, journal["digest"], journal["size"])
        and _signature_matches_journal(target_signature, journal)
    )
    target_rollback_valid = bool(
        not target_valid
        and target_exists
        and verify_file(target, journal["backup_digest"], journal["backup_size"])
        and _signature_matches_journal(target_signature, journal)
    )
    backup_exists = os.path.isfile(journal["backup"])
    backup_valid = backup_exists and _authentic_backup_artifact(journal["backup"], journal)
    candidate_exists = os.path.isfile(journal["staged"])
    candidate_valid = candidate_exists and _authentic_update_artifact(journal["staged"], journal)
    decision = recovery_decision(
        journal["phase"], target_exists, target_valid, backup_valid, candidate_valid, target_rollback_valid
    )
    try:
        if decision == "commit":
            return _finish_update_artifacts(target, journal)
        if decision == "promote":
            os.replace(journal["staged"], target)
            return _finish_update_artifacts(target, journal)
        if decision == "keep_current":
            return _finish_update_artifacts(target, journal)
        if decision == "restore_backup":
            os.replace(journal["backup"], target)
            return _finish_update_artifacts(target, journal)
    except (OSError, ValueError):
        return False
    return False


def _launch_installed_target(target: str, helper: str, expected: object = None) -> bool:
    signature = _safe_windows_authenticode_signature(target)
    if signature is None or (expected is not None and not matching_signer(expected, signature)):
        return False
    subprocess.Popen(
        [target, "--scripture-cleanup-helper", helper],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=_process_environment(),
    )
    return True


def _relaunch_after_wait(target: str, helper: str, expected: object = None) -> bool:
    for attempt in range(3):
        try:
            current = _safe_windows_authenticode_signature(target)
            if current is not None and (expected is None or matching_signer(expected, current)):
                if _launch_installed_target(target, helper, current):
                    return True
        except (OSError, TypeError, ValueError, subprocess.SubprocessError):
            pass
        if attempt < 2:
            time.sleep(0.1)
    return False


def _restart_existing_target(
    pid: int,
    target: str,
    helper: str,
    creation_time: int | None = None,
    executable: str | None = None,
) -> bool:
    try:
        expected = _safe_windows_authenticode_signature(target)
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        expected = None
    if not _wait_for_parent(pid, creation_time, executable):
        return False
    return _relaunch_after_wait(target, helper, expected)


def run_update_helper(args: list[str]) -> int:
    if len(args) != 8:
        return 2
    target, pending, digest, size_text, pid_text, creation_time_text, parent_executable, helper = args
    try:
        pid = int(pid_text)
        expected_size = int(size_text)
        creation_time = int(creation_time_text)
    except (TypeError, ValueError):
        return 2
    expected_digest = normalize_digest(digest)
    if (
        pid <= 0
        or pid > 0xFFFFFFFF
        or expected_size <= 0
        or expected_size > MAX_UPDATE_BYTES
        or creation_time < 0
        or not expected_digest
        or not parent_executable
    ):
        return 2
    target = os.path.abspath(target)
    pending = os.path.abspath(pending)
    helper = os.path.abspath(helper)
    parent_executable = _normalized_executable(parent_executable)
    if not parent_executable or _normalized_executable(target) != parent_executable:
        return 2
    if (
        not target.lower().endswith(".exe")
        or os.path.basename(helper).lower() != "scripture-update-helper.exe"
        or _is_update_temp_path(target, "scripture-update-")
        or not _is_update_temp_path(pending, "scripture-update-")
        or not _is_update_temp_path(helper, "scripture-update-helper-")
    ):
        return 2
    if not os.path.isfile(target) or not os.path.isfile(pending) or not os.path.isfile(helper):
        _restart_existing_target(pid, target, helper, creation_time, parent_executable)
        return 1
    if not verify_file(pending, expected_digest, expected_size):
        _restart_existing_target(pid, target, helper, creation_time, parent_executable)
        return 1
    target_signature = _safe_windows_authenticode_signature(target)
    if target_signature is None:
        _restart_existing_target(pid, target, helper, creation_time, parent_executable)
        return 1
    if not matching_signer(target_signature, _safe_windows_authenticode_signature(helper)):
        _restart_existing_target(pid, target, helper, creation_time, parent_executable)
        return 1
    if not matching_signer(target_signature, _safe_windows_authenticode_signature(pending)):
        _restart_existing_target(pid, target, helper, creation_time, parent_executable)
        return 1
    if not _wait_for_parent(pid, creation_time, parent_executable):
        return 1
    current_signature = _safe_windows_authenticode_signature(target)
    if current_signature is None or not matching_signer(target_signature, current_signature):
        _relaunch_after_wait(target, helper, target_signature)
        return 1
    if not _windows_signer_match(target, helper) or not _windows_signer_match(target, pending):
        _relaunch_after_wait(target, helper, target_signature)
        return 1
    update_id = uuid.uuid4().hex
    backup = target + ".scripture-backup-" + update_id
    staged = target + ".scripture-staged-" + update_id
    journal = {
        "version": JOURNAL_VERSION,
        "phase": "prepared",
        "update_id": update_id,
        "digest": expected_digest,
        "size": expected_size,
        "publisher": str(target_signature["subject"]),
        "thumbprint": str(target_signature["thumbprint"]),
        "backup_digest": "",
        "backup_size": 0,
        "target": target,
        "backup": backup,
        "staged": staged,
        "pending": pending,
    }
    launched = False
    try:
        journal["backup_size"] = os.path.getsize(target)
        journal["backup_digest"] = sha256_file(target, MAX_UPDATE_BYTES)
        _copy_atomic(pending, staged)
        if not verify_file(staged, expected_digest, expected_size) or not matching_signer(target_signature, _safe_windows_authenticode_signature(staged)):
            raise OSError("staged update verification failed")
        _write_update_journal(target, journal)
        _copy_atomic(target, backup)
        if not _authentic_backup_artifact(backup, journal):
            raise OSError("backup update verification failed")
        journal["phase"] = "backup_ready"
        _write_update_journal(target, journal)
        os.replace(staged, target)
        journal["phase"] = "new_installed"
        _write_update_journal(target, journal)
        if not verify_file(target, expected_digest, expected_size) or not matching_signer(target_signature, _safe_windows_authenticode_signature(target)):
            raise OSError("installed update verification failed")
        journal["phase"] = "verified"
        _write_update_journal(target, journal)
        if not _launch_installed_target(target, helper, target_signature):
            raise OSError("installed update signature changed before launch")
        launched = True
        return 0 if _finish_update_artifacts(target, journal) else 1
    except (OSError, ValueError, subprocess.SubprocessError):
        recovered = False
        if os.path.lexists(_journal_path(target)):
            recovered = recover_interrupted_update(target)
        if not recovered:
            _remove(staged)
            if not os.path.lexists(_journal_path(target)):
                _remove_pending_update(pending)
        if not launched:
            _relaunch_after_wait(target, helper, target_signature)
        return 0 if recovered else 1


def cleanup_stale_update_helpers() -> None:
    root = tempfile.gettempdir()
    cutoff = time.time() - 3600
    try:
        entries = list(Path(root).glob("scripture-update-*"))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.lstat().st_mtime >= cutoff:
                continue
            if entry.is_symlink() or not entry.is_dir():
                entry.unlink()
            elif entry.name.startswith("scripture-update-helper-") or entry.name.startswith("scripture-update-"):
                shutil.rmtree(entry)
        except OSError:
            continue
