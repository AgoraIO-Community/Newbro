# macOS App Icon & Menu Bar Logo — Design

Date: 2026-06-01
Status: Approved (design)

## Goal

Give the macOS Newbro Executor app a brand identity in two places:

1. **App icon** — the bundle icon shown in Finder, the DMG window, and the
   About box. Currently the app has no icon.
2. **Menu bar icon** — replace the generic SF Symbol status glyph with the
   Newbro "bro" mark, while preserving at-a-glance aggregate status.

Both derive from the existing brand logo at `design/assets/newbro-logo.webp`
(a friendly dark "bro" face — rounded hair, light face, two eyes, a smile;
1254×1254, transparent background).

## Current state

- `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift` renders the menu bar
  item via `MenuBarExtra { … } label: { Image(systemName: glyph(for: model.aggregate())) }`
  with `.menuBarExtraStyle(.menu)`. `glyph(for:)` maps `NodeStatus` to SF
  Symbols (`circle.fill`, `arrow.triangle.2.circlepath`,
  `exclamationmark.triangle.fill`, `circle`).
- `macos/Sources/NewbroExecutor/MenuContent.swift` lists each profile as a
  submenu titled `"<label> — <status>"` (text only, no status color).
- `NewbroExecutorCore` already computes a single aggregate across all profiles:
  `aggregateStatus(_:)` picks worst-first
  `error → disconnected → retrying → connecting → starting → ready → idle`.
  `NodeStatus` (in `NodeStatus.swift`) is a pure enum with no SwiftUI/AppKit
  dependency.
- `macos/package-app.sh` assembles `dist/Newbro Executor.app` and writes an
  `Info.plist` with no `CFBundleIconFile`. (It now also accepts
  `NEWBRO_APP_VERSION` / `NEWBRO_APP_ARCH`.)
- Native tooling available: `iconutil`, `sips`. **Not** available: Pillow,
  ImageMagick. So icon generation must avoid third-party image libraries.

## Design decisions (from brainstorm)

- **App icon style:** Option A — minimal light. Off-white squircle background
  (`#f4f5f7`) with the dark bro, faithful to the source logo.
- **Menu bar treatment:** Option B — a constant bro mark plus a small colored
  status pip carrying the aggregate status. (Not a static-bro-only approach,
  not status-only SF Symbols.)
- **Multiple profiles:** the bar pip shows the existing aggregate (worst-first);
  the dropdown disambiguates with a per-profile colored dot. No new aggregation
  rules — reuse `aggregateStatus`.

## Architecture

### Status tone (Core, UI-free, testable)

Add to `NewbroExecutorCore` a semantic mapping that the app layer turns into a
concrete color. Keeping it in Core (no SwiftUI import) preserves the existing
boundary and makes it unit-testable.

```
public enum StatusTone: String, Equatable, Sendable {
    case ok        // ready
    case busy      // starting, connecting, retrying
    case attention // disconnected, error
    case idle      // idle, stopped
}

public func statusTone(_ status: NodeStatus) -> StatusTone
```

Mapping:

| NodeStatus | StatusTone |
|------------|------------|
| `ready` | `ok` |
| `starting`, `connecting`, `retrying` | `busy` |
| `disconnected`, `error` | `attention` |
| `idle`, `stopped` | `idle` |

The app layer maps `StatusTone` → SwiftUI `Color`:
`ok → green (#10b981)`, `busy → amber (#f59e0b)`, `attention → red (#ef4444)`,
`idle → gray (#9ca3af)`.

### Menu bar icon (app layer)

Replace the `glyph(for:)` SF Symbol with an in-code composite:

- **Bro glyph:** a SwiftUI `Path`-based view (head + two eyes + smile) filled
  with `Color.primary` so it adapts to the light/dark menu bar. Drawn in code —
  no bundled asset, so `package-app.sh` needs no SwiftPM resource bundle copy.
- **Status pip:** a small `Circle` overlaid in a corner, filled with the color
  for `statusTone(model.aggregate())`.
- The `MenuBarExtra` label becomes a `ZStack { BroGlyph; pip }`.

