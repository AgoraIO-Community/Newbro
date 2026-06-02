import XCTest
@testable import NewbroExecutorCore

final class StatusToneTests: XCTestCase {
    func testToneForEachStatus() {
        XCTAssertEqual(statusTone(.ready), .ok)
        XCTAssertEqual(statusTone(.starting), .busy)
        XCTAssertEqual(statusTone(.connecting), .busy)
        XCTAssertEqual(statusTone(.retrying), .busy)
        XCTAssertEqual(statusTone(.disconnected), .attention)
        XCTAssertEqual(statusTone(.error), .attention)
        XCTAssertEqual(statusTone(.idle), .idle)
        XCTAssertEqual(statusTone(.stopped), .idle)
    }

    func testToneOfAggregateAcrossProfiles() {
        XCTAssertEqual(statusTone(aggregateStatus([.ready, .ready])), .ok)
        XCTAssertEqual(statusTone(aggregateStatus([.ready, .error])), .attention)
        XCTAssertEqual(statusTone(aggregateStatus([.ready, .connecting])), .busy)
        XCTAssertEqual(statusTone(aggregateStatus([.stopped, .idle])), .idle)
        XCTAssertEqual(statusTone(aggregateStatus([])), .idle)
    }
}
