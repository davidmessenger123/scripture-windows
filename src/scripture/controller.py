"""The Scripture desktop app controller.

One QObject exposed to the QML UI as the `app` singleton. It mirrors the Omarchy
widget's state (verse text/context, translation, history, favorites, reveal
progress, notices) and its behaviors (provider selection with keyless fallback,
single plain-anchor retry per fetch, no-repeat deck, 25 s fetch timeout, 8-chip
favorites, at-most-once-per-day auto-open) without touching any Omarchy API.
"""

import math
import re

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QTimer, Property, Signal, Slot

from . import references
from .errors import SecretStoreError
from .favorites import FavoritesError, FavoritesStore
from .fetcher import Fetcher
from .secrets import SecretStore

AUTO_OPEN_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
FETCH_TIMEOUT_MS = 25000
REVEAL_INTERVAL_MS = 16
REVEAL_DURATION_MS = 2200
HISTORY_CAP = 200
CHIP_CAP = 8
ALLOWED_TRANSLATIONS = {"ESV", "WEB", "KJV"}
ESV_ATTRIBUTION = "Scripture quotations are from the ESV® Bible (The Holy Bible, English Standard Version®), © 2001 by Crossway. Used by permission. All rights reserved. esv.org"
RANGE_UNSUPPORTED_RE = re.compile(
    r"(?:unsupported[ _-]*range|range[ _-]*not[ _-]*supported|"
    r"(?:passage[ _-]*)?ranges?[ _-]+(?:is|are)[ _-]+(?:unsupported|not[ _-]+supported)|"
    r"(?:does|do)[ _-]+not[ _-]+support[ _-]+(?:passage[ _-]*)?ranges?)",
    re.IGNORECASE,
)
AUTH_FAILURE_RE = re.compile(
    r"(?:unauthori[sz]ed|forbidden|authentication|authorization|invalid[ _-]*(?:api[ _-]*)?key|"
    r"missing[ _-]*(?:api[ _-]*)?key|credential|token)",
    re.IGNORECASE,
)


