import Foundation

/// The translations supported by the desktop app and the iOS port.
enum Translation: String, CaseIterable, Codable, Hashable, Identifiable, Sendable {
    case esv = "ESV"
    case web = "WEB"
    case kjv = "KJV"

    var id: String { rawValue }

    var compactName: String { rawValue }

    var displayName: String {
        switch self {
        case .esv:
            return "English Standard Version"
        case .web:
            return "World English Bible"
        case .kjv:
            return "King James Version"
        }
    }

    var apiIdentifier: String {
        switch self {
        case .esv:
            return "esv"
        case .web:
            return "web"
        case .kjv:
            return "kjv"
        }
    }
}

/// A passage with the selected anchor verse separated from its surrounding text.
struct Passage: Codable, Equatable, Sendable {
    let anchor: String
    let before: String
    let focal: String
    let after: String
    let reference: String
    let translation: Translation
    let translationName: String

    var displayBefore: String {
        ScriptureReference.cleanProviderText(before)
    }

    var displayFocal: String {
        ScriptureReference.cleanProviderText(focal)
    }

    var displayAfter: String {
        ScriptureReference.cleanProviderText(after)
    }

    var displayReference: String {
        ScriptureReference.cleanProviderText(reference)
    }

    var displayTranslationName: String {
        translation.compactName
    }

    var fullText: String {
        [displayBefore, displayFocal, displayAfter]
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    var cardText: String {
        fullText
    }

    var plainFormattedText: String {
        let text = [displayBefore, displayFocal, displayAfter]
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        var sections: [String] = []
        if !text.isEmpty {
            sections.append(text)
        }
        sections.append(contentsOf: [displayReference, displayTranslationName].filter { !$0.isEmpty })
        return sections.joined(separator: "\n\n")
    }

    var visibleTextCount: Int {
        displayBefore.count + displayFocal.count + displayAfter.count
    }
}

struct ScriptureVerseID: Codable, Hashable, Sendable {
    let book: String
    let chapter: Int
    let verse: Int

    var canonicalID: String {
        "\(book.lowercased()):\(chapter):\(verse)"
    }
}

enum RevealTiming {
    static let intervalNanoseconds: UInt64 = 16_000_000

    static func duration(for speed: Double) -> TimeInterval? {
        guard speed.isFinite, speed > 0 else { return nil }
        return 1.1 / min(max(speed, 0.05), 1)
    }

    static func step(total: Int, speed: Double) -> Int {
        guard total > 0 else { return 0 }
        guard let duration = duration(for: speed) else { return total }
        return max(1, Int(ceil(Double(total) * 0.016 / duration)))
    }
}

enum ScriptureTopic: String, CaseIterable, Codable, Equatable, Hashable, Identifiable, Sendable {
    case all
    case hope
    case love
    case courage
    case wisdom
    case prayer
    case gratitude
    case faith

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .all:
            return "All topics"
        default:
            return rawValue.capitalized
        }
    }
}

