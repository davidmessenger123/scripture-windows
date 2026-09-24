# Scripture

A **Bible verse of the day** for Windows: a random Scripture passage revealed on
a full-screen dark overlay, with favorites, history, a fixed verse of the day,
and a daily auto-open time. It is a desktop port of the author's
[Omarchy Scripture](https://github.com/davidmessenger123/omarchy-scripture) bar
widget — the same curated no-repeat deck, the same ESV/WEB/KJV providers, the
same reveal and scrim look — with no Omarchy or Quickshell dependency.

Runs as a system-tray app.

## Install for end users (no technical setup)

You don't need Python or any tools. Download a prebuilt installer from the
[Releases page](https://github.com/davidmessenger123/scripture-windows/releases):

1. Open **`Scripture-Setup-<version>.exe`** and click **Next → Next → Install**.
   It installs per-user (no admin password) and adds a Start-menu entry.
2. Published installers and portable builds are Authenticode-signed and
   timestamped. Do not bypass Windows signature warnings.
3. Look for the **gold cross ** in the system tray, right-click it, and choose
   **Open Scripture**.

First-run tip: choose **Settings…** from the tray to optionally paste an ESV
API key, set a fixed verse of the day, a daily auto-open time, or review your
favorites. Without an ESV key it shows the World English Bible, which needs no
signup.

Updates are checked automatically: when a newer release is available the tray
shows a notification and the overlay adds an “Update available: vX.Y.Z —
Download” chip. Automatic Windows replacement additionally requires a valid
Authenticode signature on both the installed and downloaded executables. The
full publisher subject and signing-certificate thumbprint must both match.
Unsigned or differently signed builds always fall back to the release page. Hash/size, trusted GitHub origins, redirects,
and a durable replacement journal are also enforced. macOS uses the same
release-page fallback. The check is silent and skipped in development builds
(set `SCRIPTURE_FORCE_UPDATE_CHECK=1` to enable it).

## Features

- **No-repeat rotation** over ~270 well-known, always-valid references (draws
  from a shuffled deck; a verse never repeats until the whole deck is seen)
- **ESV** via a free [api.esv.org](https://api.esv.org) key, or keyless
  **WEB/KJV** via bible-api.com; the ESV quietly falls back to WEB without a key
- Each pick shows a **short centered passage** (anchor ± 2 verses) with the
  anchor bright and the surroundings dimmed, revealed by a 2.2 s typewriter
- **Favorites** — ☆ on any verse, browse/load/remove them in Settings; persisted
  atomically to the app-data folder
- **Session history** (◀/▶)
- **Jump to any reference** (`John 3:16`)
- **Fixed verse** of the day and **daily auto-open** at a 24-hour time
- Toolbar buttons for Repeat/Another Verse and **Open in browser**

## Install & run (dev)

Requires Python 3.10+. The build and runtime dependency versions are pinned in
`requirements.txt`, `requirements-build.txt`, and `pyproject.toml`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install --no-deps -e .
python -m scripture
```

Windows:

```sh
pip install -r requirements.txt
pip install --no-deps -e .
python -m scripture --smoke   # optional headless load test
```

## Build the exe / installer (on Windows)

From the repo root in PowerShell:

```powershell
.\scripts\build.ps1                      # portable onefile exe
.\scripts\build-installer.ps1            # exe + dist\Scripture-Setup-<ver>.exe installer
```

- `build.ps1` produces `dist\Scripture.exe` (works by itself, no install).
- `build-installer.ps1` also compiles a per-user installer and needs
  [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed.
- Both embed the cross icon (`assets\app.ico`) and need Python 3.10+.

**Release automation:** push a matching tag (`git tag vMAJOR.MINOR.PATCH && git push --tags`) and the
[GitHub Actions workflow](.github/workflows/build-release.yml) builds both files
on a Windows runner and attaches them to a GitHub Release automatically.
`src/scripture/VERSION` is the single release-version input. The package
metadata, frozen bundle, installer workflow, and update comparison all derive
from it; release tags must match its `MAJOR.MINOR.PATCH` value. The workflow
fails closed unless the certificate, expected thumbprint, expected subject, and
HTTPS timestamp URL are configured.

## Controls

| Where | Action |
|---|---|
| Tray → **Open Scripture** | Show the overlay; draws a fresh verse |
| Overlay | **Esc** / click the dark scrim — close |
| Overlay | **Enter** — another random verse (or *Repeat* when a fixed verse is set) |
| Overlay toolbar | ◀ / ▶ history, ☆ favorite, ✱ star toggle, **Open in browser** |
| Overlay → **JUMP TO** | type a reference, Enter — jump |
| Overlay chips | click a favorite chip to open it again |
| Tray → **Settings…** | ESV key, translation, fixed verse, auto-open, favorites list |

## Data & settings

- Settings (translation, fixed verse, auto-open): `QSettings` under
  `HKCU\Software\davidjm\Scripture` on Windows. The ESV key is kept in a
  separate owner-only file encrypted with Windows DPAPI (macOS uses Keychain);
  it is never placed in
  `QSettings`, logs, URLs, or update metadata.
- Favorites: `%APPDATA%\davidjm\Scripture\favorites.json`, written atomically
  (temp file + fsync + `os.replace`) and validated against a strict JSON schema.
- A per-user local-server lock coordinates tray starts; a second launch signals
  the existing window instead of creating a second updater or fetch loop.
- Frozen startup failures are timestamped in `startup-error.log` and rotated to
  three bounded backups.

## Development

```text
src/scripture/
  main.py          QApplication bootstrap, tray, QML engine
  controller.py    AppController QObject — state, fetch, reveal, favorites, auto-open
  fetcher.py       QNetworkAccessManager wrappers for api.esv.org and bible-api.com
  updater.py       GitHub release update check (tray balloon + in-app chip)
  secrets.py       DPAPI/owner-only ESV key storage
  single_instance.py per-user local-server coordination
  favorites.py     hardened atomic favorites store (port of favorites.py)
  references.py    curated deck + range/parse/rich-text helpers (port of Scripture.js)
  VERSION          canonical release version
  qml/main.qml     overlay UI (plain Qt Quick, no Omarchy imports)
  qml/settings.qml settings dialog (own QQuickView top-level window)
tests/                 focused Python unittest coverage
```

The Omarchy plugin remains the upstream source of truth; when the two diverge,
port the change back into both.

## License

MIT — Copyright (c) 2026 David John Messenger.