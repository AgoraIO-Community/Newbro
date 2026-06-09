import Foundation

public struct ExecutorProbe: Codable, Equatable, Sendable {
    public var supportedExecutors: [String]
    public var current: CurrentExecutorProbe
    public var candidates: [ExecutorCandidateProbe]

    enum CodingKeys: String, CodingKey {
        case supportedExecutors = "supported_executors"
        case current
        case candidates
    }
}

public struct CurrentExecutorProbe: Codable, Equatable, Sendable {
    public var executor: String
    public var command: String
    public var resolvedPath: String?
    public var version: String?
    public var ok: Bool
    public var error: String?
    public var authenticated: Bool?

    enum CodingKeys: String, CodingKey {
        case executor, command, version, ok, error, authenticated
        case resolvedPath = "resolved_path"
    }
}

public struct ExecutorCandidateProbe: Codable, Equatable, Identifiable, Sendable {
    public var path: String
    public var version: String?
    public var ok: Bool
    public var source: String
    public var error: String?
    public var isCurrent: Bool

    public var id: String { path }

    enum CodingKeys: String, CodingKey {
        case path, version, ok, source, error
        case isCurrent = "is_current"
    }
}

public enum ExecutorSettingsClientError: Error, Equatable, Sendable {
    case emptyOutput
    case commandFailed(status: Int32, output: String)
    case runtimeTooOld(installedVersion: String?)
}

extension ExecutorSettingsClientError: LocalizedError {
    public var errorDescription: String? {
        switch self {
        case .emptyOutput:
            return "Newbro CLI returned no output."
        case .commandFailed(let status, let output):
            let trimmed = output.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty {
                return "Newbro CLI command failed (exit \(status))."
            }
            return "Newbro CLI command failed (exit \(status)): \(trimmed)"
        case .runtimeTooOld:
            return "Codex settings require a newer Newbro CLI. Update CLI, then reopen Settings."
        }
    }
}

public final class ExecutorSettingsClient: @unchecked Sendable {
    public typealias Runner = (_ argv: [String], _ environment: [String: String]?) throws -> String

    private let newbroPath: String
    private let environment: [String: String]?
    private let runner: Runner

    public init(newbroPath: String,
                environment: [String: String]? = RuntimeLocator.childEnvironment(),
                runner: @escaping Runner = ExecutorSettingsClient.runProcess) {
        self.newbroPath = newbroPath
        self.environment = environment
        self.runner = runner
    }

    public func probe(executor: String = "codex") throws -> ExecutorProbe {
        let output: String
        do {
            output = try runner([newbroPath, "executor", "probe", "--executor", executor, "--json"], environment)
        } catch let error as ExecutorSettingsClientError {
            if error.isUnsupportedProbeSubcommand {
                throw ExecutorSettingsClientError.runtimeTooOld(installedVersion: installedVersion())
            }
            throw error
        }
        guard !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ExecutorSettingsClientError.emptyOutput
        }
        return try JSONDecoder().decode(ExecutorProbe.self, from: Data(output.utf8))
    }

    public func useCodex(path: String) throws {
        _ = try runner([newbroPath, "executor", "use", "--executor", "codex", "--command", path], environment)
    }

    public func installCodex() throws -> String {
        do {
            return try runner([newbroPath, "executor", "install-codex"], environment)
        } catch let error as ExecutorSettingsClientError {
            if error.isUnsupportedInstallCodexSubcommand {
                throw ExecutorSettingsClientError.runtimeTooOld(installedVersion: installedVersion())
            }
            throw error
        }
    }

    public func installCodexStreaming(onLine: @escaping @Sendable (String) -> Void) throws -> String {
        do {
            return try Self.runProcessStreaming(
                argv: [newbroPath, "executor", "install-codex"],
                environment: environment,
                onLine: onLine
            )
        } catch let error as ExecutorSettingsClientError {
            if error.isUnsupportedInstallCodexSubcommand {
                throw ExecutorSettingsClientError.runtimeTooOld(installedVersion: installedVersion())
            }
            throw error
        }
    }

    public func useHermes(path: String) throws {
        _ = try runner([newbroPath, "executor", "use", "--executor", "hermes", "--command", path], environment)
    }

    public func installHermes() throws -> String {
        try runner([newbroPath, "executor", "install-hermes"], environment)
    }

    public func installHermesStreaming(onLine: @escaping @Sendable (String) -> Void) throws -> String {
        try Self.runProcessStreaming(argv: [newbroPath, "executor", "install-hermes"], environment: environment, onLine: onLine)
    }

    private func installedVersion() -> String? {
        guard let output = try? runner([newbroPath, "--version"], environment) else { return nil }
        let trimmed = output.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.split(separator: " ").last.map(String.init)
    }

    public static func runProcess(argv: [String], environment: [String: String]?) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: argv[0])
        process.arguments = Array(argv.dropFirst())
        if let environment { process.environment = environment }
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let output = String(data: data, encoding: .utf8) ?? ""
        if process.terminationStatus != 0 {
            throw ExecutorSettingsClientError.commandFailed(
                status: process.terminationStatus,
                output: output
            )
        }
        return output
    }

    public static func runProcessStreaming(argv: [String],
                                           environment: [String: String]?,
                                           onLine: @escaping @Sendable (String) -> Void) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: argv[0])
        process.arguments = Array(argv.dropFirst())
        if let environment { process.environment = environment }

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        let lock = NSLock()
        var output = Data()
        var pending = Data()

        func drainLines(final: Bool = false) {
            while let newline = pending.firstIndex(of: 10) {
                let lineData = pending[..<newline]
                pending.removeSubrange(...newline)
                let line = String(data: lineData, encoding: .utf8) ?? ""
                onLine(line)
            }
            if final, !pending.isEmpty {
                let line = String(data: pending, encoding: .utf8) ?? ""
                pending.removeAll()
                onLine(line)
            }
        }

        pipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            lock.lock()
            output.append(data)
            pending.append(data)
            drainLines()
            lock.unlock()
        }

        do {
            try process.run()
            process.waitUntilExit()
            pipe.fileHandleForReading.readabilityHandler = nil
            lock.lock()
            drainLines(final: true)
            let finalOutput = String(data: output, encoding: .utf8) ?? ""
            lock.unlock()
            if process.terminationStatus != 0 {
                throw ExecutorSettingsClientError.commandFailed(
                    status: process.terminationStatus,
                    output: finalOutput
                )
            }
            return finalOutput
        } catch {
            pipe.fileHandleForReading.readabilityHandler = nil
            throw error
        }
    }
}

private extension ExecutorSettingsClientError {
    var isUnsupportedProbeSubcommand: Bool {
        isUnsupportedExecutorSubcommand("probe")
    }

    var isUnsupportedInstallCodexSubcommand: Bool {
        isUnsupportedExecutorSubcommand("install-codex")
    }

    func isUnsupportedExecutorSubcommand(_ name: String) -> Bool {
        guard case .commandFailed(_, let output) = self else { return false }
        return output.contains("executor_command: invalid choice: '\(name)'")
    }
}
