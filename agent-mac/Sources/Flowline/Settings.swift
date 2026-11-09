import Foundation
import Combine
import FlowlineCore

/// User settings. Plain values live in UserDefaults; the API key lives in the keychain only.
///
/// Identity comes from **joining a company** (Settings → Join a company, or a `flowline://join?api=…&code=…` link):
/// `POST {api}/api/invites/{code}/claim` answers `{board_id, board_name, person_id, name, role}` and every field is
/// stored as is — the app never maps a board id to a display name. Nothing is configured on first run
/// (`isJoined == false`): the app shows Settings and neither polls nor posts anywhere.
final class AppSettings: ObservableObject {
    static let apiKeyAccount = "anthropic-api-key"
    private let d = UserDefaults.standard
    private var persist = true

    @Published var person_id: String { didSet { if persist { d.set(person_id, forKey: "person_id") } } }
    @Published var person_name: String { didSet { if persist { d.set(person_name, forKey: "person_name") } } }
    @Published var role: Role { didSet { if persist { d.set(role.rawValue, forKey: "role") } } }
    @Published var board_id: String { didSet { if persist { d.set(board_id, forKey: "board_id") } } }
    @Published var board_name: String { didSet { if persist { d.set(board_name, forKey: "board_name") } } }
    @Published var api_base: String { didSet { if persist { d.set(api_base, forKey: "api_base") } } }
    @Published var joinedAt: Date? { didSet { if persist { d.set(joinedAt, forKey: "joined_at") } } }
    @Published var eodHour: Int { didSet { d.set(eodHour, forKey: "eod_hour") } }
    @Published var eodMinute: Int { didSet { d.set(eodMinute, forKey: "eod_minute") } }
    @Published var demoMode: Bool { didSet { d.set(demoMode, forKey: "demo_mode") } }
    @Published var noteBrowserSites: Bool { didSet { d.set(noteBrowserSites, forKey: "note_browser") } }
    @Published var pausedUntil: Date? { didSet { d.set(pausedUntil, forKey: "paused_until") } }
    @Published var apiKeyPresent: Bool
    /// True while the in-memory demo identity is in use (`--demo-day` with nothing joined); nothing is written.
    @Published private(set) var demoIdentity = false

    /// Shown in the menu panel and the review header: the board's own name, else its id.
    var boardName: String { board_name.isEmpty ? board_id : board_name }
    /// "Dana Whitfield · Northwind Fitness" — the header line; falls back to the role when no name is known.
    var headerLine: String {
        let who = person_name.isEmpty ? role.rawValue : person_name
        return boardName.isEmpty ? who : "\(who) · \(boardName)"
    }
    /// Joined a company (or identity set by hand): the app may compile records for and poll this board.
    var isJoined: Bool { !person_id.isEmpty && !board_id.isEmpty && !api_base.isEmpty }

    /// `run_target` is only honoured when set explicitly (`defaults write co.sweetspot.flowline run_target desk1`,
    /// the demo); a joined company works on the person's own machine.
    var runTarget: String { d.string(forKey: "run_target").flatMap { $0.isEmpty ? nil : $0 } ?? "mac" }

    init() {
        person_id = d.string(forKey: "person_id") ?? ""
        person_name = d.string(forKey: "person_name") ?? ""
        role = Role(rawValue: d.string(forKey: "role") ?? "PM") ?? .PM
        board_id = d.string(forKey: "board_id") ?? ""
        board_name = d.string(forKey: "board_name") ?? ""
        api_base = d.string(forKey: "api_base") ?? ""
        joinedAt = d.object(forKey: "joined_at") as? Date
        eodHour = d.object(forKey: "eod_hour") as? Int ?? 18
        eodMinute = d.object(forKey: "eod_minute") as? Int ?? 0
        demoMode = d.bool(forKey: "demo_mode")
        noteBrowserSites = d.object(forKey: "note_browser") as? Bool ?? false
        pausedUntil = d.object(forKey: "paused_until") as? Date
        apiKeyPresent = !(ProcessInfo.processInfo.environment["ANTHROPIC_API_KEY"] ?? "").isEmpty
            || Keychain.readString(AppSettings.apiKeyAccount)?.isEmpty == false
    }

    /// The claim's answer becomes the identity; `api` is the address the claim was made against.
    func apply(claim: JoinClaim, api: String) {
        persist = true
        demoIdentity = false
        api_base = api.trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
        board_id = claim.board_id
        board_name = claim.board_name
        person_id = claim.person_id
        person_name = claim.name
        role = claim.role
        joinedAt = Date()
    }

    func leaveCompany() {
        for k in ["person_id", "person_name", "board_id", "board_name", "api_base", "joined_at"] { d.removeObject(forKey: k) }
        persist = false
        person_id = ""; person_name = ""; board_id = ""; board_name = ""; api_base = ""; joinedAt = nil
        persist = true
    }

    /// `--demo-day` with nothing joined: the storyboard's identity, in memory only (the mock board on :8787).
    func useDemoIdentity() {
        persist = false
        api_base = "http://localhost:8787"
        board_id = "northwind"; board_name = "Northwind Fitness"
        person_id = "pm-1"; person_name = "Dana Whitfield"; role = .PM
        persist = true
        demoIdentity = true
    }

    /// The key is handed to the namer only; it is never logged or shown.
    func resolvedAPIKey() -> String? {
        ClaudeNamer.resolveKey(settingsKey: Keychain.readString(AppSettings.apiKeyAccount))
    }

    func storeAPIKey(_ key: String) {
        try? Keychain.writeString(AppSettings.apiKeyAccount, key.trimmingCharacters(in: .whitespacesAndNewlines))
        apiKeyPresent = resolvedAPIKey() != nil
    }

    var isPaused: Bool { if let p = pausedUntil { return p > Date() } else { return false } }

    var eodString: String { String(format: "%02d:%02d", eodHour, eodMinute) }
}
