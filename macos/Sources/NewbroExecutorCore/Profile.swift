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
