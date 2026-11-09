import Foundation

public struct CompilerConfig {
    public var person_id: String
    public var role: Role
    public var board_id: String
    public var date: String
    public var idleThreshold: TimeInterval = 300   // idle ≥ 5 min = waiting / away
    public var microSeconds: TimeInterval = 120    // switches under 2 min merge into the surrounding step
    public var maxSampleGap: TimeInterval = 60     // a sample never counts for more than this
    public var toolMinSeconds: TimeInterval = 120  // a tool must hold ≥ 2 min to be listed on a step

    public init(person_id: String, role: Role, board_id: String, date: String) {
        self.person_id = person_id; self.role = role; self.board_id = board_id; self.date = date
    }
}

/// What is kept per day for repeat detection: only tool-pattern signatures, never titles.
public struct StepHistory: Codable, Equatable {
    public var date: String
    public var signatures: [String]
    public init(date: String, signatures: [String]) { self.date = date; self.signatures = signatures }
}

// MARK: - Namer protocol

public struct NamerStepInput: Codable {
    public var idx: Int
    public var start: String
    public var end: String
    public var minutes: Int
    public var kind: String
    public var apps: [String]
    public var sequence: String
    public var titles: [String]
    public var tools: [String]
}

public struct NamerStepOutput: Codable {
    public var idx: Int
    public var name: String?
    public var kind: String?
    public var case_id: String?
    public var tools: [String]?
    public var waiting_on: String?
    public var handoff_from: String?
    public var handoff_to: String?
}

public struct NamerResponse: Codable {
    public var steps: [NamerStepOutput]
    public var summary: String?
}

public protocol Namer {
    func name(_ steps: [NamerStepInput], role: Role) async -> NamerResponse?
}

// MARK: - Compiler

public enum Compiler {

    enum SegKind { case active, idle, away }

    struct Seg {
        var start: Date
        var end: Date
        var kind: SegKind
        var app: String
        var key: String
        var appSeconds: [String: Double] = [:]
        var toolSeconds: [String: Double] = [:]
        var keySeconds: [String: Double] = [:]
        var titles: [String] = []
        var sequence: [String] = []   // tool tokens in order of appearance (compressed)
        var hadName = false
        var duration: TimeInterval { end.timeIntervalSince(start) }
        var isActive: Bool { kind == .active }

        mutating func absorb(_ o: Seg) {
            let mineActive = isActive ? duration : 0
            let theirsActive = o.isActive ? o.duration : 0
            start = min(start, o.start); end = max(end, o.end)
            _ = (mineActive, theirsActive)
            for (k, v) in o.appSeconds { appSeconds[k, default: 0] += v }
            for (k, v) in o.toolSeconds { toolSeconds[k, default: 0] += v }
            for (k, v) in o.keySeconds { keySeconds[k, default: 0] += v }
            if isActive || o.isActive {
                kind = .active
                recomputeKey()
            } else { kind = .idle }
            for t in o.titles where !titles.contains(t) { titles.append(t) }
            if o.start < start || (o.start == start && o.end < end) {
                sequence = Seg.compress(o.sequence + sequence)
            } else {
                sequence = Seg.compress(sequence + o.sequence)
            }
            hadName = hadName || o.hadName
        }

        /// Dominant app|document key — or a composite key when two document tools each hold ≥ 2 min,
        /// so a "copy from sheet into deck" block never merges with a plain deck block beside it.
        mutating func recomputeKey(minTool: Double = 120) {
            let docs = toolSeconds.filter { Tools.documentTools.contains($0.key) && $0.value >= minTool }.keys.sorted()
            if docs.count >= 2 { key = "multi|" + docs.joined(separator: "→"); return }
            if let best = keySeconds.max(by: { $0.value < $1.value }) {
                key = best.key
                app = String(best.key.split(separator: "|").first ?? "")
            }
        }

        var caseId: String? { Compiler.detectCase(titles.joined(separator: " · ")) }
        /// A mail that hands work to another role (not "from" someone) stays its own step.
        var isHandoffMail: Bool {
            guard (toolSeconds["mail"] ?? 0) > 0, toolSeconds.count == 1 else { return false }
            let t = titles.joined(separator: " ").lowercased()
            return !Compiler.detectRoles(t).isEmpty && !t.contains("from ")
        }

