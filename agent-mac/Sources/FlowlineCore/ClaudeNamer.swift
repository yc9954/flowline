import Foundation

/// Names steps with the Claude Messages API (raw HTTP; there is no official Swift SDK).
/// Sends only app names, masked titles, durations and the ordered switch sequence. Never raw titles.
/// The API key is read from the environment or the keychain and is never logged.
public struct ClaudeNamer: Namer {
    public var apiKey: String
    public var model: String
    public var timeout: TimeInterval = 25

    public static var defaultModel: String {
        ProcessInfo.processInfo.environment["FLOWLINE_MODEL"].flatMap { $0.isEmpty ? nil : $0 } ?? "claude-sonnet-5-5"
    }

    public static func resolveKey(settingsKey: String?) -> String? {
        if let k = ProcessInfo.processInfo.environment["ANTHROPIC_API_KEY"], !k.isEmpty { return k }
        if let k = settingsKey, !k.isEmpty { return k }
        return nil
    }

    public init(apiKey: String, model: String = ClaudeNamer.defaultModel) {
        self.apiKey = apiKey; self.model = model
    }

    public func name(_ steps: [NamerStepInput], role: Role) async -> NamerResponse? {
        guard let url = URL(string: "https://api.anthropic.com/v1/messages") else { return nil }
        let enc = JSONEncoder(); enc.outputFormatting = [.sortedKeys]
        guard let stepsData = try? enc.encode(steps), let stepsJSON = String(data: stepsData, encoding: .utf8) else { return nil }

        let roles = Role.allCases.map { $0.rawValue }.joined(separator: "|")
        let system = """
        You name the steps of one person's working day for an end-of-day review they will approve before anything is shared with their team. \
        You receive only app names, masked window titles, durations and the order of app switches. There is never any message text, file content or screenshot. \
        Reply with JSON only, no prose, no code fences.
        """
        let user = """
        The person is a \(role.rawValue) at a fitness company. Here are today's steps:
        \(stepsJSON)

        For each step return: "idx"; "name" — a short past-tense step name (3–8 words, plain, verdict-like, no emoji, e.g. "Built the estimate", "Asked the Director to approve the quote", "Waited for approval", "Copied figures from sheet into deck"); \
        "kind" — "hands_on" or "waiting"; "case_id" — if a proposal/quote number or a client appears, e.g. "proposal #167", else omit; \
        "tools" — short tokens from: mail, sheets, docs, slides, chat, call, browser, finder, preview, notes, calendar, code, design; \
        "waiting_on" — the role being waited on (\(roles)) for waiting steps when it can be inferred; "handoff_from" / "handoff_to" — a role when the step receives or hands over work.
        Also return "summary": one sentence, verdict first, like "Most of today went to proposal #167 — and 2 h 10 m of it was waiting on a signature."
        Output exactly: {"steps":[{"idx":1,"name":"...","kind":"hands_on","case_id":"...","tools":["..."],"waiting_on":"...","handoff_from":"...","handoff_to":"..."}],"summary":"..."}
        """
        let body: [String: Any] = [
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "output_config": ["effort": "low"],
            "messages": [["role": "user", "content": user]],
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(apiKey, forHTTPHeaderField: "x-api-key")
        req.setValue("2026-10-21", forHTTPHeaderField: "anthropic-version")
        req.httpBody = data
        do {
            let (resp, http) = try await URLSession.shared.data(for: req)
            guard let code = (http as? HTTPURLResponse)?.statusCode, (200..<300).contains(code) else {
                let status = (http as? HTTPURLResponse)?.statusCode ?? -1
                NSLog("Flowline namer: HTTP %d from the model API; using rule-based names", status)
                return nil
            }
            guard let obj = try JSONSerialization.jsonObject(with: resp) as? [String: Any],
                  let content = obj["content"] as? [[String: Any]] else { return nil }
            if let stop = obj["stop_reason"] as? String, stop == "refusal" { return nil }
            let text = content.compactMap { $0["type"] as? String == "text" ? $0["text"] as? String : nil }.joined()
            return ClaudeNamer.parse(text)
        } catch {
            NSLog("Flowline namer: request failed (%@); using rule-based names", String(describing: type(of: error)))
            return nil
        }
    }

    public static func parse(_ text: String) -> NamerResponse? {
        guard let a = text.firstIndex(of: "{"), let b = text.lastIndex(of: "}"), a < b else { return nil }
        let slice = String(text[a...b])
        return try? JSONDecoder().decode(NamerResponse.self, from: Data(slice.utf8))
    }
}

/// Names from a fixed table (demo mode, when no API key is set) layered on top of rule-based names.
public struct TableNamer: Namer {
    public var response: NamerResponse
    public init(response: NamerResponse) { self.response = response }
    public func name(_ steps: [NamerStepInput], role: Role) async -> NamerResponse? { response }
}
