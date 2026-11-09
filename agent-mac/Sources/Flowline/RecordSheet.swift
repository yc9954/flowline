import SwiftUI
import FlowlineCore

/// The approved record (Record.dc.html): paper card with a torn bottom edge, over the dimmed review.
struct RecordSheet: View {
    @EnvironmentObject var c: AppController
    @State private var copied = false

    var record: FlowlineCore.Record
    var approved: Date { ISO.date(record.approved_at) ?? Date() }

    /// The three steps worth showing in full: the longest hands-on, the waiting one, the repeat.
    var featured: [RecordStep] {
        var out: [RecordStep] = []
        let hands = record.steps.filter { $0.kind == .hands_on && ($0.repeats ?? 0) < 2 }
        let withHandoff = hands.filter { $0.handoff_from != nil || $0.handoff_to != nil }
        if let h = (withHandoff.isEmpty ? hands : withHandoff).max(by: { $0.minutes < $1.minutes }) { out.append(h) }
        if let w = record.steps.first(where: { $0.kind == .waiting }) { out.append(w) }
        if let r = record.steps.first(where: { ($0.repeats ?? 0) >= 2 }) { out.append(r) }
        if out.isEmpty { out = Array(record.steps.prefix(3)) }
        return out.sorted { $0.idx < $1.idx }
    }
    var rest: [RecordStep] { record.steps.filter { s in !featured.contains { $0.idx == s.idx } } }

