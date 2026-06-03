import Foundation

/// The latest release info the app needs.
public struct ReleaseInfo: Equatable, Sendable {
    public let tag: String
    public let pageURL: URL?
    public init(tag: String, pageURL: URL?) {
        self.tag = tag
        self.pageURL = pageURL
    }
}

/// Reads the latest published release from the public GitHub API. The network
/// fetch is injected so decoding is unit-testable.
public struct ReleaseClient {
    public static let latestURL = URL(string:
        "https://api.github.com/repos/AgoraIO-Community/Newbro/releases/latest")!

    private let fetch: (URLRequest) async throws -> Data

    public init(fetch: @escaping (URLRequest) async throws -> Data = ReleaseClient.defaultFetch) {
        self.fetch = fetch
    }

    public func latest() async throws -> ReleaseInfo {
        var request = URLRequest(url: ReleaseClient.latestURL)
        // GitHub requires a User-Agent; Accept pins the API version.
        request.setValue("NewbroExecutor", forHTTPHeaderField: "User-Agent")
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        let data = try await fetch(request)
        let decoded = try JSONDecoder().decode(GitHubRelease.self, from: data)
        return ReleaseInfo(tag: decoded.tag_name,
                           pageURL: decoded.html_url.flatMap { URL(string: $0) })
    }

    public static func defaultFetch(_ request: URLRequest) async throws -> Data {
        try await URLSession.shared.data(for: request).0
    }

    private struct GitHubRelease: Decodable {
        let tag_name: String
        let html_url: String?
    }
}
