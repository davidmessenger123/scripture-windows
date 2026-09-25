import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

enum ClipboardPolicy {
    static let expirationSeconds: TimeInterval = 300
    static let localOnly = true
}

struct CardGenerationSnapshot: Equatable, Sendable {
    let token: UUID
    let passage: Passage
    let settings: AppSettings
}

enum ReminderEffectiveState: Equatable {
    case pending
    case disabled
    case scheduled
    case blocked(String)
    case failed(String)
}

@MainActor
final class ScriptureViewModel: ObservableObject {
    @Published private(set) var passage: Passage?
    @Published private(set) var isLoading = false
    @Published private(set) var favorites: [String]
    @Published private(set) var history: [String] = []
    @Published private(set) var historyIndex: Int?
    @Published private(set) var revealedCharacters = 0
    @Published private(set) var settings: AppSettings
    @Published private(set) var notice: String?
    @Published private(set) var errorMessage: String?
    @Published private(set) var settingsNotice: String?
    @Published private(set) var settingsNoticeIsError = false
    @Published private(set) var hasLoadedInitialVerse = false
    @Published private(set) var isRenderingCard = false
    @Published private(set) var cardShareItem: VerseCardTransfer?
    @Published private(set) var reminderState: ReminderEffectiveState = .pending

    @Published var isShowingSettings = false
    @Published var isShowingJump = false
    @Published var jumpText = ""

    private let api: ScriptureAPI
    private let settingsStore: SettingsStore
    private let favoritesStore: FavoritesStore
    private let passageCache: PassageCache
    private let notificationScheduler: NotificationScheduler
    private var deck: ScriptureDeck
    private var deckPoolContext = ""
    private var pendingAnchor = ""
    private var activeRequestID = UUID()
    private var revealTask: Task<Void, Never>?
    private var cardTask: Task<Void, Never>?
    private var cardGenerationToken = UUID()

    init(
        api: ScriptureAPI = ScriptureAPI(),
        settingsStore: SettingsStore = SettingsStore(),
        favoritesStore: FavoritesStore = FavoritesStore(),
        passageCache: PassageCache = PassageCache(),
        notificationScheduler: NotificationScheduler = NotificationScheduler()
    ) {
        self.api = api
        self.settingsStore = settingsStore
        self.favoritesStore = favoritesStore
        self.passageCache = passageCache
        self.notificationScheduler = notificationScheduler
        let loadedSettings = settingsStore.load()
        self.settings = loadedSettings
        self.reminderState = loadedSettings.autoOpenTime.isEmpty ? .disabled : .pending
        self.favorites = favoritesStore.list()
        let pool = Self.filteredPool(for: loadedSettings)
        self.deck = ScriptureDeck(pool: pool)
        self.deckPoolContext = Self.poolContext(pool)
        if let error = settingsStore.lastLoadError {
            self.settingsNotice = error
            self.settingsNoticeIsError = true
        } else if let notice = settingsStore.lastLoadNotice {
            self.settingsNotice = notice
            self.settingsNoticeIsError = false
        }
    }

    var currentAnchor: String {
        ScriptureReference.cleanProviderText(passage?.anchor ?? pendingAnchor)
    }

    var isFavorite: Bool {
        !currentAnchor.isEmpty && favorites.contains(currentAnchor)
    }

    var favoriteSymbol: String {
        isFavorite ? "★" : "☆"
    }

    var canGoBack: Bool {
        guard let historyIndex else { return false }
        return historyIndex > 0 && !isLoading
    }

    var canGoForward: Bool {
        guard let historyIndex else { return false }
        return historyIndex + 1 < history.count && !isLoading
    }

    var favoriteChips: [String] {
        Array(favorites.prefix(8))
    }

    var favoriteOverflow: Int {
        max(0, favorites.count - 8)
    }

    var bookFilterTitle: String {
        settings.bookFilter.isEmpty ? "All books" : settings.bookFilter
    }

    var topicFilterTitle: String {
        settings.topicFilter.displayName
    }

    var hasActiveFilters: Bool {
        !settings.bookFilter.isEmpty || settings.topicFilter != .all
    }

    var reminderDesiredTime: String {
        settings.autoOpenTime
    }

    var reminderIsScheduled: Bool {
        if case .scheduled = reminderState { return true }
        return false
    }

