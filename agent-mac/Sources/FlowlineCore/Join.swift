import Foundation

// Joining a company (track G1): POST {api}/api/invites/{code}/claim {device} → JoinClaim.
// The Mac app stores the answer as its identity; nothing here depends on a board name switch.

public struct JoinClaim: Codable, Equatable {
    public var board_id: String
    public var board_name: String
    public var person_id: String
    public var name: String
    public var role: Role

    public init(board_id: String, board_name: String, person_id: String, name: String, role: Role) {
        self.board_id = board_id; self.board_name = board_name; self.person_id = person_id; self.name = name; self.role = role
    }

    /// Tolerant of a sparse answer: `board_name` falls back to `board_id`, `name` to `person_id`, an unknown role to PM.
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        guard let b = Flex.string(c, "board_id"), !b.isEmpty, let p = Flex.string(c, "person_id"), !p.isEmpty else {
            throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "claim without board_id/person_id"))
        }
        board_id = b
        person_id = p
        board_name = Flex.string(c, "board_name").flatMap { $0.isEmpty ? nil : $0 } ?? b
        name = Flex.string(c, "name").flatMap { $0.isEmpty ? nil : $0 } ?? p
        role = Flex.string(c, "role").flatMap(Role.init(rawValue:)) ?? .PM
    }
}

public struct JoinRequest: Encodable, Equatable {
    public var device: String
    public init(device: String) { self.device = device }
}

/// `flowline://join?api=http://host:8787&code=ABC123` — what an invite mail or the board's "Join" button opens.
public struct JoinLink: Equatable {
    public var api: String?
    public var code: String?

    public init(api: String?, code: String?) { self.api = api; self.code = code }

    public static func parse(_ url: URL) -> JoinLink? {
        guard url.scheme?.lowercased() == "flowline" else { return nil }
        let host = (url.host ?? "").lowercased()
        let path = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")).lowercased()
        guard host == "join" || path == "join" else { return nil }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func q(_ n: String) -> String? { items.first { $0.name == n }?.value.flatMap { $0.isEmpty ? nil : $0 } }
        var api = q("api")
        if let a = api, !a.contains("://") { api = "http://" + a }
        return JoinLink(api: api?.trimmingCharacters(in: CharacterSet(charactersIn: "/")), code: q("code")?.trimmingCharacters(in: .whitespaces))
    }
}
