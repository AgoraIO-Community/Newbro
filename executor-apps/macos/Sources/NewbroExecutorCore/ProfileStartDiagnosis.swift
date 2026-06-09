import Foundation

public enum ProfileStartDiagnosisStatus: Equatable, Sendable {
    case ready
    case blocked
    case checking
}

public enum ProfileStartDiagnosisReason: Equatable, Sendable {
    case ready
    case profileIncomplete
    case newbroMissing
    case newbroTooOldForProbe
    case newbroVersionUnknown
    case codexMissing
    case codexConfiguredButBroken
    case codexProbeFailed
    case codexLoginRequired
    case installerFailed
    case hermesMissing
    case hermesSignInRequired
}

public enum ProfileStartDiagnosisAction: Equatable, Sendable {
    case none
    case installNewbroCLI
    case updateNewbroCLI
    case setUpCodex
    case openCodexSettings
    case signInCodex
    case viewLog
    case rerunDiagnosis
    case openProfileSettings
    case setUpHermes
    case signInHermes
}

public struct ProfileStartDiagnosis: Equatable, Sendable {
    public var status: ProfileStartDiagnosisStatus
    public var reason: ProfileStartDiagnosisReason
    public var title: String
    public var detail: String?
    public var primaryAction: ProfileStartDiagnosisAction

    public init(status: ProfileStartDiagnosisStatus,
                reason: ProfileStartDiagnosisReason,
                title: String,
                detail: String? = nil,
                primaryAction: ProfileStartDiagnosisAction) {
        self.status = status
        self.reason = reason
        self.title = title
        self.detail = detail
        self.primaryAction = primaryAction
    }
}

public func diagnoseProfileStart(_ profile: Profile,
                                 newbroPath: String?,
                                 cliVersion: String?,
                                 probe: ExecutorProbe?,
                                 probeError: String?) -> ProfileStartDiagnosis {
    guard profileIsComplete(profile) else {
        return ProfileStartDiagnosis(
            status: .blocked,
            reason: .profileIncomplete,
            title: "Start blocked: profile is incomplete",
            detail: "Complete the profile before starting it.",
            primaryAction: .openProfileSettings
        )
    }

    guard let newbroPath, !newbroPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        return ProfileStartDiagnosis(
            status: .blocked,
            reason: .newbroMissing,
            title: "Start blocked: Newbro CLI is not installed",
            detail: "Install the Newbro CLI before starting profiles.",
            primaryAction: .installNewbroCLI
        )
    }

    switch profile.enabledExecutors.first {
    case "codex":
        if let probeError {
            if probeError.contains("newer Newbro CLI") {
                return ProfileStartDiagnosis(
                    status: .blocked,
                    reason: .newbroTooOldForProbe,
                    title: "Start blocked: Newbro CLI is too old",
                    detail: probeError,
                    primaryAction: .updateNewbroCLI
                )
            }
            return ProfileStartDiagnosis(
                status: .blocked,
                reason: .codexProbeFailed,
                title: "Start blocked: Codex diagnosis failed",
                detail: probeError,
                primaryAction: .rerunDiagnosis
            )
        }

        guard let probe else {
            return ProfileStartDiagnosis(
                status: .checking,
                reason: .ready,
                title: "Checking Codex setup",
                primaryAction: .none
            )
        }

        if probe.current.ok {
            return readyDiagnosis(cliVersion: cliVersion)
        }

        if isLoginRequired(probe.current.error) {
            return ProfileStartDiagnosis(
                status: .blocked,
                reason: .codexLoginRequired,
                title: "Start blocked: Codex sign-in required",
                detail: probe.current.error,
                primaryAction: .signInCodex
            )
        }

        if probe.candidates.contains(where: { $0.ok && !$0.isCurrent }) {
            return ProfileStartDiagnosis(
                status: .blocked,
                reason: .codexConfiguredButBroken,
                title: "Start blocked: selected Codex is broken",
                detail: probe.current.error,
                primaryAction: .openCodexSettings
            )
        }

        return ProfileStartDiagnosis(
            status: .blocked,
            reason: .codexMissing,
            title: "Start blocked: Codex is not set up",
            detail: probe.current.error,
            primaryAction: .setUpCodex
        )

    case "hermes":
        guard let probe else {
            return ProfileStartDiagnosis(status: .checking, reason: .ready, title: "Checking Hermes setup", primaryAction: .none)
        }
        if !probe.current.ok {
            return ProfileStartDiagnosis(status: .blocked, reason: .hermesMissing,
                                         title: "Start blocked: Hermes is not set up",
                                         detail: probe.current.error, primaryAction: .setUpHermes)
        }
        if probe.current.authenticated == false {
            return ProfileStartDiagnosis(status: .blocked, reason: .hermesSignInRequired,
                                         title: "Start blocked: Hermes sign-in required",
                                         detail: "Run `hermes setup --portal` in a terminal, then Refresh.",
                                         primaryAction: .signInHermes)
        }
        return readyDiagnosis(cliVersion: cliVersion)

    default:
        return readyDiagnosis(cliVersion: cliVersion)
    }
}

private func readyDiagnosis(cliVersion: String?) -> ProfileStartDiagnosis {
    if cliVersion == nil {
        return ProfileStartDiagnosis(
            status: .ready,
            reason: .newbroVersionUnknown,
            title: "Ready to start",
            detail: "Newbro CLI version is unknown.",
            primaryAction: .none
        )
    }

    return ProfileStartDiagnosis(
        status: .ready,
        reason: .ready,
        title: "Ready to start",
        primaryAction: .none
    )
}

private func isLoginRequired(_ error: String?) -> Bool {
    guard let error else { return false }
    let text = error.lowercased()
    return text.contains("login")
        || text.contains("log in")
        || text.contains("sign in")
        || text.contains("signin")
        || text.contains("auth")
}
