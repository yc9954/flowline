import Foundation

// Shared shapes from /SCHEMA.md sections 1, 2 and 11. Keys are snake_case on the wire, so the
// Swift property names are kept identical to the schema to avoid a mapping layer.

public enum Role: String, Codable, CaseIterable {
    case Client, Sales, PM, Design, Finance, Director, Legal, Trainer, BranchMgr, Ops, CEO
}

public enum ISO {
    static let withOffset: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    static let withFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    public static func string(_ d: Date, tz: TimeZone = .current) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = tz
        return f.string(from: d)
    }
    public static func date(_ s: String) -> Date? {
        withOffset.date(from: s) ?? withFraction.date(from: s)
    }
    public static func day(_ d: Date, tz: TimeZone = .current) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = tz
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }
}

// MARK: - Section 1: on-device

public struct Event: Codable, Equatable {
    public var ts: String
    public var app: String
    public var title_hash: String
    public var title_masked: String?
    public var file_hint: String?
    public var idle_s: Int
    public var url_host: String?

    public init(ts: String, app: String, title_hash: String, title_masked: String? = nil,
                file_hint: String? = nil, idle_s: Int, url_host: String? = nil) {
        self.ts = ts; self.app = app; self.title_hash = title_hash; self.title_masked = title_masked
        self.file_hint = file_hint; self.idle_s = idle_s; self.url_host = url_host
    }

    public var date: Date { ISO.date(ts) ?? Date(timeIntervalSince1970: 0) }
}

public enum StepKind: String, Codable { case hands_on, waiting }

public struct DraftStep: Codable, Equatable, Identifiable {
    public var idx: Int
    public var start: String
    public var end: String
    public var name: String
    public var kind: StepKind
    public var case_id: String?
    public var tools: [String]
    public var handoff_from: Role?
    public var handoff_to: Role?
    public var waiting_on: Role?
    public var repeats: Int?
    public var share: Bool

    public var id: Int { idx }

    public init(idx: Int, start: String, end: String, name: String, kind: StepKind, case_id: String? = nil,
                tools: [String], handoff_from: Role? = nil, handoff_to: Role? = nil, waiting_on: Role? = nil,
                repeats: Int? = nil, share: Bool = true) {
        self.idx = idx; self.start = start; self.end = end; self.name = name; self.kind = kind
        self.case_id = case_id; self.tools = tools; self.handoff_from = handoff_from; self.handoff_to = handoff_to
        self.waiting_on = waiting_on; self.repeats = repeats; self.share = share
    }

    public var startDate: Date { ISO.date(start) ?? Date() }
    public var endDate: Date { ISO.date(end) ?? Date() }
    public var minutes: Int { max(0, Int((endDate.timeIntervalSince(startDate) / 60).rounded())) }
}

public enum LeftOutKind: String, Codable { case personal_chat, banking, name_in_filename, other }
public enum LeftOutAction: String, Codable { case counted_as_away, removed, renamed }

public struct LeftOut: Codable, Equatable, Identifiable {
    public var kind: LeftOutKind
    public var label: String
    public var minutes: Int?
    public var action: LeftOutAction
    public var id: String { kind.rawValue }
    public init(kind: LeftOutKind, label: String, minutes: Int?, action: LeftOutAction) {
        self.kind = kind; self.label = label; self.minutes = minutes; self.action = action
    }
}

public struct DraftDay: Codable, Equatable {
    public var person_id: String
    public var role: Role
    public var date: String
    public var board_id: String
    public var steps: [DraftStep]
    public var left_out: [LeftOut]
    public var summary: String

    public init(person_id: String, role: Role, date: String, board_id: String, steps: [DraftStep],
                left_out: [LeftOut], summary: String) {
        self.person_id = person_id; self.role = role; self.date = date; self.board_id = board_id
        self.steps = steps; self.left_out = left_out; self.summary = summary
    }

    public var handsOnMinutes: Int { steps.filter { $0.kind == .hands_on }.reduce(0) { $0 + $1.minutes } }
    public var waitingMinutes: Int { steps.filter { $0.kind == .waiting }.reduce(0) { $0 + $1.minutes } }
    public var repeatMinutes: Int { steps.filter { ($0.repeats ?? 0) >= 2 }.reduce(0) { $0 + $1.minutes } }
}

// MARK: - Section 2: approved record

public struct Covers: Codable, Equatable {
    public var start: String
    public var end: String
    public init(start: String, end: String) { self.start = start; self.end = end }
}

public struct RecordStep: Codable, Equatable {
    public var idx: Int
    public var start: String
    public var end: String
    public var name: String
    public var kind: StepKind
    public var case_id: String?
    public var tools: [String]
    public var handoff_from: Role?
    public var handoff_to: Role?
    public var waiting_on: Role?
    public var repeats: Int?

