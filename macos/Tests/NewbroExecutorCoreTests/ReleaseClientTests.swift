import XCTest
@testable import NewbroExecutorCore

final class ReleaseClientTests: XCTestCase {
    func testDecodesTagAndPageURL() async throws {
        let json = """
        {
          "tag_name": "v0.2.0",
          "html_url": "https://github.com/AgoraIO/Synopse/releases/tag/v0.2.0",
          "assets": [
            {"name": "NewbroExecutor-0.2.0-arm64.dmg",
             "browser_download_url": "https://example.com/a.dmg"}
          ]
        }
        """
        let client = ReleaseClient(fetch: { _ in Data(json.utf8) })
        let info = try await client.latest()
        XCTAssertEqual(info.tag, "v0.2.0")
        XCTAssertEqual(info.pageURL,
                       URL(string: "https://github.com/AgoraIO/Synopse/releases/tag/v0.2.0"))
    }

    func testMissingHTMLURLIsNil() async throws {
        let client = ReleaseClient(fetch: { _ in Data(#"{"tag_name":"v0.3.0"}"#.utf8) })
        let info = try await client.latest()
        XCTAssertEqual(info.tag, "v0.3.0")
        XCTAssertNil(info.pageURL)
    }

    func testLatestURLUsesCommunityNewbroRepository() {
        XCTAssertEqual(
            ReleaseClient.latestURL.absoluteString,
            "https://api.github.com/repos/AgoraIO-Community/Newbro/releases/latest")
    }
}
