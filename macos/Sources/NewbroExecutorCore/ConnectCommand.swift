import Foundation

public struct ConnectCommandFields: Equatable {
    public let baseURL: String
    public let nodeID: String
    public let token: String
    public let enabledExecutors: [String]

    public init(baseURL: String, nodeID: String, token: String, enabledExecutors: [String]) {
        self.baseURL = baseURL
        self.nodeID = nodeID
        self.token = token
        self.enabledExecutors = enabledExecutors
    }
}

public enum ConnectCommandError: Error, Equatable {
    case missingFields([String])
}

/// Tokenize a shell-style command line, honoring single/double quotes so a
/// shell-quoted value like `'codex'` becomes `codex`. Correctly reassembles the
/// `'a'"'"'b'` single-quote-escaping pattern that POSIX shell quoting emits.
func shellTokenize(_ text: String) -> [String] {
    var tokens: [String] = []
    var current = ""
    var hasToken = false
    var quote: Character? = nil
    for ch in text {
        if let active = quote {
            if ch == active { quote = nil } else { current.append(ch) }
            continue
        }
        if ch == "'" || ch == "\"" {
            quote = ch
            hasToken = true
            continue
        }
        if ch.isWhitespace {
            if hasToken { tokens.append(current); current = ""; hasToken = false }
            continue
        }
        current.append(ch)
        hasToken = true
    }
    if hasToken { tokens.append(current) }
    return tokens
}

public func parseConnectCommand(_ text: String) throws -> ConnectCommandFields {
    let tokens = shellTokenize(text)
    var baseURL = "", nodeID = "", token = ""
    var enabled: [String] = []
    var index = 0
    let valueFlags: Set<String> = ["--base-url", "--node-id", "--token", "--enabled-executor"]
    while index < tokens.count {
        let flag = tokens[index]
        if valueFlags.contains(flag), index + 1 < tokens.count {
            let value = tokens[index + 1]
            switch flag {
            case "--base-url": baseURL = value
            case "--node-id": nodeID = value
            case "--token": token = value
            default: enabled.append(value)
            }
            index += 2
            continue
        }
        index += 1
    }
    var missing: [String] = []
    if baseURL.isEmpty { missing.append("--base-url") }
    if nodeID.isEmpty { missing.append("--node-id") }
    if token.isEmpty { missing.append("--token") }
    if !missing.isEmpty { throw ConnectCommandError.missingFields(missing) }
    return ConnectCommandFields(baseURL: baseURL, nodeID: nodeID, token: token,
                                enabledExecutors: enabled)
}

public func normalizedBaseURL(_ value: String) -> String {
    var text = value.trimmingCharacters(in: .whitespacesAndNewlines)
    while text.hasSuffix("/") { text.removeLast() }
    return text
}

public func normalizedProfileIdentity(baseURL: String, nodeID: String) -> String {
    normalizedBaseURL(baseURL) + "\u{0}" + nodeID.trimmingCharacters(in: .whitespacesAndNewlines)
}

public func firstMatchingProfileIndex(in profiles: [Profile], baseURL: String, nodeID: String) -> Int? {
    let target = normalizedProfileIdentity(baseURL: baseURL, nodeID: nodeID)
    return profiles.firstIndex {
        normalizedProfileIdentity(baseURL: $0.baseURL, nodeID: $0.nodeID) == target
    }
}

public func uniqueProfileID(existing profiles: [Profile],
                            maxAttempts: Int = 100,
                            generate: () -> String = { "profile-\(UUID().uuidString.prefix(8))" }) -> String {
    let existingIDs = Set(profiles.map(\.id))
    precondition(maxAttempts > 0, "maxAttempts must be positive")
    for _ in 0..<maxAttempts {
        let candidate = generate()
        if !existingIDs.contains(candidate) { return candidate }
    }
    preconditionFailure("Unable to generate a unique profile ID")
}

public func conflictingProfileIDs(_ profiles: [Profile]) -> Set<String> {
    var seen: [String: String] = [:]
    var conflicts: Set<String> = []
    for profile in profiles {
        let key = normalizedProfileIdentity(baseURL: profile.baseURL, nodeID: profile.nodeID)
        if let first = seen[key] {
            conflicts.insert(first)
            conflicts.insert(profile.id)
        } else {
            seen[key] = profile.id
        }
    }
    return conflicts
}
