import SwiftUI
import FlowlineCore

/// The dropdown under the menu-bar icon (Main.dc.html).
struct MenuPanelView: View {
    @EnvironmentObject var c: AppController

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 10) {
                MarkBadge(size: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Flowline").font(Theme.sans(15, .semibold)).foregroundStyle(.black)
                    Text(c.settings.isJoined ? c.settings.headerLine : "Not joined to a company yet").font(Theme.sans(12)).foregroundStyle(Theme.mutedText)
                        .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Chip(text: c.settings.isJoined ? "On this Mac" : "Set up", fg: c.settings.isJoined ? Theme.teal : Theme.amber,
                     bg: (c.settings.isJoined ? Theme.teal : Theme.amber).opacity(0.08))
            }
            .padding(.horizontal, 14).padding(.top, 14).padding(.bottom, 12)

            Rectangle().fill(Color.black).frame(height: 1).padding(.horizontal, 14)

            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 6) {
                    MonoLabel("Noted today")
                    Text(Fmt.hm(c.notedTodayMinutes)).font(Theme.stat(26)).foregroundStyle(.black).monospacedDigit()
                }.frame(maxWidth: .infinity, alignment: .leading)
                VHairline().frame(height: 48)
                VStack(alignment: .leading, spacing: 6) {
                    MonoLabel("Sent to team")
                    Text("\(c.sentToday)").font(Theme.stat(26)).foregroundStyle(.black).monospacedDigit()
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 16)
            }
            .padding(.horizontal, 14).padding(.vertical, 12)

            Text("Nothing leaves this Mac until you approve today’s record.")
                .font(Theme.sans(11.5)).foregroundStyle(Theme.mutedText).lineSpacing(2)
                .padding(.horizontal, 14).padding(.bottom, 10)

            // Primary row
            Button { c.openReview() } label: {
                HStack {
                    Text("Review today’s work…").font(Theme.sans(13, .semibold)).foregroundStyle(.white)
                    Spacer()
                    HStack(spacing: 5) {
                        SquareDot(color: c.draft == nil ? Theme.yellow : Theme.teal, size: 6)
                        Text(c.drafting ? "DRAFTING" : (c.draft == nil ? "DRAFT AT \(c.settings.eodString)" : "READY"))
                            .font(Theme.mono(9.5)).tracking(1).foregroundStyle(.white)
                    }
                }
                .padding(.horizontal, 12).frame(height: 32)
                .background(RoundedRectangle(cornerRadius: 3).fill(Color.black))
                .contentShape(Rectangle())
            }.buttonStyle(.plain).padding(.horizontal, 8)

            row(c.settings.isPaused ? "Resume noting" : "Pause for 1 hour", kbd: "⌃⌘P") { c.settings.isPaused ? c.resume() : c.pauseOneHour() }
            row("What Flowline never keeps", kbd: nil) {
                c.showNeverKeeps.toggle(); c.resizeMenuPanel()
            }
            if c.showNeverKeeps {
                VStack(alignment: .leading, spacing: 8) {
                    FlowChips(items: Privacy.neverKept)
                    Text("Only app names, name-masked window titles and durations are noted, and they stay on this Mac until you approve a record.")
                        .font(Theme.sans(11)).foregroundStyle(Theme.mutedText).lineSpacing(2)
                }.padding(.horizontal, 14).padding(.vertical, 8)
            }
            Hairline().padding(.horizontal, 14).padding(.vertical, 4)
            row("Settings…", kbd: "⌘ ,") { c.openSettings() }
            Hairline().padding(.horizontal, 14).padding(.vertical, 4)
            HStack(spacing: 8) {
                SquareDot(color: c.settings.isPaused ? Theme.amber : Theme.teal, size: 7)
                Text(c.observerStatus).font(Theme.sans(11.5)).foregroundStyle(Theme.mutedText)
                Spacer()
                Button("Quit") { c.quit() }.buttonStyle(.plain).font(Theme.sans(11)).foregroundStyle(Theme.mutedText.opacity(0.7))
            }.padding(.horizontal, 14).padding(.vertical, 8)
            Spacer(minLength: 0)
        }
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.hairline, lineWidth: 1))
        .padding(1)
    }

    func row(_ title: String, kbd: String?, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                Text(title).font(Theme.sans(13)).foregroundStyle(.black)
                Spacer()
                if let k = kbd { Kbd(text: k) }
            }
            .padding(.horizontal, 12).frame(height: 28).contentShape(Rectangle())
        }
        .buttonStyle(HoverRowStyle()).padding(.horizontal, 8)
    }
}

struct HoverRowStyle: ButtonStyle {
    @State private var hover = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(RoundedRectangle(cornerRadius: 3).fill(hover || configuration.isPressed ? Theme.muted2 : Color.clear))
            .onHover { hover = $0 }
    }
}

/// Outlined "⊘ Label" chips that wrap.
struct FlowChips: View {
    var items: [String]
    var body: some View {
        let rows = stride(from: 0, to: items.count, by: 2).map { Array(items[$0..<min($0 + 2, items.count)]) }
        VStack(alignment: .leading, spacing: 8) {
            ForEach(rows.indices, id: \.self) { r in
                HStack(spacing: 8) {
                    ForEach(rows[r], id: \.self) { item in
                        HStack(spacing: 6) {
                            Image(systemName: "nosign").font(.system(size: 10, weight: .medium))
                            Text(item).font(Theme.mono(10.5))
                        }
                        .foregroundStyle(Theme.ink)
                        .padding(.horizontal, 9).padding(.vertical, 6)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(Theme.hairline, lineWidth: 1))
                    }
                }
            }
        }
    }
}
