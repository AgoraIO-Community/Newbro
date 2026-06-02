# macOS App Icon & Menu Bar Logo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the macOS Newbro Executor app a brand app icon (off-white squircle + the "bro" logo) and replace the generic menu bar SF Symbol with an in-code bro glyph carrying an aggregate status pip, plus per-profile status dots in the dropdown.

**Architecture:** A UI-free `StatusTone` mapping in `NewbroExecutorCore` (testable) drives both the menu bar pip color and the dropdown dot color. The menu bar bro is a SwiftUI `Shape` (eyes/mouth as even-odd cut-outs) filled with `Color.primary` so it adapts to light/dark. The app icon is produced by a committed Swift/CoreGraphics generator into a committed `AppIcon.icns`, which `package-app.sh` copies into the bundle.

**Tech Stack:** Swift / SwiftUI / AppKit, Swift Package Manager, XCTest, `iconutil`, `sips`.

**Reference spec:** `docs/superpowers/specs/2026-06-01-macos-app-menubar-logos-design.md`

---

## File Structure

- **Create** `macos/Sources/NewbroExecutorCore/StatusTone.swift` — `StatusTone` enum + `statusTone(_:)`. Pure, no UI imports.
- **Create** `macos/Tests/NewbroExecutorCoreTests/StatusToneTests.swift` — unit tests for the mapping and aggregate composition.
- **Create** `macos/Sources/NewbroExecutor/BroGlyph.swift` — `BroShape` (SwiftUI), `MenuBarLabel`, and `StatusTone` → `Color` / `NSImage` dot helpers (app layer).
- **Create** `macos/tools/make-appicon.swift` + `macos/tools/make-appicon.sh` — icon generator.
- **Create** `macos/Resources/AppIcon.icns` — committed generated output.
- **Modify** `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift` — use `MenuBarLabel`; remove `glyph(for:)`.
- **Modify** `macos/Sources/NewbroExecutor/MenuContent.swift` — per-profile status dot.
- **Modify** `macos/package-app.sh` — copy `AppIcon.icns`, add `CFBundleIconFile`.

> **TDD note:** Only `StatusTone` (Task 1) has automated unit tests — it's the pure logic. The drawn glyph, icon, and menu rendering are validated visually (Tasks 2–5) by building/launching and inspecting rendered pixels, because they are presentation with no return value to assert.

---

### Task 1: `StatusTone` mapping in Core

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/StatusTone.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/StatusToneTests.swift`

- [ ] **Step 1: Write the failing test**

Create `macos/Tests/NewbroExecutorCoreTests/StatusToneTests.swift`:

```swift
import XCTest
@testable import NewbroExecutorCore

final class StatusToneTests: XCTestCase {
    func testToneForEachStatus() {
        XCTAssertEqual(statusTone(.ready), .ok)
        XCTAssertEqual(statusTone(.starting), .busy)
        XCTAssertEqual(statusTone(.connecting), .busy)
        XCTAssertEqual(statusTone(.retrying), .busy)
        XCTAssertEqual(statusTone(.disconnected), .attention)
        XCTAssertEqual(statusTone(.error), .attention)
        XCTAssertEqual(statusTone(.idle), .idle)
        XCTAssertEqual(statusTone(.stopped), .idle)
    }