/// The small, curated no-repeat deck used by the desktop application.
enum ScriptureReference {
    static let deck: [String] = [
        "Genesis 1:1", "Genesis 1:27", "Genesis 2:18", "Genesis 12:2", "Genesis 28:15",
        "Exodus 14:14", "Exodus 15:2", "Exodus 20:12", "Exodus 33:14",
        "Leviticus 19:18", "Leviticus 26:12",
        "Numbers 6:24", "Numbers 23:19",
        "Deuteronomy 6:5", "Deuteronomy 31:6", "Deuteronomy 33:27",
        "Joshua 1:9", "Joshua 24:15",
        "Judges 6:24",
        "Ruth 1:16",
        "1 Samuel 16:7", "1 Samuel 12:24",
        "2 Samuel 22:31",
        "1 Kings 8:61",
        "2 Kings 19:19",
        "1 Chronicles 16:11",
        "2 Chronicles 7:14",
        "Ezra 7:10",
        "Nehemiah 8:10",
        "Job 1:21", "Job 19:25", "Job 42:2",
        "Psalm 1:1", "Psalm 16:11", "Psalm 19:1", "Psalm 23:1", "Psalm 23:4",
        "Psalm 27:1", "Psalm 30:5", "Psalm 32:8", "Psalm 34:8", "Psalm 37:4",
        "Psalm 37:5", "Psalm 46:1", "Psalm 46:10", "Psalm 55:22", "Psalm 62:8",
        "Psalm 91:1", "Psalm 103:12", "Psalm 118:24", "Psalm 119:105", "Psalm 127:1",
        "Psalm 133:1", "Psalm 139:14", "Psalm 145:18", "Psalm 150:6",
        "Proverbs 3:5", "Proverbs 3:6", "Proverbs 16:3", "Proverbs 17:17",
        "Proverbs 18:10", "Proverbs 27:17",
        "Ecclesiastes 3:1", "Ecclesiastes 12:13",
        "Song of Solomon 4:7",
        "Isaiah 40:8", "Isaiah 40:31", "Isaiah 41:10", "Isaiah 41:13", "Isaiah 43:2",
        "Isaiah 53:5", "Isaiah 55:8", "Isaiah 58:11",
        "Jeremiah 29:11", "Jeremiah 33:3", "Lamentations 3:22", "Ezekiel 34:15",
        "Daniel 2:20", "Hosea 6:6", "Joel 2:13", "Amos 5:24", "Jonah 2:2",
        "Micah 6:8", "Nahum 1:7", "Habakkuk 3:19", "Zephaniah 3:17", "Haggai 2:4",
        "Zechariah 4:6", "Malachi 3:10",
        "Matthew 5:14", "Matthew 6:33", "Matthew 6:34", "Matthew 7:7", "Matthew 11:28",
        "Matthew 28:20",
        "Mark 9:23", "Mark 11:24",
        "Luke 1:37", "Luke 6:38", "Luke 10:27", "Luke 12:32", "Luke 15:10",
        "John 1:29", "John 3:16", "John 6:35", "John 8:32", "John 10:10", "John 10:27",
        "John 11:25", "John 13:34", "John 14:6", "John 14:27", "John 15:5", "John 16:33",
        "Acts 1:8", "Acts 4:12", "Acts 16:31",
        "Romans 3:23", "Romans 5:8", "Romans 8:28", "Romans 8:38", "Romans 10:9",
        "Romans 12:2", "Romans 12:12", "Romans 15:13",
        "1 Corinthians 10:13", "1 Corinthians 13:4", "1 Corinthians 15:58",
        "1 Corinthians 16:14",
        "2 Corinthians 5:17", "2 Corinthians 5:18", "2 Corinthians 12:9",
        "Galatians 5:22", "Galatians 6:9",
        "Ephesians 2:8", "Ephesians 2:10", "Ephesians 3:20", "Ephesians 4:32",
        "Ephesians 6:10",
        "Philippians 4:4", "Philippians 4:6", "Philippians 4:8", "Philippians 4:13",
        "Philippians 4:19",
        "Colossians 3:2", "Colossians 3:23",
        "1 Thessalonians 5:16", "1 Thessalonians 5:18",
        "2 Thessalonians 3:3",
        "1 Timothy 2:5", "1 Timothy 4:12", "1 Timothy 6:12",
        "2 Timothy 1:7", "2 Timothy 2:15", "2 Timothy 3:16", "2 Timothy 4:7",
        "Titus 2:11", "Philemon 1:6",
        "Hebrews 10:35", "Hebrews 11:1", "Hebrews 11:6", "Hebrews 12:1", "Hebrews 12:2",
        "Hebrews 13:5", "Hebrews 13:8",
        "James 1:5", "James 1:17", "James 2:17", "James 4:8", "James 4:10", "James 5:16",
        "1 Peter 2:9", "1 Peter 5:7",
        "2 Peter 1:4", "2 Peter 3:9",
        "1 John 1:9", "1 John 4:7", "1 John 4:19", "1 John 5:14",
        "2 John 1:6",
        "3 John 1:2",
        "Jude 1:21",
        "Revelation 3:20", "Revelation 21:4", "Revelation 22:20"
    ]

