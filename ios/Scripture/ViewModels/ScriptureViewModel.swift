import Foundation
import SwiftUI

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

    @Published var isShowingSettings = false
    @Published var isShowingJump = false
    @Published var jumpText = ""

    private let api: ScriptureAPI
    private let settingsStore: SettingsStore
    private let favoritesStore: FavoritesStore
    private let notificationScheduler: NotificationScheduler
    private let deck: ScriptureDeck
    private var pendingAnchor = ""
    private var activeRequestID = UUID()
    private var revealTask: Task<Void, Never>?

    init(
        api: ScriptureAPI = ScriptureAPI(),
        settingsStore: SettingsStore = SettingsStore(),
        favoritesStore: FavoritesStore = FavoritesStore(),
        notificationScheduler: NotificationScheduler = NotificationScheduler()
    ) {
        self.api = api
        self.settingsStore = settingsStore
        self.favoritesStore = favoritesStore
        self.notificationScheduler = notificationScheduler
        self.deck = ScriptureDeck()
        self.settings = settingsStore.load()
        self.favorites = favoritesStore.list()
    }

    var currentAnchor: String {
        passage?.anchor ?? pendingAnchor
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

    var visibleBefore: String {
        guard let passage else { return "" }
        return String(passage.before.prefix(min(revealedCharacters, passage.before.count)))
    }

    var visibleFocal: String {
        guard let passage else { return "" }
        let beforeCount = min(revealedCharacters, passage.before.count)
        let focalCount = min(passage.focal.count, max(0, revealedCharacters - beforeCount))
        return String(passage.focal.prefix(focalCount))
    }

    var visibleAfter: String {
        guard let passage else { return "" }
        let beforeCount = min(revealedCharacters, passage.before.count)
        let focalCount = min(passage.focal.count, max(0, revealedCharacters - beforeCount))
        let afterCount = min(passage.after.count, max(0, revealedCharacters - beforeCount - focalCount))
        return String(passage.after.prefix(afterCount))
    }

    var browserURL: URL? {
        guard let passage else { return nil }
        return ScriptureReference.browserURL(for: passage.reference, translation: passage.translation)
    }

    func loadInitialIfNeeded() async {
        guard !hasLoadedInitialVerse else { return }
        hasLoadedInitialVerse = true
        await refresh()
    }

    func refresh() async {
        let fixed = settings.fixedReference.trimmingCharacters(in: .whitespacesAndNewlines)
        if !fixed.isEmpty {
            await loadReference(fixed)
        } else {
            let reference = deck.draw(avoiding: passage?.anchor)
            await loadReference(reference)
        }
    }

    func loadReference(_ rawReference: String, recordHistory: Bool = true) async {
        let reference = rawReference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !reference.isEmpty else { return }

        pendingAnchor = reference
        if recordHistory {
            record(reference)
        }

        let requestID = UUID()
        activeRequestID = requestID
        isLoading = true
        notice = nil
        errorMessage = nil

        do {
            let requestedTranslation = settings.translation
            let key = settings.apiKey
            let result = try await api.fetch(
                anchor: reference,
                translation: requestedTranslation,
                apiKey: key
            )
            guard activeRequestID == requestID else { return }
            if requestedTranslation == .esv, key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                notice = "Set an ESV API key in Settings to read the ESV — showing the World English Bible."
            }
            apply(result)
        } catch is CancellationError {
            guard activeRequestID == requestID else { return }
            isLoading = false
        } catch {
            guard activeRequestID == requestID else { return }
            isLoading = false
            if passage == nil {
                hasLoadedInitialVerse = false
            }
            errorMessage = "Could not load that passage. Check your connection and try again."
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
        let reference = jumpText.trimmingCharacters(in: .whitespacesAndNewlines)
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

    func loadFavorite(_ reference: String) async {
        await loadReference(reference)
    }

    func saveSettings(_ draft: AppSettings) async {
        let normalized = AppSettings(
            apiKey: draft.apiKey.trimmingCharacters(in: .whitespacesAndNewlines),
            translation: draft.translation,
            fixedReference: draft.fixedReference.trimmingCharacters(in: .whitespacesAndNewlines),
            autoOpenTime: draft.autoOpenTime.trimmingCharacters(in: .whitespacesAndNewlines)
        )

        if !normalized.autoOpenTime.isEmpty, Self.timeComponents(normalized.autoOpenTime) == nil {
            settingsNotice = "Auto-open must be a 24-hour time like 07:30."
            settingsNoticeIsError = true
            return
        }

        settings = normalized
        settingsStore.save(normalized)
        settingsNotice = "Saved."
        settingsNoticeIsError = false

        guard !normalized.autoOpenTime.isEmpty else {
            notificationScheduler.cancelDaily()
            return
        }
        guard let (hour, minute) = Self.timeComponents(normalized.autoOpenTime) else { return }
        let authorized = await notificationScheduler.requestAuthorization()
        guard authorized else {
            settingsNotice = "Saved, but notifications are disabled for Scripture."
            settingsNoticeIsError = true
            return
        }
        do {
            try await notificationScheduler.scheduleDaily(hour: hour, minute: minute)
            settingsNotice = "Saved. Daily reminder scheduled for \(normalized.autoOpenTime)."
            settingsNoticeIsError = false
        } catch {
            settingsNotice = "Saved, but the daily reminder could not be scheduled."
            settingsNoticeIsError = true
        }
    }

    func clearSettingsNotice() {
        settingsNotice = nil
        settingsNoticeIsError = false
    }

    func handleScenePhase(_ phase: ScenePhase) {
        guard phase == .active, passage == nil else { return }
        Task { [weak self] in
            await self?.loadInitialIfNeeded()
        }
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
        revealedCharacters = 0
        startReveal()
    }

    private func startReveal() {
        revealTask?.cancel()
        guard let total = passage?.visibleTextCount, total > 0 else { return }
        let step = max(1, Int(ceil(Double(total) * 16.0 / 2_200.0)))
        revealTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 16_000_000)
                guard !Task.isCancelled, let self else { return }
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

    nonisolated static func timeComponents(_ value: String) -> (hour: Int, minute: Int)? {
        let parts = value.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2,
              let hour = Int(parts[0]),
              let minute = Int(parts[1]),
              (0...23).contains(hour),
              (0...59).contains(minute),
              parts[0].count == 2,
              parts[1].count == 2 else {
            return nil
        }
        return (hour, minute)
    }
}