        static func compress(_ s: [String]) -> [String] {
            var out: [String] = []
            for x in s where out.last != x { out.append(x) }
            return out
        }
    }

    public struct Result {
        public var draft: DraftDay
        public var signatures: [String]
    }

    public static func compile(events rawEvents: [Event], config: CompilerConfig, history: [StepHistory],
                               namer: Namer?) async -> Result {
        let events = rawEvents.sorted { $0.date < $1.date }
        guard !events.isEmpty else {
            let d = DraftDay(person_id: config.person_id, role: config.role, date: config.date, board_id: config.board_id,
                             steps: [], left_out: [], summary: "Nothing was noted today.")
            return Result(draft: d, signatures: [])
        }

        // 1. Idle intervals from idle_s ≥ threshold (the idle run started idle_s seconds before the sample).
        var idleRanges: [(Date, Date)] = []
        for e in events where Double(e.idle_s) >= config.idleThreshold {
            let end = e.date, start = end.addingTimeInterval(-Double(e.idle_s))
            if let last = idleRanges.last, start <= last.1 { idleRanges[idleRanges.count - 1].1 = max(last.1, end) }
            else { idleRanges.append((start, end)) }
        }
        func isIdle(_ d: Date) -> Bool { idleRanges.contains { d >= $0.0 && d <= $0.1 } }

        // 2. Classify, measure, build raw segments.
        var chatSeconds = 0.0, bankSeconds = 0.0
        var nameHashes = Set<String>()
        var segs: [Seg] = []
        for (i, e) in events.enumerated() {
            let ts = e.date
            var dur: TimeInterval
            if i + 1 < events.count { dur = events[i + 1].date.timeIntervalSince(ts) }
            else if i > 0 { dur = min(ts.timeIntervalSince(events[i - 1].date), config.maxSampleGap) } else { dur = 1 }
            let gap = dur
            dur = max(0, min(dur, config.maxSampleGap))

            var kind: SegKind = .active
            if Privacy.isDeniedHost(e.url_host) { kind = .away; bankSeconds += dur }
            else if Privacy.isDeniedApp(e.app) { kind = .away; chatSeconds += dur }
            else if isIdle(ts) { kind = .idle }
            if e.title_masked == "client file" { nameHashes.insert(e.title_hash) }

            let title = e.title_masked ?? ""
            let tool = Tools.token(app: e.app, title: title)
            let key = kind == .active ? "\(e.app)|\(Privacy.documentKey(title))" : "wait"
            var seg = Seg(start: ts, end: ts.addingTimeInterval(dur), kind: kind, app: e.app, key: key)
            if kind == .active {
                seg.appSeconds[e.app] = dur
                seg.toolSeconds[tool] = dur
                seg.keySeconds[key] = dur
                if !title.isEmpty, title != "client file" { seg.titles = [title] }
                seg.sequence = [tool]
                seg.hadName = e.title_masked == "client file"
            }
            if var last = segs.last, (last.kind == seg.kind && (last.kind != .active || last.key == seg.key)) {
                last.absorb(seg); segs[segs.count - 1] = last
            } else {
                segs.append(seg)
            }
            // A hole in the samples longer than the idle threshold is time away from the machine.
            if gap > config.idleThreshold {
                let hole = Seg(start: ts.addingTimeInterval(dur), end: ts.addingTimeInterval(gap), kind: .idle, app: "", key: "wait")
                segs.append(hole)
            }
        }

        // 3. Merge passes until stable.
        var changed = true
        var guardCount = 0
        while changed && guardCount < 50 {
            changed = false; guardCount += 1
            // A. adjacent same-kind
            var i = 0
            while i + 1 < segs.count {
                let a = segs[i], b = segs[i + 1]
                if (!a.isActive && !b.isActive) || (a.isActive && b.isActive && a.key == b.key) {
                    segs[i].absorb(b); segs.remove(at: i + 1); changed = true
                } else { i += 1 }
            }
            // B. micro active segments merge into the surrounding active step
            i = 0
            while i < segs.count {
                let s = segs[i]
                if s.isActive, s.duration < config.microSeconds, segs.count > 1 {
                    let prevActive = i > 0 && segs[i - 1].isActive
                    let nextActive = i + 1 < segs.count && segs[i + 1].isActive
                    if prevActive { segs[i - 1].absorb(s); segs.remove(at: i); changed = true; continue }
                    if nextActive { segs[i + 1].absorb(s); segs.remove(at: i); changed = true; continue }
                    if s.duration < 60 { // a blip inside a waiting stretch
                        if i > 0 { segs[i - 1].absorb(s); segs.remove(at: i); changed = true; continue }
                        if i + 1 < segs.count { segs[i + 1].absorb(s); segs.remove(at: i); changed = true; continue }
                    }
                }
                i += 1
            }
            // C. short away/idle stretches (a one-minute chat check) belong to the step around them
            i = 0
            while i < segs.count {
                let s = segs[i]
                if !s.isActive, s.duration < config.idleThreshold, segs.count > 1 {
                    if i > 0, segs[i - 1].isActive { segs[i - 1].absorb(s); segs.remove(at: i); changed = true; continue }
                    if i + 1 < segs.count, segs[i + 1].isActive { segs[i + 1].absorb(s); segs.remove(at: i); changed = true; continue }
                }
                i += 1
            }
            // D. a call or chat sandwiched between two stretches of the same document is part of that step
            i = 1
            while i + 1 < segs.count {
                let s = segs[i]
                if s.isActive, Privacy.commApps.contains(s.app), segs[i - 1].isActive, segs[i + 1].isActive,
                   segs[i - 1].key == segs[i + 1].key {
                    segs[i - 1].absorb(s); segs[i - 1].absorb(segs[i + 1])
                    segs.removeSubrange(i...(i + 1)); changed = true; continue
                }
                i += 1
            }
            // E. a short stretch on the same case as its neighbour (reading the brief in Mail, then in Docs)
            //    belongs to one step — unless it is a mail that hands the work to someone else.
            i = 0
            while i + 1 < segs.count {
                let a = segs[i], b = segs[i + 1]
                if a.isActive, b.isActive, let ca = a.caseId, let cb = b.caseId, ca == cb,
                   min(a.duration, b.duration) < 600, !a.isHandoffMail, !b.isHandoffMail,
                   !a.key.hasPrefix("multi|"), !b.key.hasPrefix("multi|") {
                    segs[i].absorb(b); segs.remove(at: i + 1); changed = true; continue
                }
                i += 1
            }
        }
        // Drop leading / trailing waiting (the day starts and ends with work).
        while let f = segs.first, !f.isActive { segs.removeFirst() }
        while let l = segs.last, !l.isActive { segs.removeLast() }

        // 4. Steps.
        var steps: [DraftStep] = []
        var inputs: [NamerStepInput] = []
        var prevMailRole: Role?
        var prevMailWasApproval = false
        for (n, s) in segs.enumerated() {
            let idx = n + 1
            let kind: StepKind = s.isActive ? .hands_on : .waiting
            var tools: [String] = []
            if s.isActive {
                let dominant = s.toolSeconds.max { $0.value < $1.value }?.key
                for t in s.sequence where !tools.contains(t) {
                    if (s.toolSeconds[t] ?? 0) >= config.toolMinSeconds || t == dominant { tools.append(t) }
                }
            }
            let titleText = s.titles.joined(separator: " · ")
            let caseId = detectCase(titleText)
            let roles = detectRoles(titleText)
            var step = DraftStep(idx: idx, start: ISO.string(s.start), end: ISO.string(s.end), name: "", kind: kind, case_id: caseId, tools: tools)
            if kind == .hands_on {
                if tools.contains("mail"), let r = roles.first(where: { $0 != config.role }) {
                    if titleText.lowercased().contains("from \(r.rawValue.lowercased())") { step.handoff_from = r } else { step.handoff_to = r }
                    prevMailRole = r
                    prevMailWasApproval = ["approv", "sign", "quote", "review", "confirm"].contains { titleText.lowercased().contains($0) }
                } else if !tools.contains("mail") {
                    // keep the last mail context for the waiting step that may follow
                }
                step.name = ruleName(step, seg: s, roles: roles)
            } else {
                step.waiting_on = prevMailRole
                step.name = prevMailWasApproval ? "Waited for approval" : (prevMailRole != nil ? "Waited for a reply" : "Away from the desk")
                if step.case_id == nil, let prev = steps.last { step.case_id = prev.case_id }
            }
            steps.append(step)
            inputs.append(NamerStepInput(idx: idx, start: Fmt.clock(s.start), end: Fmt.clock(s.end), minutes: step.minutes,
                                         kind: kind.rawValue, apps: Array(s.appSeconds.keys.sorted()),
                                         sequence: s.sequence.map(Tools.display).joined(separator: " → "),
                                         titles: s.titles, tools: tools))
        }

        // 5. Repeats: same ordered document-tool pattern on other days this week.
        var signatures: [String] = []
        for i in steps.indices where steps[i].kind == .hands_on {
            let docTools = steps[i].tools.filter { Tools.documentTools.contains($0) }
            guard docTools.count >= 2 else { continue }
            let sig = docTools.joined(separator: "→")
            signatures.append(sig)
            let others = history.filter { $0.date != config.date && sameWeek($0.date, config.date) && $0.signatures.contains(sig) }.count
            let count = others + 1
            if count >= 2 { steps[i].repeats = count }
        }

        // 6. Names from the model, when available.
        var summary: String?
        if let namer, !steps.isEmpty, let resp = await namer.name(inputs, role: config.role) {
            for out in resp.steps {
                guard let i = steps.firstIndex(where: { $0.idx == out.idx }) else { continue }
                if let n = out.name?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty { steps[i].name = n }
                if let k = out.kind, let kk = StepKind(rawValue: k) { steps[i].kind = kk }
                if let c = out.case_id, !c.isEmpty { steps[i].case_id = c }
                if let t = out.tools, !t.isEmpty, steps[i].kind == .hands_on { steps[i].tools = t.map { $0.lowercased() } }
                if let w = out.waiting_on, let r = Role(rawValue: w) { steps[i].waiting_on = r }
                if let w = out.handoff_from, let r = Role(rawValue: w) { steps[i].handoff_from = r }
                if let w = out.handoff_to, let r = Role(rawValue: w) { steps[i].handoff_to = r }
            }
            if let s = resp.summary?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty { summary = s }
        }

        // 7. Left out.
        var leftOut: [LeftOut] = []
        if chatSeconds > 0 { leftOut.append(LeftOut(kind: .personal_chat, label: "A personal chat app", minutes: Int((chatSeconds / 60).rounded()), action: .counted_as_away)) }
        if bankSeconds > 0 { leftOut.append(LeftOut(kind: .banking, label: "A banking site", minutes: Int((bankSeconds / 60).rounded()), action: .removed)) }
        if !nameHashes.isEmpty { leftOut.append(LeftOut(kind: .name_in_filename, label: nameHashes.count == 1 ? "A file name with a person’s name" : "\(nameHashes.count) file names with a person’s name", minutes: nil, action: .renamed)) }

        var draft = DraftDay(person_id: config.person_id, role: config.role, date: config.date, board_id: config.board_id,
                             steps: steps, left_out: leftOut, summary: "")
        draft.summary = summary ?? ruleSummary(draft)
        return Result(draft: draft, signatures: signatures)
    }

