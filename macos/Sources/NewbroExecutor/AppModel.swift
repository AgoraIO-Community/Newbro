import Foundation
import SwiftUI
import Combine
import NewbroExecutorCore

@MainActor
final class AppModel: ObservableObject {
    @Published var profiles: [Profile] = []
    @Published var runtimeAvailable: Bool = true
    @Published var installLog: String = ""

    let supervisor: ProfileSupervisor
    private let store = ProfileStore()
    private let locator = RuntimeLocator()
    private let loginItem: LoginItem
    private var cancellables: Set<AnyCancellable> = []

    init() {
        let locatorRef = RuntimeLocator()
        self.loginItem = LoginItem(appPath: Bundle.main.bundlePath)
        self.supervisor = ProfileSupervisor(
            processFactory: .init(make: { argv, onLine, onExit in
                NodeProcess(argv: argv, onLine: onLine, onExit: onExit)
            }),
            argvBuilder: { profile in
                locatorRef.nodeArgv(for: profile) ?? []
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

    func start(_ profile: Profile) {
        guard runtimeAvailable else { return }
        supervisor.start(profile)
    }
    func stop(_ profile: Profile) { supervisor.stop(profile.id) }
    func restart(_ profile: Profile) { supervisor.restart(profile) }

    func toggleAutoActivate(_ profile: Profile) {
        guard let index = profiles.firstIndex(where: { $0.id == profile.id }) else { return }
        profiles[index].autoActivate.toggle()
        try? store.save(profiles)
    }

    func delete(_ profile: Profile) {
        supervisor.stop(profile.id)
        profiles.removeAll { $0.id == profile.id }
        try? store.save(profiles)
    }

    func upsert(_ profile: Profile) {
        if let index = profiles.firstIndex(where: { $0.id == profile.id }) {
            profiles[index] = profile
        } else {
            profiles.append(profile)
        }
        try? store.save(profiles)
    }

    func addFromConnectCommand(_ text: String) throws {
        let fields = try parseConnectCommand(text)
        if let index = profiles.firstIndex(where: {
            $0.nodeID == fields.nodeID && $0.baseURL == fields.baseURL
        }) {
            profiles[index].token = fields.token
            profiles[index].enabledExecutors = fields.enabledExecutors
        } else {
            profiles.append(Profile(
                id: "profile-\(UUID().uuidString.prefix(8))",
                label: fields.baseURL, baseURL: fields.baseURL,
                nodeID: fields.nodeID, token: fields.token,
                enabledExecutors: fields.enabledExecutors))
        }
        try? store.save(profiles)
    }

    func recentLog(_ profile: Profile) -> [String] {
        ProfileLog(path: ProfileLog.defaultPath(profileID: profile.id)).recent()
    }

    var loginItemEnabled: Bool { loginItem.isInstalled }
    func toggleLoginItem() {
        if loginItem.isInstalled { try? loginItem.remove() } else { try? loginItem.install() }
        objectWillChange.send()
    }

    func installRuntime() {
        let argv = locator.installCommandArgv()
        installLog = "Installing…\n"
        let process = NodeProcess(
            argv: argv,
            onLine: { [weak self] line in
                Task { @MainActor in self?.installLog += line + "\n" }
            },
            onExit: { [weak self] _ in
                Task { @MainActor in self?.refreshRuntime() }
            })
        process.start()
    }

    func emptyProfile() -> Profile {
        Profile(id: "profile-\(UUID().uuidString.prefix(8))", label: "New profile",
                baseURL: "", nodeID: "", token: "")
    }
}
