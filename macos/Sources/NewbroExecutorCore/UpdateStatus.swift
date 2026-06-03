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

public struct UpdateMenuRows: Equatable, Sendable {
    public let cliVersionRow: String
    public let appVersionRow: String
    public let cliUpdateRow: String?
    public let appUpdateRow: String?
}

public func updateMenuRows(installedCLI: String?, installedApp: String?, status: UpdateStatus) -> UpdateMenuRows {
    UpdateMenuRows(
        cliVersionRow: installedCLI.map { "newbro CLI v\($0)" } ?? "newbro CLI version unknown",
        appVersionRow: installedApp.map { "App v\($0)" } ?? "App version unknown",
        cliUpdateRow: status.cliUpdate.map { "CLI update available: \($0)" },
        appUpdateRow: status.appUpdate.map { "App update available: \($0)" })
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
