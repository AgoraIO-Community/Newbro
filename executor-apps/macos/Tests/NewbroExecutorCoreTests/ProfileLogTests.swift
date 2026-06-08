import XCTest
@testable import NewbroExecutorCore

final class ProfileLogTests: XCTestCase {
    private func tempLog() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("node.log")
    }

    func testAppendAndRecent() {
        let log = ProfileLog(path: tempLog())
        log.append("[start] one")
        log.append("[ready] two")
        XCTAssertEqual(log.recent(), ["[start] one", "[ready] two"])
    }

    func testRecentCapsToMaxLines() {
        let log = ProfileLog(path: tempLog(), maxLines: 3)
        for index in 0..<10 { log.append("line \(index)") }
        XCTAssertEqual(log.recent(), ["line 7", "line 8", "line 9"])
    }

    func testRecentOnMissingFileIsEmpty() {
        XCTAssertEqual(ProfileLog(path: tempLog()).recent(), [])
    }

    func testDefaultPathUsesProfileID() {
        let path = ProfileLog.defaultPath(profileID: "abc")
        XCTAssertEqual(path.lastPathComponent, "executor-ui-abc.log")
        XCTAssertEqual(path.deletingLastPathComponent().lastPathComponent, "logs")
    }
}
