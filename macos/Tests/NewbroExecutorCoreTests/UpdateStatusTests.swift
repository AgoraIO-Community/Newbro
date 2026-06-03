import XCTest
@testable import NewbroExecutorCore

final class UpdateStatusTests: XCTestCase {
    func testCLIBehind() {
        let s = updateStatus(installedCLI: "0.1.0", installedApp: "0.2.0", latestTag: "v0.2.0")
        XCTAssertEqual(s.cliUpdate, "v0.2.0")
        XCTAssertNil(s.appUpdate)
    }

    func testAppBehind() {
        let s = updateStatus(installedCLI: "0.2.0", installedApp: "0.1.0", latestTag: "v0.2.0")
        XCTAssertNil(s.cliUpdate)
        XCTAssertEqual(s.appUpdate, "v0.2.0")
    }

    func testBothCurrent() {
        let s = updateStatus(installedCLI: "0.2.0", installedApp: "0.2.0", latestTag: "v0.2.0")
        XCTAssertNil(s.cliUpdate)
        XCTAssertNil(s.appUpdate)
    }

    func testDevDefaultAppVersionSuppressed() {
        let s = updateStatus(installedCLI: "0.2.0", installedApp: "1.0", latestTag: "v0.2.0")
        XCTAssertNil(s.appUpdate)
    }

    func testUnparseableInputsNoFalsePositive() {
        XCTAssertEqual(updateStatus(installedCLI: nil, installedApp: nil, latestTag: nil), UpdateStatus())
        XCTAssertEqual(updateStatus(installedCLI: "abc", installedApp: "x", latestTag: "v0.2.0"), UpdateStatus())
    }

    func testComponentVersionRows() {
        let rows = updateMenuRows(installedCLI: "0.1.0", installedApp: "0.1.0", status: UpdateStatus(cliUpdate: "v0.2.0", appUpdate: "v0.2.0"))
        XCTAssertEqual(rows.cliVersionRow, "newbro CLI v0.1.0")
        XCTAssertEqual(rows.appVersionRow, "App v0.1.0")
        XCTAssertEqual(rows.cliUpdateRow, "CLI update available: v0.2.0")
        XCTAssertEqual(rows.appUpdateRow, "App update available: v0.2.0")
    }
}
