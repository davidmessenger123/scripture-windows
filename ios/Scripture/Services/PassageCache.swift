import Foundation

private struct PassageCacheEntry: Codable {
    let passage: Passage
    let providerIdentity: String?
    let verseIDs: [String]
}

private struct PassageCacheEnvelope: Codable {
    let version: Int
    let entries: [PassageCacheEntry]
}

private func markExcludedFromBackup(_ url: URL) throws {
    var values = URLResourceValues()
    values.isExcludedFromBackup = true
    var mutableURL = url
    try mutableURL.setResourceValues(values)
}

private func defaultPassageCacheFileURL(fileManager: FileManager) -> URL {
    let base = (try? fileManager.url(
        for: .cachesDirectory,
        in: .userDomainMask,
        appropriateFor: nil,
        create: true
    )) ?? fileManager.temporaryDirectory
    let directory = base.appendingPathComponent("Scripture", isDirectory: true)
    try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
    try? markExcludedFromBackup(directory)
    return directory.appendingPathComponent("passage-cache.json", isDirectory: false)
}

actor PassageCache {
    static let maximumVersesPerProvider = 500
    static let maximumFileBytes = 1_048_576
    static let maximumPassageCharacters = 24_000

    nonisolated static func maximumVerses(forBook book: String) -> Int {
        guard let count = ScriptureReference.verseCount(forBook: book) else { return 1 }
        return max(1, count / 2)
    }

    private let fileURL: URL
    private let fileManager: FileManager
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(fileManager: FileManager = .default, fileURL: URL? = nil) {
        self.fileManager = fileManager
        self.fileURL = fileURL ?? defaultPassageCacheFileURL(fileManager: fileManager)

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        self.encoder = encoder
        self.decoder = JSONDecoder()
    }

    func passage(
        for anchor: String,
        translations: [Translation],
        esvKeyIdentity: String? = nil
    ) -> Passage? {
        let normalizedAnchor = Self.normalized(anchor).lowercased()
        let allowedTranslations = Set(translations)
        guard !normalizedAnchor.isEmpty,
              !allowedTranslations.isEmpty,
              let entry = validEntries().first(where: {
                  allowedTranslations.contains($0.passage.translation)
                      && Self.normalized($0.passage.anchor).lowercased() == normalizedAnchor
                      && identityMatches($0, esvKeyIdentity: esvKeyIdentity)
              }) else {
            return nil
        }
        return entry.passage
    }

    @discardableResult
    func store(_ passage: Passage, esvKeyIdentity: String? = nil) -> Bool {
        guard isValid(passage) else { return false }

        let providerIdentity: String?
        if passage.translation == .esv {
            guard let esvKeyIdentity, validIdentity(esvKeyIdentity) else { return false }
            providerIdentity = esvKeyIdentity
        } else {
            providerIdentity = nil
        }

        let verseIDs = ScriptureReference.verseIDs(
            for: passage,
            requireNumberedText: passage.translation == .esv
        )
        if passage.translation == .esv, verseIDs.isEmpty {
            return false
        }

        var entries = validEntries()
        if passage.translation == .esv {
            entries.removeAll {
                $0.passage.translation == .esv && $0.providerIdentity != providerIdentity
            }
        }
        let key = Self.cacheKey(
            anchor: passage.anchor,
            translation: passage.translation,
            providerIdentity: providerIdentity
        )
        entries.removeAll {
            Self.cacheKey(
                anchor: $0.passage.anchor,
                translation: $0.passage.translation,
                providerIdentity: $0.providerIdentity
            ) == key
        }
        entries.insert(
            PassageCacheEntry(
                passage: passage,
                providerIdentity: providerIdentity,
                verseIDs: verseIDs.map { $0.canonicalID }
            ),
            at: 0
        )
        enforcePolicy(&entries)

        return persist(entries)
    }

    @discardableResult
    func removeAll() -> Bool {
        guard fileManager.fileExists(atPath: fileURL.path) else { return true }
        do {
            try fileManager.removeItem(at: fileURL)
            return true
        } catch {
            return false
        }
    }

    func verseCount(for translation: Translation) -> Int {
        uniqueVerseCount(validEntries(), translation: translation)
    }

    nonisolated static func cacheKey(anchor: String, translation: Translation) -> String {
        cacheKey(anchor: anchor, translation: translation, providerIdentity: nil)
    }

    nonisolated static func cacheKey(
        anchor: String,
        translation: Translation,
        providerIdentity: String?
    ) -> String {
        "\(translation.rawValue.lowercased())|\(normalized(anchor).lowercased())|\(providerIdentity ?? "")"
    }

    nonisolated static func normalized(_ value: String) -> String {
        value
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static let currentVersion = 3

    private func validEntries() -> [PassageCacheEntry] {
        guard let data = readData(),
              data.count <= Self.maximumFileBytes,
              let envelope = try? decoder.decode(PassageCacheEnvelope.self, from: data),
              envelope.version == Self.currentVersion else {
            return []
        }
        var entries = envelope.entries.filter { isValidEntry($0) }
        enforcePolicy(&entries)
        if entries.count != envelope.entries.count {
            _ = persist(entries)
        }
        return entries
    }

    private func persist(_ entries: [PassageCacheEntry]) -> Bool {
        var data: Data?
        var values = entries
        while true {
            guard let encoded = try? encoder.encode(
                PassageCacheEnvelope(version: Self.currentVersion, entries: values)
            ) else {
                return false
            }
            if encoded.count <= Self.maximumFileBytes {
                data = encoded
                break
            }
            guard values.count > 1 else { return false }
            values.removeLast()
        }
        guard let data else { return false }

        do {
            let directory = fileURL.deletingLastPathComponent()
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            try markExcludedFromBackup(directory)
            try fileManager.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: directory.path
            )
            try data.write(to: fileURL, options: [.atomic])
            try markExcludedFromBackup(fileURL)
            try fileManager.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: fileURL.path
            )
            return true
        } catch {
            try? fileManager.removeItem(at: fileURL)
            return false
        }
    }

    private func readData() -> Data? {
        guard let handle = try? FileHandle(forReadingFrom: fileURL) else { return nil }
        defer { try? handle.close() }
        do {
            guard let data = try handle.read(upToCount: Self.maximumFileBytes + 1) else { return nil }
            return data
        } catch {
            return nil
        }
    }

    private func isValidEntry(_ entry: PassageCacheEntry) -> Bool {
        guard isValid(entry.passage) else { return false }
        guard entry.verseIDs.allSatisfy({
            ScriptureReference.verseID(fromCanonicalID: $0) != nil
        }), Set(entry.verseIDs).count == entry.verseIDs.count else {
            return false
        }
        if entry.passage.translation == .esv {
            let derived = ScriptureReference.verseIDs(
                for: entry.passage,
                requireNumberedText: true
            ).map { $0.canonicalID }
            return validIdentity(entry.providerIdentity)
                && !derived.isEmpty
                && Set(entry.verseIDs) == Set(derived)
        }
        return entry.providerIdentity == nil
    }

    private func identityMatches(
        _ entry: PassageCacheEntry,
        esvKeyIdentity: String?
    ) -> Bool {
        guard entry.passage.translation == .esv else { return true }
        guard let esvKeyIdentity, validIdentity(esvKeyIdentity) else { return false }
        return entry.providerIdentity == esvKeyIdentity
    }

    private func validIdentity(_ value: String?) -> Bool {
        guard let value, !value.isEmpty, value.count <= 128 else { return false }
        return value.unicodeScalars.allSatisfy {
            ($0.value >= 48 && $0.value <= 57)
                || ($0.value >= 97 && $0.value <= 102)
        }
    }

    private func isValid(_ passage: Passage) -> Bool {
        let anchor = Self.normalized(passage.anchor)
        guard !anchor.isEmpty,
              anchor.count <= 240,
              safeText(anchor, maximumLength: 240),
              !passage.focal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              safeText(passage.before, maximumLength: 8_000),
              safeText(passage.focal, maximumLength: 8_000),
              safeText(passage.after, maximumLength: 8_000),
              !passage.reference.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              safeText(passage.reference, maximumLength: 300),
              !passage.translationName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              safeText(passage.translationName, maximumLength: 200),
              passage.before.count + passage.focal.count + passage.after.count <= Self.maximumPassageCharacters else {
            return false
        }
        return true
    }

    private func safeText(_ value: String, maximumLength: Int) -> Bool {
        guard value.count <= maximumLength else { return false }
        return value.unicodeScalars.allSatisfy {
            $0.value >= 32 || $0.value == 9 || $0.value == 10 || $0.value == 13
        }
    }

    private func enforcePolicy(_ entries: inout [PassageCacheEntry]) {
        while uniqueVerseCount(entries, translation: .esv) > Self.maximumVersesPerProvider {
            guard removeLast(&entries, translation: .esv) else { return }
        }

        for book in ScriptureReference.allBooks {
            while uniqueVerseCount(entries, translation: .esv, book: book)
                > Self.maximumVerses(forBook: book) {
                guard removeLast(&entries, translation: .esv, book: book) else { break }
            }
        }
    }

    private func uniqueVerseCount(
        _ entries: [PassageCacheEntry],
        translation: Translation,
        book: String? = nil
    ) -> Int {
        var ids = Set<String>()
        for entry in entries where entry.passage.translation == translation {
            let entryBooks = entry.verseIDs.compactMap {
                ScriptureReference.verseID(fromCanonicalID: $0)?.book
            }
            if let book, !entryBooks.contains(book) {
                continue
            }
            ids.formUnion(entry.verseIDs)
        }
        return ids.count
    }

    @discardableResult
    private func removeLast(
        _ entries: inout [PassageCacheEntry],
        translation: Translation,
        book: String? = nil
    ) -> Bool {
        guard let index = entries.lastIndex(where: { entry in
            guard entry.passage.translation == translation else { return false }
            guard let book else { return true }
            return entry.verseIDs.contains {
                ScriptureReference.verseID(fromCanonicalID: $0)?.book == book
            }
        }) else {
            return false
        }
        entries.remove(at: index)
        return true
    }
}
