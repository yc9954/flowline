import SwiftUI
import AppKit

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255,
                  blue: Double(hex & 0xff) / 255, opacity: 1)
    }
}

/// Design tokens from design/DESIGN-NOTES.md. Light only.
enum Theme {
    static let bg = Color.white
    static let fg = Color.black
    static let ink = Color(hex: 0x1f2428)
    static let card = Color(hex: 0xf2f5f6)
    static let muted2 = Color(hex: 0xedf0f2)
    static let border = Color(hex: 0xd8dddf)
    static let hairline = Color.black.opacity(0.12)
    static let mutedText = Color(hex: 0x4d5353)
    static let primary = Color(hex: 0x171717)
    static let teal = Color(hex: 0x0F766E)
    static let violet = Color(hex: 0x6D5BD0)
    static let amber = Color(hex: 0xB45309)
    static let amberChipBg = Color(hex: 0xf6ebd3)
    static let amberChipFg = Color(hex: 0x6b4a00)
    static let red = Color(hex: 0xe40014)
    static let yellow = Color(hex: 0xFCBB00)
    static let blue = Color(hex: 0x3B73FF)
    static let grey = Color(hex: 0xB8BEC2)
    static let paper = Color(hex: 0xfafaf8)
    static let notchText = Color(hex: 0xb9bdc0)

    static let hasInstrument: Bool = NSFontManager.shared.availableFontFamilies.contains("Instrument Sans")
    static let hasGeist: Bool = NSFontManager.shared.availableFontFamilies.contains("Geist Mono")
    static let hasHost: Bool = NSFontManager.shared.availableFontFamilies.contains("Host Grotesk")

    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        hasInstrument ? .custom("Instrument Sans", size: size).weight(weight) : .system(size: size, weight: weight)
    }
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        hasGeist ? .custom("Geist Mono", size: size).weight(weight) : .system(size: size, weight: weight, design: .monospaced)
    }
    static func stat(_ size: CGFloat) -> Font {
        hasHost ? .custom("Host Grotesk", size: size).weight(.medium) : .system(size: size, weight: .medium)
    }
}

/// Geist Mono label: 10px uppercase, 1px tracking, muted.
struct MonoLabel: View {
    var text: String
    var color: Color = Theme.mutedText
    var size: CGFloat = 10
    init(_ text: String, color: Color = Theme.mutedText, size: CGFloat = 10) { self.text = text; self.color = color; self.size = size }
    var body: some View {
        Text(text.uppercased()).font(Theme.mono(size)).tracking(1).foregroundStyle(color)
    }
}

struct SquareDot: View {
    var color: Color
    var size: CGFloat = 7
    var body: some View { RoundedRectangle(cornerRadius: 1).fill(color).frame(width: size, height: size) }
}

struct Hairline: View {
    var color: Color = Theme.hairline
    var body: some View { Rectangle().fill(color).frame(height: 1) }
}

struct VHairline: View {
    var color: Color = Theme.hairline
    var body: some View { Rectangle().fill(color).frame(width: 1) }
}

/// Status chip: mono uppercase on a tint, 2px square corners.
struct Chip: View {
    var text: String
    var fg: Color
    var bg: Color
    var dot: Bool = false
    var body: some View {
        HStack(spacing: 5) {
            if dot { SquareDot(color: fg, size: 6) }
            Text(text.uppercased()).font(Theme.mono(9.5)).tracking(0.8)
        }
        .foregroundStyle(fg)
        .padding(.horizontal, 7).padding(.vertical, 3)
        .background(RoundedRectangle(cornerRadius: 2).fill(bg))
    }
}

struct BlackButtonStyle: ButtonStyle {
    var height: CGFloat = 36
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(13, .semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 14)
            .frame(height: height)
            .background(RoundedRectangle(cornerRadius: 2).fill(Theme.primary.opacity(configuration.isPressed ? 0.8 : 1)))
            .contentShape(Rectangle())
    }
}

struct OutlineButtonStyle: ButtonStyle {
    var height: CGFloat = 36
    var tint: Color = .black
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(13, .medium))
            .foregroundStyle(tint)
            .padding(.horizontal, 12)
            .frame(height: height)
            .background(RoundedRectangle(cornerRadius: 2).fill(Color.white.opacity(configuration.isPressed ? 0.6 : 1)))
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(tint == .black ? Theme.hairline : tint.opacity(0.4), lineWidth: 1))
            .contentShape(Rectangle())
    }
}

/// Buttons inside the black notch.
struct NotchFilledButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(13, .semibold))
            .foregroundStyle(.black)
            .padding(.horizontal, 16)
            .frame(height: 36)
            .background(RoundedRectangle(cornerRadius: 2).fill(Color.white.opacity(configuration.isPressed ? 0.8 : 1)))
            .contentShape(Rectangle())
    }
}

struct NotchOutlineButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(13, .medium))
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .frame(height: 36)
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.white.opacity(configuration.isPressed ? 0.4 : 0.7), lineWidth: 1))
            .contentShape(Rectangle())
    }
}

/// Compact buttons for the Dynamic-Island-sized notch (24 pt high).
struct NotchSmallFilledButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(11.5, .semibold))
            .foregroundStyle(.black)
            .padding(.horizontal, 10)
            .frame(height: 24)
            .background(RoundedRectangle(cornerRadius: 2).fill(Color.white.opacity(configuration.isPressed ? 0.8 : 1)))
            .contentShape(Rectangle())
    }
}

