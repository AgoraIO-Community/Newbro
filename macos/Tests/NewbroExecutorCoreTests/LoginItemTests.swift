import XCTest
@testable import NewbroExecutorCore

final class LoginItemTests: XCTestCase {
    func testRenderPlistContainsLabelAndAppPath() throws {
        let item = LoginItem(plistPath: nil, appPath: "/Applications/Newbro Executor.app")
        let text = item.renderPlist()
        let data = text.data(using: .utf8)!
        let parsed = try PropertyListSerialization.propertyList(
            from: data, options: [], format: nil) as! [String: Any]
        XCTAssertEqual(parsed["Label"] as? String, LoginItem.label)
        XCTAssertEqual(parsed["RunAtLoad"] as? Bool, true)
        let args = parsed["ProgramArguments"] as? [String]
        XCTAssertEqual(args, ["/usr/bin/open", "/Applications/Newbro Executor.app"])
    }

    func testInstallThenRemove() throws {
        let plist = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("\(LoginItem.label).plist")
        let item = LoginItem(plistPath: plist, appPath: "/Applications/Newbro Executor.app")
        XCTAssertFalse(item.isInstalled)
        try item.install()
        XCTAssertTrue(item.isInstalled)
        try item.remove()
        XCTAssertFalse(item.isInstalled)
    }
}
