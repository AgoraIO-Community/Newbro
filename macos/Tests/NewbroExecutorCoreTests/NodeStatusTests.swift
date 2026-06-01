import XCTest
@testable import NewbroExecutorCore

final class NodeStatusTests: XCTestCase {
    func testConnectToReady() {
        let p = StatusParser()
        p.onStart()
        p.onLine("[start] executor node node_id=n executors=codex newbro=https://x")
        p.onLine("[connect] executor node attempt=1 url=wss://x")
        p.onLine("[ready] executor node node_id=n executors=codex newbro=https://x")
        XCTAssertEqual(p.status, .ready)
    }

    func testDisconnectAndRetry() {
        let p = StatusParser()
        p.onLine("[ready] executor node node_id=n executors=codex newbro=https://x")
        p.onLine("[warn] executor node disconnected=ConnectionClosed url=wss://x")
        XCTAssertEqual(p.status, .disconnected)
        p.onLine("[retry] executor node retrying in 2.0s")
        XCTAssertEqual(p.status, .retrying)
    }

    func testConnectFailedStaysConnecting() {
        let p = StatusParser()
        p.onLine("[connect] executor node attempt=1 url=wss://x")
        p.onLine("[warn] executor node attempt=1 connect_failed=Timeout url=wss://x")
        XCTAssertEqual(p.status, .connecting)
    }

    func testExitExpectedStoppedUnexpectedError() {
        let a = StatusParser(); a.onStart()
        XCTAssertEqual(a.onExit(code: 0, expected: true), .stopped)
        let b = StatusParser(); b.onStart()
        XCTAssertEqual(b.onExit(code: 1, expected: false), .error)
    }

    func testAggregatePriority() {
        XCTAssertEqual(aggregateStatus([.ready, .error]), .error)
        XCTAssertEqual(aggregateStatus([.ready, .connecting]), .connecting)
        XCTAssertEqual(aggregateStatus([.ready, .stopped]), .ready)
        XCTAssertEqual(aggregateStatus([.stopped, .idle]), .idle)
        XCTAssertEqual(aggregateStatus([]), .idle)
    }
}
