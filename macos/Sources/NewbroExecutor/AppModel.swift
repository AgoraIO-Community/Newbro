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
    @Published var isInstallingRuntime: Bool = false
    @Published var runtimeInstallError: String?
    @Published var installLog: String = ""
    @Published var executorProbe: ExecutorProbe?
    @Published var executorSettingsError: String?
    @Published var executorSettingsBusy: Bool = false
    @Published var executorSettingsCanUpdateCLI: Bool = false
    @Published var profileDiagnoses: [String: ProfileStartDiagnosis] = [:]
    @Published var cachedCLIVersion: String?
    @Published var codexSetupLog: String = ""
    @Published var codexSetupBusy: Bool = false
    @Published var selectedSettingsPane: SettingsPane = .updates

    private let supervisor: ProfileSupervisor
    private let notifier: AppNotifying
    private let notificationController: ProfileNotificationController
    private let eventRelay: ProfileLifecycleEventRelay
    private let store = ProfileStore()
    private let locator = RuntimeLocator()
    private let loginItem: LoginItem
    private var cancellables: Set<AnyCancellable> = []
    private var installProcess: NodeProcess?
    private var updateInstallProcess: NodeProcess?
    private var pendingStartProfileIDs: Set<String> = []
    private var pendingRestartProfileIDs: Set<String> = []
    private var pendingSilentStartProfileIDs: Set<String> = []
    private var pendingSilentRestartProfileIDs: Set<String> = []
    private var executorProbeRequestID: Int = 0
    private var executorProbeInFlight: Bool = false
    private var codexSetupRequestID: Int = 0
    private var cliVersionRequestID: Int = 0
    private var runtimeDiagnosisRefreshRequestID: Int = 0
    private let windows = WindowManager()
    // Blocking node lifecycle calls (stop/restart busy-wait up to 5s) run here
    // so they never freeze the main actor / menu.
    private let controlQueue = DispatchQueue(label: "newbro.ui.control")

    private struct DiagnosisRuntimeContext: Sendable {
        let newbroPath: String?
        let cliVersion: String?
    }

    /// Login-shell PATH so node subprocesses (and the `node`-based `codex`
    /// they exec) resolve under the app's otherwise-minimal launchd env.
    private let childEnv = RuntimeLocator.childEnvironment()

    init(notifier: AppNotifying? = nil) {
        let notifier = notifier ?? MacAppNotifier()
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
        refreshCachedCLIVersion()
        // Forward supervisor status changes so SwiftUI re-renders the menu/icon.
        supervisor.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)
        // Start auto-activate profiles at launch (login-item or manual).
        autostart()
        refreshExecutorProbe()
    }

    func refreshRuntime() {
        runtimeAvailable = locator.isRuntimeAvailable
        refreshCodexStatus()
        refreshCachedCLIVersion()
    }

    @discardableResult
    func refreshCodexStatus() -> CommandStatus {
        refreshCommandStatus(&codexStatus) {
            locator.codexRuntimeStatus()
        }
    }

    func autostart() {
        refreshRuntime()
        for profile in profiles where profile.autoActivate {
            _ = requestStart(profile, suppressStartNotification: true)
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
        guard let profile = profiles.first(where: { $0.id == id }) else { return }
        start(profile)
    }

    func stop(profileID id: String) {
        controlQueue.async { [supervisor] in supervisor.stop(id) }
    }

    /// The installed CLI version, read by running `newbro --version` (e.g. "0.1.2").
    func installedCLIVersion() -> String? {
        guard let newbro = locator.resolveNewbro() else { return nil }
        return Self.readInstalledCLIVersion(newbroPath: newbro)
    }

    private func refreshCachedCLIVersion() {
        cliVersionRequestID += 1
        let requestID = cliVersionRequestID
        guard let newbro = locator.resolveNewbro() else {
            cachedCLIVersion = nil
            return
        }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let version = Self.readInstalledCLIVersion(newbroPath: newbro)
            DispatchQueue.main.async {
                guard let self, requestID == self.cliVersionRequestID else { return }
                self.cachedCLIVersion = version
            }
        }
    }

    nonisolated private static func readInstalledCLIVersion(newbroPath: String) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: newbroPath)
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
        _ = requestStart(profile)
    }

    @discardableResult
    private func requestStart(_ profile: Profile,
                              suppressStartNotification: Bool = false) -> Bool {
        refreshRuntime()
        let diagnosis = diagnoseStart(for: profile)
        switch diagnosis.status {
        case .ready:
            pendingStartProfileIDs.remove(profile.id)
            pendingRestartProfileIDs.remove(profile.id)
            pendingSilentStartProfileIDs.remove(profile.id)
            pendingSilentRestartProfileIDs.remove(profile.id)
            profileDiagnoses.removeValue(forKey: profile.id)
            if suppressStartNotification {
                notificationController.suppressNextStart(profileID: profile.id)
            }
            perform(.start(profile))
            return true
        case .checking:
            pendingRestartProfileIDs.remove(profile.id)
            pendingStartProfileIDs.insert(profile.id)
            if suppressStartNotification {
                pendingSilentStartProfileIDs.insert(profile.id)
            } else {
                pendingSilentStartProfileIDs.remove(profile.id)
            }
            pendingSilentRestartProfileIDs.remove(profile.id)
            objectWillChange.send()
            return true
        case .blocked:
            pendingStartProfileIDs.remove(profile.id)
            pendingRestartProfileIDs.remove(profile.id)
            pendingSilentStartProfileIDs.remove(profile.id)
            pendingSilentRestartProfileIDs.remove(profile.id)
            objectWillChange.send()
            return false
        }
    }

    func diagnosis(for profile: Profile) -> ProfileStartDiagnosis? {
        profileDiagnoses[profile.id]
    }

    @discardableResult
    func diagnoseStart(for profile: Profile) -> ProfileStartDiagnosis {
        let newbro = locator.resolveNewbro()
        if let newbro,
           profileRequiresCodex(profile),
           profileIsComplete(profile),
           executorProbeInFlight || codexSetupBusy {
            let diagnosis = diagnoseProfileStart(
                profile,
                newbroPath: newbro,
                cliVersion: nil,
                probe: nil,
                probeError: nil
            )
            profileDiagnoses[profile.id] = diagnosis
            return diagnosis
        }
        if executorProbe == nil && executorSettingsError == nil {
            refreshExecutorProbe()
        }
        let diagnosis = diagnoseProfileStart(
            profile,
            newbroPath: newbro,
            cliVersion: newbro == nil ? nil : installedCLIVersion(),
            probe: newbro == nil ? nil : executorProbe,
            probeError: newbro == nil ? nil : executorSettingsError
        )
        profileDiagnoses[profile.id] = diagnosis
        return diagnosis
    }

    @discardableResult
    private func diagnoseStart(for profile: Profile,
                               runtime: DiagnosisRuntimeContext) -> ProfileStartDiagnosis {
        let diagnosis = diagnoseProfileStart(
            profile,
            newbroPath: runtime.newbroPath,
            cliVersion: runtime.newbroPath == nil ? nil : runtime.cliVersion,
            probe: runtime.newbroPath == nil ? nil : executorProbe,
            probeError: runtime.newbroPath == nil ? nil : executorSettingsError
        )
        profileDiagnoses[profile.id] = diagnosis
        return diagnosis
    }

    func rerunDiagnosis(for profile: Profile) {
        profileDiagnoses[profile.id] = ProfileStartDiagnosis(
            status: .checking,
            reason: .ready,
            title: "Checking Codex setup",
            primaryAction: .none
        )
        refreshExecutorProbeAndStoredDiagnoses()
    }

    private func refreshStoredDiagnosis(for profile: Profile) {
        let newbro = locator.resolveNewbro()
        refreshStoredDiagnosis(
            for: profile,
            runtime: DiagnosisRuntimeContext(
                newbroPath: newbro,
                cliVersion: newbro == nil ? nil : cachedCLIVersion
            )
        )
    }

    private func refreshStoredDiagnosis(for profile: Profile,
                                        runtime: DiagnosisRuntimeContext) {
        let diagnosis = diagnoseProfileStart(
            profile,
            newbroPath: runtime.newbroPath,
            cliVersion: runtime.newbroPath == nil ? nil : runtime.cliVersion,
            probe: runtime.newbroPath == nil ? nil : executorProbe,
            probeError: runtime.newbroPath == nil ? nil : executorSettingsError
        )
        switch diagnosis.status {
        case .ready:
            profileDiagnoses.removeValue(forKey: profile.id)
        case .blocked, .checking:
            profileDiagnoses[profile.id] = diagnosis
        }
    }

    private func refreshStoredProfileDiagnoses() {
        let diagnosedIDs = Array(profileDiagnoses.keys)
        guard !diagnosedIDs.isEmpty else { return }

        for profileID in diagnosedIDs {
            guard let profile = profiles.first(where: { $0.id == profileID }) else {
                profileDiagnoses.removeValue(forKey: profileID)
                continue
            }
            refreshStoredDiagnosis(for: profile)
        }
    }

    private func refreshStoredProfileDiagnoses(runtime: DiagnosisRuntimeContext) {
        let diagnosedIDs = Array(profileDiagnoses.keys)
        guard !diagnosedIDs.isEmpty else { return }

        for profileID in diagnosedIDs {
            guard let profile = profiles.first(where: { $0.id == profileID }) else {
                profileDiagnoses.removeValue(forKey: profileID)
                continue
            }
            refreshStoredDiagnosis(for: profile, runtime: runtime)
        }
    }

    func stop(_ profile: Profile) {
        controlQueue.async { [supervisor] in supervisor.stop(profile.id) }
    }
    func restart(_ profile: Profile) {
        _ = requestRestartAfterDiagnosis(profile)
    }

    func refreshExecutorProbe(after completion: (() -> Void)? = nil) {
        refreshCachedCLIVersion()
        refreshExecutorProbe(resolvedNewbro: locator.resolveNewbro(), after: completion)
    }

    private func refreshExecutorProbe(resolvedNewbro newbro: String?,
                                      pendingDiagnosisRuntime: DiagnosisRuntimeContext? = nil,
                                      after completion: (() -> Void)? = nil) {
        executorProbeRequestID += 1
        let requestID = executorProbeRequestID
        guard let newbro else {
            executorProbe = nil
            executorSettingsError = "newbro CLI not found"
            executorSettingsCanUpdateCLI = false
            executorSettingsBusy = false
            executorProbeInFlight = false
            continuePendingStarts(runtime: pendingDiagnosisRuntime)
            completion?()
            return
        }
        executorSettingsBusy = true
        executorProbeInFlight = true
        let client = ExecutorSettingsClient(newbroPath: newbro)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Result { try client.probe() }
            DispatchQueue.main.async {
                guard let self else { return }
                guard requestID == self.executorProbeRequestID else { return }
                self.applyExecutorProbeResult(result)
                self.continuePendingStarts(runtime: pendingDiagnosisRuntime)
                completion?()
            }
        }
    }

    func refreshExecutorProbeAndStoredDiagnoses() {
        runtimeDiagnosisRefreshRequestID += 1
        let requestID = runtimeDiagnosisRefreshRequestID
        executorProbeRequestID += 1
        cliVersionRequestID += 1
        let versionRequestID = cliVersionRequestID
        executorSettingsBusy = true
        executorProbeInFlight = true
        let loc = locator
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let newbro = loc.resolveNewbro()
            let cliVersion = newbro.flatMap { Self.readInstalledCLIVersion(newbroPath: $0) }
            let codex = loc.codexRuntimeStatus()
            DispatchQueue.main.async {
                guard let self else { return }
                guard requestID == self.runtimeDiagnosisRefreshRequestID else { return }
                let runtime = DiagnosisRuntimeContext(newbroPath: newbro, cliVersion: cliVersion)
                self.runtimeAvailable = newbro != nil
                if versionRequestID == self.cliVersionRequestID {
                    self.cachedCLIVersion = cliVersion
                }
                self.codexStatus = codex
                self.refreshExecutorProbe(
                    resolvedNewbro: runtime.newbroPath,
                    pendingDiagnosisRuntime: runtime
                ) { [weak self] in
                    self?.refreshStoredProfileDiagnoses(runtime: runtime)
                }
            }
        }
    }

    private func applyExecutorProbeResult(_ result: Result<ExecutorProbe, Error>) {
        executorSettingsBusy = false
        executorProbeInFlight = false
        switch result {
        case .success(let probe):
            executorProbe = probe
            executorSettingsError = nil
            executorSettingsCanUpdateCLI = false
        case .failure(let error):
            executorProbe = nil
            executorSettingsError = error.localizedDescription
            executorSettingsCanUpdateCLI = isRuntimeTooOld(error)
        }
    }

    private func continuePendingStarts(runtime: DiagnosisRuntimeContext? = nil) {
        guard !pendingStartProfileIDs.isEmpty || !pendingRestartProfileIDs.isEmpty else { return }
        for profileID in Array(pendingStartProfileIDs) {
            guard let profile = profiles.first(where: { $0.id == profileID }) else {
                pendingStartProfileIDs.remove(profileID)
                pendingSilentStartProfileIDs.remove(profileID)
                profileDiagnoses.removeValue(forKey: profileID)
                continue
            }
            continueStartIfReady(profile, runtime: runtime)
        }
        for profileID in Array(pendingRestartProfileIDs) {
            guard let profile = profiles.first(where: { $0.id == profileID }) else {
                pendingRestartProfileIDs.remove(profileID)
                pendingSilentRestartProfileIDs.remove(profileID)
                profileDiagnoses.removeValue(forKey: profileID)
                continue
            }
            continueRestartIfReady(profile, runtime: runtime)
        }
    }

    private func continueStartIfReady(_ profile: Profile,
                                      runtime: DiagnosisRuntimeContext? = nil) {
        let diagnosis = runtime.map { diagnoseStart(for: profile, runtime: $0) }
            ?? diagnoseStart(for: profile)
        switch diagnosis.status {
        case .ready:
            pendingStartProfileIDs.remove(profile.id)
            if pendingSilentStartProfileIDs.remove(profile.id) != nil {
                notificationController.suppressNextStart(profileID: profile.id)
            }
            profileDiagnoses.removeValue(forKey: profile.id)
            perform(.start(profile))
        case .blocked:
            pendingStartProfileIDs.remove(profile.id)
            pendingSilentStartProfileIDs.remove(profile.id)
        case .checking:
            pendingStartProfileIDs.insert(profile.id)
        }
    }

    private func continueRestartIfReady(_ profile: Profile,
                                        runtime: DiagnosisRuntimeContext? = nil) {
        let diagnosis = runtime.map { diagnoseStart(for: profile, runtime: $0) }
            ?? diagnoseStart(for: profile)
        switch diagnosis.status {
        case .ready:
            pendingRestartProfileIDs.remove(profile.id)
            if pendingSilentRestartProfileIDs.remove(profile.id) != nil {
                notificationController.suppressNextRestart(profileID: profile.id)
            }
            profileDiagnoses.removeValue(forKey: profile.id)
            perform(.restart(profile))
        case .blocked:
            pendingRestartProfileIDs.remove(profile.id)
            pendingSilentRestartProfileIDs.remove(profile.id)
        case .checking:
            pendingRestartProfileIDs.insert(profile.id)
        }
    }

    private func isRuntimeTooOld(_ error: Error) -> Bool {
        if case ExecutorSettingsClientError.runtimeTooOld = error {
            return true
        }
        return false
    }

    private func profileRequiresCodex(_ profile: Profile) -> Bool {
        profile.enabledExecutors.contains("codex")
    }

    func setUpCodex(for profile: Profile?) {
        guard !codexSetupBusy, let newbro = locator.resolveNewbro() else { return }
        let profileID = profile?.id
        codexSetupRequestID += 1
        let setupRequestID = codexSetupRequestID
        executorProbeRequestID += 1
        if let profileID {
            if profile.map(isActive) == true {
                pendingStartProfileIDs.remove(profileID)
                pendingRestartProfileIDs.insert(profileID)
            } else {
                pendingRestartProfileIDs.remove(profileID)
                pendingStartProfileIDs.insert(profileID)
            }
        }
        executorProbeInFlight = true
        codexSetupBusy = true
        codexSetupLog = "Preparing Codex setup...\n"
        executorSettingsBusy = true
        let client = ExecutorSettingsClient(newbroPath: newbro)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Result { try client.installCodex() }
            DispatchQueue.main.async {
                guard let self else { return }
                guard setupRequestID == self.codexSetupRequestID else { return }
                self.executorProbeRequestID += 1
                self.codexSetupBusy = false
                switch result {
                case .success(let output):
                    self.codexSetupLog += output
                    if !output.hasSuffix("\n") {
                        self.codexSetupLog += "\n"
                    }
                    self.refreshExecutorProbeAndStoredDiagnoses()
                case .failure(let error):
                    self.codexSetupLog += error.localizedDescription + "\n"
                    let isRuntimeTooOld = self.isRuntimeTooOld(error)
                    self.executorProbeRequestID += 1
                    self.executorSettingsBusy = false
                    self.executorProbeInFlight = false
                    self.executorSettingsError = error.localizedDescription
                    self.executorSettingsCanUpdateCLI = isRuntimeTooOld
                    self.blockPendingProfilesAfterCodexSetupFailure(
                        error: error,
                        isRuntimeTooOld: isRuntimeTooOld,
                        profileID: profileID
                    )
                }
            }
        }
    }

    private func blockPendingProfilesAfterCodexSetupFailure(error: Error,
                                                            isRuntimeTooOld: Bool,
                                                            profileID: String?) {
        var ids = pendingStartProfileIDs.union(pendingRestartProfileIDs)
        if let profileID { ids.insert(profileID) }
        let diagnosis = ProfileStartDiagnosis(
            status: .blocked,
            reason: isRuntimeTooOld ? .newbroTooOldForProbe : .installerFailed,
            title: isRuntimeTooOld ? "Codex setup requires a newer Newbro CLI" : "Codex setup failed",
            detail: error.localizedDescription,
            primaryAction: isRuntimeTooOld ? .updateNewbroCLI : .setUpCodex
        )
        for id in ids {
            pendingStartProfileIDs.remove(id)
            pendingRestartProfileIDs.remove(id)
            pendingSilentStartProfileIDs.remove(id)
            pendingSilentRestartProfileIDs.remove(id)
            profileDiagnoses[id] = diagnosis
        }
    }

    func updateCLIFromExecutorSettings() {
        guard !executorSettingsBusy else { return }
        let activeIDs = self.activeProfileIDs()
        executorSettingsBusy = true
        controlQueue.async { [supervisor] in
            for id in activeIDs { supervisor.stop(id) }
            Task { @MainActor [weak self] in
                self?.runCLIUpdateInstallerAfterStops(activeIDs: activeIDs)
            }
        }
    }

    private func runCLIUpdateInstallerAfterStops(activeIDs: [String]) {
        runInstaller { [weak self] code in
            guard let self else { return }
            if code == 0 {
                for id in activeIDs { self.pendingStartProfileIDs.insert(id) }
                self.refreshExecutorProbeAndStoredDiagnoses()
            } else {
                self.restoreProfilesAfterMaintenance(activeIDs: activeIDs)
                self.executorSettingsBusy = false
                self.executorSettingsError = "Update failed (exit \(code)). Nodes restarted."
                self.executorSettingsCanUpdateCLI = true
            }
        }
    }

    private func restoreProfilesAfterMaintenance(activeIDs: [String]) {
        for id in activeIDs {
            restoreProfileAfterMaintenance(profileID: id)
        }
    }

    func restoreProfileAfterMaintenance(profileID id: String) {
        guard let profile = profiles.first(where: { $0.id == id }) else { return }
        pendingStartProfileIDs.remove(id)
        pendingRestartProfileIDs.remove(id)
        pendingSilentStartProfileIDs.remove(id)
        pendingSilentRestartProfileIDs.remove(id)
        profileDiagnoses.removeValue(forKey: id)
        controlQueue.async { [supervisor] in supervisor.start(profile) }
    }

    func useCodexCandidate(_ candidate: ExecutorCandidateProbe) {
        guard candidate.ok else { return }
        let candidatePath = candidate.path
        let activeIDs = self.activeProfileIDs()
        executorSettingsBusy = true
        let loc = locator
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let newbro = loc.resolveNewbro() else {
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.executorSettingsBusy = false
                    self.executorSettingsError = "newbro CLI not found"
                    self.executorSettingsCanUpdateCLI = false
                }
                return
            }
            let client = ExecutorSettingsClient(newbroPath: newbro)
            let result = Result { try client.useCodex(path: candidatePath) }
            DispatchQueue.main.async {
                guard let self else { return }
                switch result {
                case .success:
                    self.executorSettingsError = nil
                    self.executorSettingsCanUpdateCLI = false
                    for id in activeIDs {
                        self.pendingStartProfileIDs.remove(id)
                        self.pendingSilentStartProfileIDs.remove(id)
                        self.pendingRestartProfileIDs.insert(id)
                    }
                    self.refreshExecutorProbeAndStoredDiagnoses()
                case .failure(let error):
                    self.executorSettingsBusy = false
                    self.executorSettingsError = error.localizedDescription
                    self.executorSettingsCanUpdateCLI = false
                }
            }
        }
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
    func addFromConnectSettings(_ text: String) throws -> Profile {
        let fields = try parseConnectSettings(text)
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
        refreshRuntime()
        if isActive(profile) {
            return requestRestartAfterDiagnosis(profile, suppressRestartNotification: true)
        }
        return requestStart(profile, suppressStartNotification: true)
    }

    @discardableResult
    private func requestRestartAfterDiagnosis(_ profile: Profile,
                                              suppressRestartNotification: Bool = false) -> Bool {
        refreshRuntime()
        let diagnosis = diagnoseStart(for: profile)
        switch diagnosis.status {
        case .ready:
            pendingStartProfileIDs.remove(profile.id)
            pendingRestartProfileIDs.remove(profile.id)
            pendingSilentStartProfileIDs.remove(profile.id)
            pendingSilentRestartProfileIDs.remove(profile.id)
            profileDiagnoses.removeValue(forKey: profile.id)
            if suppressRestartNotification {
                notificationController.suppressNextRestart(profileID: profile.id)
            }
            perform(.restart(profile))
            return true
        case .checking:
            pendingStartProfileIDs.remove(profile.id)
            pendingRestartProfileIDs.insert(profile.id)
            pendingSilentStartProfileIDs.remove(profile.id)
            if suppressRestartNotification {
                pendingSilentRestartProfileIDs.insert(profile.id)
            } else {
                pendingSilentRestartProfileIDs.remove(profile.id)
            }
            objectWillChange.send()
            return true
        case .blocked:
            pendingStartProfileIDs.remove(profile.id)
            pendingRestartProfileIDs.remove(profile.id)
            pendingSilentStartProfileIDs.remove(profile.id)
            pendingSilentRestartProfileIDs.remove(profile.id)
            objectWillChange.send()
            return false
        }
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
        refreshCodexStatus().isAvailable
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

    func showSettings(updates: UpdateService, initialPane: SettingsPane = .updates) {
        selectedSettingsPane = initialPane
        refreshExecutorProbeAndStoredDiagnoses()
        windows.show(id: "settings", title: "Settings",
                     size: NSSize(width: 760, height: 480)) { [self] in
            NewbroSettingsView(model: self, updates: updates)
        }
    }

    var loginItemEnabled: Bool { loginItem.isInstalled }
    func toggleLoginItem() {
        if loginItem.isInstalled { try? loginItem.remove() } else { try? loginItem.install() }
        objectWillChange.send()
    }

    func installRuntime() {
        guard !isInstallingRuntime else { return }
        let argv = locator.installCommandArgv()
        isInstallingRuntime = true
        runtimeInstallError = nil
        installLog = "Installing…\n"
        // Retain the process; otherwise it is deallocated before it runs.
        installProcess = NodeProcess(
            argv: argv,
            environment: childEnv,
            onLine: { [weak self] line in
                Task { @MainActor in self?.installLog += line + "\n" }
            },
            onExit: { [weak self] code in
                Task { @MainActor in
                    guard let self else { return }
                    self.refreshRuntime()
                    let completion = runtimeInstallCompletion(
                        exitCode: code,
                        runtimeAvailable: self.runtimeAvailable)
                    self.runtimeInstallError = completion.errorRow
                    self.notifier.notify(
                        title: completion.notificationTitle,
                        body: completion.notificationBody)
                    self.isInstallingRuntime = false
                    self.installProcess = nil
                }
            })
        installProcess?.start()
    }

    func notifyUpdateEvent(_ event: UpdateServiceEvent) {
        switch event {
        case .cliUpdateSucceeded:
            refreshExecutorProbeAndStoredDiagnoses()
            notifier.notify(title: "Newbro CLI updated", body: "Executor nodes restarted.")
        case let .cliUpdateFailed(code, _):
            notifier.notify(title: "Newbro CLI update failed", body: "Exit \(code). Executor nodes restarted.")
        }
    }
}

@MainActor
private final class ProfileNotificationController {
    private let notifier: AppNotifying
    private let suppression = ProfileLifecycleEventSuppression()

    init(notifier: AppNotifying) {
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