    static let allBooks: [String] = [
        "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua",
        "Judges", "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings",
        "1 Chronicles", "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job",
        "Psalm", "Proverbs", "Ecclesiastes", "Song of Solomon", "Isaiah",
        "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel",
        "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah",
        "Haggai", "Zechariah", "Malachi", "Matthew", "Mark", "Luke", "John",
        "Acts", "Romans", "1 Corinthians", "2 Corinthians", "Galatians",
        "Ephesians", "Philippians", "Colossians", "1 Thessalonians",
        "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon",
        "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John",
        "3 John", "Jude", "Revelation"
    ]

    private static let bookAliases: [String: String] = [
        "psalms": "Psalm",
        "song of songs": "Song of Solomon"
    ]

    static var books: [String] {
        var seen = Set<String>()
        return deck.compactMap { reference in
            guard let book = book(for: reference), seen.insert(book).inserted else { return nil }
            return book
        }
    }

    static func canonicalBookName(_ value: String) -> String? {
        let normalized = value
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")
        if let alias = bookAliases[normalized.lowercased()] {
            return alias
        }
        return allBooks.first {
            $0.caseInsensitiveCompare(normalized) == .orderedSame
        }
    }

    static func verseCount(forBook value: String) -> Int? {
        guard let book = canonicalBookName(value) else { return nil }
        return bookVerseCounts[book]
    }

    static func verseIDs(from reference: String) -> [ScriptureVerseID] {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let match = firstMatch(
            in: value,
            pattern: #"^(.*?)\s+(\d+):(\d+)(?:-(\d+))?$"#
        ), match.count >= 5,
              let book = canonicalBookName(match[1]),
              let chapter = Int(match[2]),
              let firstVerse = Int(match[3]),
              let lastVerse = Int(match[4].isEmpty ? "\(firstVerse)" : match[4]),
              chapter > 0,
              firstVerse > 0,
              lastVerse >= firstVerse,
              lastVerse - firstVerse < 2_000 else {
            return []
        }
        return (firstVerse...lastVerse).compactMap {
            ScriptureVerseID(book: book, chapter: chapter, verse: $0)
        }
    }

    static func verseID(fromCanonicalID value: String) -> ScriptureVerseID? {
        let parts = value.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 3,
              let book = canonicalBookName(String(parts[0])),
              let chapter = Int(parts[1]),
              let verse = Int(parts[2]),
              chapter > 0,
              verse > 0 else {
            return nil
        }
        let id = ScriptureVerseID(book: book, chapter: chapter, verse: verse)
        return id.canonicalID == value ? id : nil
    }

    static func verseIDs(
        for passage: Passage,
        requireNumberedText: Bool = false
    ) -> [ScriptureVerseID] {
        let referenceIDs = verseIDs(from: passage.reference)
        let sourceIDs = referenceIDs.isEmpty ? verseIDs(from: passage.anchor) : referenceIDs
        let numbers = [passage.before, passage.focal, passage.after]
            .flatMap { numberedVerseNumbers(in: $0) }
        if numbers.isEmpty {
            return requireNumberedText ? [] : sourceIDs
        }
        guard let book = sourceIDs.first?.book,
              let chapter = sourceIDs.first?.chapter,
              sourceIDs.allSatisfy({ $0.book == book && $0.chapter == chapter }) else {
            return []
        }
        var seen = Set<String>()
        var result: [ScriptureVerseID] = []
        for number in numbers where number > 0 {
            let id = ScriptureVerseID(book: book, chapter: chapter, verse: number)
            if seen.insert(id.canonicalID).inserted {
                result.append(id)
            }
        }
        return result.sorted {
            if $0.book != $1.book { return $0.book < $1.book }
            if $0.chapter != $1.chapter { return $0.chapter < $1.chapter }
            return $0.verse < $1.verse
        }
    }