    func testToneOfAggregateAcrossProfiles() {
        XCTAssertEqual(statusTone(aggregateStatus([.ready, .ready])), .ok)
        XCTAssertEqual(statusTone(aggregateStatus([.ready, .error])), .attention)
        XCTAssertEqual(statusTone(aggregateStatus([.ready, .connecting])), .busy)
        XCTAssertEqual(statusTone(aggregateStatus([.stopped, .idle])), .idle)
        XCTAssertEqual(statusTone(aggregateStatus([])), .idle)
    }
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `swift test --package-path macos --filter StatusToneTests`
Expected: FAIL to build with "cannot find 'statusTone' in scope" / "cannot find 'StatusTone'".

- [ ] **Step 3: Write the implementation**

Create `macos/Sources/NewbroExecutorCore/StatusTone.swift`:

```swift
/// Semantic grouping of `NodeStatus` for UI indicators. Kept free of
/// SwiftUI/AppKit so it stays in Core and is unit-testable; the app layer maps
/// each tone to a concrete color.
public enum StatusTone: String, Equatable, Sendable {
    case ok        // ready
    case busy      // starting, connecting, retrying
    case attention // disconnected, error
    case idle      // idle, stopped
}

public func statusTone(_ status: NodeStatus) -> StatusTone {
    switch status {
    case .ready:
        return .ok
    case .starting, .connecting, .retrying:
        return .busy
    case .disconnected, .error:
        return .attention
    case .idle, .stopped:
        return .idle
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `swift test --package-path macos --filter StatusToneTests`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/StatusTone.swift macos/Tests/NewbroExecutorCoreTests/StatusToneTests.swift
git commit -m "feat(macos): add StatusTone mapping in Core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Menu bar bro glyph + status pip

**Files:**
- Create: `macos/Sources/NewbroExecutor/BroGlyph.swift`
- Modify: `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`

- [ ] **Step 1: Create the glyph, label, and color helpers**

Create `macos/Sources/NewbroExecutor/BroGlyph.swift`:

```swift
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
```

- [ ] **Step 2: Wire the label into the menu bar**

In `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`, replace the `body` and remove `glyph(for:)`. Change:

```swift
    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model)
        } label: {
            Image(systemName: glyph(for: model.aggregate()))
        }
        .menuBarExtraStyle(.menu)
    }

    private func glyph(for status: NodeStatus) -> String {
        switch status {
        case .ready: return "circle.fill"
        case .connecting, .starting, .retrying: return "arrow.triangle.2.circlepath"
        case .disconnected, .error: return "exclamationmark.triangle.fill"
        case .stopped, .idle: return "circle"
        }
    }
```

to:

```swift
    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model)
        } label: {
            MenuBarLabel(tone: statusTone(model.aggregate()))
        }
        .menuBarExtraStyle(.menu)
    }
```

- [ ] **Step 3: Build**

Run: `swift build --package-path macos`
Expected: builds with no errors.

- [ ] **Step 4: Launch and visually verify the menu bar icon**

Run:
```bash
./macos/package-app.sh
open "macos/dist/Newbro Executor.app"
sleep 2
screencapture -x /tmp/menubar-check.png
```
Then Read `/tmp/menubar-check.png` and confirm: the bro mark appears in the top-right menu bar with visible eyes/mouth and a gray pip (idle, nothing running). The head must read upright (dome up). If `screencapture` is blocked by permissions, ask the user to confirm visually instead.

If the bro is hard to read at 18px, reduce detail (drop the smile cut-out by removing the three smile lines in `BroShape`). If `Color.primary` does not invert between light/dark menu bars, switch `BroGlyph` to render a template `NSImage` of `BroShape` via `Image(nsImage:)` (set `isTemplate = true`) while keeping the pip overlay — note this in the commit message.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutor/BroGlyph.swift macos/Sources/NewbroExecutor/NewbroExecutorApp.swift
git commit -m "feat(macos): brand bro glyph with status pip in the menu bar

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Per-profile status dots in the dropdown

**Files:**
- Modify: `macos/Sources/NewbroExecutor/MenuContent.swift`

- [ ] **Step 1: Add a colored dot to each profile row**

In `macos/Sources/NewbroExecutor/MenuContent.swift`, replace the `Menu("…") { … }` for each profile. Change:

```swift
            Menu("\(profile.label) — \(status.rawValue)\(model.conflicts().contains(profile.id) ? "  (duplicate node id)" : "")") {
                if running {
                    Button("Stop") { model.stop(profile) }
                    Button("Restart") { model.restart(profile) }
                } else {
                    Button("Start") { model.start(profile) }
                }
                Toggle("Auto-activate at login", isOn: Binding(
                    get: { profile.autoActivate },
                    set: { _ in model.toggleAutoActivate(profile) }))
                Button("View recent log…") { model.viewLog(profile.id) }
                Button("Edit…") { model.editProfile(profile.id) }
                Button("Delete") { model.delete(profile) }
            }
```

to:

```swift
            let title = "\(profile.label) — \(status.rawValue)"
                + (model.conflicts().contains(profile.id) ? "  (duplicate node id)" : "")
            Menu {
                if running {
                    Button("Stop") { model.stop(profile) }
                    Button("Restart") { model.restart(profile) }
                } else {
                    Button("Start") { model.start(profile) }
                }
                Toggle("Auto-activate at login", isOn: Binding(
                    get: { profile.autoActivate },
                    set: { _ in model.toggleAutoActivate(profile) }))
                Button("View recent log…") { model.viewLog(profile.id) }
                Button("Edit…") { model.editProfile(profile.id) }
                Button("Delete") { model.delete(profile) }
            } label: {
                Label {
                    Text(title)
                } icon: {
                    Image(nsImage: statusTone(status).dotImage())
                }
            }
