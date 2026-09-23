import XCTest
@testable import Scripture

final class ScriptureReferenceTests: XCTestCase {
    func testRangeQueryExpandsAnchor() {
        XCTAssertEqual(ScriptureReference.rangeQuery("John 3:16"), "John 3:14-18")
        XCTAssertEqual(ScriptureReference.rangeQuery("Genesis 1:1"), "Genesis 1:1-3")
    }

    func testFocalVerse() {
        XCTAssertEqual(ScriptureReference.focalVerse("John 3:16"), 16)
        XCTAssertNil(ScriptureReference.focalVerse("John 3"))
    }

    func testESVCleaningRetainsVerseMarkers() {
        let cleaned = ScriptureReference.cleanESVText(
            "John 3:14-18\n[14] And as Moses lifted up\n(ESV)",
            reference: "John 3:14-18"
        )
        XCTAssertTrue(cleaned.contains("[14]"))
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
}
