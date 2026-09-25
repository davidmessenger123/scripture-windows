import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "ios/Scripture.xcodeproj/project.pbxproj"
PRIVACY = ROOT / "ios/Scripture/PrivacyInfo.xcprivacy"
ICON = ROOT / "ios/Scripture/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
API = ROOT / "ios/Scripture/Services/ScriptureAPI.swift"
MODELS = ROOT / "ios/Scripture/Models/ScriptureModels.swift"
CACHE = ROOT / "ios/Scripture/Services/PassageCache.swift"
FAVORITES = ROOT / "ios/Scripture/Services/FavoritesStore.swift"
NOTIFICATIONS = ROOT / "ios/Scripture/Services/NotificationScheduler.swift"
VIEWMODEL = ROOT / "ios/Scripture/ViewModels/ScriptureViewModel.swift"
CARD = ROOT / "ios/Scripture/Views/VerseCardView.swift"
LEGAL = ROOT / "ios/Scripture/Views/LegalPrivacyView.swift"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_png() -> None:
    data = ICON.read_bytes()
    require(data[:8] == b"\x89PNG\r\n\x1a\n", "AppIcon is not a PNG")
    offset = 8
    width = height = bit_depth = color_type = None
    has_srgb = False
    has_chrm = False
    has_gama = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR" and len(payload) >= 13:
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", payload[:13])
            require(interlace == 0, "AppIcon must not be interlaced")
        if kind == b"sRGB":
            has_srgb = True
        if kind == b"cHRM":
            has_chrm = True
        if kind == b"gAMA":
            has_gama = True
        offset += 12 + length
        if kind == b"IEND":
            break
    require((width, height) == (1024, 1024), "AppIcon must be 1024x1024")
    require(bit_depth == 8, "AppIcon must be 8-bit")
    require(color_type == 2, "AppIcon must be RGB without alpha")
    require(has_srgb or (has_chrm and has_gama), "AppIcon must declare an sRGB color profile")


def main() -> None:
    project = PROJECT.read_text()
    require(project.count("MARKETING_VERSION = 0.2.0;") == 4, "marketing version mismatch")
    require(project.count("CURRENT_PROJECT_VERSION = 2;") == 4, "build version mismatch")
    for name in (
        "PassageCache.swift in Sources",
        "VerseCardView.swift in Sources",
        "LegalPrivacyView.swift in Sources",
        "PrivacyInfo.xcprivacy in Resources",
    ):
        require(name in project, f"project membership missing: {name}")

    privacy = json.loads(PRIVACY.read_text())
    require(privacy["NSPrivacyTracking"] is False, "privacy tracking must be false")
    accessed = privacy["NSPrivacyAccessedAPITypes"]
    require(any(
        item["NSPrivacyAccessedAPIType"] == "NSPrivacyAccessedAPICategoryUserDefaults"
        and "CA92.1" in item["NSPrivacyAccessedAPITypeReasons"]
        for item in accessed
    ), "UserDefaults privacy reason missing")

    validate_png()
    api = API.read_text()
    require("bytes(for: request)" in api, "bounded network byte reader missing")
    require("canAppendResponseByte" in api, "network byte limit helper missing")
    require("CFBundleShortVersionString" in api, "version-derived user agent missing")

    models = MODELS.read_text()
    require("ScriptureVerseID" in models, "canonical verse ID model missing")
    require("static func verseIDs(" in models, "verse ID extraction missing")
    require("verseCount(forBook" in models, "book verse counts missing")
    require("ScriptureHalf" not in models, "OT/NT half model remains")

    cache = CACHE.read_text()
    require("cachesDirectory" in cache, "cache is not in Library/Caches")
    require("isExcludedFromBackup" in cache, "cache backup exclusion missing")
    require("FileProtectionType.completeUntilFirstUserAuthentication" in cache, "cache protection missing")
    require("esvKeyIdentity" in cache, "ESV cache identity missing")
    require("let verseIDs: [String]" in cache, "canonical verse IDs are not persisted")
    require("maximumVersesPerProvider = 500" in cache, "ESV provider verse limit is not 500")
    require("maximumVerses(forBook" in cache, "per-book verse limit missing")
    require("currentVersion = 3" in cache, "cache verse-ID schema version mismatch")
    require("maximumVersesPerHalf" not in cache, "OT/NT half cache policy remains")

    favorites = FAVORITES.read_text()
    require("Application Support" in favorites or "applicationSupportDirectory" in favorites, "favorites persistence disclosure source missing")
    require("func removeAll()" in favorites, "delete-all favorites store path missing")

    notifications = NOTIFICATIONS.read_text()
    require("maximumNotificationBodyBytes" in notifications, "notification body cap missing")
    require("truncateUTF8" in notifications, "UTF-8 notification truncation missing")
    require("requestMatches" in notifications, "notification request comparison missing")

    view_model = VIEWMODEL.read_text()
    for marker in (
        "CardGenerationSnapshot",
        "cardTask",
        "cardGenerationToken",
        "Task.checkCancellation()",
        "isCurrentCardSnapshot",
        "ReminderEffectiveState",
        "reminderState",
        "effectiveReminderState",
        "deletePassageCache",
        "deleteAPIKey",
        "deleteAllFavorites",
    ):
        require(marker in view_model, f"view-model behavior missing: {marker}")

    card = CARD.read_text()
    require("FileRepresentation" in card, "file-backed PNG transfer missing")
    require("SentTransferredFile" in card, "PNG filename transfer missing")

    legal = LEGAL.read_text()
    for disclosure in (
        "bible-api.com",
        "api.esv.org",
        "Authorization header",
        "expires after five minutes",
        "Delete the key below",
        "Favorites are persisted on-device",
        "device backup",
        "in memory only",
        "individual favorite",
        "Delete All Favorites",
        "No analytics or advertising SDK",
        "https://bible-api.com/",
        "https://api.esv.org/",
        "https://www.crossway.org/permissions/",
    ):
        require(disclosure in legal, f"privacy disclosure missing: {disclosure}")

    print("iOS release static checks passed")


if __name__ == "__main__":
    main()
