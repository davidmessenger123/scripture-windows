import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
import time

from . import references
from .secure_files import (
    create_owner_only_directory,
    descriptor_identity,
    fsync_directory,
    open_file_no_follow,
    owner_only_handle_valid,
    restrict_handle_owner_only,
    secure_replace,
)

CACHE_VERSION = 3
MAX_ENTRIES = 256
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PASSAGE_BYTES = references.MAX_RESPONSE_BYTES
MAX_TRANSLATION_NAME_BYTES = 128
MAX_ATTRIBUTION_BYTES = 8192
MAX_AGE_SECONDS = 90 * 24 * 60 * 60
CACHE_FILE_NAME = "passage-cache.json"
CACHE_KEY_FILE_NAME = "passage-cache.key"
CACHE_KEY_BYTES = 32
CACHE_KEY_HEX_BYTES = CACHE_KEY_BYTES * 2
ROOT_KEYS = {"version", "entries"}
MAC_FIELDS = (
    "provider",
    "translation_id",
    "passage",
    "anchor",
    "identity",
    "before",
    "focal",
    "after",
    "reference",
    "translation_name",
    "attribution",
    "cached_at",
)
ENTRY_KEYS = set(MAC_FIELDS) | {"mac"}


class PassageCacheError(RuntimeError):
    pass


