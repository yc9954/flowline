import XCTest
@testable import FlowlineCore

final class CompilerTests: XCTestCase {

    func loadDemo() throws -> [Event] {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Flowline/Resources/demo-day.jsonl")
        let text = try String(contentsOf: url, encoding: .utf8)
        let dec = JSONDecoder()
        return try text.split(separator: "\n").map { try dec.decode(Event.self, from: Data($0.utf8)) }
    }

    func testDemoDayCompilesToStoryboard() async throws {
        let events = try loadDemo()
        XCTAssertGreaterThan(events.count, 1000)
        let cfg = CompilerConfig(person_id: "pm-1", role: .PM, board_id: "northwind", date: "2026-11-06")
        let history = [StepHistory(date: "2026-11-03", signatures: ["sheets→slides"]),
                       StepHistory(date: "2026-11-05", signatures: ["sheets→slides"])]
        let r = await Compiler.compile(events: events, config: cfg, history: history, namer: nil)
        let d = r.draft
        for s in d.steps { print(s.idx, Fmt.clock(s.start), Fmt.clock(s.end), s.kind, s.tools, s.name, s.case_id ?? "-", s.repeats ?? 0) }
        print(d.left_out.map { "\($0.kind) \($0.minutes ?? -1) \($0.action)" })
        print(d.summary)

        XCTAssertEqual(d.steps.count, 7)
        XCTAssertEqual(d.steps.map(\.kind), [.hands_on, .hands_on, .hands_on, .waiting, .hands_on, .hands_on, .hands_on])
        XCTAssertEqual(d.steps[0].tools, ["mail", "docs"])
        XCTAssertEqual(d.steps[1].tools, ["sheets"])
        XCTAssertEqual(d.steps[3].minutes, 130)
        XCTAssertEqual(d.steps[3].waiting_on, .Director)
        XCTAssertEqual(d.steps[4].tools, ["sheets", "slides"])
        XCTAssertEqual(d.steps[4].repeats, 3)
        XCTAssertEqual(Set(d.steps[5].tools), Set(["slides", "chat", "call"]))
        XCTAssertEqual(d.handsOnMinutes, 246)
        XCTAssertEqual(d.waitingMinutes, 130)
        XCTAssertEqual(d.left_out.count, 3)
        XCTAssertEqual(d.left_out[0].kind, .personal_chat); XCTAssertEqual(d.left_out[0].minutes, 14)
        XCTAssertEqual(d.left_out[1].kind, .banking); XCTAssertEqual(d.left_out[1].minutes, 6)
        XCTAssertEqual(d.left_out[2].kind, .name_in_filename)
        XCTAssertTrue(d.summary.hasPrefix("Most of today went to proposal #167"))
    }

    func testPrivacy() {
        XCTAssertTrue(Privacy.isDeniedApp("Messages"))
        XCTAssertTrue(Privacy.isDeniedApp("KakaoTalk"))
        XCTAssertFalse(Privacy.isDeniedApp("Slack"))
        XCTAssertTrue(Privacy.isDeniedHost("obank.kbstar.com"))
        XCTAssertTrue(Privacy.isDeniedHost("secure.chase.com"))
        XCTAssertTrue(Privacy.isDeniedHost("mychart.example.org"))
        XCTAssertFalse(Privacy.isDeniedHost("docs.google.com"))
        XCTAssertEqual(Privacy.maskNames("Kim Minji contract.pdf").text, "client file")
        XCTAssertEqual(Privacy.maskNames("John Smith resume.pdf").text, "client file")
        XCTAssertFalse(Privacy.maskNames("pricing-sheet · Proposal #167 - Google Sheets").hadName)
        XCTAssertFalse(Privacy.maskNames("Re: Proposal #167 — client brief from Sales").hadName)
    }
}
