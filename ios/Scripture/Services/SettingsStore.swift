import Foundation
import Security

struct AppSettings: Equatable, Sendable {
    var apiKey = ""
    var translation: Translation = .esv
    var fixedReference = ""
    var autoOpenTime = ""
    var bookFilter = ""
    var topicFilter: ScriptureTopic = .all
    var verseFontSize: Double = 28
    var scrimOpacity: Double = 0.12
    var revealSpeed: Double = 0.5

    static let empty = AppSettings()

    var normalized: AppSettings {
        var value = self
        let key = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        value.apiKey = key.count <= 4096
            && key.unicodeScalars.allSatisfy { $0.value >= 32 && $0.value != 127 }
            ? key
            : ""
        let fixed = fixedReference.trimmingCharacters(in: .whitespacesAndNewlines)
        value.fixedReference = isValidFixedReference(fixed) ? fixed : ""
        let time = autoOpenTime.trimmingCharacters(in: .whitespacesAndNewlines)
        value.autoOpenTime = isValidTime(time) ? time : ""

        let requestedBook = bookFilter.trimmingCharacters(in: .whitespacesAndNewlines)
        let canonicalBook = canonicalBook(requestedBook)
        if !requestedBook.isEmpty, canonicalBook == nil {
            value.bookFilter = ""
            value.topicFilter = .all
        } else if let canonicalBook,
                  topicFilter != .all,
                  ScriptureReference.references(book: canonicalBook, topic: topicFilter).isEmpty {
            value.bookFilter = ""
            value.topicFilter = .all
        } else {
            value.bookFilter = canonicalBook ?? ""
        }

        value.verseFontSize = finiteValue(verseFontSize, fallback: AppSettings().verseFontSize)
        value.scrimOpacity = finiteValue(scrimOpacity, fallback: AppSettings().scrimOpacity)
        value.revealSpeed = finiteValue(revealSpeed, fallback: AppSettings().revealSpeed)
        value.verseFontSize = Self.clamp(value.verseFontSize, lower: 16, upper: 44)
        value.scrimOpacity = Self.clamp(value.scrimOpacity, lower: 0, upper: 0.95)
        value.revealSpeed = Self.clamp(value.revealSpeed, lower: 0, upper: 1)
        return value
    }

    static func clamp(_ value: Double, lower: Double, upper: Double) -> Double {
        min(max(value, lower), upper)
    }

    static func isValidTime(_ value: String) -> Bool {
        let parts = value.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2,
              parts[0].count == 2,
              parts[1].count == 2,
              let hour = Int(parts[0]),
              let minute = Int(parts[1]) else {
            return false
        }
        return (0...23).contains(hour) && (0...59).contains(minute)
    }

    static func isValidFixedReference(_ value: String) -> Bool {
        guard !value.isEmpty, value.count <= 240 else { return value.isEmpty }
        guard value.unicodeScalars.allSatisfy({
            $0.value >= 32 && $0.value != 127 && !CharacterSet.newlines.contains($0)
        }), ScriptureReference.book(for: value) != nil,
              let verse = ScriptureReference.focalVerse(value), verse > 0 else {
            return false
        }
        return true
    }

    static func canonicalBook(_ value: String) -> String? {
        ScriptureReference.books.first {
            $0.caseInsensitiveCompare(value) == .orderedSame
        }
    }

    static func hasFilterIntersection(book: String, topic: ScriptureTopic) -> Bool {
        !ScriptureReference.references(book: book, topic: topic).isEmpty
    }

    private static func finiteValue(_ value: Double, fallback: Double) -> Double {
        value.isFinite ? value : fallback
    }
}

enum SettingsStoreError: LocalizedError {
    case invalid(String)
    case keychain(String)

    var errorDescription: String? {
        switch self {
        case let .invalid(message), let .keychain(message):
            return message
        }
    }
}

enum KeychainError: LocalizedError {
    case status(OSStatus)
    case invalidResult

    var errorDescription: String? {
        switch self {
        case let .status(status):
            return "Keychain operation failed (status \(status))."
        case .invalidResult:
            return "Keychain returned an invalid value."
        }
    }
}

final class SettingsStore {
    private enum Key {
        static let translation = "scripture.translation"
        static let fixedReference = "scripture.fixedReference"
        static let autoOpenTime = "scripture.autoOpenTime"
        static let bookFilter = "scripture.bookFilter"
        static let topicFilter = "scripture.topicFilter"
        static let verseFontSize = "scripture.verseFontSize"
        static let scrimOpacity = "scripture.scrimOpacity"
        static let revealSpeed = "scripture.revealSpeed"
    }

    private let defaults: UserDefaults
    private let keychain: KeychainStore
    private(set) var lastLoadNotice: String?
    private(set) var lastLoadError: String?

    init(defaults: UserDefaults = .standard, keychain: KeychainStore = KeychainStore()) {
        self.defaults = defaults
        self.keychain = keychain
    }