def fingerprint_secret(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def record_mac(key: bytes, entry: dict) -> str:
    if not isinstance(key, bytes) or len(key) != CACHE_KEY_BYTES:
        raise PassageCacheError("cache authentication key is invalid")
    if not isinstance(entry, dict) or any(field not in entry for field in MAC_FIELDS):
        raise PassageCacheError("cache record is incomplete")
    canonical = json.dumps(
        {field: entry[field] for field in MAC_FIELDS},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def cache_key(provider: str, passage: str, anchor: str, identity: str) -> tuple:
    return (
        _clean_provider(provider),
        references.normalize_reference(passage),
        references.normalize_reference(anchor),
        _clean_identity(identity, _clean_provider(provider)),
    )


def _clean_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if provider not in {"esv", "web", "kjv"}:
        raise PassageCacheError("cached passage provider is invalid")
    return provider


def _clean_identity(value: str, provider: str) -> str:
    identity = str(value or "").strip().lower()
    if provider == "esv":
        if len(identity) != 64 or any(char not in "0123456789abcdef" for char in identity):
            raise PassageCacheError("cached ESV identity is invalid")
    elif identity:
        raise PassageCacheError("cached keyless passage identity is invalid")
    return identity


def _clean_reference(value: str) -> str:
    reference = references.normalize_reference(value)
    if not reference:
        raise PassageCacheError("cached passage reference is invalid")
    return reference


def _clean_translation(provider: str, translation_id: str, translation_name: str) -> tuple:
    selected = _clean_provider(provider)
    selected_id = _clean_provider(translation_id)
    if selected_id != selected:
        raise PassageCacheError("cached provider and translation do not match")
    name = _clean_text(translation_name, MAX_TRANSLATION_NAME_BYTES, False).strip()
    if name != references.expected_translation_name(selected):
        raise PassageCacheError("cached translation does not match its provider")
    return selected, selected_id, name


def _validate_relations(entry: dict) -> None:
    anchor = entry["anchor"]
    passage = entry["passage"]
    if passage not in {anchor, references.range_query(anchor)}:
        raise PassageCacheError("cached passage is inconsistent with its anchor")
    if entry["reference"] not in {anchor, passage}:
        raise PassageCacheError("cached passage reference is inconsistent with its request")
    focal_verse = references.focal_verse(anchor)
    if focal_verse and "[%d]" % focal_verse not in entry["focal"]:
        raise PassageCacheError("cached focal verse is structurally incomplete")
    if not entry["before"] and not entry["after"] and "[" not in entry["focal"]:
        raise PassageCacheError("cached passage is structurally incomplete")


def _clean_text(value: str, limit: int, allow_empty: bool = True) -> str:
    text = str(value or "")
    if not allow_empty and not text.strip():
        raise PassageCacheError("cached passage text is empty")
    if any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in text):
        raise PassageCacheError("cached passage text contains control characters")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as exc:
        raise PassageCacheError("cached passage text is invalid") from exc
    if size > limit:
        raise PassageCacheError("cached passage text exceeds the size limit")
    return text


def _clean_attribution(value: str) -> str:
    text = _clean_text(value, MAX_ATTRIBUTION_BYTES).strip()
    return "" if references.esv_legal_text_present(text) else text


class PassageCache:
    def __init__(self, data_dir: str):
        source_dir = str(data_dir or "")
        if not source_dir:
            raise PassageCacheError("cache directory is invalid")
        raw_dir = os.path.abspath(source_dir)
        if len(raw_dir) > 32767 or any(ord(char) < 32 for char in raw_dir):
            raise PassageCacheError("cache directory is invalid")
        self._dir = raw_dir
        self._path = os.path.join(self._dir, CACHE_FILE_NAME)
        self._key_path = os.path.join(self._dir, CACHE_KEY_FILE_NAME)
        self._key = None
        self._entries = []
        self._loaded = False

    @property
    def path(self) -> str:
        return self._path

    @property
    def key_path(self) -> str:
        return self._key_path

    def ensure_dir(self) -> None:
        try:
            create_owner_only_directory(self._dir)
        except OSError as exc:
            raise PassageCacheError("could not create or protect cache directory") from exc

    def _ensure_key(self) -> bytes:
        if self._key is not None:
            return self._key
        self.ensure_dir()
        try:
            self._key = self._read_key()
        except FileNotFoundError:
            self._key = self._create_key()
        if not isinstance(self._key, bytes) or len(self._key) != CACHE_KEY_BYTES:
            raise PassageCacheError("cache authentication key is invalid")
        return self._key

    def _read_key(self) -> bytes:
        fd = open_file_no_follow(self._key_path, os.O_RDONLY)
        try:
            if not owner_only_handle_valid(fd):
                raise PassageCacheError("cache authentication key permissions are unsafe")
            raw = os.read(fd, CACHE_KEY_HEX_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) != CACHE_KEY_HEX_BYTES or any(char not in b"0123456789abcdef" for char in raw):
            raise PassageCacheError("cache authentication key is invalid")
        return bytes.fromhex(raw.decode("ascii"))

    def _create_key(self) -> bytes:
        value = secrets.token_bytes(CACHE_KEY_BYTES)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self._key_path, flags, 0o600)
        except FileExistsError:
            return self._read_key()
        except OSError as exc:
            raise PassageCacheError("could not create cache authentication key") from exc
        try:
            restrict_handle_owner_only(fd)
            encoded = value.hex().encode("ascii")
            written = 0
            while written < len(encoded):
                count = os.write(fd, encoded[written:])
                if count <= 0:
                    raise PassageCacheError("cache authentication key write failed")
                written += count
            os.fsync(fd)
            if not owner_only_handle_valid(fd):
                raise PassageCacheError("cache authentication key permissions are unsafe")
            fsync_directory(self._dir)
        except Exception:
            try:
                os.close(fd)
            finally:
                try:
                    os.unlink(self._key_path)
                except OSError:
                    pass
            raise
        else:
            os.close(fd)
        return value

    def list(self, now: int | None = None) -> list:
        key = self._ensure_key()
        if not self._loaded:
            self._entries = self._read(key)
            self._loaded = True
        timestamp = self._now(now)
        active = [entry for entry in self._entries if self._age(entry["cached_at"], timestamp) <= MAX_AGE_SECONDS]
        if len(active) != len(self._entries):
            self._entries = active
        return [dict(entry) for entry in self._entries]

    def get(self, provider: str, passage: str, anchor: str, identity: str, now: int | None = None) -> dict | None:
        key = cache_key(provider, passage, anchor, identity)
        timestamp = self._now(now)
        for entry in reversed(self.list(timestamp)):
            if self._entry_key(entry) == key:
                return dict(entry)
        return None

    def put(
        self,
        provider: str,
        translation_id: str,
        passage: str,
        anchor: str,
        identity: str,
        before: str,
        focal: str,
        after: str,
        reference: str,
        translation_name: str,
        attribution: str,
        now: int | None = None,
    ) -> None:
        timestamp = self._now(now)
        provider, translation_id, translation_name = _clean_translation(
            provider, translation_id, translation_name
        )
        entry = {
            "provider": provider,
            "translation_id": translation_id,
            "passage": _clean_reference(passage),
            "anchor": _clean_reference(anchor),
            "identity": "",
            "before": _clean_text(before, MAX_PASSAGE_BYTES),
            "focal": _clean_text(focal, MAX_PASSAGE_BYTES, False),
            "after": _clean_text(after, MAX_PASSAGE_BYTES),
            "reference": _clean_reference(reference),
            "translation_name": translation_name,
            "attribution": _clean_attribution(attribution),
            "cached_at": timestamp,
        }
        entry["identity"] = _clean_identity(identity, provider)
        if sum(len(entry[field].encode("utf-8")) for field in ("before", "focal", "after")) > MAX_PASSAGE_BYTES:
            raise PassageCacheError("cached passage exceeds the combined size limit")
        _validate_relations(entry)
        key = self._ensure_key()
        entry["mac"] = record_mac(key, entry)
        entries = [item for item in self.list(timestamp) if self._entry_key(item) != self._entry_key(entry)]
        entries.append(entry)
        entries = entries[-MAX_ENTRIES:]
        self._write(entries)
        self._entries = entries
        self._loaded = True

    def clear(self) -> None:
        self._ensure_key()
        self._write([])
        self._entries = []
        self._loaded = True

    def size(self, now: int | None = None) -> int:
        return len(self.list(now))

    def _read(self, key: bytes) -> list:
        self.ensure_dir()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        try:
            fd = open_file_no_follow(self._path, flags)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise PassageCacheError("could not open passage cache") from exc
        try:
            if not owner_only_handle_valid(fd):
                raise PassageCacheError("passage cache permissions are unsafe")
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_JSON_BYTES:
                raise PassageCacheError("passage cache is not a valid regular file")
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = -1
                raw = handle.read(MAX_JSON_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
        if len(raw) > MAX_JSON_BYTES:
            raise PassageCacheError("passage cache exceeds the size limit")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, TypeError, ValueError) as exc:
            raise PassageCacheError("passage cache is not valid JSON") from exc
        entries = self._validate_root(value, key)
        timestamp = self._now()
        return [entry for entry in entries if self._age(entry["cached_at"], timestamp) <= MAX_AGE_SECONDS]

    def _validate_root(self, value, key: bytes) -> list:
        version = value.get("version") if isinstance(value, dict) else None
        if not isinstance(value, dict) or set(value) != ROOT_KEYS or isinstance(version, bool) or version != CACHE_VERSION:
            raise PassageCacheError("passage cache has an invalid schema")
        entries = value.get("entries")
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise PassageCacheError("passage cache entry list is invalid")
        result = []
        seen = set()
        for item in entries:
            entry = self._validate_entry(item, key)
            identity = self._entry_key(entry)
            if identity in seen:
                raise PassageCacheError("passage cache contains duplicate entries")
            seen.add(identity)
            result.append(entry)
        return result

    def _validate_entry(self, value, key: bytes) -> dict:
        if not isinstance(value, dict) or set(value) != ENTRY_KEYS:
            raise PassageCacheError("passage cache entry has an invalid schema")
        provider, translation_id, translation_name = _clean_translation(
            value.get("provider"), value.get("translation_id"), value.get("translation_name")
        )
        cached_at = value.get("cached_at")
        if isinstance(cached_at, bool) or not isinstance(cached_at, int) or cached_at < 0 or cached_at > self._now() + 86400:
            raise PassageCacheError("passage cache timestamp is invalid")
        entry = {
            "provider": provider,
            "translation_id": translation_id,
            "passage": _clean_reference(value.get("passage")),
            "anchor": _clean_reference(value.get("anchor")),
            "identity": _clean_identity(value.get("identity"), provider),
            "before": _clean_text(value.get("before"), MAX_PASSAGE_BYTES),
            "focal": _clean_text(value.get("focal"), MAX_PASSAGE_BYTES, False),
            "after": _clean_text(value.get("after"), MAX_PASSAGE_BYTES),
            "reference": _clean_reference(value.get("reference")),
            "translation_name": translation_name,
            "attribution": _clean_text(value.get("attribution"), MAX_ATTRIBUTION_BYTES).strip(),
            "cached_at": cached_at,
        }
        if sum(len(entry[field].encode("utf-8")) for field in ("before", "focal", "after")) > MAX_PASSAGE_BYTES:
            raise PassageCacheError("passage cache passage exceeds the combined size limit")
        _validate_relations(entry)
        provided = value.get("mac")
        if not isinstance(provided, str) or len(provided) != 64 or any(char not in "0123456789abcdef" for char in provided):
            raise PassageCacheError("passage cache authentication is invalid")
        if not hmac.compare_digest(provided, record_mac(key, entry)):
            raise PassageCacheError("passage cache authentication failed")
        entry["mac"] = provided
        return entry

    def _write(self, entries: list) -> None:
        self.ensure_dir()
        payload = (json.dumps({"version": CACHE_VERSION, "entries": entries}, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > MAX_JSON_BYTES:
            raise PassageCacheError("passage cache exceeds the size limit")
        tmp_name = ""
        fd = -1
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=".passage-cache.", suffix=".tmp", dir=self._dir)
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
            secure_replace(tmp_name, self._path, identity, self._dir)
            tmp_name = ""
        except PassageCacheError:
            raise
        except OSError as exc:
            raise PassageCacheError("could not write passage cache") from exc
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

    def _entry_key(self, entry: dict) -> tuple:
        return entry["provider"], entry["passage"], entry["anchor"], entry["identity"]

    @staticmethod
    def _age(cached_at: int, now: int) -> int:
        return max(0, now - cached_at)

    @staticmethod
    def _now(value: int | None = None) -> int:
        if value is None:
            return int(time.time())
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PassageCacheError("cache time is invalid")
        return value
