import Foundation

public struct CommandStatus: Equatable, Sendable {
    public let command: String?
    public let version: String?
    public let menuTitle: String
    public let isAvailable: Bool

    public init(command: String?, version: String?, menuTitle: String, isAvailable: Bool) {
        self.command = command
        self.version = version
        self.menuTitle = menuTitle
        self.isAvailable = isAvailable
    }
}

@discardableResult
public func refreshCommandStatus(_ status: inout CommandStatus,
                                 probe: () -> CommandStatus) -> CommandStatus {
    let refreshed = probe()
    status = refreshed
    return refreshed
}

public struct RuntimeLocator {
    public static let installScriptURL =
        "https://raw.githubusercontent.com/AgoraIO-Community/Newbro/main/scripts/install-newbro-cli.sh"
    public static let runtimeProbeTimeout: TimeInterval = 2.0

    private let overridePath: String?
    private let homeDir: URL
    private let fileExists: (String) -> Bool
    private let whichNewbro: () -> String?
    private let whichCommand: (String) -> String?
    private let runCommand: ([String], [String: String]?) -> (Int32, String)

    /// `overridePath` defaults to the `NEWBRO_BIN` environment variable, so a
    /// local dev build can point the app at a working-copy `newbro` (e.g. the
    /// repo's `./newbro`) by launching the app binary with `NEWBRO_BIN=…` set.
    /// It takes precedence over the installed `~/.local/bin/newbro`.
    public init(overridePath: String? = ProcessInfo.processInfo.environment["NEWBRO_BIN"],
                homeDir: URL = FileManager.default.homeDirectoryForCurrentUser,
                fileExists: @escaping (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) },
                whichNewbro: @escaping () -> String? = RuntimeLocator.loginShellWhich,
                whichCommand: @escaping (String) -> String? = RuntimeLocator.loginShellWhichCommand,
                runCommand: @escaping ([String], [String: String]?) -> (Int32, String) = RuntimeLocator.runCommandOutput) {
        self.overridePath = overridePath
        self.homeDir = homeDir
        self.fileExists = fileExists
        self.whichNewbro = whichNewbro
        self.whichCommand = whichCommand
        self.runCommand = runCommand
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

    public func codexRuntimeStatus() -> CommandStatus {
        guard let command = whichCommand("codex") else {
            return CommandStatus(
                command: nil,
                version: nil,
                menuTitle: "No Codex found. Newbro may not work properly.",
                isAvailable: false)
        }
        let result = runCommand([command, "--version"], RuntimeLocator.childEnvironment())
        let version = result.0 == 0 ? RuntimeLocator.extractVersion(result.1) : nil
        return CommandStatus(
            command: command,
            version: version,
            menuTitle: version.map { "Codex v\($0)" } ?? "Codex detected",
            isAvailable: true)
    }

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
        guard waitForProcess(proc, timeout: runtimeProbeTimeout) else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return output.isEmpty ? nil : output
    }

    public static func extractVersion(_ output: String) -> String? {
        let pattern = #"(?<![A-Za-z0-9._-])\d+(?:\.\d+)+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?(?![A-Za-z0-9._-])"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        var hasCodexLine = false
        var candidates: [String] = []
        for line in output.split(whereSeparator: \.isNewline) {
            let lineText = String(line)
            let isCodexLine = lineText.localizedCaseInsensitiveContains("codex")
            hasCodexLine = hasCodexLine || isCodexLine
            let lineRange = NSRange(lineText.startIndex..<lineText.endIndex, in: lineText)
            let lineMatches = regex.matches(in: lineText, range: lineRange).compactMap { match -> String? in
                guard let matchRange = Range(match.range, in: lineText) else { return nil }
                return String(lineText[matchRange])
            }
            guard !lineMatches.isEmpty else { continue }
            if isCodexLine {
                return lineMatches[0]
            }
            candidates.append(contentsOf: lineMatches)
        }
        if hasCodexLine { return nil }
        return candidates.count == 1 ? candidates[0] : nil
    }

    public static func loginShellWhichCommand(_ name: String) -> String? {
        guard isSafeCommandName(name) else { return nil }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
        proc.arguments = ["-lc", "command -v \(name)"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        do { try proc.run() } catch { return nil }
        guard waitForProcess(proc, timeout: runtimeProbeTimeout) else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return output.isEmpty ? nil : output
    }

    public static func runCommandOutput(_ argv: [String], _ environment: [String: String]?) -> (Int32, String) {
        runCommandOutput(argv, environment, timeout: runtimeProbeTimeout)
    }

    public static func runCommandOutput(_ argv: [String],
                                        _ environment: [String: String]?,
                                        timeout: TimeInterval) -> (Int32, String) {
        guard let executable = argv.first else { return (127, "") }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: executable)
        proc.arguments = Array(argv.dropFirst())
        if let environment { proc.environment = environment }
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        do { try proc.run() } catch { return (127, "") }
        guard waitForProcess(proc, timeout: timeout) else { return (124, "") }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return (proc.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }

    private static func isSafeCommandName(_ name: String) -> Bool {
        guard !name.isEmpty else { return false }
        return name.utf8.allSatisfy { byte in
            (65...90).contains(byte)
                || (97...122).contains(byte)
                || (48...57).contains(byte)
                || byte == 95
                || byte == 45
                || byte == 46
        }
    }

    private static func waitForProcess(_ proc: Process, timeout: TimeInterval) -> Bool {
        let semaphore = DispatchSemaphore(value: 0)
        proc.terminationHandler = { _ in semaphore.signal() }
        if !proc.isRunning { return true }
        let result = semaphore.wait(timeout: .now() + timeout)
        guard result == .success else {
            proc.terminate()
            _ = semaphore.wait(timeout: .now() + 0.2)
            if proc.isRunning {
                kill(proc.processIdentifier, SIGKILL)
                _ = semaphore.wait(timeout: .now() + 0.2)
            }
            return false
        }
        return true
    }

    /// The login shell's PATH. A menu-bar/login-item app inherits a minimal
    /// launchd PATH, so node subprocesses (and tools they exec, like the
    /// `node`-based `codex` binary) must run with the user's real PATH.
    public static func loginShellPath() -> String? {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
        proc.arguments = ["-lc", "printf %s \"$PATH\""]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
        } catch {
            return nil
        }
        guard waitForProcess(proc, timeout: runtimeProbeTimeout) else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return output.isEmpty ? nil : output
    }

    /// The current process environment with PATH replaced by the login-shell
    /// PATH (when available), suitable for launching node subprocesses.
    public static func childEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        if let shellPath = loginShellPath(), !shellPath.isEmpty {
            env["PATH"] = shellPath
        }
        return env
    }
}
