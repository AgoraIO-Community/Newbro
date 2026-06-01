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
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            self?.ingest(data)
        }
        proc.terminationHandler = { [weak self] proc in
            guard let self else { return }
            pipe.fileHandleForReading.readabilityHandler = nil
            self.flush()
            self.onExit(proc.terminationStatus)
        }
        process = proc
        try? proc.run()
    }

    private func ingest(_ data: Data) {
        queue.async {
            self.buffer.append(data)
            while let newline = self.buffer.firstIndex(of: 0x0A) {
                let lineData = self.buffer.subdata(in: self.buffer.startIndex..<newline)
                self.buffer.removeSubrange(self.buffer.startIndex...newline)
                if let line = String(data: lineData, encoding: .utf8) {
                    self.onLine(line)
                }
            }
        }
    }

    private func flush() {
        queue.sync {
            if !self.buffer.isEmpty, let line = String(data: self.buffer, encoding: .utf8) {
                self.onLine(line)
            }
            self.buffer.removeAll()
        }
    }

    public func stop(timeout: TimeInterval = 5.0) {
        guard let proc = process, proc.isRunning else { return }
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
}
