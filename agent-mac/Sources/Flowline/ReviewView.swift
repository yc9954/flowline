import SwiftUI
import FlowlineCore

/// End-of-day review window (Review.dc.html), 1260×800.
struct ReviewView: View {
    @EnvironmentObject var c: AppController
    @State private var editing = false
    @State private var search = ""
    @State private var savedAt = Date()

    var draft: DraftDay { c.draft ?? DraftDay(person_id: "", role: .PM, date: c.today, board_id: "", steps: [], left_out: [], summary: "") }

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                header
                Hairline()
                HStack(spacing: 0) {
                    mainColumn
                    VHairline()
                    LeftOutColumn(draft: draft).frame(width: 340)
                }
            }
            .background(Color.white)
            if let r = c.record {
                RecordSheet(record: r).environmentObject(c)
            }
        }
        .frame(minWidth: 1100, minHeight: 700)
    }

    // MARK: Header

    var header: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                Text("End-of-day review").font(Theme.sans(13, .semibold)).foregroundStyle(.black)
                Text("Draft · saved \(Fmt.clock(savedAt))").font(Theme.mono(10)).foregroundStyle(Theme.mutedText)
            }
            .padding(.leading, 100)
            Spacer()
            HStack(spacing: 0) {
                Image(systemName: "chevron.left").font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.mutedText).frame(width: 30, height: 30)
                VHairline().frame(height: 30)
                HStack(spacing: 8) {
                    Text(Fmt.shortDay(draft.date)).font(Theme.sans(13, .medium)).foregroundStyle(.black)
                    Text("TODAY").font(Theme.mono(9)).tracking(1).foregroundStyle(Theme.teal)
                }.padding(.horizontal, 14)
                VHairline().frame(height: 30)
                Image(systemName: "chevron.right").font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.mutedText).frame(width: 30, height: 30)
            }
            .overlay(RoundedRectangle(cornerRadius: 3).stroke(Theme.hairline, lineWidth: 1))
            Spacer()
            HStack(spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").font(.system(size: 11)).foregroundStyle(Theme.mutedText)
                    TextField("Search steps", text: $search).textFieldStyle(.plain).font(Theme.sans(12.5))
                    Kbd(text: "⌘F")
                }
                .padding(.horizontal, 10).frame(width: 200, height: 30)
                .overlay(RoundedRectangle(cornerRadius: 3).stroke(Theme.hairline, lineWidth: 1))
                Button { c.openSettings() } label: {
                    HStack(spacing: 6) { Image(systemName: "gearshape").font(.system(size: 11)); Text("Settings") }
                }.buttonStyle(OutlineButtonStyle(height: 30))
            }
            .padding(.trailing, 16)
        }
        .frame(height: 56)
    }

    // MARK: Main column

    var filteredSteps: [DraftStep] {
        search.isEmpty ? draft.steps : draft.steps.filter { $0.name.localizedCaseInsensitiveContains(search) || $0.tools.joined().localizedCaseInsensitiveContains(search) }
    }

    var mainColumn: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 14) {
                        MonoLabel("End of day · Drafted on this Mac")
                        Hairline()
                        MonoLabel("\(draft.role.rawValue) · \(c.settings.boardName)")
                    }
                    .padding(.top, 28)
                    Text(draft.summary)
                        .font(Theme.sans(30, .semibold)).tracking(-0.5).lineSpacing(2)
                        .foregroundStyle(.black).fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 14)
                    Text("Check the steps. Rename, merge or remove anything. Only what you approve goes to your team’s board.")
                        .font(Theme.sans(15)).foregroundStyle(Theme.mutedText).padding(.top, 10)

                    TimelineBar(steps: draft.steps).padding(.top, 22)

                    stepTable.padding(.top, 22)
                    Spacer(minLength: 20)
                }
                .padding(.horizontal, 40)
            }
            Hairline()
            bottomBar
        }
    }

    var stepTable: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                MonoLabel("Time").frame(width: 100, alignment: .leading)
                MonoLabel("App").frame(width: 56, alignment: .leading)
                MonoLabel("Step")
                Spacer()
                MonoLabel("Took").frame(width: 70, alignment: .trailing)
                MonoLabel("Share").frame(width: 60, alignment: .trailing)
            }
            .padding(.horizontal, 18).frame(height: 34)
            .background(Theme.card)
            ForEach(filteredSteps) { step in
                Hairline()
                StepRow(step: step, editing: editing, isLast: step.idx == draft.steps.last?.idx).environmentObject(c)
            }
        }
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.hairline, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    var bottomBar: some View {
        let shared = draft.steps.filter(\.share).count
        return HStack(spacing: 14) {
            LockIcon(size: 32, dark: true)
            VStack(alignment: .leading, spacing: 3) {
                Text("Nothing leaves this Mac until you approve.").font(Theme.sans(14, .semibold)).foregroundStyle(.black)
                if let err = c.approveError {
                    Text(err).font(Theme.sans(12.5)).foregroundStyle(Theme.red)
                } else {
                    Text("\(shared) of \(draft.steps.count) steps go to the \(c.settings.boardName) board. Editable until tomorrow 09:00.")
                        .font(Theme.sans(12.5)).foregroundStyle(Theme.mutedText)
                }
            }
            Spacer()
            Button(editing ? "Done editing" : "Edit steps") { editing.toggle() }.buttonStyle(OutlineButtonStyle())
            Button { Task { await c.approveAndShare() } } label: {
                HStack(spacing: 10) { Text("Approve and share"); Kbd(text: "⌘↵", dark: true) }
            }
            .buttonStyle(BlackButtonStyle())
            .keyboardShortcut(.return, modifiers: .command)
            .disabled(shared == 0)
        }
        .padding(.horizontal, 40).frame(height: 80)
    }
}

