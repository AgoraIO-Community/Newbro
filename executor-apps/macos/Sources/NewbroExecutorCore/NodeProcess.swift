import Foundation

public protocol NodeProcessProtocol: AnyObject {
    func start()
    func stop(timeout: TimeInterval)
    var isRunning: Bool { get }
}

public final class NodeProcess: NodeProcessProtocol {
    private let argv: [String]
    private let environment: [String: String]?
    private let onLine: (String) -> Void
    private let onExit: (Int32) -> Void
    private var process: Process?
    private var readHandle: FileHandle?
    private let queue = DispatchQueue(label: "newbro.node-process")
    private var buffer = Data()

    public init(argv: [String],
                environment: [String: String]? = nil,
                onLine: @escaping (String) -> Void,
                onExit: @escaping (Int32) -> Void) {
        self.argv = argv
        self.environment = environment
        self.onLine = onLine
        self.onExit = onExit
    }

    public var isRunning: Bool { process?.isRunning ?? false }

    public func start() {
        guard process == nil, !argv.isEmpty else { return }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: argv[0])
        proc.arguments = Array(argv.dropFirst())
        if let environment { proc.environment = environment }
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        process = proc
        let handle = pipe.fileHandleForReading
        readHandle = handle
        do {
            try proc.run()
        } catch {
            process = nil
            readHandle = nil
            onExit(127)
            return
        }
        // A single serial reader owns all output consumption and the exit
        // report. Using POSIX read() rather than FileHandle.read(upToCount:)
        // so that:
        //   (a) we get data as soon as any bytes arrive (not after 65536 bytes),
        //   (b) stop() can unblock the reader by closing the fd even when a
        //       surviving grandchild still holds the pipe's write end.
        let fd = handle.fileDescriptor
        queue.async { [weak self] in
            var buf = [UInt8](repeating: 0, count: 65536)
            while true {
                let n = Darwin.read(fd, &buf, buf.count)
                if n <= 0 { break }  // 0 = EOF, -1 = fd closed (EBADF) or error
                self?.ingest(Data(buf[..<n]))
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
        // Unblock the reader even if a surviving grandchild still holds the pipe
        // write end: closing the read handle makes Darwin.read() return -1/EBADF,
        // so the reader loop ends and onExit fires. Idempotent via try?.
        try? readHandle?.close()
        // Bounded drain — never block the caller forever on the reader queue.
        if process != nil {
            let drained = DispatchSemaphore(value: 0)
            queue.async { drained.signal() }
            _ = drained.wait(timeout: .now() + 2.0)
        }
    }
}
