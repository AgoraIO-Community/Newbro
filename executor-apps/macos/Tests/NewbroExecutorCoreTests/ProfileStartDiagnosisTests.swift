import XCTest
@testable import NewbroExecutorCore

final class ProfileStartDiagnosisTests: XCTestCase {
    func testIncompleteProfileBlocksWithProfileSettingsAction() {
        let diagnosis = diagnoseProfileStart(
            incompleteProfile(),
            newbroPath: "/usr/local/bin/newbro",
            cliVersion: "1.0.0",
            probe: readyCodexProbe(),
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .profileIncomplete)
        XCTAssertEqual(diagnosis.primaryAction, .openProfileSettings)
    }

    func testMissingNewbroCLIBlocksWithInstallAction() {
        let diagnosis = diagnoseProfileStart(
            completeProfile(executors: ["acpx"]),
            newbroPath: nil,
            cliVersion: nil,
            probe: nil,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .newbroMissing)
        XCTAssertEqual(diagnosis.primaryAction, .installNewbroCLI)
    }

    func testNonCodexProfileIsReadyWithoutCodexProbe() {
        let diagnosis = diagnoseProfileStart(
            completeProfile(executors: ["acpx"]),
            newbroPath: "/usr/local/bin/newbro",
            cliVersion: "1.0.0",
            probe: nil,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .ready)
        XCTAssertEqual(diagnosis.reason, .ready)
        XCTAssertEqual(diagnosis.primaryAction, .none)
    }

    func testMissingCodexMapsToSetupCodexAction() {
        let diagnosis = diagnoseProfileStart(
            completeProfile(executors: ["codex"]),
            newbroPath: "/usr/local/bin/newbro",
            cliVersion: "1.0.0",
            probe: missingCodexProbe(),
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .codexMissing)
        XCTAssertEqual(diagnosis.title, "Start blocked: Codex is not set up")
        XCTAssertEqual(diagnosis.primaryAction, .setUpCodex)
    }

    func testBrokenConfiguredCodexWithUsableCandidateMapsToOpenCodexSettingsAction() {
        let diagnosis = diagnoseProfileStart(
            completeProfile(executors: ["codex"]),
            newbroPath: "/usr/local/bin/newbro",
            cliVersion: "1.0.0",
            probe: brokenConfiguredCodexProbeWithUsableCandidate(),
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .codexConfiguredButBroken)
        XCTAssertEqual(diagnosis.title, "Start blocked: selected Codex is broken")
        XCTAssertEqual(diagnosis.primaryAction, .openCodexSettings)
    }

    func testReadyCodexAllowsStartWhenNewbroVersionIsUnknown() {
        let diagnosis = diagnoseProfileStart(
            completeProfile(executors: ["codex"]),
            newbroPath: "/usr/local/bin/newbro",
            cliVersion: nil,
            probe: readyCodexProbe(),
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .ready)
        XCTAssertEqual(diagnosis.reason, .newbroVersionUnknown)
        XCTAssertEqual(diagnosis.primaryAction, .none)
    }

    func testNewerNewbroCLIProbeErrorMapsToUpdateAction() {
        let diagnosis = diagnoseProfileStart(
            completeProfile(executors: ["codex"]),
            newbroPath: "/usr/local/bin/newbro",
            cliVersion: "0.1.0",
            probe: nil,
            probeError: "Codex settings require a newer Newbro CLI. Update CLI, then reopen Settings."
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .newbroTooOldForProbe)
        XCTAssertEqual(diagnosis.primaryAction, .updateNewbroCLI)
    }
}

private func completeProfile(executors: [String]) -> Profile {
    Profile(
        id: "p1",
        label: "Profile",
        baseURL: "https://newbro.example",
        nodeID: "node-1",
        token: "token-1",
        enabledExecutors: executors
    )
}

private func incompleteProfile() -> Profile {
    Profile(
        id: "p1",
        label: "Profile",
        baseURL: "",
        nodeID: "node-1",
        token: "token-1",
        enabledExecutors: ["codex"]
    )
}

private func readyCodexProbe() -> ExecutorProbe {
    ExecutorProbe(
        supportedExecutors: ["codex"],
        current: CurrentExecutorProbe(
            executor: "codex",
            command: "/opt/homebrew/bin/codex",
            resolvedPath: "/opt/homebrew/bin/codex",
            version: "codex-cli 0.136.0",
            ok: true,
            error: nil
        ),
        candidates: []
    )
}

private func missingCodexProbe() -> ExecutorProbe {
    ExecutorProbe(
        supportedExecutors: ["codex"],
        current: CurrentExecutorProbe(
            executor: "codex",
            command: "codex",
            resolvedPath: nil,
            version: nil,
            ok: false,
            error: "vendor executable missing"
        ),
        candidates: []
    )
}

private func brokenConfiguredCodexProbeWithUsableCandidate() -> ExecutorProbe {
    ExecutorProbe(
        supportedExecutors: ["codex"],
        current: CurrentExecutorProbe(
            executor: "codex",
            command: "/opt/homebrew/bin/codex",
            resolvedPath: "/opt/homebrew/bin/codex",
            version: nil,
            ok: false,
            error: "vendor executable missing"
        ),
        candidates: [
            ExecutorCandidateProbe(
                path: "/Users/test/.bun/bin/codex",
                version: "codex-cli 0.136.0",
                ok: true,
                source: "discovered",
                error: nil,
                isCurrent: false
            ),
        ]
    )
}
