import Foundation
import SwiftUI
import Combine
import NewbroExecutorCore

@MainActor
final class AppModel: ObservableObject {
    @Published var profiles: [Profile] = []
    @Published var runtimeAvailable: Bool = true
    @Published var isInstallingRuntime: Bool = false
    @Published var runtimeInstallError: String?
    @Published var installLog: String = ""
    @Published var executorSettingsError: String?
    @Published var executorSettingsBusy: Bool = false
    @Published var executorSettingsCanUpdateCLI: Bool = false
    @Published var profileDiagnoses: [String: ProfileStartDiagnosis] = [:]
    @Published var cachedCLIVersion: String?
    @Published var selectedSettingsPane: SettingsPane = .updates

    // Per-family probe state
    @Published var probeByFamily: [String: ExecutorProbe] = [:]
    @Published var statusByFamily: [String: CommandStatus] = [:]
    @Published var setupLogByFamily: [String: String] = [:]
    @Published var setupBusyByFamily: [String: Bool] = [:]

    /// The executor family currently shown in Settings (drives probeScope at launch/refresh).
    var viewedSettingsFamily: String?

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
    // Per-family probe request IDs to cancel stale results
    private var probeRequestIDByFamily: [String: Int] = [:]
    private var executorProbeInFlight: Bool = false
    private var setupRequestIDByFamily: [String: Int] = [:]
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
        // Forward supervisor status changes so SwiftUI re-renders the menu/icon.
        supervisor.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)
        // Start auto-activate profiles at launch (login-item or manual).
        autostart()
        refreshExecutorProbeAndStoredDiagnoses()
    }

    func refreshRuntime() {
        runtimeAvailable = locator.isRuntimeAvailable
        refreshCodexStatus()
        refreshCachedCLIVersion()
    }

    @discardableResult
    func refreshCodexStatus() -> CommandStatus {
        let status = locator.codexRuntimeStatus()
        statusByFamily["codex"] = status
        return status
    }

    func autostart() {
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

    /// Cached installed CLI version for update/status UI. Background diagnosis
    /// refreshes own the actual `newbro --version` process execution.
    func installedCLIVersion() -> String? {
        cachedCLIVersion
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
        guard profileIsComplete(profile) else {
            blockStartRequest(profile)
            return false
        }
        pendingRestartProfileIDs.remove(profile.id)
        pendingStartProfileIDs.insert(profile.id)
        if suppressStartNotification {
            pendingSilentStartProfileIDs.insert(profile.id)
        } else {
            pendingSilentStartProfileIDs.remove(profile.id)
        }
        pendingSilentRestartProfileIDs.remove(profile.id)
        profileDiagnoses[profile.id] = checkingLocalSetupDiagnosis()
        objectWillChange.send()
        refreshExecutorProbeAndStoredDiagnoses()
        return true
    }

    func diagnosis(for profile: Profile) -> ProfileStartDiagnosis? {
        profileDiagnoses[profile.id]
    }

    @discardableResult
    private func diagnoseStart(for profile: Profile,
                               runtime: DiagnosisRuntimeContext) -> ProfileStartDiagnosis {
        let family = profile.enabledExecutors.first ?? "codex"
        let probe = runtime.newbroPath == nil ? nil : probeByFamily[family]
        let probeError = runtime.newbroPath == nil ? nil : executorSettingsError
        let diagnosis = diagnoseProfileStart(
            profile,
            newbroPath: runtime.newbroPath,
            cliVersion: runtime.newbroPath == nil ? nil : runtime.cliVersion,
            probe: probe,
            probeError: probeError
        )
        profileDiagnoses[profile.id] = diagnosis
        return diagnosis
    }

    private func checkingLocalSetupDiagnosis() -> ProfileStartDiagnosis {
        ProfileStartDiagnosis(
            status: .checking,
            reason: .ready,
            title: "Checking local setup",
            primaryAction: .none
        )
    }

    private func blockStartRequest(_ profile: Profile) {
        let diagnosis = diagnoseProfileStart(
            profile,
            newbroPath: "newbro",
            cliVersion: nil,
            probe: nil,
            probeError: nil
        )
        pendingStartProfileIDs.remove(profile.id)
        pendingRestartProfileIDs.remove(profile.id)
        pendingSilentStartProfileIDs.remove(profile.id)
        pendingSilentRestartProfileIDs.remove(profile.id)
        profileDiagnoses[profile.id] = diagnosis
        objectWillChange.send()
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

    private func refreshStoredDiagnosis(for profile: Profile,
                                        runtime: DiagnosisRuntimeContext) {
        let family = profile.enabledExecutors.first ?? "codex"
        let probe = runtime.newbroPath == nil ? nil : probeByFamily[family]
        let probeError = runtime.newbroPath == nil ? nil : executorSettingsError
        let diagnosis = diagnoseProfileStart(
            profile,
            newbroPath: runtime.newbroPath,
            cliVersion: runtime.newbroPath == nil ? nil : runtime.cliVersion,
            probe: probe,
            probeError: probeError
        )
        switch diagnosis.status {
        case .ready:
            profileDiagnoses.removeValue(forKey: profile.id)
        case .blocked, .checking:
            profileDiagnoses[profile.id] = diagnosis
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

    // MARK: - Per-family scoped probe

    /// Probe a single executor family and store results into the per-family maps.
    /// Modelled on the old refreshExecutorProbe flow: same threading, same request-id
    /// guarding, same error handling, but scoped to one family.
    /// On completion also re-derives stored per-profile diagnoses and drains pending starts
    /// (mirroring the post-steps the full refreshExecutorProbeAndStoredDiagnoses performs).
    func refreshProbe(for family: String) {
        guard probeableExecutorFamilies.contains(family) else { return }
        probeRequestIDByFamily[family] = (probeRequestIDByFamily[family] ?? 0) + 1
        let requestID = probeRequestIDByFamily[family]!
        guard let newbro = locator.resolveNewbro() else {
            probeByFamily.removeValue(forKey: family)
            executorSettingsError = "newbro CLI not found"
            executorSettingsCanUpdateCLI = false
            executorSettingsBusy = false
            executorProbeInFlight = false
            let runtime = DiagnosisRuntimeContext(newbroPath: nil, cliVersion: nil)
            refreshStoredProfileDiagnoses(runtime: runtime)
            continuePendingStarts(runtime: runtime)
            return
        }
        executorSettingsBusy = true
        executorProbeInFlight = true
        let client = ExecutorSettingsClient(newbroPath: newbro)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Result { try client.probe(executor: family) }
            DispatchQueue.main.async {
                guard let self else { return }
                guard requestID == self.probeRequestIDByFamily[family] else { return }
                // Build the runtime context using the resolved path and cached CLI version.
                let runtime = DiagnosisRuntimeContext(
                    newbroPath: newbro,
                    cliVersion: self.cachedCLIVersion
                )
                self.applyProbeResult(result, for: family)
                self.refreshStoredProfileDiagnoses(runtime: runtime)
                self.continuePendingStarts(runtime: runtime)
            }
        }
    }

    private func applyProbeResult(_ result: Result<ExecutorProbe, Error>, for family: String) {
        executorSettingsBusy = false
        executorProbeInFlight = false
        switch result {
        case .success(let probe):
            probeByFamily[family] = probe
            executorSettingsError = nil
            executorSettingsCanUpdateCLI = false
        case .failure(let error):
            probeByFamily.removeValue(forKey: family)
            executorSettingsError = error.localizedDescription
            executorSettingsCanUpdateCLI = isRuntimeTooOld(error)
        }
    }

    private func refreshExecutorProbe(resolvedNewbro newbro: String?,
                                      pendingDiagnosisRuntime: DiagnosisRuntimeContext? = nil,
                                      after completion: (() -> Void)? = nil) {
        // Bump all family probe request IDs to cancel any stale in-flight per-family probes
        for family in probeableExecutorFamilies {
            probeRequestIDByFamily[family] = (probeRequestIDByFamily[family] ?? 0) + 1
        }
        let requestIDs = probeRequestIDByFamily
        guard let newbro else {
            for family in probeableExecutorFamilies {
                probeByFamily.removeValue(forKey: family)
            }
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
        let scope = probeScope(profiles: profiles, viewedFamily: viewedSettingsFamily)
        let client = ExecutorSettingsClient(newbroPath: newbro)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            // Probe only the families in scope (codex by default)
            var results: [String: Result<ExecutorProbe, Error>] = [:]
            for family in scope {
                results[family] = Result { try client.probe(executor: family) }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                // Apply each result, guarded by request ID
                var anyError: Error?
                var anyOld = false
                for (family, result) in results {
                    guard requestIDs[family] == self.probeRequestIDByFamily[family] else { continue }
                    switch result {
                    case .success(let probe):
                        self.probeByFamily[family] = probe
                    case .failure(let error):
                        self.probeByFamily.removeValue(forKey: family)
                        if self.isRuntimeTooOld(error) { anyOld = true }
                        anyError = error
                    }
                }
                self.executorSettingsBusy = false
                self.executorProbeInFlight = false
                if let error = anyError {
                    self.executorSettingsError = error.localizedDescription
                    self.executorSettingsCanUpdateCLI = anyOld
                } else {
                    self.executorSettingsError = nil
                    self.executorSettingsCanUpdateCLI = false
                }
                self.continuePendingStarts(runtime: pendingDiagnosisRuntime)
                completion?()
            }
        }
    }

    func refreshExecutorProbeAndStoredDiagnoses() {
        runtimeDiagnosisRefreshRequestID += 1
        let requestID = runtimeDiagnosisRefreshRequestID
        // Bump all family probe request IDs
        for family in probeableExecutorFamilies {
            probeRequestIDByFamily[family] = (probeRequestIDByFamily[family] ?? 0) + 1
        }
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
                self.statusByFamily["codex"] = codex
                self.refreshExecutorProbe(
                    resolvedNewbro: runtime.newbroPath,
                    pendingDiagnosisRuntime: runtime
                ) { [weak self] in
                    self?.refreshStoredProfileDiagnoses(runtime: runtime)
                }
            }
        }
    }

    private func applyMissingRuntimeDiagnosisState(codexStatus: CommandStatus) {
        runtimeDiagnosisRefreshRequestID += 1
        for family in probeableExecutorFamilies {
            probeRequestIDByFamily[family] = (probeRequestIDByFamily[family] ?? 0) + 1
        }
        cliVersionRequestID += 1
        let runtime = DiagnosisRuntimeContext(newbroPath: nil, cliVersion: nil)
        runtimeAvailable = false
        cachedCLIVersion = nil
        statusByFamily["codex"] = codexStatus
        for family in probeableExecutorFamilies {
            probeByFamily.removeValue(forKey: family)
        }
        executorSettingsError = "newbro CLI not found"
        executorSettingsCanUpdateCLI = false
        executorSettingsBusy = false
        executorProbeInFlight = false
        continuePendingStarts(runtime: runtime)
        refreshStoredProfileDiagnoses(runtime: runtime)
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
        guard let runtime else {
            profileDiagnoses[profile.id] = checkingLocalSetupDiagnosis()
            refreshExecutorProbeAndStoredDiagnoses()
            return
        }
        let diagnosis = diagnoseStart(for: profile, runtime: runtime)
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
        guard let runtime else {
            profileDiagnoses[profile.id] = checkingLocalSetupDiagnosis()
            refreshExecutorProbeAndStoredDiagnoses()
            return
        }
        let diagnosis = diagnoseStart(for: profile, runtime: runtime)
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
        guard setupBusyByFamily["codex"] != true else { return }
        let profileID = profile?.id
        setupRequestIDByFamily["codex"] = (setupRequestIDByFamily["codex"] ?? 0) + 1
        let setupRequestID = setupRequestIDByFamily["codex"]!
        // Bump codex probe request ID to cancel stale results
        probeRequestIDByFamily["codex"] = (probeRequestIDByFamily["codex"] ?? 0) + 1
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
        setupBusyByFamily["codex"] = true
        setupLogByFamily["codex"] = "Preparing Codex setup...\n"
        executorSettingsBusy = true
        let loc = locator
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let newbro = loc.resolveNewbro() else {
                let codex = loc.codexRuntimeStatus()
                DispatchQueue.main.async {
                    guard let self else { return }
                    guard setupRequestID == self.setupRequestIDByFamily["codex"] else { return }
                    self.setupBusyByFamily["codex"] = false
                    self.setupLogByFamily["codex", default: ""] += "newbro CLI not found\n"
                    self.applyMissingRuntimeDiagnosisState(codexStatus: codex)
                }
                return
            }
            let client = ExecutorSettingsClient(newbroPath: newbro)
            let result = Result {
                try client.installCodexStreaming { line in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        guard setupRequestID == self.setupRequestIDByFamily["codex"] else { return }
                        self.appendSetupLog(line, for: "codex")
                    }
                }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                guard setupRequestID == self.setupRequestIDByFamily["codex"] else { return }
                self.probeRequestIDByFamily["codex"] = (self.probeRequestIDByFamily["codex"] ?? 0) + 1
                self.setupBusyByFamily["codex"] = false
                switch result {
                case .success:
                    self.refreshExecutorProbeAndStoredDiagnoses()
                case .failure(let error):
                    self.setupLogByFamily["codex", default: ""] += error.localizedDescription + "\n"
                    let isRuntimeTooOld = self.isRuntimeTooOld(error)
                    self.probeRequestIDByFamily["codex"] = (self.probeRequestIDByFamily["codex"] ?? 0) + 1
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

    func setUpHermes(for profile: Profile?) {
        guard setupBusyByFamily["hermes"] != true else { return }
        let profileID = profile?.id
        setupRequestIDByFamily["hermes"] = (setupRequestIDByFamily["hermes"] ?? 0) + 1
        let setupRequestID = setupRequestIDByFamily["hermes"]!
        // Bump hermes probe request ID to cancel stale results
        probeRequestIDByFamily["hermes"] = (probeRequestIDByFamily["hermes"] ?? 0) + 1
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
        setupBusyByFamily["hermes"] = true
        setupLogByFamily["hermes"] = "Preparing Hermes setup...\n"
        executorSettingsBusy = true
        let loc = locator
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let newbro = loc.resolveNewbro() else {
                let codex = loc.codexRuntimeStatus()
                DispatchQueue.main.async {
                    guard let self else { return }
                    guard setupRequestID == self.setupRequestIDByFamily["hermes"] else { return }
                    self.setupBusyByFamily["hermes"] = false
                    self.setupLogByFamily["hermes", default: ""] += "newbro CLI not found\n"
                    self.applyMissingRuntimeDiagnosisState(codexStatus: codex)
                }
                return
            }
            let client = ExecutorSettingsClient(newbroPath: newbro)
            let result = Result {
                try client.installHermesStreaming { line in
                    DispatchQueue.main.async {
                        guard let self else { return }
                        guard setupRequestID == self.setupRequestIDByFamily["hermes"] else { return }
                        self.appendSetupLog(line, for: "hermes")
                    }
                }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                guard setupRequestID == self.setupRequestIDByFamily["hermes"] else { return }
                self.probeRequestIDByFamily["hermes"] = (self.probeRequestIDByFamily["hermes"] ?? 0) + 1
                self.setupBusyByFamily["hermes"] = false
                switch result {
                case .success:
                    self.refreshProbe(for: "hermes")
                    if let profileID,
                       let profile = self.profiles.first(where: { $0.id == profileID }) {
                        // Re-queue the pending profile to continue start after hermes probe completes
                        if self.isActive(profile) {
                            self.pendingStartProfileIDs.remove(profileID)
                            self.pendingRestartProfileIDs.insert(profileID)
                        } else {
                            self.pendingRestartProfileIDs.remove(profileID)
                            self.pendingStartProfileIDs.insert(profileID)
                        }
                    }
                case .failure(let error):
                    self.setupLogByFamily["hermes", default: ""] += error.localizedDescription + "\n"
                    self.probeRequestIDByFamily["hermes"] = (self.probeRequestIDByFamily["hermes"] ?? 0) + 1
                    self.executorSettingsBusy = false
                    self.executorProbeInFlight = false
                    self.executorSettingsError = error.localizedDescription
                    self.executorSettingsCanUpdateCLI = false
                    // Block any pending hermes profiles after setup failure
                    var ids = self.pendingStartProfileIDs.union(self.pendingRestartProfileIDs)
                    if let profileID { ids.insert(profileID) }
                    let diagnosis = ProfileStartDiagnosis(
                        status: .blocked,
                        reason: .installerFailed,
                        title: "Hermes setup failed",
                        detail: error.localizedDescription,
                        primaryAction: .setUpHermes
                    )
                    for id in ids {
                        self.pendingStartProfileIDs.remove(id)
                        self.pendingRestartProfileIDs.remove(id)
                        self.pendingSilentStartProfileIDs.remove(id)
                        self.pendingSilentRestartProfileIDs.remove(id)
                        self.profileDiagnoses[id] = diagnosis
                    }
                }
            }
        }
    }

    private func appendSetupLog(_ line: String, for family: String) {
        var log = setupLogByFamily[family] ?? ""
        log += line
        if !line.hasSuffix("\n") {
            log += "\n"
        }
        setupLogByFamily[family] = log
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

    func startProfileAfterMaintenanceDiagnosis(profileID id: String) {
        guard let profile = profiles.first(where: { $0.id == id }) else { return }
        _ = requestStart(profile)
    }

    func useCodexCandidate(_ candidate: ExecutorCandidateProbe) {
        guard candidate.ok else { return }
        let candidatePath = candidate.path
        let activeIDs = self.activeProfileIDs()
        executorSettingsBusy = true
        let loc = locator
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let newbro = loc.resolveNewbro() else {
                let codex = loc.codexRuntimeStatus()
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.applyMissingRuntimeDiagnosisState(codexStatus: codex)
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
        // Stop every node off the main thread so the menu-bar UI never freezes,
        // then terminate. A deadline guarantees we exit even if a stop lags.
        DispatchQueue.global().async { [supervisor] in
            supervisor.stopAll()
            DispatchQueue.main.async { NSApplication.shared.terminate(nil) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            NSApplication.shared.terminate(nil)
        }
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
        if isActive(profile) {
            return requestRestartAfterDiagnosis(profile, suppressRestartNotification: true)
        }
        return requestStart(profile, suppressStartNotification: true)
    }

    @discardableResult
    private func requestRestartAfterDiagnosis(_ profile: Profile,
                                              suppressRestartNotification: Bool = false) -> Bool {
        guard profileIsComplete(profile) else {
            blockStartRequest(profile)
            return false
        }
        pendingStartProfileIDs.remove(profile.id)
        pendingRestartProfileIDs.insert(profile.id)
        pendingSilentStartProfileIDs.remove(profile.id)
        if suppressRestartNotification {
            pendingSilentRestartProfileIDs.insert(profile.id)
        } else {
            pendingSilentRestartProfileIDs.remove(profile.id)
        }
        profileDiagnoses[profile.id] = checkingLocalSetupDiagnosis()
        objectWillChange.send()
        refreshExecutorProbeAndStoredDiagnoses()
        return true
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
        return profileCanStart(profile, codexRuntimeAvailable: { statusByFamily["codex"]?.isAvailable ?? false })
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
