import SwiftUI
import FlowlineCore

/// Root of the notch panel. Draws the black housing shape at whatever size the window currently has (the frame is
/// animated by NotchPanel) and swaps the content for the current kind × state. The top `housing.height` points are
/// behind the physical camera housing, so all content sits below that band; CLOSED only uses the wings beside it.
struct NotchRootView: View {
    @ObservedObject var notch: NotchPanel
    @EnvironmentObject var c: AppController

    var body: some View {
        let housingH = notch.housing.height
        ZStack(alignment: .top) {
            NotchShape(radius: notch.cornerRadius).fill(Color.black)
                .shadow(color: .black.opacity(notch.state == .closed ? 0 : 0.35), radius: 10, y: 4)
            Group {
                if notch.state == .closed {
                    ClosedContent(housing: notch.housing)
                } else {
                    kindContent(open: notch.state == .open).padding(.top, housingH)
                }
            }
            .transition(.opacity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .clipShape(NotchShape(radius: notch.cornerRadius))
        .contentShape(Rectangle())
        .onTapGesture { notch.toggleOpen() }
        .onHover { notch.hover($0) }
        .animation(.easeOut(duration: 0.2), value: notch.state)
    }

    @ViewBuilder func kindContent(open: Bool) -> some View {
        switch notch.kind {
        case .endOfDay: EndOfDayBanner(open: open)
        case .suggestion: if let s = c.suggestion { SuggestionBanner(suggestion: s, open: open) }
        case .agent: AgentPanel(open: open)
        }
    }
}

// MARK: - CLOSED

/// Housing footprint plus wings: a breathing dot while something is pending; during a run the dot is steady, a tiny
/// "1 screen" label sits right of it and a 2-pt progress line runs along the bottom edge.
struct ClosedContent: View {
    @EnvironmentObject var c: AppController
    var housing: CGRect
    @State private var breathe = false

    var running: Bool { c.run != nil && !c.runFinished }

    var body: some View {
        GeometryReader { g in
            let wing = (g.size.width - housing.width) / 2
            ZStack(alignment: .bottomLeading) {
                HStack(spacing: 0) {
                    Spacer().frame(width: wing + housing.width)
                    HStack(spacing: 5) {
                        Circle().fill(Theme.violet).frame(width: 6, height: 6)
                            .scaleEffect(running || !breathe ? 1 : 0.7)
                            .opacity(running || breathe ? 1 : 0.55)
                        if running {
                            Text("\(c.activeScreens) screen\(c.activeScreens == 1 ? "" : "s")")
                                .font(Theme.mono(8.5)).foregroundStyle(Theme.notchText).lineLimit(1).fixedSize()
                        }
                    }
                    .frame(width: wing, height: housing.height)
                }
                if running {
                    Rectangle().fill(Color.white.opacity(0.14)).frame(height: 2)
                    Rectangle().fill(Theme.violet).frame(width: max(2, g.size.width * c.runProgress), height: 2)
                        .animation(.easeOut(duration: 0.25), value: c.runProgress)
                }
            }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) { breathe = true }
        }
    }
}

// MARK: - End of day

struct EndOfDayBanner: View {
    @EnvironmentObject var c: AppController
    var open: Bool

    var body: some View {
        let steps = c.draft?.steps.count ?? 0
        let left = c.draft?.left_out.count ?? 0
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                SquareDot(color: Theme.teal, size: 6)
                Text("Your day is drafted · \(steps) item\(steps == 1 ? "" : "s")")
                    .font(Theme.sans(12.5, .semibold)).foregroundStyle(.white).lineLimit(1)
                Spacer(minLength: 8)
                if !open {
                    Button("Review") { c.bannerReview() }.buttonStyle(NotchSmallFilledButtonStyle())
                }
            }
            if open {
                Text("\(left) personal thing\(left == 1 ? "" : "s") left out · about 2 min to review")
                    .font(Theme.mono(9.5)).foregroundStyle(Theme.notchText).lineLimit(1)
                HStack(spacing: 6) {
                    Button { c.bannerReview() } label: {
                        HStack(spacing: 5) { Text("Review"); Image(systemName: "arrow.right").font(.system(size: 9, weight: .bold)) }
                    }.buttonStyle(NotchSmallFilledButtonStyle())
                    Button("Tomorrow morning") { c.bannerTomorrow() }.buttonStyle(NotchSmallOutlineButtonStyle())
                }.padding(.top, 4)
            }
        }
        .padding(.horizontal, 14).padding(.top, open ? 10 : 0).padding(.bottom, open ? 10 : 0)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: open ? .topLeading : .leading)
    }
}

