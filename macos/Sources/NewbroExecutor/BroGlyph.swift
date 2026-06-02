import SwiftUI
import AppKit
import NewbroExecutorCore

/// The Newbro "bro" mark as a single even-odd-filled shape: the eyes and mouth
/// are cut-outs so the menu bar shows through, giving a clean template look at
/// small sizes. Designed in a 24×24 space and scaled to the view.
struct BroShape: Shape {
    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 24.0
        let ox = rect.minX, oy = rect.minY
        func P(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: ox + x * s, y: oy + y * s) }
        func Rt(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> CGRect {
            CGRect(x: ox + x * s, y: oy + y * s, width: w * s, height: h * s)
        }

        var path = Path()
        // Head: rounded, slightly taller than wide (a "helmet" silhouette).
        path.addRoundedRect(in: Rt(5, 4, 14, 16), cornerSize: CGSize(width: 7 * s, height: 7 * s))
        // Eyes (cut-outs).
        path.addEllipse(in: Rt(9.4 - 1.7, 11.2 - 1.7, 3.4, 3.4))
        path.addEllipse(in: Rt(14.6 - 1.7, 11.2 - 1.7, 3.4, 3.4))
        // Smile (thin crescent cut-out).
        path.move(to: P(10.2, 14.0))
        path.addQuadCurve(to: P(13.8, 14.0), control: P(12, 16.0))
        path.addQuadCurve(to: P(10.2, 14.0), control: P(12, 15.0))
        path.closeSubpath()
        return path
    }
}

struct BroGlyph: View {
    var body: some View {
        BroShape()
            .fill(Color.primary, style: FillStyle(eoFill: true))
    }
}

/// Menu bar status item: the bro plus a small colored aggregate-status pip.
struct MenuBarLabel: View {
    let tone: StatusTone
    var body: some View {
        BroGlyph()
            .frame(width: 18, height: 18)
            .overlay(alignment: .bottomTrailing) {
                Circle()
                    .fill(tone.indicatorColor)
                    .frame(width: 7, height: 7)
            }
    }
}

extension StatusTone {
    /// Intentional, non-adaptive status colors (same values as the design spec).
    var indicatorColor: Color {
        switch self {
        case .ok:        return Color(red: 0.063, green: 0.725, blue: 0.506) // #10b981
        case .busy:      return Color(red: 0.961, green: 0.620, blue: 0.043) // #f59e0b
        case .attention: return Color(red: 0.937, green: 0.267, blue: 0.267) // #ef4444
        case .idle:      return Color(red: 0.612, green: 0.639, blue: 0.686) // #9ca3af
        }
    }

    /// A non-template colored dot so SwiftUI menus render it in color
    /// (template images would be tinted by the menu instead).
    func dotImage(diameter: CGFloat = 9) -> NSImage {
        let color: NSColor
        switch self {
        case .ok:        color = NSColor(srgbRed: 0.063, green: 0.725, blue: 0.506, alpha: 1)
        case .busy:      color = NSColor(srgbRed: 0.961, green: 0.620, blue: 0.043, alpha: 1)
        case .attention: color = NSColor(srgbRed: 0.937, green: 0.267, blue: 0.267, alpha: 1)
        case .idle:      color = NSColor(srgbRed: 0.612, green: 0.639, blue: 0.686, alpha: 1)
        }
        let size = NSSize(width: diameter, height: diameter)
        let image = NSImage(size: size)
        image.lockFocus()
        color.setFill()
        NSBezierPath(ovalIn: NSRect(origin: .zero, size: size)).fill()
        image.unlockFocus()
        image.isTemplate = false
        return image
    }
}
