import XCTest
@testable import NewbroExecutorCore

final class MaintenanceOperationTests: XCTestCase {
    func testRuntimeInstallCompletionSucceedsOnlyWhenRuntimeIsAvailable() {
        let completion = runtimeInstallCompletion(exitCode: 0, runtimeAvailable: true)

        XCTAssertNil(completion.errorRow)
        XCTAssertEqual(completion.notificationTitle, "Runtime installed")
        XCTAssertEqual(completion.notificationBody, "Newbro runtime is ready.")
    }

    func testRuntimeInstallCompletionFailsWhenInstallerExitsNonZero() {
        let completion = runtimeInstallCompletion(exitCode: 7, runtimeAvailable: false)

        XCTAssertEqual(completion.errorRow, "Runtime install failed (exit 7).")
        XCTAssertEqual(completion.notificationTitle, "Runtime install failed")
        XCTAssertEqual(completion.notificationBody, "Exit 7.")
    }

    func testRuntimeInstallCompletionFailsWhenRuntimeIsStillMissing() {
        let completion = runtimeInstallCompletion(exitCode: 0, runtimeAvailable: false)

        XCTAssertEqual(completion.errorRow, "Runtime install finished, but Newbro is still unavailable.")
        XCTAssertEqual(completion.notificationTitle, "Runtime install failed")
        XCTAssertEqual(completion.notificationBody, "Newbro runtime is still unavailable.")
    }
}
