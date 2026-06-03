import XCTest
@testable import NewbroExecutorCore

private final class FakeProcess: NodeProcessProtocol {
    let onLine: (String) -> Void
    let onExit: (Int32) -> Void
    private(set) var started = false
    private(set) var stopped = false
    init(onLine: @escaping (String) -> Void, onExit: @escaping (Int32) -> Void) {
        self.onLine = onLine
        self.onExit = onExit
    }
    func start() { started = true }
    func stop(timeout: TimeInterval) { stopped = true }
    var isRunning: Bool { started && !stopped }
}

private final class SyncExitOnStartProcess: NodeProcessProtocol {
    private let onExit: (Int32) -> Void
    private let exitCode: Int32
    private(set) var started = false

    init(exitCode: Int32, onExit: @escaping (Int32) -> Void) {
        self.exitCode = exitCode
        self.onExit = onExit
    }

    func start() {
        started = true
        onExit(exitCode)
    }

    func stop(timeout: TimeInterval) {}
    var isRunning: Bool { false }
}

private actor LifecycleEventRecorder {
    private var processedCount = 0
    private var deliveredEvents: [ProfileLifecycleEvent] = []

    func record(_ event: ProfileLifecycleEvent, delivered: Bool) {
        processedCount += 1
        if delivered { deliveredEvents.append(event) }
    }

    func processed() -> Int { processedCount }
    func delivered() -> [ProfileLifecycleEvent] { deliveredEvents }
}

final class ProfileSupervisorTests: XCTestCase {
    private var created: [FakeProcess] = []

    private func makeSupervisor(logSink: ProfileLogging? = nil) -> ProfileSupervisor {
        created = []
        let factory = ProfileSupervisor.ProcessFactory { _, onLine, onExit in
            let fake = FakeProcess(onLine: onLine, onExit: onExit)
            self.created.append(fake)
            return fake
        }
        return ProfileSupervisor(
            processFactory: factory,
            argvBuilder: { ["run", $0.nodeID] },
            logFactory: logSink == nil ? nil : { _ in logSink })
    }

    private func profile(_ id: String = "p1", _ node: String = "node-1") -> Profile {
        Profile(id: id, label: id, baseURL: "https://x", nodeID: node, token: "t",
                enabledExecutors: ["codex"])
    }

