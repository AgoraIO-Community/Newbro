import Foundation

/// A minimal `X.Y.Z` version, tolerant of a leading `v` and ignoring any
/// pre-release/build suffix (`-rc1`, `+build`). Missing minor/patch default to 0.
public struct SemanticVersion: Comparable, Equatable, Sendable {
    public let major: Int
    public let minor: Int
    public let patch: Int

    public init?(_ string: String) {
        var text = string.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("v") { text.removeFirst() }
        let core = text.split(whereSeparator: { $0 == "-" || $0 == "+" }).first.map(String.init) ?? ""
        let parts = core.split(separator: ".", omittingEmptySubsequences: false).map(String.init)
        guard let first = parts.first, let major = Int(first) else { return nil }
        let minor: Int
        if parts.count > 1 {
            guard let value = Int(parts[1]) else { return nil }
            minor = value
        } else { minor = 0 }
        let patch: Int
        if parts.count > 2 {
            guard let value = Int(parts[2]) else { return nil }
            patch = value
        } else { patch = 0 }
        self.major = major
        self.minor = minor
        self.patch = patch
    }

    public static func < (lhs: SemanticVersion, rhs: SemanticVersion) -> Bool {
        (lhs.major, lhs.minor, lhs.patch) < (rhs.major, rhs.minor, rhs.patch)
    }
}
