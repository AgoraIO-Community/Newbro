import Foundation

struct MenubarFile: Codable {
    var version: Int
    var profiles: [Profile]
}

public struct ProfileStore {
    private let path: URL

    public init(path: URL = ProfileStore.defaultPath) {
        self.path = path
    }

    public static var defaultPath: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".newbro/menubar.json")
    }

    public func load() -> [Profile] {
        guard let data = try? Data(contentsOf: path),
              let file = try? JSONDecoder().decode(MenubarFile.self, from: data)
        else { return [] }
        return file.profiles
    }

    public func save(_ profiles: [Profile]) throws {
        try FileManager.default.createDirectory(
            at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(MenubarFile(version: 1, profiles: profiles))
        try data.write(to: path)
    }
}
