import XCTest
@testable import FlowlineCore

/// The join contract (track G1): POST /api/invites/{code}/claim → {board_id, board_name, person_id, name, role}.
final class JoinTests: XCTestCase {
    func testClaimDecodesTheContractShape() throws {
        let json = #"{"board_id":"acme","board_name":"Acme Tooling","person_id":"ops-7","name":"Jordan Blake","role":"Ops"}"#
        let c = try JSONDecoder().decode(JoinClaim.self, from: Data(json.utf8))
        XCTAssertEqual(c, JoinClaim(board_id: "acme", board_name: "Acme Tooling", person_id: "ops-7", name: "Jordan Blake", role: .Ops))
    }

    func testClaimToleratesSparseAnswersButNeedsIds() throws {
        let sparse = try JSONDecoder().decode(JoinClaim.self, from: Data(#"{"board_id":"northwind","person_id":"pm-1","role":"Wizard"}"#.utf8))
        XCTAssertEqual(sparse.board_name, "northwind")   // no name switch: the id itself, until the API names it
        XCTAssertEqual(sparse.name, "pm-1")
        XCTAssertEqual(sparse.role, .PM)
        XCTAssertThrowsError(try JSONDecoder().decode(JoinClaim.self, from: Data(#"{"board_name":"x"}"#.utf8)))
    }

    func testRequestBodyIsTheDevice() throws {
        let data = try JSONEncoder().encode(JoinRequest(device: "Dana’s MacBook"))
        XCTAssertEqual(try JSONSerialization.jsonObject(with: data) as? [String: String], ["device": "Dana’s MacBook"])
    }

    func testJoinLinkParsing() {
        let l = JoinLink.parse(URL(string: "flowline://join?api=http://board.acme.example:8787&code=ACME-OPS")!)
        XCTAssertEqual(l, JoinLink(api: "http://board.acme.example:8787", code: "ACME-OPS"))
        XCTAssertEqual(JoinLink.parse(URL(string: "flowline:///join?api=localhost:8787/&code=x")!), JoinLink(api: "http://localhost:8787", code: "x"))
        XCTAssertEqual(JoinLink.parse(URL(string: "FLOWLINE://JOIN?code=only")!), JoinLink(api: nil, code: "only"))
        XCTAssertNil(JoinLink.parse(URL(string: "flowline://other?code=x")!))
        XCTAssertNil(JoinLink.parse(URL(string: "https://example.com/join?code=x")!))
    }
}