    var body: some View {
        ZStack(alignment: .top) {
            Color.black.opacity(0.42).ignoresSafeArea()
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: 0) {
                    card
                    TornEdge().fill(Theme.paper).frame(height: 9)
                }
                .frame(width: 840)
                .shadow(color: .black.opacity(0.32), radius: 28, y: 18)
                .padding(.top, 14).padding(.bottom, 24)
            }
        }
    }

    var card: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack(alignment: .top, spacing: 16) {
                Circle().fill(Color.black).frame(width: 44, height: 44)
                    .overlay(Image(systemName: "checkmark.shield").font(.system(size: 16, weight: .semibold)).foregroundStyle(.white))
                VStack(alignment: .leading, spacing: 6) {
                    MonoLabel("Flowline work record · No. \(record.id)")
                    HStack(spacing: 12) {
                        Text("\(record.role.rawValue) · \(Fmt.longDay(record.date))").font(Theme.sans(22, .semibold)).tracking(-0.3).foregroundStyle(.black)
                        HStack(spacing: 5) {
                            Image(systemName: "checkmark").font(.system(size: 9, weight: .bold))
                            Text("Approved by you · \(Fmt.clock(approved))".uppercased()).font(Theme.mono(9.5)).tracking(0.8)
                        }.foregroundStyle(Theme.teal).padding(.horizontal, 8).padding(.vertical, 4).background(RoundedRectangle(cornerRadius: 2).fill(Theme.teal.opacity(0.08)))
                    }
                    Text("This record is all your team’s board can see from today. Nothing else from this Mac is shared.")
                        .font(Theme.sans(14)).foregroundStyle(Theme.mutedText)
                }
                Spacer()
                Button { c.recordDone() } label: { Image(systemName: "xmark").font(.system(size: 11, weight: .semibold)).frame(width: 30, height: 30) }
                    .buttonStyle(OutlineButtonStyle(height: 30))
            }
            .padding(.horizontal, 32).padding(.top, 22).padding(.bottom, 16)

            DashedRule()
            // Meta row
            HStack(spacing: 24) {
                meta("Board", "\(c.settings.boardName) board")
                meta("Role", record.role.rawValue)
                meta("Covers", "\(Fmt.clock(record.covers.start))–\(Fmt.clock(record.covers.end))")
                Spacer()
                meta("Approved", "\(Fmt.mediumDay(record.date)) · \(Fmt.clockSeconds(approved))")
            }.padding(.horizontal, 32).frame(height: 36)
            DashedRule()
            // Stats
            HStack(spacing: 0) {
                stat("Steps", "\(record.steps.count)", nil)
                VHairline()
                stat("Hands-on", Fmt.hm(record.hands_on_min), Theme.ink)
                VHairline()
                stat("Waiting on others", Fmt.hm(record.waiting_min), Theme.yellow)
                VHairline()
                stat("Kept private", "\(record.kept_private) items", nil, lock: true)
            }
            .frame(height: 68).background(Theme.card.opacity(0.5))
            DashedRule()

            // Steps
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    MonoLabel("\(record.steps.count) steps shared · Showing \(featured.count)")
                    Spacer()
                    MonoLabel("Took")
                }.frame(height: 30)
                Rectangle().fill(Color.black).frame(height: 1)
                ForEach(featured, id: \.idx) { s in
                    featuredStep(s)
                }
                HStack {
                    if !rest.isEmpty {
                        (Text("+ \(rest.count) more step\(rest.count == 1 ? "" : "s")").font(Theme.sans(13)).foregroundStyle(.black) +
                         Text(" · " + rest.map { String(format: "%02d", $0.idx) }.joined(separator: " · ")).font(Theme.mono(10.5)).foregroundStyle(Theme.mutedText))
                    }
                    Spacer()
                    Text("Day total · \(Fmt.hm(record.hands_on_min + record.waiting_min))").font(Theme.mono(11)).foregroundStyle(.black)
                }.padding(.vertical, 9)
            }.padding(.horizontal, 32)
            DashedRule()

            // Proof + hash
            HStack(alignment: .top, spacing: 16) {
                proofBox.frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: 10) {
                    HStack { MonoLabel("Record hash"); Spacer(); MonoLabel("sha-256") }
                    HStack(spacing: 8) {
                        Text(shortHash).font(Theme.mono(13)).foregroundStyle(.black)
                        Spacer()
                        Button {
                            NSPasteboard.general.clearContents(); NSPasteboard.general.setString(record.hash, forType: .string)
                            copied = true
                        } label: { HStack(spacing: 5) { Image(systemName: "doc.on.doc").font(.system(size: 10)); Text(copied ? "Copied" : "Copy") } }
                            .buttonStyle(OutlineButtonStyle(height: 26))
                    }
                    .padding(.leading, 10).padding(.trailing, 6).frame(height: 36)
                    .background(RoundedRectangle(cornerRadius: 2).fill(Color.white))
                    .overlay(RoundedRectangle(cornerRadius: 2).stroke(Theme.hairline, lineWidth: 1))
                    HStack(alignment: .bottom) {
                        Squiggle().stroke(Color.black, lineWidth: 1.4).frame(width: 120, height: 26)
                        Spacer()
                        Text("sig \(shortSig)").font(Theme.mono(10)).foregroundStyle(Theme.mutedText)
                        HStack(spacing: 4) {
                            Image(systemName: verified ? "checkmark" : "xmark").font(.system(size: 9, weight: .bold))
                            Text(verified ? "VERIFIED" : "NOT VERIFIED").font(Theme.mono(9.5)).tracking(0.8)
                        }.foregroundStyle(verified ? Theme.teal : Theme.red)
                    }.padding(.top, 6)
                    Rectangle().fill(Color.black).frame(height: 1)
                    HStack(spacing: 6) {
                        Image(systemName: "key").font(.system(size: 9)).foregroundStyle(Theme.mutedText)
                        Text("Signed with this Mac’s key · ed25519").font(Theme.mono(10)).foregroundStyle(Theme.mutedText)
                    }
                }.frame(width: 340)
            }
            .padding(.horizontal, 32).padding(.vertical, 14)
            DashedRule()

            // Footer
            HStack(spacing: 14) {
                if c.recordWithdrawn {
                    Text("Withdrawn from the board.").font(Theme.sans(13, .semibold)).foregroundStyle(Theme.red)
                    Text("The steps stay on this Mac.").font(Theme.sans(12.5)).foregroundStyle(Theme.mutedText)
                } else if c.recordPosted {
                    Button { Task { await c.withdraw() } } label: {
                        HStack(spacing: 6) { Image(systemName: "arrow.uturn.backward").font(.system(size: 11)); Text("Withdraw") }
                    }.buttonStyle(OutlineButtonStyle(tint: Theme.red))
                    Text("Takes it off the board any time. The steps stay on this Mac.").font(Theme.sans(12.5)).foregroundStyle(Theme.mutedText)
                } else {
                    ProgressView().controlSize(.small)
                    Text("Posting to the board…").font(Theme.sans(12.5)).foregroundStyle(Theme.mutedText)
                }
                if let e = c.approveError { Text(e).font(Theme.sans(12)).foregroundStyle(Theme.red) }
                Spacer()
                Button("Done") { c.recordDone() }.buttonStyle(BlackButtonStyle())
            }
            .padding(.horizontal, 32).frame(height: 60)
        }
        .background(Theme.paper)
    }

    var verified: Bool { Signer.verify(record) }
    var shortHash: String { record.hash.count > 16 ? "\(record.hash.prefix(8))…\(record.hash.suffix(6))" : record.hash }
    var shortSig: String { record.sig.count > 10 ? "\(record.sig.prefix(4))…\(record.sig.suffix(4))" : record.sig }

    var proofBox: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "checkmark.shield").font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.teal)
                Text(c.recordWithdrawn ? "Withdrawn from the \(c.settings.boardName) board" : (c.recordPosted ? "Added to the \(c.settings.boardName) board" : "Signed on this Mac"))
                    .font(Theme.sans(15, .semibold)).foregroundStyle(.white)
            }
            Text("Signed on this Mac. Your team sees steps, times and hand-offs — never screens, messages or files.")
                .font(Theme.sans(13)).foregroundStyle(Theme.notchText).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
            Text(c.recordPosted && !c.recordWithdrawn
                 ? "Posted \(Fmt.clockSeconds(c.postedAt ?? approved)) · \(record.steps.count) of \(record.steps.count) steps visible to the board"
                 : (c.recordWithdrawn ? "Removed from the board · kept on this Mac" : "Not posted yet"))
                .font(Theme.mono(10)).foregroundStyle(Theme.notchText).padding(.top, 6)
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 4).fill(c.recordWithdrawn ? Color(hex: 0x4d5353) : Color.black))
    }

    func meta(_ k: String, _ v: String) -> some View {
        HStack(spacing: 8) { MonoLabel(k); Text(v).font(Theme.mono(11)).foregroundStyle(.black) }
    }

    func stat(_ k: String, _ v: String, _ dot: Color?, lock: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                if let d = dot { SquareDot(color: d, size: 7) }
                if lock { Image(systemName: "lock.fill").font(.system(size: 9)).foregroundStyle(Theme.mutedText) }
                MonoLabel(k)
            }
            Text(v).font(Theme.stat(22)).foregroundStyle(.black).monospacedDigit()
        }
        .padding(.horizontal, 20).frame(maxWidth: .infinity, alignment: .leading)
    }

    func featuredStep(_ s: RecordStep) -> some View {
        let waiting = s.kind == .waiting
        let repeats = (s.repeats ?? 0) >= 2
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Text(String(format: "%02d", s.idx)).font(Theme.mono(10.5)).foregroundStyle(Theme.mutedText).frame(width: 24, alignment: .leading)
                Text(s.name).font(Theme.sans(15, .medium)).foregroundStyle(.black)
                if waiting { Chip(text: "Waiting", fg: Theme.amberChipFg, bg: Theme.amberChipBg) }
                if repeats { Chip(text: "Repeats", fg: Theme.violet, bg: Theme.violet.opacity(0.1)) }
                DottedLeader().stroke(Theme.hairline, style: StrokeStyle(lineWidth: 1, dash: [1, 3])).frame(height: 1).padding(.horizontal, 6)
                Text(Fmt.hm(s.minutes)).font(Theme.mono(11, .semibold)).tracking(0.5).foregroundStyle(waiting ? Theme.amberChipFg : .black)
            }
            HStack(alignment: .top, spacing: 0) {
                detail("Case", s.case_id ?? "—").frame(width: 150, alignment: .leading)
                VStack(alignment: .leading, spacing: 6) {
                    MonoLabel("Tools")
                    HStack(spacing: 6) {
                        ForEach(s.tools, id: \.self) { ToolIcon(tool: $0, size: 14) }
                        Text(s.tools.isEmpty ? "—" : s.tools.joined(separator: " → ")).font(Theme.mono(11)).foregroundStyle(.black)
                    }
                }.frame(width: 250, alignment: .leading)
                detail("Handed from / to", handoff(s)).frame(width: 160, alignment: .leading)
                VStack(alignment: .leading, spacing: 6) {
                    MonoLabel("Waiting on")
                    HStack(spacing: 6) {
                        if let w = s.waiting_on { SquareDot(color: Theme.yellow, size: 7); Text(w.rawValue).font(Theme.mono(11)).foregroundStyle(.black) }
                        else { Text("—").font(Theme.mono(11)).foregroundStyle(.black) }
                        if repeats { Text("· repeats \(s.repeats!)× / wk").font(Theme.mono(10.5)).foregroundStyle(Theme.violet) }
                    }
                }
                Spacer()
            }.padding(.leading, 34)
        }
        .padding(.vertical, 11)
        .overlay(alignment: .bottom) { Hairline() }
    }

    func handoff(_ s: RecordStep) -> String {
        if let f = s.handoff_from, let t = s.handoff_to { return "\(f.rawValue) → \(t.rawValue)" }
        if let f = s.handoff_from { return "\(f.rawValue) → \(record.role.rawValue)" }
        if let t = s.handoff_to { return "\(record.role.rawValue) → \(t.rawValue)" }
        return "—"
    }

    func detail(_ k: String, _ v: String) -> some View {
        VStack(alignment: .leading, spacing: 6) { MonoLabel(k); Text(v).font(Theme.mono(11)).foregroundStyle(.black) }
    }
}

