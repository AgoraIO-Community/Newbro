import SwiftUI
import AppKit
import NewbroExecutorCore

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}

@main
struct NewbroExecutorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model)
        } label: {
            Image(systemName: glyph(for: model.aggregate()))
        }
        .menuBarExtraStyle(.menu)

        WindowGroup("Edit Profile", id: "edit", for: String.self) { $profileID in
            ProfileEditView(model: model, profileID: profileID)
        }
        WindowGroup("Recent Log", id: "log", for: String.self) { $profileID in
            LogView(model: model, profileID: profileID)
        }
    }

    private func glyph(for status: NodeStatus) -> String {
        switch status {
        case .ready: return "circle.fill"
        case .connecting, .starting, .retrying: return "arrow.triangle.2.circlepath"
        case .disconnected, .error: return "exclamationmark.triangle.fill"
        case .stopped, .idle: return "circle"
        }
    }
}
