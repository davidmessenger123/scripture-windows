import Foundation
import XCTest
@testable import Scripture

final class ScriptureReferenceTests: XCTestCase {
    func testRangeQueryExpandsAnchor() {
        XCTAssertEqual(ScriptureReference.rangeQuery("John 3:16"), "John 3:14-18")
        XCTAssertEqual(ScriptureReference.rangeQuery("Genesis 1:1"), "Genesis 1:1-3")
    }

    func testFocalVerse() {
        XCTAssertEqual(ScriptureReference.focalVerse("John 3:16"), 16)
        XCTAssertEqual(ScriptureReference.focalVerse("John 3:14-18"), 14)
        XCTAssertNil(ScriptureReference.focalVerse("John 3"))
    }

    func testESVCleaningRetainsVerseMarkers() {
        let cleaned = ScriptureReference.cleanESVText(
            "John 3:14-18\n[14] And as Moses lifted up\n(ESV)",
            reference: "John 3:14-18"
        )
        XCTAssertTrue(cleaned.contains("[14]"))
        XCTAssertFalse(cleaned.contains("(ESV)"))
    }

    func testESVCleaningRemovesProviderLegalBlock() {
        let legal = "Scripture taken from the ESV® (The Holy Bible, English Standard Version®). ESV® Copyright © 2001, 2016 Crossway. Used by permission. All rights reserved."
        let cleaned = ScriptureReference.cleanESVText(
            "John 3:14-18\n[14] And as Moses lifted up\n[16] For God so loved\n\(legal)",
            reference: "John 3:14-18"
        )
        XCTAssertTrue(cleaned.contains("[16] For God so loved"))
        XCTAssertFalse(cleaned.contains("Scripture taken"))
        XCTAssertFalse(cleaned.contains("Crossway"))
        XCTAssertFalse(cleaned.contains("All rights reserved"))
    }

    func testNumberedPassageCentersAnchor() {
        let result = ScriptureReference.parseNumberedPassage(
            "[14] before [15] nearby [16] For God so loved [17] the world",
            focal: 16
        )
        XCTAssertEqual(result.focal, "[16] For God so loved")
        XCTAssertTrue(result.before.contains("[14]"))
        XCTAssertTrue(result.after.contains("[17]"))
    }

    func testTimeValidation() {
        XCTAssertEqual(ScriptureViewModel.timeComponents("07:30")?.hour, 7)
        XCTAssertNil(ScriptureViewModel.timeComponents("24:00"))
        XCTAssertNil(ScriptureViewModel.timeComponents("7:30"))
    }

    func testDeckDoesNotRepeatBeforeCycleCompletes() {
        let pool = ["A", "B", "C"]
        let deck = ScriptureDeck(pool: pool)
        var seen: [String] = []
        for _ in 0..<pool.count {
            seen.append(deck.draw())
        }
        XCTAssertEqual(Set(seen), Set(pool))
    }

    func testPlainFormattedTextIncludesReferenceAndCompactTranslation() {
        let passage = Passage(
            anchor: "John 3:16",
            before: "[14] Before",
            focal: "[16] For God so loved",
            after: "[17] The world",
            reference: "John 3:14-18",
            translation: .web,
            translationName: "World English Bible"
        )
        XCTAssertEqual(
            passage.plainFormattedText,
            "[14] Before\n[16] For God so loved\n[17] The world\n\nJohn 3:14-18\nWEB"
        )
    }

    func testUserFacingOutputsExcludeProviderLegalText() {
        let legal = "Scripture taken from the ESV® (The Holy Bible, English Standard Version®). ESV® Copyright © 2001, 2016 Crossway. Used by permission. All rights reserved."
        let passage = Passage(
            anchor: "John 3:16",
            before: "[14] Before",
            focal: "[16] For God so loved\n\(legal)",
            after: "[17] The world",
            reference: "John 3:14-18",
            translation: .esv,
            translationName: legal
        )
        let outputs = [
            passage.displayBefore,
            passage.displayFocal,
            passage.displayAfter,
            passage.fullText,
            passage.cardText,
            passage.plainFormattedText,
            NotificationScheduler.notificationBody(for: passage)
        ]

        for output in outputs {
            XCTAssertFalse(output.contains(legal))
            XCTAssertFalse(output.contains("Scripture taken"))
            XCTAssertFalse(output.contains("Crossway"))
            XCTAssertFalse(output.contains("All rights reserved"))
        }
        XCTAssertEqual(passage.displayReference, "John 3:14-18")
        XCTAssertEqual(passage.displayTranslationName, "ESV")
        XCTAssertTrue(passage.plainFormattedText.contains("John 3:14-18"))
        XCTAssertTrue(passage.plainFormattedText.contains("ESV"))
        XCTAssertTrue(NotificationScheduler.notificationBody(for: passage).contains("ESV"))
    }

