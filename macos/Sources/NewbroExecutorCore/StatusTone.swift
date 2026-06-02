/// Semantic grouping of `NodeStatus` for UI indicators. Kept free of
/// SwiftUI/AppKit so it stays in Core and is unit-testable; the app layer maps
/// each tone to a concrete color.
public enum StatusTone: String, Equatable, Sendable {
    case ok        // ready
    case busy      // starting, connecting, retrying
    case attention // disconnected, error
    case idle      // idle, stopped
}

public func statusTone(_ status: NodeStatus) -> StatusTone {
    switch status {
    case .ready:
        return .ok
    case .starting, .connecting, .retrying:
        return .busy
    case .disconnected, .error:
        return .attention
    case .idle, .stopped:
        return .idle
    }
}