def _clean_fixed_reference(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = references.normalize_reference(text)
    if not normalized:
        raise ValueError("reference must look like John 3:16")
    return normalized


_ORG = "davidjm"
_APP = "Scripture"
_LEGACY_APP = "scripture"


def _data_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return str(base) if base else "."


def migrate_legacy_api_keys(settings, legacy_settings, secret_store) -> tuple[str, str]:
    value = ""
    error = ""
    try:
        value = secret_store.load()
    except SecretStoreError as exc:
        error = "Settings: %s" % exc
    for source in (settings, legacy_settings):
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


class AppController(QObject):
    # -- notifications ----------------------------------------------------
    verseChanged = Signal()
    displayTextChanged = Signal()  # reveal ticks only — not full verseChanged
    loadingChanged = Signal()
    favoritesChanged = Signal()
    overlayChanged = Signal()
    settingsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings(_ORG, _APP)
        self._legacy_settings = QSettings(_ORG, _LEGACY_APP)
        self._store = FavoritesStore(_data_dir())
        self._secrets = SecretStore(_data_dir())
        self._api_key_value = ""
        self._error_text = ""
        for key in ("translation", "fixedReference", "autoOpenAt", "lastAutoOpenDay"):
            if not self._settings.contains(key) and self._legacy_settings.contains(key):
                self._settings.setValue(key, self._legacy_settings.value(key))
        self._settings.sync()
        self._api_key_value, self._error_text = migrate_legacy_api_keys(
            self._settings, self._legacy_settings, self._secrets
        )
        try:
            self._store.ensure_dir()
            self._favorites = self._store.list()
        except FavoritesError as exc:
            self._favorites = []
            self._error_text = self._error_text or "Favorites: %s" % exc

        self._fetcher = Fetcher(self)
        self._fetcher.esv_result.connect(self._on_esv_result)
        self._fetcher.web_result.connect(self._on_web_result)

        # verse state
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
        self._pending_anchor = ""
        self._pending_reference = ""
        self._pending_focal = 0
        self._web_retried = False
        self._esv_retried = False
        self._current_web_translation = "web"
        self._fetch_notice = ""
        self._translation_attribution = ""
        self._fetch_seq = 0

        # reveal
        self._revealed_chars = -1
        self._reveal_total = 0
        self._reveal_step = 1
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(REVEAL_INTERVAL_MS)
        self._reveal_timer.timeout.connect(self._reveal_tick)

        # history
        self._history: list[str] = []
        self._hist_pos = -1

        # persistent settings (read each time so edits land immediately)
        self._open_refresh_timer = QTimer(self)
        self._open_refresh_timer.setSingleShot(True)
        self._open_refresh_timer.timeout.connect(self.refresh)
        self._auto_open_timer = QTimer(self)
        self._auto_open_timer.setInterval(30_000)
        self._auto_open_timer.timeout.connect(self.check_auto_open)
        self._last_auto_open_day = str(self._settings.value("lastAutoOpenDay", "") or "").strip()

        self._fetch_timeout = QTimer(self)
        self._fetch_timeout.setSingleShot(True)
        self._fetch_timeout.timeout.connect(self._on_fetch_timeout)

        self._deck = references.Deck()

        # settings-window mirror state
        self._settings_open = False
        self._settings_notice = ""
        self._settings_notice_error = False

        self._sync_auto_open_timer()
        self.check_auto_open()
        self._update_chips()

    # == settings helpers =================================================

    def _setting(self, key: str, default: str = "") -> str:
        return str(self._settings.value(key, default) or "").strip()

    @Slot()
    def save_settings(self, api_key: str, translation: str, fixed_reference: str, auto_open_at: str) -> None:
        auto_open_at = str(auto_open_at or "").strip()
        if auto_open_at and not AUTO_OPEN_RE.match(auto_open_at):
            self._settings_notice = "Auto-open must be a 24-hour time like 07:30."
            self._settings_notice_error = True
            self.settingsChanged.emit()
            return
        translation = str(translation or "").strip().upper() or "ESV"
        if translation not in ALLOWED_TRANSLATIONS:
            self._settings_notice = "Translation must be ESV, WEB, or KJV."
            self._settings_notice_error = True
            self.settingsChanged.emit()
            return
        old_key = self._api_key_value
        try:
            fixed_reference = _clean_fixed_reference(fixed_reference)
            new_key = str(api_key or "").strip()
            self._secrets.save(new_key)
        except (SecretStoreError, ValueError) as exc:
            self._settings_notice = "Settings: %s" % exc
            self._settings_notice_error = True
            self.settingsChanged.emit()
            return
        old_values = {key: self._settings.value(key) for key in ("translation", "fixedReference", "autoOpenAt")}
        self._settings.setValue("translation", translation)
        self._settings.setValue("fixedReference", fixed_reference)
        self._settings.setValue("autoOpenAt", auto_open_at)
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            for key, value in old_values.items():
                if value is None:
                    self._settings.remove(key)
                else:
                    self._settings.setValue(key, value)
            self._settings.sync()
            try:
                self._secrets.save(old_key)
            except SecretStoreError:
                self._settings_notice = "Settings and API key could not be saved."
                self._settings_notice_error = True
                self.settingsChanged.emit()
                return
            self._settings_notice = "Settings could not be saved."
            self._settings_notice_error = True
            self.settingsChanged.emit()
            return
        self._api_key_value = new_key
        self._settings_notice = "Saved."
        self._settings_notice_error = False
        self.settingsChanged.emit()
        self._sync_auto_open_timer()
        self.liveTip()
        self.check_auto_open()

    def _sync_auto_open_timer(self) -> None:
        if self._setting("autoOpenAt"):
            if not self._auto_open_timer.isActive():
                self._auto_open_timer.start()
        else:
            self._auto_open_timer.stop()

    # == properties (QML-facing) ==========================================

    def _overlay(self) -> bool:
        return self._overlay_open

    def _set_overlay(self, value: bool) -> None:
        value = bool(value)
        if value == self._overlay_open:
            return
        self._overlay_open = value
        self.overlayChanged.emit()
        if value:
            # Skip refresh when load_reference already started a targeted fetch.
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

    @Slot()
    def toggle_settings(self) -> None:
        self.settingsOpen = not self._settings_open

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
        return self._translation_name.upper() if self._translation_id else ""

    translationLabel = Property(str, _translation_label, notify=verseChanged)

    def _reported_translation(self) -> str:
        return self._translation_name or ("English Standard Version" if self._translation_id == "esv" else "World English Bible")

    translationName = Property(str, _reported_translation, notify=verseChanged)

    def _translation_attribution(self) -> str:
        return self._translation_attribution

    translationAttribution = Property(str, _translation_attribution, notify=verseChanged)

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

    def _current_anchor(self) -> str:
        return self._verse_anchor or self._pending_anchor

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

    # favorites ------------------------------------------------------------

    def _favorites(self) -> list:
        return self._favorites

    favorites = Property(list, _favorites, notify=favoritesChanged)

    def _chips(self) -> list:
        return self._favorites[:CHIP_CAP]

    favoritesChips = Property(list, _chips, notify=favoritesChanged)

    def _overflow(self) -> int:
        return max(0, len(self._favorites) - CHIP_CAP)

    favoritesOverflow = Property(int, _overflow, notify=favoritesChanged)

    # settings-window props -------------------------------------------------

    def _settings_api_key(self) -> str:
        return self._api_key_value

    settingsApiKey = Property(str, _settings_api_key, notify=settingsChanged)

    def _settings_translation(self) -> str:
        return (self._setting("translation") or "ESV").upper()

    settingsTranslation = Property(str, _settings_translation, notify=settingsChanged)

    def _settings_fixed(self) -> str:
        return self._setting("fixedReference")

    settingsFixedReference = Property(str, _settings_fixed, notify=settingsChanged)

    def _settings_auto(self) -> str:
        return self._setting("autoOpenAt")

    settingsAutoOpenAt = Property(str, _settings_auto, notify=settingsChanged)

    def _settings_notice(self) -> str:
        return self._settings_notice

    settingsNotice = Property(str, _settings_notice, notify=settingsChanged)

    def _settings_notice_error(self) -> bool:
        return self._settings_notice_error

    settingsNoticeError = Property(bool, _settings_notice_error, notify=settingsChanged)

    # == QML-invokable actions =============================================

    @Slot()
    def close_overlay(self) -> None:
        self.overlayOpen = False

    @Slot()
    def toggle_overlay(self) -> None:
        self.overlayOpen = not self._overlay_open

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
        # Skip the open-triggered refresh so it cannot race this targeted fetch.
        if not self._overlay_open:
            self._skip_next_open_refresh = True
        self.overlayOpen = True
        self._verse_anchor = ref
        self._fetch(ref, record_history=True)

    @Slot()
    def refresh(self) -> None:
        self._open_refresh_timer.stop()
        try:
            fixed = _clean_fixed_reference(self._setting("fixedReference"))
        except ValueError as exc:
            self._error_text = "Reference: %s" % exc
            self.verseChanged.emit()
            return
        if fixed:
            # Fetch the pinned verse without going through load_reference's
            # overlay-open path (overlay may already be open).
            self._verse_anchor = fixed
            self._fetch(fixed, record_history=True)
        else:
            ref = self._deck.draw(self._verse_anchor or self._pending_anchor)
            self._verse_anchor = ref
            self._fetch(ref, record_history=True)

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
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            target = QUrl(url)
            if target.isValid() and target.scheme() == "https" and target.host() in {"www.esv.org", "www.biblegateway.com"}:
                QDesktopServices.openUrl(target)
        except Exception:
            pass

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
        target = self._setting("autoOpenAt")
        if not target:
            return
        import datetime

        now = datetime.datetime.now()
        hhmm = "{0:02d}:{1:02d}".format(now.hour, now.minute)
        day = "{0}-{1}-{2}".format(now.year, now.month, now.day)
        if hhmm == target and day != self._last_auto_open_day:
            self._last_auto_open_day = day
            self._settings.setValue("lastAutoOpenDay", day)
            self._settings.sync()
            if self._overlay_open:
                # Already visible — open path won't refresh; do it ourselves.
                self._open_refresh_timer.start(1)
            else:
                # Let _set_overlay schedule the single open refresh.
                self.overlayOpen = True

    def liveTip(self) -> str:
        return 'Scripture \u2014 {0}'.format(self._verse_reference) if self._verse_reference else "Scripture"

    # == fetch pipeline =====================================================

    def _provider_choice(self) -> str:
        choice = self._setting("translation", "ESV").lower()
        return choice if choice in ("esv", "web", "kjv") else "esv"

    def _api_key(self) -> str:
        return self._api_key_value

    def _fetch(self, anchor: str, record_history: bool) -> None:
        try:
            anchor = _clean_fixed_reference(anchor)
        except ValueError as exc:
            self._error_text = "Reference: %s" % exc
            self.verseChanged.emit()
            return
        if not anchor:
            return
        self._loading = True
        self.loadingChanged.emit()
        self._error_text = ""
        self._fetch_notice = ""
        self._pending_anchor = anchor
        self._pending_reference = references.range_query(anchor)
        self._pending_focal = references.focal_verse(anchor)
        self._web_retried = False
        self._esv_retried = False
        self._verse_reference = ""
        if record_history:
            self._record_history(anchor)
        self._fetch_timeout.start(FETCH_TIMEOUT_MS)
        self.verseChanged.emit()
        self.displayTextChanged.emit()

        choice = self._provider_choice()
        key = self._api_key()
        self._fetch_seq += 1
        tag = self._fetch_seq

        if choice == "esv" and key:
            self._translation_id = ""
            self._translation_name = ""
            self._fetcher.fetch_esv(tag, self._pending_reference, key)
            self.verseChanged.emit()
            self.displayTextChanged.emit()
        elif choice == "esv":
            self._fetch_notice = (
                "Set an ESV API key in Settings to read the ESV \u2014 showing the World English Bible."
            )
            self._current_web_translation = "web"
            self._fetcher.fetch_web(tag, self._pending_reference, "web")
            self.verseChanged.emit()
            self.displayTextChanged.emit()
        else:
            tr = "kjv" if choice == "kjv" else "web"
            self._current_web_translation = tr
            self._fetcher.fetch_web(tag, self._pending_reference, tr)
            self.verseChanged.emit()
            self.displayTextChanged.emit()

    def _on_fetch_timeout(self) -> None:
        if not self._loading:
            return
        self._fetch_seq += 1
        self._fetcher.abort()
        self._loading = False
        self.loadingChanged.emit()
        self._error_text = "The verse fetch timed out. Try again."
        self.verseChanged.emit()
        self.displayTextChanged.emit()

    # -- ESV ----------------------------------------------------------------

    def _on_esv_result(self, tag: int, body: str, error: str, status: int) -> None:
        if tag != self._fetch_seq or not self._loading:
            return
        self._fetch_timeout.stop()
        try:
            payload = parse_json(body) if body else None
        except (TypeError, ValueError):
            payload = None

        ok = not error and valid_esv_payload(payload)
        if not ok and should_retry_range(
            "esv", self._pending_reference, self._pending_anchor, body, error, status, self._esv_retried
        ):
            self._esv_retried = True
            tag = self._fetch_seq + 1
            self._fetch_seq = tag
            self._fetch_timeout.start(FETCH_TIMEOUT_MS)
            self._fetcher.fetch_esv(tag, self._pending_anchor, self._api_key())
            return

        if not ok:
            self._loading = False
            self.loadingChanged.emit()
            self._error_text = "Could not load from the ESV API. Check your key and connection."
            self.verseChanged.emit()
            self.displayTextChanged.emit()
            return

        reference = references.normalize_reference(payload.get("canonical")) or self._pending_reference
        before, focal, after = references.parse_numbered_passage(payload["passages"][0], self._pending_focal)
        attribution = esv_attribution(payload)
        self._apply_verse(before, focal, after, reference, "esv", "English Standard Version", attribution)

    # -- WEB / KJV ----------------------------------------------------------

    def _on_web_result(self, tag: int, body: str, error: str, status: int) -> None:
        if tag != self._fetch_seq or not self._loading:
            return
        self._fetch_timeout.stop()
        try:
            payload = parse_json(body) if body else None
        except (TypeError, ValueError):
            payload = None

        ok = not error and valid_web_payload(payload)
        if not ok and should_retry_range(
            "web", self._pending_reference, self._pending_anchor, body, error, status, self._web_retried
        ):
            self._web_retried = True
            tag = self._fetch_seq + 1
            self._fetch_seq = tag
            self._fetch_timeout.start(FETCH_TIMEOUT_MS)
            self._fetcher.fetch_web(tag, self._pending_anchor, self._current_web_translation)
            return

        if not ok:
            self._loading = False
            self.loadingChanged.emit()
            self._error_text = "Could not load that passage. Try again."
            self.verseChanged.emit()
            self.displayTextChanged.emit()
            return

        version_id = self._current_web_translation
        version_name = (
            references.translation_text(payload)
            or ("King James Version" if version_id == "kjv" else "World English Bible")
        )
        before, focal, after = references.parse_web_passage(payload, self._pending_focal)
        reference = references.reference_text(payload) or self._pending_reference
        attribution = str(payload.get("attribution") or payload.get("copyright") or "").strip()
        self._apply_verse(before, focal, after, reference, version_id, version_name, attribution)

    def _apply_verse(self, before: str, focal: str, after: str, reference: str, translation_id: str, translation_name: str, attribution: str = "") -> None:
        self._context_before = before
        self._verse_text = focal
        self._context_after = after
        self._verse_reference = references.normalize_reference(reference) or self._pending_reference
        self._translation_id = translation_id
        self._translation_name = translation_name
        self._translation_attribution = str(attribution or "")
        self._esv_retried = False
        self._loading = False
        self.loadingChanged.emit()
        self.verseChanged.emit()
        self.displayTextChanged.emit()
        self._start_reveal()

    # == history / reveal ===================================================

    def _record_history(self, anchor: str) -> None:
        if self._history and self._history[-1] == anchor:
            return
        self._history = (self._history + [anchor])[-HISTORY_CAP:]
        self._hist_pos = len(self._history) - 1

    def _start_reveal(self) -> None:
        total = len(self._context_before) + len(self._verse_text) + len(self._context_after)
        self._reveal_total = total if total > 0 else 0
        self._reveal_step = max(1, math.ceil(total * REVEAL_INTERVAL_MS / REVEAL_DURATION_MS))
        self._revealed_chars = 0
        if total <= 0:
            return
        self.displayTextChanged.emit()
        self._reveal_timer.start()

    def _reveal_tick(self) -> None:
        self._revealed_chars = min(self._reveal_total, self._revealed_chars + self._reveal_step)
        if self._revealed_chars >= self._reveal_total:
            self._revealed_chars = self._reveal_total
            self._reveal_timer.stop()
        # Only notify display text — avoid re-evaluating histCanBack/isFavorite/etc at 60Hz.
        self.displayTextChanged.emit()

    # == misc ===============================================================

    def _update_chips(self) -> None:
        self.favoritesChanged.emit()


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
    return str(payload.get("copyright") or "").strip() or str(payload.get("attribution") or "").strip() or ESV_ATTRIBUTION


def valid_esv_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    passages = payload.get("passages")
    if not isinstance(passages, list) or not passages or len(passages) > 32 or any(not isinstance(item, str) or not item.strip() for item in passages):
        return False
    for key in ("canonical", "copyright", "attribution"):
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
    for key in ("reference", "attribution", "copyright", "translation_name"):
        if key in payload and not isinstance(payload[key], str):
            return False
    translation = payload.get("translation")
    if translation is not None:
        if not isinstance(translation, dict):
            return False
        if "name" in translation and not isinstance(translation["name"], str):
            return False
    return True
