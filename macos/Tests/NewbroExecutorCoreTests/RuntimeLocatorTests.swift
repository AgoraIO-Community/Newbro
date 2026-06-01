import XCTest
@testable import NewbroExecutorCore

final class RuntimeLocatorTests: XCTestCase {
    private let home = URL(fileURLWithPath: "/Users/test")

    func testResolvesUvLocationWhenPresent() {
        let uv = "/Users/test/.local/bin/newbro"
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { $0 == uv },
            whichNewbro: { nil })
        XCTAssertEqual(locator.resolveNewbro(), uv)
        XCTAssertTrue(locator.isRuntimeAvailable)
    }

    func testOverrideWins() {
        let override = "/opt/newbro"
        let locator = RuntimeLocator(
            overridePath: override, homeDir: home,
            fileExists: { $0 == override || $0 == "/Users/test/.local/bin/newbro" },
            whichNewbro: { nil })
        XCTAssertEqual(locator.resolveNewbro(), override)
    }

    func testFallsBackToLoginShellWhich() {
        let shellPath = "/usr/local/bin/newbro"
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { $0 == shellPath },
            whichNewbro: { shellPath })
        XCTAssertEqual(locator.resolveNewbro(), shellPath)
    }

    func testMissingRuntime() {
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { _ in false }, whichNewbro: { nil })
        XCTAssertNil(locator.resolveNewbro())
        XCTAssertFalse(locator.isRuntimeAvailable)
        XCTAssertNil(locator.nodeArgv(for: Profile(
            id: "p", label: "L", baseURL: "https://x", nodeID: "n", token: "t")))
    }

    func testNodeArgvShape() {
        let uv = "/Users/test/.local/bin/newbro"
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { $0 == uv }, whichNewbro: { nil })
        let profile = Profile(id: "p", label: "L", baseURL: "https://x",
                              nodeID: "n", token: "t", enabledExecutors: ["codex", "acpx"])
        XCTAssertEqual(locator.nodeArgv(for: profile), [
            uv, "executor", "run",
            "--base-url", "https://x", "--node-id", "n", "--token", "t",
            "--enabled-executor", "codex", "--enabled-executor", "acpx",
        ])
    }

    func testInstallCommandArgv() {
        let locator = RuntimeLocator(overridePath: nil, homeDir: home,
                                     fileExists: { _ in false }, whichNewbro: { nil })
        let argv = locator.installCommandArgv()
        XCTAssertEqual(argv[0], "/bin/sh")
        XCTAssertEqual(argv[1], "-c")
        XCTAssertTrue(argv[2].contains("install-newbro-cli.sh"))
        XCTAssertTrue(argv[2].contains("curl -fsSL"))
    }
}
