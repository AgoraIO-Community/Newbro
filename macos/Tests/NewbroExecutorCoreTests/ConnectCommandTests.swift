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

    func testParsesShellQuotedValues() throws {
        // The web UI emits shell-quoted values; pasting into the app must strip
        // the quotes (otherwise the CLI rejects e.g. --enabled-executor 'codex').
        let text = "newbro executor run --base-url 'http://localhost:8000' " +
                   "--node-id 'node-abc' --token 'MRElL_T251-b1c' --enabled-executor 'codex'"
        let fields = try parseConnectCommand(text)
        XCTAssertEqual(fields, ConnectCommandFields(
            baseURL: "http://localhost:8000", nodeID: "node-abc",
            token: "MRElL_T251-b1c", enabledExecutors: ["codex"]))
    }

    func testParsesPosixSingleQuoteEscaping() throws {
        // shellQuote("tok'en") => 'tok'"'"'en'  — must reassemble to tok'en.
        let text = "newbro executor run --base-url https://x --node-id n " +
                   "--token 'tok'\"'\"'en'"
        let fields = try parseConnectCommand(text)
        XCTAssertEqual(fields.token, "tok'en")
    }

    func testMissingCoreFieldThrows() {
        XCTAssertThrowsError(try parseConnectCommand("newbro executor run --base-url https://x")) { error in
            XCTAssertEqual(error as? ConnectCommandError, .missingFields(["--node-id", "--token"]))
        }
    }

    func testValueFlagAsLastTokenDoesNotCrash() {
        XCTAssertThrowsError(try parseConnectCommand(
            "newbro executor run --base-url https://x --node-id n --token"))
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