    public init(idx: Int, start: String, end: String, name: String, kind: StepKind, case_id: String? = nil,
                tools: [String], handoff_from: Role? = nil, handoff_to: Role? = nil, waiting_on: Role? = nil,
                repeats: Int? = nil) {
        self.idx = idx; self.start = start; self.end = end; self.name = name; self.kind = kind
        self.case_id = case_id; self.tools = tools; self.handoff_from = handoff_from; self.handoff_to = handoff_to
        self.waiting_on = waiting_on; self.repeats = repeats
    }

    public init(_ d: DraftStep, idx: Int) {
        self.init(idx: idx, start: d.start, end: d.end, name: d.name, kind: d.kind, case_id: d.case_id,
                  tools: d.tools, handoff_from: d.handoff_from, handoff_to: d.handoff_to,
                  waiting_on: d.waiting_on, repeats: d.repeats)
    }

    public var minutes: Int {
        guard let s = ISO.date(start), let e = ISO.date(end) else { return 0 }
        return max(0, Int((e.timeIntervalSince(s) / 60).rounded()))
    }
}

public struct Record: Codable, Equatable {
    public var id: String
    public var board_id: String
    public var person_id: String
    public var role: Role
    public var date: String
    public var covers: Covers
    public var steps: [RecordStep]
    public var kept_private: Int
    public var hands_on_min: Int
    public var waiting_min: Int
    public var approved_at: String
    public var hash: String
    public var pubkey: String
    public var sig: String

    public init(id: String, board_id: String, person_id: String, role: Role, date: String, covers: Covers,
                steps: [RecordStep], kept_private: Int, hands_on_min: Int, waiting_min: Int, approved_at: String,
                hash: String = "", pubkey: String = "", sig: String = "") {
        self.id = id; self.board_id = board_id; self.person_id = person_id; self.role = role; self.date = date
        self.covers = covers; self.steps = steps; self.kept_private = kept_private; self.hands_on_min = hands_on_min
        self.waiting_min = waiting_min; self.approved_at = approved_at; self.hash = hash; self.pubkey = pubkey
        self.sig = sig
    }
}

// MARK: - Section 11: suggestions and runs
// Decoders here are tolerant: the live API/executor send numbers as floats, add keys the schema does not list,
// and omit arrays at the start of a run. Unknown enum values map to a safe default; extra keys are ignored.

enum Flex {
    static func number(_ c: KeyedDecodingContainer<AnyKey>, _ key: String) -> Double? {
        guard let k = AnyKey(stringValue: key) else { return nil }
        if let d = try? c.decodeIfPresent(Double.self, forKey: k) { return d }
        if let i = try? c.decodeIfPresent(Int.self, forKey: k) { return Double(i) }
        if let s = try? c.decodeIfPresent(String.self, forKey: k) { return Double(s) }
        return nil
    }
    static func string(_ c: KeyedDecodingContainer<AnyKey>, _ key: String) -> String? {
        guard let k = AnyKey(stringValue: key) else { return nil }
        return try? c.decodeIfPresent(String.self, forKey: k)
    }
    static func numbers(_ c: KeyedDecodingContainer<AnyKey>, _ key: String) -> [Int]? {
        guard let k = AnyKey(stringValue: key) else { return nil }
        if let a = try? c.decodeIfPresent([Double].self, forKey: k) { return a.map { Int($0.rounded()) } }
        if let a = try? c.decodeIfPresent([Int].self, forKey: k) { return a }
        return nil
    }
    static func list<T: Decodable>(_ c: KeyedDecodingContainer<AnyKey>, _ key: String, _ t: T.Type) -> [T] {
        guard let k = AnyKey(stringValue: key) else { return [] }
        return (try? c.decodeIfPresent([T].self, forKey: k)) ?? []
    }
}

public struct AnyKey: CodingKey {
    public var stringValue: String
    public var intValue: Int? { nil }
    public init?(stringValue: String) { self.stringValue = stringValue }
    public init?(intValue: Int) { return nil }
}

public enum SuggestionStatus: String, Codable { case offered, accepted, declined, never, done }

public struct Suggestion: Codable, Equatable, Identifiable {
    public var id: String
    public var person_id: String
    public var skill_id: String
    public var title: String
    public var body: String
    public var why_now: String
    public var count_last_week: Int
    public var minutes_each: Int
    public var estimate_s: Int
    public var plan_id: String
    public var status: SuggestionStatus

    public init(id: String, person_id: String, skill_id: String, title: String, body: String, why_now: String,
                count_last_week: Int, minutes_each: Int, estimate_s: Int, plan_id: String, status: SuggestionStatus) {
        self.id = id; self.person_id = person_id; self.skill_id = skill_id; self.title = title; self.body = body
        self.why_now = why_now; self.count_last_week = count_last_week; self.minutes_each = minutes_each
        self.estimate_s = estimate_s; self.plan_id = plan_id; self.status = status
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = Flex.string(c, "id") ?? ""
        person_id = Flex.string(c, "person_id") ?? ""
        skill_id = Flex.string(c, "skill_id") ?? ""
        title = Flex.string(c, "title") ?? ""
        body = Flex.string(c, "body") ?? ""
        why_now = Flex.string(c, "why_now") ?? ""
        count_last_week = Int((Flex.number(c, "count_last_week") ?? 0).rounded())
        minutes_each = Int((Flex.number(c, "minutes_each") ?? 0).rounded())
        estimate_s = Int((Flex.number(c, "estimate_s") ?? 0).rounded())
        plan_id = Flex.string(c, "plan_id") ?? ""
        if let raw = Flex.string(c, "status") { status = SuggestionStatus(rawValue: raw) ?? .never } else { status = .offered }
    }
}