    var reminderStatusMessage: String? {
        switch reminderState {
        case .pending:
            return reminderDesiredTime.isEmpty ? nil : "Reminder desired; checking authorization and scheduling."
        case .disabled:
            return reminderDesiredTime.isEmpty ? nil : "Reminder desired but not scheduled."
        case .scheduled:
            return nil
        case let .blocked(message):
            return "Reminder blocked: \(message)"
        case let .failed(message):
            return "Reminder failed: \(message)"
        }
    }

    var reminderStatusIsError: Bool {
        switch reminderState {
        case .pending, .blocked, .failed:
            return !reminderDesiredTime.isEmpty
        case .disabled, .scheduled:
            return false
        }
    }

    var revealAnimation: Animation? {
        guard settings.revealSpeed > 0 else { return nil }
        return .easeOut(duration: min(0.3, max(0.04, 0.16 / settings.revealSpeed)))
    }

    var availableBooks: [String] {
        ScriptureReference.books
    }

    var availableTopics: [ScriptureTopic] {
        ScriptureTopic.allCases
    }

    var visibleBefore: String {
        guard let passage else { return "" }
        let text = passage.displayBefore
        return String(text.prefix(min(revealedCharacters, text.count)))
    }

    var visibleFocal: String {
        guard let passage else { return "" }
        let before = passage.displayBefore
        let focal = passage.displayFocal
        let beforeCount = min(revealedCharacters, before.count)
        let focalCount = min(focal.count, max(0, revealedCharacters - beforeCount))
        return String(focal.prefix(focalCount))
    }

    var visibleAfter: String {
        guard let passage else { return "" }
        let before = passage.displayBefore
        let focal = passage.displayFocal
        let after = passage.displayAfter
        let beforeCount = min(revealedCharacters, before.count)
        let focalCount = min(focal.count, max(0, revealedCharacters - beforeCount))
        let afterCount = min(after.count, max(0, revealedCharacters - beforeCount - focalCount))
        return String(after.prefix(afterCount))
    }

    var browserURL: URL? {
        guard let passage else { return nil }
        return ScriptureReference.browserURL(for: passage.displayReference, translation: passage.translation)
    }

    func loadInitialIfNeeded() async {
        guard !hasLoadedInitialVerse else { return }
        hasLoadedInitialVerse = true
        await refresh()
        await reconcileReminderIfPossible()
    }

    func refresh() async {
        let fixed = settings.fixedReference.trimmingCharacters(in: .whitespacesAndNewlines)
        if !fixed.isEmpty {
            await loadReference(fixed)
        } else {
            await loadReference(drawRandomReference())
        }
    }

    func loadReference(_ rawReference: String, recordHistory: Bool = true) async {
        let reference = ScriptureReference.cleanProviderText(rawReference)
        guard !reference.isEmpty, AppSettings.isValidFixedReference(reference) else { return }

        invalidateCardGeneration()
        pendingAnchor = reference
        if recordHistory {
            record(reference)
        }

        let requestID = UUID()
        activeRequestID = requestID
        isLoading = true
        notice = nil
        errorMessage = nil
        let requestedTranslation = settings.translation
        let key = settings.apiKey
        let esvKeyIdentity = ScriptureAPI.esvKeyIdentity(for: key)

        do {
            let result = try await api.fetch(
                anchor: reference,
                translation: requestedTranslation,
                apiKey: key
            )
            guard activeRequestID == requestID else { return }
            _ = await passageCache.store(result, esvKeyIdentity: esvKeyIdentity)
            guard activeRequestID == requestID else { return }
            if requestedTranslation == .esv, esvKeyIdentity == nil {
                notice = "Set an ESV API key in Settings to read the ESV — showing WEB."
            }
            apply(result)
        } catch is CancellationError {
            guard activeRequestID == requestID else { return }
            isLoading = false
        } catch {
            guard activeRequestID == requestID else { return }
            if let cached = await passageCache.passage(
                for: reference,
                translations: cacheTranslations(for: requestedTranslation, apiKey: key),
                esvKeyIdentity: esvKeyIdentity
            ) {
                guard activeRequestID == requestID else { return }
                apply(cached)
                notice = "Offline: showing the last saved passage."
                errorMessage = nil
            } else {
                isLoading = false
                if passage == nil {
                    hasLoadedInitialVerse = false
                }
                errorMessage = "Could not load that passage. No saved offline passage is available; check your connection and try again."
            }
        }
    }

    func goBack() async {
        guard canGoBack, let index = historyIndex, history.indices.contains(index - 1) else { return }
        historyIndex = index - 1
        await loadReference(history[index - 1], recordHistory: false)
    }

