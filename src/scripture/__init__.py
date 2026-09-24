from pathlib import Path

version_file = Path(__file__).with_name("VERSION")
__version__ = version_file.read_text(encoding="ascii").strip()
parts = __version__.split(".")
if len(parts) != 3 or any(not part.isdigit() or (len(part) > 1 and part[0] == "0") for part in parts):
    raise RuntimeError("invalid Scripture version")
