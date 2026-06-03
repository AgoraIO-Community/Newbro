import Foundation
import SwiftUI
import Combine
import NewbroExecutorCore

@MainActor
final class AppModel: ObservableObject {
    @Published var profiles: [Profile] = []
    @Published var runtimeAvailable: Bool = true
    @Published var codexStatus = CommandStatus(
        command: nil,
        version: nil,
        menuTitle: "No Codex found. Newbro may not work properly.",
        isAvailable: false)
    @Published var installLog: String = ""

    private let supervisor: ProfileSupervisor
    private let notifier: ProfileNotifying
    private let notificationController: ProfileNotificationController
    private let eventRelay: ProfileLifecycleEventRelay
    private let store = ProfileStore()
    private let locator = RuntimeLocator()
    private let loginItem: LoginItem
    private var cancellables: Set<AnyCancellable> = []
    private var installProcess: NodeProcess?
    private var updateInstallProcess: NodeProcess?
    private let windows = WindowManager()
    // Blocking node lifecycle calls (stop/restart busy-wait up to 5s) run here
    // so they never freeze the main actor / menu.
    private let controlQueue = DispatchQueue(label: "newbro.ui.control")

    /// Login-shell PATH so node subprocesses (and the `node`-based `codex`
    /// they exec) resolve under the app's otherwise-minimal launchd env.
    private let childEnv = RuntimeLocator.childEnvironment()