// MARK: - Timeline

struct TimelineBar: View {
    var steps: [DraftStep]

    var total: Double { max(1, steps.reduce(0) { $0 + Double($1.minutes) }) }
    func color(_ s: DraftStep) -> Color {
        if s.kind == .waiting { return Theme.yellow }
        if (s.repeats ?? 0) >= 2 { return Theme.violet }
        return Theme.ink
    }

    var body: some View {
        let hands = steps.filter { $0.kind == .hands_on }.reduce(0) { $0 + $1.minutes }
        let wait = steps.filter { $0.kind == .waiting }.reduce(0) { $0 + $1.minutes }
        let rep = steps.filter { ($0.repeats ?? 0) >= 2 }.reduce(0) { $0 + $1.minutes }
        let first = steps.first.map { Fmt.clock($0.start) } ?? "", last = steps.last.map { Fmt.clock($0.end) } ?? ""
        VStack(spacing: 6) {
            HStack {
                MonoLabel("\(steps.count) steps · \(first) – \(last)")
                Spacer()
                HStack(spacing: 14) {
                    legend("Hands-on", Fmt.hm(hands), Theme.ink)
                    legend("Waiting", Fmt.hm(wait), Theme.yellow)
                    if rep > 0 { legend("Repeat", Fmt.hm(rep), Theme.violet) }
                }
            }
            GeometryReader { g in
                let w = g.size.width
                let gap: CGFloat = 2
                HStack(spacing: gap) {
                    ForEach(steps) { s in
                        RoundedRectangle(cornerRadius: 1).fill(color(s))
                            .frame(width: max(2, (w - gap * CGFloat(steps.count - 1)) * CGFloat(Double(s.minutes) / total)))
                    }
                }
            }
            .frame(height: 8)
            ZStack(alignment: .leading) {
                HStack {
                    Text(first).font(Theme.mono(10)).foregroundStyle(Theme.mutedText)
                    Spacer()
                    Text(last).font(Theme.mono(10)).foregroundStyle(Theme.mutedText)
                }
                if let w = steps.first(where: { $0.kind == .waiting }) {
                    GeometryReader { g in
                        let before = steps.prefix { $0.idx != w.idx }.reduce(0) { $0 + Double($1.minutes) }
                        let x = g.size.width * CGFloat((before + Double(w.minutes) / 2) / total)
                        Text("\(Fmt.clock(w.start)) → \(Fmt.clock(w.end)) · waiting").font(Theme.mono(10)).foregroundStyle(Theme.amberChipFg)
                            .fixedSize().position(x: x, y: 7)
                    }
                }
            }.frame(height: 14)
        }
    }