struct NotchSmallOutlineButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(11.5, .medium))
            .foregroundStyle(.white)
            .padding(.horizontal, 10)
            .frame(height: 24)
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.white.opacity(configuration.isPressed ? 0.4 : 0.6), lineWidth: 1))
            .contentShape(Rectangle())
    }
}

struct NotchSmallTextButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(Theme.sans(11.5)).foregroundStyle(Theme.notchText.opacity(configuration.isPressed ? 0.6 : 1))
            .frame(height: 24).contentShape(Rectangle())
    }
}

struct PlainTextButtonStyle: ButtonStyle {
    var color: Color = Theme.notchText
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(Theme.sans(13)).foregroundStyle(color.opacity(configuration.isPressed ? 0.6 : 1))
            .frame(height: 36).contentShape(Rectangle())
    }
}

/// Keyboard shortcut badge like "⌘ P".
struct Kbd: View {
    var text: String
    var dark = false
    var body: some View {
        Text(text).font(Theme.mono(9.5)).tracking(0.5)
            .foregroundStyle(dark ? Color.white.opacity(0.8) : Theme.mutedText)
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 2).fill(dark ? Color.white.opacity(0.18) : Theme.muted2))
    }
}

/// The Flowline mark: a step line. Same path as the storyboard SVG (M3 17h6V7h6v6h6 in a 24 box).
struct StepMark: Shape {
    func path(in r: CGRect) -> Path {
        let s = r.width / 24
        var p = Path()
        p.move(to: CGPoint(x: r.minX + 3 * s, y: r.minY + 17 * s))
        p.addLine(to: CGPoint(x: r.minX + 9 * s, y: r.minY + 17 * s))
        p.addLine(to: CGPoint(x: r.minX + 9 * s, y: r.minY + 7 * s))
        p.addLine(to: CGPoint(x: r.minX + 15 * s, y: r.minY + 7 * s))
        p.addLine(to: CGPoint(x: r.minX + 15 * s, y: r.minY + 13 * s))
        p.addLine(to: CGPoint(x: r.minX + 21 * s, y: r.minY + 13 * s))
        return p
    }
}

struct MarkBadge: View {
    var size: CGFloat = 36
    var dark = true
    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.22)
            .fill(dark ? Color.black : Color.white)
            .frame(width: size, height: size)
            .overlay(StepMark().stroke(dark ? Color.white : Color.black, style: StrokeStyle(lineWidth: size * 0.1, lineCap: .square))
                .frame(width: size * 0.55, height: size * 0.55))
    }
}

/// Coloured app square with an SF Symbol, for a tool token.
struct ToolIcon: View {
    var tool: String
    var size: CGFloat = 22
    var body: some View {
        let (bg, symbol) = ToolIcon.style(tool)
        RoundedRectangle(cornerRadius: size * 0.23).fill(bg)
            .frame(width: size, height: size)
            .overlay(Image(systemName: symbol).font(.system(size: size * 0.5, weight: .semibold)).foregroundStyle(.white))
    }
    static func style(_ tool: String) -> (Color, String) {
        switch tool {
        case "mail": return (Theme.blue, "envelope.fill")
        case "docs": return (Color(hex: 0x1f2a44), "doc.text.fill")
        case "sheets": return (Theme.teal, "tablecells.fill")
        case "slides": return (Color(hex: 0xD9741A), "play.rectangle.fill")
        case "chat": return (Color(hex: 0x1f2428), "bubble.left.fill")
        case "call": return (Color(hex: 0x1f2428), "phone.fill")
        case "browser": return (Theme.blue, "globe")
        case "finder": return (Theme.blue, "folder.fill")
        case "preview": return (Color(hex: 0x6b7280), "eye.fill")
        case "notes": return (Color(hex: 0xE2B33C), "note.text")
        case "calendar": return (Theme.red, "calendar")
        case "code": return (Color(hex: 0x1f2428), "chevron.left.forwardslash.chevron.right")
        case "design": return (Theme.violet, "paintbrush.fill")
        default: return (Theme.grey, "app.fill")
        }
    }
}

/// Up to two overlapping tool icons, or an outlined clock for waiting.
struct ToolStack: View {
    var tools: [String]
    var waiting = false
    var body: some View {
        if waiting {
            Circle().stroke(Theme.hairline, lineWidth: 1).frame(width: 22, height: 22)
                .overlay(Image(systemName: "clock").font(.system(size: 11)).foregroundStyle(Theme.mutedText))
        } else if tools.isEmpty {
            ToolIcon(tool: "other")
        } else if tools.count == 1 {
            ToolIcon(tool: tools[0])
        } else {
            ZStack(alignment: .leading) {
                ToolIcon(tool: tools[0])
                ToolIcon(tool: tools[1]).overlay(RoundedRectangle(cornerRadius: 5).stroke(Color.white, lineWidth: 1.5)).offset(x: 12)
            }.frame(width: 34, alignment: .leading)
        }
    }
}

struct LockIcon: View {
    var size: CGFloat = 28
    var dark = false
    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.5)
            .fill(dark ? Color.black : Color.white)
            .overlay(RoundedRectangle(cornerRadius: size * 0.5).stroke(dark ? Color.clear : Theme.hairline, lineWidth: 1))
            .frame(width: size, height: size)
            .overlay(Image(systemName: "lock.fill").font(.system(size: size * 0.42)).foregroundStyle(dark ? .white : Theme.mutedText))
    }
}
