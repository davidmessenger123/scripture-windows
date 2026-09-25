import Foundation

struct FavoritesStore {
    private let fileURL: URL
    private let fileManager: FileManager
    private let maximumEntries = 200
    private let maximumReferenceLength = 120

    init(fileManager: FileManager = .default, fileURL: URL? = nil) {
        self.fileManager = fileManager
        if let fileURL {
            self.fileURL = fileURL
            try? fileManager.createDirectory(
                at: fileURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
        } else {
            let base = (try? fileManager.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )) ?? fileManager.temporaryDirectory
            let directory = base.appendingPathComponent("Scripture", isDirectory: true)
            try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            self.fileURL = directory.appendingPathComponent("favorites.json")
        }
    }

    func list() -> [String] {
        guard let data = try? Data(contentsOf: fileURL, options: [.mappedIfSafe]),
              data.count <= 65_536,
              let values = try? JSONDecoder().decode([String].self, from: data) else {
            return []
        }
        return values
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .prefix(maximumEntries)
            .map { $0 }
    }

    func add(_ reference: String) -> [String] {
        let current = list()
        let value = clean(reference)
        let values = [value] + current.filter { $0 != value }
        let capped = Array(values.prefix(maximumEntries))
        guard write(capped) else { return current }
        return capped
    }

    func remove(_ reference: String) -> [String] {
        let current = list()
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        let values = current.filter { $0 != value }
        guard write(values) else { return current }
        return values
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

    private func clean(_ reference: String) -> String {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        return String(value.prefix(maximumReferenceLength))
    }

    @discardableResult
    private func write(_ values: [String]) -> Bool {
        guard let data = try? JSONEncoder().encode(Array(values.prefix(maximumEntries))) else { return false }
        let directory = fileURL.deletingLastPathComponent()
        try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let temporary = directory.appendingPathComponent(".favorites-\(UUID().uuidString).tmp")
        do {
            try data.write(to: temporary, options: [.atomic])
            if fileManager.fileExists(atPath: fileURL.path) {
                _ = try fileManager.replaceItemAt(fileURL, withItemAt: temporary)
            } else {
                try fileManager.moveItem(at: temporary, to: fileURL)
            }
            return true
        } catch {
            try? fileManager.removeItem(at: temporary)
            return false
        }
    }
}
