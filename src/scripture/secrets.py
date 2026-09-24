import ctypes
import os
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import threading
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
    killpg = getattr(os, "killpg", None)
    if os.name != "nt" and killpg is not None:
        try:
            kill_signal = getattr(signal, "SIGKILL", getattr(signal, "SIGTERM", 9))
            killpg(process.pid, kill_signal)
            return
        except (AttributeError, NotImplementedError, OSError):
            pass
    try:
        process.kill()
    except (AttributeError, NotImplementedError, OSError):
        pass


def _run_bounded(command, input_bytes=None, max_bytes=513, timeout=5):
    try:
        output_limit = int(max_bytes)
        timeout_limit = max(0.1, min(float(timeout), 30.0))
    except (OverflowError, TypeError, ValueError):
        return None
    if output_limit < 0:
        return None

    process = None
    reader = None
    writer = None
    output = bytearray()
    reader_failure = []
    status = None
    read_failed = False
    try:
        popen_options = {
            "stdin": subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "env": _helper_environment(),
            "close_fds": True,
            "bufsize": 0,
        }
        if os.name != "nt":
            popen_options["start_new_session"] = True
        process = subprocess.Popen(command, **popen_options)

        def read_output():
            stream = process.stdout
            if stream is None:
                return
            try:
                while len(output) <= output_limit:
                    remaining = output_limit + 1 - len(output)
                    chunk = stream.read(min(4096, remaining))
                    if not chunk:
                        return
                    if len(chunk) > remaining:
                        output.extend(chunk[:remaining])
                        return
                    output.extend(chunk)
            except (OSError, TypeError, ValueError) as exc:
                reader_failure.append(exc)

        def write_input():
            stream = process.stdin
            if stream is None:
                return
            try:
                remaining = memoryview(input_bytes)
                while len(remaining):
                    written = stream.write(remaining)
                    if not isinstance(written, int) or written <= 0:
                        break
                    remaining = remaining[written:]
                try:
                    stream.flush()
                except (OSError, ValueError):
                    pass
            except (OSError, TypeError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        if input_bytes is not None and process.stdin is not None:
            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()

        deadline = time.monotonic() + timeout_limit
        while reader.is_alive() or (writer is not None and writer.is_alive()) or process.poll() is None:
            if len(output) > output_limit:
                status = 125
                break
            if reader_failure:
                read_failed = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = 124
                break
            time.sleep(min(0.01, remaining))

        if status is None and len(output) > output_limit:
            status = 125
        if status is None and reader_failure:
            read_failed = True
        if status is not None or read_failed:
            _kill_process_group(process)

        try:
            returncode = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if status is None:
                status = 124
            _kill_process_group(process)
            try:
                returncode = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _kill_process_group(process)
                returncode = process.poll()
                if returncode is None:
                    return None
        if read_failed:
            return None
        if status is not None:
            returncode = status
        return subprocess.CompletedProcess(command, returncode, bytes(output[:output_limit]), None)
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        if process is not None:
            _kill_process_group(process)
        return None
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    _kill_process_group(process)
                    try:
                        process.wait(timeout=1)
                    except (OSError, subprocess.SubprocessError):
                        pass
            except (AttributeError, OSError, subprocess.SubprocessError):
                pass
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            if reader is not None:
                try:
                    reader.join(timeout=1)
                except RuntimeError:
                    pass
            if writer is not None:
                try:
                    writer.join(timeout=1)
                except RuntimeError:
                    pass


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
