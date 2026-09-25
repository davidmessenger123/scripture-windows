# Scripture for iOS

This directory contains the native SwiftUI port of the Scripture desktop app.
The desktop PySide6/QML UI is not embedded in iOS; the shared behavior is
reimplemented with SwiftUI, URLSession, UserNotifications, CoreTransferable,
and the iOS Keychain.

The iOS app version is `0.2.0`.

## Open the project

1. Finish installing Xcode and its command-line tools.
2. Open `Scripture.xcodeproj`.
3. Select the `Scripture` scheme and an iPhone or iPad simulator.
4. Press **Run**.

If Xcode shows no simulator devices, install an iOS runtime from **Xcode → Settings → Components** (or run `xcodebuild -downloadPlatform iOS -architectureVariant universal`).

The project targets iOS 17.0 and is universal (iPhone and iPad). It uses the bundle identifier `com.davidjm.scripture`.

## Included features

- Curated no-repeat Scripture deck with optional ESV, WEB, and KJV providers
- Short passage context around the selected verse
- Network-first passage loading with a validated, bounded offline cache
- Explicit offline fallback notices when a saved passage is available
- Configurable book and fixed curated-topic filters
- Session history, favorites, Jump to verse, and a fixed verse of the day
- Copyable plain passage text with reference and compact translation label
- Deterministic 1080 × 1350 PNG verse cards created with `ImageRenderer`
- File-backed PNG sharing through `ShareLink`
- Configurable daily local notification content and time
- Persisted notification scheduling dedupe and reconciliation
- In-app Legal & Privacy information with Crossway permissions
- Adjustable verse size, scrim opacity, and animation/reveal speed
- Online passage links

## Passage cache and security

Successful network passages are written atomically to
`Library/Caches/Scripture/passage-cache.json`. The cache is excluded from
backup and protected until first unlock. ESV entries persist canonical
`book:chapter:verse` IDs for every verse represented by a passage, deduplicate
overlapping IDs, and enforce a provider total of 500 verses plus a per-book
limit of half that book's verses. The cache is also bounded to 1 MiB on disk
and 24,000 passage characters per record. Decoded records and the stored file
are validated before use; malformed or oversized data is ignored.

Every passage request tries the network first. The cache is consulted only
after a request fails, and the app then shows `Offline: showing the last saved
passage.` A missing or invalid cached record produces an explicit error instead
of silently presenting stale data.

The cache stores only passage content, references, internal translation metadata, and canonical verse IDs. A non-secret ESV key-generation identity separates key generations; removing or rotating a key makes older ESV entries inaccessible. ESV entries without reliable verse markers are rejected. Provider legal text is filtered before any display projection, and passage surfaces use only the compact `ESV`, `WEB`, or `KJV` label. The cache never stores the ESV API key. The key remains in the iOS Keychain with device-only protection and is kept out of `UserDefaults`, the cache file, and notification fingerprints.

## Filters

Book options are derived from the existing curated deck. Topic options use
fixed, deterministic sets such as Hope, Love, Courage, Wisdom, Prayer,
Gratitude, and Faith; every topic reference is filtered against the deck before
use, so filtering cannot introduce a new or unverified passage. An empty
book/topic intersection is rejected with an explanation and never expands to
the full deck.

Filters affect **Another verse** only. A fixed verse, favorite, history item, or
Jump to verse selection always bypasses the active filters.

## Copy, cards, and notifications

**Copy verse** writes plain text to `UIPasteboard.general` with local-only
handling and a five-minute expiration. The copied text uses line breaks between
passage segments and ends with the passage reference and a compact translation
label.

**Create card** renders a fixed-layout PNG from the current passage. For the same
passage and appearance settings, the card has no date or random content. Card
work is cancellable and guarded by a generation token and snapshot, so a stale
render cannot replace a newer card.
**Share card** exports a file-backed PNG with a filename through `ShareLink`; the
card displays the reference and compact translation label.

The daily reminder uses the existing `UNUserNotificationCenter` authorization
and scheduling flow. The saved time is the editable desired state; the UI also
tracks whether the actual notification is scheduled, blocked by authorization,
or failed to schedule. Launch and activation reconciliation update that visible
state. Scheduling is serialized, persisted dedupe state is written only after a
verified or successful schedule, and full bodies are capped by UTF-8 bytes while
the compact translation label is preserved. iOS does not perform a background
Scripture fetch, so opening the app is required to refresh notification content.

## Appearance

- Verse size is clamped to 16–44 points.
- Scrim opacity is clamped to 0–95%; zero removes the scrim overlay.
- Animation/reveal speed is clamped to 0–100%; zero disables the animation and
  shows the complete passage immediately.

All three values are persisted in `UserDefaults` and normalized again whenever
settings are loaded or saved.

## Legal & Privacy

Open **Settings → Legal & Privacy** for exact provider disclosures: WEB/KJV
references are sent to bible-api.com, while ESV references and the configured
key are sent to api.esv.org. The view links to bible-api.com terms/service
information, the ESV API terms/documentation, and Crossway permissions. It also
explains cache and Keychain retention, persisted favorites in Application
Support that may be included in device backups, in-memory-only session history,
individual and Delete All Favorites behavior, local-only clipboard expiry,
temporary PNG sharing, and the absence of analytics or advertising SDKs.
Provider legal notices are not rendered into verse, card, clipboard, or
notification output.

## Intentional iOS differences

The desktop application uses a system tray, a frameless always-on-top window,
and a timer that opens a full-screen overlay. iOS does not provide that desktop
model. The native port therefore opens directly into the verse screen. The
desktop auto-open setting is represented by a local notification; iOS cannot
force-open an app while it is suspended.

The desktop self-updater is not copied. App Store/TestFlight distribution should
use Apple's normal update mechanism.

## Signing

The project has no development team hard-coded. For a device or archive build,
select your Apple Developer team in **Project → Targets → Scripture → Signing &
Capabilities**. A personal Apple ID can run the app in the simulator without
signing setup.

## Tests

The `ScriptureTests` target covers reference expansion and parsing, no-repeat
deck behavior, Cartesian filter intersections, plain-text metadata, appearance
clamps and reveal timing, UTF-8 notification caps, desired/effective reminder
state, card snapshot invalidation, dedupe fingerprints, provider-legal-text
filtering, ESV key generations, canonical verse IDs, overlapping/repeated
anchors, short-book limits, provider totals, favorite persistence/deletion,
and passage-cache round trips/corruption.
Run it with **Product → Test** after selecting a simulator. From Terminal, an
equivalent command is:

```sh
xcodebuild -project ios/Scripture.xcodeproj \
  -scheme Scripture \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro,OS=latest' \
  test
```

The SwiftUI, UIKit, UserNotifications, CryptoKit, and XCTest checks require
Xcode and an iOS SDK. They cannot be compiled or run on Linux. The repository also includes a Linux static release check that validates
project membership, the privacy manifest, the opaque sRGB app icon, cache and
notification policies, and file-backed card transfer markers:

```sh
python3 scripts/verify_ios_release.py
```
