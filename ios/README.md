# Scripture for iOS

This directory contains the native SwiftUI port of the Scripture desktop app.
The desktop PySide6/QML UI is not embedded in iOS; the shared behavior is
reimplemented with SwiftUI, URLSession, UserNotifications, and the iOS
Keychain.

## Open the project

1. Finish installing Xcode and its command-line tools.
2. Open `Scripture.xcodeproj`.
3. Select the `Scripture` scheme and an iPhone or iPad simulator.
4. Press **Run**.

If Xcode shows no simulator devices, install an iOS runtime from **Xcode → Settings → Components** (or run `xcodebuild -downloadPlatform iOS -architectureVariant universal`).

The project currently targets iOS 17.0 and is universal (iPhone and iPad). It uses the bundle identifier `com.davidjm.scripture`.

## Included in this first port

- Curated no-repeat Scripture deck
- ESV (with an optional user-supplied API key) and keyless WEB/KJV providers
- Short passage context around the selected verse
- Typewriter-style reveal
- Session history
- Favorites persisted in the app's Application Support directory
- Jump to any reference
- Fixed verse of the day
- Daily local notification reminder
- Online passage links

The ESV API key is stored in the iOS Keychain rather than in `UserDefaults`.

## Intentional iOS differences

The desktop application uses a system tray, a frameless always-on-top window, and a timer that opens a full-screen overlay. iOS does not provide that desktop model. The native port therefore opens directly into the verse screen. The desktop auto-open setting is represented by a local notification; iOS cannot force-open an app while it is suspended.

The desktop self-updater is not copied. App Store/TestFlight distribution should use Apple's normal update mechanism.

## Signing

The project has no development team hard-coded. For a device or archive build, select your Apple Developer team in **Project → Targets → Scripture → Signing & Capabilities**. A personal Apple ID can run the app in the simulator without signing setup.

## Tests

The `ScriptureTests` target covers reference expansion, focal verse parsing, passage splitting, time validation, and the no-repeat deck. Run it with **Product → Test** after selecting a simulator. From Terminal, an equivalent command is:

```sh
xcodebuild -project ios/Scripture.xcodeproj \
  -scheme Scripture \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro,OS=latest' \
  test
```
