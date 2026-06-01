import Foundation

public enum NodeStatus: String, Equatable, Sendable {
    case idle, starting, connecting, ready, disconnected, retrying, error, stopped
}

public final class StatusParser {
    public private(set) var status: NodeStatus = .idle

    public init() {}

    @discardableResult
    public func onStart() -> NodeStatus {
        status = .starting
        return status
    }

    @discardableResult
    public func onLine(_ line: String) -> NodeStatus {
        if line.hasPrefix("[start]") {
            status = .starting
        } else if line.hasPrefix("[connect]") {
            status = .connecting
        } else if line.hasPrefix("[ready]") {
            status = .ready
        } else if line.hasPrefix("[retry]") {
            status = .retrying
        } else if line.hasPrefix("[warn]"), line.contains("disconnected=") {
            status = .disconnected
        } else if line.hasPrefix("[warn]"), line.contains("connect_failed=") {
            status = .connecting
        }
        return status
    }

    @discardableResult
    public func onExit(code: Int32, expected: Bool) -> NodeStatus {
        status = expected ? .stopped : .error
        return status
    }
}

public func aggregateStatus(_ statuses: [NodeStatus]) -> NodeStatus {
    let priority: [NodeStatus] = [.error, .disconnected, .retrying, .connecting, .starting, .ready]
    let present = Set(statuses)
    for candidate in priority where present.contains(candidate) {
        return candidate
    }
    return .idle
}
