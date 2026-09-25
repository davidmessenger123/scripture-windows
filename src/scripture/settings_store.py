import datetime
import math
import re

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from . import references
from .errors import SecretStoreError

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ALLOWED_TRANSLATIONS = {"ESV", "WEB", "KJV"}
MIN_VERSE_FONT_PX = 18
MAX_VERSE_FONT_PX = 56
DEFAULT_VERSE_FONT_PX = 28
MIN_SCRIM_OPACITY = 0.35
MAX_SCRIM_OPACITY = 0.98
DEFAULT_SCRIM_OPACITY = 0.78
MIN_ANIMATION_SPEED = 0.0
MAX_ANIMATION_SPEED = 4.0
DEFAULT_ANIMATION_SPEED = 1.0
ANIMATION_SPEED_STEP = 0.05
MIGRATED_SETTING_KEYS = (
    "translation",
    "fixedReference",
    "autoOpenAt",
    "notificationTime",
    "notificationEnabled",
    "lastAutoOpenDay",
    "lastNotificationDay",
    "bookFilter",
    "topicFilter",
    "verseFontPx",
    "scrimOpacity",
    "animationSpeed",
)
SAVE_SETTING_KEYS = (
    "translation",
    "fixedReference",
    "autoOpenAt",
    "notificationTime",
    "notificationEnabled",
    "bookFilter",
    "topicFilter",
    "verseFontPx",
    "scrimOpacity",
    "animationSpeed",
)
HOT_RELOAD_KEYS = set(SAVE_SETTING_KEYS) | {"lastAutoOpenDay", "lastNotificationDay"}
REQUEST_KEYS = {"translation", "fixedReference", "bookFilter", "topicFilter"}


class SettingsValidationError(ValueError):
    pass


class SettingsChangeWatcher(QObject):
    changed = Signal(str, object)

    def __init__(self, settings, keys, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._keys = tuple(str(key) for key in keys)
        self._snapshot = self._read()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    def _read(self) -> dict:
        return {key: self._settings.value(key) for key in self._keys}

    def poll(self) -> None:
        current = self._read()
        for key in self._keys:
            if current[key] != self._snapshot.get(key):
                self._snapshot[key] = current[key]
                self.changed.emit(key, current[key])
        self._snapshot = current

    def resnapshot(self) -> None:
        self._snapshot = self._read()


def clean_fixed_reference(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = references.normalize_reference(text)
    if not normalized:
        raise SettingsValidationError("reference must look like John 3:16")
    return normalized


def clamp_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, number))


