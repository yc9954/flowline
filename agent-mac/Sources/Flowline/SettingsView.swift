import SwiftUI
import FlowlineCore

struct SettingsView: View {
    @EnvironmentObject var c: AppController
    @ObservedObject var settings: AppSettings
    @State private var apiKey = ""
    @State private var keySaved = false
    @State private var showManual = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 10) {
                MarkBadge(size: 30)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Settings").font(Theme.sans(15, .semibold))
                    Text("Who this Mac notes for, and where approved records go.").font(Theme.sans(12)).foregroundStyle(Theme.mutedText)
                }
            }
            joinSection
            section("Step names") {
                HStack(alignment: .center) {
                    MonoLabel("Anthropic key").frame(width: 110, alignment: .leading)
                    SecureField(settings.apiKeyPresent ? "Set (env or keychain)" : "sk-ant-… (optional)", text: $apiKey)
                        .textFieldStyle(.roundedBorder).frame(width: 220)
                    Button(keySaved ? "Saved" : "Save") { c.settings.storeAPIKey(apiKey); apiKey = ""; keySaved = true }
                        .buttonStyle(OutlineButtonStyle(height: 24)).disabled(apiKey.isEmpty)
                }
                Text("Model: \(ClaudeNamer.defaultModel) (env FLOWLINE_MODEL). The key lives in the keychain and only app names, masked titles and durations are sent. Without a key, steps get rule-based names.")
                    .font(Theme.sans(11)).foregroundStyle(Theme.mutedText).fixedSize(horizontal: false, vertical: true)
            }
            section("End of day") {
                HStack {
                    MonoLabel("Review at").frame(width: 110, alignment: .leading)
                    Picker("", selection: $settings.eodHour) { ForEach(6..<24, id: \.self) { Text(String(format: "%02d", $0)).tag($0) } }.labelsHidden().frame(width: 70)
                    Text(":").font(Theme.mono(12))
                    Picker("", selection: $settings.eodMinute) { ForEach([0, 15, 30, 45], id: \.self) { Text(String(format: "%02d", $0)).tag($0) } }.labelsHidden().frame(width: 70)
                    Button("Show now") { c.hotKeyPressed() }.buttonStyle(OutlineButtonStyle(height: 24))
                }
                Toggle("Note browser site names (asks once per browser)", isOn: $settings.noteBrowserSites).font(Theme.sans(12.5))
                Toggle("Demo day (loads the storyboard day instead of today)", isOn: $settings.demoMode).font(Theme.sans(12.5))
                    .onChange(of: c.settings.demoMode) { _, v in c.demoDay = v; Task { await c.prepareDraft(force: true) } }
                HStack(spacing: 10) {
                    Button(c.settings.isPaused ? "Resume noting" : "Pause for 1 hour") { c.settings.isPaused ? c.resume() : c.pauseOneHour() }
                        .buttonStyle(OutlineButtonStyle(height: 24))
                    Text(c.observerStatus).font(Theme.sans(12)).foregroundStyle(Theme.mutedText)
                }
            }
            HStack(spacing: 6) {
                Text("Device key: \(c.signer.source) · \(c.signer.pubkeyBase64.prefix(12))…").font(Theme.mono(10)).foregroundStyle(Theme.mutedText)
                Spacer()
                Text("Hotkey ⌃⌘P shows the end-of-day banner").font(Theme.mono(10)).foregroundStyle(Theme.mutedText)
            }
            Spacer()
        }
        .padding(22)
        .frame(width: 460, height: 640)
        .background(Color.white)
    }

    // MARK: Join a company

    @ViewBuilder var joinSection: some View {
        section("Join a company") {
            if settings.isJoined && !c.joinEditing {
                HStack(alignment: .top, spacing: 10) {
                    SquareDot(color: settings.demoIdentity ? Theme.amber : Theme.teal, size: 7).padding(.top, 5)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(settings.headerLine).font(Theme.sans(13, .semibold))
                        Text("\(settings.role.rawValue) · \(settings.person_id) on \(settings.board_id)").font(Theme.mono(10.5)).foregroundStyle(Theme.mutedText)
                        Text(settings.demoIdentity ? "Demo identity (not saved) · \(settings.api_base)" : "\(settings.api_base)\(settings.joinedAt.map { " · joined \(Fmt.clock($0))" } ?? "")")
                            .font(Theme.mono(10.5)).foregroundStyle(Theme.mutedText)
                    }
                    Spacer()
                    Button("Change…") { c.joinEditing = true }.buttonStyle(OutlineButtonStyle(height: 24))
                }
            } else {
                field("API address", text: $c.joinAPI, placeholder: "http://localhost:8787")
                HStack {
                    MonoLabel("Invite code").frame(width: 110, alignment: .leading)
                    TextField("from your invite mail", text: $c.joinCode).textFieldStyle(.roundedBorder).frame(width: 220)
                        .onSubmit { Task { await c.join() } }
                    Button(c.joining ? "Joining…" : "Join") { Task { await c.join() } }
                        .buttonStyle(BlackButtonStyle(height: 24)).disabled(c.joining || c.joinAPI.isEmpty || c.joinCode.isEmpty)
                }
                if let e = c.joinError {
                    Text(e).font(Theme.sans(11.5)).foregroundStyle(Theme.amber).fixedSize(horizontal: false, vertical: true)
                } else {
                    Text("Your invite names the board, who you are on it and your role; this Mac keeps them and nothing else. The link form is flowline://join?api=…&code=….")
                        .font(Theme.sans(11)).foregroundStyle(Theme.mutedText).fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 10) {
                    if settings.isJoined { Button("Cancel") { c.joinEditing = false; c.joinError = nil }.buttonStyle(OutlineButtonStyle(height: 24)) }
                    if settings.isJoined && !settings.demoIdentity { Button("Leave company") { c.leaveCompany() }.buttonStyle(OutlineButtonStyle(height: 24)) }
                    Spacer()
                    Button(showManual ? "Hide manual setup" : "Manual setup…") { showManual.toggle() }.buttonStyle(.plain).font(Theme.sans(11.5)).foregroundStyle(Theme.mutedText)
                }
                if showManual {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Without an invite (developers): the same fields, typed by hand.").font(Theme.sans(11)).foregroundStyle(Theme.mutedText)
                        field("Person id", text: $settings.person_id)
                        field("Your name", text: $settings.person_name)
                        HStack { MonoLabel("Role").frame(width: 110, alignment: .leading)
                            Picker("", selection: $settings.role) { ForEach(Role.allCases, id: \.self) { Text($0.rawValue).tag($0) } }
                                .labelsHidden().frame(width: 160) }
                        field("Board id", text: $settings.board_id)
                        field("Board name", text: $settings.board_name)
                        field("API base", text: $settings.api_base)
                    }
                }
            }
        }
    }

    func section<V: View>(_ title: String, @ViewBuilder _ content: () -> V) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel(title)
            Hairline()
            content()
        }
    }

    func field(_ label: String, text: Binding<String>, placeholder: String = "") -> some View {
        HStack { MonoLabel(label).frame(width: 110, alignment: .leading); TextField(placeholder, text: text).textFieldStyle(.roundedBorder).frame(width: 220) }
    }
}