// MARK: - Suggestion

struct SuggestionBanner: View {
    @EnvironmentObject var c: AppController
    var suggestion: Suggestion
    var open: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                SquareDot(color: Theme.violet, size: 6)
                Text(open ? Suggestion.oneLine(suggestion.title) : suggestion.peekTitle)
                    .font(Theme.sans(12.5, .semibold)).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.85)
                Spacer(minLength: 8)
                if !open {
                    Button("Do it") { c.suggestionAnswer(.do_it) }.buttonStyle(NotchSmallFilledButtonStyle())
                    Button("Later") { c.suggestionAnswer(.not_now) }.buttonStyle(NotchSmallOutlineButtonStyle())
                }
            }
            if open {
                Text(suggestion.whyNowLine).font(Theme.mono(9.5)).foregroundStyle(Theme.notchText).lineLimit(1)
                HStack(spacing: 6) {
                    Button("Do it") { c.suggestionAnswer(.do_it) }.buttonStyle(NotchSmallFilledButtonStyle())
                    Button("Later") { c.suggestionAnswer(.not_now) }.buttonStyle(NotchSmallOutlineButtonStyle())
                    Button("Don’t ask") { c.suggestionAnswer(.dont_ask) }.buttonStyle(NotchSmallTextButtonStyle()).padding(.leading, 4)
                }.padding(.top, 4)
            }
        }
        .padding(.horizontal, 14).padding(.top, open ? 10 : 0).padding(.bottom, open ? 10 : 0)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: open ? .topLeading : .leading)
    }
}

extension Suggestion {
    /// "Proposal 172 · fill the deck?" — a case reference when one appears in the text, else how often it recurred.
    var peekTitle: String {
        let subject = Suggestion.caseRef(in: [title, body, why_now]) ?? (count_last_week > 0 ? "\(count_last_week)× last week" : "Suggestion")
        return "\(subject) · \(shortAsk)"
    }

    /// Short imperative for the peek line, by skill, else the title cut to a few words.
    var shortAsk: String {
        if skill_id.contains("deck") { return "fill the deck?" }
        if skill_id.contains("mail") || skill_id.contains("send") { return "send the mail?" }
        if skill_id.contains("sheet") { return "fill the sheet?" }
        var t = title.trimmingCharacters(in: CharacterSet(charactersIn: "?!. "))
        let words = t.split(separator: " ")
        if words.count > 4 { t = words.prefix(4).joined(separator: " ") + "…" }
        if let f = t.first { t = f.lowercased() + t.dropFirst() }
        return t + "?"
    }

    /// One "why now" line: count_last_week, minutes_each, estimate_s.
    var whyNowLine: String {
        var parts: [String] = []
        if count_last_week > 0 { parts.append("\(count_last_week)× last week") }
        if minutes_each > 0 { parts.append("\(minutes_each) min each by hand") }
        if estimate_s > 0 { parts.append(estimate_s < 60 ? "~\(estimate_s) s for me" : "~\(Int((Double(estimate_s) / 60).rounded())) min for me") }
        if parts.isEmpty { return Suggestion.oneLine(why_now) }
        return parts.joined(separator: " · ")
    }

    static func oneLine(_ s: String) -> String {
        s.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
    }

    static func caseRef(in texts: [String]) -> String? {
        for t in texts {
            if let r = t.range(of: #"(?i)(proposal|quote|order|ticket|case|invoice|deal|sheet|deck)[\s\-]*#?\s*(\d{2,6})"#, options: .regularExpression) {
                let m = String(t[r])
                let digits = m.filter(\.isNumber)
                let kind = m.prefix { $0.isLetter }
                return kind.prefix(1).uppercased() + kind.dropFirst().lowercased() + " " + digits
            }
        }
        return nil
    }
}

// MARK: - Agent

/// A running agent: title, horizontal step rail with a progress bar under the current step, detail line, elapsed, Stop.
/// After the run: "Left for you · nothing saved" + Dismiss.
struct AgentPanel: View {
    @EnvironmentObject var c: AppController
    var open: Bool

