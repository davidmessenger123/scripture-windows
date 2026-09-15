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
2. If Windows shows **"Windows protected your PC"**, the app is unsigned (that
   is normal for indie software): click **More info → Run anyway**.
3. Look for the **gold star ** in the system tray, right-click it, and choose
   **Open Scripture**.

First-run tip: choose **Settings…** from the tray to optionally paste an ESV
API key, set a fixed verse of the day, a daily auto-open time, or review your
favorites. Without an ESV key it shows the World English Bible, which needs no
signup.

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

Requires Python 3.9+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripture
```

Windows:

```sh
pip install -r requirements.txt
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
- Both embed the star icon (`assets\app.ico`) and need Python 3.9+.

**Release automation:** push a tag (`git tag v0.1.0 && git push --tags`) and the
[GitHub Actions workflow](.github/workflows/build-release.yml) builds both files
on a Windows runner and attaches them to a GitHub Release automatically.

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

- Settings (ESV key, translation, fixed verse, auto-open): `QSettings` under
  `HKCU\Software\davidjm\scripture` on Windows (no registry editing needed —
  it is only ever touched by the app's Settings panel).
- Favorites: `%APPDATA%\Scripture\favorites.json`, written atomically (temp
  file + fsync + `os.replace`) exactly like the Omarchy plugin.

## Development

```text
src/scripture/
  main.py          QApplication bootstrap, tray, QML engine
  controller.py    AppController QObject — state, fetch, reveal, favorites, auto-open
  fetcher.py       QNetworkAccessManager wrappers for api.esv.org and bible-api.com
  favorites.py     hardened atomic favorites store (port of favorites.py)
  references.py    curated deck + range/parse/rich-text helpers (port of Scripture.js)
  qml/main.qml     overlay + settings UI (plain Qt Quick, no Omarchy imports)
```

The Omarchy plugin remains the upstream source of truth; when the two diverge,
port the change back into both.

## License

MIT — Copyright (c) 2026 David John Messenger.