    func goForward() async {
        guard canGoForward, let index = historyIndex, history.indices.contains(index + 1) else { return }
        historyIndex = index + 1
        await loadReference(history[index + 1], recordHistory: false)
    }

    func submitJump() async {
        let reference = ScriptureReference.cleanProviderText(jumpText)
        jumpText = ""
        isShowingJump = false
        await loadReference(reference)
    }

    func toggleFavorite() {
        let reference = currentAnchor.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !reference.isEmpty else { return }
        favorites = favorites.contains(reference)
            ? favoritesStore.remove(reference)
            : favoritesStore.add(reference)
    }

    func removeFavorite(_ reference: String) {
        favorites = favoritesStore.remove(reference)
    }

    @discardableResult
    func deleteAllFavorites() -> Bool {
        guard favoritesStore.removeAll() else {
            notice = nil
            errorMessage = "Favorites could not be deleted."
            return false
        }
        favorites = []
        notice = "All favorites deleted."
        errorMessage = nil
        return true
    }

    func loadFavorite(_ reference: String) async {
        await loadReference(reference)
    }

    func setBookFilter(_ value: String) {
        let requested = value.trimmingCharacters(in: .whitespacesAndNewlines)
        let canonical = requested.isEmpty ? "" : AppSettings.canonicalBook(requested)
        guard requested.isEmpty || canonical != nil else {
            showFilterResetExplanation("That book is not available.")
            return
        }
        var draft = settings
        draft.bookFilter = canonical ?? ""
        if !AppSettings.hasFilterIntersection(book: draft.bookFilter, topic: draft.topicFilter) {
            showFilterResetExplanation("That book and topic have no verses in the deck.")
            return
        }
        do {
            try settingsStore.save(draft)
        } catch {
            showSettingsPersistenceError(error)
            return
        }
        settings = draft.normalized
        invalidateCardGeneration()
        resetDeck(for: settings)
        clearFilterNotice()
    }

    func setTopicFilter(_ topic: ScriptureTopic) {
        var draft = settings
        draft.topicFilter = topic
        if !AppSettings.hasFilterIntersection(book: draft.bookFilter, topic: topic) {
            showFilterResetExplanation("That book and topic have no verses in the deck.")
            return
        }
        do {
            try settingsStore.save(draft)
        } catch {
            showSettingsPersistenceError(error)
            return
        }
        settings = draft.normalized
        invalidateCardGeneration()
        resetDeck(for: settings)
        clearFilterNotice()
    }

    func copyPassage() {
        guard let passage else { return }
        UIPasteboard.general.setItems(
            [[UTType.utf8PlainText.identifier: passage.plainFormattedText]],
            options: [
                .localOnly: ClipboardPolicy.localOnly,
                .expirationDate: Date(timeIntervalSinceNow: ClipboardPolicy.expirationSeconds)
            ]
        )
        notice = "Passage copied locally for 5 minutes."
        errorMessage = nil
    }

    func generateCard() {
        guard let passage else { return }
        cardTask?.cancel()
        let snapshot = CardGenerationSnapshot(
            token: UUID(),
            passage: passage,
            settings: settings
        )
        cardGenerationToken = snapshot.token
        cardShareItem = nil
        isRenderingCard = true
        let task = Task { [weak self] in
            guard let self else { return }
            defer { self.finishCardTask(token: snapshot.token) }
            do {
                try Task.checkCancellation()
                guard let image = PassageCardRenderer.renderImage(
                    passage: snapshot.passage,
                    fontSize: snapshot.settings.verseFontSize
                ) else {
                    guard self.isCurrentCardSnapshot(snapshot) else { return }
                    self.errorMessage = "The verse card could not be generated."
                    return
                }
                let data = try await Task.detached(priority: .userInitiated) {
                    try Task.checkCancellation()
                    let encoded = image.image.pngData()
                    try Task.checkCancellation()
                    return encoded
                }.value
                try Task.checkCancellation()
                guard self.isCurrentCardSnapshot(snapshot) else { return }
                guard let data else {
                    self.errorMessage = "The verse card could not be encoded."
                    return
                }
                let url = try VerseCardTransfer.write(
                    data: data,
                    reference: snapshot.passage.displayReference
                )
                try Task.checkCancellation()
                guard self.isCurrentCardSnapshot(snapshot) else {
                    try? FileManager.default.removeItem(at: url)
                    return
                }
                self.cardShareItem = VerseCardTransfer(url: url)
                self.notice = "Verse card ready to share."
                self.errorMessage = nil
            } catch is CancellationError {
                return
            } catch {
                guard self.isCurrentCardSnapshot(snapshot) else { return }
                self.errorMessage = "The verse card file could not be prepared."
            }
        }
        cardTask = task
    }