struct DashedRule: View {
    var body: some View {
        DottedLeader().stroke(Theme.hairline, style: StrokeStyle(lineWidth: 1, dash: [3, 3])).frame(height: 1)
    }
}

struct DottedLeader: Shape {
    func path(in r: CGRect) -> Path { var p = Path(); p.move(to: CGPoint(x: r.minX, y: r.midY)); p.addLine(to: CGPoint(x: r.maxX, y: r.midY)); return p }
}

struct Squiggle: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.midY + 4))
        p.addCurve(to: CGPoint(x: r.minX + r.width * 0.3, y: r.midY - 6), control1: CGPoint(x: r.minX + r.width * 0.08, y: r.minY), control2: CGPoint(x: r.minX + r.width * 0.2, y: r.maxY))
        p.addCurve(to: CGPoint(x: r.minX + r.width * 0.62, y: r.midY + 2), control1: CGPoint(x: r.minX + r.width * 0.4, y: r.minY - 4), control2: CGPoint(x: r.minX + r.width * 0.52, y: r.maxY + 2))
        p.addCurve(to: CGPoint(x: r.maxX, y: r.midY - 3), control1: CGPoint(x: r.minX + r.width * 0.72, y: r.minY), control2: CGPoint(x: r.minX + r.width * 0.88, y: r.maxY))
        return p
    }
}

/// Torn paper bottom edge.
struct TornEdge: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        let tooth: CGFloat = 12
        p.move(to: CGPoint(x: r.minX, y: r.minY))
        var x = r.minX
        var down = true
        while x < r.maxX {
            let nx = min(x + tooth / 2, r.maxX)
            p.addLine(to: CGPoint(x: nx, y: down ? r.maxY : r.minY))
            x = nx; down.toggle()
        }
        p.addLine(to: CGPoint(x: r.maxX, y: r.minY))
        p.closeSubpath()
        return p
    }
}
