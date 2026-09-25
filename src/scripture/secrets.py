import ctypes
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .errors import SecretStoreError
from .secure_files import (
    create_owner_only_directory,
    descriptor_identity,
    fsync_directory,
    open_file_no_follow,
    owner_only_handle_valid,
    restrict_handle_owner_only,
    secure_replace,
    windows_system_library,
)


KEYCHAIN_SERVICE = "org.davidjm.scripture.esv"
KEYCHAIN_ACCOUNT = "current-user"
KEYCHAIN_SUCCESS = 0
KEYCHAIN_ITEM_NOT_FOUND = -25300
KEYCHAIN_DUPLICATE_ITEM = -25299
CORE_FOUNDATION_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
SECURITY_FRAMEWORK_PATH = "/System/Library/Frameworks/Security.framework/Security"
MAX_SECRET_FILE_BYTES = 8192
_KEYCHAIN_LOCK = threading.RLock()


def _helper_environment() -> dict:
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for key in ("HOME", "TMPDIR"):
        value = os.environ.get(key, "")
        if value:
            environment[key] = value
    return environment


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class KeychainStatusError(SecretStoreError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = int(status)


class SecretStore:
    def __init__(self, data_dir: str):
        self._path = Path(data_dir) / "esv-api-key"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> str:
        if sys.platform == "darwin":
            return _keychain_load()
        fd = -1
        try:
            fd = open_file_no_follow(self._path, os.O_RDONLY)
            if not owner_only_handle_valid(fd):
                raise SecretStoreError("stored API key permissions are too broad")
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_SECRET_FILE_BYTES:
                raise SecretStoreError("stored API key file is invalid")
            chunks = []
            remaining = MAX_SECRET_FILE_BYTES + 1
            while remaining > 0:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
        except FileNotFoundError:
            return ""
        except SecretStoreError:
            raise
        except OSError as exc:
            raise SecretStoreError("could not read the stored API key") from exc
        finally:
            if fd >= 0:
                os.close(fd)
        if len(data) > MAX_SECRET_FILE_BYTES:
            raise SecretStoreError("stored API key exceeds the size limit")
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
            create_owner_only_directory(self._path.parent)
        except (OSError, ValueError, AttributeError) as exc:
            raise SecretStoreError("could not prepare the API key store") from exc
        fd = -1
        tmp_name = ""
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=".esv-key.", dir=str(self._path.parent))
            if hasattr(os, "fchmod"):
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            restrict_handle_owner_only(fd)
            identity = descriptor_identity(fd)
            handle = os.fdopen(fd, "wb", closefd=True)
            fd = -1
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            secure_replace(tmp_name, self._path, identity, self._path.parent)
            tmp_name = ""
        except OSError as exc:
            raise SecretStoreError("could not save the API key") from exc
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def clear(self) -> None:
        if sys.platform == "darwin":
            _keychain_clear()
            return
        try:
            self._path.unlink()
            fsync_directory(self._path.parent)
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


def _macos_security_api():
    core = ctypes.CDLL(CORE_FOUNDATION_PATH, use_errno=True)
    security = ctypes.CDLL(SECURITY_FRAMEWORK_PATH, use_errno=True)
    core.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    core.CFStringCreateWithCString.restype = ctypes.c_void_p
    core.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
    core.CFDataCreate.restype = ctypes.c_void_p
    core.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    core.CFDataGetBytePtr.restype = ctypes.c_void_p
    core.CFDataGetLength.argtypes = [ctypes.c_void_p]
    core.CFDataGetLength.restype = ctypes.c_long
    core.CFBooleanCreate.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
    core.CFBooleanCreate.restype = ctypes.c_void_p
    core.CFDictionaryCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    core.CFDictionaryCreate.restype = ctypes.c_void_p
    core.CFRelease.argtypes = [ctypes.c_void_p]
    core.CFRelease.restype = None
    security.SecItemCopyMatching.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    security.SecItemCopyMatching.restype = ctypes.c_int32
    security.SecItemAdd.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    security.SecItemAdd.restype = ctypes.c_int32
    security.SecItemUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecItemUpdate.restype = ctypes.c_int32
    security.SecItemDelete.argtypes = [ctypes.c_void_p]
    security.SecItemDelete.restype = ctypes.c_int32
    return core, security


def _cf_string(api, value: str):
    core, _security = api
    encoded = str(value).encode("utf-8")
    result = core.CFStringCreateWithCString(None, encoded, 0x08000100)
    if not result:
        raise SecretStoreError("could not create macOS keychain identifier")
    return result


def _cf_boolean(api, value: bool):
    core, _security = api
    result = core.CFBooleanCreate(None, 1 if value else 0)
    if not result:
        raise SecretStoreError("could not create macOS keychain query")
    return result


