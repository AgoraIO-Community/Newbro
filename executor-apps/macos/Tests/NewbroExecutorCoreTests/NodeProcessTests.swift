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

    func testAllLinesDeliveredBeforeExit() {
        // Regression: onLine must never fire after onExit. The reader queue
        // delivers every line, then reports exit, on one serial queue.
        let events = Box<[String]>([])
        let exited = expectation(description: "exited")
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "printf '[start] a\\n[ready] b\\n'; exit 0"],
            onLine: { line in events.mutate { $0.append("line:\(line)") } },
            onExit: { _ in events.mutate { $0.append("exit") }; exited.fulfill() }
        )
        proc.start()
        wait(for: [exited], timeout: 10)
        let recorded = events.value
        XCTAssertEqual(recorded.last, "exit")
        let exitIndex = recorded.firstIndex(of: "exit")!
        XCTAssertTrue(recorded[..<exitIndex].allSatisfy { $0.hasPrefix("line:") })
        XCTAssertEqual(recorded.filter { $0.hasPrefix("line:") }.count, 2)
    }

    func testLaunchFailureReportsExit() {
        let code = Box<Int32>(0)
        let exited = expectation(description: "exited")
        let proc = NodeProcess(
            argv: ["/nonexistent/definitely-not-here", "arg"],
            onLine: { _ in },
            onExit: { c in code.mutate { $0 = c }; exited.fulfill() }
        )
        proc.start()
        wait(for: [exited], timeout: 10)
        XCTAssertEqual(code.value, 127)
        XCTAssertFalse(proc.isRunning)
    }

    func testStopDeliversExitBeforeReturning() {
        // After stop() returns, onExit must already have fired, so restart can
        // safely start a fresh run without racing a late exit callback.
        let exitedFlag = Box<Bool>(false)
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "printf '[start] up\\n'; while true; do sleep 0.1; done"],
            onLine: { _ in },
            onExit: { _ in exitedFlag.mutate { $0 = true } }
        )
        proc.start()
        let deadline = Date().addingTimeInterval(5)
        while !proc.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.02) }
        proc.stop()
        XCTAssertTrue(exitedFlag.value)
        XCTAssertFalse(proc.isRunning)
    }

    func testHonorsCustomEnvironment() {
        // The menu-bar app launches with a minimal PATH; it must be able to
        // override the child's environment (so e.g. `node`/`codex` resolve).
        let lines = Box<[String]>([])
        let exited = expectation(description: "exited")
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "printf 'PATHIS=%s\\n' \"$PATH\""],
            environment: ["PATH": "/custom/bin:/usr/bin"],
            onLine: { line in lines.mutate { $0.append(line) } },
            onExit: { _ in exited.fulfill() }
        )
        proc.start()
        wait(for: [exited], timeout: 10)
        XCTAssertTrue(lines.value.contains("PATHIS=/custom/bin:/usr/bin"))
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