    private func waitForProcessed(_ count: Int, recorder: LifecycleEventRecorder) async {
        for _ in 0..<50 {
            if await recorder.processed() >= count { return }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
    }

    func testStartReportsStarting() {
        let sup = makeSupervisor()
        sup.start(profile())
        XCTAssertEqual(sup.activeIDs(), Set(["p1"]))
        XCTAssertEqual(sup.status(of: "p1"), .starting)
    }

    func testLinesDriveStatusAndAggregate() {
        let sup = makeSupervisor()
        sup.start(profile())
        created[0].onLine("[ready] executor node node_id=node-1 executors=codex newbro=https://x")
        XCTAssertEqual(sup.status(of: "p1"), .ready)
        XCTAssertEqual(sup.aggregateStatus(), .ready)
    }

    func testUserStopDropsProfile() {
        let sup = makeSupervisor()
        sup.start(profile())
        sup.stop("p1")
        created[0].onExit(0)
        XCTAssertTrue(created[0].stopped)
        XCTAssertEqual(sup.activeIDs(), [])
    }

    func testUnexpectedExitKeepsRecordAsError() {
        let sup = makeSupervisor()
        sup.start(profile())
        created[0].onExit(1)
        XCTAssertEqual(sup.status(of: "p1"), .error)
        XCTAssertEqual(sup.activeIDs(), Set(["p1"]))
    }

    func testStopAllStopsEveryProcess() {
        let sup = makeSupervisor()
        sup.start(profile("p1", "node-1"))
        sup.start(profile("p2", "node-2"))
        sup.stopAll()
        XCTAssertTrue(created.allSatisfy { $0.stopped })
    }

    func testStopOnErroredProfileDropsRecord() {
        let sup = makeSupervisor()
        sup.start(profile())
        created[0].onExit(1)  // unexpected exit → error, record kept for the UI
        XCTAssertEqual(sup.status(of: "p1"), .error)
        XCTAssertEqual(sup.activeIDs(), Set(["p1"]))
        sup.stop("p1")        // process already exited → record reclaimed now
        XCTAssertEqual(sup.activeIDs(), [])
    }

    func testLogFactoryReceivesLines() {
        final class FakeLog: ProfileLogging {
            private(set) var lines: [String] = []
            func append(_ line: String) { lines.append(line) }
        }
        let sink = FakeLog()
        let sup = makeSupervisor(logSink: sink)
        sup.start(profile())
        created[0].onLine("[ready] go")
        XCTAssertEqual(sink.lines, ["[ready] go"])
    }

    func testLifecycleEventsForStartStopAndError() {
        var events: [ProfileLifecycleEvent] = []
        created = []
        let factory = ProfileSupervisor.ProcessFactory { _, onLine, onExit in
            let fake = FakeProcess(onLine: onLine, onExit: onExit)
            self.created.append(fake)
            return fake
        }
        let sup = ProfileSupervisor(
            processFactory: factory,
            argvBuilder: { ["run", $0.nodeID] },
            onEvent: { events.append($0) })

        let p = profile()
        sup.start(p)
        XCTAssertEqual(events, [.started(profileID: "p1", label: "p1")])
        sup.stop("p1")
        created[0].onExit(0)
        XCTAssertEqual(events.last, .stopped(profileID: "p1", label: "p1"))

        sup.start(p)
        created[1].onExit(1)
        XCTAssertEqual(events.last, .error(profileID: "p1", label: "p1", exitCode: 1))
    }

    func testLifecycleEventsEmitStartedBeforeSynchronousLaunchFailureExit() {
        var events: [ProfileLifecycleEvent] = []
        let factory = ProfileSupervisor.ProcessFactory { _, _, onExit in
            SyncExitOnStartProcess(exitCode: 127, onExit: onExit)
        }
        let sup = ProfileSupervisor(
            processFactory: factory,
            argvBuilder: { ["run", $0.nodeID] },
            onEvent: { events.append($0) })

        sup.start(profile())

        XCTAssertEqual(events, [
            .started(profileID: "p1", label: "p1"),
            .error(profileID: "p1", label: "p1", exitCode: 127)
        ])
    }

    func testLifecycleEventSuppressionForPasteRestart() {
        let suppression = ProfileLifecycleEventSuppression()
        suppression.suppressNextRestart(profileID: "p1")

        XCTAssertTrue(suppression.shouldSuppress(.stopped(profileID: "p1", label: "p1")))
        XCTAssertTrue(suppression.shouldSuppress(.started(profileID: "p1", label: "p1")))

        XCTAssertFalse(suppression.shouldSuppress(.stopped(profileID: "p1", label: "p1")))
        XCTAssertFalse(suppression.shouldSuppress(.started(profileID: "p1", label: "p1")))
    }

    func testLifecycleEventSuppressionKeepsOtherLifecycleEvents() {
        let suppression = ProfileLifecycleEventSuppression()
        suppression.suppressNextRestart(profileID: "p1")

        XCTAssertFalse(suppression.shouldSuppress(.stopped(profileID: "p2", label: "p2")))
        XCTAssertFalse(suppression.shouldSuppress(.error(profileID: "p1", label: "p1", exitCode: 1)))
        XCTAssertTrue(suppression.shouldSuppress(.stopped(profileID: "p1", label: "p1")))
        XCTAssertTrue(suppression.shouldSuppress(.started(profileID: "p1", label: "p1")))
    }

    func testLifecycleEventSuppressionDoesNotLeakWhenRestartStopEventIsMissing() {
        let suppression = ProfileLifecycleEventSuppression()
        suppression.suppressNextRestart(profileID: "p1")

        XCTAssertTrue(suppression.shouldSuppress(.started(profileID: "p1", label: "p1")))
        XCTAssertFalse(suppression.shouldSuppress(.stopped(profileID: "p1", label: "p1")))
    }

    func testLifecycleEventRelayProcessesRestartSuppressionInEnqueueOrder() async {
        let suppression = ProfileLifecycleEventSuppression()
        suppression.suppressNextRestart(profileID: "p1")
        let recorder = LifecycleEventRecorder()
        let relay = ProfileLifecycleEventRelay { event in
            let delivered = !suppression.shouldSuppress(event)
            await recorder.record(event, delivered: delivered)
        }

        relay.enqueue(.stopped(profileID: "p1", label: "p1"))
        relay.enqueue(.started(profileID: "p1", label: "p1"))

        await waitForProcessed(2, recorder: recorder)
        let processed = await recorder.processed()
        let delivered = await recorder.delivered()
        XCTAssertEqual(processed, 2)
        XCTAssertEqual(delivered, [])
    }
}