    // MARK: Rules

    static func ruleName(_ step: DraftStep, seg: Seg, roles: [Role]) -> String {
        let doc = seg.titles.first.map { Privacy.documentKey($0) } ?? ""
        let docPart = doc.isEmpty ? "" : " on \(doc)"
        let docTools = step.tools.filter { Tools.documentTools.contains($0) }
        if step.tools == ["mail"] || (step.tools.first == "mail" && step.tools.count == 1) {
            if let r = step.handoff_to { return "Wrote to \(article(r))\(r.rawValue)" + (step.case_id.map { " about \($0)" } ?? "") }
            if let r = step.handoff_from { return "Read mail from \(r.rawValue)" + (step.case_id.map { " about \($0)" } ?? "") }
            return "Handled mail" + (step.case_id.map { " about \($0)" } ?? "")
        }
        if docTools.count >= 2 {
            let switches = seg.sequence.count - 1
            if switches >= 3 { return "Moved content from \(Tools.display(docTools[0])) into \(Tools.display(docTools[1]))" }
            return "Worked across \(docTools.map(Tools.display).joined(separator: " and "))\(docPart)"
        }
        if let main = step.tools.first {
            var n = "Worked in \(Tools.display(main))\(docPart)"
            if step.tools.contains("call") || step.tools.contains("chat"), let r = roles.first { n += " with \(r.rawValue)" }
            return n
        }
        return "Worked\(docPart)"
    }