    static func numberedVerseNumbers(in text: String) -> [Int] {
        guard let regex = try? NSRegularExpression(pattern: #"\[(\d+)\]"#) else {
            return []
        }
        let nsText = text as NSString
        let range = NSRange(location: 0, length: nsText.length)
        return regex.matches(in: text, options: [], range: range).compactMap { match in
            guard match.numberOfRanges >= 2 else { return nil }
            return Int(nsText.substring(with: match.range(at: 1)))
        }
    }

    static func book(for reference: String) -> String? {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let match = firstMatch(in: value, pattern: #"^(.*?)\s+\d+:\d+(?:-\d+)?$"#),
              match.count >= 2 else {
            return nil
        }
        let book = match[1].trimmingCharacters(in: .whitespacesAndNewlines)
        return book.isEmpty ? nil : book
    }

    private static let bookVerseCounts: [String: Int] = [
        "Genesis": 1533, "Exodus": 1213, "Leviticus": 859, "Numbers": 1533,
        "Deuteronomy": 959, "Joshua": 618, "Judges": 711, "Ruth": 85,
        "1 Samuel": 810, "2 Samuel": 722, "1 Kings": 246, "2 Kings": 304,
        "1 Chronicles": 439, "2 Chronicles": 647, "Ezra": 149,
        "Nehemiah": 406, "Esther": 223, "Job": 1670, "Psalm": 1891,
        "Proverbs": 915, "Ecclesiastes": 222, "Song of Solomon": 117,
        "Isaiah": 1291, "Jeremiah": 1893, "Lamentations": 154,
        "Ezekiel": 1178, "Daniel": 357, "Hosea": 197, "Joel": 73,
        "Amos": 146, "Obadiah": 21, "Jonah": 32, "Micah": 105,
        "Nahum": 47, "Habakkuk": 56, "Zephaniah": 53, "Haggai": 56,
        "Zechariah": 241, "Malachi": 18, "Matthew": 1071, "Mark": 678,
        "Luke": 1151, "John": 879, "Acts": 1211, "Romans": 433,
        "1 Corinthians": 437, "2 Corinthians": 256, "Galatians": 149,
        "Ephesians": 166, "Philippians": 104, "Colossians": 95,
        "1 Thessalonians": 89, "2 Thessalonians": 52, "1 Timothy": 224,
        "2 Timothy": 83, "Titus": 46, "Philemon": 25, "Hebrews": 303,
        "James": 62, "1 Peter": 63, "2 Peter": 61, "1 John": 105,
        "2 John": 13, "3 John": 14, "Jude": 25, "Revelation": 404
    ]

    static func references(for topic: ScriptureTopic) -> [String] {
        guard topic != .all else { return deck }
        return deck.filter { topicMembers[topic]?.contains($0) == true }
    }

    static func references(book: String, topic: ScriptureTopic) -> [String] {
        let value = book.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return references(for: topic) }
        return references(for: topic).filter { reference in
            self.book(for: reference)?.caseInsensitiveCompare(value) == .orderedSame
        }
    }

    private static let providerLegalMarkers = [
        "copyright",
        "all rights reserved",
        "used by permission",
        "scripture taken from",
        "permissions",
        "permission",
        "license",
        "reproduce",
        "crossway",
        "the holy bible",
        "english standard version",
        "the english standard version",
        "esv®",
        "the esv",
        "esv (",
        "esv translation",
        "©"
    ]