def _cf_dictionary(api, pairs):
    core, _security = api
    keys = []
    values = []
    owned = []
    for key, value in pairs:
        key_ref = _cf_string(api, key)
        if isinstance(value, bytes):
            buffer = ctypes.create_string_buffer(value, len(value))
            value_ref = core.CFDataCreate(None, ctypes.cast(buffer, ctypes.c_void_p), len(value))
            if not value_ref:
                for item in owned:
                    core.CFRelease(item)
                core.CFRelease(key_ref)
                raise SecretStoreError("could not create macOS keychain data")
        elif isinstance(value, bool):
            value_ref = _cf_boolean(api, value)
        else:
            value_ref = _cf_string(api, str(value))
        keys.append(key_ref)
        values.append(value_ref)
        owned.extend((key_ref, value_ref))
    key_array = (ctypes.c_void_p * len(keys))(*keys) if keys else None
    value_array = (ctypes.c_void_p * len(values))(*values) if values else None
    result = core.CFDictionaryCreate(None, key_array, value_array, len(pairs), None, None)
    if not result:
        for item in owned:
            core.CFRelease(item)
        raise SecretStoreError("could not create macOS keychain query")
    return result, owned


def _release_cf(core, dictionary, owned) -> None:
    if dictionary:
        core.CFRelease(dictionary)
    for item in owned:
        core.CFRelease(item)


def _keychain_query(api, include_data: bool):
    pairs = [
        ("class", "genp"),
        ("svce", KEYCHAIN_SERVICE),
        ("acct", KEYCHAIN_ACCOUNT),
    ]
    if include_data:
        pairs.extend((("r_Data", True), ("m_Limit", "m_LimitOne")))
    return _cf_dictionary(api, pairs)


def _keychain_find(api):
    core, security = api
    query, owned = _keychain_query(api, True)
    result = ctypes.c_void_p()
    try:
        status = security.SecItemCopyMatching(query, ctypes.byref(result))
    finally:
        _release_cf(core, query, owned)
    if status == KEYCHAIN_ITEM_NOT_FOUND:
        return b""
    if status != KEYCHAIN_SUCCESS:
        raise SecretStoreError("could not read the macOS keychain")
    if not result:
        raise SecretStoreError("macOS keychain returned an invalid item")
    try:
        length = core.CFDataGetLength(result)
        pointer = core.CFDataGetBytePtr(result)
        if length <= 0 or length > MAX_SECRET_FILE_BYTES or not pointer:
            raise SecretStoreError("stored macOS keychain item is invalid")
        return ctypes.string_at(pointer, length)
    finally:
        core.CFRelease(result)


def _keychain_add_attributes(api, value: str):
    return _cf_dictionary(
        api,
        (
            ("class", "genp"),
            ("svce", KEYCHAIN_SERVICE),
            ("acct", KEYCHAIN_ACCOUNT),
            ("v_Data", value.encode("utf-8")),
        ),
    )


def _keychain_update_attributes(api, value: str):
    return _cf_dictionary(api, (("v_Data", value.encode("utf-8")),))


def _keychain_load() -> str:
    if sys.platform != "darwin":
        raise SecretStoreError("native keychain access is unavailable")
    with _KEYCHAIN_LOCK:
        try:
            value = _keychain_find(_macos_security_api())
        except SecretStoreError:
            raise
        except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError) as exc:
            raise SecretStoreError("could not load the macOS keychain framework") from exc
    if not value:
        return ""
    try:
        return _validate(value.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SecretStoreError("macOS keychain item is not valid UTF-8") from exc


def _keychain_save(value: str) -> None:
    if not value:
        _keychain_clear()
        return
    if sys.platform != "darwin":
        raise SecretStoreError("native keychain access is unavailable")
    value = _validate(value)
    with _KEYCHAIN_LOCK:
        api = _macos_security_api()
        core, security = api
        query, query_owned = _keychain_query(api, False)
        add_attributes, add_owned = _keychain_add_attributes(api, value)
        update_attributes, update_owned = _keychain_update_attributes(api, value)
        try:
            status = security.SecItemUpdate(query, update_attributes)
            if status == KEYCHAIN_ITEM_NOT_FOUND:
                result = ctypes.c_void_p()
                try:
                    status = security.SecItemAdd(add_attributes, ctypes.byref(result))
                finally:
                    if result:
                        core.CFRelease(result)
                if status == KEYCHAIN_DUPLICATE_ITEM:
                    status = security.SecItemUpdate(query, update_attributes)
            if status != KEYCHAIN_SUCCESS:
                raise KeychainStatusError("could not save the macOS keychain", status)
        finally:
            _release_cf(core, query, query_owned)
            _release_cf(core, add_attributes, add_owned)
            _release_cf(core, update_attributes, update_owned)


def _keychain_clear() -> None:
    if sys.platform != "darwin":
        raise SecretStoreError("native keychain access is unavailable")
    with _KEYCHAIN_LOCK:
        core, security = _macos_security_api()
        query, owned = _keychain_query((core, security), False)
        try:
            status = security.SecItemDelete(query)
            if status not in {KEYCHAIN_SUCCESS, KEYCHAIN_ITEM_NOT_FOUND}:
                raise SecretStoreError("could not remove the macOS keychain item")
        finally:
            _release_cf(core, query, owned)


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


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return DATA_BLOB(len(data), pointer), buffer


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        return data
    source, source_buffer = _blob(data)
    result = DATA_BLOB()
    crypt32 = windows_system_library("crypt32.dll")
    kernel32 = windows_system_library("kernel32.dll")
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
    crypt32 = windows_system_library("crypt32.dll")
    kernel32 = windows_system_library("kernel32.dll")
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
