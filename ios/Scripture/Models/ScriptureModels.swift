import Foundation

/// The translations supported by the desktop app and the iOS port.
enum Translation: String, CaseIterable, Codable, Identifiable, Sendable {
    case esv = "ESV"
    case web = "WEB"
    case kjv = "KJV"

    var id: String { rawValue }

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
struct Passage: Equatable, Sendable {
    let anchor: String
    let before: String
    let focal: String
    let after: String
    let reference: String
    let translation: Translation
    let translationName: String

    var fullText: String {
        [before, focal, after]
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    var visibleTextCount: Int {
        before.count + focal.count + after.count
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
        guard let match = firstMatch(in: value, pattern: #"^.*?\s+\d+:(\d+)$"#),
              match.count >= 2,
              let verse = Int(match[1]) else {
            return nil
        }
        return verse
    }

    static func browserURL(for reference: String, translation: Translation) -> URL? {
        let value = reference.trimmingCharacters(in: .whitespacesAndNewlines)
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
        var text = raw
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        text = text.replacingOccurrences(of: #"[ \t]+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if !reference.isEmpty,
           let firstLine = text.split(separator: "\n", maxSplits: 1).first,
           firstLine.trimmingCharacters(in: .whitespacesAndNewlines).caseInsensitiveCompare(
               reference.trimmingCharacters(in: .whitespacesAndNewlines)
           ) == .orderedSame {
            text = String(text.dropFirst(firstLine.count))
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }

        text = text.replacingOccurrences(
            of: #"\s*\(ESV\)\s*$"#,
            with: "",
            options: .regularExpression
        )
        text = text.replacingOccurrences(of: #"\n{2,}"#, with: "\n", options: .regularExpression)
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Split an ESV response around the selected anchor verse.
    static func parseNumberedPassage(_ raw: String, focal: Int?) -> (before: String, focal: String, after: String) {
        let text = raw
            .replacingOccurrences(of: #"[ \t]+"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: "\r\n", with: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
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
            guard let number = verse.number, !verse.text.isEmpty else { continue }
            let formatted = "[\(number)] \(verse.text)"
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
                verse.text.isEmpty ? nil : verse.text
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
