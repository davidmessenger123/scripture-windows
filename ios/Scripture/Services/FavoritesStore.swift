import Foundation

struct FavoritesStore {
    private let fileURL: URL
    private let fileManager: FileManager
    private let maximumEntries = 200
    private let maximumReferenceLength = 120

    init(fileManager: FileManager = .default) {
        self.fileManager = fileManager
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
        let value = clean(reference)
        let values = [value] + list().filter { $0 != value }
        let capped = Array(values.prefix(maximumEntries))
        write(capped)
        return capped
    }

    func remove(_ reference: String) -> [String] {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        let values = list().filter { $0 != value }
        write(values)
        return values
    }

    private func clean(_ reference: String) -> String {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        return String(value.prefix(maximumReferenceLength))
    }

    private func write(_ values: [String]) {
        guard let data = try? JSONEncoder().encode(Array(values.prefix(maximumEntries))) else { return }
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
        } catch {
            try? fileManager.removeItem(at: temporary)
        }
    }
}