```

- [ ] **Step 2: Build**

Run: `swift build --package-path macos`
Expected: builds with no errors.

- [ ] **Step 3: Launch and visually verify the dropdown**

Run:
```bash
./macos/package-app.sh
open "macos/dist/Newbro Executor.app"
```
Click the menu bar bro to open the dropdown. Confirm each profile row shows a colored dot matching its status (gray when idle/stopped). If there are no profiles yet, add one via "Add profile…" first. If SwiftUI drops the custom icon for the submenu label (no dot shows), revert this row to the original `Menu("title") { … }` text-only form and note in the commit that SwiftUI menu labels don't support colored icons here. Ask the user to confirm if you cannot see the dropdown yourself.

- [ ] **Step 4: Commit**

```bash
git add macos/Sources/NewbroExecutor/MenuContent.swift
git commit -m "feat(macos): per-profile status dots in the menu dropdown

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: App icon generator and committed `AppIcon.icns`

**Files:**
- Create: `macos/tools/make-appicon.swift`
- Create: `macos/tools/make-appicon.sh`
- Create: `macos/Resources/AppIcon.icns` (generated, committed)

- [ ] **Step 1: Create the CoreGraphics generator**

Create `macos/tools/make-appicon.swift`:

```swift
import AppKit
import Foundation

// usage: swift make-appicon.swift <logo.png> <out-iconset-dir>
let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write(Data("usage: make-appicon.swift <logo.png> <iconset-dir>\n".utf8))
    exit(2)
}
let logoPath = args[1]
let outDir = args[2]

guard let logo = NSImage(contentsOfFile: logoPath) else {
    FileHandle.standardError.write(Data("error: cannot load \(logoPath)\n".utf8))
    exit(1)
}

let bg = NSColor(srgbRed: 0.957, green: 0.961, blue: 0.969, alpha: 1) // #f4f5f7

func render(_ side: Int) -> Data {
    let size = CGFloat(side)
    let img = NSImage(size: NSSize(width: size, height: size))
    img.lockFocus()
    // Off-white squircle filling the tile with a small transparent margin.
    let margin = size * 0.06
    let rectSide = size - margin * 2
    let bgRect = NSRect(x: margin, y: margin, width: rectSide, height: rectSide)
    let radius = rectSide * 0.225
    bg.setFill()
    NSBezierPath(roundedRect: bgRect, xRadius: radius, yRadius: radius).fill()
    // Bro centered at ~62% of the tile.
    let logoSide = size * 0.62
    let logoRect = NSRect(x: (size - logoSide) / 2, y: (size - logoSide) / 2,
                          width: logoSide, height: logoSide)
    logo.draw(in: logoRect, from: .zero, operation: .sourceOver, fraction: 1.0)
    img.unlockFocus()
    guard let tiff = img.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else {
        FileHandle.standardError.write(Data("error: png encode failed at \(side)px\n".utf8))
        exit(1)
    }
    return png
}

let sizes: [(String, Int)] = [
    ("icon_16x16", 16), ("icon_16x16@2x", 32),
    ("icon_32x32", 32), ("icon_32x32@2x", 64),
    ("icon_128x128", 128), ("icon_128x128@2x", 256),
    ("icon_256x256", 256), ("icon_256x256@2x", 512),
    ("icon_512x512", 512), ("icon_512x512@2x", 1024),
]

do {
    try FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)
    for (name, px) in sizes {
        let path = "\(outDir)/\(name).png"
        try render(px).write(to: URL(fileURLWithPath: path))
        FileHandle.standardError.write(Data("wrote \(path)\n".utf8))
    }
} catch {
    FileHandle.standardError.write(Data("error: \(error)\n".utf8))
    exit(1)
}
```

- [ ] **Step 2: Create the wrapper script**

Create `macos/tools/make-appicon.sh`:

```bash
#!/usr/bin/env bash
# Regenerate macos/Resources/AppIcon.icns from the brand logo.
# Native tooling only (sips + swift + iconutil); run when the logo changes.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LOGO_WEBP="$REPO/design/assets/newbro-logo.webp"
OUT="$HERE/../Resources/AppIcon.icns"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
LOGO_PNG="$WORK/logo.png"
ICONSET="$WORK/AppIcon.iconset"

echo "[make-appicon] converting logo webp -> png"
sips -s format png "$LOGO_WEBP" --out "$LOGO_PNG" >/dev/null

echo "[make-appicon] rendering iconset"
swift "$HERE/make-appicon.swift" "$LOGO_PNG" "$ICONSET"

echo "[make-appicon] building icns"
mkdir -p "$HERE/../Resources"
iconutil -c icns "$ICONSET" -o "$OUT"
echo "[make-appicon] wrote $OUT"
```