    func saveSettings(_ draft: AppSettings) async {
        if let message = SettingsStore.validationMessage(for: draft) {
            settingsNotice = message
            settingsNoticeIsError = true
            return
        }

        let normalized = draft.normalized
        let oldSettings = settings
        do {
            try settingsStore.save(normalized)
        } catch {
            settingsNotice = "Settings could not be saved: \(error.localizedDescription)"
            settingsNoticeIsError = true
            return
        }

        settings = normalized
        if oldSettings != normalized {
            invalidateCardGeneration()
        }
        resetDeck(for: settings)
        if oldSettings.revealSpeed != normalized.revealSpeed {
            startReveal()
        }
        settingsNotice = "Saved."
        settingsNoticeIsError = false
        reminderState = normalized.autoOpenTime.isEmpty ? .disabled : .pending

        guard let (hour, minute) = Self.timeComponents(normalized.autoOpenTime) else {
            await notificationScheduler.cancelDaily()
            reminderState = .disabled
            return
        }
        _ = await notificationScheduler.requestAuthorization()
        let result = await notificationScheduler.reconcileDaily(
            hour: hour,
            minute: minute,
            passage: passage
        )
        applyReminderResult(result, desiredTime: normalized.autoOpenTime)
        switch result {
        case .scheduled, .unchanged:
            settingsNotice = "Saved. Daily reminder scheduled for \(normalized.autoOpenTime)."
            settingsNoticeIsError = false
        case .unauthorized:
            settingsNotice = "Reminder desired, but notifications are not authorized. The saved time remains editable."
            settingsNoticeIsError = true
        case let .failed(message):
            settingsNotice = "Reminder desired, but scheduling failed: \(message)"
            settingsNoticeIsError = true
        case .disabled:
            settingsNotice = "Reminder turned off."
            settingsNoticeIsError = false
        }
    }

    func clearSettingsNotice() {
        settingsNotice = nil
        settingsNoticeIsError = false
    }

    @discardableResult
    func deletePassageCache() async -> Bool {
        let removed = await passageCache.removeAll()
        if removed {
            notice = "Passage cache deleted."
            errorMessage = nil
            return true
        }
        let message = "The passage cache could not be deleted."
        notice = message
        errorMessage = message
        return false
    }

    @discardableResult
    func deleteAPIKey() async -> Bool {
        var draft = settings
        draft.apiKey = ""
        do {
            try settingsStore.save(draft)
            settings = draft.normalized
            invalidateCardGeneration()
            let cacheRemoved = await passageCache.removeAll()
            guard cacheRemoved else {
                settingsNotice = "The ESV API key was deleted, but the passage cache could not be deleted."
                settingsNoticeIsError = true
                return false
            }
            notice = "ESV API key and passage cache deleted."
            errorMessage = nil
            return true
        } catch {
            settingsNotice = "The ESV API key could not be deleted: \(error.localizedDescription)"
            settingsNoticeIsError = true
            return false
        }
    }

    func handleScenePhase(_ phase: ScenePhase) {
        guard phase == .active else { return }
        Task { [weak self] in
            guard let self else { return }
            await self.loadInitialIfNeeded()
            await self.reconcileReminderIfPossible()
        }
    }

    private func drawRandomReference() -> String {
        let pool = Self.filteredPool(for: settings)
        guard !pool.isEmpty else {
            var reset = settings
            reset.bookFilter = ""
            reset.topicFilter = .all
            do {
                try settingsStore.save(reset)
                settings = reset.normalized
                invalidateCardGeneration()
                resetDeck(for: settings)
                showFilterResetExplanation("The selected filters had no verses, so they were reset.")
            } catch {
                showSettingsPersistenceError(error)
            }
            return deck.draw()
        }
        let context = Self.poolContext(pool)
        if deckPoolContext != context {
            deck = ScriptureDeck(pool: pool)
            deckPoolContext = context
        }
        return deck.draw(avoiding: passage?.anchor)
    }

    private func resetDeck(for settings: AppSettings) {
        let pool = Self.filteredPool(for: settings)
        let context = Self.poolContext(pool)
        guard deckPoolContext != context else { return }
        deck = ScriptureDeck(pool: pool)
        deckPoolContext = context
    }

    private static func filteredPool(for settings: AppSettings) -> [String] {
        ScriptureReference.references(
            book: settings.bookFilter,
            topic: settings.topicFilter
        )
    }

