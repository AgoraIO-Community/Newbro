import XCTest
@testable import NewbroExecutorCore

private final class Box<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: T
    init(_ value: T) { stored = value }
    var value: T { lock.lock(); defer { lock.unlock() }; return stored }
    func mutate(_ change: (inout T) -> Void) { lock.lock(); change(&stored); lock.unlock() }
}

final class NodeProcessTests: XCTestCase {
    func testCapturesLinesAndExitCode() {
        let lines = Box<[String]>([])
        let code = Box<Int32>(-1)
        let exited = expectation(description: "exited")
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "printf '[start] hi\\n[ready] go\\n'; exit 0"],
            onLine: { line in lines.mutate { $0.append(line) } },
            onExit: { c in code.mutate { $0 = c }; exited.fulfill() }
        )
        proc.start()
        wait(for: [exited], timeout: 10)
        XCTAssertTrue(lines.value.contains("[start] hi"))
        XCTAssertTrue(lines.value.contains("[ready] go"))
        XCTAssertEqual(code.value, 0)
    }

    func testStopTerminatesLongRunner() {
        let started = expectation(description: "started")
        started.assertForOverFulfill = false
        let exited = expectation(description: "exited")
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "printf '[start] up\\n'; while true; do sleep 0.1; done"],
            onLine: { _ in started.fulfill() },
            onExit: { _ in exited.fulfill() }
        )
        proc.start()
        wait(for: [started], timeout: 10)
        XCTAssertTrue(proc.isRunning)
        proc.stop()
        wait(for: [exited], timeout: 10)
        XCTAssertFalse(proc.isRunning)
    }
}
