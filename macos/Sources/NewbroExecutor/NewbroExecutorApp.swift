import SwiftUI
import AppKit
import Combine
import NewbroExecutorCore

@main
struct NewbroExecutorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        // The UI lives entirely in the AppDelegate's NSStatusItem + AppKit
        // windows; this empty Settings scene just satisfies the App protocol.
        Settings { EmptyView() }
    }
}

/// An `NSMenuItem` that runs a closure when selected.
@MainActor
final class ActionMenuItem: NSMenuItem {
    private let handler: () -> Void
    init(title: String, state: NSControl.StateValue = .off, _ handler: @escaping () -> Void) {
        self.handler = handler
        super.init(title: title, action: #selector(invoke), keyEquivalent: "")
        self.target = self
        self.state = state
    }
    required init(coder: NSCoder) { fatalError("not supported") }
    @objc private func invoke() { handler() }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var model: AppModel!
    private var statusItem: NSStatusItem!
    private var pip: NSView!
    private var cancellable: AnyCancellable?
    private var updates: UpdateService!
    private var updateTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        let model = AppModel()
        self.model = model

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem = item
        if let button = item.button {
            button.image = menuBarBroTemplate()       // template → system tints white/dark
            button.imagePosition = .imageOnly

            // Colored status pip pinned to the icon's bottom-trailing corner.
            let pip = NSView()
            pip.wantsLayer = true
            pip.layer?.cornerRadius = 3.5
            pip.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(pip)
            NSLayoutConstraint.activate([
                pip.widthAnchor.constraint(equalToConstant: 7),
                pip.heightAnchor.constraint(equalToConstant: 7),
                pip.trailingAnchor.constraint(equalTo: button.trailingAnchor, constant: -1),
                pip.bottomAnchor.constraint(equalTo: button.bottomAnchor, constant: -2),
            ])
            self.pip = pip
        }

        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu

        // Re-tint the pip whenever any profile's status changes.
        cancellable = model.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.updatePip() }
        updatePip()

        let releaseClient = ReleaseClient()
        let updates = UpdateService(
            fetchLatest: { try? await releaseClient.latest() },
            installedCLIVersion: { [weak model] in model?.installedCLIVersion() },
            appVersion: { [weak model] in model?.appVersion },
            activeProfileIDs: { [weak model] in model?.activeProfileIDs() ?? [] },
            stopProfile: { [weak model] id in model?.stop(profileID: id) },
            startProfile: { [weak model] id in model?.start(profileID: id) },
            runInstaller: { [weak model] completion in model?.runInstaller(completion) })
        self.updates = updates
        Task { await updates.check() }
        updateTimer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.updates.check() }
        }
    }

    private func updatePip() {
        pip?.layer?.backgroundColor = statusTone(model.aggregate()).nsColor.cgColor
    }

    // MARK: - Menu (rebuilt from the model each time it opens)

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        build(into: menu)
    }

    private func build(into menu: NSMenu) {
        model.refreshCodexStatus()

        if !model.runtimeAvailable {
            menu.addItem(NSMenuItem(title: "Node runtime not found", action: nil, keyEquivalent: ""))
            menu.addItem(ActionMenuItem(title: "Install runtime…") { [weak self] in self?.model.installRuntime() })
            menu.addItem(.separator())
        }

        let codexRow = NSMenuItem(title: model.codexStatus.menuTitle, action: nil, keyEquivalent: "")
        codexRow.isEnabled = false
        menu.addItem(codexRow)
        menu.addItem(.separator())

        for profile in model.profiles {
            let status = model.status(of: profile)
            let active = model.isActive(profile)
            let running = active && status != .stopped && status != .error
            let conflict = model.conflicts().contains(profile.id) ? "  (duplicate node id)" : ""

            let row = NSMenuItem(title: "\(profile.label) — \(status.rawValue)\(conflict)",
                                 action: nil, keyEquivalent: "")
            row.image = statusTone(status).dotImage()

            let sub = NSMenu()
            if running {
                sub.addItem(ActionMenuItem(title: "Stop") { [weak self] in self?.model.stop(profile) })
                sub.addItem(ActionMenuItem(title: "Restart") { [weak self] in self?.model.restart(profile) })
            } else {
                sub.addItem(ActionMenuItem(title: "Start") { [weak self] in self?.model.start(profile) })
            }
            sub.addItem(ActionMenuItem(title: "Auto-activate at login",
                                       state: profile.autoActivate ? .on : .off) { [weak self] in
                self?.model.toggleAutoActivate(profile)
            })
            sub.addItem(ActionMenuItem(title: "View recent log…") { [weak self] in self?.model.viewLog(profile.id) })
            sub.addItem(ActionMenuItem(title: "Edit…") { [weak self] in self?.model.editProfile(profile.id) })
            sub.addItem(ActionMenuItem(title: "Delete") { [weak self] in self?.model.delete(profile) })
            row.submenu = sub
            menu.addItem(row)
        }

        if !model.profiles.isEmpty {
            menu.addItem(.separator())
        }
        menu.addItem(ActionMenuItem(title: "Paste connect command…") { [weak self] in self?.pasteConnectCommand() })
        menu.addItem(ActionMenuItem(title: "Launch at login",
                                    state: model.loginItemEnabled ? .on : .off) { [weak self] in
            self?.model.toggleLoginItem()
        })

        menu.addItem(.separator())
        let rows = updateMenuRows(installedCLI: updates.installedCLI,
                                  installedApp: model.appVersion,
                                  status: updates.status)
        menu.addItem(disabledMenuItem(title: rows.cliVersionRow))
        menu.addItem(disabledMenuItem(title: rows.appVersionRow))

        if updates.isUpdating {
            menu.addItem(disabledMenuItem(title: "Updating CLI…"))
        } else if let cliUpdateRow = rows.cliUpdateRow {
            menu.addItem(disabledMenuItem(title: cliUpdateRow))
        }

        if let appUpdateRow = rows.appUpdateRow {
            menu.addItem(disabledMenuItem(title: appUpdateRow))
        }

        if let available = updates.status.cliUpdate, !updates.isUpdating {
            menu.addItem(ActionMenuItem(title: "Update CLI to \(available)") { [weak self] in
                self?.updates.updateCLI()
            })
        }
        menu.addItem(ActionMenuItem(title: "Check for Updates…") { [weak self] in
            Task { @MainActor in await self?.updates.check() }
        })
        if let appAvailable = updates.status.appUpdate {
            menu.addItem(ActionMenuItem(title: "Download app update \(appAvailable)…") { [weak self] in
                guard let url = self?.updates.releasePageURL else { return }
                NSWorkspace.shared.open(url)
            })
        }
        if let error = updates.lastError {
            let errorRow = NSMenuItem(title: error, action: nil, keyEquivalent: "")
            errorRow.isEnabled = false
            menu.addItem(errorRow)
        }

        menu.addItem(.separator())
        menu.addItem(ActionMenuItem(title: "Quit") { [weak self] in self?.model.quit() })
    }

    private func disabledMenuItem(title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }

    private func pasteConnectCommand() {
        guard let text = NSPasteboard.general.string(forType: .string) else { return }
        _ = try? model.addFromConnectCommand(text)
    }
}