**Verification requirement:** confirm on both a light and a dark menu bar that
`Color.primary` inverts correctly for the bro. If it does not, the fallback is
to render the bro as a template `NSImage` (`isTemplate = true`) shown via
`Image(nsImage:)`, keeping the colored pip as a SwiftUI overlay. Template
`NSImage` is guaranteed to invert with the menu bar; the colored pip is
intentionally non-adaptive.

### Dropdown per-profile dots (app layer)

In `MenuContent.swift`, prefix each profile row with a colored status dot using
the same `StatusTone` → color map. SwiftUI menus render **non-template**
`NSImage`s in their own colors, so generate a small filled-circle `NSImage`
(non-template) per tone and show it via `Label { Text("<label> — <status>") }
icon: { Image(nsImage: dot) }`. The existing text is retained.

### App icon generation & bundling

- **Generator:** `macos/tools/make-appicon.swift` (run with `swift`), using
  CoreGraphics/AppKit only:
  1. Load `design/assets/newbro-logo.webp` as an `NSImage` (macOS ImageIO
     decodes WebP on macOS 14). If direct WebP load proves unreliable, the
     wrapper first converts it to PNG with
     `sips -s format png … --out …` and the script loads the PNG.
  2. Render a 1024×1024 canvas: an off-white (`#f4f5f7`) rounded-rect
     (corner radius ≈ 0.225 × side, the macOS squircle proportion) filling the
     tile with a small transparent margin, then the bro centered at ≈ 62%.
  3. Emit the `.iconset` PNGs at all required sizes: 16, 32, 128, 256, 512 at
     @1x and @2x.
- **Wrapper:** `macos/tools/make-appicon.sh` runs the Swift generator into a
  temporary `AppIcon.iconset`, then `iconutil -c icns -o
  macos/Resources/AppIcon.icns`.
- **Committed output:** `macos/Resources/AppIcon.icns` is committed. CI and
  `package-app.sh` need no image tooling; the generator only re-runs when the
  logo changes.
- **Bundling:** `package-app.sh` copies `AppIcon.icns` into
  `Contents/Resources/` and adds `CFBundleIconFile = AppIcon` to `Info.plist`.

## File structure

- **New:**
  - `macos/Sources/NewbroExecutorCore/StatusTone.swift` — `StatusTone` enum and
    `statusTone(_:)`.
  - `macos/Sources/NewbroExecutor/BroGlyph.swift` — the SwiftUI `Path` bro view
    and the `StatusTone` → `Color` / dot-`NSImage` helpers (app layer).
  - `macos/tools/make-appicon.swift`, `macos/tools/make-appicon.sh`.
  - `macos/Resources/AppIcon.icns` (committed binary asset).
- **Modified:**
  - `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift` — menu bar label uses
    `BroGlyph` + pip; remove `glyph(for:)`.
  - `macos/Sources/NewbroExecutor/MenuContent.swift` — per-profile status dot.
  - `macos/package-app.sh` — copy `AppIcon.icns`, add `CFBundleIconFile`.
- **Tests:**
  - `macos/Tests/NewbroExecutorCoreTests/StatusToneTests.swift` — `statusTone`
    for every `NodeStatus`; aggregate composition (e.g. one `error` among
    `ready`s → `attention`; all `ready` → `ok`; empty/idle → `idle`).

## Testing strategy

- **Unit (automated):** `statusTone(_:)` mapping for all eight `NodeStatus`
  cases, and `statusTone(aggregateStatus(...))` composition across multi-profile
  sets. These run under the existing `swift test --package-path macos` gate.
- **Visual (manual, during implementation):** build the app, confirm the app
  icon renders correctly in Finder/About and in the DMG; confirm the menu bar
  bro adapts on light and dark menu bars and the pip color tracks aggregate
  status across multiple profiles; confirm the dropdown dots render in color.

## Out of scope (YAGNI)

- Custom DMG volume/background icon.
- Animated/spinning menu bar icon for the busy state.
- Separate light/dark app-icon variants.
- Replacing the source logo art itself.
