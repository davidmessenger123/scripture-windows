import Foundation
import Security

struct AppSettings: Equatable, Sendable {
    var apiKey = ""
    var translation: Translation = .esv
    var fixedReference = ""
    var autoOpenTime = ""

    static let empty = AppSettings()
}

final class SettingsStore {
    private enum Key {
        static let translation = "scripture.translation"
        static let fixedReference = "scripture.fixedReference"
        static let autoOpenTime = "scripture.autoOpenTime"
    }

    private let defaults: UserDefaults
    private let keychain: KeychainStore

    init(defaults: UserDefaults = .standard, keychain: KeychainStore = KeychainStore()) {
        self.defaults = defaults
        self.keychain = keychain
    }

    func load() -> AppSettings {
        let translation = Translation(rawValue: defaults.string(forKey: Key.translation) ?? "") ?? .esv
        return AppSettings(
            apiKey: keychain.readAPIKey() ?? "",
            translation: translation,
            fixedReference: defaults.string(forKey: Key.fixedReference) ?? "",
            autoOpenTime: defaults.string(forKey: Key.autoOpenTime) ?? ""
        )
    }

    func save(_ settings: AppSettings) {
        defaults.set(settings.translation.rawValue, forKey: Key.translation)
        defaults.set(settings.fixedReference.trimmingCharacters(in: .whitespacesAndNewlines), forKey: Key.fixedReference)
        defaults.set(settings.autoOpenTime.trimmingCharacters(in: .whitespacesAndNewlines), forKey: Key.autoOpenTime)
        keychain.saveAPIKey(settings.apiKey.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}

final class KeychainStore {
    private let service: String
    private let account = "esv-api-key"

    init(service: String = Bundle.main.bundleIdentifier ?? "com.davidjm.scripture") {
        self.service = service
    }

    func readAPIKey() -> String? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    func saveAPIKey(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            deleteAPIKey()
            return
        }

        let data = Data(trimmed.utf8)
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account
        ]
        let attributes: [CFString: Any] = [kSecValueData: data]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insert = query
            insert[kSecValueData] = data
            SecItemAdd(insert as CFDictionary, nil)
        }
    }

    func deleteAPIKey() {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account
        ]
        SecItemDelete(query as CFDictionary)
    }
}
