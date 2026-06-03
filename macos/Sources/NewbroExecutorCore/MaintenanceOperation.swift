public struct MaintenanceCompletion: Equatable, Sendable {
    public let errorRow: String?
    public let notificationTitle: String
    public let notificationBody: String

    public init(errorRow: String?, notificationTitle: String, notificationBody: String) {
        self.errorRow = errorRow
        self.notificationTitle = notificationTitle
        self.notificationBody = notificationBody
    }
}

public func runtimeInstallCompletion(exitCode: Int32, runtimeAvailable: Bool) -> MaintenanceCompletion {
    if exitCode != 0 {
        return MaintenanceCompletion(
            errorRow: "Runtime install failed (exit \(exitCode)).",
            notificationTitle: "Runtime install failed",
            notificationBody: "Exit \(exitCode).")
    }
    if !runtimeAvailable {
        return MaintenanceCompletion(
            errorRow: "Runtime install finished, but Newbro is still unavailable.",
            notificationTitle: "Runtime install failed",
            notificationBody: "Newbro runtime is still unavailable.")
    }
    return MaintenanceCompletion(
        errorRow: nil,
        notificationTitle: "Runtime installed",
        notificationBody: "Newbro runtime is ready.")
}
