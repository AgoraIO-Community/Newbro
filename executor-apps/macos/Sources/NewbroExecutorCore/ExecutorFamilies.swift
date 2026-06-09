import Foundation

/// Mirror of the backend's SUPPORTED_EXECUTOR_FAMILIES / PROBEABLE_EXECUTOR_FAMILIES.
public let supportedExecutorFamilies: [String] = ["codex", "acpx", "hermes"]
public let probeableExecutorFamilies: [String] = ["codex", "hermes"]

/// The picker's initial selection: a supported family for an existing profile, or nil
/// (no default) so the user must choose explicitly — no fallback to codex.
public func initialPickerFamily(for enabledExecutors: [String]?) -> String? {
    guard let first = enabledExecutors?.first, supportedExecutorFamilies.contains(first) else { return nil }
    return first
}