    private static let topicMembers: [ScriptureTopic: Set<String>] = [
        .hope: [
            "Genesis 12:2", "Isaiah 40:31", "Jeremiah 29:11", "Romans 15:13",
            "Hebrews 11:1", "Hebrews 12:2", "Revelation 21:4"
        ],
        .love: [
            "John 3:16", "John 13:34", "John 14:6", "John 15:5",
            "Romans 12:12", "1 Corinthians 13:4", "Ephesians 4:32", "1 John 4:7", "1 John 4:19"
        ],
        .courage: [
            "Joshua 1:9", "Isaiah 41:10", "Acts 4:12", "2 Corinthians 12:9",
            "Philippians 4:13", "2 Timothy 1:7"
        ],
        .wisdom: [
            "Proverbs 3:5", "Proverbs 3:6", "Proverbs 17:17", "Ecclesiastes 12:13",
            "James 1:5", "Psalm 119:105"
        ],
        .prayer: [
            "Psalm 46:1", "Jeremiah 33:3", "Matthew 7:7", "Philippians 4:6",
            "1 Thessalonians 5:16", "1 Thessalonians 5:18"
        ],
        .gratitude: [
            "Psalm 30:5", "Romans 12:2", "1 Thessalonians 5:18",
            "James 1:17", "Colossians 3:23"
        ],
        .faith: [
            "Mark 9:23", "Habakkuk 3:19", "Romans 10:9", "Acts 16:31",
            "Hebrews 11:1", "Hebrews 11:6", "Jude 1:21"
        ]
    ]