    static func article(_ r: Role) -> String {
        switch r { case .Director, .CEO: return "the "; default: return "" }
    }

    public static func ruleSummary(_ d: DraftDay) -> String {
        var caseMinutes: [String: Int] = [:]
        for s in d.steps where s.kind == .hands_on { if let c = s.case_id { caseMinutes[c, default: 0] += s.minutes } }
        let top = caseMinutes.max { $0.value < $1.value }?.key
        let waiting = d.waitingMinutes
        let waitRole = d.steps.first { $0.kind == .waiting }?.waiting_on
        if let top {
            if waiting > 0 {
                let who = waitRole.map { "the \($0.rawValue)" } ?? "others"
                return "Most of today went to \(top) — and \(Fmt.hm(waiting)) of it was waiting on \(who)."
            }
            return "Most of today went to \(top) — \(d.steps.count) steps, \(Fmt.hm(d.handsOnMinutes)) hands-on."
        }
        if d.steps.isEmpty { return "Nothing was noted today." }
        return "\(d.steps.count) steps today — \(Fmt.hm(d.handsOnMinutes)) hands-on, \(Fmt.hm(waiting)) waiting."
    }

    static func detectCase(_ text: String) -> String? {
        let t = text.lowercased()
        if let m = t.range(of: #"(proposal|quote|order|ticket|case|invoice|deal|po)[\s\-]*#?\s*(\d{2,6})"#, options: .regularExpression) {
            let s = String(t[m])
            let word = s.components(separatedBy: CharacterSet(charactersIn: " -#")).first ?? "case"
            let num = s.components(separatedBy: CharacterSet.decimalDigits.inverted).filter { !$0.isEmpty }.last ?? ""
            return "\(word) #\(num)"
        }
        if let m = t.range(of: #"#(\d{2,6})"#, options: .regularExpression) { return String(t[m]) }
        return nil
    }

    static func detectRoles(_ text: String) -> [Role] {
        let t = text.lowercased()
        var out: [Role] = []
        let map: [(String, Role)] = [("director", .Director), ("sales", .Sales), ("design", .Design), ("finance", .Finance),
                                     ("legal", .Legal), ("client", .Client), ("ceo", .CEO), ("ops", .Ops), ("trainer", .Trainer),
                                     ("branch", .BranchMgr)]
        for (w, r) in map where t.contains(w) && !out.contains(r) { out.append(r) }
        return out
    }

    static func sameWeek(_ a: String, _ b: String) -> Bool {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
        guard let da = f.date(from: a), let db = f.date(from: b) else { return false }
        var cal = Calendar(identifier: .iso8601); cal.timeZone = .current
        return cal.component(.weekOfYear, from: da) == cal.component(.weekOfYear, from: db)
            && cal.component(.yearForWeekOfYear, from: da) == cal.component(.yearForWeekOfYear, from: db)
    }
}

// MARK: - Record building

public extension DraftDay {
    /// Build the approved Record (unsigned) from the shared steps. Hash / pubkey / sig are filled by Signer.seal.
    func record(id: String, approvedAt: Date) -> Record {
        let shared = steps.filter { $0.share }
        var rs: [RecordStep] = []
        for (i, s) in shared.enumerated() { rs.append(RecordStep(s, idx: i + 1)) }
        let start = shared.first?.start ?? ISO.string(approvedAt)
        let end = shared.last?.end ?? start
        return Record(id: id, board_id: board_id, person_id: person_id, role: role, date: date,
                      covers: Covers(start: start, end: end), steps: rs, kept_private: left_out.count,
                      hands_on_min: shared.filter { $0.kind == .hands_on }.reduce(0) { $0 + $1.minutes },
                      waiting_min: shared.filter { $0.kind == .waiting }.reduce(0) { $0 + $1.minutes },
                      approved_at: ISO.string(approvedAt))
    }
}
