import XCTest
@testable import FlowlineCore

final class DecodingTests: XCTestCase {
    /// Exact sample from the live executor: floats, extra keys, empty checks.
    let sample = """
    {"id":"run-20261109-041141-02b6","skill_id":"fill_deck_from_sheet","target":"desk1","title":"Filling proposal #172 pricing from your sheet","suggestion_id":"sug-1","status":"running","started_at":"2026-11-09T04:11:41.100+09:00","elapsed_s":0.52,"steps":[{"n":1,"label":"READ THE SHEET","detail":"Reading the pricing sheet","status":"now","at_s":0.5},{"n":2,"label":"FILL THE DECK","detail":"","status":"pending","progress":[0,4]},{"n":3,"label":"CHECK THE TOTAL","detail":"","status":"pending"},{"n":4,"label":"LEAVE IT FOR YOU","detail":"","status":"pending"}],"checks":[],"model":"claude-sonnet-5-5","actions":[]}
    """

    func testLiveRunDecodes() throws {
        let r = try JSONDecoder().decode(Run.self, from: Data(sample.utf8))
        XCTAssertEqual(r.id, "run-20261109-041141-02b6")
        XCTAssertEqual(r.target, "desk1")
        XCTAssertEqual(r.title, "Filling proposal #172 pricing from your sheet")
        XCTAssertEqual(r.status, .running)
        XCTAssertEqual(r.elapsed_s, 0.52, accuracy: 1e-9)
        XCTAssertEqual(r.steps.count, 4)
        XCTAssertEqual(r.steps[0].status, .now)
        XCTAssertEqual(r.steps[0].at_s ?? -1, 0.5, accuracy: 1e-9)
        XCTAssertEqual(r.steps[0].atSeconds, 1)
        XCTAssertEqual(r.steps[1].progress, [0, 4])
        XCTAssertNil(r.steps[2].progress)
        XCTAssertTrue(r.checks.isEmpty)
    }

    func testRunMissingArraysAndUnknownStatus() throws {
        let json = """
        {"id":"r1","skill_id":"s","target":"mac","status":"queued","started_at":"x","elapsed_s":3,"finished_at":null,"error":null,"steps":[{"n":"1","label":"A","detail":"d","status":"weird","progress":[1.0,4.0],"at_s":2}]}
        """
        let r = try JSONDecoder().decode(Run.self, from: Data(json.utf8))
        XCTAssertEqual(r.status, .running)
        XCTAssertEqual(r.elapsed_s, 3)
        XCTAssertTrue(r.checks.isEmpty)
        XCTAssertNil(r.title)
        XCTAssertEqual(r.steps[0].n, 1)
        XCTAssertEqual(r.steps[0].status, .pending)
        XCTAssertEqual(r.steps[0].progress, [1, 4])
        XCTAssertEqual(r.steps[0].atSeconds, 2)
    }

    func testSuggestionTolerant() throws {
        let json = """
        [{"id":"sug-1","person_id":"pm-1","skill_id":"fill_deck_from_sheet","title":"Fill?","body":"b","why_now":"w","count_last_week":11.0,"minutes_each":22,"estimate_s":50.4,"plan_id":"plan-2","status":"offered","accept_rate":{"yes":3,"no":1},"created_at":"2026-11-09T04:00:00+09:00","responded_at":null,"run_id":null}]
        """
        let list = try JSONDecoder().decode([Suggestion].self, from: Data(json.utf8))
        XCTAssertEqual(list.count, 1)
        XCTAssertEqual(list[0].count_last_week, 11)
        XCTAssertEqual(list[0].estimate_s, 50)
        XCTAssertEqual(list[0].status, .offered)
        let odd = try JSONDecoder().decode(Suggestion.self, from: Data(#"{"id":"x","status":"snoozed"}"#.utf8))
        XCTAssertEqual(odd.status, .never)
    }
}
