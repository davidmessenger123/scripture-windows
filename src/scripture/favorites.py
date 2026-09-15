"""User favorites persistence for the Scripture desktop app.

Faithful port of the Omarchy widget's `favorites.py`, keeping the same
discipline: references travel as plain strings, the list is capped, and writes
go to a same-directory temporary file that is fsynced before an atomic
`os.replace` so a partially-written store can never be observed. The file lives
in the platform app-data directory (e.g. `%APPDATA%\\Scripture\\favorites.json`
on Windows) instead of beside a plugin folder.
"""

import json
import os
import stat
import sys

MAX_ANCHOR_BYTES = 120
MAX_ENTRIES = 200
MAX_JSON_BYTES = 65536


class FavoritesError(RuntimeError):
    pass


class FavoritesStore:
    """Thread-hostile by design: call from the one thread that owns it.

    Rides on `QStandardPaths.writableLocation(AppDataLocation)` for the data
    folder (created on demand), so `%APPDATA%` is honored on Windows and a
    sane XDG dir is used on other platforms.
    """

    def __init__(self, data_dir: str):
        self._dir = data_dir
        self._path = os.path.join(data_dir, "favorites.json")

    @property
    def path(self) -> str:
        return self._path

    def ensure_dir(self) -> None:
        os.makedirs(self._dir, exist_ok=True)

    # -- reads ------------------------------------------------------------

    def list(self) -> list:
        try:
            with open(self._path, "r", encoding="utf-8", newline="") as fh:
                data = fh.read(MAX_JSON_BYTES + 1)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise FavoritesError("favorites file refused open: %s" % exc) from exc

        if len(data) > MAX_JSON_BYTES:
            raise FavoritesError("favorites list exceeds the %d-byte limit" % MAX_JSON_BYTES)
        try:
            value = json.loads(data)
        except Exception as exc:
            raise FavoritesError("favorites file is not valid JSON") from exc
        if not isinstance(value, list):
            raise FavoritesError("favorites file is not a JSON list")
        return [anchor for anchor in value if isinstance(anchor, str)]

    # -- writes -----------------------------------------------------------

    def add(self, reference: str) -> list:
        ref = self._clean(reference)
        anchors = [ref] + [a for a in self.list() if a != ref]
        self._write(anchors[:MAX_ENTRIES])
        return anchors[:MAX_ENTRIES]

    def remove(self, reference: str) -> list:
        ref = self._clean(reference)
        anchors = [a for a in self.list() if a != ref]
        self._write(anchors)
        return anchors

    def clear(self) -> list:
        self._write([])
        return []

    # -- internals --------------------------------------------------------

    @staticmethod
    def _clean(reference: str) -> str:
        anchor = str(reference or "").strip()
        if not anchor:
            raise FavoritesError("no reference provided")
        if len(anchor) > MAX_ANCHOR_BYTES:
            raise FavoritesError("reference exceeds the %d-byte limit" % MAX_ANCHOR_BYTES)
        if any(ord(c) < 32 for c in anchor):
            raise FavoritesError("reference contains control characters")
        return anchor

    def _write(self, anchors: list) -> None:
        self.ensure_dir()
        payload = (json.dumps(anchors, ensure_ascii=True) + "\n").encode("utf-8")
        if len(payload) > MAX_JSON_BYTES:
            raise FavoritesError("favorites list exceeds the %d-byte limit" % MAX_JSON_BYTES)

        import tempfile

        tmp_name = None
        tmp_fh = None
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=".favorites.", suffix=".tmp", dir=self._dir)
            tmp_fh = os.fdopen(fd, "wb", closefd=True)
            tmp_fh.write(payload)
            tmp_fh.flush()
            os.fsync(tmp_fh.fileno())
            tmp_fh.close()
            tmp_fh = None

            with open(tmp_name, "rb") as check:
                st = os.fstat(check.fileno())
                if not stat.S_ISREG(st.st_mode):
                    raise FavoritesError("temporary favorites file is not a regular file")
                if st.st_size != len(payload):
                    raise FavoritesError("temporary favorites file size mismatch")
                check.seek(0)
                if check.read(len(payload)) != payload:
                    raise FavoritesError("temporary favorites file content mismatch")

            os.replace(tmp_name, self._path)
            tmp_name = None
        finally:
            if tmp_fh is not None:
                try:
                    tmp_fh.close()
                except Exception:
                    pass
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass


def main(argv=None) -> int:
    """CLI mirror of the Omarchy helper (`list|add|remove|clear`), mainly for dev use."""
    argv = sys.argv[1:] if argv is None else argv
    data_dir = os.environ.get("SCRIPTURE_DATA_DIR", "")
    if not data_dir:
        print("SCRIPTURE_DATA_DIR must point at the data folder", file=sys.stderr)
        return 2
    store = FavoritesStore(data_dir)
    store.ensure_dir()
    if not argv:
        print("usage: favorites.py {list|add|remove|clear} [reference]", file=sys.stderr)
        return 2
    op = argv[0]
    try:
        if op == "list":
            print(json.dumps(store.list(), ensure_ascii=True))
        elif op == "add":
            print("ok" if store.add(argv[1]) else "ok")
        elif op == "remove":
            print("ok" if store.remove(argv[1]) else "ok")
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