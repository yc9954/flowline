import Foundation
import Combine
import FlowlineCore

/// User settings. Plain values live in UserDefaults; the API key lives in the keychain only.
final class AppSettings: ObservableObject {
    static let apiKeyAccount = "anthropic-api-key"
    private let d = UserDefaults.standard

    @Published var person_id: String { didSet { d.set(person_id, forKey: "person_id") } }
    @Published var role: Role { didSet { d.set(role.rawValue, forKey: "role") } }
    @Published var board_id: String { didSet { d.set(board_id, forKey: "board_id") } }
    @Published var api_base: String { didSet { d.set(api_base, forKey: "api_base") } }
    @Published var eodHour: Int { didSet { d.set(eodHour, forKey: "eod_hour") } }
    @Published var eodMinute: Int { didSet { d.set(eodMinute, forKey: "eod_minute") } }
    @Published var demoMode: Bool { didSet { d.set(demoMode, forKey: "demo_mode") } }
    @Published var noteBrowserSites: Bool { didSet { d.set(noteBrowserSites, forKey: "note_browser") } }
    @Published var pausedUntil: Date? { didSet { d.set(pausedUntil, forKey: "paused_until") } }
    @Published var apiKeyPresent: Bool

    var boardName: String {
        switch board_id { case "northwind": return "Northwind Fitness"; default: return board_id }
    }

    init() {
        person_id = d.string(forKey: "person_id") ?? "pm-1"
        role = Role(rawValue: d.string(forKey: "role") ?? "PM") ?? .PM
        board_id = d.string(forKey: "board_id") ?? "northwind"
        api_base = d.string(forKey: "api_base") ?? "http://localhost:8787"
        eodHour = d.object(forKey: "eod_hour") as? Int ?? 18
        eodMinute = d.object(forKey: "eod_minute") as? Int ?? 0
        demoMode = d.bool(forKey: "demo_mode")
        noteBrowserSites = d.object(forKey: "note_browser") as? Bool ?? false
        pausedUntil = d.object(forKey: "paused_until") as? Date
        apiKeyPresent = !(ProcessInfo.processInfo.environment["ANTHROPIC_API_KEY"] ?? "").isEmpty
            || Keychain.readString(AppSettings.apiKeyAccount)?.isEmpty == false
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