    private static func poolContext(_ pool: [String]) -> String {
        pool.joined(separator: "\u{1f}")
    }

    private func cacheTranslations(for translation: Translation, apiKey: String) -> [Translation] {
        if translation == .esv, ScriptureAPI.esvKeyIdentity(for: apiKey) == nil {
            return [.web]
        }
        return [translation]
    }

    private func record(_ reference: String) {
        if history.last == reference {
            historyIndex = history.isEmpty ? nil : history.count - 1
            return
        }
        history.append(reference)
        if history.count > 200 {
            history.removeFirst(history.count - 200)
        }
        historyIndex = history.count - 1
    }

    private func apply(_ newPassage: Passage) {
        passage = newPassage
        pendingAnchor = newPassage.anchor
        isLoading = false
        errorMessage = nil
        invalidateCardGeneration()
        revealedCharacters = 0
        startReveal()
        Task { [weak self] in
            await self?.reconcileReminderIfPossible()
        }
    }

    private func isCurrentCardSnapshot(_ snapshot: CardGenerationSnapshot) -> Bool {
        Self.cardSnapshotMatches(
            snapshot,
            token: cardGenerationToken,
            passage: passage,
            settings: settings
        )
    }

    nonisolated static func cardSnapshotMatches(
        _ snapshot: CardGenerationSnapshot,
        token: UUID,
        passage: Passage?,
        settings: AppSettings
    ) -> Bool {
        guard token == snapshot.token,
              let currentPassage = passage,
              currentPassage == snapshot.passage else {
            return false
        }
        return settings == snapshot.settings
    }

    private func finishCardTask(token: UUID) {
        guard cardGenerationToken == token else { return }
        cardTask = nil
        isRenderingCard = false
    }

    private func invalidateCardGeneration() {
        cardGenerationToken = UUID()
        cardTask?.cancel()
        cardTask = nil
        isRenderingCard = false
        cardShareItem = nil
    }

    private func startReveal() {
        revealTask?.cancel()
        guard let total = passage?.visibleTextCount, total > 0 else {
            revealTask = nil
            return
        }
        let speed = settings.revealSpeed
        guard RevealTiming.duration(for: speed) != nil else {
            revealedCharacters = total
            revealTask = nil
            return
        }
        let step = RevealTiming.step(total: total, speed: speed)
        revealTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: RevealTiming.intervalNanoseconds)
                } catch {
                    return
                }
                guard !Task.isCancelled, let self = self else { return }
                let current = self.revealedCharacters
                if current >= total {
                    self.revealTask = nil
                    return
                }
                self.revealedCharacters = min(total, current + step)
                if self.revealedCharacters >= total {
                    self.revealTask = nil
                    return
                }
            }
        }
    }

    private func reconcileReminderIfPossible() async {
        let desiredTime = settings.autoOpenTime
        let time = Self.timeComponents(desiredTime)
        let result = await notificationScheduler.reconcileDaily(
            hour: time?.hour,
            minute: time?.minute,
            passage: passage
        )
        applyReminderResult(result, desiredTime: desiredTime)
    }

    private func applyReminderResult(
        _ result: NotificationReconcileResult,
        desiredTime: String
    ) {
        reminderState = Self.effectiveReminderState(
            for: result,
            desiredTime: desiredTime
        )
    }

    private func showFilterResetExplanation(_ message: String) {
        notice = message
        errorMessage = nil
    }

    private func clearFilterNotice() {
        notice = nil
        errorMessage = nil
    }

    private func showSettingsPersistenceError(_ error: Error) {
        settingsNotice = "Settings could not be saved: \(error.localizedDescription)"
        settingsNoticeIsError = true
    }

    nonisolated static func effectiveReminderState(
        for result: NotificationReconcileResult,
        desiredTime: String
    ) -> ReminderEffectiveState {
        switch result {
        case .disabled:
            return desiredTime.isEmpty
                ? .disabled
                : .failed("The desired reminder time is not valid.")
        case .unchanged, .scheduled:
            return .scheduled
        case .unauthorized:
            return .blocked("Notifications are not authorized.")
        case let .failed(message):
            return .failed(message)
        }
    }

    nonisolated static func timeComponents(_ value: String) -> (hour: Int, minute: Int)? {
        let parts = value.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2,
              parts[0].count == 2,
              parts[1].count == 2,
              let hour = Int(parts[0]),
              let minute = Int(parts[1]),
              (0...23).contains(hour),
              (0...59).contains(minute) else {
            return nil
        }
        return (hour, minute)
    }
}
