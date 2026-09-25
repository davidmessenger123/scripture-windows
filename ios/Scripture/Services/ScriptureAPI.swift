import CryptoKit
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
        self.text = ScriptureReference.cleanProviderText(rawText)
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
    static let maxResponseBytes = 262_144
    private static let timeout: TimeInterval = 15

    static func canAppendResponseByte(currentCount: Int) -> Bool {
        currentCount < maxResponseBytes
    }

    static var userAgent: String {
        let version = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)?
            .flatMap { $0.isEmpty ? nil : $0 } ?? "0.2.0"
        return "scripture-ios/\(version)"
    }

    static func esvKeyIdentity(for apiKey: String?) -> String? {
        guard let value = apiKey?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty else {
            return nil
        }
        let digest = SHA256.hash(data: Data("esv-key-v1:\(value)".utf8))
        return digest.map { String(format: "%02x", Int($0)) }.joined()
    }

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
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")

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
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")

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
            if let rawText = response.text?.value {
                let text = ScriptureReference.cleanProviderText(rawText)
                if !text.isEmpty {
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
        do {
            let (bytes, response) = try await session.bytes(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                throw ScriptureAPIError.server(statusCode: http.statusCode)
            }

            var data = Data()
            data.reserveCapacity(Self.maxResponseBytes)
            for try await byte in bytes {
                guard Self.canAppendResponseByte(currentCount: data.count) else {
                    throw ScriptureAPIError.responseTooLarge
                }
                data.append(byte)
            }
            return data
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as ScriptureAPIError {
            throw error
        } catch {
            throw ScriptureAPIError.network(error.localizedDescription)
        }
    }
}

private extension String {
    var nonEmpty: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
