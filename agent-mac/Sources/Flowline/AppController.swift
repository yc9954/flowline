import AppKit
import SwiftUI
import Combine
import Carbon.HIToolbox
import FlowlineCore

/// One object owns the state and the surfaces: menu-bar panel, notch, review window, agent panel.
@MainActor
final class AppController: NSObject, ObservableObject {
    let settings = AppSettings()
    let store = EventStore()
    let observer = Observer()
    lazy var signer = Signer(supportDir: store.root)
    var api: APIClient { APIClient(base: settings.api_base) }

    // Launch options
    var demoDay = false
    var eodNow = false

    // Published state
    @Published var draft: DraftDay?
    @Published var drafting = false
    @Published var record: FlowlineCore.Record?
    @Published var recordPosted = false
    @Published var recordWithdrawn = false
    @Published var postedAt: Date?
    @Published var approveError: String?
    @Published var handsOnTodaySeconds: Int = 0
    @Published var sentToday: Int = 0
    @Published var suggestion: Suggestion?
    @Published var run: Run?
    @Published var runTitle: String = ""
    @Published var runFinished = false
    @Published var runElapsed: Int = 0
    @Published var runError: String?
    @Published var showNeverKeeps = false
    /// Screens an agent is working on right now, shown in the CLOSED notch ("1 screen"). Counts the runs this app
    /// started. TODO: wire the fleet count from the API (runs on every desk for this person) once it exposes one.
    @Published var activeScreens: Int = 0
    @Published var observerStatus = "Noting work steps locally"

    // Surfaces
    var statusItem: NSStatusItem!
    var menuPanel: FloatingPanel?
    let notch = NotchPanel()
    let border = ScreenBorderWindow()
    var reviewWindow: NSWindow?
    var settingsWindow: NSWindow?

    private var eodTimer: Timer?
    private var pollTimer: Timer?
    private var runTimer: Timer?
    private var runStarted: Date?
    private var dismissedSuggestions = Set<String>()
    private var eodShownFor: String?
    private var snoozedUntil: Date?
    private var clickMonitor: Any?
    private var cancellables = Set<AnyCancellable>()
    private var hotKeyRef: EventHotKeyRef?
    private var debugTimer: Timer?

    var today: String { demoDay ? "2026-11-06" : ISO.day(Date()) }

    // MARK: Lifecycle

