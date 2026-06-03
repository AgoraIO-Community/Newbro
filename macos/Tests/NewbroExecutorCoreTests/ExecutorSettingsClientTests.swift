import XCTest
@testable import NewbroExecutorCore

final class ExecutorSettingsClientTests: XCTestCase {
    func testDecodesCodexProbeJSON() throws {
        let json = """
        {
          "supported_executors": ["codex"],
          "current": {
            "executor": "codex",
            "command": "codex",
            "resolved_path": "/opt/homebrew/bin/codex",
            "version": null,
            "ok": false,
            "error": "vendor executable missing"
          },
          "candidates": [
            {
              "path": "/opt/homebrew/bin/codex",
              "version": null,
              "ok": false,
              "source": "configured",
              "error": "vendor executable missing",
              "is_current": true
            },
            {
              "path": "/Users/test/.bun/bin/codex",
              "version": "codex-cli 0.136.0",
              "ok": true,
              "source": "discovered",
              "error": null,
              "is_current": false
            }
          ]
        }
        """.data(using: .utf8)!

        let probe = try JSONDecoder().decode(ExecutorProbe.self, from: json)

        XCTAssertEqual(probe.supportedExecutors, ["codex"])
        XCTAssertEqual(probe.current.command, "codex")
        XCTAssertEqual(probe.current.resolvedPath, "/opt/homebrew/bin/codex")
        XCTAssertFalse(probe.current.ok)
        XCTAssertEqual(probe.current.error, "vendor executable missing")
        XCTAssertEqual(probe.candidates[1].path, "/Users/test/.bun/bin/codex")
        XCTAssertEqual(probe.candidates[1].version, "codex-cli 0.136.0")
        XCTAssertTrue(probe.candidates[1].ok)
    }

    func testClientInvokesProbeAndUseCommands() throws {
        var calls: [(argv: [String], environment: [String: String]?)] = []
        let client = ExecutorSettingsClient(
            newbroPath: "/usr/local/bin/newbro",
            environment: ["PATH": "/login/bin", "HOME": "/Users/test"]
        ) { argv, environment in
            calls.append((argv, environment))
            if argv.contains("probe") {
                return """
                {
                  "supported_executors": ["codex"],
                  "current": {
                    "executor": "codex",
                    "command": "/Users/test/.bun/bin/codex",
                    "resolved_path": "/Users/test/.bun/bin/codex",
                    "version": "codex-cli 0.136.0",
                    "ok": true,
                    "error": null
                  },
                  "candidates": []
                }
                """
            }
            return "ok\n"
        }

        let probe = try client.probe()
        try client.useCodex(path: "/Users/test/.bun/bin/codex")

        XCTAssertEqual(probe.current.version, "codex-cli 0.136.0")
        XCTAssertEqual(calls.map(\.argv), [
            ["/usr/local/bin/newbro", "executor", "probe", "--executor", "codex", "--json"],
            ["/usr/local/bin/newbro", "executor", "use", "--executor", "codex", "--command", "/Users/test/.bun/bin/codex"],
        ])
        XCTAssertEqual(calls.map(\.environment), [
            ["PATH": "/login/bin", "HOME": "/Users/test"],
            ["PATH": "/login/bin", "HOME": "/Users/test"],
        ])
    }

    func testDefaultRunnerThrowsWhenCommandFails() throws {
        let script = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("newbro-failing-\(UUID().uuidString).sh")
        try "#!/bin/sh\necho failed\nexit 7\n".write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)

        let client = ExecutorSettingsClient(newbroPath: script.path)

        XCTAssertThrowsError(try client.probe()) { error in
            XCTAssertEqual(
                error as? ExecutorSettingsClientError,
                .commandFailed(status: 7, output: "failed\n")
            )
        }
    }

    func testProbeReportsRuntimeTooOldWhenProbeSubcommandIsUnsupported() throws {
        var calls: [[String]] = []
        let oldRuntimeOutput = """
        usage: newbro executor [-h] {run} ...
        newbro executor: error: argument executor_command: invalid choice: 'probe' (choose from 'run')
        """
        let client = ExecutorSettingsClient(newbroPath: "/usr/local/bin/newbro") { argv, _ in
            calls.append(argv)
            if argv == ["/usr/local/bin/newbro", "--version"] {
                return "newbro 0.1.2\n"
            }
            throw ExecutorSettingsClientError.commandFailed(status: 2, output: oldRuntimeOutput)
        }

        XCTAssertThrowsError(try client.probe()) { error in
            XCTAssertEqual(
                error as? ExecutorSettingsClientError,
                .runtimeTooOld(installedVersion: "0.1.2")
            )
            XCTAssertEqual(
                error.localizedDescription,
                "Codex settings require a newer Newbro CLI. Update CLI, then reopen Settings."
            )
        }
        XCTAssertEqual(calls, [
            ["/usr/local/bin/newbro", "executor", "probe", "--executor", "codex", "--json"],
            ["/usr/local/bin/newbro", "--version"],
        ])
    }

    func testExecutorSettingsErrorsHaveHumanReadableDescriptions() {
        XCTAssertEqual(
            ExecutorSettingsClientError.emptyOutput.localizedDescription,
            "Newbro CLI returned no output."
        )
        XCTAssertEqual(
            ExecutorSettingsClientError.commandFailed(status: 7, output: "\n failed \n").localizedDescription,
            "Newbro CLI command failed (exit 7): failed"
        )
        XCTAssertEqual(
            ExecutorSettingsClientError.commandFailed(status: 7, output: " \n ").localizedDescription,
            "Newbro CLI command failed (exit 7)."
        )
        XCTAssertEqual(
            ExecutorSettingsClientError.runtimeTooOld(installedVersion: nil).localizedDescription,
            "Codex settings require a newer Newbro CLI. Update CLI, then reopen Settings."
        )
    }
}