    /// Expand an anchor into the same short context window used by the desktop app.
    static func rangeQuery(_ reference: String, margin: Int = 2) -> String {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let match = firstMatch(in: value, pattern: #"^(.*?)\s+(\d+):(\d+)$"#),
          match.count >= 4,
          let chapter = Int(match[2]),
          let verse = Int(match[3]) else {
            return value
        }

        let start = max(1, verse - margin)
        let end = verse + margin
        if start == end {
            return "\(match[1]) \(chapter):\(verse)"
        }
        return "\(match[1]) \(chapter):\(start)-\(end)"
    }

    /// The verse number of an anchor, when it has a chapter and verse.
    static func focalVerse(_ reference: String) -> Int? {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let match = firstMatch(in: value, pattern: #"^.*?\s+\d+:(\d+)(?:-\d+)?$"#),
              match.count >= 2,
              let verse = Int(match[1]) else {
            return nil
        }
        return verse
    }

    static func browserURL(for reference: String, translation: Translation) -> URL? {
        let value = cleanProviderText(reference)
        guard !value.isEmpty else { return nil }
        let slug = value.replacingOccurrences(of: " ", with: "+")
        let string: String
        switch translation {
        case .esv:
            string = "https://www.esv.org/\(slug)/"
        case .web, .kjv:
            let version = translation == .kjv ? "KJV" : "WEB"
            string = "https://www.biblegateway.com/passage/?search=\(slug)&version=\(version)"
        }
        return URL(string: string)
    }

    static func cleanESVText(_ raw: String, reference: String) -> String {
        cleanProviderText(raw, reference: reference)
    }

    static func cleanProviderText(_ raw: String, reference: String? = nil) -> String {
        var text = raw
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        text = text.replacingOccurrences(of: #"[ \t]+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if let reference,
           !reference.isEmpty,
           let firstLine = text.split(separator: "\n", maxSplits: 1).first,
           firstLine.trimmingCharacters(in: .whitespacesAndNewlines).caseInsensitiveCompare(
               reference.trimmingCharacters(in: .whitespacesAndNewlines)
           ) == .orderedSame {
            text = String(text.dropFirst(firstLine.count))
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }

        var cutLocation = text.endIndex
        for marker in providerLegalMarkers {
            if let range = text.range(
                of: marker,
                options: [.caseInsensitive, .diacriticInsensitive]
            ), range.lowerBound < cutLocation {
                cutLocation = range.lowerBound
            }
        }
        if cutLocation != text.endIndex {
            text = String(text[..<cutLocation])
        }

        text = text.replacingOccurrences(
            of: #"(?m)^\s*\(ESV\)\s*$"#,
            with: "",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"(?m)^\s*ESV®?\s*$"#,
            with: "",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"\s*\(ESV\)\s*$"#,
            with: "",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"\s*ESV®?\s*$"#,
            with: "",
            options: .regularExpression
        )
        text = text.replacingOccurrences(of: #"\n{2,}"#, with: "\n", options: .regularExpression)
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Split an ESV response around the selected anchor verse.
    static func parseNumberedPassage(_ raw: String, focal: Int?) -> (before: String, focal: String, after: String) {
        let text = cleanProviderText(raw)
        let pattern = #"\[(\d+)\]([\s\S]*?)(?=\[\d+\]|$)"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.dotMatchesLineSeparators]) else {
            return ("", text, "")
        }

        let nsText = text as NSString
        let range = NSRange(location: 0, length: nsText.length)
        var before: [String] = []
        var focalText = ""
        var after: [String] = []
        var found = false

        for match in regex.matches(in: text, options: [], range: range) {
            guard match.numberOfRanges >= 3,
                  let number = Int(nsText.substring(with: match.range(at: 1))) else { continue }
            let verse = nsText.substring(with: match.range(at: 2))
                .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !verse.isEmpty else { continue }
            let formatted = "[\(number)] \(verse)"
            if number == focal, !found {
                focalText = formatted
                found = true
            } else if !found {
                before.append(formatted)
            } else {
                after.append(formatted)
            }
        }

        guard found else {
            let whole = regex.matches(in: text, options: [], range: range).compactMap { match -> String? in
                guard match.numberOfRanges >= 3,
                      let number = Int(nsText.substring(with: match.range(at: 1))) else { return nil }
                let verse = nsText.substring(with: match.range(at: 2))
                    .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                return verse.isEmpty ? nil : "[\(number)] \(verse)"
            }
            return ("", whole.joined(separator: " "), "")
        }

        return (before.joined(separator: " "), focalText, after.joined(separator: " "))
    }

    /// Split a bible-api.com response around the selected anchor verse.
    static func parseWebPassage(_ verses: [WebVerse], focal: Int?) -> (before: String, focal: String, after: String) {
        var before: [String] = []
        var focalText = ""
        var after: [String] = []
        var found = false

        for verse in verses {
            guard let number = verse.number else { continue }
            let text = cleanProviderText(verse.text)
            guard !text.isEmpty else { continue }
            let formatted = "[\(number)] \(text)"
            if number == focal, !found {
                focalText = formatted
                found = true
            } else if !found {
                before.append(formatted)
            } else {
                after.append(formatted)
            }
        }

        guard found else {
            let whole = verses.compactMap { verse in
                let text = cleanProviderText(verse.text)
                return text.isEmpty ? nil : text
            }
            return ("", whole.joined(separator: " "), "")
        }
        return (before.joined(separator: " "), focalText, after.joined(separator: " "))
    }

    private static func firstMatch(in value: String, pattern: String) -> [String]? {
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(
                in: value,
                options: [],
                range: NSRange(value.startIndex..<value.endIndex, in: value)
              ) else {
            return nil
        }
        let nsValue = value as NSString
        return (0..<match.numberOfRanges).map { nsValue.substring(with: match.range(at: $0)) }
    }
}

/// A deliberately small no-repeat deck implementation. It avoids repeats until
/// every curated reference has been shown, and avoids the immediately previous
/// reference when a new shuffled cycle begins.
final class ScriptureDeck {
    private let pool: [String]
    private var cards: [String] = []
    private var position = 0

    init(pool: [String] = ScriptureReference.deck) {
        self.pool = pool
    }

    func draw(avoiding previous: String? = nil) -> String {
        if position >= cards.count {
            cards = pool.shuffled()
            position = 0
        }
        guard !cards.isEmpty else { return "" }
        var reference = cards[position]
        position += 1
        if reference == previous, pool.count > 1 {
            reference = cards[position % cards.count]
            position += 1
        }
        return reference
    }
}