    func start() {
        let args = CommandLine.arguments
        demoDay = args.contains("--demo-day") || settings.demoMode
        eodNow = args.contains("--eod-now")

        setupStatusItem()
        registerHotKey()
        loadSentToday()
        notch.setRoot(NotchRootView(notch: notch).environmentObject(self))

        if !args.contains("--no-observe") {
            observer.requestAccessibility(prompt: !demoDay)
            observer.noteBrowserSites = { [weak self] in self?.settings.noteBrowserSites ?? false }
            observer.isPaused = { [weak self] in self?.settings.isPaused ?? false }
            observer.onEvent = { [weak self] e, handsOn in self?.record(e, handsOn: handsOn) }
            seedHandsOn()
            observer.start()
        }

        eodTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in Task { @MainActor in self?.checkEndOfDay() } }
        pollTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in Task { @MainActor in await self?.pollSuggestions() } }

        settings.$pausedUntil.sink { [weak self] _ in self?.refreshStatus() }.store(in: &cancellables)
        settings.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &cancellables)

        if args.contains("--debug-control") { installDebugControl() }
        if demoDay { Task { await prepareDraft() } }
        if eodNow { Task { await prepareDraft(); showEndOfDayBanner() } }
    }

    private func record(_ e: Event, handsOn: Bool) {
        store.append(e, day: ISO.day(Date()))
        if handsOn { handsOnTodaySeconds += 1 }
    }

    private func seedHandsOn() {
        let events = store.events(day: ISO.day(Date()))
        handsOnTodaySeconds = events.filter { $0.idle_s < 300 && !Privacy.isDeniedApp($0.app) && !Privacy.isDeniedHost($0.url_host) }.count
    }

    private func loadSentToday() {
        let d = UserDefaults.standard
        if d.string(forKey: "sent_day") == today { sentToday = d.integer(forKey: "sent_count") } else { sentToday = 0 }
    }
    private func bumpSent(_ delta: Int) {
        sentToday = max(0, sentToday + delta)
        UserDefaults.standard.set(today, forKey: "sent_day"); UserDefaults.standard.set(sentToday, forKey: "sent_count")
    }

    func refreshStatus() {
        if let p = settings.pausedUntil, p > Date() { observerStatus = "Paused until \(Fmt.clock(p))" }
        else { observerStatus = "Noting work steps locally" }
    }

    var notedTodayMinutes: Int {
        if demoDay, let d = draft { return d.handsOnMinutes + d.waitingMinutes }
        return handsOnTodaySeconds / 60
    }

    // MARK: Status item + menu panel

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: 28)
        if let b = statusItem.button {
            b.image = StatusIcon.image()
            b.imagePosition = .imageOnly
            b.target = self
            b.action = #selector(toggleMenuPanel)
            b.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        refreshStatus()
    }

    @objc func toggleMenuPanel() {
        if let p = menuPanel, p.isVisible { closeMenuPanel(); return }
        openMenuPanel()
    }

    func openMenuPanel() {
        guard let button = statusItem.button, let bw = button.window else { return }
        let size = NSSize(width: 328, height: showNeverKeeps ? 480 : 362)
        let panel = menuPanel ?? FloatingPanel(size: size, level: .popUpMenu)
        panel.setContent(MenuPanelView().environmentObject(self))
        let br = bw.convertToScreen(button.convert(button.bounds, to: nil))
        var x = br.maxX - size.width
        if let s = bw.screen { x = min(x, s.visibleFrame.maxX - size.width - 8); x = max(x, s.visibleFrame.minX + 8) }
        panel.setFrame(NSRect(x: x, y: br.minY - size.height - 6, width: size.width, height: size.height), display: true)
        panel.orderFrontRegardless()
        panel.makeKey()
        button.highlight(true)
        menuPanel = panel
        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor in self?.closeMenuPanel() }
        }
    }

    func closeMenuPanel() {
        menuPanel?.orderOut(nil)
        statusItem.button?.highlight(false)
        if let m = clickMonitor { NSEvent.removeMonitor(m); clickMonitor = nil }
    }

    func resizeMenuPanel() {
        guard let p = menuPanel, p.isVisible else { return }
        let h: CGFloat = showNeverKeeps ? 480 : 362
        var f = p.frame; f.origin.y = f.maxY - h; f.size.height = h
        p.setFrame(f, display: true)
        p.setContent(MenuPanelView().environmentObject(self))
    }

    // MARK: Hotkey (⌃⌘P — a bare ⌘P would take Print from every app)

    private func registerHotKey() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ -> OSStatus in
            DispatchQueue.main.async { AppController.shared?.hotKeyPressed() }
            return noErr
        }, 1, &spec, nil, nil)
        let id = EventHotKeyID(signature: OSType(0x464C574E), id: 1) // 'FLWN'
        RegisterEventHotKey(UInt32(kVK_ANSI_P), UInt32(cmdKey | controlKey), id, GetApplicationEventTarget(), 0, &hotKeyRef)
    }

    static weak var shared: AppController?

    func hotKeyPressed() {
        Task { await prepareDraft(); showEndOfDayBanner() }
    }

    // MARK: Pause

    func pauseOneHour() {
        settings.pausedUntil = Date().addingTimeInterval(3600)
        closeMenuPanel()
    }
    func resume() { settings.pausedUntil = nil; closeMenuPanel() }

    // MARK: Draft + end of day

    func demoEvents() -> [Event] {
        guard let url = Bundle.module.url(forResource: "demo-day", withExtension: "jsonl"),
              let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        let dec = JSONDecoder()
        return text.split(separator: "\n").compactMap { try? dec.decode(Event.self, from: Data($0.utf8)) }
    }

    func prepareDraft(force: Bool = false) async {
        if draft != nil && !force { return }
        drafting = true
        defer { drafting = false }
        let events = demoDay ? demoEvents() : store.events(day: today)
        var history = store.history()
        var namer: Namer?
        if let key = settings.resolvedAPIKey() {
            namer = ClaudeNamer(apiKey: key)
        }
        if demoDay {
            if let url = Bundle.module.url(forResource: "demo-week", withExtension: "json"),
               let d = try? Data(contentsOf: url), let h = try? JSONDecoder().decode([StepHistory].self, from: d) { history += h }
            if namer == nil, let url = Bundle.module.url(forResource: "demo-names", withExtension: "json"),
               let d = try? Data(contentsOf: url), let r = try? JSONDecoder().decode(NamerResponse.self, from: d) {
                namer = TableNamer(response: r)
            }
        }
        let cfg = CompilerConfig(person_id: settings.person_id, role: settings.role, board_id: settings.board_id, date: today)
        let result = await Compiler.compile(events: events, config: cfg, history: history, namer: namer)
        draft = result.draft
        if !demoDay { store.saveHistory(StepHistory(date: today, signatures: result.signatures)) }
        record = nil; recordPosted = false; recordWithdrawn = false; approveError = nil
    }

    private func checkEndOfDay() {
        guard !settings.isPaused, eodShownFor != today else { return }
        if let s = snoozedUntil, s > Date() { return }
        let now = Date()
        let comps = Calendar.current.dateComponents([.hour, .minute], from: now)
        guard let h = comps.hour, let m = comps.minute, h * 60 + m >= settings.eodHour * 60 + settings.eodMinute else { return }
        eodShownFor = today
        Task { await prepareDraft(force: true); showEndOfDayBanner() }
    }

    func showEndOfDayBanner() {
        closeMenuPanel()
        notch.show(.endOfDay, state: .peek)
    }

    func bannerReview() {
        notch.hide()
        openReview()
    }

    func bannerTomorrow() {
        notch.hide()
        var comps = Calendar.current.dateComponents([.year, .month, .day], from: Date())
        comps.day! += 1; comps.hour = 9; comps.minute = 0
        snoozedUntil = Calendar.current.date(from: comps)
        eodShownFor = nil
    }

    // MARK: Review window

    func openReview() {
        NSLog("Flowline openReview (notch state=%@)", "\(notch.state)")
        closeMenuPanel()
        if notch.isShown { notch.hide() }
        if draft == nil { Task { await prepareDraft(); openReview() }; return }
        if reviewWindow == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1260, height: 800),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                             backing: .buffered, defer: false)
            w.title = "End-of-day review"
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.isMovableByWindowBackground = false
            w.backgroundColor = .white
            w.minSize = NSSize(width: 1100, height: 700)
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: ReviewView().environmentObject(self).ignoresSafeArea())
            w.center()
            reviewWindow = w
        }
        NSApp.activate(ignoringOtherApps: true)
        reviewWindow?.makeKeyAndOrderFront(nil)
    }

    func closeReview() {
        reviewWindow?.orderOut(nil)
    }

    // Step editing
    func rename(_ idx: Int, to name: String) {
        guard var d = draft, let i = d.steps.firstIndex(where: { $0.idx == idx }) else { return }
        d.steps[i].name = name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? d.steps[i].name : name
        draft = d
    }
    func toggleShare(_ idx: Int) {
        guard var d = draft, let i = d.steps.firstIndex(where: { $0.idx == idx }) else { return }
        d.steps[i].share.toggle(); draft = d
    }
    func hide(_ idx: Int) {
        guard var d = draft, let i = d.steps.firstIndex(where: { $0.idx == idx }) else { return }
        d.steps[i].share = false; draft = d
    }
    func mergeWithNext(_ idx: Int) {
        guard var d = draft, let i = d.steps.firstIndex(where: { $0.idx == idx }), i + 1 < d.steps.count else { return }
        var a = d.steps[i]; let b = d.steps[i + 1]
        a.end = b.end
        for t in b.tools where !a.tools.contains(t) { a.tools.append(t) }
        if a.kind == .waiting && b.kind == .hands_on { a.kind = .hands_on; a.name = b.name }
        a.case_id = a.case_id ?? b.case_id
        a.handoff_to = a.handoff_to ?? b.handoff_to
        a.repeats = max(a.repeats ?? 0, b.repeats ?? 0) == 0 ? nil : max(a.repeats ?? 0, b.repeats ?? 0)
        d.steps[i] = a
        d.steps.remove(at: i + 1)
        for (n, _) in d.steps.enumerated() { d.steps[n].idx = n + 1 }
        draft = d
    }

    // MARK: Approve and share

    func approveAndShare() async {
        guard let d = draft else { return }
        approveError = nil
        let now = Date()
        let f = DateFormatter(); f.dateFormat = "MMdd"
        let id = "\(f.string(from: now))-\(String(format: "%04d", Int.random(in: 0...9999)))"
        do {
            let unsigned = d.record(id: id, approvedAt: now)
            let sealed = try signer.seal(unsigned)
            record = sealed
            store.saveRecord(sealed)
            let acc = try await api.postRecord(sealed)
            if acc.accepted {
                recordPosted = true
                postedAt = Date()
                bumpSent(1)
                if !demoDay { store.deleteDay(today) }
            } else {
                approveError = "The board did not accept the record."
            }
        } catch {
            record = nil
            approveError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func withdraw() async {
        guard let r = record else { return }
        do {
            try await api.deleteRecord(board: r.board_id, id: r.id)
            recordWithdrawn = true
            bumpSent(-1)
        } catch {
            approveError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func recordDone() {
        closeReview()
        record = nil
        if !demoDay { draft = nil }
    }

    // MARK: Suggestions + runs

    private func pollSuggestions() async {
        guard suggestion == nil, run == nil, !settings.isPaused else { return }
        let list: [Suggestion]
        do { list = try await api.suggestions(person: settings.person_id) }
        catch { NSLog("Flowline suggestions: %@", (error as? LocalizedError)?.errorDescription ?? "\(error)"); return }
        NSLog("Flowline suggestions: %d offered=%d dismissed=%d", list.count, list.filter { $0.status == .offered }.count, dismissedSuggestions.count)
        if let s = list.first(where: { $0.status == .offered && !dismissedSuggestions.contains($0.id) }) {
            suggestion = s
            notch.show(.suggestion, state: .peek)
            NSLog("Flowline suggestion notch shown=%d frame=%@", notch.isShown ? 1 : 0, NSStringFromRect(notch.panel.frame))
        }
    }

    func suggestionAnswer(_ answer: SuggestionAnswer) {
        guard let s = suggestion else { return }
        dismissedSuggestions.insert(s.id)
        if answer != .do_it { notch.hide() }
        Task {
            try? await api.respond(id: s.id, answer: answer)
            if answer == .do_it { await startRun(for: s) } else { suggestion = nil }
        }
    }

    /// Optimistic: the panel and the screen border appear at once (step 1 "now", elapsed 0:00); the POST may take
    /// a while because the executor opens the deck before answering. Polling starts as soon as the id arrives.
    private func startRun(for s: Suggestion) async {
        runTitle = AppController.runTitle(from: s.title)
        runFinished = false
        runError = nil
        runElapsed = 0
        runStarted = Date()
        run = Run(id: "", skill_id: s.skill_id, target: "mac", status: .running, started_at: ISO.string(Date()), elapsed_s: 0,
                  steps: [RunStep(n: 1, label: "Starting", detail: "Asking the executor to begin", status: .now, progress: nil, at_s: nil)],
                  checks: [], title: nil)
        activeScreens += 1
        statusItem.button?.image = StatusIcon.image(running: true)
        border.show()
        notch.running = true
        notch.show(.agent, state: .open)
        runTimer?.invalidate()
        runTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in Task { @MainActor in await self?.pollRun() } }
        do {
            let r = try await api.createRun(s)
            guard !runFinished else { return } // Stop was pressed while the POST was in flight
            run = r
            if let t = r.title, !t.isEmpty { runTitle = t }
        } catch {
            runError = "Couldn’t start — " + ((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            finishRun()
        }
    }

    static func runTitle(from title: String) -> String {
        var t = title.trimmingCharacters(in: CharacterSet(charactersIn: "?! "))
        if let r = t.range(of: "Fill ") , r.lowerBound == t.startIndex { t = t.replacingCharacters(in: r, with: "Filling ") }
        else if let r = t.range(of: "Send "), r.lowerBound == t.startIndex { t = t.replacingCharacters(in: r, with: "Sending ") }
        else if let r = t.range(of: "Copy "), r.lowerBound == t.startIndex { t = t.replacingCharacters(in: r, with: "Copying ") }
        return t
    }

    private func pollRun() async {
        guard let r = run, !runFinished else { return }
        if let s = runStarted { runElapsed = Int(Date().timeIntervalSince(s)) }
        guard !r.id.isEmpty, let fresh = try? await api.run(id: r.id) else { return }
        run = fresh
        if let t = fresh.title, !t.isEmpty { runTitle = t }
        if fresh.status != .running { finishRun() }
    }

    func stopRun() {
        guard let r = run else { return }
        Task {
            if !r.id.isEmpty { try? await api.stop(id: r.id) }
            if var cur = run { cur.status = .stopped; run = cur }
            finishRun()
        }
    }

    private func finishRun() {
        guard !runFinished else { return }   // two overlapping polls can both see the final status
        runTimer?.invalidate(); runTimer = nil
        runFinished = true
        activeScreens = max(0, activeScreens - 1)
        border.hide()
        statusItem.button?.image = StatusIcon.image()
        notch.running = false
        notch.show(.agent, state: .open)
        let finished = run?.id
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
            guard let self, self.runFinished, self.run?.id == finished else { return }
            self.dismissRun()
        }
    }

    /// "Dismiss" on the finished panel, also the 4 s autocollapse.
    func dismissRun() {
        notch.hide { Task { @MainActor in self.run = nil; self.suggestion = nil } }
    }

    /// 0…1 across the run's steps, for the 2-pt progress line in the CLOSED notch.
    var runProgress: CGFloat {
        guard let steps = run?.steps, !steps.isEmpty else { return 0 }
        if runFinished { return 1 }
        var done: CGFloat = 0
        for s in steps {
            switch s.status {
            case .done: done += 1
            case .now:
                if let p = s.progress, p.count == 2, p[1] > 0 { done += CGFloat(p[0]) / CGFloat(p[1]) } else { done += 0.5 }
            case .pending: break
            }
        }
        return min(1, max(0.04, done / CGFloat(steps.count)))
    }

    // MARK: Settings window

    func openSettings() {
        closeMenuPanel()
        if settingsWindow == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 580),
                             styleMask: [.titled, .closable], backing: .buffered, defer: false)
            w.title = "Flowline Settings"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: SettingsView(settings: settings).environmentObject(self))
            w.center()
            settingsWindow = w
        }
        NSApp.activate(ignoringOtherApps: true)
        settingsWindow?.makeKeyAndOrderFront(nil)
    }

    func quit() { NSApp.terminate(nil) }

    // MARK: Debug control (only with --debug-control): `scripts/drive.sh <command>` posts a distributed notification.

    private func installDebugControl() {
        let url = store.root.appendingPathComponent("debug-command")
        try? FileManager.default.removeItem(at: url)
        debugTimer = Timer.scheduledTimer(withTimeInterval: 0.4, repeats: true) { [weak self] _ in
            guard let cmd = try? String(contentsOf: url, encoding: .utf8) else { return }
            try? FileManager.default.removeItem(at: url)
            Task { @MainActor in await self?.debug(cmd.trimmingCharacters(in: .whitespacesAndNewlines)) }
        }
    }

    private func debug(_ cmd: String) async {
        NSLog("Flowline debug command: %@", cmd)
        switch cmd {
        case "banner": await prepareDraft(); showEndOfDayBanner()
        case "menu": openMenuPanel()
        case "review": openReview()
        case "approve": await approveAndShare()
        case "withdraw": await withdraw()
        case "done": recordDone()
        case "settings": openSettings()
        case "poll": await pollSuggestions()
        case "do-it": suggestionAnswer(.do_it)
        case "not-now": suggestionAnswer(.not_now)
        case "stop": stopRun()
        case "redraft": await prepareDraft(force: true)
        case "hide-notch": notch.hide()
        case "notch-closed": notch.collapse()
        case "notch-peek": notch.setState(.peek)
        case "notch-open": notch.expand()
        case "glow-on": border.show()       // the edge glow alone, for filming / measuring without an executor run
        case "glow-off": border.hide()
        default: break
        }
    }
}