    func testFilterIntersectionsNeverBroadenTheDeck() {
        let cases: [(String, ScriptureTopic)] = [
            ("Genesis", .love),
            ("John", .gratitude),
            ("Genesis", .faith),
            ("John", .prayer)
        ]
        for (book, topic) in cases {
            let settings = AppSettings(bookFilter: book, topicFilter: topic)
            XCTAssertTrue(ScriptureReference.references(book: book, topic: topic).isEmpty)
            XCTAssertNotNil(SettingsStore.validationMessage(for: settings))
            let normalized = settings.normalized
            XCTAssertTrue(normalized.bookFilter.isEmpty)
            XCTAssertEqual(normalized.topicFilter, .all)
        }
    }

    func testSettingsRejectInvalidRawValues() {
        let settings = AppSettings(
            fixedReference: "John\n3:16",
            autoOpenTime: "25:00",
            bookFilter: "Not a book"
        )
        XCTAssertNotNil(SettingsStore.validationMessage(for: settings))
        XCTAssertTrue(settings.normalized.fixedReference.isEmpty)
        XCTAssertTrue(settings.normalized.autoOpenTime.isEmpty)
        XCTAssertTrue(settings.normalized.bookFilter.isEmpty)
        XCTAssertTrue(SettingsStore.isValidFixedReference("John 3:16"))
        XCTAssertTrue(SettingsStore.isValidFixedReference("John 3:14-18"))
        XCTAssertFalse(SettingsStore.isValidFixedReference("not a reference"))
    }

    func testSettingsClampAppearanceValues() {
        let settings = AppSettings(
            verseFontSize: 999,
            scrimOpacity: -4,
            revealSpeed: Double.nan
        ).normalized
        XCTAssertEqual(settings.verseFontSize, 44)
        XCTAssertEqual(settings.scrimOpacity, 0)
        XCTAssertEqual(settings.revealSpeed, 0.5)
    }

    func testRevealSpeedBoundaries() {
        XCTAssertNil(RevealTiming.duration(for: 0))
        XCTAssertEqual(RevealTiming.duration(for: 0.5) ?? 0, 2.2, accuracy: 0.0001)
        XCTAssertEqual(RevealTiming.step(total: 100, speed: 0), 100)
        XCTAssertGreaterThan(RevealTiming.step(total: 100, speed: 0.5), RevealTiming.step(total: 100, speed: 1))
    }

    func testNotificationBodyUsesUTF8ByteCapAndKeepsLabel() {
        let passage = Passage(
            anchor: "John 3:16",
            before: "",
            focal: String(repeating: "é", count: 1_000),
            after: "",
            reference: "John 3:16",
            translation: .esv,
            translationName: "Legal metadata"
        )
        let body = NotificationScheduler.notificationBody(for: passage)
        XCTAssertLessThanOrEqual(body.utf8.count, NotificationScheduler.maximumNotificationBodyBytes)
        XCTAssertTrue(body.hasSuffix("ESV"))
        XCTAssertEqual(NotificationScheduler.truncateUTF8("😀abc", maximumBytes: 4), "😀")
    }

    func testNotificationDedupeFingerprintIsDeterministic() {
        let first = NotificationScheduler.dedupeFingerprint(hour: 7, minute: 30, body: "Verse")
        let second = NotificationScheduler.dedupeFingerprint(hour: 7, minute: 30, body: "Verse")
        let different = NotificationScheduler.dedupeFingerprint(hour: 7, minute: 31, body: "Verse")
        XCTAssertEqual(first, second)
        XCTAssertNotEqual(first, different)
    }