    var elapsed: String { String(format: "%d:%02d", c.runElapsed / 60, c.runElapsed % 60) }
    var steps: [RunStep] { c.run?.steps ?? [] }
    var current: RunStep? { steps.first { $0.status == .now } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                SquareDot(color: c.runFinished ? Theme.teal : Theme.violet, size: 6)
                Text(c.runFinished ? finishedTitle : c.runTitle)
                    .font(Theme.sans(12.5, .semibold)).foregroundStyle(.white).lineLimit(1)
                Spacer(minLength: 8)
                if c.runFinished {
                    Button("Dismiss") { c.dismissRun() }.buttonStyle(NotchSmallOutlineButtonStyle())
                } else {
                    Text(elapsed).font(Theme.mono(11, .semibold)).foregroundStyle(.white).monospacedDigit()
                    Button { c.stopRun() } label: {
                        HStack(spacing: 4) { Image(systemName: "stop.fill").font(.system(size: 7)); Text("Stop") }
                    }.buttonStyle(NotchSmallOutlineButtonStyle())
                }
            }
            if open {
                if c.runFinished {
                    HStack(spacing: 10) {
                        if let checks = c.run?.checks, checks.count > 3 {
                            // The executor can report a dozen checks; one line says how they went.
                            let ok = checks.filter(\.ok).count
                            let failed = checks.first { !$0.ok }?.name.replacingOccurrences(of: "_", with: " ")
                            Image(systemName: ok == checks.count ? "checkmark" : "xmark").font(.system(size: 8, weight: .bold))
                                .foregroundStyle(ok == checks.count ? Theme.teal : Theme.red)
                            Text("\(ok) of \(checks.count) checks passed" + (failed.map { " · \($0) failed" } ?? ""))
                                .font(Theme.mono(9.5)).foregroundStyle(Theme.notchText).lineLimit(1)
                        } else if let checks = c.run?.checks, !checks.isEmpty {
                            ForEach(checks.indices, id: \.self) { i in
                                HStack(spacing: 4) {
                                    Image(systemName: checks[i].ok ? "checkmark" : "xmark").font(.system(size: 8, weight: .bold))
                                        .foregroundStyle(checks[i].ok ? Theme.teal : Theme.red)
                                    Text(checks[i].name).font(Theme.mono(9.5)).foregroundStyle(Theme.notchText)
                                }
                            }
                        } else {
                            Text(finishedDetail).font(Theme.mono(9.5)).foregroundStyle(Theme.notchText).lineLimit(1)
                        }
                    }.padding(.top, 10)
                    Spacer(minLength: 0)
                } else {
                    StepRail(steps: steps).padding(.top, 12)
                    Text(current?.detail ?? (steps.last?.status == .done ? "Finishing" : "Starting"))
                        .font(Theme.sans(11.5)).foregroundStyle(Theme.notchText).lineLimit(1)
                        .padding(.top, 8)
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(.horizontal, 14).padding(.top, open ? 10 : 0).padding(.bottom, open ? 10 : 0)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: open ? .topLeading : .leading)
    }

    var finishedTitle: String {
        if c.runError != nil { return "Couldn’t start · nothing changed" }
        return c.run?.status == .stopped ? "Stopped · nothing saved" : "Left for you · nothing saved"
    }
    var finishedDetail: String {
        if let e = c.runError { return e }
        return c.run?.status == .stopped ? "Whatever was typed is still yours to keep or undo" : "Check the slide, then keep it or undo"
    }
}

/// Four small labels side by side, each with a dot indicator and a thin bar; the bar under the current step fills
/// with its progress (or sits half-way when the executor reports none).
struct StepRail: View {
    var steps: [RunStep]
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            ForEach(steps) { step in
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 4) {
                        indicator(step).frame(width: 7, height: 7)
                        Text(step.label.uppercased()).font(Theme.mono(8.5, .medium)).tracking(0.4)
                            .foregroundStyle(step.status == .pending ? Theme.notchText.opacity(0.7) : .white)
                            .lineLimit(1).minimumScaleFactor(0.75)
                    }
                    GeometryReader { g in
                        ZStack(alignment: .leading) {
                            Rectangle().fill(Color.white.opacity(0.14))
                            Rectangle().fill(step.status == .done ? Theme.teal : Theme.violet)
                                .frame(width: g.size.width * fill(step))
                                .animation(.easeOut(duration: 0.25), value: fill(step))
                        }
                    }.frame(height: 2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    func fill(_ s: RunStep) -> CGFloat {
        switch s.status {
        case .done: return 1
        case .pending: return 0
        case .now:
            if let p = s.progress, p.count == 2, p[1] > 0 { return max(0.08, CGFloat(p[0]) / CGFloat(p[1])) }
            return 0.5
        }
    }

    @ViewBuilder func indicator(_ s: RunStep) -> some View {
        switch s.status {
        case .done: Circle().fill(Theme.teal)
        case .now: Circle().stroke(Theme.violet, lineWidth: 1.5).overlay(Circle().fill(Theme.violet).frame(width: 3, height: 3))
        case .pending: Circle().stroke(Color.white.opacity(0.35), lineWidth: 1)
        }
    }
}
