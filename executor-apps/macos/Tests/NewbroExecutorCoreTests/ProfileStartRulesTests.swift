import XCTest
@testable import NewbroExecutorCore

final class ProfileStartRulesTests: XCTestCase {
    private func profile(_ id: String,
                         executors: [String] = ["acpx"],
                         autoActivate: Bool = false,
                         token: String = "t") -> Profile {
        Profile(id: id, label: id, baseURL: "https://x", nodeID: "n-\(id)",
                token: token, enabledExecutors: executors, autoActivate: autoActivate)
    }

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

    func testAutostartActionsStartOnlyCompleteEligibleAutoActivateProfiles() {
        let profiles = [
            profile("auto", autoActivate: true),
            profile("manual", autoActivate: false),
            profile("incomplete", autoActivate: true, token: ""),
            profile("codex", executors: ["codex"], autoActivate: true),
        ]

        let actions = autostartProfileActions(in: profiles, runtimeAvailable: true) { false }

        XCTAssertEqual(actions, [.start(profile("auto", autoActivate: true))])
    }

    func testAutostartActionsRespectRuntimeAvailability() {
        let profiles = [profile("auto", autoActivate: true)]

        XCTAssertEqual(autostartProfileActions(in: profiles, runtimeAvailable: false) { true }, [])
    }

    func testStartByIDUsesStartGateAndIgnoresUnknownProfile() {
        let profiles = [
            profile("one"),
            profile("codex", executors: ["codex"]),
        ]

        XCTAssertEqual(
            startProfileAction(in: profiles, profileID: "one", runtimeAvailable: true) { false },
            .start(profile("one")))
        XCTAssertNil(startProfileAction(in: profiles, profileID: "codex", runtimeAvailable: true) { false })
        XCTAssertNil(startProfileAction(in: profiles, profileID: "missing", runtimeAvailable: true) { true })
    }

    func testManualStartAndRestartActionsUseSameReadinessGate() {
        let codex = profile("codex", executors: ["codex"])
        let acpx = profile("acpx")

        XCTAssertNil(startProfileAction(for: codex, runtimeAvailable: true) { false })
        XCTAssertNil(restartProfileAction(for: codex, runtimeAvailable: true) { false })
        XCTAssertEqual(startProfileAction(for: acpx, runtimeAvailable: true) { false }, .start(acpx))
        XCTAssertEqual(restartProfileAction(for: acpx, runtimeAvailable: true) { false }, .restart(acpx))
    }

    func testPastedProfileActionStartsInactiveAndRestartsActiveProfiles() {
        let pasted = profile("pasted")

        XCTAssertEqual(
            pastedProfileAction(for: pasted, runtimeAvailable: true, isActive: false) { false },
            .start(pasted))
        XCTAssertEqual(
            pastedProfileAction(for: pasted, runtimeAvailable: true, isActive: true) { false },
            .restart(pasted))
    }

    func testPastedProfileActionDoesNotStartIncompleteOrUnavailableCodexProfiles() {
        let incomplete = profile("incomplete", token: "")
        let codex = profile("codex", executors: ["codex"])

        XCTAssertNil(pastedProfileAction(for: incomplete, runtimeAvailable: true, isActive: false) { true })
        XCTAssertNil(pastedProfileAction(for: codex, runtimeAvailable: true, isActive: false) { false })
        XCTAssertNil(pastedProfileAction(for: codex, runtimeAvailable: true, isActive: true) { false })
    }

    // MARK: - Hermes diagnosis tests

    private func hermesProfile() -> Profile {
        Profile(id: "p", label: "h", baseURL: "u", nodeID: "n", token: "t", enabledExecutors: ["hermes"])
    }
    private func hermesProbe(ok: Bool, authenticated: Bool?) -> ExecutorProbe {
        ExecutorProbe(supportedExecutors: ["codex", "acpx", "hermes"],
                      current: CurrentExecutorProbe(executor: "hermes", command: "hermes", resolvedPath: nil,
                                                    version: ok ? "0.12.0" : nil, ok: ok, error: ok ? nil : "command not found",
                                                    authenticated: authenticated),
                      candidates: [])
    }

    func testHermesMissingBlocksWithSetUp() {
        let d = diagnoseProfileStart(hermesProfile(), newbroPath: "/n", cliVersion: "9.9.9",
                                     probe: hermesProbe(ok: false, authenticated: nil), probeError: nil)
        XCTAssertEqual(d.status, .blocked)
        XCTAssertEqual(d.primaryAction, .setUpHermes)
    }

    func testHermesPresentUnauthedBlocksWithSignIn() {
        let d = diagnoseProfileStart(hermesProfile(), newbroPath: "/n", cliVersion: "9.9.9",
                                     probe: hermesProbe(ok: true, authenticated: false), probeError: nil)
        XCTAssertEqual(d.status, .blocked)
        XCTAssertEqual(d.primaryAction, .signInHermes)
    }

    func testHermesPresentAuthedOrUnknownReady() {
        for auth in [true, nil] as [Bool?] {
            let d = diagnoseProfileStart(hermesProfile(), newbroPath: "/n", cliVersion: "9.9.9",
                                         probe: hermesProbe(ok: true, authenticated: auth), probeError: nil)
            XCTAssertEqual(d.status, .ready)
        }
    }
}
