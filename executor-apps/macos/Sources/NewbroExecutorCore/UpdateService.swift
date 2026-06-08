import Foundation
import Combine

public enum UpdateServiceEvent: Equatable, Sendable {
    case cliUpdateSucceeded(restartedProfileCount: Int)
    case cliUpdateFailed(exitCode: Int32, restartedProfileCount: Int)
}

/// Drives update checks and the orchestrated CLI update (stop → upgrade →
/// restart). UI-free: all side effects (network, version probe, supervisor
/// start/stop, installer) are injected, so it is fully unit-testable and the
/// app wires the real implementations.
@MainActor
public final class UpdateService: ObservableObject {
    @Published public private(set) var status = UpdateStatus()
    @Published public private(set) var installedCLI: String?
    @Published public private(set) var isUpdating = false
    @Published public private(set) var isChecking = false
    @Published public private(set) var lastError: String?
    public private(set) var releasePageURL: URL?

    // All side-effect closures are @MainActor because they call into the
    // @MainActor AppModel; fetchLatest stays nonisolated/async (network, off main).
    private let fetchLatest: () async -> ReleaseInfo?
    private let installedCLIVersion: @MainActor () -> String?
    private let appVersion: @MainActor () -> String?
    private let activeProfileIDs: @MainActor () -> [String]
    private let stopProfile: @MainActor (String) -> Void
    private let startProfile: @MainActor (String) -> Void
    private let runInstaller: @MainActor (@escaping @MainActor (Int32) -> Void) -> Void
    private let onEvent: @MainActor (UpdateServiceEvent) -> Void

    public init(
        fetchLatest: @escaping () async -> ReleaseInfo?,
        installedCLIVersion: @escaping @MainActor () -> String?,
        appVersion: @escaping @MainActor () -> String?,
        activeProfileIDs: @escaping @MainActor () -> [String],
        stopProfile: @escaping @MainActor (String) -> Void,
        startProfile: @escaping @MainActor (String) -> Void,
        runInstaller: @escaping @MainActor (@escaping @MainActor (Int32) -> Void) -> Void,
        onEvent: @escaping @MainActor (UpdateServiceEvent) -> Void = { _ in }
    ) {
        self.fetchLatest = fetchLatest
        self.installedCLIVersion = installedCLIVersion
        self.appVersion = appVersion
        self.activeProfileIDs = activeProfileIDs
        self.stopProfile = stopProfile
        self.startProfile = startProfile
        self.runInstaller = runInstaller
        self.onEvent = onEvent
    }

    public func check() async {
        isChecking = true
        defer { isChecking = false }
        guard let release = await fetchLatest() else {
            lastError = "Couldn't check for updates."
            return
        }
        lastError = nil
        releasePageURL = release.pageURL
        let cli = installedCLIVersion()
        installedCLI = cli
        status = updateStatus(installedCLI: cli,
                              installedApp: appVersion(),
                              latestTag: release.tag)
    }

    public func updateCLI() {
        guard !isUpdating else { return }
        isUpdating = true
        lastError = nil
        let ids = activeProfileIDs()
        for id in ids { stopProfile(id) }
        runInstaller { [weak self] code in
            guard let self else { return }
            for id in ids { self.startProfile(id) }
            self.isUpdating = false
            if code != 0 {
                self.lastError = "Update failed (exit \(code)). Nodes restarted."
                self.onEvent(.cliUpdateFailed(exitCode: code, restartedProfileCount: ids.count))
            } else {
                self.onEvent(.cliUpdateSucceeded(restartedProfileCount: ids.count))
                Task { await self.check() }
            }
        }
    }
}
