import Foundation
import NaturalLanguage

/// The privacy filter. Runs before anything is drafted. Nothing here ever sees a screenshot,
/// message text, file contents or keystrokes — only app names, window titles and URL hosts.
public enum Privacy {

    // Personal communication apps: time in them is counted as "away", nothing else is noted.
    public static let denyApps: Set<String> = [
        "Messages", "WhatsApp", "KakaoTalk", "Telegram", "Signal", "Discord", "FaceTime", "LINE", "WeChat", "iMessage",
    ]

    // Banking / health / personal hosts: events removed entirely.
    public static let denyHostTokens: [String] = [
        "bank", "banking", "chase", "wellsfargo", "bofa", "citi", "capitalone", "hsbc", "barclays",
        "kbstar", "kbcard", "shinhan", "woori", "hana", "nonghyup", "toss", "kakaobank", "kakaopay", "naverpay",
        "paypal", "venmo", "zelle", "revolut", "wise", "monzo", "n26", "coinbase", "binance", "upbit", "bithumb",
        "robinhood", "schwab", "fidelity", "vanguard",
        "health", "mychart", "healthcare", "hospital", "clinic", "pharmacy", "therapy", "patient",
        "tinder", "bumble", "hinge",
    ]
    static let shortExactTokens: Set<String> = ["kb", "nh", "ibk", "sc", "kbank", "toss", "wise", "hana"]

    public static let neverKept = ["Screen images", "Message text", "File contents", "Keystrokes"]

    // Apps whose time inside a document step belongs to that step (a call or chat about the document).
    public static let commApps: Set<String> = ["Slack", "Zoom", "zoom.us", "Microsoft Teams", "Google Meet", "Webex", "Discord"]

    public static func isDeniedApp(_ app: String) -> Bool {
        let a = app.trimmingCharacters(in: .whitespaces)
        if denyApps.contains(a) { return true }
        let low = a.lowercased()
        return denyApps.contains { low == $0.lowercased() }
    }

    public static func isDeniedHost(_ host: String?) -> Bool {
        guard let host = host?.lowercased(), !host.isEmpty else { return false }
        let labels = host.split(whereSeparator: { $0 == "." || $0 == "-" }).map(String.init)
        for label in labels {
            if shortExactTokens.contains(label) { return true }
            for t in denyHostTokens where t.count >= 4 && label.contains(t) { return true }
        }
        return false
    }

    // MARK: Names in titles and file names

    static let surnames: Set<String> = [
        // Korean romanisations (both orders are common in file names)
        "kim", "lee", "park", "choi", "jung", "jeong", "kang", "cho", "jo", "yoon", "yun", "jang", "chang", "lim", "im",
        "han", "oh", "seo", "shin", "kwon", "hwang", "ahn", "song", "ryu", "yoo", "hong", "jeon", "moon", "bae", "baek",
        "nam", "noh", "ha", "heo", "yang", "koo", "min", "minji", "jihoon", "seojun", "yuna", "jiwoo", "hyun", "soo",
        // Common English / Chinese / Indian / Vietnamese surnames
        "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis", "rodriguez", "martinez",
        "hernandez", "lopez", "gonzalez", "wilson", "anderson", "thomas", "taylor", "moore", "jackson", "martin",
        "thompson", "white", "harris", "clark", "lewis", "robinson", "walker", "young", "allen", "king", "wright",
        "scott", "green", "baker", "adams", "nelson", "hill", "campbell", "mitchell", "roberts", "carter", "phillips",
        "evans", "turner", "torres", "parker", "collins", "edwards", "stewart", "morris", "murphy", "cook", "rogers",
        "nguyen", "tran", "pham", "chen", "wang", "li", "zhang", "liu", "huang", "wu", "zhou", "xu", "sun", "ma",
        "patel", "singh", "kumar", "sharma", "gupta", "khan", "ali", "ahmed", "tanaka", "suzuki", "sato", "watanabe",
        "schmidt", "müller", "mueller", "fischer", "weber", "meyer", "rossi", "russo", "silva", "santos", "costa",
    ]
    static let docWords: Set<String> = [
        "contract", "agreement", "resume", "résumé", "cv", "invoice", "offer", "letter", "nda", "onboarding", "notes",
        "interview", "payslip", "review", "feedback", "evaluation", "appraisal", "application", "references", "file",
        "folder", "profile", "record", "report", "memo", "1on1", "1:1", "performance", "salary", "termination",
        "계약서", "이력서", "면접", "평가", "급여", "계약",
    ]
    static let notNames: Set<String> = [
        "proposal", "re", "fwd", "fw", "northwind", "fitness", "google", "sheets", "docs", "slides", "mail", "untitled",
        "new", "draft", "final", "copy", "pricing", "sheet", "deck", "client", "brief", "quote", "estimate", "monday",
        "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april",
        "may", "june", "july", "august", "september", "october", "november", "december", "director", "sales", "design",
        "finance", "legal", "ops", "pm", "ceo", "team", "meeting", "sync", "call", "zoom", "slack", "inbox", "sent",
        "halden", "logistics", "investment", "total", "the", "and", "for", "with", "from", "to", "of", "in", "on",
    ]

