# Scripture

A **Bible verse of the day** for Windows, macOS, and iOS: a random Scripture
passage revealed in a focused, dark reading experience, with favorites,
history, a fixed verse of the day, and a daily reminder. The desktop versions
are ports of the author's
[Omarchy Scripture](https://github.com/davidmessenger123/omarchy-scripture) bar
widget — the same curated no-repeat deck, the same ESV/WEB/KJV providers, and
the same reveal and scrim look — with no Omarchy or Quickshell dependency.

The Windows and macOS versions run as desktop apps; the native iOS port lives
in [`ios/`](ios/).

## Install for end users (no technical setup)

You don't need Python or any tools. Download a prebuilt installer from the
[Releases page](https://github.com/davidmessenger123/scripture-windows/releases):

1. Open **`Scripture-Setup-<version>.exe`** and click **Next → Next → Install**.
   It installs per-user (no admin password) and adds a Start-menu entry.
2. If Windows shows **"Windows protected your PC"**, the app is unsigned (that
   is normal for indie software): click **More info → Run anyway**.
3. Look for the **gold cross ** in the system tray, right-click it, and choose
   **Open Scripture**.

First-run tip: choose **Settings…** from the tray to optionally paste an ESV
API key, set a fixed verse of the day, a daily auto-open time, or review your
favorites. Without an ESV key it shows the World English Bible, which needs no
signup.

Updates are checked automatically: when a newer release is available the tray
shows a notification and the overlay adds an “Update available: vX.Y.Z —
Download” chip. Clicking either downloads the new version and Scripture
restarts itself automatically (the running installer-less exe is swapped in
place) — no need to reinstall from the Releases page. The chip also keeps an
“Open browser” fallback. The check is silent and skipped in development builds
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
- Both embed the cross icon (`assets\app.ico`) and need Python 3.9+.

**Release automation:** push a tag (`git tag v0.1.0 && git push --tags`) and the
[GitHub Actions workflow](.github/workflows/build-release.yml) builds both files
on a Windows runner and attaches them to a GitHub Release automatically.
Keep `src/scripture/__init__.py` (`__version__`) in step with the tag so the
built-in update check never flags the app's own release.

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
  updater.py       GitHub release update check (tray balloon + in-app chip)
  favorites.py     hardened atomic favorites store (port of favorites.py)
  references.py    curated deck + range/parse/rich-text helpers (port of Scripture.js)
  qml/main.qml     overlay UI (plain Qt Quick, no Omarchy imports)
  qml/settings.qml settings dialog (own QQuickView top-level window)
```

The Omarchy plugin remains the upstream source of truth; when the two diverge,
port the change back into both.

## iOS

A native SwiftUI port is in [`ios/`](ios/). Open
`ios/Scripture.xcodeproj` in Xcode after installing the iOS SDK. It targets
iOS 17 and supports iPhone and iPad. The iOS app is version `0.2.0`.

The iOS version keeps the Scripture providers, no-repeat deck, passage reveal,
favorites, history, fixed verse, jump-to-reference, and online reading
features. It also adds a validated, bounded `Library/Caches` passage cache with
network-first offline fallback, canonical ESV verse-ID accounting, a 500-verse
provider limit, per-book half limits, and ESV key-generation isolation, plain passage
copying, file-backed deterministic 1080 × 1350 verse cards shared through
`ShareLink`, persisted daily-notification reconciliation, deterministic
book/topic filters, and adjustable verse size, scrim opacity, and reveal speed.
Provider legal suffixes are filtered from rendered passage surfaces, which show
only the passage, reference, and compact translation label. The ESV API key
remains in the iOS Keychain with device-only protection and is never written to
the passage cache. Settings → Legal & Privacy provides exact provider-request
disclosures, policy links, cache/key retention and deletion controls, favorite
and in-memory history behavior, reminder state, and clipboard details.

Book and topic filters affect only the random **Another verse** action. Fixed
verses, favorites, history, and Jump to verse bypass them. Topic sets are
curated from the existing reference deck rather than inferred or fetched, and
empty intersections are rejected instead of broadening the deck. The daily
reminder uses a local notification because iOS cannot force-open a suspended
app or perform a background Scripture fetch.

See [`ios/README.md`](ios/README.md) for cache limits, compact translation
labels, Legal & Privacy, sharing, notification behavior, the Linux static
release check, and Xcode-only verification notes.

## License

MIT — Copyright (c) 2026 David John Messenger.
