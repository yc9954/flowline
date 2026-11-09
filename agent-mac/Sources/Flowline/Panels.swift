import AppKit
import SwiftUI

/// Borderless, non-activating panel that can still take clicks and keys.
final class FloatingPanel: NSPanel {
    init(size: NSSize, level: NSWindow.Level) {
        super.init(contentRect: NSRect(origin: .zero, size: size),
                   styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        self.level = level
        isMovableByWindowBackground = false
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        isReleasedWhenClosed = false
        hidesOnDeactivate = false
        animationBehavior = .none
    }
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    func setContent<V: View>(_ v: V) {
        let host = NSHostingView(rootView: v)
        host.frame = NSRect(origin: .zero, size: frame.size)
        host.autoresizingMask = [.width, .height]
        contentView = host
    }
}

enum Screens {
    /// The built-in display (the one with the notch), else the main screen.
    static var builtIn: NSScreen {
        for s in NSScreen.screens {
            if let id = s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID,
               CGDisplayIsBuiltin(id) != 0 { return s }
        }
        return NSScreen.main ?? NSScreen.screens[0]
    }
}

enum NotchState: Equatable { case closed, peek, open }
enum NotchKind: Equatable { case endOfDay, suggestion, agent }

/// Dynamic-Island-style panel hanging from the camera housing of the built-in display.
///
/// Three states: CLOSED hugs the housing (plus a thin wing on each side so a dot / "1 screen" label can show next to
/// the housing, since anything drawn behind the housing itself is invisible), PEEK adds one line below it (≈340×64),
/// OPEN is at most 400×140. Width never exceeds 400 pt and nothing is drawn below 150 pt from the top of the screen.
/// Frame changes animate in ≤ 250 ms ease-out; the SwiftUI root follows the animated frame.
@MainActor
final class NotchPanel: ObservableObject {
    static let maxWidth: CGFloat = 400
    static let maxHeight: CGFloat = 150
    static let wing: CGFloat = 62          // black extension left/right of the housing in CLOSED
    static let runningLip: CGFloat = 4     // CLOSED hangs 4 pt below the housing while a run is active (progress line)

    let panel: FloatingPanel
    @Published private(set) var state: NotchState = .closed
    @Published private(set) var kind: NotchKind = .endOfDay
    @Published var hovering = false
    private(set) var isShown = false
    /// The state the panel returns to when the pointer leaves after a hover-expand.
    private var restState: NotchState = .peek
    /// Set by the controller: while true CLOSED shows the progress line and the panel does not idle-collapse.
    var running = false
    var onStateChange: ((NotchState) -> Void)?
    private var hoverTimer: Timer?
    private var idleTimer: Timer?
    private var settleTimer: Timer?

    init() {
        panel = FloatingPanel(size: NSSize(width: 200, height: 37),
                              level: NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + 2))
        panel.hasShadow = false   // CLOSED must blend with the housing; PEEK/OPEN draw their own soft shadow
    }

    // MARK: Geometry

    /// The camera housing in screen coordinates, measured from the auxiliary top areas; 200×37 centred as a fallback.
    static func housing(on screen: NSScreen) -> CGRect {
        if let l = screen.auxiliaryTopLeftArea, let r = screen.auxiliaryTopRightArea, r.minX > l.maxX, screen.safeAreaInsets.top > 0 {
            let h = screen.safeAreaInsets.top
            return CGRect(x: l.maxX, y: screen.frame.maxY - h, width: r.minX - l.maxX, height: h)
        }
        return CGRect(x: screen.frame.midX - 100, y: screen.frame.maxY - 37, width: 200, height: 37)
    }

    var screen: NSScreen { Screens.builtIn }
    var housing: CGRect { NotchPanel.housing(on: screen) }

    func size(for state: NotchState, kind: NotchKind) -> CGSize {
        let h = housing
        switch state {
        case .closed:
            return CGSize(width: h.width + 2 * NotchPanel.wing, height: h.height + (running ? NotchPanel.runningLip : 0))
        case .peek:
            return CGSize(width: max(340, h.width + 2 * NotchPanel.wing), height: h.height + 32)
        case .open:
            switch kind {
            case .endOfDay:   return CGSize(width: 400, height: h.height + 80)
            case .suggestion: return CGSize(width: 400, height: h.height + 102)
            case .agent:      return CGSize(width: 400, height: h.height + 108)
            }
        }
    }

    private func frame(for size: CGSize) -> NSRect {
        let w = min(size.width, NotchPanel.maxWidth), h = min(size.height, NotchPanel.maxHeight)
        let hs = housing
        return NSRect(x: (hs.midX - w / 2).rounded(), y: screen.frame.maxY - h, width: w, height: h)
    }

    var cornerRadius: CGFloat { state == .open ? 18 : 12 }

    // MARK: Showing

    /// Install the SwiftUI root once (the controller passes its environment object).
    func setRoot<V: View>(_ v: V) { panel.setContent(v) }

