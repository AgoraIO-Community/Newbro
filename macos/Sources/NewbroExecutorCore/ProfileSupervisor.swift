import Foundation
import Combine

public final class ProfileSupervisor: ObservableObject {
    public struct ProcessFactory {
        public let make: (_ argv: [String],
                          _ onLine: @escaping (String) -> Void,
                          _ onExit: @escaping (Int32) -> Void) -> NodeProcessProtocol
        public init(make: @escaping (_ argv: [String],
                                     _ onLine: @escaping (String) -> Void,
                                     _ onExit: @escaping (Int32) -> Void) -> NodeProcessProtocol) {
            self.make = make
        }
    }

    private final class Record {
        let profile: Profile
        var process: NodeProcessProtocol?
        let parser = StatusParser()
        var expectedStop = false
        let log: ProfileLogging?
        init(profile: Profile, log: ProfileLogging?) {
            self.profile = profile
            self.log = log
        }
    }

    private let processFactory: ProcessFactory
    private let argvBuilder: (Profile) -> [String]
    private let logFactory: ((Profile) -> ProfileLogging?)?
    private var records: [String: Record] = [:]
    private let lock = NSRecursiveLock()

    public init(processFactory: ProcessFactory,
                argvBuilder: @escaping (Profile) -> [String],
                logFactory: ((Profile) -> ProfileLogging?)? = nil) {
        self.processFactory = processFactory
        self.argvBuilder = argvBuilder
        self.logFactory = logFactory
    }

    public func start(_ profile: Profile) {
        lock.lock()
        if let existing = records[profile.id], existing.process?.isRunning == true {
            lock.unlock()
            return
        }
        let record = Record(profile: profile, log: logFactory?(profile))
        record.parser.onStart()
        let process = processFactory.make(
            argvBuilder(profile),
            { [weak self] line in self?.handleLine(profile.id, line) },
            { [weak self] code in self?.handleExit(profile.id, code) })
        record.process = process
        records[profile.id] = record
        lock.unlock()
        process.start()
        notifyChange()
    }

    public func stop(_ profileID: String) {
        lock.lock()
        guard let record = records[profileID] else { lock.unlock(); return }
        record.expectedStop = true
        let process = record.process
        lock.unlock()
        process?.stop(timeout: 5.0)
    }

    public func restart(_ profile: Profile) {
        stop(profile.id)
        start(profile)
    }

    public func stopAll() {
        lock.lock()
        let processes = records.values.compactMap { record -> NodeProcessProtocol? in
            record.expectedStop = true
            return record.process
        }
        lock.unlock()
        for process in processes { process.stop(timeout: 5.0) }
    }

    public func status(of profileID: String) -> NodeStatus {
        lock.lock(); defer { lock.unlock() }
        return records[profileID]?.parser.status ?? .idle
    }

    public func aggregateStatus() -> NodeStatus {
        lock.lock(); defer { lock.unlock() }
        return NewbroExecutorCore.aggregateStatus(records.values.map { $0.parser.status })
    }

    public func activeIDs() -> Set<String> {
        lock.lock(); defer { lock.unlock() }
        return Set(records.keys)
    }

    private func handleLine(_ profileID: String, _ line: String) {
        lock.lock()
        guard let record = records[profileID] else { lock.unlock(); return }
        record.parser.onLine(line)
        let log = record.log
        lock.unlock()
        log?.append(line)
        notifyChange()
    }

    private func handleExit(_ profileID: String, _ code: Int32) {
        lock.lock()
        guard let record = records[profileID] else { lock.unlock(); return }
        if record.expectedStop {
            record.parser.onExit(code: code, expected: true)
            records.removeValue(forKey: profileID)
        } else {
            record.parser.onExit(code: code, expected: false)
        }
        lock.unlock()
        notifyChange()
    }

    private func notifyChange() {
        DispatchQueue.main.async { [weak self] in self?.objectWillChange.send() }
    }
}
