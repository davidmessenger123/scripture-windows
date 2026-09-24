import ctypes
import os
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .errors import SecretStoreError


KEYCHAIN_SERVICE = "org.davidjm.scripture.esv"
KEYCHAIN_ACCOUNT = "current-user"
SECURITY_BINARY = "/usr/bin/security"
MAX_SECRET_FILE_BYTES = 8192


def _helper_environment() -> dict:
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for key in ("HOME", "TMPDIR"):
        value = os.environ.get(key, "")
        if value:
            environment[key] = value
    return environment


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class SecretStore:
    def __init__(self, data_dir: str):
        self._path = Path(data_dir) / "esv-api-key"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> str:
        if sys.platform == "darwin":
            return _keychain_load()
        try:
            with self._path.open("rb", buffering=0) as handle:
                data = handle.read(MAX_SECRET_FILE_BYTES + 1)
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise SecretStoreError("could not read the stored API key") from exc
        if len(data) > MAX_SECRET_FILE_BYTES:
            raise SecretStoreError("stored API key exceeds the size limit")
        try:
            mode = stat.S_IMODE(self._path.stat().st_mode)
        except OSError as exc:
            raise SecretStoreError("could not inspect the stored API key") from exc
        if os.name != "nt" and mode & 0o077:
            raise SecretStoreError("stored API key permissions are too broad")
        try:
            if os.name == "nt":
                value = _dpapi_unprotect(data).decode("utf-8")
            else:
                value = data.decode("utf-8")
        except (UnicodeDecodeError, ValueError, OSError, AttributeError) as exc:
            raise SecretStoreError("stored API key is invalid") from exc
        return _validate(value)

    def save(self, value: str) -> None:
        value = _validate(value)
        if sys.platform == "darwin":
            _keychain_save(value)
            return
        if not value:
            self.clear()
            return
        try:
            payload = _dpapi_protect(value.encode("utf-8")) if os.name == "nt" else value.encode("utf-8")
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError, AttributeError) as exc:
            raise SecretStoreError("could not prepare the API key store") from exc
        fd = -1
        tmp_name = ""
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=".esv-key.", dir=str(self._path.parent))
            if hasattr(os, "fchmod"):
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "wb") as fh:
                fd = -1
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self._path)
            tmp_name = ""
            _fsync_directory(self._path.parent)
        except OSError as exc:
            raise SecretStoreError("could not save the API key") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass

    def clear(self) -> None:
        if sys.platform == "darwin":
            _keychain_clear()
            return
        try:
            self._path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise SecretStoreError("could not remove the stored API key") from exc


def _kill_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def _run_bounded(command, input_bytes=None, max_bytes=513, timeout=5):
    process = None
    selector = None
    output = bytearray()
    status = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_helper_environment(),
            start_new_session=True,
            close_fds=True,
            bufsize=0,
        )
        if input_bytes is not None and process.stdin is not None:
            try:
                process.stdin.write(input_bytes)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + max(0.1, min(float(timeout), 30.0))
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = 124
                _kill_process_group(process)
                break
            for key, _ in selector.select(min(0.25, remaining)):
                chunk = os.read(key.fileobj.fileno(), min(4096, max_bytes - len(output) + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > max_bytes:
                    status = 125
                    _kill_process_group(process)
                    break
            if status is not None:
                break
        if status is None:
            try:
                status = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                status = 124
                _kill_process_group(process)
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        if process is not None:
            _kill_process_group(process)
        return None
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            for stream in (process.stdout, process.stdin):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if status is not None and process.poll() is None:
                try:
                    process.wait(timeout=1)
                except (OSError, subprocess.SubprocessError):
                    pass
    return subprocess.CompletedProcess(command, status, bytes(output[:max_bytes]), None)


def _keychain_load() -> str:
    result = _run_bounded(
        [SECURITY_BINARY, "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"],
        max_bytes=513,
        timeout=5,
    )
    if result is None:
        raise SecretStoreError("could not read the macOS keychain")
    if result.returncode != 0:
        if result.returncode == 44:
            return ""
        raise SecretStoreError("could not read the macOS keychain")
    try:
        value = result.stdout.decode("utf-8").rstrip("\n")
    except UnicodeDecodeError as exc:
        raise SecretStoreError("could not read the macOS keychain") from exc
    return _validate(value)


def _keychain_save(value: str) -> None:
    if not value:
        _keychain_clear()
        return
    command = "add-generic-password -U -a {} -s {} -w {}\n".format(
        shlex.quote(KEYCHAIN_ACCOUNT), shlex.quote(KEYCHAIN_SERVICE), shlex.quote(value)
    )
    result = _run_bounded([SECURITY_BINARY, "-i"], command.encode("utf-8"), max_bytes=1, timeout=5)
    if result is None or result.returncode != 0:
        raise SecretStoreError("could not save the macOS keychain")


def _keychain_clear() -> None:
    try:
        result = subprocess.run(
            [SECURITY_BINARY, "delete-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            env=_helper_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecretStoreError("could not remove the macOS keychain") from exc
    if result.returncode not in (0, 44):
        raise SecretStoreError("could not remove the macOS keychain")


def _validate(value: str) -> str:
    value = str(value or "").strip()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise SecretStoreError("API key is not valid Unicode") from exc
    if size > 512:
        raise SecretStoreError("API key exceeds the size limit")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SecretStoreError("API key contains control characters")
    return value


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(str(path), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return DATA_BLOB(len(data), pointer), buffer


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        return data
    source, source_buffer = _blob(data)
    result = DATA_BLOB()
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    crypt32 = ctypes.WinDLL(os.path.join(system_root, "System32", "crypt32.dll"), use_last_error=True)
    kernel32 = ctypes.WinDLL(os.path.join(system_root, "System32", "kernel32.dll"), use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not crypt32.CryptProtectData(ctypes.byref(source), "Scripture ESV API key", None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        return data
    source, source_buffer = _blob(data)
    result = DATA_BLOB()
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    crypt32 = ctypes.WinDLL(os.path.join(system_root, "System32", "crypt32.dll"), use_last_error=True)
    kernel32 = ctypes.WinDLL(os.path.join(system_root, "System32", "kernel32.dll"), use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    description = ctypes.c_wchar_p()
    if not crypt32.CryptUnprotectData(ctypes.byref(source), ctypes.byref(description), None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
