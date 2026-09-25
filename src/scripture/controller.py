import datetime
import math
import re
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QTimer, Property, Signal, Slot

from . import references
from .errors import SecretStoreError
from .favorites import FavoritesError, FavoritesStore
from .fetcher import Fetcher
from .passage_cache import PassageCache, PassageCacheError, fingerprint_secret
from .secrets import SecretStore
from .secure_files import create_owner_only_directory
from .settings_store import (
    DEFAULT_ANIMATION_SPEED,
    DEFAULT_SCRIM_OPACITY,
    DEFAULT_VERSE_FONT_PX,
    HOT_RELOAD_KEYS,
    MAX_ANIMATION_SPEED,
    MAX_SCRIM_OPACITY,
    MAX_VERSE_FONT_PX,
    MIN_ANIMATION_SPEED,
    MIN_SCRIM_OPACITY,
    MIN_VERSE_FONT_PX,
    REQUEST_KEYS,
    SAVE_SETTING_KEYS,
    SettingsChangeWatcher,
    SettingsValidationError,
    TIME_RE as AUTO_OPEN_RE,
    clean_fixed_reference as _clean_fixed_reference,
    filter_state,
    migrate_legacy_api_keys,
    migrate_startup,
    quantize_animation_speed,
    setting_bool,
    setting_float,
    setting_int,
    setting_text,
    translation_state,
    validate_persisted_settings,
    validate_save,
)
from .sharing import ShareError, copy_card, copy_image, copy_plain_text, choose_and_save_card, format_plain_text, render_card

FETCH_TIMEOUT_MS = 25000
REVEAL_INTERVAL_MS = 16
REVEAL_DURATION_MS = 2200
HISTORY_CAP = 200
CHIP_CAP = 8
DAILY_DUE_WINDOW_SECONDS = 600
RANGE_UNSUPPORTED_RE = re.compile(
    r"(?:unsupported[ _-]*range|range[ _-]*not[ _-]*supported|"
    r"(?:passage[ _-]*)?ranges?[ _-]+(?:is|are)[ _-]*(?:unsupported|not[ _-]+supported)|"
    r"(?:does|do)[ _-]+not[ _-]+support[ _-]+(?:passage[ _-]*)?ranges?)",
    re.IGNORECASE,
)
AUTH_FAILURE_RE = re.compile(
    r"(?:unauthori[sz]ed|forbidden|authentication|authorization|invalid[ _-]*(?:api[ _-]*)?key|"
    r"missing[ _-]*(?:api[ _-]*)?key|credential|token)",
    re.IGNORECASE,
)
def daily_event_due(
    target: str,
    last_day: str,
    now: datetime.datetime | None = None,
    window_seconds: int = DAILY_DUE_WINDOW_SECONDS,
) -> tuple:
    current = now or datetime.datetime.now()
    current_day = "{0}-{1:02d}-{2:02d}".format(current.year, current.month, current.day)
    if not target or not AUTO_OPEN_RE.fullmatch(str(target or "")):
        return current_day, False
    try:
        hour, minute = (int(value) for value in str(target).split(":", 1))
        window = max(0, min(int(window_seconds), 86400))
    except (TypeError, ValueError, OverflowError):
        return current_day, False
    for days_ago in (0, 1):
        day_date = current - datetime.timedelta(days=days_ago)
        day = "{0}-{1:02d}-{2:02d}".format(day_date.year, day_date.month, day_date.day)
        if day == str(last_day or ""):
            continue
        scheduled = current.replace(hour=hour, minute=minute, second=0, microsecond=0) - datetime.timedelta(days=days_ago)
        elapsed = (current - scheduled).total_seconds()
        if 0 <= elapsed <= window:
            return day, True
    return current_day, False


def _data_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return str(base) if base else "."


@dataclass(frozen=True)
class DailyNotificationSnapshot:
    reference: str
    before: str
    focal: str
    after: str
    translation_id: str
    translation_name: str


@dataclass(frozen=True)
class FetchRequest:
    tag: int
    anchor: str
    passage: str
    focal: int
    provider: str
    translation_id: str
    translation_name: str
    identity: str
    api_key: str
    record_history: bool
    auto_day: str
    notification_day: str
    retried: bool
    notice: str = ""

    @property
    def notification(self) -> bool:
        return bool(self.notification_day)

    @property
    def auto_open(self) -> bool:
        return bool(self.auto_day)

    def retry(self) -> "FetchRequest":
        return replace(self, tag=0, passage=self.anchor, retried=True)


