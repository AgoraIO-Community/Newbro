import Foundation
import Combine

public enum ProfileLifecycleEvent: Equatable, Sendable {
    case started(profileID: String, label: String)
    case stopped(profileID: String, label: String)
    case error(profileID: String, label: String, exitCode: Int32)
}

public final class ProfileLifecycleEventSuppression {
    private var startOnlyCounts: [String: Int] = [:]
    private var restartAwaitingStopAndStartCounts: [String: Int] = [:]
    private var restartAwaitingStartCounts: [String: Int] = [:]

    public init() {}

    public func suppressNextStart(profileID: String) {
        startOnlyCounts[profileID, default: 0] += 1
    }

    public func suppressNextRestart(profileID: String) {
        restartAwaitingStopAndStartCounts[profileID, default: 0] += 1
    }

    public func shouldSuppress(_ event: ProfileLifecycleEvent) -> Bool {
        switch event {
        case let .started(profileID, _):
            if consume(&restartAwaitingStartCounts, profileID: profileID) {
                return true
            }
            if consume(&restartAwaitingStopAndStartCounts, profileID: profileID) {
                return true
            }
            return consume(&startOnlyCounts, profileID: profileID)
        case let .stopped(profileID, _):
            if consume(&restartAwaitingStopAndStartCounts, profileID: profileID) {
                restartAwaitingStartCounts[profileID, default: 0] += 1
                return true
            }
            return false
        case .error:
            return false
        }
    }

    private func consume(_ counts: inout [String: Int], profileID: String) -> Bool {
        guard let count = counts[profileID], count > 0 else { return false }
        if count == 1 {
            counts.removeValue(forKey: profileID)
        } else {
            counts[profileID] = count - 1
        }
        return true
    }
}

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
        var exited = false
        let log: ProfileLogging?
        init(profile: Profile, log: ProfileLogging?) {
            self.profile = profile
            self.log = log
        }
    }

    private let processFactory: ProcessFactory
    private let argvBuilder: (Profile) -> [String]
    private let logFactory: ((Profile) -> ProfileLogging?)?
    private let onEvent: ((ProfileLifecycleEvent) -> Void)?
    private var records: [String: Record] = [:]
    private let lock = NSRecursiveLock()

    public init(processFactory: ProcessFactory,
                argvBuilder: @escaping (Profile) -> [String],
                logFactory: ((Profile) -> ProfileLogging?)? = nil,
                onEvent: ((ProfileLifecycleEvent) -> Void)? = nil) {
        self.processFactory = processFactory
        self.argvBuilder = argvBuilder
        self.logFactory = logFactory
        self.onEvent = onEvent
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
        onEvent?(.started(profileID: profile.id, label: profile.label))
    }

    public func stop(_ profileID: String) {
        lock.lock()
        guard let record = records[profileID] else { lock.unlock(); return }
        record.expectedStop = true
        // If the process already exited (e.g. an errored record kept for the UI),
        // reclaim it now — stopping a dead process won't re-fire handleExit.
        if record.exited { records.removeValue(forKey: profileID) }
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
        let event: ProfileLifecycleEvent
        if record.expectedStop {
            record.parser.onExit(code: code, expected: true)
            records.removeValue(forKey: profileID)
            event = .stopped(profileID: profileID, label: record.profile.label)
        } else {
            record.parser.onExit(code: code, expected: false)
            record.exited = true
            event = .error(profileID: profileID, label: record.profile.label, exitCode: code)
        }
        lock.unlock()
        notifyChange()
        onEvent?(event)
    }

    private func notifyChange() {
        DispatchQueue.main.async { [weak self] in self?.objectWillChange.send() }
    }
}