    init(notifier: ProfileNotifying? = nil) {
        let notifier = notifier ?? MacProfileNotifier()
        self.notifier = notifier
        let notificationController = ProfileNotificationController(notifier: notifier)
        self.notificationController = notificationController
        let eventRelay = ProfileLifecycleEventRelay { event in
            await MainActor.run {
                notificationController.notify(event)
            }
        }
        self.eventRelay = eventRelay
        let loc = locator
        let env = RuntimeLocator.childEnvironment()
        self.loginItem = LoginItem(appPath: Bundle.main.bundlePath)
        self.supervisor = ProfileSupervisor(
            processFactory: .init(make: { argv, onLine, onExit in
                NodeProcess(argv: argv, environment: env, onLine: onLine, onExit: onExit)
            }),
            argvBuilder: { profile in
                loc.nodeArgv(for: profile) ?? []
            },
            logFactory: { profile in
                ProfileLog(path: ProfileLog.defaultPath(profileID: profile.id))
            },
            onEvent: { event in
                eventRelay.enqueue(event)
            })
        self.profiles = store.load()
        self.runtimeAvailable = locator.isRuntimeAvailable
        self.codexStatus = locator.codexRuntimeStatus()
        // Forward supervisor status changes so SwiftUI re-renders the menu/icon.
        supervisor.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)
        // Start auto-activate profiles at launch (login-item or manual).
        autostart()
    }

    func refreshRuntime() {
        runtimeAvailable = locator.isRuntimeAvailable
        codexStatus = locator.codexRuntimeStatus()
    }

    func autostart() {
        for action in autostartProfileActions(in: profiles,
                                              runtimeAvailable: runtimeAvailable,
                                              codexRuntimeAvailable: codexRuntimeAvailable) {
            perform(action)
        }
    }

    func isComplete(_ profile: Profile) -> Bool {
        profileIsComplete(profile)
    }

    func status(of profile: Profile) -> NodeStatus { supervisor.status(of: profile.id) }
    func aggregate() -> NodeStatus { supervisor.aggregateStatus() }
    func isActive(_ profile: Profile) -> Bool { supervisor.activeIDs().contains(profile.id) }
    func conflicts() -> Set<String> { conflictingProfileIDs(profiles) }

    // MARK: - Update support

    /// IDs of profiles currently being supervised (active).
    func activeProfileIDs() -> [String] { Array(supervisor.activeIDs()) }

    func start(profileID id: String) {
        perform(startProfileAction(in: profiles,
                                   profileID: id,
                                   runtimeAvailable: runtimeAvailable,
                                   codexRuntimeAvailable: codexRuntimeAvailable))
    }

    func stop(profileID id: String) {
        controlQueue.async { [supervisor] in supervisor.stop(id) }
    }

    /// The installed CLI version, read by running `newbro --version` (e.g. "0.1.2").
    func installedCLIVersion() -> String? {
        guard let newbro = locator.resolveNewbro() else { return nil }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: newbro)
        process.arguments = ["--version"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let output = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        // Output is "newbro 0.1.2" → take the last whitespace-separated token.
        return output.split(separator: " ").last.map(String.init)
    }

    /// Run the CLI installer/upgrader; `completion` is invoked on the main actor
    /// with the process exit code.
    func runInstaller(_ completion: @escaping @MainActor (Int32) -> Void) {
        let argv = locator.installCommandArgv()
        updateInstallProcess = NodeProcess(
            argv: argv,
            environment: childEnv,
            onLine: { _ in },
            onExit: { [weak self] code in
                Task { @MainActor in
                    self?.updateInstallProcess = nil
                    completion(code)
                }
            })
        updateInstallProcess?.start()
    }

    /// The app's own version from the bundle (CFBundleShortVersionString).
    var appVersion: String? {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
    }

    func start(_ profile: Profile) {
        perform(startProfileAction(for: profile,
                                   runtimeAvailable: runtimeAvailable,
                                   codexRuntimeAvailable: codexRuntimeAvailable))
    }
    func stop(_ profile: Profile) {
        controlQueue.async { [supervisor] in supervisor.stop(profile.id) }
    }
    func restart(_ profile: Profile) {
        perform(restartProfileAction(for: profile,
                                     runtimeAvailable: runtimeAvailable,
                                     codexRuntimeAvailable: codexRuntimeAvailable))
    }

    func quit() {
        // Stop every node before exiting so no orphaned subprocess survives.
        supervisor.stopAll()
        NSApplication.shared.terminate(nil)
    }

    func toggleAutoActivate(_ profile: Profile) {
        guard let index = profiles.firstIndex(where: { $0.id == profile.id }) else { return }
        profiles[index].autoActivate.toggle()
        try? store.save(profiles)
    }

    func delete(_ profile: Profile) {
        profiles.removeAll { $0.id == profile.id }
        try? store.save(profiles)
        controlQueue.async { [supervisor] in supervisor.stop(profile.id) }
    }

    func upsert(_ profile: Profile) {
        if let index = profiles.firstIndex(where: { $0.id == profile.id }) {
            profiles[index] = profile
        } else {
            profiles.append(profile)
        }
        try? store.save(profiles)
    }

    @discardableResult
    func addFromConnectCommand(_ text: String) throws -> Profile {
        let fields = try parseConnectCommand(text)
        let matchingIndex = firstMatchingProfileIndex(in: profiles,
                                                      baseURL: fields.baseURL,
                                                      nodeID: fields.nodeID)
        let wasUpdate = matchingIndex != nil
        let profile: Profile
        if let index = matchingIndex {
            profiles[index].token = fields.token
            profiles[index].enabledExecutors = fields.enabledExecutors
            profile = profiles[index]
        } else {
            profile = Profile(
                id: uniqueProfileID(existing: profiles),
                label: fields.baseURL,
                baseURL: fields.baseURL,
                nodeID: fields.nodeID,
                token: fields.token,
                enabledExecutors: fields.enabledExecutors)
            profiles.append(profile)
        }
        try? store.save(profiles)
        let didRequestStart = autoStartPastedProfile(profile)
        notifier.notify(
            title: pasteNotificationTitle(wasUpdate: wasUpdate, started: didRequestStart),
            body: profile.label)
        return profile
    }

    private func autoStartPastedProfile(_ profile: Profile) -> Bool {
        let action = pastedProfileAction(for: profile,
                                         runtimeAvailable: runtimeAvailable,
                                         isActive: isActive(profile),
                                         codexRuntimeAvailable: codexRuntimeAvailable)
        switch action {
        case .start(let profile):
            notificationController.suppressNextStart(profileID: profile.id)
        case .restart(let profile):
            notificationController.suppressNextRestart(profileID: profile.id)
        case nil:
            break
        }
        perform(action)
        return action != nil
    }

    private func pasteNotificationTitle(wasUpdate: Bool, started: Bool) -> String {
        switch (wasUpdate, started) {
        case (false, true): return "Profile created and started"
        case (false, false): return "Profile created"
        case (true, true): return "Profile updated and started"
        case (true, false): return "Profile updated"
        }
    }

    func canStart(_ profile: Profile) -> Bool {
        return profileCanStart(profile, codexRuntimeAvailable: codexRuntimeAvailable)
    }

    private func codexRuntimeAvailable() -> Bool {
        codexStatus.isAvailable
    }

    private func perform(_ action: ProfileLifecycleAction?) {
        guard let action else { return }
        perform(action)
    }

    private func perform(_ action: ProfileLifecycleAction) {
        switch action {
        case .start(let profile):
            supervisor.start(profile)
        case .restart(let profile):
            controlQueue.async { [supervisor] in supervisor.restart(profile) }
        }
    }

    func recentLog(_ profile: Profile) -> [String] {
        ProfileLog(path: ProfileLog.defaultPath(profileID: profile.id)).recent()
    }

    // MARK: - Windows

    func editProfile(_ profileID: String) {
        let windowID = "edit-\(profileID)"
        windows.show(id: windowID, title: "Edit Profile",
                     size: NSSize(width: 420, height: 360)) { [self] in
            ProfileEditView(model: self, profileID: profileID,
                            onClose: { [weak self] in self?.windows.close(id: windowID) })
        }
    }

    func viewLog(_ profileID: String) {
        windows.show(id: "log-\(profileID)", title: "Recent Log",
                     size: NSSize(width: 560, height: 360)) { [self] in
            LogView(model: self, profileID: profileID)
        }
    }

    var loginItemEnabled: Bool { loginItem.isInstalled }
    func toggleLoginItem() {
        if loginItem.isInstalled { try? loginItem.remove() } else { try? loginItem.install() }
        objectWillChange.send()
    }

    func installRuntime() {
        let argv = locator.installCommandArgv()
        installLog = "Installing…\n"
        // Retain the process; otherwise it is deallocated before it runs.
        installProcess = NodeProcess(
            argv: argv,
            environment: childEnv,
            onLine: { [weak self] line in
                Task { @MainActor in self?.installLog += line + "\n" }
            },
            onExit: { [weak self] _ in
                Task { @MainActor in
                    self?.refreshRuntime()
                    self?.installProcess = nil
                }
            })
        installProcess?.start()
    }
}

@MainActor
private final class ProfileNotificationController {
    private let notifier: ProfileNotifying
    private let suppression = ProfileLifecycleEventSuppression()

    init(notifier: ProfileNotifying) {
        self.notifier = notifier
    }

    func suppressNextStart(profileID: String) {
        suppression.suppressNextStart(profileID: profileID)
    }

    func suppressNextRestart(profileID: String) {
        suppression.suppressNextRestart(profileID: profileID)
    }

    func notify(_ event: ProfileLifecycleEvent) {
        if suppression.shouldSuppress(event) { return }
        switch event {
        case let .started(_, label):
            notifier.notify(title: "Profile started", body: label)
        case let .stopped(_, label):
            notifier.notify(title: "Profile stopped", body: label)
        case let .error(_, label, _):
            notifier.notify(title: "Profile error", body: label)
        }
    }
}
