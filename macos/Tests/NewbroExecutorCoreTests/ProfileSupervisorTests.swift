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
}