    func legend(_ label: String, _ value: String, _ color: Color) -> some View {
        HStack(spacing: 6) {
            SquareDot(color: color, size: 8)
            MonoLabel(label)
            Text(value.uppercased()).font(Theme.mono(10, .semibold)).tracking(1).foregroundStyle(.black)
        }
    }
}

// MARK: - Step row

struct StepRow: View {
    @EnvironmentObject var c: AppController
    var step: DraftStep
    var editing: Bool
    var isLast: Bool
    @State private var hover = false
    @State private var renaming = false
    @State private var draftName = ""

    var waiting: Bool { step.kind == .waiting }
    var repeats: Bool { (step.repeats ?? 0) >= 2 }

    var subline: String {
        if waiting { return "Waiting on · \((step.waiting_on?.rawValue ?? "someone"))".uppercased() }
        var parts = step.tools.map(Tools.display)
        if step.tools == ["sheets", "slides"] || (step.tools.count == 2 && Set(step.tools).isSubset(of: Tools.documentTools)) {
            parts = [parts.joined(separator: " → ")]
        }
        return parts.joined(separator: " · ").uppercased()
    }

    var body: some View {
        HStack(spacing: 0) {
            Text("\(Fmt.clock(step.start))–\(Fmt.clock(step.end))").font(Theme.mono(11)).foregroundStyle(Theme.mutedText)
                .frame(width: 100, alignment: .leading)
            ToolStack(tools: step.tools, waiting: waiting).frame(width: 56, alignment: .leading)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    if renaming {
                        TextField("Step name", text: $draftName, onCommit: { c.rename(step.idx, to: draftName); renaming = false })
                            .textFieldStyle(.plain).font(Theme.sans(15, .medium)).frame(maxWidth: 420)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.black, lineWidth: 1))
                    } else {
                        Text(step.name).font(Theme.sans(15, .medium)).foregroundStyle(step.share ? .black : Theme.mutedText)
                            .strikethrough(!step.share, color: Theme.mutedText)
                    }
                    if waiting { Chip(text: "Waiting", fg: Theme.amberChipFg, bg: Theme.amberChipBg) }
                    if repeats {
                        Chip(text: "Repeats", fg: Theme.violet, bg: Theme.violet.opacity(0.1))
                        Chip(text: "\(step.repeats!)× this week", fg: Theme.violet, bg: .white)
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(Theme.violet.opacity(0.3), lineWidth: 1))
                    }
                }
                Text(subline).font(Theme.mono(10)).tracking(1).foregroundStyle(Theme.mutedText)
            }
            Spacer()
            if (hover || editing) && !renaming {
                HStack(spacing: 8) {
                    actionButton("pencil", "Rename") { draftName = step.name; renaming = true }
                    if !isLast { actionButton("arrow.triangle.merge", "Merge") { c.mergeWithNext(step.idx) } }
                    actionButton("eye.slash", step.share ? "Hide" : "Show") { c.toggleShare(step.idx) }
                }.padding(.trailing, 20)
            }
            Text(Fmt.hm(step.minutes)).font(Theme.mono(11, waiting ? .semibold : .regular)).tracking(0.5)
                .foregroundStyle(waiting ? Theme.amberChipFg : .black).frame(width: 70, alignment: .trailing)
            Button { c.toggleShare(step.idx) } label: { CheckBox(on: step.share) }
                .buttonStyle(.plain).frame(width: 60, alignment: .trailing)
        }
        .padding(.horizontal, 18).frame(height: 52)
        .background(waiting ? Color(hex: 0xfffbf1) : (hover ? Theme.card.opacity(0.6) : Color.white))
        .overlay(alignment: .leading) { if waiting { Rectangle().fill(Theme.yellow).frame(width: 3) } }
        .onHover { hover = $0 }
    }

    func actionButton(_ icon: String, _ label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) { Image(systemName: icon).font(.system(size: 10)); Text(label) }
        }.buttonStyle(OutlineButtonStyle(height: 26)).font(Theme.sans(12))
    }
}