class AppController(QObject):
    verseChanged = Signal()
    displayTextChanged = Signal()
    loadingChanged = Signal()
    favoritesChanged = Signal()
    overlayChanged = Signal()
    settingsChanged = Signal()
    actionNoticeChanged = Signal()
    dailyNotificationReady = Signal(str, str)

    def __init__(
        self,
        parent=None,
        *,
        settings=None,
        legacy_settings=None,
        store=None,
        cache=None,
        secrets=None,
        fetcher=None,
        data_dir=None,
    ):
        super().__init__(parent)
        resolved_data_dir = str(data_dir or _data_dir())
        self._settings = settings if settings is not None else QSettings("davidjm", "Scripture")
        self._legacy_settings = legacy_settings if legacy_settings is not None else QSettings("davidjm", "scripture")
        self._store = store if store is not None else FavoritesStore(resolved_data_dir)
        self._cache = cache if cache is not None else PassageCache(resolved_data_dir)
        self._secrets = secrets if secrets is not None else SecretStore(resolved_data_dir)
        self._api_key_value = ""
        self._error_text = ""
        self._writing_settings = False
        try:
            create_owner_only_directory(resolved_data_dir)
        except OSError as exc:
            self._error_text = "Settings: app data directory is unavailable: %s" % exc
        migrated_key, migration_error = migrate_startup(
            self._settings, self._legacy_settings, self._secrets
        )
        self._api_key_value = migrated_key
        self._error_text = self._error_text or migration_error
        try:
            self._store.ensure_dir()
            self._favorites = self._store.list()
        except FavoritesError as exc:
            self._favorites = []
            self._error_text = self._error_text or "Favorites: %s" % exc
        try:
            self._cache.list()
        except PassageCacheError as exc:
            self._error_text = self._error_text or "Cache: %s" % exc
        self._fetcher = fetcher if fetcher is not None else Fetcher(self)
        self._fetcher.esv_result.connect(self._on_esv_result)
        self._fetcher.web_result.connect(self._on_web_result)
        self._overlay_open = False
        self._skip_next_open_refresh = False
        self._loading = False
        self._context_before = ""
        self._verse_text = ""
        self._context_after = ""
        self._verse_reference = ""
        self._translation_id = ""
        self._translation_name = ""
        self._verse_anchor = ""
        self._active_request: FetchRequest | None = None
        self._fetch_notice = ""
        self._from_cache = False
        self._fetch_seq = 0
        self._revealed_chars = -1
        self._reveal_total = 0
        self._reveal_step = 1
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(REVEAL_INTERVAL_MS)
        self._reveal_timer.timeout.connect(self._reveal_tick)
        self._history = []
        self._hist_pos = -1
        self._open_refresh_timer = QTimer(self)
        self._open_refresh_timer.setSingleShot(True)
        self._open_refresh_timer.timeout.connect(self.refresh)
        self._daily_timer = QTimer(self)
        self._daily_timer.setInterval(30_000)
        self._daily_timer.timeout.connect(self.check_auto_open)
        self._last_auto_open_day = str(self._settings.value("lastAutoOpenDay", "") or "").strip()
        self._last_notification_day = str(self._settings.value("lastNotificationDay", "") or "").strip()
        self._notification_pending = False
        self._notification_attempt_day = ""
        self._auto_open_attempt_day = ""
        self._pending_day_commits = {}
        self._daily_snapshot = None
        self._fetch_timeout = QTimer(self)
        self._fetch_timeout.setSingleShot(True)
        self._fetch_timeout.timeout.connect(self._on_fetch_timeout)
        self._filter_error = ""
        pool = self._filtered_pool()
        self._deck = references.Deck(pool) if pool else None
        self._settings_open = False
        self._settings_notice = ""
        self._settings_notice_error = False
        if self._error_text.startswith("Settings: "):
            self._settings_notice = self._error_text
            self._settings_notice_error = True
        self._action_notice = ""
        self._sync_daily_timer()
        self._update_chips()
        if hasattr(self._settings, "valueChanged"):
            self._settings.valueChanged.connect(self._on_setting_changed)
        else:
            self._settings_watcher = SettingsChangeWatcher(
                self._settings,
                HOT_RELOAD_KEYS,
                self,
            )
            self._settings_watcher.changed.connect(self._on_setting_changed)

    def _setting(self, key: str, default: str = "") -> str:
        return setting_text(self._settings, key, default)

    def _bool_setting(self, key: str, default: bool = False) -> bool:
        return setting_bool(self._settings, key, default)

    def _verse_font_px(self) -> int:
        return setting_int(
            self._settings,
            "verseFontPx",
            MIN_VERSE_FONT_PX,
            MAX_VERSE_FONT_PX,
            DEFAULT_VERSE_FONT_PX,
        )

    def _scrim_opacity_value(self) -> float:
        return setting_float(
            self._settings,
            "scrimOpacity",
            MIN_SCRIM_OPACITY,
            MAX_SCRIM_OPACITY,
            DEFAULT_SCRIM_OPACITY,
        )

    def _animation_speed_value(self) -> float:
        return quantize_animation_speed(self._settings.value("animationSpeed", DEFAULT_ANIMATION_SPEED))

    @Slot(str, str, str, str, str, str, str, bool, str, str, str, result=bool)
    def save_settings(
        self,
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
    ) -> bool:
        try:
            (
                new_key,
                translation,
                fixed_reference,
                auto_open_at,
                notification_time,
                book_filter,
                topic_filter,
                notification_enabled,
                verse_font_px,
                scrim_opacity,
                animation_speed,
            ) = validate_save(
                api_key,
                translation,
                fixed_reference,
                auto_open_at,
                notification_time,
                book_filter,
                topic_filter,
                notification_enabled,
                verse_font_px,
                scrim_opacity,
                animation_speed,
            )
        except SettingsValidationError as exc:
            return self._settings_error("Settings: %s" % exc)
        old_key = self._api_key_value
        try:
            self._secrets.save(new_key)
        except SecretStoreError as exc:
            return self._settings_error("Settings: %s" % exc)
        keys = SAVE_SETTING_KEYS
        old_values = {key: self._settings.value(key) for key in keys}
        self._writing_settings = True
        try:
            self._settings.setValue("translation", translation)
            self._settings.setValue("fixedReference", fixed_reference)
            self._settings.setValue("autoOpenAt", auto_open_at)
            self._settings.setValue("notificationTime", notification_time)
            self._settings.setValue("notificationEnabled", bool(notification_enabled))
            self._settings.setValue("bookFilter", book_filter)
            self._settings.setValue("topicFilter", topic_filter)
            self._settings.setValue("verseFontPx", verse_font_px)
            self._settings.setValue("scrimOpacity", scrim_opacity)
            self._settings.setValue("animationSpeed", animation_speed)
            self._settings.sync()
            failed = self._settings.status() != QSettings.Status.NoError
            if failed:
                for key, value in old_values.items():
                    if value is None:
                        self._settings.remove(key)
                    else:
                        self._settings.setValue(key, value)
                self._settings.sync()
        finally:
            self._writing_settings = False
        if hasattr(self, "_settings_watcher"):
            self._settings_watcher.resnapshot()
        if failed:
            try:
                self._secrets.save(old_key)
            except SecretStoreError:
                return self._settings_error("Settings and API key could not be saved.")
            return self._settings_error("Settings could not be saved.")
        self._api_key_value = new_key
        self._settings_notice = "Saved."
        self._settings_notice_error = False
        self._rebuild_deck()
        self.settingsChanged.emit()
        self._sync_daily_timer()
        self._abort_active()
        if self._overlay_open:
            self._open_refresh_timer.start(1)
        self.check_auto_open()
        return True

    def _settings_error(self, message: str) -> bool:
        self._settings_notice = message
        self._settings_notice_error = True
        self.settingsChanged.emit()
        return False

    @Slot(str, object)
    def _on_setting_changed(self, key: str, _value) -> None:
        if self._writing_settings or str(key) not in HOT_RELOAD_KEYS:
            return
        self._writing_settings = True
        try:
            notices = validate_persisted_settings(self._settings)
        finally:
            self._writing_settings = False
        self._rebuild_deck()
        if self._filter_error:
            self._error_text = self._filter_error
        elif self._error_text.startswith("The saved ") or self._error_text.startswith("No Scripture references match"):
            self._error_text = ""
        if notices:
            self._settings_notice = "Settings: " + " ".join(notices)
            self._settings_notice_error = True
        elif self._settings_notice_error and self._settings_notice.startswith("Settings: "):
            self._settings_notice = ""
            self._settings_notice_error = False
        self.settingsChanged.emit()
        self._sync_daily_timer()
        if str(key) in REQUEST_KEYS:
            self._abort_active()
            if self._overlay_open:
                self._open_refresh_timer.start(1)
        self.check_auto_open()

    def _sync_daily_timer(self) -> None:
        auto_time = self._setting("autoOpenAt")
        notification_time = self._setting("notificationTime")
        active = bool(
            (auto_time and AUTO_OPEN_RE.fullmatch(auto_time))
            or (self._notification_enabled() and notification_time and AUTO_OPEN_RE.fullmatch(notification_time))
        )
        if active and not self._daily_timer.isActive():
            self._daily_timer.start()
        elif not active:
            self._daily_timer.stop()

    def _overlay(self) -> bool:
        return self._overlay_open

    def _set_overlay(self, value: bool) -> None:
        value = bool(value)
        if value == self._overlay_open:
            return
        self._overlay_open = value
        self.overlayChanged.emit()
        if value:
            if self._skip_next_open_refresh:
                self._skip_next_open_refresh = False
            else:
                self._open_refresh_timer.start(1)
        else:
            self._open_refresh_timer.stop()

    overlayOpen = Property(bool, _overlay, _set_overlay, notify=overlayChanged)

    def _loading(self) -> bool:
        return self._loading

    loading = Property(bool, _loading, notify=loadingChanged)

    def _has_content(self) -> bool:
        return self._context_before != "" or self._verse_text != "" or self._context_after != ""

    hasContent = Property(bool, _has_content, notify=verseChanged)

    def _settings_open(self) -> bool:
        return self._settings_open

    def _set_settings_open(self, value: bool) -> None:
        value = bool(value)
        if value == self._settings_open:
            return
        self._settings_open = value
        self.settingsChanged.emit()

    settingsOpen = Property(bool, _settings_open, _set_settings_open, notify=settingsChanged)

    def toggle_settings(self) -> None:
        self.settingsOpen = not self.settings_open

    @Slot()
    def start_daily_events(self) -> None:
        self.check_auto_open()

    def _contextBefore(self) -> str:
        return self._context_before

    def _verseText(self) -> str:
        return self._verse_text

    def _contextAfter(self) -> str:
        return self._context_after

    contextBefore = Property(str, _contextBefore, notify=verseChanged)
    verseText = Property(str, _verseText, notify=verseChanged)
    contextAfter = Property(str, _contextAfter, notify=verseChanged)

    def _verse_reference(self) -> str:
        return self._verse_reference

    verseReference = Property(str, _verse_reference, notify=verseChanged)

    def _translation_id(self) -> str:
        return self._translation_id

    translationId = Property(str, _translation_id, notify=verseChanged)

    def _translation_label(self) -> str:
        return self._reported_translation().upper() if self._translation_id else ""

    translationLabel = Property(str, _translation_label, notify=verseChanged)

    def _reported_translation(self) -> str:
        if not self._translation_id:
            return ""
        value = self._translation_name or references.expected_translation_name(self._translation_id)
        return references.compact_translation_name(value)

    translationName = Property(str, _reported_translation, notify=verseChanged)

    def _display_text(self) -> str:
        if self._loading and not self._has_content():
            return "\u2026"
        if not self._has_content():
            return ""
        return references.compose_rich_text(
            self._context_before, self._verse_text, self._context_after, self._revealed_chars
        )

    displayText = Property(str, _display_text, notify=displayTextChanged)

    def _fetch_notice(self) -> str:
        return self._fetch_notice

    fetchNotice = Property(str, _fetch_notice, notify=verseChanged)

    def _error_text(self) -> str:
        return self._error_text

    errorText = Property(str, _error_text, notify=verseChanged)

    def _from_cache_value(self) -> bool:
        return self._from_cache

    fromCache = Property(bool, _from_cache_value, notify=verseChanged)

    def _current_anchor(self) -> str:
        request = self._active_request
        return self._verse_anchor or (request.anchor if request else "")

    anchor = Property(str, _current_anchor, notify=verseChanged)

    def _is_favorite(self) -> bool:
        anchor = self._current_anchor()
        return anchor != "" and anchor in self._favorites

    isFavorite = Property(bool, _is_favorite, notify=verseChanged)

    def _star_symbol(self) -> str:
        return "\u2605" if self._is_favorite() else "\u2606"

    starSymbol = Property(str, _star_symbol, notify=verseChanged)

    def _fixed(self) -> str:
        return self._setting("fixedReference")

    fixedReference = Property(str, _fixed, notify=settingsChanged)

    def _hist_can_back(self) -> bool:
        return self._hist_pos > 0 and not self._loading

    histCanBack = Property(bool, _hist_can_back, notify=verseChanged)

    def _hist_can_forward(self) -> bool:
        return 0 <= self._hist_pos < len(self._history) - 1 and not self._loading

    histCanForward = Property(bool, _hist_can_forward, notify=verseChanged)

    def _favorites(self) -> list:
        return self._favorites

    favorites = Property(list, _favorites, notify=favoritesChanged)

    def _chips(self) -> list:
        return self._favorites[:CHIP_CAP]

    favoritesChips = Property(list, _chips, notify=favoritesChanged)

    def _overflow(self) -> int:
        return max(0, len(self._favorites) - CHIP_CAP)

    favoritesOverflow = Property(int, _overflow, notify=favoritesChanged)

    def _settings_api_key(self) -> str:
        return self._api_key_value

    settingsApiKey = Property(str, _settings_api_key, notify=settingsChanged)

    def _settings_translation(self) -> str:
        return translation_state(self._settings)

    settingsTranslation = Property(str, _settings_translation, notify=settingsChanged)

    def _settings_fixed(self) -> str:
        return self._setting("fixedReference")

    settingsFixedReference = Property(str, _settings_fixed, notify=settingsChanged)

    def _settings_auto(self) -> str:
        return self._setting("autoOpenAt")

    settingsAutoOpenAt = Property(str, _settings_auto, notify=settingsChanged)

    def _settings_notification_time(self) -> str:
        return self._setting("notificationTime")

    settingsNotificationTime = Property(str, _settings_notification_time, notify=settingsChanged)

    def _notification_enabled(self) -> bool:
        return self._bool_setting("notificationEnabled")

    settingsNotificationEnabled = Property(bool, _notification_enabled, notify=settingsChanged)

    def _settings_book(self) -> str:
        return self._setting("bookFilter")

    settingsBookFilter = Property(str, _settings_book, notify=settingsChanged)

    def _settings_topic(self) -> str:
        return self._setting("topicFilter")

    settingsTopicFilter = Property(str, _settings_topic, notify=settingsChanged)

    def _filter_error_value(self) -> str:
        return self._filter_error

    filterError = Property(str, _filter_error_value, notify=settingsChanged)

    def _available_books(self) -> list:
        return list(references.BOOKS)

    availableBooks = Property(list, _available_books, notify=settingsChanged)

    def _available_topics(self) -> list:
        return list(references.TOPICS)

    availableTopics = Property(list, _available_topics, notify=settingsChanged)

    def _settings_font(self) -> int:
        return self._verse_font_px()

    settingsVerseFontPx = Property(int, _settings_font, notify=settingsChanged)

    def _settings_opacity(self) -> float:
        return self._scrim_opacity_value()

    settingsScrimOpacity = Property(float, _settings_opacity, notify=settingsChanged)

    def _settings_speed(self) -> float:
        return self._animation_speed_value()

    settingsAnimationSpeed = Property(float, _settings_speed, notify=settingsChanged)

    def _settings_notice(self) -> str:
        return self._settings_notice

    settingsNotice = Property(str, _settings_notice, notify=settingsChanged)

    def _settings_notice_error(self) -> bool:
        return self._settings_notice_error

    settingsNoticeError = Property(bool, _settings_notice_error, notify=settingsChanged)

    def _action_notice_value(self) -> str:
        return self._action_notice

    actionNotice = Property(str, _action_notice_value, notify=actionNoticeChanged)

    def _cache_size(self) -> int:
        try:
            return self._cache.size()
        except PassageCacheError:
            return 0

    passageCacheSize = Property(int, _cache_size, notify=actionNoticeChanged)

    @Slot()
    def close_overlay(self) -> None:
        self.overlayOpen = False

    @Slot()
    def toggle_overlay(self) -> None:
        self.overlayOpen = not self._overlay_open

    @Slot()
    def show_current_verse(self) -> None:
        self._open_refresh_timer.stop()
        if not self._overlay_open:
            self._skip_next_open_refresh = True
        self.overlayOpen = True

    def daily_snapshot(self, reference: str):
        snapshot = self._daily_snapshot
        if snapshot is not None and snapshot.reference == str(reference or ""):
            return snapshot
        return None

    @Slot(str)
    def show_daily_verse(self, reference: str) -> None:
        snapshot = self.daily_snapshot(reference)
        if snapshot is not None:
            self.show_daily_snapshot(snapshot)

    @Slot(object)
    def show_daily_snapshot(self, snapshot) -> None:
        if not isinstance(snapshot, DailyNotificationSnapshot):
            return
        self._abort_active()
        self._open_refresh_timer.stop()
        self._context_before = snapshot.before
        self._verse_text = snapshot.focal
        self._context_after = snapshot.after
        self._verse_reference = snapshot.reference
        self._translation_id = snapshot.translation_id
        self._translation_name = snapshot.translation_name
        self._verse_anchor = snapshot.reference
        self._loading = False
        self._from_cache = False
        self._start_reveal()
        self.verseChanged.emit()
        self.displayTextChanged.emit()
        if not self._overlay_open:
            self._skip_next_open_refresh = True
        self.overlayOpen = True

    @Slot(str)
    def load_reference(self, reference: str) -> None:
        try:
            ref = _clean_fixed_reference(reference)
        except ValueError as exc:
            self._error_text = "Reference: %s" % exc
            self.verseChanged.emit()
            return
        if not ref:
            return
        self._open_refresh_timer.stop()
        if not self._overlay_open:
            self._skip_next_open_refresh = True
        self.overlayOpen = True
        self._verse_anchor = ref
        self._fetch(ref, record_history=True)

    @Slot()
    def refresh(self) -> None:
        self._refresh()

    def _refresh(self, auto_day: str = "", notification_day: str = "") -> None:
        self._open_refresh_timer.stop()
        try:
            fixed = _clean_fixed_reference(self._setting("fixedReference"))
        except SettingsValidationError as exc:
            self._abort_active()
            self._error_text = "Reference: %s" % exc
            self.verseChanged.emit()
            self.displayTextChanged.emit()
            return
        if fixed:
            self._verse_anchor = fixed
            self._fetch(fixed, record_history=True, auto_day=auto_day, notification_day=notification_day)
        else:
            pool = self._filtered_pool()
            if not pool or self._deck is None:
                self._abort_active()
                self._error_text = self._filter_error or "No Scripture references match the selected filters."
                self._loading = False
                self.loadingChanged.emit()
                self.verseChanged.emit()
                self.displayTextChanged.emit()
                return
            ref = self._deck.draw(self._verse_anchor or (self._active_request.anchor if self._active_request else ""))
            self._verse_anchor = ref
            self._fetch(ref, record_history=True, auto_day=auto_day, notification_day=notification_day)

    @Slot()
    def back(self) -> None:
        self._open_refresh_timer.stop()
        if self._hist_pos <= 0:
            return
        self._hist_pos -= 1
        self._fetch(self._history[self._hist_pos], record_history=False)

    @Slot()
    def forward(self) -> None:
        self._open_refresh_timer.stop()
        if self._hist_pos < 0 or self._hist_pos >= len(self._history) - 1:
            return
        self._hist_pos += 1
        self._fetch(self._history[self._hist_pos], record_history=False)

    @Slot(str)
    def open_in_browser(self, reference: str) -> None:
        try:
            ref = _clean_fixed_reference(reference or self._verse_reference)
        except ValueError as exc:
            self._error_text = "Reference: %s" % exc
            self.verseChanged.emit()
            return
        if not ref:
            return
        url = references.browser_url(ref, self._translation_id)
        if not url:
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            target = QUrl(url)
            if target.isValid() and target.scheme() == "https" and target.host() in {"www.esv.org", "www.biblegateway.com"}:
                QDesktopServices.openUrl(target)
        except Exception:
            pass

    @Slot()
    def copy_verse_text(self) -> None:
        try:
            copy_plain_text(self._share_text())
            self._set_action_notice("Verse text copied.")
        except ShareError as exc:
            self._set_action_notice(str(exc), True)

    @Slot()
    def copy_verse_card(self) -> None:
        try:
            text = self._share_text()
            copy_image(render_card(text))
            self._set_action_notice("Verse card copied to the clipboard.")
        except ShareError as exc:
            self._set_action_notice(str(exc), True)

    @Slot()
    def share_verse_card(self) -> None:
        try:
            text = self._share_text()
            copy_card(text, render_card(text))
            self._set_action_notice("Verse text and card copied. Paste into another app to share.")
        except ShareError as exc:
            self._set_action_notice(str(exc), True)

    @Slot()
    def save_verse_card(self) -> None:
        try:
            text = self._share_text()
            path = choose_and_save_card(text, render_card(text), self._verse_reference)
            if path:
                self._set_action_notice("Verse card saved.")
        except ShareError as exc:
            self._set_action_notice(str(exc), True)

    @Slot()
    def clear_passage_cache(self) -> None:
        try:
            self._cache.clear()
            self._set_action_notice("Offline passage cache cleared.")
        except PassageCacheError as exc:
            self._set_action_notice("Cache: %s" % exc, True)

    def _share_text(self) -> str:
        return format_plain_text(
            self._context_before,
            self._verse_text,
            self._context_after,
            self._verse_reference,
            self._translation_name,
        )

    def _set_action_notice(self, message: str, error: bool = False) -> None:
        self._action_notice = str(message or "")
        if error:
            self._error_text = self._action_notice
        self.actionNoticeChanged.emit()
        if error:
            self.verseChanged.emit()

    @Slot()
    def toggle_favorite(self) -> None:
        anchor = self._current_anchor()
        if not anchor:
            return
        try:
            if anchor in self._favorites:
                self._favorites = self._store.remove(anchor, current=self._favorites)
            else:
                self._favorites = self._store.add(anchor, current=self._favorites)
            self._error_text = ""
            self.favoritesChanged.emit()
            self.verseChanged.emit()
        except FavoritesError as exc:
            self._error_text = "Favorites: %s" % exc
            self.verseChanged.emit()

    @Slot(str)
    def remove_favorite(self, anchor: str) -> None:
        anchor = str(anchor or "").strip()
        if not anchor:
            return
        try:
            self._favorites = self._store.remove(anchor, current=self._favorites)
            self._error_text = ""
            self.favoritesChanged.emit()
            self.verseChanged.emit()
        except FavoritesError as exc:
            self._error_text = "Favorites: %s" % exc
            self.verseChanged.emit()

    @Slot()
    def check_auto_open(self) -> None:
        self._retry_pending_day_commits()
        now = datetime.datetime.now()
        auto_day, auto_due = daily_event_due(self._setting("autoOpenAt"), self._last_auto_open_day, now)
        notification_day, notification_due = daily_event_due(
            self._setting("notificationTime"),
            self._last_notification_day,
            now,
        )
        if not self._notification_enabled():
            notification_due = False
        if self._notification_attempt_day and self._notification_attempt_day != notification_day:
            self._notification_attempt_day = ""
            self._notification_pending = False
        if self._auto_open_attempt_day and self._auto_open_attempt_day != auto_day:
            self._auto_open_attempt_day = ""
        if self._active_request is not None:
            return
        start_auto = auto_due and not self._auto_open_attempt_day
        start_notification = notification_due and not self._notification_attempt_day
        if not start_auto and not start_notification:
            return
        if start_auto:
            self._auto_open_attempt_day = auto_day
        if start_notification:
            self._notification_attempt_day = notification_day
            self._notification_pending = True
        self._refresh(
            auto_day=auto_day if start_auto else "",
            notification_day=notification_day if start_notification else "",
        )

    def _commit_daily_day(self, kind: str, day: str) -> None:
        if not day:
            return
        if kind == "auto":
            self._last_auto_open_day = day
            self._auto_open_attempt_day = ""
            key = "lastAutoOpenDay"
        else:
            self._last_notification_day = day
            key = "lastNotificationDay"
        self._settings.setValue(key, day)
        self._settings.sync()
        if self._settings.status() == QSettings.Status.NoError:
            self._pending_day_commits.pop((kind, day), None)
            return
        self._pending_day_commits[(kind, day)] = day
        self._settings_notice = "Settings: daily delivery state could not be synchronized."
        self._settings_notice_error = True
        self.settingsChanged.emit()

    def _retry_pending_day_commits(self) -> None:
        for kind, day in tuple(self._pending_day_commits.items()):
            key = "lastAutoOpenDay" if kind == "auto" else "lastNotificationDay"
            self._settings.setValue(key, day)
            self._settings.sync()
            if self._settings.status() == QSettings.Status.NoError:
                self._pending_day_commits.pop((kind, day), None)
                if self._settings_notice == "Settings: daily delivery state could not be synchronized.":
                    self._settings_notice = ""
                    self._settings_notice_error = False
                    self.settingsChanged.emit()

    @Slot()
    def mark_daily_notification_delivered(self) -> None:
        day = self._notification_attempt_day
        self._notification_pending = False
        self._notification_attempt_day = ""
        if day:
            self._commit_daily_day("notification", day)

    @Slot()
    def cancel_daily_notification_attempt(self) -> None:
        self._notification_pending = False
        self._notification_attempt_day = ""


    def liveTip(self) -> str:
        return "Scripture — %s" % self._verse_reference if self._verse_reference else "Scripture"

    def _provider_choice(self) -> str:
        return translation_state(self._settings).lower()

    def _api_key(self) -> str:
        return self._api_key_value

    def _next_request_tag(self) -> int:
        self._fetch_seq += 1
        return self._fetch_seq

    def _abort_active(self, clear_notification: bool = True) -> None:
        had_request = self._active_request is not None
        self._fetch_seq += 1
        self._fetch_timeout.stop()
        self._active_request = None
        if had_request:
            self._fetcher.abort()
        if self._loading:
            self._loading = False
            self.loadingChanged.emit()
        if clear_notification:
            self._notification_pending = False
            self._notification_attempt_day = ""
            self._auto_open_attempt_day = ""

    def _fail_active_request(self, message: str) -> None:
        request = self._active_request
        self._fetch_seq += 1
        self._fetch_timeout.stop()
        self._active_request = None
        if request is not None:
            self._fetcher.abort()
        self._loading = False
        self.loadingChanged.emit()
        if request is not None and request.notification:
            self._notification_pending = False
            self._notification_attempt_day = ""
        if request is not None and request.auto_open:
            self._auto_open_attempt_day = ""
        self._error_text = str(message or "Could not load that passage. Try again.")
        self.verseChanged.emit()
        self.displayTextChanged.emit()

    def _fetch(
        self,
        anchor: str,
        record_history: bool,
        auto_day: str = "",
        notification_day: str = "",
    ) -> None:
        try:
            anchor = _clean_fixed_reference(anchor)
        except SettingsValidationError as exc:
            self._fail_active_request("Reference: %s" % exc)
            return
        if not anchor:
            return
        choice = self._provider_choice()
        key = self._api_key()
        provider = choice
        identity = ""
        request_key = ""
        notice = ""
        if choice == "esv" and key:
            provider = "esv"
            identity = fingerprint_secret(key)
            request_key = key
        elif choice == "esv":
            provider = "web"
            notice = "Set an ESV API key in Settings to read the ESV — showing the World English Bible."
        request = FetchRequest(
            tag=self._next_request_tag(),
            anchor=anchor,
            passage=references.range_query(anchor),
            focal=references.focal_verse(anchor),
            provider=provider,
            translation_id=provider,
            translation_name=references.expected_translation_name(provider),
            identity=identity,
            api_key=request_key,
            record_history=bool(record_history),
            auto_day=str(auto_day or ""),
            notification_day=str(notification_day or ""),
            retried=False,
            notice=notice,
        )
        if record_history:
            self._record_history(anchor)
        self._abort_active(clear_notification=not bool(auto_day or notification_day))
        self._start_request(request)

    def _start_request(self, request: FetchRequest) -> None:
        self._active_request = request
        self._loading = True
        self._error_text = ""
        self._fetch_notice = request.notice
        self._from_cache = False
        self._notification_pending = bool(request.notification)
        self._translation_id = request.translation_id
        self._translation_name = request.translation_name
        self._verse_reference = ""
        self._fetch_timeout.start(FETCH_TIMEOUT_MS)
        self.loadingChanged.emit()
        self.verseChanged.emit()
        self.displayTextChanged.emit()
        try:
            if request.provider == "esv":
                self._fetcher.fetch_esv(request.tag, request.passage, request.api_key)
            else:
                self._fetcher.fetch_web(request.tag, request.passage, request.provider)
        except Exception:
            self._fail_active_request("Could not start the passage request.")

    def _retry_request(self, request: FetchRequest) -> None:
        if request.retried:
            self._fail_active_request("Could not load that passage. Try again.")
            return
        retry = replace(request, tag=self._next_request_tag(), passage=request.anchor, retried=True)
        self._start_request(retry)

    def _on_fetch_timeout(self) -> None:
        request = self._active_request
        if request is None or not self._loading:
            return
        self._fetch_seq += 1
        self._fetcher.abort()
        try:
            if self._try_cached_fallback(request, "Offline fallback: the network timed out."):
                return
        except Exception:
            pass
        self._fail_active_request("The verse fetch timed out. Try again.")

    def _on_esv_result(self, tag: int, body: str, error: str, status: int) -> None:
        try:
            self._handle_esv_result(tag, body, error, status)
        except Exception:
            request = self._active_request
            if request is not None and request.tag == tag:
                self._fail_active_request("The ESV response could not be processed.")

    def _handle_esv_result(self, tag: int, body: str, error: str, status: int) -> None:
        request = self._active_request
        if request is None or request.tag != tag or not self._loading or request.provider != "esv":
            return
        self._fetch_timeout.stop()
        try:
            payload = parse_json(body) if body else None
        except (TypeError, ValueError):
            payload = None
        ok = not error and valid_esv_payload(payload)
        if not ok and should_retry_range(
            request.provider,
            request.passage,
            request.anchor,
            body,
            error,
            status,
            request.retried,
        ):
            self._retry_request(request)
            return
        if not ok:
            if self._cache_failure_eligible(error, status) and self._try_cached_fallback(
                request, "Cached fallback: the ESV service was unavailable."
            ):
                return
            self._fail_active_request("Could not load from the ESV API. Check your key and connection.")
            return
        try:
            if "canonical" not in payload:
                raise ValueError("ESV response has no canonical reference")
            reference = references.normalize_reference(payload.get("canonical"))
            if not reference or reference not in {request.anchor, request.passage}:
                raise ValueError("ESV reference does not match request")
            cleaned = references.strip_esv_legal_suffix(
                payload["passages"][0],
                str(payload.get("copyright") or ""),
                str(payload.get("attribution") or ""),
            )
            if references.esv_legal_text_present(cleaned):
                raise ValueError("ESV legal text was not isolated from the verse")
            before, focal, after = references.parse_numbered_passage(cleaned, request.focal)
            _validate_response_passage(request, before, focal, after)
            self._apply_verse(
                request,
                before,
                focal,
                after,
                reference,
                request.translation_id,
                request.translation_name,
                esv_attribution(payload),
            )
        except Exception:
            self._fail_active_request("The ESV response was incomplete or inconsistent.")

    def _on_web_result(self, tag: int, body: str, error: str, status: int) -> None:
        try:
            self._handle_web_result(tag, body, error, status)
        except Exception:
            request = self._active_request
            if request is not None and request.tag == tag:
                self._fail_active_request("The passage response could not be processed.")

    def _handle_web_result(self, tag: int, body: str, error: str, status: int) -> None:
        request = self._active_request
        if request is None or request.tag != tag or not self._loading or request.provider not in {"web", "kjv"}:
            return
        self._fetch_timeout.stop()
        try:
            payload = parse_json(body) if body else None
        except (TypeError, ValueError):
            payload = None
        ok = not error and valid_web_payload(payload)
        if not ok and should_retry_range(
            request.provider,
            request.passage,
            request.anchor,
            body,
            error,
            status,
            request.retried,
        ):
            self._retry_request(request)
            return
        if not ok:
            if self._cache_failure_eligible(error, status) and self._try_cached_fallback(
                request, "Cached fallback: the passage service was unavailable."
            ):
                return
            self._fail_active_request("Could not load that passage. Try again.")
            return
        try:
            reported_name = references.compact_translation_name(references.translation_text(payload))
            if reported_name and reported_name != request.translation_name:
                raise ValueError("translation does not match request")
            translation = payload.get("translation")
            if isinstance(translation, dict):
                for identity_key in ("id", "short_name"):
                    identity_value = translation.get(identity_key)
                    if identity_value is not None:
                        if not isinstance(identity_value, str) or identity_value.strip().lower() != request.provider:
                            raise ValueError("translation identity does not match request")
            before, focal, after = references.parse_web_passage(payload, request.focal)
            if "reference" not in payload:
                raise ValueError("passage response has no reference")
            reference = references.reference_text(payload)
            if not reference or reference not in {request.anchor, request.passage}:
                raise ValueError("reference does not match request")
            _validate_response_passage(request, before, focal, after)
            attribution = str(payload.get("attribution") or payload.get("copyright") or "").strip()
            self._apply_verse(
                request,
                before,
                focal,
                after,
                reference,
                request.provider,
                request.translation_name,
                attribution,
            )
        except Exception:
            self._fail_active_request("The passage response was incomplete or inconsistent.")

    def _cache_failure_eligible(self, error: str, status: int) -> bool:
        if status in {401, 403, 404, 422}:
            return False
        if status == 0:
            text = str(error or "").lower()
            return "network" in text or "timed out" in text or "canceled" in text or "redirect" in text
        return status in {408, 429} or 500 <= status < 600

    def _try_cached_fallback(self, request: FetchRequest, message: str) -> bool:
        try:
            entry = self._cache.get(
                request.provider,
                request.passage,
                request.anchor,
                request.identity,
            )
        except PassageCacheError as exc:
            self._error_text = "Cache: %s" % exc
            self.verseChanged.emit()
            return False
        if not entry:
            return False
        if (
            entry.get("provider") != request.provider
            or entry.get("translation_id") != request.translation_id
            or entry.get("translation_name") != request.translation_name
        ):
            return False
        self._fetch_notice = "%s Reference: %s." % (message, entry["reference"])
        try:
            self._apply_verse(
                request,
                entry["before"],
                entry["focal"],
                entry["after"],
                entry["reference"],
                request.translation_id,
                request.translation_name,
                entry["attribution"],
                from_cache=True,
                persist=False,
            )
        except Exception:
            self._error_text = "Cache: cached passage validation failed"
            return False
        return True

    def _apply_verse(
        self,
        request: FetchRequest,
        before: str,
        focal: str,
        after: str,
        reference: str,
        translation_id: str,
        translation_name: str,
        attribution: str = "",
        from_cache: bool = False,
        persist: bool = True,
    ) -> None:
        if self._active_request is None or self._active_request != request:
            return
        normalized_reference = references.normalize_reference(reference) or request.passage
        normalized_translation = references.compact_translation_name(translation_name)
        if translation_id != request.translation_id or normalized_translation != request.translation_name:
            raise ValueError("cache translation does not match request")
        if normalized_reference not in {request.anchor, request.passage}:
            raise ValueError("cache reference does not match request")
        _validate_response_passage(request, before, focal, after)
        self._context_before = str(before or "")
        self._verse_text = str(focal or "")
        self._context_after = str(after or "")
        self._verse_reference = normalized_reference
        self._translation_id = request.translation_id
        self._translation_name = request.translation_name
        if request.notification:
            self._daily_snapshot = DailyNotificationSnapshot(
                reference=self._verse_reference,
                before=self._context_before,
                focal=self._verse_text,
                after=self._context_after,
                translation_id=self._translation_id,
                translation_name=self._translation_name,
            )
        payload_attribution = ""
        self._from_cache = bool(from_cache)
        self._active_request = None
        self._loading = False
        self.loadingChanged.emit()
        if persist:
            try:
                self._cache.put(
                    request.provider,
                    request.translation_id,
                    request.passage,
                    request.anchor,
                    request.identity,
                    self._context_before,
                    self._verse_text,
                    self._context_after,
                    self._verse_reference,
                    self._translation_name,
                    payload_attribution,
                )
                self.actionNoticeChanged.emit()
            except PassageCacheError as exc:
                suffix = " Offline cache could not be updated: %s" % exc
                self._fetch_notice = (self._fetch_notice + suffix).strip()
        self.verseChanged.emit()
        self.displayTextChanged.emit()
        self._start_reveal()
        if request.auto_open:
            self._commit_daily_day("auto", request.auto_day)
            self.show_current_verse()
        if request.notification:
            self.dailyNotificationReady.emit(self._verse_reference, self._translation_name)

    def _record_history(self, anchor: str) -> None:
        if self._history and self._history[-1] == anchor:
            return
        self._history = (self._history + [anchor])[-HISTORY_CAP:]
        self._hist_pos = len(self._history) - 1

    def _start_reveal(self) -> None:
        total = len(self._context_before) + len(self._verse_text) + len(self._context_after)
        self._reveal_total = total if total > 0 else 0
        speed = self._animation_speed_value()
        if total <= 0:
            self._revealed_chars = 0
            return
        if speed <= 0:
            self._revealed_chars = total
            self._reveal_timer.stop()
            self.displayTextChanged.emit()
            return
        duration = REVEAL_DURATION_MS / speed
        self._reveal_step = max(1, math.ceil(total * REVEAL_INTERVAL_MS / duration))
        self._revealed_chars = 0
        self.displayTextChanged.emit()
        self._reveal_timer.start()

    def _reveal_tick(self) -> None:
        self._revealed_chars = min(self._reveal_total, self._revealed_chars + self._reveal_step)
        if self._revealed_chars >= self._reveal_total:
            self._revealed_chars = self._reveal_total
            self._reveal_timer.stop()
        self.displayTextChanged.emit()

    def _filtered_pool(self) -> list:
        book, topic, error = filter_state(self._settings)
        self._filter_error = error
        if error:
            return []
        pool = references.filtered_references(book, topic)
        if not pool and (book or topic):
            self._filter_error = "No Scripture references match the selected filters."
        return pool

    def _rebuild_deck(self) -> None:
        pool = self._filtered_pool()
        self._deck = references.Deck(pool) if pool else None

    def _update_chips(self) -> None:
        self.favoritesChanged.emit()


