import Foundation
import SwiftUI
import Combine
import NewbroExecutorCore

@MainActor
final class AppModel: ObservableObject {
    @Published var profiles: [Profile] = []
    @Published var runtimeAvailable: Bool = true
    @Published var installLog: String = ""

    private let supervisor: ProfileSupervisor
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

    init() {
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
            })
        self.profiles = store.load()
        self.runtimeAvailable = locator.isRuntimeAvailable
        // Forward supervisor status changes so SwiftUI re-renders the menu/icon.
        supervisor.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)
        // Start auto-activate profiles at launch (login-item or manual).
        autostart()
    }

    func refreshRuntime() { runtimeAvailable = locator.isRuntimeAvailable }

    func autostart() {
        guard runtimeAvailable else { return }
        for profile in profiles where profile.autoActivate && isComplete(profile) {
            supervisor.start(profile)
        }
    }

    func isComplete(_ profile: Profile) -> Bool {
        !profile.baseURL.isEmpty && !profile.nodeID.isEmpty
            && !profile.token.isEmpty && !profile.enabledExecutors.isEmpty
    }

    func status(of profile: Profile) -> NodeStatus { supervisor.status(of: profile.id) }
    func aggregate() -> NodeStatus { supervisor.aggregateStatus() }
    func isActive(_ profile: Profile) -> Bool { supervisor.activeIDs().contains(profile.id) }
    func conflicts() -> Set<String> { conflictingProfileIDs(profiles) }

    // MARK: - Update support

    /// IDs of profiles currently being supervised (active).
    func activeProfileIDs() -> [String] { Array(supervisor.activeIDs()) }

    func start(profileID id: String) {
        guard runtimeAvailable, let profile = profiles.first(where: { $0.id == id }) else { return }
        supervisor.start(profile)
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
        guard runtimeAvailable, canStart(profile) else { return }
        supervisor.start(profile)
    }
    func stop(_ profile: Profile) {
        controlQueue.async { [supervisor] in supervisor.stop(profile.id) }
    }
    func restart(_ profile: Profile) {
        guard runtimeAvailable, canStart(profile) else { return }
        controlQueue.async { [supervisor] in supervisor.restart(profile) }
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
        let profile: Profile
        if let index = firstMatchingProfileIndex(in: profiles, baseURL: fields.baseURL, nodeID: fields.nodeID) {
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
        autoStartPastedProfile(profile)
        return profile
    }

    private func autoStartPastedProfile(_ profile: Profile) {
        guard runtimeAvailable, isComplete(profile), canStart(profile) else { return }
        if isActive(profile) {
            restart(profile)
        } else {
            start(profile)
        }
    }

    func canStart(_ profile: Profile) -> Bool {
        if profile.enabledExecutors.contains("codex") {
            return locator.codexRuntimeStatus().isAvailable
        }
        return true
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

    func addProfile() {
        let new = emptyProfile()
        upsert(new)
        editProfile(new.id)
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

    func emptyProfile() -> Profile {
        Profile(id: "profile-\(UUID().uuidString.prefix(8))", label: "New profile",
                baseURL: "", nodeID: "", token: "")
    }
}