public enum SuggestionAnswer: String, Codable { case do_it, not_now, dont_ask }

public enum RunStatus: String, Codable { case running, done, stopped, failed }
public enum RunStepStatus: String, Codable { case done, now, pending }

public struct RunStep: Codable, Equatable, Identifiable {
    public var n: Int
    public var label: String
    public var detail: String
    public var status: RunStepStatus
    public var progress: [Int]?
    public var at_s: Double?
    public var id: Int { n }
    public var atSeconds: Int? { at_s.map { Int($0.rounded()) } }

    public init(n: Int, label: String, detail: String, status: RunStepStatus, progress: [Int]? = nil, at_s: Double? = nil) {
        self.n = n; self.label = label; self.detail = detail; self.status = status; self.progress = progress; self.at_s = at_s
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        n = Int((Flex.number(c, "n") ?? 0).rounded())
        label = Flex.string(c, "label") ?? ""
        detail = Flex.string(c, "detail") ?? ""
        status = Flex.string(c, "status").flatMap(RunStepStatus.init(rawValue:)) ?? .pending
        progress = Flex.numbers(c, "progress")
        at_s = Flex.number(c, "at_s")
    }
}

public struct RunCheck: Codable, Equatable {
    public var name: String
    public var ok: Bool
    public var detail: String
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        name = Flex.string(c, "name") ?? ""
        ok = (try? c.decodeIfPresent(Bool.self, forKey: AnyKey(stringValue: "ok")!)) ?? false
        detail = Flex.string(c, "detail") ?? ""
    }
}

public struct Run: Codable, Equatable {
    public var id: String
    public var skill_id: String
    public var target: String
    public var status: RunStatus
    public var started_at: String
    public var elapsed_s: Double
    public var steps: [RunStep]
    public var checks: [RunCheck]
    public var title: String?   // optional, not in SCHEMA.md §11 yet; used for the agent panel headline when present

    public init(id: String, skill_id: String, target: String, status: RunStatus, started_at: String, elapsed_s: Double,
                steps: [RunStep], checks: [RunCheck], title: String? = nil) {
        self.id = id; self.skill_id = skill_id; self.target = target; self.status = status; self.started_at = started_at
        self.elapsed_s = elapsed_s; self.steps = steps; self.checks = checks; self.title = title
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = Flex.string(c, "id") ?? ""
        skill_id = Flex.string(c, "skill_id") ?? ""
        target = Flex.string(c, "target") ?? "mac"
        status = Flex.string(c, "status").flatMap(RunStatus.init(rawValue:)) ?? .running
        started_at = Flex.string(c, "started_at") ?? ""
        elapsed_s = Flex.number(c, "elapsed_s") ?? 0
        steps = Flex.list(c, "steps", RunStep.self)
        checks = Flex.list(c, "checks", RunCheck.self)
        title = Flex.string(c, "title")
    }
}

// MARK: - Formatting helpers shared by UI and compiler

public enum Fmt {
    public static func hm(_ minutes: Int) -> String {
        let h = minutes / 60, m = minutes % 60
        if h == 0 { return "\(m) m" }
        return String(format: "%d h %02d m", h, m)
    }
    public static func clock(_ d: Date, tz: TimeZone = .current) -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = tz
        f.dateFormat = "HH:mm"; return f.string(from: d)
    }
    public static func clock(_ iso: String) -> String {
        guard let d = ISO.date(iso) else { return "--:--" }
        return clock(d)
    }
    public static func clockSeconds(_ d: Date) -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm:ss"; return f.string(from: d)
    }
    public static func longDay(_ ymd: String) -> String {
        // "2026-11-06" -> "Wednesday 6 November"
        let p = DateFormatter(); p.locale = Locale(identifier: "en_US_POSIX"); p.dateFormat = "yyyy-MM-dd"
        guard let d = p.date(from: ymd) else { return ymd }
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "EEEE d MMMM"
        return f.string(from: d)
    }
    public static func shortDay(_ ymd: String) -> String {
        let p = DateFormatter(); p.locale = Locale(identifier: "en_US_POSIX"); p.dateFormat = "yyyy-MM-dd"
        guard let d = p.date(from: ymd) else { return ymd }
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "EEE d MMM"
        return f.string(from: d)
    }
    public static func mediumDay(_ ymd: String) -> String {
        let p = DateFormatter(); p.locale = Locale(identifier: "en_US_POSIX"); p.dateFormat = "yyyy-MM-dd"
        guard let d = p.date(from: ymd) else { return ymd }
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "d MMM yyyy"
        return f.string(from: d)
    }
}
