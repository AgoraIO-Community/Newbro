import XCTest
@testable import NewbroExecutorCore

final class ConnectCommandTests: XCTestCase {
    func testParsesAllFields() throws {
        let text = "newbro executor run --base-url https://x --node-id node-1 " +
                   "--token tok --enabled-executor codex --enabled-executor acpx"
        let fields = try parseConnectCommand(text)
        XCTAssertEqual(fields, ConnectCommandFields(
            baseURL: "https://x", nodeID: "node-1", token: "tok",
            enabledExecutors: ["codex", "acpx"]))
    }

    func testMissingCoreFieldThrows() {
        XCTAssertThrowsError(try parseConnectCommand("newbro executor run --base-url https://x"))
    }

    func testConflictingProfileIDs() {
        let profiles = [
            Profile(id: "a", label: "A", baseURL: "https://x", nodeID: "n1", token: "t"),
            Profile(id: "b", label: "B", baseURL: "https://x", nodeID: "n1", token: "t2"),
            Profile(id: "c", label: "C", baseURL: "https://x", nodeID: "n2", token: "t3"),
        ]
        XCTAssertEqual(conflictingProfileIDs(profiles), Set(["a", "b"]))
    }
}
