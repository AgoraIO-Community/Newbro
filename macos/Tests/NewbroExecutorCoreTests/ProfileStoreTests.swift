import XCTest
@testable import NewbroExecutorCore

final class ProfileStoreTests: XCTestCase {
    func testSaveThenLoadRoundTrips() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let path = dir.appendingPathComponent("menubar.json")
        let store = ProfileStore(path: path)
        let profiles = [
            Profile(id: "p1", label: "Prod", baseURL: "https://x", nodeID: "node-1",
                    token: "t1", enabledExecutors: ["codex"], autoActivate: true),
            Profile(id: "p2", label: "Staging", baseURL: "http://127.0.0.1:8000",
                    nodeID: "node-2", token: "t2"),
        ]
        try store.save(profiles)
        let loaded = store.load()
        XCTAssertEqual(loaded, profiles)
        XCTAssertEqual(loaded[1].enabledExecutors, [])
        XCTAssertFalse(loaded[1].autoActivate)
    }

    func testLoadMissingFileReturnsEmpty() {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).appendingPathComponent("absent.json")
        XCTAssertEqual(ProfileStore(path: path).load(), [])
    }

    func testJSONUsesSnakeCaseKeys() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let path = dir.appendingPathComponent("menubar.json")
        try ProfileStore(path: path).save([
            Profile(id: "p1", label: "L", baseURL: "https://x", nodeID: "n", token: "t",
                    enabledExecutors: ["codex"], autoActivate: true)
        ])
        let text = try String(contentsOf: path, encoding: .utf8)
        XCTAssertTrue(text.contains("\"base_url\""))
        XCTAssertTrue(text.contains("\"node_id\""))
        XCTAssertTrue(text.contains("\"enabled_executors\""))
        XCTAssertTrue(text.contains("\"auto_activate\""))
    }
}
