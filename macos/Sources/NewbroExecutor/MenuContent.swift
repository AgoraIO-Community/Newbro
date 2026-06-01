import SwiftUI
import NewbroExecutorCore

struct MenuContent: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if !model.runtimeAvailable {
            Text("Node runtime not found")
            Button("Install runtime…") { model.installRuntime() }
            Divider()
        }
        ForEach(model.profiles) { profile in
            let active = model.isActive(profile)
            let status = model.status(of: profile)
            let running = active && status != .stopped && status != .error
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
                Button("View recent log…") { openWindow(id: "log", value: profile.id) }
                Button("Edit…") { openWindow(id: "edit", value: profile.id) }
                Button("Delete") { model.delete(profile) }
            }
        }
        Divider()
        Button("Add profile…") {
            let new = model.emptyProfile()
            model.upsert(new)
            openWindow(id: "edit", value: new.id)
        }
        Button("Paste connect command…") { pasteConnectCommand() }
        Toggle("Launch at login", isOn: Binding(
            get: { model.loginItemEnabled },
            set: { _ in model.toggleLoginItem() }))
        Divider()
        Button("Quit") { model.quit() }
    }

    private func pasteConnectCommand() {
        guard let text = NSPasteboard.general.string(forType: .string) else { return }
        try? model.addFromConnectCommand(text)
    }
}