    func testReminderEffectiveStateDistinguishesDesiredFromActual() {
        XCTAssertEqual(
            ScriptureViewModel.effectiveReminderState(
                for: .scheduled,
                desiredTime: "07:30"
            ),
            .scheduled
        )
        XCTAssertEqual(
            ScriptureViewModel.effectiveReminderState(
                for: .unauthorized,
                desiredTime: "07:30"
            ),
            .blocked("Notifications are not authorized.")
        )
        XCTAssertEqual(
            ScriptureViewModel.effectiveReminderState(
                for: .failed("The system rejected the request."),
                desiredTime: "07:30"
            ),
            .failed("The system rejected the request.")
        )
        XCTAssertEqual(
            ScriptureViewModel.effectiveReminderState(
                for: .disabled,
                desiredTime: "07:30"
            ),
            .failed("The desired reminder time is not valid.")
        )
    }

    func testUserAgentIsVersionDerivedAndNetworkLimitIsBounded() {
        let version = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0.2.0"
        XCTAssertEqual(ScriptureAPI.userAgent, "scripture-ios/\(version)")
        XCTAssertTrue(ScriptureAPI.canAppendResponseByte(currentCount: ScriptureAPI.maxResponseBytes - 1))
        XCTAssertFalse(ScriptureAPI.canAppendResponseByte(currentCount: ScriptureAPI.maxResponseBytes))
    }

    func testClipboardPolicyIsLocalAndExpiring() {
        XCTAssertTrue(ClipboardPolicy.localOnly)
        XCTAssertEqual(ClipboardPolicy.expirationSeconds, 300)
    }

