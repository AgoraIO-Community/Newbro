import AppKit
import SwiftUI

/// Opens auxiliary windows from the menu-bar (`.accessory`) app.
///
/// SwiftUI's `openWindow` is delivered unreliably from a `.menu`-style
/// `MenuBarExtra`, and an accessory app does not bring new windows to the
/// front on its own. Hosting the SwiftUI views in `NSWindow`s and activating
/// the app explicitly is the reliable path.
@MainActor
final class WindowManager {
    private var windows: [String: NSWindow] = [:]

    func show<Content: View>(
        id: String,
        title: String,
        size: NSSize,
        @ViewBuilder content: () -> Content
    ) {
        if let existing = windows[id] {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let window = NSWindow(contentViewController: NSHostingController(rootView: content()))
        window.title = title
        window.styleMask = [.titled, .closable]
        window.setContentSize(size)
        window.isReleasedWhenClosed = false
        window.center()
        windows[id] = window
        NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification, object: window, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.windows[id] = nil }
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func close(id: String) {
        windows[id]?.close()
    }
}