def _validate_response_passage(request: FetchRequest, before: str, focal: str, after: str) -> None:
    parts = (str(before or ""), str(focal or ""), str(after or ""))
    if not parts[1].strip():
        raise ValueError("focal verse is missing")
    if sum(len(part.encode("utf-8")) for part in parts) > references.MAX_RESPONSE_BYTES:
        raise ValueError("passage exceeds the response limit")
    if any(any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in part) for part in parts):
        raise ValueError("passage contains control characters")
    if request.focal and "[%d]" % request.focal not in parts[1]:
        raise ValueError("focal verse is missing")
    if not parts[0] and not parts[2] and "[" not in parts[1]:
        raise ValueError("passage is structurally incomplete")


def should_retry_range(
    provider: str,
    range_reference: str,
    anchor_reference: str,
    body: str,
    error: str,
    http_status: int,
    already_retried: bool = False,
) -> bool:
    if already_retried or http_status not in {400, 404, 422}:
        return False
    if str(error or "") != "server returned HTTP %d" % int(http_status):
        return False
    requested_range = references.normalize_reference(range_reference)
    anchor = references.normalize_reference(anchor_reference)
    if not requested_range or not anchor or requested_range == anchor or not re.search(r":\d+-\d+$", requested_range):
        return False
    try:
        payload = parse_json(body)
    except (TypeError, ValueError):
        return False
    provider_id = str(provider or "").strip().lower()
    if provider_id == "web":
        if "verses" in payload or not isinstance(payload.get("error"), str):
            return False
        values = [payload["error"]]
    elif provider_id == "esv":
        if "passages" in payload:
            return False
        values = []
        for key in ("code", "message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, dict):
                for nested in ("code", "message", "detail"):
                    if isinstance(value.get(nested), str):
                        values.append(value[nested])
    else:
        return False
    if not values or AUTH_FAILURE_RE.search(" ".join(values)):
        return False
    return any(RANGE_UNSUPPORTED_RE.search(value) for value in values)


def parse_json(text: str) -> dict:
    import json

    if not isinstance(text, str):
        raise ValueError("invalid JSON response")
    try:
        if len(text.encode("utf-8")) > references.MAX_RESPONSE_BYTES:
            raise ValueError("invalid JSON response")
    except UnicodeError as exc:
        raise ValueError("invalid JSON response") from exc
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("JSON response is not an object")
    return payload


def esv_attribution(payload: dict) -> str:
    return ""


def valid_esv_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    passages = payload.get("passages")
    if not isinstance(passages, list) or not passages or len(passages) > 32 or any(not isinstance(item, str) or not item.strip() for item in passages):
        return False
    if "canonical" not in payload or not isinstance(payload["canonical"], str) or not references.normalize_reference(payload["canonical"]):
        return False
    for key in ("copyright", "attribution"):
        if key in payload and not isinstance(payload[key], str):
            return False
    return True


def valid_web_payload(payload: dict) -> bool:
    if not isinstance(payload, dict) or "error" in payload:
        return False
    verses = payload.get("verses")
    if not isinstance(verses, list) or not verses or len(verses) > 32:
        return False
    for verse in verses:
        if not isinstance(verse, dict) or not isinstance(verse.get("text"), str) or not verse["text"].strip():
            return False
        if "verse" not in verse and "number" not in verse:
            return False
        for key in ("verse", "number"):
            if key in verse:
                value = verse[key]
                if isinstance(value, bool) or not isinstance(value, (int, str)):
                    return False
                if isinstance(value, str) and (not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 999):
                    return False
                if isinstance(value, int) and not 1 <= value <= 999:
                    return False
    if "reference" not in payload or not isinstance(payload["reference"], str) or not references.normalize_reference(payload["reference"]):
        return False
    for key in ("attribution", "copyright", "translation_name"):
        if key in payload and not isinstance(payload[key], str):
            return False
    translation = payload.get("translation")
    if translation is not None:
        if not isinstance(translation, dict):
            return False
        for key in ("name", "id", "short_name"):
            if key in translation and not isinstance(translation[key], str):
                return False
    return True
