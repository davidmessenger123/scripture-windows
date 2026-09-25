# Scripture

A **Bible verse of the day** for Windows and macOS: a random Scripture passage
revealed on a full-screen dark overlay, with favorites, history, a fixed verse
of the day, daily scheduling, offline fallback, sharing, and appearance controls.
It is a desktop port of the author's
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

First-run tip: choose **Settings…** from the tray to paste an ESV API key, set
a fixed verse, daily auto-open and notification times, random-selection filters,
appearance controls, and favorites. Without an ESV key it shows the World
English Bible, which needs no signup.

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

- **No-repeat rotation** over 185 well-known, always-valid references, with
  deterministic book and curated-topic filters for random selection
- **ESV** via a free [api.esv.org](https://api.esv.org) key, or keyless
  **WEB/KJV** via bible-api.com; the ESV quietly falls back to WEB without a key.
  ESV requests explicitly disable copyright fields, and exact provider-supplied
  legal suffixes are removed before verse-marker parsing as a regression guard
- **Network-first offline fallback** using a bounded, schema-v3, strictly
  validated, HMAC-authenticated, atomically persisted passage cache; the UI
  explicitly identifies cached results
- Each pick shows a **short centered passage** (anchor ± 2 verses) with the
  anchor bright and the surroundings dimmed, revealed by a 2.2 s typewriter
- **Copy/share** the passage, reference, and compact translation name as plain
  text or a deterministic 1080 × 1350 PNG card; input, layout, image, and encoded
  output are bounded and writes use `QSaveFile`; provider copyright and legal
  blocks are never displayed, copied, shared, saved, or notified
- **Favorites** — ☆ on any verse, browse/load/remove them in Settings; persisted
  atomically to the app-data folder
- **Session history** (◀/▶) and **Jump to any reference** (`John 3:16`)
- **Fixed verse**, **daily auto-open**, and an optional resident-tray notification;
  tray messages are serialized and daily clicks reopen the immutable fetched
  verse snapshot without a random refresh
- Configurable **verse font size**, **scrim opacity**, and **animation speed**;
  zero or near-zero speed is quantized off for immediate display
- Toolbar buttons for Repeat/Another Verse, **Open in browser**, and **Share**

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
| Overlay toolbar | ◀ / ▶ history, ☆ favorite, Repeat/Another Verse, browser, **Share** |
| Overlay → **Share** | copy text, copy/save a PNG card, or copy text + card; provider legal text is omitted |
| Overlay → **JUMP TO** | type a reference, Enter — jump |
| Overlay chips | click a favorite chip to open it again |
| Tray → **Settings…** | ESV key, translation, schedule, filters, appearance, cache, favorites |

## Data & settings

- Settings (translation, fixed verse, schedules, filters, and appearance):
  `QSettings` under `HKCU\Software\davidjm\Scripture` on Windows. The ESV key is
  kept in a separate owner-only file encrypted with Windows DPAPI (macOS uses
  Keychain); it is never placed in `QSettings`, cache files, logs, URLs, or
  update metadata. Windows WinAPI libraries are loaded by absolute path from
  `GetSystemDirectoryW`, never from environment-derived paths. macOS uses direct
  `Security.framework` and `CoreFoundation` ctypes calls; no `/usr/bin/security`
  process, argv, stdin, or allow-any ACL is used. The native path must be
  runtime-verified in the frozen, signed app on the `macos-15` and
  `macos-15-intel` runners with Python 3.12.10, including keychain create/read/
  update/delete against the default login keychain; Linux tests use a fake
  framework boundary and are not a substitute for that gate. Keychain retains
  its own ACL/code-identity policy; the native path never requests an allow-any
  ACL.
- Favorites: `%APPDATA%\davidjm\Scripture\favorites.json`, written atomically
  with handle-based no-follow validation and strict JSON schema validation. Fresh
  app-data and default `Pictures/Scripture` share directories are created with
  owner-only permissions before use.
- Offline passages: schema-v3 `passage-cache.json` in the same app-data folder,
  limited to 256 entries and 90 days. Atomic replacement is paired with file
  `fsync` and directory sync; POSIX mode and Windows protected DACLs are
  owner-only, and reads reject unsafe permissions, reparse points, or identity
  changes. A random per-install 0600/DACL-protected `passage-cache.key`
  authenticates canonical provider/reference/payload fields; modified records
  fail closed. Cache entries must also agree with their provider, translation,
  requested passage/anchor, canonical reference, and focal verse. ESV
  identities are SHA-256 fingerprints, never API keys. The cache is
  deliberately **non-authoritative against the same OS user**: HMAC provides
  corruption/tamper detection, not protection from a user who can read the key.
  Provider legal/attribution blocks are not persisted in cache records.
- Daily notifications run while the resident tray app is running. A ten-minute
  due window catches up after transient startup delays. Auto-open commits only
  after its fetch succeeds; notification dedupe commits only after the queued
  tray message is dispatched. Failed fetches or unsupported tray messages
  remain retryable. Clicking a delivered daily notification opens the exact
  immutable verse snapshot without requesting another random passage.
- Book/topic filters affect only random selection; fixed verses, favorites,
  history, and direct jumps remain unfiltered. Invalid saved filters fail closed
  with a visible no-match message rather than broadening to all references.
  Settings are migrated and validated centrally, and external `QSettings` changes
  hot-reload the UI; runtimes without a bound `valueChanged` signal use a
  bounded 500 ms QSettings-value watcher.
- Every fetch snapshots translation, API-key identity, request reference,
  fallback identity, and notification intent. Range retries get a new immutable
  request derived from the original context, and superseded replies are ignored.
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
  passage_cache.py bounded schema-v3 HMAC-authenticated offline passage cache
  settings_store.py centralized settings migration, validation, and hot reload
  secure_files.py  system WinAPI loading, protected DACLs, and directory sync
  sharing.py       bounded formatted text and deterministic PNG card rendering
  references.py    curated deck, filters, and passage helpers
  VERSION          canonical release version
  qml/main.qml     overlay UI (plain Qt Quick, no Omarchy imports)
  qml/settings.qml settings dialog (own QQuickView top-level window)
tests/                 focused Python unittest coverage
```

The Omarchy plugin remains the upstream source of truth; when the two diverge,
port the change back into both.

## License

MIT — Copyright (c) 2026 David John Messenger.