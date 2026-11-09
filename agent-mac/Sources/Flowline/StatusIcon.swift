import AppKit

/// Menu-bar template image: the step-line glyph knocked out of a small rounded square.
enum StatusIcon {
    static func image(running: Bool = false) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let img = NSImage(size: size, flipped: true) { rect in
            let sq = NSRect(x: 1.5, y: 1.5, width: 15, height: 15)
            let path = NSBezierPath(roundedRect: sq, xRadius: 4, yRadius: 4)
            NSColor.black.setFill()
            path.fill()
            // glyph (24-box path M3 17h6V7h6v6h6) scaled into a 11pt box centred in the square
            let s: CGFloat = 11 / 24
            let ox = sq.midX - 5.5, oy = sq.midY - 5.5
            let g = NSBezierPath()
            g.move(to: NSPoint(x: ox + 3 * s, y: oy + 17 * s))
            g.line(to: NSPoint(x: ox + 9 * s, y: oy + 17 * s))
            g.line(to: NSPoint(x: ox + 9 * s, y: oy + 7 * s))
            g.line(to: NSPoint(x: ox + 15 * s, y: oy + 7 * s))
            g.line(to: NSPoint(x: ox + 15 * s, y: oy + 13 * s))
            g.line(to: NSPoint(x: ox + 21 * s, y: oy + 13 * s))
            g.lineWidth = 1.7
            g.lineCapStyle = .square
            g.lineJoinStyle = .miter
            NSGraphicsContext.current?.compositingOperation = .destinationOut
            NSColor.black.setStroke()
            g.stroke()
            NSGraphicsContext.current?.compositingOperation = .sourceOver
            if running { // small dot top-right while an agent run is on screen
                NSColor.black.setFill()
                NSBezierPath(ovalIn: NSRect(x: 13, y: 0, width: 5, height: 5)).fill()
            }
            return true
        }
        img.isTemplate = true
        return img
    }
}