- [ ] **Step 3: Make the wrapper executable and run it**

Run:
```bash
chmod +x macos/tools/make-appicon.sh
./macos/tools/make-appicon.sh
ls -la macos/Resources/AppIcon.icns
```
Expected: prints progress and `AppIcon.icns` exists (tens of KB, not empty).

- [ ] **Step 4: Visually verify the rendered icon**

Run:
```bash
sips -s format png macos/Resources/AppIcon.icns --out /tmp/appicon-preview.png >/dev/null
sips -g pixelWidth /tmp/appicon-preview.png
```
Then Read `/tmp/appicon-preview.png` and confirm: off-white rounded-square tile with the dark bro centered, well-proportioned (not clipped, not tiny). If the logo is too large/small or off-center, adjust the `0.62` scale or `0.06` margin in `make-appicon.swift` and re-run Steps 3–4.

- [ ] **Step 5: Commit**

```bash
git add macos/tools/make-appicon.swift macos/tools/make-appicon.sh macos/Resources/AppIcon.icns
git commit -m "feat(macos): app icon generator and generated AppIcon.icns

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Bundle the icon in `package-app.sh`

**Files:**
- Modify: `macos/package-app.sh`

- [ ] **Step 1: Copy the icns and declare it in Info.plist**

In `macos/package-app.sh`, after the line `cp "$BIN_PATH" "$APP/Contents/MacOS/$BIN_NAME"`, add a Resources copy. Change:

```bash
echo "[package-app] assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_PATH" "$APP/Contents/MacOS/$BIN_NAME"
```

to:

```bash
echo "[package-app] assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_PATH" "$APP/Contents/MacOS/$BIN_NAME"
mkdir -p "$APP/Contents/Resources"
cp "$HERE/Resources/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
```

Then add the `CFBundleIconFile` key to the Info.plist heredoc. Change:

```bash
  <key>CFBundleExecutable</key><string>NewbroExecutor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
```

to:

```bash
  <key>CFBundleExecutable</key><string>NewbroExecutor</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
```

- [ ] **Step 2: Build the bundle and verify the icon is embedded**

Run:
```bash
./macos/package-app.sh
ls -la "macos/dist/Newbro Executor.app/Contents/Resources/AppIcon.icns"
plutil -p "macos/dist/Newbro Executor.app/Contents/Info.plist" | grep CFBundleIconFile
```
Expected: the icns exists in the bundle and `CFBundleIconFile => "AppIcon"` prints.

- [ ] **Step 3: Visually verify the Finder icon**

Run:
```bash
# Refresh the icon cache for the freshly built bundle, then snapshot it.
touch "macos/dist/Newbro Executor.app"
qlmanage -t -s 512 -o /tmp "macos/dist/Newbro Executor.app" >/dev/null 2>&1 || true
ls /tmp/*.png 2>/dev/null
```
Read the generated thumbnail (`/tmp/Newbro Executor.app.png`) if present and confirm the app shows the bro icon. If `qlmanage` produces nothing, open Finder at `macos/dist/` and ask the user to confirm the icon visually.

- [ ] **Step 4: Commit**

```bash
git add macos/package-app.sh
git commit -m "build(macos): bundle AppIcon.icns and set CFBundleIconFile

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Run the full test gate once at the end:** `swift test --package-path macos` — expected: all tests pass (existing 36 + the 2 new `StatusToneTests`).
- **Visual verification is real verification here.** Don't claim the glyph/icon "looks right" without reading the captured PNG (or getting explicit user confirmation). If a capture tool is blocked by macOS permissions, say so and defer to the user.
- **Fallbacks are pre-authorized** for the two rendering risks only: (1) `Color.primary` not inverting → template `NSImage` bro; (2) SwiftUI menu dropping the colored icon → revert that one row to text-only. Both are noted inline in their tasks. Do not introduce other fallbacks without asking.
- **Coordinate system:** `BroShape` is designed in a 24×24 box with y pointing down (SwiftUI default). The head must render dome-up; if it renders inverted, the rounded-rect approach in this plan should already be orientation-safe (no arcs), so an inverted result means a different bug — investigate rather than flipping blindly.
