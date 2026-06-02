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
