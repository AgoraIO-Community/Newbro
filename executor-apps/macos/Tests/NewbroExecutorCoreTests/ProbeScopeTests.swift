import XCTest
@testable import NewbroExecutorCore

final class ProbeScopeTests: XCTestCase {
    func testProbeScopeUnionsProfileFamiliesAndViewedFamily() {
        let profiles = [
            Profile(id: "a", label: "", baseURL: "", nodeID: "", token: "", enabledExecutors: ["codex"]),
            Profile(id: "b", label: "", baseURL: "", nodeID: "", token: "", enabledExecutors: ["acpx"]),
        ]
        XCTAssertEqual(Set(probeScope(profiles: profiles, viewedFamily: "hermes")), Set(["codex", "hermes"]))
        XCTAssertEqual(Set(probeScope(profiles: profiles, viewedFamily: nil)), Set(["codex"]))
    }
}
