import XCTest
import CryptoKit
@testable import FlowlineCore

final class CanonicalTests: XCTestCase {

    /// One fixed record. The expected hash was computed in Python with
    /// `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` → sha256 hex
    /// (see scripts/hash_check.py, which recomputes it from the same JSON).
    static let fixedRecord = Record(
        id: "1106-0412", board_id: "northwind", person_id: "pm-1", role: .PM, date: "2026-11-06",
        covers: Covers(start: "2026-11-06T09:02:00+09:00", end: "2026-11-06T15:18:00+09:00"),
        steps: [
            RecordStep(idx: 1, start: "2026-11-06T09:02:00+09:00", end: "2026-11-06T09:20:00+09:00",
                       name: "Read the client brief for #167", kind: .hands_on, case_id: "proposal #167",
                       tools: ["mail", "docs"], handoff_from: .Sales),
            RecordStep(idx: 2, start: "2026-11-06T10:52:00+09:00", end: "2026-11-06T13:02:00+09:00",
                       name: "Waited for approval", kind: .waiting, case_id: "proposal #167", tools: [],
                       handoff_to: .Director, waiting_on: .Director),
            RecordStep(idx: 3, start: "2026-11-06T13:02:00+09:00", end: "2026-11-06T13:24:00+09:00",
                       name: "Copied figures from sheet into deck — “Investment” → déck", kind: .hands_on,
                       case_id: "proposal #167", tools: ["sheets", "slides"], repeats: 3),
        ],
        kept_private: 3, hands_on_min: 40, waiting_min: 130, approved_at: "2026-11-06T18:04:31+09:00"
    )

    static let expectedCanonical = #"{"approved_at":"2026-11-06T18:04:31+09:00","board_id":"northwind","covers":{"end":"2026-11-06T15:18:00+09:00","start":"2026-11-06T09:02:00+09:00"},"date":"2026-11-06","hands_on_min":40,"id":"1106-0412","kept_private":3,"person_id":"pm-1","role":"PM","steps":[{"case_id":"proposal #167","end":"2026-11-06T09:20:00+09:00","handoff_from":"Sales","idx":1,"kind":"hands_on","name":"Read the client brief for #167","start":"2026-11-06T09:02:00+09:00","tools":["mail","docs"]},{"case_id":"proposal #167","end":"2026-11-06T13:02:00+09:00","handoff_to":"Director","idx":2,"kind":"waiting","name":"Waited for approval","start":"2026-11-06T10:52:00+09:00","tools":[],"waiting_on":"Director"},{"case_id":"proposal #167","end":"2026-11-06T13:24:00+09:00","idx":3,"kind":"hands_on","name":"Copied figures from sheet into deck — “Investment” → déck","repeats":3,"start":"2026-11-06T13:02:00+09:00","tools":["sheets","slides"]}],"waiting_min":130}"#

    // python3 -c 'import json,hashlib; print(hashlib.sha256(json.dumps(json.loads(open("c.json").read()),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest())'
    static let expectedHash = "131600388d035f267a4a896218a972998ea53814aa5f7b5a912623a701fa10f6"

    func testCanonicalBytesMatchPython() throws {
        let bytes = try Canonical.bytes(for: Self.fixedRecord)
        XCTAssertEqual(String(data: bytes, encoding: .utf8), Self.expectedCanonical)
    }

    func testHashMatchesPython() throws {
        XCTAssertEqual(try Canonical.hash(for: Self.fixedRecord), Self.expectedHash)
    }

    func testSealAndVerify() throws {
        let signer = Signer(key: Curve25519.Signing.PrivateKey())
        let sealed = try signer.seal(Self.fixedRecord)
        XCTAssertEqual(sealed.hash, Self.expectedHash)
        XCTAssertTrue(Signer.verify(sealed))
        var tampered = sealed
        tampered.hands_on_min = 41
        XCTAssertFalse(Signer.verify(tampered))
    }

    func testStringEscapingLikePython() {
        var out = ""
        JSON.writeString("a\"b\\c\nd\te\u{01}f/g한", into: &out)
        XCTAssertEqual(out, #""a\"b\\c\nd\te\u0001f/g한""#)
    }

    func testKeyOrderIsCodePoint() {
        let j = JSON.object(["b": .int(1), "a": .int(2), "Z": .int(3), "_": .int(4)])
        XCTAssertEqual(j.canonical, #"{"Z":3,"_":4,"a":2,"b":1}"#)
    }
}
