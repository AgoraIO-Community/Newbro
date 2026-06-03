import XCTest
@testable import NewbroExecutorCore

final class ProfileStartRulesTests: XCTestCase {
    func testCodexProfileCannotStartWhenCodexRuntimeUnavailable() {
        let profile = Profile(id: "p1", label: "A", baseURL: "https://x",
                              nodeID: "n", token: "t", enabledExecutors: ["codex"])

        XCTAssertFalse(profileCanStart(profile) { false })
    }

    func testCodexProfileCanStartWhenCodexRuntimeAvailable() {
        let profile = Profile(id: "p1", label: "A", baseURL: "https://x",
                              nodeID: "n", token: "t", enabledExecutors: ["codex"])

        XCTAssertTrue(profileCanStart(profile) { true })
    }

    func testNonCodexProfileDoesNotRequireCodexRuntimeProbe() {
        let profile = Profile(id: "p1", label: "A", baseURL: "https://x",
                              nodeID: "n", token: "t", enabledExecutors: ["acpx"])
        var probedCodex = false

        XCTAssertTrue(profileCanStart(profile) {
            probedCodex = true
            return false
        })
        XCTAssertFalse(probedCodex)
    }
}
