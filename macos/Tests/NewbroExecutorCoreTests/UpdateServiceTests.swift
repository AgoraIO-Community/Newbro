import XCTest
@testable import NewbroExecutorCore

@MainActor
final class UpdateServiceTests: XCTestCase {
    private func make(order: ActorRef, installerExit: Int32 = 0,
                      latest: ReleaseInfo? = ReleaseInfo(tag: "v0.2.0", pageURL: nil),
                      cli: String? = "0.1.0", app: String? = "1.0") -> UpdateService {
        UpdateService(
            fetchLatest: { latest },
            installedCLIVersion: { cli },
            appVersion: { app },
            activeProfileIDs: { ["a", "b"] },
            stopProfile: { id in order.append("stop:\(id)") },
            startProfile: { id in order.append("start:\(id)") },
            runInstaller: { completion in order.append("install"); completion(installerExit) })
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
}

/// Simple ordered recorder for the fakes.
@MainActor
final class ActorRef {
    private(set) var values: [String] = []
    func append(_ s: String) { values.append(s) }
}