    func testFavoritesStoreSupportsIndividualAndDeleteAllRemoval() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("FavoritesTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let store = FavoritesStore(
            fileURL: directory.appendingPathComponent("favorites.json")
        )
        let first = store.add("John 3:16")
        let second = store.add("John 3:17")
        XCTAssertEqual(Set(first + second), Set(["John 3:16", "John 3:17"]))
        let afterIndividualRemoval = store.remove("John 3:16")
        XCTAssertEqual(afterIndividualRemoval, ["John 3:17"])
        XCTAssertTrue(store.removeAll())
        XCTAssertTrue(store.list().isEmpty)
    }

    func testCardTransferFilenameIsCompact() {
        let name = VerseCardTransfer.filename(for: "John 3:16 — ESV®")
        XCTAssertTrue(name.hasSuffix(".png"))
        XCTAssertTrue(name.contains("John-3-16"))
        XCTAssertFalse(name.contains("ESV®"))
    }

    func testCardSnapshotRejectsStaleTokenPassageFontAndSettings() {
        let token = UUID()
        let passage = makeNumberedPassage(
            anchor: "John 3:16",
            reference: "John 3:16",
            numbers: [16],
            translationName: "English Standard Version"
        )
        let settings = AppSettings(verseFontSize: 28)
        let snapshot = CardGenerationSnapshot(
            token: token,
            passage: passage,
            settings: settings
        )
        XCTAssertTrue(
            ScriptureViewModel.cardSnapshotMatches(
                snapshot,
                token: token,
                passage: passage,
                settings: settings
            )
        )
        XCTAssertFalse(
            ScriptureViewModel.cardSnapshotMatches(
                snapshot,
                token: UUID(),
                passage: passage,
                settings: settings
            )
        )
        XCTAssertFalse(
            ScriptureViewModel.cardSnapshotMatches(
                snapshot,
                token: token,
                passage: nil,
                settings: settings
            )
        )
        var changedFont = settings
        changedFont.verseFontSize = 30
        XCTAssertFalse(
            ScriptureViewModel.cardSnapshotMatches(
                snapshot,
                token: token,
                passage: passage,
                settings: changedFont
            )
        )
        var changedSettings = settings
        changedSettings.translation = .web
        XCTAssertFalse(
            ScriptureViewModel.cardSnapshotMatches(
                snapshot,
                token: token,
                passage: passage,
                settings: changedSettings
            )
        )
    }

    func testPassageCacheRoundTripAndValidation() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScriptureTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let fileURL = directory.appendingPathComponent("passage-cache.json")
        let cache = PassageCache(fileURL: fileURL)
        let passage = Passage(
            anchor: "John 3:16",
            before: "[14] Before",
            focal: "[16] For God so loved",
            after: "[17] The world",
            reference: "John 3:14-18",
            translation: .web,
            translationName: "World English Bible"
        )
        let stored = await cache.store(passage)
        XCTAssertTrue(stored)

        let loaded = await cache.passage(for: " JOHN  3:16 ", translations: [.web])
        XCTAssertEqual(loaded, passage)

        let data = try Data(contentsOf: fileURL)
        let json = String(decoding: data, as: UTF8.self)
        XCTAssertFalse(json.contains("apiKey"))

        try Data("not-json".utf8).write(to: fileURL)
        let invalid = await cache.passage(for: "John 3:16", translations: [.web])
        XCTAssertNil(invalid)
    }

    func testPassageCacheUsesESVKeyGeneration() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScriptureKeyTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let fileURL = directory.appendingPathComponent("passage-cache.json")
        let cache = PassageCache(fileURL: fileURL)
        let firstIdentity = ScriptureAPI.esvKeyIdentity(for: "key-one")
        let secondIdentity = ScriptureAPI.esvKeyIdentity(for: "key-two")
        XCTAssertNotNil(firstIdentity)
        XCTAssertNotEqual(firstIdentity, secondIdentity)

        let passage = Passage(
            anchor: "John 3:16",
            before: "",
            focal: "[16] For God so loved",
            after: "",
            reference: "John 3:16",
            translation: .esv,
            translationName: "English Standard Version"
        )
        let firstStored = await cache.store(passage, esvKeyIdentity: firstIdentity)
        XCTAssertTrue(firstStored)
        let firstLoaded = await cache.passage(
            for: "John 3:16",
            translations: [.esv],
            esvKeyIdentity: firstIdentity
        )
        XCTAssertNotNil(firstLoaded)
        let wrongGeneration = await cache.passage(
            for: "John 3:16",
            translations: [.esv],
            esvKeyIdentity: secondIdentity
        )
        XCTAssertNil(wrongGeneration)
        let secondStored = await cache.store(passage, esvKeyIdentity: secondIdentity)
        XCTAssertTrue(secondStored)
        let oldGeneration = await cache.passage(
            for: "John 3:16",
            translations: [.esv],
            esvKeyIdentity: firstIdentity
        )
        XCTAssertNil(oldGeneration)
        let data = try Data(contentsOf: fileURL)
        let json = String(decoding: data, as: UTF8.self)
        XCTAssertFalse(json.contains("key-one"))
        XCTAssertFalse(json.contains("key-two"))
    }

    func testPassageCachePersistsCanonicalIDsAndDeduplicatesOverlaps() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScriptureOverlapTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let fileURL = directory.appendingPathComponent("passage-cache.json")
        let cache = PassageCache(fileURL: fileURL)
        let identity = try XCTUnwrap(ScriptureAPI.esvKeyIdentity(for: "key-one"))
        let first = makeNumberedPassage(
            anchor: "John 3:14-16",
            reference: "John 3:14-16",
            numbers: [14, 15, 16]
        )
        let second = makeNumberedPassage(
            anchor: "John 3:15-17",
            reference: "John 3:15-17",
            numbers: [15, 16, 17]
        )
        let firstStored = await cache.store(first, esvKeyIdentity: identity)
        let secondStored = await cache.store(second, esvKeyIdentity: identity)
        XCTAssertTrue(firstStored)
        XCTAssertTrue(secondStored)

        let data = try Data(contentsOf: fileURL)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        let entries = try XCTUnwrap(object["entries"] as? [[String: Any]])
        let ids = entries.flatMap { $0["verseIDs"] as? [String] ?? [] }
        XCTAssertEqual(Set(ids), Set([
            "john:3:14", "john:3:15", "john:3:16", "john:3:17"
        ]))
        let unionCount = await cache.verseCount(for: .esv)
        XCTAssertEqual(unionCount, 4)

        let repeated = makeNumberedPassage(
            anchor: "John 3:14-16",
            reference: "John 3:14-16",
            numbers: [14, 15, 16],
            translationName: "Updated ESV"
        )
        let repeatedStored = await cache.store(repeated, esvKeyIdentity: identity)
        let loaded = await cache.passage(
            for: "John 3:14-16",
            translations: [.esv],
            esvKeyIdentity: identity
        )
        XCTAssertTrue(repeatedStored)
        XCTAssertEqual(loaded, repeated)
        let repeatedCount = await cache.verseCount(for: .esv)
        XCTAssertEqual(repeatedCount, 4)
    }

    func testPassageCacheRejectsESVWithoutReliableVerseIDs() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScriptureReliabilityTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let cache = PassageCache(
            fileURL: directory.appendingPathComponent("passage-cache.json")
        )
        let identity = try XCTUnwrap(ScriptureAPI.esvKeyIdentity(for: "key-one"))
        let passage = makeNumberedPassage(
            anchor: "John 3:16",
            reference: "John 3:16",
            numbers: [],
            translationName: "English Standard Version"
        )
        let stored = await cache.store(passage, esvKeyIdentity: identity)
        let loaded = await cache.passage(
            for: "John 3:16",
            translations: [.esv],
            esvKeyIdentity: identity
        )
        XCTAssertFalse(stored)
        XCTAssertNil(loaded)
    }

    func testPassageCacheEnforcesShortBookLimit() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScriptureShortBookTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let cache = PassageCache(
            fileURL: directory.appendingPathComponent("passage-cache.json")
        )
        let identity = try XCTUnwrap(ScriptureAPI.esvKeyIdentity(for: "key-one"))
        let limit = PassageCache.maximumVerses(forBook: "2 John")
        XCTAssertEqual(limit, 6)
        for verse in 1...(limit + 1) {
            let passage = makeNumberedPassage(
                anchor: "2 John 1:\(verse)",
                reference: "2 John 1:\(verse)",
                numbers: [verse]
            )
            let stored = await cache.store(passage, esvKeyIdentity: identity)
            XCTAssertTrue(stored)
        }
        let evicted = await cache.passage(
            for: "2 John 1:1",
            translations: [.esv],
            esvKeyIdentity: identity
        )
        let newest = await cache.passage(
            for: "2 John 1:7",
            translations: [.esv],
            esvKeyIdentity: identity
        )
        XCTAssertNil(evicted)
        XCTAssertNotNil(newest)
    }

    func testPassageCacheEnforcesProviderVerseTotal() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScriptureProviderLimitTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let fileURL = directory.appendingPathComponent("passage-cache.json")
        let identity = try XCTUnwrap(ScriptureAPI.esvKeyIdentity(for: "key-one"))
        var entries: [[String: Any]] = []
        for verse in 1...(PassageCache.maximumVersesPerProvider + 1) {
            let reference = "Genesis 1:\(verse)"
            let passage: [String: Any] = [
                "anchor": reference,
                "before": "",
                "focal": "[\(verse)] Verse",
                "after": "",
                "reference": reference,
                "translation": Translation.esv.rawValue,
                "translationName": "English Standard Version"
            ]
            entries.append([
                "passage": passage,
                "providerIdentity": identity,
                "verseIDs": ["genesis:1:\(verse)"]
            ])
        }
        let envelope: [String: Any] = ["version": 3, "entries": entries]
        let data = try JSONSerialization.data(withJSONObject: envelope)
        try data.write(to: fileURL)
        let cache = PassageCache(fileURL: fileURL)
        let count = await cache.verseCount(for: .esv)
        let persistedData = try Data(contentsOf: fileURL)
        let persistedObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: persistedData) as? [String: Any]
        )
        let persistedEntries = try XCTUnwrap(
            persistedObject["entries"] as? [[String: Any]]
        )
        let evicted = await cache.passage(
            for: "Genesis 1:1",
            translations: [.esv],
            esvKeyIdentity: identity
        )
        let newest = await cache.passage(
            for: "Genesis 1:\(PassageCache.maximumVersesPerProvider + 1)",
            translations: [.esv],
            esvKeyIdentity: identity
        )
        XCTAssertEqual(count, PassageCache.maximumVersesPerProvider)
        XCTAssertEqual(persistedEntries.count, PassageCache.maximumVersesPerProvider)
        XCTAssertNil(evicted)
        XCTAssertNotNil(newest)
    }

    private func makeNumberedPassage(
        anchor: String,
        reference: String,
        numbers: [Int],
        translationName: String = "English Standard Version"
    ) -> Passage {
        let focal = numbers.isEmpty
            ? "Passage text"
            : numbers.map { "[\($0)] Verse \($0)" }.joined(separator: " ")
        return Passage(
            anchor: anchor,
            before: "",
            focal: focal,
            after: "",
            reference: reference,
            translation: .esv,
            translationName: translationName
        )
    }

    func testTopicReferencesStayInsideTheDeck() {
        for topic in ScriptureTopic.allCases {
            let references = ScriptureReference.references(for: topic)
            XCTAssertFalse(references.isEmpty)
            XCTAssertTrue(references.allSatisfy { ScriptureReference.deck.contains($0) })
        }
        XCTAssertTrue(ScriptureReference.books.allSatisfy { book in
            !ScriptureReference.references(book: book, topic: .all).isEmpty
        })
    }
}
