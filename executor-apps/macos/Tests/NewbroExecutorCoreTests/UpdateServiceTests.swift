import XCTest
@testable import NewbroExecutorCore

@MainActor
final class UpdateServiceTests: XCTestCase {
    private func make(order: ActorRef, installerExit: Int32 = 0,
                      latest: ReleaseInfo? = ReleaseInfo(tag: "v0.2.0", pageURL: nil),
                      cli: String? = "0.1.0", app: String? = "1.0",
                      onEvent: @escaping @MainActor (UpdateServiceEvent) -> Void = { _ in }) -> UpdateService {
        UpdateService(
            fetchLatest: { latest },
            installedCLIVersion: { cli },
            appVersion: { app },
            activeProfileIDs: { ["a", "b"] },
            stopProfile: { id in order.append("stop:\(id)") },
            startProfile: { id in order.append("start:\(id)") },
            runInstaller: { completion in order.append("install"); completion(installerExit) },
            onEvent: onEvent)
    }

    func testCheckComputesStatusAndReleaseURL() async {
        let svc = make(order: ActorRef(),
                       latest: ReleaseInfo(tag: "v0.2.0",
                                           pageURL: URL(string: "https://x/rel")))
        await svc.check()
        XCTAssertEqual(svc.status.cliUpdate, "v0.2.0")
        XCTAssertNil(svc.status.appUpdate)            // app "1.0" suppressed
        XCTAssertEqual(svc.releasePageURL, URL(string: "https://x/rel"))
        XCTAssertNil(svc.lastError)
    }

    func testCheckNetworkFailureSetsError() async {
        let svc = make(order: ActorRef(), latest: nil)
        await svc.check()
        XCTAssertNotNil(svc.lastError)
    }

    func testCheckStaysBusyUntilFetchCompletes() async {
        let gate = FetchGate()
        let svc = UpdateService(
            fetchLatest: { await gate.fetch() },
            installedCLIVersion: { "0.1.0" },
            appVersion: { "1.0" },
            activeProfileIDs: { [] },
            stopProfile: { _ in },
            startProfile: { _ in },
            runInstaller: { _ in })

        let task = Task { await svc.check() }
        await gate.waitUntilStarted()
        XCTAssertTrue(svc.isChecking)
        await gate.finish()
        await task.value
        XCTAssertFalse(svc.isChecking)
        XCTAssertNil(svc.lastError)
    }

    func testUpdateCLIStopsUpdatesRestartsInOrder() {
        let order = ActorRef()
        let svc = make(order: order, installerExit: 0)
        svc.updateCLI()
        XCTAssertEqual(order.values, ["stop:a", "stop:b", "install", "start:a", "start:b"])
        XCTAssertFalse(svc.isUpdating)
    }

    func testUpdateCLIRestartsEvenWhenInstallerFails() {
        let order = ActorRef()
        let svc = make(order: order, installerExit: 1)
        svc.updateCLI()
        XCTAssertEqual(order.values, ["stop:a", "stop:b", "install", "start:a", "start:b"])
        XCTAssertNotNil(svc.lastError)
    }

    func testUpdateCLIStaysBusyUntilInstallerCompletes() {
        let order = ActorRef()
        var completion: (@MainActor (Int32) -> Void)?
        let svc = UpdateService(
            fetchLatest: { ReleaseInfo(tag: "v0.2.0", pageURL: nil) },
            installedCLIVersion: { "0.1.0" },
            appVersion: { "1.0" },
            activeProfileIDs: { ["a"] },
            stopProfile: { id in order.append("stop:\(id)") },
            startProfile: { id in order.append("start:\(id)") },
            runInstaller: { installerCompletion in
                order.append("install")
                completion = installerCompletion
            },
            onEvent: { _ in })

        svc.updateCLI()
        svc.updateCLI()

        XCTAssertTrue(svc.isUpdating)
        XCTAssertEqual(order.values, ["stop:a", "install"])
        completion?(0)
        XCTAssertFalse(svc.isUpdating)
        XCTAssertEqual(order.values, ["stop:a", "install", "start:a"])
    }

    func testUpdateCLIEmitsCompletionEvents() {
        let successOrder = ActorRef()
        var successEvents: [UpdateServiceEvent] = []
        let success = make(order: successOrder, installerExit: 0) { event in
            successEvents.append(event)
        }

        success.updateCLI()

        XCTAssertEqual(successEvents, [.cliUpdateSucceeded(restartedProfileCount: 2)])

        let failureOrder = ActorRef()
        var failureEvents: [UpdateServiceEvent] = []
        let failure = make(order: failureOrder, installerExit: 7) { event in
            failureEvents.append(event)
        }

        failure.updateCLI()

        XCTAssertEqual(failureEvents, [.cliUpdateFailed(exitCode: 7, restartedProfileCount: 2)])
    }
}

/// Simple ordered recorder for the fakes.
@MainActor
final class ActorRef {
    private(set) var values: [String] = []
    func append(_ s: String) { values.append(s) }
}

actor FetchGate {
    private var started = false
    private var startedContinuations: [CheckedContinuation<Void, Never>] = []
    private var finishContinuation: CheckedContinuation<Void, Never>?

    func fetch() async -> ReleaseInfo? {
        started = true
        for continuation in startedContinuations {
            continuation.resume()
        }
        startedContinuations.removeAll()
        await withCheckedContinuation { continuation in
            finishContinuation = continuation
        }
        return ReleaseInfo(tag: "v0.2.0", pageURL: nil)
    }

    func waitUntilStarted() async {
        if started { return }
        await withCheckedContinuation { continuation in
            startedContinuations.append(continuation)
        }
    }

    func finish() {
        finishContinuation?.resume()
        finishContinuation = nil
    }
}
