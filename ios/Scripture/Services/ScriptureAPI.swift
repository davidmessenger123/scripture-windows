import Foundation

/// A small decoder used for bible-api.com fields that are sometimes strings and
/// sometimes numbers depending on the endpoint response.
struct FlexibleString: Decodable {
    let value: String?

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let string = try? container.decode(String.self) {
            value = string
        } else if let integer = try? container.decode(Int.self) {
            value = String(integer)
        } else if let double = try? container.decode(Double.self) {
            value = String(double)
        } else {
            value = nil
        }
    }
}

struct WebVerse: Decodable {
    let number: Int?
    let text: String

    private enum CodingKeys: String, CodingKey {
        case verse
        case number
        case text
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let verse = try container.decodeIfPresent(FlexibleString.self, forKey: .verse)
        let number = try container.decodeIfPresent(FlexibleString.self, forKey: .number)
        let text = try container.decodeIfPresent(FlexibleString.self, forKey: .text)
        self.number = Int(verse?.value ?? "") ?? Int(number?.value ?? "")
        let rawText = text?.value ?? ""
        self.text = rawText
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private struct ESVResponse: Decodable {
    let canonical: String?
    let passages: [String]?
}

private struct WebTranslation: Decodable {
    let name: String?
}

private struct WebResponse: Decodable {
    let error: FlexibleString?
    let verses: [WebVerse]?
    let reference: FlexibleString?
    let translation: WebTranslation?
    let translationName: FlexibleString?
    let text: FlexibleString?
}

enum ScriptureAPIError: LocalizedError {
    case invalidURL
    case invalidResponse
    case server(statusCode: Int)
    case responseTooLarge
    case emptyPassage
    case decoding
    case network(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "The Scripture request could not be created."
        case .invalidResponse:
            return "The Scripture service returned an invalid response."
        case let .server(statusCode):
            return "The Scripture service returned HTTP \(statusCode)."
        case .responseTooLarge:
            return "The Scripture response was unexpectedly large."
        case .emptyPassage:
            return "The Scripture service returned no passage."
        case .decoding:
            return "The Scripture response could not be read."
        case let .network(message):
            return message
        }
    }
}

/// Network layer for the same two providers used by the desktop application.
struct ScriptureAPI: Sendable {
    private static let esvURL = "https://api.esv.org/v3/passage/text/"
    private static let webURL = "https://bible-api.com"
    private static let maxResponseBytes = 262_144
    private static let timeout: TimeInterval = 15

    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    /// Fetch an anchor and its surrounding verses. If an expanded range is not
    /// accepted, retry once with the exact anchor, matching the desktop client.
    func fetch(
        anchor: String,
        translation: Translation,
        apiKey: String?
    ) async throws -> Passage {
        let requestedTranslation: Translation
        let hasESVKey = !(apiKey?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
        if translation == .esv, !hasESVKey {
            requestedTranslation = .web
        } else {
            requestedTranslation = translation
        }

        let expanded = ScriptureReference.rangeQuery(anchor)
        do {
            if requestedTranslation == .esv {
                return try await fetchESV(reference: expanded, anchor: anchor, apiKey: apiKey ?? "")
            }
            return try await fetchWeb(reference: expanded, anchor: anchor, translation: requestedTranslation)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            let exact = anchor.trimmingCharacters(in: .whitespacesAndNewlines)
            guard expanded != exact else { throw error }
            if requestedTranslation == .esv {
                return try await fetchESV(reference: exact, anchor: anchor, apiKey: apiKey ?? "")
            }
            return try await fetchWeb(reference: exact, anchor: anchor, translation: requestedTranslation)
        }
    }

    private func fetchESV(reference: String, anchor: String, apiKey: String) async throws -> Passage {
        var components = URLComponents(string: Self.esvURL)
        components?.queryItems = [
            URLQueryItem(name: "q", value: reference),
            URLQueryItem(name: "include-headings", value: "false"),
            URLQueryItem(name: "include-footnotes", value: "false"),
            URLQueryItem(name: "include-verse-numbers", value: "true"),
            URLQueryItem(name: "include-short-copyright", value: "false"),
            URLQueryItem(name: "include-passage-references", value: "false")
        ]
        guard let url = components?.url else { throw ScriptureAPIError.invalidURL }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = Self.timeout
        request.setValue("Token \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("scripture-ios/1.0", forHTTPHeaderField: "User-Agent")

        let data = try await perform(request)
        let response: ESVResponse
        do {
            response = try JSONDecoder().decode(ESVResponse.self, from: data)
        } catch {
            throw ScriptureAPIError.decoding
        }
        guard let rawPassage = response.passages?.first, !rawPassage.isEmpty else {
            throw ScriptureAPIError.emptyPassage
        }

        let cleaned = ScriptureReference.cleanESVText(rawPassage, reference: reference)
        let pieces = ScriptureReference.parseNumberedPassage(cleaned, focal: ScriptureReference.focalVerse(anchor))
        guard !pieces.focal.isEmpty else { throw ScriptureAPIError.emptyPassage }
        return Passage(
            anchor: anchor,
            before: pieces.before,
            focal: pieces.focal,
            after: pieces.after,
            reference: response.canonical?.trimmingCharacters(in: .whitespacesAndNewlines).nonEmpty ?? reference,
            translation: .esv,
            translationName: Translation.esv.displayName
        )
    }

    private func fetchWeb(reference: String, anchor: String, translation: Translation) async throws -> Passage {
        let slug = reference.replacingOccurrences(of: " ", with: "+")
        let urlString = "\(Self.webURL)/\(slug)?translation=\(translation.apiIdentifier)"
        guard let url = URL(string: urlString) else { throw ScriptureAPIError.invalidURL }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = Self.timeout
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("scripture-ios/1.0", forHTTPHeaderField: "User-Agent")

        let data = try await perform(request)
        let response: WebResponse
        do {
            response = try JSONDecoder().decode(WebResponse.self, from: data)
        } catch {
            throw ScriptureAPIError.decoding
        }
        if let error = response.error?.value, !error.isEmpty {
            throw ScriptureAPIError.network(error)
        }
        guard let verses = response.verses, !verses.isEmpty else {
            if let text = response.text?.value?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
                return Passage(
                    anchor: anchor,
                    before: "",
                    focal: text,
                    after: "",
                    reference: response.reference?.value?.nonEmpty ?? reference,
                    translation: translation,
                    translationName: translation.displayName
                )
            }
            throw ScriptureAPIError.emptyPassage
        }

        let pieces = ScriptureReference.parseWebPassage(
            verses,
            focal: ScriptureReference.focalVerse(anchor)
        )
        guard !pieces.focal.isEmpty else { throw ScriptureAPIError.emptyPassage }
        let name = response.translation?.name?.nonEmpty
            ?? response.translationName?.value?.nonEmpty
            ?? translation.displayName
        return Passage(
            anchor: anchor,
            before: pieces.before,
            focal: pieces.focal,
            after: pieces.after,
            reference: response.reference?.value?.nonEmpty ?? reference,
            translation: translation,
            translationName: name
        )
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw ScriptureAPIError.network(error.localizedDescription)
        }

        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw ScriptureAPIError.server(statusCode: http.statusCode)
        }
        guard data.count <= Self.maxResponseBytes else {
            throw ScriptureAPIError.responseTooLarge
        }
        return data
    }
}

private extension String {
    var nonEmpty: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