    func load() -> AppSettings {
        lastLoadNotice = nil
        lastLoadError = nil

        let apiKey: String
        do {
            apiKey = try keychain.readAPIKey() ?? ""
        } catch {
            lastLoadError = error.localizedDescription
            apiKey = ""
        }

        let translationValue = defaults.string(forKey: Key.translation) ?? ""
        let topicValue = defaults.string(forKey: Key.topicFilter) ?? ""
        let translation = Translation(rawValue: translationValue) ?? .esv
        let topic = ScriptureTopic(rawValue: topicValue) ?? .all
        let raw = AppSettings(
            apiKey: apiKey,
            translation: translation,
            fixedReference: defaults.string(forKey: Key.fixedReference) ?? "",
            autoOpenTime: defaults.string(forKey: Key.autoOpenTime) ?? "",
            bookFilter: defaults.string(forKey: Key.bookFilter) ?? "",
            topicFilter: topic,
            verseFontSize: double(forKey: Key.verseFontSize, fallback: AppSettings().verseFontSize),
            scrimOpacity: double(forKey: Key.scrimOpacity, fallback: AppSettings().scrimOpacity),
            revealSpeed: double(forKey: Key.revealSpeed, fallback: AppSettings().revealSpeed)
        )
        var notices: [String] = []
        if !translationValue.isEmpty, translation == .esv, Translation(rawValue: translationValue) == nil {
            notices.append("The saved translation was reset.")
        }
        if !topicValue.isEmpty, topic == .all, ScriptureTopic(rawValue: topicValue) == nil {
            notices.append("The saved topic filter was reset.")
        }
        if let message = Self.validationMessage(for: raw), !notices.contains(message) {
            notices.append(message)
        }
        if !raw.verseFontSize.isFinite || raw.verseFontSize < 16 || raw.verseFontSize > 44
            || !raw.scrimOpacity.isFinite || raw.scrimOpacity < 0 || raw.scrimOpacity > 0.95
            || !raw.revealSpeed.isFinite || raw.revealSpeed < 0 || raw.revealSpeed > 1 {
            notices.append("Appearance values were normalized.")
        }
        if raw.apiKey.count > 4096 || !raw.apiKey.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }) {
            notices.append("The saved API key was cleared because it was invalid.")
        }
        let value = raw.normalized
        if !notices.isEmpty {
            lastLoadNotice = notices.joined(separator: " ")
            writeDefaults(value)
        }
        return value
    }

    func save(_ settings: AppSettings) throws {
        if let message = Self.validationMessage(for: settings) {
            throw SettingsStoreError.invalid(message)
        }
        let value = settings.normalized
        try keychain.saveAPIKey(value.apiKey)
        writeDefaults(value)
    }

    static func validationMessage(for settings: AppSettings) -> String? {
        let key = settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        if key.count > 4096 || !key.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }) {
            return "The API key contains invalid characters or is too long."
        }
        let fixed = settings.fixedReference.trimmingCharacters(in: .whitespacesAndNewlines)
        if !AppSettings.isValidFixedReference(fixed) {
            return "Fixed verse must be a safe reference such as John 3:16."
        }
        let time = settings.autoOpenTime.trimmingCharacters(in: .whitespacesAndNewlines)
        if !time.isEmpty, !AppSettings.isValidTime(time) {
            return "Auto-open must be a 24-hour time like 07:30."
        }
        let book = settings.bookFilter.trimmingCharacters(in: .whitespacesAndNewlines)
        if !book.isEmpty, AppSettings.canonicalBook(book) == nil {
            return "The saved book filter is invalid."
        }
        if !book.isEmpty, !AppSettings.hasFilterIntersection(book: book, topic: settings.topicFilter) {
            return "That book and topic have no verses in the deck."
        }
        if !settings.verseFontSize.isFinite
            || !settings.scrimOpacity.isFinite
            || !settings.revealSpeed.isFinite {
            return "Appearance values are invalid."
        }
        return nil
    }

    private func writeDefaults(_ value: AppSettings) {
        defaults.set(value.translation.rawValue, forKey: Key.translation)
        defaults.set(value.fixedReference, forKey: Key.fixedReference)
        defaults.set(value.autoOpenTime, forKey: Key.autoOpenTime)
        defaults.set(value.bookFilter, forKey: Key.bookFilter)
        defaults.set(value.topicFilter.rawValue, forKey: Key.topicFilter)
        defaults.set(value.verseFontSize, forKey: Key.verseFontSize)
        defaults.set(value.scrimOpacity, forKey: Key.scrimOpacity)
        defaults.set(value.revealSpeed, forKey: Key.revealSpeed)
    }

    private func double(forKey key: String, fallback: Double) -> Double {
        guard let number = defaults.object(forKey: key) as? NSNumber else { return fallback }
        return number.doubleValue
    }
}

final class KeychainStore {
    private let service: String
    private let account = "esv-api-key"

    init(service: String = Bundle.main.bundleIdentifier ?? "com.davidjm.scripture") {
        self.service = service
    }

    func readAPIKey() throws -> String? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess else {
            throw KeychainError.status(status)
        }
        guard let data = result as? Data else {
            throw KeychainError.invalidResult
        }
        guard let value = String(data: data, encoding: .utf8) else {
            throw KeychainError.invalidResult
        }
        return value
    }

    func saveAPIKey(_ value: String) throws {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            try deleteAPIKey()
            return
        }

        let data = Data(trimmed.utf8)
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account
        ]
        let attributes: [CFString: Any] = [
            kSecValueData: data,
            kSecAttrAccessible: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insert = query
            attributes.forEach { insert[$0.key] = $0.value }
            let insertStatus = SecItemAdd(insert as CFDictionary, nil)
            guard insertStatus == errSecSuccess else {
                throw KeychainError.status(insertStatus)
            }
        } else if status != errSecSuccess {
            throw KeychainError.status(status)
        }
    }

    func deleteAPIKey() throws {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account
        ]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.status(status)
        }
    }
}
