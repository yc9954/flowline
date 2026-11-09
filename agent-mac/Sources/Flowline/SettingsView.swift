import SwiftUI
import FlowlineCore

struct SettingsView: View {
    @EnvironmentObject var c: AppController
    @ObservedObject var settings: AppSettings
    @State private var apiKey = ""
    @State private var keySaved = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 10) {
                MarkBadge(size: 30)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Settings").font(Theme.sans(15, .semibold))
                    Text("Who this Mac notes for, and where approved records go.").font(Theme.sans(12)).foregroundStyle(Theme.mutedText)
                }
            }
            section("Person") {
                field("Person id", text: $settings.person_id)
                HStack { MonoLabel("Role").frame(width: 110, alignment: .leading)
                    Picker("", selection: $settings.role) { ForEach(Role.allCases, id: \.self) { Text($0.rawValue).tag($0) } }
                        .labelsHidden().frame(width: 160) }
                field("Board id", text: $settings.board_id)
            }
            section("Board API") {
                field("API base", text: $settings.api_base)
            }
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
        .frame(width: 460, height: 580)
        .background(Color.white)
    }

    func section<V: View>(_ title: String, @ViewBuilder _ content: () -> V) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel(title)
            Hairline()
            content()
        }
    }

    func field(_ label: String, text: Binding<String>) -> some View {
        HStack { MonoLabel(label).frame(width: 110, alignment: .leading); TextField("", text: text).textFieldStyle(.roundedBorder).frame(width: 220) }
    }
}
