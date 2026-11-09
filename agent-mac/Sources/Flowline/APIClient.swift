import Foundation
import FlowlineCore

enum APIError: LocalizedError {
    case badURL
    case http(Int, String)
    case transport(String)
    var errorDescription: String? {
        switch self {
        case .badURL: return "The board address is not a valid URL."
        case .http(let c, let body): return "The board answered \(c)\(body.isEmpty ? "" : ": \(body.prefix(140))")."
        case .transport(let m): return "Could not reach the board (\(m))."
        }
    }
}

struct APIClient {
    var base: String

    private func url(_ path: String) throws -> URL {
        guard let u = URL(string: base.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + path) else { throw APIError.badURL }
        return u
    }

    private func send<T: Decodable>(_ method: String, _ path: String, body: Encodable? = nil, timeout: TimeInterval = 8, as: T.Type) async throws -> T {
        let data = try await raw(method, path, body: body, timeout: timeout)
        return try JSONDecoder().decode(T.self, from: data)
    }

    @discardableResult
    private func raw(_ method: String, _ path: String, body: Encodable? = nil, timeout: TimeInterval = 8) async throws -> Data {
        var req = URLRequest(url: try url(path))
        req.httpMethod = method
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            guard (200..<300).contains(code) else { throw APIError.http(code, String(data: data, encoding: .utf8) ?? "") }
            return data
        } catch let e as APIError { throw e }
        catch { throw APIError.transport((error as NSError).localizedDescription) }
    }

    struct Accepted: Decodable { var id: String; var accepted: Bool }

    func postRecord(_ r: Record) async throws -> Accepted {
        try await send("POST", "/api/boards/\(r.board_id)/records", body: r, as: Accepted.self)
    }

    func deleteRecord(board: String, id: String) async throws {
        try await raw("DELETE", "/api/boards/\(board)/records/\(id)")
    }

    func suggestions(person: String) async throws -> [Suggestion] {
        let data = try await raw("GET", "/api/people/\(person)/suggestions")
        do { return try JSONDecoder().decode([Suggestion].self, from: data) }
        catch {
            struct Wrapped: Decodable { var suggestions: [Suggestion] }
            if let w = try? JSONDecoder().decode(Wrapped.self, from: data) { return w.suggestions }
            NSLog("Flowline suggestions: cannot decode (%@)", "\(error)")
            return []
        }
    }

    struct Respond: Encodable { var answer: String }
    func respond(id: String, answer: SuggestionAnswer) async throws {
        try await raw("POST", "/api/suggestions/\(id)/respond", body: Respond(answer: answer.rawValue))
    }

    struct RunRequest: Encodable { var suggestion_id: String; var skill_id: String; var target: String; var person_id: String; var inputs: [String: String] }
    /// `target` defaults to "mac" (the person's own machine); `defaults write co.sweetspot.flowline run_target desk1`
    /// makes the executor work on a Linux desk while the panel shows here (the demo). The API adds the board block.
    func createRun(_ s: Suggestion, target: String, person: String) async throws -> Run {
        // The executor may open the deck before answering; give it a minute.
        return try await send("POST", "/api/runs", body: RunRequest(suggestion_id: s.id, skill_id: s.skill_id, target: target, person_id: person, inputs: [:]), timeout: 60, as: Run.self)
    }

    /// Join a company: `POST {api}/api/invites/{code}/claim {device}` (track G1) → the identity to store.
    static func claimInvite(api: String, code: String, device: String) async throws -> JoinClaim {
        let base = api.trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
        guard !base.isEmpty, URL(string: base) != nil else { throw APIError.badURL }
        let c = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !c.isEmpty, let encoded = c.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else { throw APIError.badURL }
        return try await APIClient(base: base).send("POST", "/api/invites/\(encoded)/claim", body: JoinRequest(device: device), timeout: 15, as: JoinClaim.self)
    }

    func run(id: String) async throws -> Run { try await send("GET", "/api/runs/\(id)", as: Run.self) }

    func stop(id: String) async throws { try await raw("POST", "/api/runs/\(id)/stop") }
}

struct AnyEncodable: Encodable {
    let value: Encodable
    init(_ v: Encodable) { value = v }
    func encode(to encoder: Encoder) throws { try value.encode(to: encoder) }
}
