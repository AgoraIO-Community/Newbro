import Foundation

public protocol NodeProcessProtocol: AnyObject {
    func start()
    func stop(timeout: TimeInterval)
    var isRunning: Bool { get }
}

public final class NodeProcess: NodeProcessProtocol {
    private let argv: [String]
    private let onLine: (String) -> Void
    private let onExit: (Int32) -> Void
    private var process: Process?
    private let queue = DispatchQueue(label: "newbro.node-process")
    private var buffer = Data()

    public init(argv: [String],
                onLine: @escaping (String) -> Void,
                onExit: @escaping (Int32) -> Void) {
        self.argv = argv
        self.onLine = onLine
        self.onExit = onExit
    }

    public var isRunning: Bool { process?.isRunning ?? false }

    public func start() {
        guard process == nil, !argv.isEmpty else { return }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: argv[0])
        proc.arguments = Array(argv.dropFirst())
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        process = proc
        do {
            try proc.run()
        } catch {
            process = nil
            onExit(127)
            return
        }
        // A single serial reader owns all output consumption and the exit
        // report. Reading to EOF, flushing, then waiting and calling onExit on
        // the same queue guarantees every onLine is delivered strictly before
        // onExit — no readabilityHandler/terminationHandler race.
        let handle = pipe.fileHandleForReading
        queue.async { [weak self] in
            while true {
                let data = handle.availableData
                if data.isEmpty { break }  // EOF
                self?.ingest(data)
            }
            self?.flushPartial()
            proc.waitUntilExit()
            self?.onExit(proc.terminationStatus)
        }
    }

    /// Runs on `queue`. Appends bytes and emits each complete (newline-terminated) line.
    private func ingest(_ data: Data) {
        buffer.append(data)
        while let newline = buffer.firstIndex(of: 0x0A) {
            let lineData = buffer.subdata(in: buffer.startIndex..<newline)
            buffer.removeSubrange(buffer.startIndex...newline)
            if let line = String(data: lineData, encoding: .utf8) {
                onLine(line)
            }
        }
    }

    /// Runs on `queue`. Emits any trailing partial line left at EOF.
    private func flushPartial() {
        if !buffer.isEmpty, let line = String(data: buffer, encoding: .utf8) {
            onLine(line)
        }
        buffer.removeAll()
    }

    public func stop(timeout: TimeInterval = 5.0) {
        if let proc = process, proc.isRunning {
            proc.terminate()
            let deadline = Date().addingTimeInterval(timeout)
            while proc.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.05)
            }
            if proc.isRunning {
                kill(proc.processIdentifier, SIGKILL)
                proc.waitUntilExit()
            }
        }
        // Block until the reader queue has drained output and delivered onExit,
        // so callers (e.g. restart) observe a fully settled state and never race
        // a late onExit against a fresh start.
        if process != nil {
            queue.sync {}
        }
    }
}
