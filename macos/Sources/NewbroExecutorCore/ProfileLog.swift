import Foundation

public protocol ProfileLogging {
    func append(_ line: String)
}

public struct ProfileLog: ProfileLogging {
    private let path: URL
    private let maxLines: Int

    public init(path: URL, maxLines: Int = 200) {
        self.path = path
        self.maxLines = maxLines
    }

    public static func defaultPath(profileID: String) -> URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".newbro/logs/executor-ui-\(profileID).log")
    }

    public func append(_ line: String) {
        try? FileManager.default.createDirectory(
            at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard let data = (line + "\n").data(using: .utf8) else { return }
        if let handle = try? FileHandle(forWritingTo: path) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: path)
        }
    }

    public func recent() -> [String] {
        guard let content = try? String(contentsOf: path, encoding: .utf8) else { return [] }
        var lines = content.components(separatedBy: "\n")
        if lines.last == "" { lines.removeLast() }
        return Array(lines.suffix(maxLines))
    }
}
