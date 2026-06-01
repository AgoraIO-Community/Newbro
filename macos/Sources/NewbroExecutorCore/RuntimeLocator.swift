import Foundation

public struct RuntimeLocator {
    public static let installScriptURL =
        "https://raw.githubusercontent.com/AgoraIO-Community/Newbro/main/scripts/install-newbro-cli.sh"

    private let overridePath: String?
    private let homeDir: URL
    private let fileExists: (String) -> Bool
    private let whichNewbro: () -> String?

    public init(overridePath: String? = nil,
                homeDir: URL = FileManager.default.homeDirectoryForCurrentUser,
                fileExists: @escaping (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) },
                whichNewbro: @escaping () -> String? = RuntimeLocator.loginShellWhich) {
        self.overridePath = overridePath
        self.homeDir = homeDir
        self.fileExists = fileExists
        self.whichNewbro = whichNewbro
    }

    public func resolveNewbro() -> String? {
        if let override = overridePath, !override.isEmpty, fileExists(override) {
            return override
        }
        let uvPath = homeDir.appendingPathComponent(".local/bin/newbro").path
        if fileExists(uvPath) { return uvPath }
        if let viaShell = whichNewbro(), fileExists(viaShell) { return viaShell }
        return nil
    }

    public var isRuntimeAvailable: Bool { resolveNewbro() != nil }

    public func candidatePaths() -> [String] {
        var paths: [String] = []
        if let override = overridePath, !override.isEmpty { paths.append(override) }
        paths.append(homeDir.appendingPathComponent(".local/bin/newbro").path)
        return paths
    }

    public func nodeArgv(for profile: Profile) -> [String]? {
        guard let newbro = resolveNewbro() else { return nil }
        var argv = [newbro, "executor", "run",
                    "--base-url", profile.baseURL,
                    "--node-id", profile.nodeID,
                    "--token", profile.token]
        for executor in profile.enabledExecutors {
            argv.append(contentsOf: ["--enabled-executor", executor])
        }
        return argv
    }

    public func installCommandArgv() -> [String] {
        ["/bin/sh", "-c", "curl -fsSL \(RuntimeLocator.installScriptURL) | sh"]
    }

    public static func loginShellWhich() -> String? {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
        proc.arguments = ["-lc", "command -v newbro"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
        } catch {
            return nil
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        let output = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return output.isEmpty ? nil : output
    }
}
