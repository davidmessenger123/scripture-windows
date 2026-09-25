import json
import os
import stat
import sys
import tempfile

try:
    from . import references
    from .secure_files import (
        create_owner_only_directory,
        descriptor_identity,
        open_file_no_follow,
        owner_only_handle_valid,
        restrict_handle_owner_only,
        secure_replace,
    )
except ImportError:
    import references
    from secure_files import (
        create_owner_only_directory,
        descriptor_identity,
        open_file_no_follow,
        owner_only_handle_valid,
        restrict_handle_owner_only,
        secure_replace,
    )

MAX_ANCHOR_BYTES = 120
MAX_ENTRIES = 200
MAX_JSON_BYTES = 65536


class FavoritesError(RuntimeError):
    pass


class FavoritesStore:
    def __init__(self, data_dir: str):
        self._dir = data_dir
        self._path = os.path.join(data_dir, "favorites.json")

    @property
    def path(self) -> str:
        return self._path

    def ensure_dir(self) -> None:
        try:
            create_owner_only_directory(self._dir)
        except OSError as exc:
            raise FavoritesError("could not create favorites directory: %s" % exc) from exc

    def list(self) -> list:
        self.ensure_dir()
        fd = -1
        try:
            fd = open_file_no_follow(self._path, os.O_RDONLY)
            if not owner_only_handle_valid(fd):
                raise FavoritesError("favorites file permissions are unsafe")
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_JSON_BYTES:
                raise FavoritesError("favorites file is not a valid regular file")
            with os.fdopen(fd, "rb", closefd=True) as fh:
                fd = -1
                raw = fh.read(MAX_JSON_BYTES + 1)
            data = raw.decode("utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError) as exc:
            raise FavoritesError("favorites file refused open: %s" % exc) from exc
        finally:
            if fd >= 0:
                os.close(fd)
        if len(raw) > MAX_JSON_BYTES:
            raise FavoritesError("favorites list exceeds the %d-byte limit" % MAX_JSON_BYTES)
        try:
            value = json.loads(data)
        except (TypeError, ValueError) as exc:
            raise FavoritesError("favorites file is not valid JSON") from exc
        if not isinstance(value, list):
            raise FavoritesError("favorites file is not a JSON list")
        if len(value) > MAX_ENTRIES:
            raise FavoritesError("favorites list exceeds the %d-entry limit" % MAX_ENTRIES)
        result = []
        seen = set()
        for item in value:
            if not isinstance(item, str):
                raise FavoritesError("favorites file contains a non-string entry")
            anchor = self._clean(item)
            if anchor in seen:
                raise FavoritesError("favorites file contains duplicate entries")
            seen.add(anchor)
            result.append(anchor)
        return result

    def add(self, reference: str, current=None) -> list:
        ref = self._clean(reference)
        existing = self._validated_current(current)
        anchors = [ref] + [anchor for anchor in existing if anchor != ref]
        anchors = anchors[:MAX_ENTRIES]
        self._write(anchors)
        return anchors

    def remove(self, reference: str, current=None) -> list:
        ref = self._clean(reference)
        existing = self._validated_current(current)
        anchors = [anchor for anchor in existing if anchor != ref]
        self._write(anchors)
        return anchors

    def clear(self) -> list:
        self._write([])
        return []

    def _validated_current(self, current) -> list:
        if current is None:
            return self.list()
        if not isinstance(current, (list, tuple)) or len(current) > MAX_ENTRIES:
            raise FavoritesError("favorites state exceeds the entry limit")
        result = []
        seen = set()
        for item in current:
            if not isinstance(item, str):
                raise FavoritesError("favorites state contains a non-string entry")
            anchor = self._clean(item)
            if anchor in seen:
                raise FavoritesError("favorites state contains duplicate entries")
            seen.add(anchor)
            result.append(anchor)
        return result

    @staticmethod
    def _clean(reference: str) -> str:
        anchor = references.normalize_reference(reference)
        if not anchor:
            raise FavoritesError("reference must look like John 3:16")
        if len(anchor.encode("utf-8")) > MAX_ANCHOR_BYTES:
            raise FavoritesError("reference exceeds the %d-byte limit" % MAX_ANCHOR_BYTES)
        return anchor

    def _write(self, anchors: list) -> None:
        self.ensure_dir()
        payload = (json.dumps(anchors, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > MAX_JSON_BYTES:
            raise FavoritesError("favorites list exceeds the %d-byte limit" % MAX_JSON_BYTES)
        tmp_name = ""
        tmp_fh = None
        fd = -1
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=".favorites.", suffix=".tmp", dir=self._dir)
            if hasattr(os, "fchmod"):
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            restrict_handle_owner_only(fd)
            identity = descriptor_identity(fd)
            tmp_fh = os.fdopen(fd, "wb", closefd=True)
            fd = -1
            tmp_fh.write(payload)
            tmp_fh.flush()
            os.fsync(tmp_fh.fileno())
            tmp_fh.close()
            tmp_fh = None
            secure_replace(tmp_name, self._path, identity, self._dir)
            tmp_name = ""
        except (OSError, FavoritesError) as exc:
            if isinstance(exc, FavoritesError):
                raise
            raise FavoritesError("favorites file write failed: %s" % exc) from exc
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_fh is not None:
                try:
                    tmp_fh.close()
                except OSError:
                    pass
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    data_dir = os.environ.get("SCRIPTURE_DATA_DIR", "")
    if not data_dir:
        print("SCRIPTURE_DATA_DIR must point at the data folder", file=sys.stderr)
        return 2
    store = FavoritesStore(data_dir)
    try:
        store.ensure_dir()
        if not argv:
            print("usage: favorites.py {list|add|remove|clear} [reference]", file=sys.stderr)
            return 2
        op = argv[0]
        if op == "list":
            print(json.dumps(store.list(), ensure_ascii=True))
        elif op in ("add", "remove"):
            if len(argv) != 2:
                raise FavoritesError("a reference is required")
            result = store.add(argv[1]) if op == "add" else store.remove(argv[1])
            print("ok" if result is not None else "ok")
        elif op == "clear":
            store.clear()
            print("ok")
        else:
            print("unknown op: %s" % op, file=sys.stderr)
            return 2
    except FavoritesError as exc:
        print("favorites: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