def clamp_float(value, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return max(minimum, min(maximum, number))


def quantize_animation_speed(value) -> float:
    speed = clamp_float(
        value,
        MIN_ANIMATION_SPEED,
        MAX_ANIMATION_SPEED,
        DEFAULT_ANIMATION_SPEED,
    )
    if speed < ANIMATION_SPEED_STEP:
        return 0.0
    return round(speed / ANIMATION_SPEED_STEP) * ANIMATION_SPEED_STEP


def setting_text(settings, key: str, default: str = "") -> str:
    return str(settings.value(key, default) or "").strip()


def setting_bool(settings, key: str, default: bool = False) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def setting_int(settings, key: str, minimum: int, maximum: int, default: int) -> int:
    return clamp_int(settings.value(key), minimum, maximum, default)


def setting_float(settings, key: str, minimum: float, maximum: float, default: float) -> float:
    return clamp_float(settings.value(key), minimum, maximum, default)


def filter_state(settings) -> tuple:
    book = setting_text(settings, "bookFilter")
    topic = setting_text(settings, "topicFilter")
    if book and book not in references.BOOKS:
        return book, topic, "The saved book filter is invalid; no references are shown."
    if topic and topic not in references.TOPICS:
        return book, topic, "The saved topic filter is invalid; no references are shown."
    if book and topic and not references.filtered_references(book, topic):
        return book, topic, "No Scripture references match both selected filters."
    return book, topic, ""


def translation_state(settings) -> str:
    value = setting_text(settings, "translation", "ESV").upper()
    return value if value in ALLOWED_TRANSLATIONS else "ESV"


def validate_persisted_settings(settings) -> list:
    notices = []
    enabled_value = settings.value("notificationEnabled", None)
    if enabled_value is not None and not isinstance(enabled_value, bool):
        if str(enabled_value).strip().lower() not in {"0", "1", "true", "false", "yes", "no", "on", "off"}:
            notices.append("Notification enablement is invalid; notifications are disabled.")
            settings.setValue("notificationEnabled", False)
    for key, label in (("autoOpenAt", "Auto-open time"), ("notificationTime", "Notification time")):
        value = setting_text(settings, key)
        if value:
            if TIME_RE.fullmatch(value):
                normalized = value
            else:
                notices.append("%s is invalid; this feature is disabled." % label)
                normalized = ""
            if normalized and setting_text(settings, key) != normalized:
                settings.setValue(key, normalized)
    fixed = setting_text(settings, "fixedReference")
    if fixed:
        try:
            normalized = clean_fixed_reference(fixed)
            if normalized != fixed:
                settings.setValue("fixedReference", normalized)
        except SettingsValidationError:
            notices.append("Fixed verse reference is invalid; fixed verse is disabled.")
    for key, valid, label in (
        ("bookFilter", references.BOOKS, "Book filter"),
        ("topicFilter", references.TOPICS, "Topic filter"),
    ):
        value = setting_text(settings, key)
        if value and value not in valid:
            notices.append("%s is invalid; random selection is disabled." % label)
    for key in ("lastAutoOpenDay", "lastNotificationDay"):
        value = setting_text(settings, key)
        if value:
            try:
                datetime.date.fromisoformat(value)
            except (TypeError, ValueError):
                notices.append("Persisted daily schedule state is invalid; today's event may retry.")
                settings.remove(key)
    translation = setting_text(settings, "translation", "ESV").upper()
    if translation and translation not in ALLOWED_TRANSLATIONS:
        notices.append("Translation is invalid; ESV is used until Settings are corrected.")
    book, topic, filter_error = filter_state(settings)
    if filter_error and filter_error.startswith("No Scripture references"):
        notices.append(filter_error)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        notices.append("Settings could not be synchronized.")
    return notices


def validate_save(
    api_key: str,
    translation: str,
    fixed_reference: str,
    auto_open_at: str,
    notification_time: str,
    book_filter: str,
    topic_filter: str,
    notification_enabled: bool,
    verse_font_px: str,
    scrim_opacity: str,
    animation_speed: str,
) -> tuple:
    auto_open_at = str(auto_open_at or "").strip()
    notification_time = str(notification_time or "").strip()
    if auto_open_at and not TIME_RE.fullmatch(auto_open_at):
        raise SettingsValidationError("Auto-open must be a 24-hour time like 07:30.")
    if notification_time and not TIME_RE.fullmatch(notification_time):
        raise SettingsValidationError("Notification time must be a 24-hour time like 07:30.")
    if notification_enabled and not notification_time:
        raise SettingsValidationError("Set a time for the daily notification.")
    selected_translation = str(translation or "").strip().upper() or "ESV"
    if selected_translation not in ALLOWED_TRANSLATIONS:
        raise SettingsValidationError("Translation must be ESV, WEB, or KJV.")
    selected_reference = clean_fixed_reference(fixed_reference)
    selected_book = str(book_filter or "").strip()
    selected_topic = str(topic_filter or "").strip()
    if selected_book and selected_book not in references.BOOKS:
        raise SettingsValidationError("Book filter is invalid.")
    if selected_topic and selected_topic not in references.TOPICS:
        raise SettingsValidationError("Topic filter is invalid.")
    if selected_book and selected_topic and not references.filtered_references(selected_book, selected_topic):
        raise SettingsValidationError("No Scripture references match both selected filters.")
    return (
        str(api_key or "").strip(),
        selected_translation,
        selected_reference,
        auto_open_at,
        notification_time,
        selected_book,
        selected_topic,
        bool(notification_enabled),
        clamp_int(verse_font_px, MIN_VERSE_FONT_PX, MAX_VERSE_FONT_PX, DEFAULT_VERSE_FONT_PX),
        clamp_float(scrim_opacity, MIN_SCRIM_OPACITY, MAX_SCRIM_OPACITY, DEFAULT_SCRIM_OPACITY),
        quantize_animation_speed(animation_speed),
    )


def migrate_legacy_api_keys(settings, legacy_settings, secret_store) -> tuple:
    value = ""
    error = ""
    try:
        value = secret_store.load()
    except SecretStoreError as exc:
        error = "Settings: %s" % exc
    for source in (settings, legacy_settings):
        if not source.contains("apiKey"):
            continue
        legacy_value = str(source.value("apiKey", "") or "").strip()
        if not legacy_value:
            source.remove("apiKey")
            source.sync()
            if source.status() != QSettings.Status.NoError and not error:
                error = "Settings: could not remove the legacy API key"
            continue
        if not value:
            try:
                secret_store.save(legacy_value)
                value = legacy_value
            except SecretStoreError as exc:
                if not error:
                    error = "Settings: %s" % exc
                continue
        source.remove("apiKey")
        source.sync()
        if source.status() != QSettings.Status.NoError and not error:
            error = "Settings: could not remove the legacy API key"
    return value, error


def migrate_startup(settings, legacy_settings, secret_store) -> tuple:
    for key in MIGRATED_SETTING_KEYS:
        if not settings.contains(key) and legacy_settings.contains(key):
            settings.setValue(key, legacy_settings.value(key))
    settings.sync()
    value, error = migrate_legacy_api_keys(settings, legacy_settings, secret_store)
    notices = validate_persisted_settings(settings)
    if notices:
        error = error or "Settings: " + " ".join(notices)
    if settings.status() != QSettings.Status.NoError:
        error = error or "Settings: could not migrate settings"
    return value, error
