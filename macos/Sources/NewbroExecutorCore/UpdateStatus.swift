/// The result of comparing installed versions against the latest release tag.
/// Each field holds the available version string, or nil when up to date.
public struct UpdateStatus: Equatable, Sendable {
    public var cliUpdate: String?
    public var appUpdate: String?

    public init(cliUpdate: String? = nil, appUpdate: String? = nil) {
        self.cliUpdate = cliUpdate
        self.appUpdate = appUpdate
    }
}

public struct UpdateSettingsRows: Equatable, Sendable {
    public let cliVersionRow: String
    public let appVersionRow: String
    public let cliUpdateRow: String?
    public let appUpdateRow: String?
}

public func updateSettingsRows(installedCLI: String?, installedApp: String?, status: UpdateStatus) -> UpdateSettingsRows {
    UpdateSettingsRows(
        cliVersionRow: installedCLI.map { "Newbro CLI: v\($0)" } ?? "Newbro CLI: version unknown",
        appVersionRow: appVersionMenuRow(installedApp),
        cliUpdateRow: status.cliUpdate.map { "Newbro CLI update: \($0) available" },
        appUpdateRow: status.appUpdate.map { "Menu bar app update: \($0) available" })
}

private func appVersionMenuRow(_ installedApp: String?) -> String {
    guard let installedApp else { return "Menu bar app: version unknown" }
    if installedApp == "1.0" {
        return "Menu bar app: local build (bundle v1.0)"
    }
    return "Menu bar app: v\(installedApp)"
}

/// Compute which components have an update available. Never reports a false
/// positive: any nil/unparseable input leaves that field nil. The app's
/// dev-default version ("1.0") is treated as "not a real release" and suppressed.
public func updateStatus(installedCLI: String?, installedApp: String?, latestTag: String?) -> UpdateStatus {
    guard let latestTag, let latest = SemanticVersion(latestTag) else { return UpdateStatus() }
    var result = UpdateStatus()
    if let installed = installedCLI.flatMap(SemanticVersion.init), latest > installed {
        result.cliUpdate = latestTag
    }
    if let appString = installedApp, appString != "1.0",
       let app = SemanticVersion(appString), latest > app {
        result.appUpdate = latestTag
    }
    return result
}
