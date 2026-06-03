import Foundation

public struct Profile: Codable, Equatable, Identifiable {
    public var id: String
    public var label: String
    public var baseURL: String
    public var nodeID: String
    public var token: String
    public var enabledExecutors: [String]
    public var autoActivate: Bool

    public init(id: String, label: String, baseURL: String, nodeID: String,
                token: String, enabledExecutors: [String] = [], autoActivate: Bool = false) {
        self.id = id
        self.label = label
        self.baseURL = baseURL
        self.nodeID = nodeID
        self.token = token
        self.enabledExecutors = enabledExecutors
        self.autoActivate = autoActivate
    }

    enum CodingKeys: String, CodingKey {
        case id, label, token
        case baseURL = "base_url"
        case nodeID = "node_id"
        case enabledExecutors = "enabled_executors"
        case autoActivate = "auto_activate"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        baseURL = try c.decodeIfPresent(String.self, forKey: .baseURL) ?? ""
        nodeID = try c.decodeIfPresent(String.self, forKey: .nodeID) ?? ""
        token = try c.decodeIfPresent(String.self, forKey: .token) ?? ""
        enabledExecutors = try c.decodeIfPresent([String].self, forKey: .enabledExecutors) ?? []
        autoActivate = try c.decodeIfPresent(Bool.self, forKey: .autoActivate) ?? false
    }
}

public func profileCanStart(_ profile: Profile, codexRuntimeAvailable: () -> Bool) -> Bool {
    if profile.enabledExecutors.contains("codex") {
        return codexRuntimeAvailable()
    }
    return true
}

public func profileIsComplete(_ profile: Profile) -> Bool {
    !profile.baseURL.isEmpty && !profile.nodeID.isEmpty
        && !profile.token.isEmpty && !profile.enabledExecutors.isEmpty
}

public enum ProfileLifecycleAction: Equatable {
    case start(Profile)
    case restart(Profile)
}

public func startProfileAction(for profile: Profile,
                               runtimeAvailable: Bool,
                               codexRuntimeAvailable: () -> Bool) -> ProfileLifecycleAction? {
    guard runtimeAvailable, profileCanStart(profile, codexRuntimeAvailable: codexRuntimeAvailable) else {
        return nil
    }
    return .start(profile)
}

public func startProfileAction(in profiles: [Profile],
                               profileID: String,
                               runtimeAvailable: Bool,
                               codexRuntimeAvailable: () -> Bool) -> ProfileLifecycleAction? {
    guard let profile = profiles.first(where: { $0.id == profileID }) else { return nil }
    return startProfileAction(for: profile,
                              runtimeAvailable: runtimeAvailable,
                              codexRuntimeAvailable: codexRuntimeAvailable)
}

public func restartProfileAction(for profile: Profile,
                                 runtimeAvailable: Bool,
                                 codexRuntimeAvailable: () -> Bool) -> ProfileLifecycleAction? {
    guard runtimeAvailable, profileCanStart(profile, codexRuntimeAvailable: codexRuntimeAvailable) else {
        return nil
    }
    return .restart(profile)
}

public func autostartProfileActions(in profiles: [Profile],
                                    runtimeAvailable: Bool,
                                    codexRuntimeAvailable: () -> Bool) -> [ProfileLifecycleAction] {
    profiles.compactMap { profile in
        guard profile.autoActivate, profileIsComplete(profile) else { return nil }
        return startProfileAction(for: profile,
                                  runtimeAvailable: runtimeAvailable,
                                  codexRuntimeAvailable: codexRuntimeAvailable)
    }
}

public func pastedProfileAction(for profile: Profile,
                                runtimeAvailable: Bool,
                                isActive: Bool,
                                codexRuntimeAvailable: () -> Bool) -> ProfileLifecycleAction? {
    guard profileIsComplete(profile) else { return nil }
    if isActive {
        return restartProfileAction(for: profile,
                                    runtimeAvailable: runtimeAvailable,
                                    codexRuntimeAvailable: codexRuntimeAvailable)
    }
    return startProfileAction(for: profile,
                              runtimeAvailable: runtimeAvailable,
                              codexRuntimeAvailable: codexRuntimeAvailable)
}
