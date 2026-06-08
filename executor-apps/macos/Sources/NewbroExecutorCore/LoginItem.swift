import Foundation

public struct LoginItem {
    public static let label = "com.newbro.executor-ui"

    private let plistPath: URL
    private let appPath: String

    public init(plistPath: URL? = nil, appPath: String) {
        self.plistPath = plistPath ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(LoginItem.label).plist")
        self.appPath = appPath
    }

    public func renderPlist() -> String {
        let dict: [String: Any] = [
            "Label": LoginItem.label,
            "ProgramArguments": ["/usr/bin/open", appPath],
            "RunAtLoad": true,
        ]
        let data = (try? PropertyListSerialization.data(
            fromPropertyList: dict, format: .xml, options: 0)) ?? Data()
        return String(data: data, encoding: .utf8) ?? ""
    }

    public var isInstalled: Bool {
        FileManager.default.fileExists(atPath: plistPath.path)
    }

    public func install() throws {
        let plist = renderPlist()
        guard !plist.isEmpty, let data = plist.data(using: .utf8) else {
            throw CocoaError(.propertyListWriteStream)
        }
        try FileManager.default.createDirectory(
            at: plistPath.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: plistPath)
    }

    public func remove() throws {
        if isInstalled { try FileManager.default.removeItem(at: plistPath) }
    }
}