    /// Show `kind`, settling into `state`. A fresh appearance starts at the housing footprint and grows after 0.3 s.
    func show(_ kind: NotchKind, state target: NotchState) {
        self.kind = kind
        restState = target
        settleTimer?.invalidate()
        if !isShown {
            isShown = true
            state = .closed
            panel.alphaValue = 0
            panel.setFrame(frame(for: size(for: .closed, kind: kind)), display: true)
            panel.orderFrontRegardless()
            NSAnimationContext.runAnimationGroup { ctx in ctx.duration = 0.15; panel.animator().alphaValue = 1 }
            if target != .closed {
                settleTimer = Timer.scheduledTimer(withTimeInterval: 0.3, repeats: false) { [weak self] _ in
                    Task { @MainActor in self?.setState(target) }
                }
            }
        } else {
            setState(target)
        }
        scheduleIdleCollapse()
        NSLog("Flowline notch show kind=%@ state=%@ frame=%@", "\(kind)", "\(target)", NSStringFromRect(frame(for: size(for: target, kind: kind))))
    }

    func setState(_ s: NotchState, animated: Bool = true) {
        guard isShown else { return }
        let f = frame(for: size(for: s, kind: kind))
        state = s
        if animated {
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.22
                ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
                panel.animator().setFrame(f, display: true)
            }
        } else {
            panel.setFrame(f, display: true)
        }
        onStateChange?(s)
        NSLog("Flowline notch state=%@ frame=%@", "\(s)", NSStringFromRect(f))
    }

    /// Collapse to CLOSED and stay there until hovered (or the controller re-shows).
    func collapse() { restState = .closed; setState(.closed) }
    func expand() { restState = .open; setState(.open) }
    func toggleOpen() { if state == .open { collapse() } else { expand() } }

    func hide(fade: Bool = true, done: (() -> Void)? = nil) {
        guard isShown else { done?(); return }
        isShown = false
        hoverTimer?.invalidate(); idleTimer?.invalidate(); settleTimer?.invalidate()
        running = false
        if fade {
            NSAnimationContext.runAnimationGroup({ ctx in ctx.duration = 0.2; panel.animator().alphaValue = 0 },
                                                 completionHandler: { self.panel.orderOut(nil); done?() })
        } else { panel.orderOut(nil); done?() }
    }

    // MARK: Hover + idle

    /// Pointer over the panel expands it to OPEN; leaving returns to the rest state after 0.6 s.
    func hover(_ inside: Bool) {
        hovering = inside
        hoverTimer?.invalidate()
        guard isShown else { return }
        if inside {
            idleTimer?.invalidate()
            if state != .open { setState(.open) }
        } else {
            hoverTimer = Timer.scheduledTimer(withTimeInterval: 0.6, repeats: false) { [weak self] _ in
                Task { @MainActor in
                    guard let self, self.isShown, !self.hovering else { return }
                    if self.state != self.restState { self.setState(self.restState) }
                    self.scheduleIdleCollapse()
                }
            }
        }
    }

    /// A pending PEEK that nobody touches folds back into the housing after 12 s (a run never idles).
    private func scheduleIdleCollapse() {
        idleTimer?.invalidate()
        guard !running, restState == .peek else { return }
        idleTimer = Timer.scheduledTimer(withTimeInterval: 12, repeats: false) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isShown, !self.hovering, !self.running else { return }
                self.collapse()
            }
        }
    }
}

/// Rounded only at the bottom, hangs from the top edge of the screen.
struct NotchShape: Shape {
    var radius: CGFloat
    var animatableData: CGFloat { get { radius } set { radius = newValue } }
    func path(in r: CGRect) -> Path {
        let radius = min(radius, r.height / 2, r.width / 2)
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.maxY - radius))
        p.addArc(center: CGPoint(x: r.maxX - radius, y: r.maxY - radius), radius: radius,
                 startAngle: .degrees(0), endAngle: .degrees(90), clockwise: false)
        p.addLine(to: CGPoint(x: r.minX + radius, y: r.maxY))
        p.addArc(center: CGPoint(x: r.minX + radius, y: r.maxY - radius), radius: radius,
                 startAngle: .degrees(90), endAngle: .degrees(180), clockwise: false)
        p.closeSubpath()
        return p
    }
}

/// Click-through window over the whole built-in display with a wavy edge glow while an agent works (the Metal port
/// of design/edge-glow.frag in EdgeGlow.swift): screen-saver level, all spaces, ignores the mouse. Fades in over
/// 300 ms and out over 400 ms; the render loop runs only while the window is up.
final class ScreenBorderWindow {
    private var window: NSWindow?
    private var glow: EdgeGlowView?

    func show() {
        if let w = window { w.orderFrontRegardless(); glow?.startAnimating(); return }
        let screen = Screens.builtIn
        let w = NSWindow(contentRect: screen.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        w.isOpaque = false
        w.backgroundColor = .clear
        w.hasShadow = false
        w.ignoresMouseEvents = true
        w.level = .screenSaver
        w.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        w.isReleasedWhenClosed = false
        w.animationBehavior = .none
        let view = EdgeGlowView(frame: NSRect(origin: .zero, size: screen.frame.size))
        view.hue = 0
        view.thickness = 90
        w.contentView = view
        w.alphaValue = 0
        w.setFrame(screen.frame, display: true)
        view.startAnimating()
        w.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { ctx in ctx.duration = 0.3; w.animator().alphaValue = 1 }
        window = w
        glow = view
    }

    func hide() {
        guard let w = window else { return }
        let view = glow
        window = nil; glow = nil
        NSAnimationContext.runAnimationGroup({ ctx in ctx.duration = 0.4; w.animator().alphaValue = 0 },
                                             completionHandler: { view?.stopAnimating(); w.orderOut(nil) })
    }
}