    public struct Mask: Equatable {
        public var text: String
        public var hadName: Bool
    }

    /// Masks person names. If any personal name is found the whole title becomes "client file" (the
    /// name is what we never want to keep; the rest of a file name rarely matters to a step).
    public static func maskNames(_ title: String) -> Mask {
        guard !title.isEmpty else { return Mask(text: title, hadName: false) }
        if hasPersonalName(title) { return Mask(text: "client file", hadName: true) }
        return Mask(text: title, hadName: false)
    }

    public static func hasPersonalName(_ s: String) -> Bool {
        // 1. NaturalLanguage: personalName tags.
        let tagger = NLTagger(tagSchemes: [.nameType])
        tagger.string = s
        var found = false
        tagger.enumerateTags(in: s.startIndex..<s.endIndex, unit: .word, scheme: .nameType,
                             options: [.omitWhitespace, .omitPunctuation, .joinNames]) { tag, _ in
            if tag == .personalName { found = true; return false }
            return true
        }
        if found { return true }

        // 2. Heuristic: a known surname next to another capitalised word, or two capitalised words
        //    followed by a personal-document word ("Kim Minji contract.pdf", "Sarah Chen onboarding notes").
        let stripped = s.replacingOccurrences(of: #"\.[A-Za-z0-9]{1,5}$"#, with: "", options: .regularExpression)
        let words = stripped.split(whereSeparator: { $0 == " " || $0 == "_" || $0 == "-" || $0 == "·" || $0 == "—" || $0 == "(" || $0 == ")" || $0 == "," })
            .map(String.init)
        func isCap(_ w: String) -> Bool {
            guard let f = w.unicodeScalars.first else { return false }
            return CharacterSet.uppercaseLetters.contains(f) && w.count >= 2 && w.allSatisfy { $0.isLetter }
                && !notNames.contains(w.lowercased())
        }
        for i in 0..<words.count {
            let w = words[i].lowercased()
            if surnames.contains(w), isCap(words[i]) {
                if i + 1 < words.count, isCap(words[i + 1]) { return true }
                if i > 0, isCap(words[i - 1]) { return true }
            }
            if i + 2 < words.count, isCap(words[i]), isCap(words[i + 1]), docWords.contains(words[i + 2].lowercased()) {
                return true
            }
        }
        // 3. Hangul name (2–4 syllables) followed by a personal-document word.
        if s.range(of: #"[가-힣]{2,4}\s*(계약서|이력서|면접|평가|급여|계약)"#, options: .regularExpression) != nil { return true }
        return false
    }

    /// A short hint of the document a title refers to (strip app suffixes), for the compiler's step key.
    public static func documentKey(_ title: String?) -> String {
        guard var t = title, !t.isEmpty else { return "" }
        for suffix in [" - Google Sheets", " - Google Docs", " - Google Slides", " - Google Chrome", " — Mozilla Firefox",
                       " - Safari", " – Safari", " - Microsoft Excel", " - Excel", " - Word", " - PowerPoint", " — Slack", " - Slack"] {
            if t.hasSuffix(suffix) { t = String(t.dropLast(suffix.count)) }
        }
        let seps = [" · ", " — ", " – ", " | ", " - "]
        for s in seps { if let r = t.range(of: s) { t = String(t[..<r.lowerBound]) } }
        return t.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}
