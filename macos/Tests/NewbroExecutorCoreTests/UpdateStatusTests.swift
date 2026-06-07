import XCTest
@testable import NewbroExecutorCore

final class UpdateStatusTests: XCTestCase {
    func testCLIBehind() {
        let s = updateStatus(installedCLI: "0.1.0", installedApp: "0.2.0", latestTag: "v0.2.0")
        XCTAssertEqual(s.cliUpdate, "v0.2.0")
        XCTAssertNil(s.appUpdate)
    }

    func testUnknownCLIVersionShowsUpdateWhenLatestIsKnown() {
        let s = updateStatus(installedCLI: nil, installedApp: "0.2.0", latestTag: "v0.2.0")
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
        let rows = updateSettingsRows(installedCLI: "0.1.0", installedApp: "0.1.0", status: UpdateStatus(cliUpdate: "v0.2.0", appUpdate: "v0.2.0"))
        XCTAssertEqual(rows.cliVersionRow, "Newbro CLI: v0.1.0")
        XCTAssertEqual(rows.appVersionRow, "Menu bar app: v0.1.0")
        XCTAssertEqual(rows.cliUpdateRow, "Newbro CLI update: v0.2.0 available")
        XCTAssertEqual(rows.appUpdateRow, "Menu bar app update: v0.2.0 available")
    }

    func testDevDefaultAppVersionRowExplainsLocalBuild() {
        let rows = updateSettingsRows(installedCLI: "0.1.2", installedApp: "1.0", status: UpdateStatus(cliUpdate: "v0.1.22"))
        XCTAssertEqual(rows.cliVersionRow, "Newbro CLI: v0.1.2")
        XCTAssertEqual(rows.appVersionRow, "Menu bar app: local build (bundle v1.0)")
        XCTAssertEqual(rows.cliUpdateRow, "Newbro CLI update: v0.1.22 available")
        XCTAssertNil(rows.appUpdateRow)
    }
}