struct CheckBox: View {
    var on: Bool
    var body: some View {
        RoundedRectangle(cornerRadius: 3)
            .fill(on ? Color.black : Color.white)
            .overlay(RoundedRectangle(cornerRadius: 3).stroke(on ? Color.black : Theme.border, lineWidth: 1))
            .frame(width: 16, height: 16)
            .overlay(Image(systemName: "checkmark").font(.system(size: 10, weight: .bold)).foregroundStyle(.white).opacity(on ? 1 : 0))
    }
}

// MARK: - Left column

struct LeftOutColumn: View {
    var draft: DraftDay

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    MonoLabel("Left out · Stays on this Mac")
                    Spacer()
                    Text("\(draft.left_out.count)").font(Theme.mono(11, .semibold)).foregroundStyle(.white)
                        .frame(width: 22, height: 22).background(Circle().fill(Color.black))
                }
                Text(draft.left_out.isEmpty ? "Nothing personal was noted today." : "\(draft.left_out.count) personal thing\(draft.left_out.count == 1 ? " was" : "s were") never added.")
                    .font(Theme.sans(16, .semibold)).foregroundStyle(.black).padding(.top, 10)
                Text("Flowline removed them on this Mac before drafting. Your team never sees them.")
                    .font(Theme.sans(13)).foregroundStyle(Theme.mutedText).lineSpacing(2).padding(.top, 4)

                VStack(spacing: 0) {
                    ForEach(draft.left_out) { item in
                        Hairline()
                        HStack(alignment: .top, spacing: 12) {
                            LockIcon(size: 26)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.label).font(Theme.sans(14, .medium)).foregroundStyle(.black)
                                Text(leftOutSub(item)).font(Theme.sans(12.5)).foregroundStyle(Theme.mutedText).lineSpacing(2)
                            }
                            Spacer()
                            Text(item.minutes.map { "\($0) m" } ?? "—").font(Theme.mono(11)).foregroundStyle(Theme.mutedText)
                        }.padding(.vertical, 14)
                    }
                    if !draft.left_out.isEmpty { Hairline() }
                }.padding(.top, 18)

                MonoLabel("Never kept, even here").padding(.top, 26)
                FlowChips(items: Privacy.neverKept).padding(.top, 12)

                if let rep = draft.steps.first(where: { ($0.repeats ?? 0) >= 2 }) {
                    noticedCard(rep).padding(.top, 28)
                }
                Spacer(minLength: 24)
            }
            .padding(.horizontal, 22).padding(.top, 28)
        }
    }

    func leftOutSub(_ i: LeftOut) -> String {
        switch i.kind {
        case .personal_chat: return "Time counted as “away”. Nothing else noted."
        case .banking: return "Removed entirely."
        case .name_in_filename: return "Renamed to “client file” in your record."
        case .other: return "Removed."
        }
    }

    func noticedCard(_ s: DraftStep) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) { SquareDot(color: Theme.violet, size: 7); MonoLabel("Noticed by Flowline", color: Theme.violet) }
            (Text("One step repeats. ").font(Theme.sans(14, .semibold)) +
             Text("You’ve \(s.name.prefix(1).lowercased() + s.name.dropFirst()) \(s.repeats!) times this week.").font(Theme.sans(14)))
                .foregroundStyle(.black).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                if s.tools.count >= 2 {
                    ToolIcon(tool: s.tools[0], size: 20)
                    Image(systemName: "arrow.right").font(.system(size: 9, weight: .bold)).foregroundStyle(Theme.violet)
                    ToolIcon(tool: s.tools[1], size: 20)
                }
                Text("\(Fmt.hm(s.minutes)) today").font(Theme.mono(10.5)).foregroundStyle(.black).padding(.leading, 6)
                Spacer()
                Text("\(s.repeats!)× this week").font(Theme.mono(10.5)).foregroundStyle(Theme.violet)
            }
            Hairline(color: Theme.violet.opacity(0.2))
            Text("Shown to your team only as a count, if you approve.").font(Theme.sans(12)).foregroundStyle(Theme.mutedText)
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 6).fill(Theme.violet.opacity(0.04)))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.violet.opacity(0.24), lineWidth: 1))
        .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 1).fill(Theme.violet).frame(width: 2).padding(.vertical, 1) }
    }
}
