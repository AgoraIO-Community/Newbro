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

    func testNewbroBinEnvironmentOverrideWins() {
        let dev = "/Users/test/dev/newbro"
        setenv("NEWBRO_BIN", dev, 1)
        defer { unsetenv("NEWBRO_BIN") }
        // overridePath defaults to the NEWBRO_BIN env var.
        let locator = RuntimeLocator(
            homeDir: home,
            fileExists: { $0 == dev || $0 == "/Users/test/.local/bin/newbro" },
            whichNewbro: { nil })
        XCTAssertEqual(locator.resolveNewbro(), dev)
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

    func testCodexStatusReportsVersion() {
        let locator = RuntimeLocator(
            overridePath: nil,
            homeDir: home,
            fileExists: { _ in false },
            whichNewbro: { nil },
            whichCommand: { name in name == "codex" ? "/opt/bin/codex" : nil },
            runCommand: { argv, _ in
                XCTAssertEqual(argv, ["/opt/bin/codex", "--version"])
                return (0, "codex 0.42.0\n")
            })
        XCTAssertEqual(locator.codexRuntimeStatus().menuTitle, "Codex v0.42.0")
        XCTAssertTrue(locator.codexRuntimeStatus().isAvailable)
    }

    func testCodexStatusWarnsWhenMissing() {
        let locator = RuntimeLocator(
            overridePath: nil,
            homeDir: home,
            fileExists: { _ in false },
            whichNewbro: { nil },
            whichCommand: { _ in nil },
            runCommand: { _, _ in (1, "") })
        XCTAssertEqual(locator.codexRuntimeStatus().menuTitle, "No Codex found. Newbro may not work properly.")
        XCTAssertFalse(locator.codexRuntimeStatus().isAvailable)
    }

    func testExtractVersionIgnoresTrailingWarnings() {
        XCTAssertEqual(
            RuntimeLocator.extractVersion("""
            warning: using fallback path
            codex 1.2.3-beta
            trailing junk after version
            """),
            "1.2.3-beta")
    }

    func testExtractVersionReturnsNilForMalformedOutput() {
        XCTAssertNil(RuntimeLocator.extractVersion("warning: codex version unavailable"))
    }

    func testCodexStatusShowsDetectedWhenVersionOutputIsMalformed() {
        let locator = RuntimeLocator(
            overridePath: nil,
            homeDir: home,
            fileExists: { _ in false },
            whichNewbro: { nil },
            whichCommand: { name in name == "codex" ? "/opt/bin/codex" : nil },
            runCommand: { _, _ in (0, "warning: codex version unavailable") })
        let status = locator.codexRuntimeStatus()
        XCTAssertEqual(status.menuTitle, "Codex detected")
        XCTAssertTrue(status.isAvailable)
        XCTAssertNil(status.version)
    }

    func testLoginShellWhichCommandRejectsInvalidNames() {
        XCTAssertNil(RuntimeLocator.loginShellWhichCommand("definitely_missing_codex; echo injected"))
    }

    func testRunCommandOutputTimesOut() {
        let result = RuntimeLocator.runCommandOutput(
            ["/bin/sh", "-c", "sleep 1; echo late"],
            nil,
            timeout: 0.01)
        XCTAssertEqual(result.0, 124)
        XCTAssertEqual(result.1, "")
    }
}
