import AppKit
import ApplicationServices
import FlowlineCore

/// Samples once per second: frontmost app, focused window title (Accessibility), idle seconds,
/// browser URL host (Safari / Chrome, AppleScript, optional). Titles are hashed and name-masked
/// before they are stored. Never screenshots, message text, file contents or keystrokes.
final class Observer {
    var onEvent: ((Event, _ handsOn: Bool) -> Void)?
    var noteBrowserSites: () -> Bool = { true }
    var isPaused: () -> Bool = { false }

    private var timer: Timer?
    private var lastHostFetch = Date.distantPast
    private var lastHostTitle = ""
    private var cachedHost: String?
    private(set) var accessibilityTrusted = false

    static let browsers: Set<String> = ["Safari", "Google Chrome", "Arc", "Brave Browser", "Microsoft Edge", "Chromium"]

    func requestAccessibility(prompt: Bool) {
        let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: prompt] as CFDictionary
        accessibilityTrusted = AXIsProcessTrustedWithOptions(opts)
    }

    func start() {
        stop()
        let t = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in self?.sample() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    func stop() { timer?.invalidate(); timer = nil }

    private func sample() {
        if isPaused() { return }
        guard let app = NSWorkspace.shared.frontmostApplication else { return }
        let name = app.localizedName ?? app.bundleIdentifier ?? "unknown"
        if !accessibilityTrusted { accessibilityTrusted = AXIsProcessTrusted() }
        let title = accessibilityTrusted ? focusedWindowTitle(pid: app.processIdentifier) : ""
        let idle = Int(Observer.idleSeconds())

        var host: String?
        if Observer.browsers.contains(name), noteBrowserSites() {
            let now = Date()
            if now.timeIntervalSince(lastHostFetch) > 5 || title != lastHostTitle {
                cachedHost = browserHost(app: name)
                lastHostFetch = now; lastHostTitle = title
            }
            host = cachedHost
        }

        let mask = Privacy.maskNames(title)
        let event = Event(ts: ISO.string(Date()), app: name, title_hash: Canonical.sha256Hex(title),
                          title_masked: mask.text, file_hint: mask.hadName ? "client file" : nil,
                          idle_s: idle, url_host: host)
        let handsOn = idle < 300 && !Privacy.isDeniedApp(name) && !Privacy.isDeniedHost(host)
        onEvent?(event, handsOn)
    }

    private func focusedWindowTitle(pid: pid_t) -> String {
        let appEl = AXUIElementCreateApplication(pid)
        var win: CFTypeRef?
        guard AXUIElementCopyAttributeValue(appEl, kAXFocusedWindowAttribute as CFString, &win) == .success, let w = win else { return "" }
        var title: CFTypeRef?
        guard AXUIElementCopyAttributeValue(w as! AXUIElement, kAXTitleAttribute as CFString, &title) == .success else { return "" }
        return (title as? String) ?? ""
    }

    static func idleSeconds() -> TimeInterval {
        let types: [CGEventType] = [.keyDown, .mouseMoved, .leftMouseDown, .rightMouseDown, .scrollWheel, .flagsChanged, .leftMouseDragged]
        return types.map { CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: $0) }.min() ?? 0
    }

    private func browserHost(app: String) -> String? {
        let source: String
        switch app {
        case "Safari": source = "tell application \"Safari\" to if (count of windows) > 0 then return URL of front document"
        case "Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium", "Arc":
            source = "tell application \"\(app)\" to if (count of windows) > 0 then return URL of active tab of front window"
        default: return nil
        }
        var err: NSDictionary?
        guard let script = NSAppleScript(source: source) else { return nil }
        let out = script.executeAndReturnError(&err)
        guard err == nil, let s = out.stringValue, let url = URL(string: s) else { return nil }
        return url.host?.lowercased()
    }
}
