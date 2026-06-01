# macOS Executor SwiftUI App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python rumps menu-bar executor app with a native SwiftUI app that supervises multiple concurrent `newbro executor run` node profiles.

**Architecture:** A Swift Package at `macos/` with a pure-logic `NewbroExecutorCore` library (XCTest-covered) and a thin `NewbroExecutor` SwiftUI executable (`MenuBarExtra`, menu-bar only). The app resolves the externally-installed `newbro` CLI and spawns one `newbro executor run …` subprocess per active profile, parsing its stderr status lines. The Python `src/newbro/executors/ui/` package and its wiring are removed.

**Tech Stack:** Swift 5.9+/Xcode (macOS 14 target), SwiftUI, Foundation `Process`, XCTest. Build via `swift build`/`swift test`; bundle via a shell script.

**Prerequisites:** Full Xcode installed and selected (`xcode-select -p` → `…/Xcode.app`), license accepted. Verify with `swift test --package-path /tmp/... ` smoke if unsure. All `swift` commands below run from the repo root `/Users/zhangqianze/Documents/Synopse`.

---

## File Structure

```
macos/
  .gitignore                                   ← ignore .build/ and dist/
  Package.swift                                ← swift-tools 5.9, macOS .v14, 3 targets
  Sources/
    NewbroExecutorCore/
      Profile.swift                            ← Profile (Codable, snake_case JSON)
      ProfileStore.swift                       ← load/save ~/.newbro/menubar.json
      ConnectCommand.swift                     ← parseConnectCommand + conflictingProfileIDs
      NodeStatus.swift                         ← NodeStatus, StatusParser, aggregateStatus
      NodeProcess.swift                        ← NodeProcessProtocol + NodeProcess (Process wrapper)
      ProfileLog.swift                         ← ProfileLogging + ProfileLog (file tail)
      RuntimeLocator.swift                     ← resolve newbro, nodeArgv, install command
      LoginItem.swift                          ← LaunchAgent plist render/install/remove
      ProfileSupervisor.swift                  ← per-profile process+status map (ObservableObject)
    NewbroExecutor/
      NewbroExecutorApp.swift                  ← @main App, MenuBarExtra, AppDelegate(.accessory)
      AppModel.swift                           ← ObservableObject wiring store+supervisor+locator
      MenuContent.swift                        ← menu-bar dropdown view
      ProfileEditView.swift                    ← add/edit form window
      LogView.swift                            ← recent-log window
  Tests/
    NewbroExecutorCoreTests/
      ProfileStoreTests.swift
      ConnectCommandTests.swift
      NodeStatusTests.swift
      NodeProcessTests.swift
      ProfileSupervisorTests.swift
      RuntimeLocatorTests.swift
      LoginItemTests.swift
      ProfileLogTests.swift
  package-app.sh                               ← swift build + assemble Newbro Executor.app
```

**Removed (Task 10):** `src/newbro/executors/ui/`, `tests/unit/executors/ui/`, `src/newbro/cli/commands/executor_ui.py`, the `executor ui` parser/dispatch wiring, `pyproject.toml` `macos-ui`/`macos-ui-build` extras, `packaging/menubar/`.

---

### Task 1: Package scaffold + Profile model + ProfileStore

**Files:**
- Create: `macos/.gitignore`, `macos/Package.swift`
- Create: `macos/Sources/NewbroExecutorCore/Profile.swift`, `macos/Sources/NewbroExecutorCore/ProfileStore.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/ProfileStoreTests.swift`

- [ ] **Step 1: Create the package manifest and gitignore**

`macos/.gitignore`:
```
.build/
dist/
*.xcodeproj
```

`macos/Package.swift`:
```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "NewbroExecutor",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "NewbroExecutorCore"),
        .executableTarget(
            name: "NewbroExecutor",
            dependencies: ["NewbroExecutorCore"]
        ),
        .testTarget(
            name: "NewbroExecutorCoreTests",
            dependencies: ["NewbroExecutorCore"]
        ),
    ]
)
```

- [ ] **Step 2: Write the failing test**

`macos/Tests/NewbroExecutorCoreTests/ProfileStoreTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

final class ProfileStoreTests: XCTestCase {
    func testSaveThenLoadRoundTrips() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let path = dir.appendingPathComponent("menubar.json")
        let store = ProfileStore(path: path)
        let profiles = [
            Profile(id: "p1", label: "Prod", baseURL: "https://x", nodeID: "node-1",
                    token: "t1", enabledExecutors: ["codex"], autoActivate: true),
            Profile(id: "p2", label: "Staging", baseURL: "http://127.0.0.1:8000",
                    nodeID: "node-2", token: "t2"),
        ]
        try store.save(profiles)
        let loaded = store.load()
        XCTAssertEqual(loaded, profiles)
        XCTAssertEqual(loaded[1].enabledExecutors, [])
        XCTAssertFalse(loaded[1].autoActivate)
    }

    func testLoadMissingFileReturnsEmpty() {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).appendingPathComponent("absent.json")
        XCTAssertEqual(ProfileStore(path: path).load(), [])
    }

    func testJSONUsesSnakeCaseKeys() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let path = dir.appendingPathComponent("menubar.json")
        try ProfileStore(path: path).save([
            Profile(id: "p1", label: "L", baseURL: "https://x", nodeID: "n", token: "t",
                    enabledExecutors: ["codex"], autoActivate: true)
        ])
        let text = try String(contentsOf: path, encoding: .utf8)
        XCTAssertTrue(text.contains("\"base_url\""))
        XCTAssertTrue(text.contains("\"node_id\""))
        XCTAssertTrue(text.contains("\"enabled_executors\""))
        XCTAssertTrue(text.contains("\"auto_activate\""))
    }
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `swift test --package-path macos 2>&1 | tail -20`
Expected: build failure — `cannot find 'ProfileStore' in scope` / `cannot find 'Profile' in scope`.

- [ ] **Step 4: Write minimal implementation**

`macos/Sources/NewbroExecutorCore/Profile.swift`:
```swift
import Foundation

public struct Profile: Codable, Equatable, Identifiable {
    public var id: String
    public var label: String
    public var baseURL: String
    public var nodeID: String
    public var token: String
    public var enabledExecutors: [String]
    public var autoActivate: Bool

    public init(id: String, label: String, baseURL: String, nodeID: String,
                token: String, enabledExecutors: [String] = [], autoActivate: Bool = false) {
        self.id = id
        self.label = label
        self.baseURL = baseURL
        self.nodeID = nodeID
        self.token = token
        self.enabledExecutors = enabledExecutors
        self.autoActivate = autoActivate
    }

    enum CodingKeys: String, CodingKey {
        case id, label, token
        case baseURL = "base_url"
        case nodeID = "node_id"
        case enabledExecutors = "enabled_executors"
        case autoActivate = "auto_activate"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        baseURL = try c.decodeIfPresent(String.self, forKey: .baseURL) ?? ""
        nodeID = try c.decodeIfPresent(String.self, forKey: .nodeID) ?? ""
        token = try c.decodeIfPresent(String.self, forKey: .token) ?? ""
        enabledExecutors = try c.decodeIfPresent([String].self, forKey: .enabledExecutors) ?? []
        autoActivate = try c.decodeIfPresent(Bool.self, forKey: .autoActivate) ?? false
    }
}
```

`macos/Sources/NewbroExecutorCore/ProfileStore.swift`:
```swift
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `swift test --package-path macos 2>&1 | tail -8`
Expected: `Executed 3 tests, with 0 failures`.

- [ ] **Step 6: Commit**

```bash
git add macos/.gitignore macos/Package.swift macos/Sources/NewbroExecutorCore/Profile.swift macos/Sources/NewbroExecutorCore/ProfileStore.swift macos/Tests/NewbroExecutorCoreTests/ProfileStoreTests.swift
git commit -m "feat(macos): scaffold SwiftPM package, Profile model, ProfileStore"
```

---

### Task 2: ConnectCommand parsing + conflict detection

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/ConnectCommand.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/ConnectCommandTests.swift`

- [ ] **Step 1: Write the failing test**

`macos/Tests/NewbroExecutorCoreTests/ConnectCommandTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

final class ConnectCommandTests: XCTestCase {
    func testParsesAllFields() throws {
        let text = "newbro executor run --base-url https://x --node-id node-1 " +
                   "--token tok --enabled-executor codex --enabled-executor acpx"
        let fields = try parseConnectCommand(text)
        XCTAssertEqual(fields, ConnectCommandFields(
            baseURL: "https://x", nodeID: "node-1", token: "tok",
            enabledExecutors: ["codex", "acpx"]))
    }

    func testMissingCoreFieldThrows() {
        XCTAssertThrowsError(try parseConnectCommand("newbro executor run --base-url https://x"))
    }

    func testConflictingProfileIDs() {
        let profiles = [
            Profile(id: "a", label: "A", baseURL: "https://x", nodeID: "n1", token: "t"),
            Profile(id: "b", label: "B", baseURL: "https://x", nodeID: "n1", token: "t2"),
            Profile(id: "c", label: "C", baseURL: "https://x", nodeID: "n2", token: "t3"),
        ]
        XCTAssertEqual(conflictingProfileIDs(profiles), Set(["a", "b"]))
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `swift test --package-path macos 2>&1 | tail -20`
Expected: `cannot find 'parseConnectCommand' in scope`.

- [ ] **Step 3: Write minimal implementation**

`macos/Sources/NewbroExecutorCore/ConnectCommand.swift`:
```swift
import Foundation

public struct ConnectCommandFields: Equatable {
    public let baseURL: String
    public let nodeID: String
    public let token: String
    public let enabledExecutors: [String]

    public init(baseURL: String, nodeID: String, token: String, enabledExecutors: [String]) {
        self.baseURL = baseURL
        self.nodeID = nodeID
        self.token = token
        self.enabledExecutors = enabledExecutors
    }
}

public enum ConnectCommandError: Error, Equatable {
    case missingFields([String])
}

public func parseConnectCommand(_ text: String) throws -> ConnectCommandFields {
    let tokens = text.split(whereSeparator: { $0.isWhitespace }).map(String.init)
    var baseURL = "", nodeID = "", token = ""
    var enabled: [String] = []
    var index = 0
    let valueFlags: Set<String> = ["--base-url", "--node-id", "--token", "--enabled-executor"]
    while index < tokens.count {
        let flag = tokens[index]
        if valueFlags.contains(flag), index + 1 < tokens.count {
            let value = tokens[index + 1]
            switch flag {
            case "--base-url": baseURL = value
            case "--node-id": nodeID = value
            case "--token": token = value
            default: enabled.append(value)
            }
            index += 2
            continue
        }
        index += 1
    }
    var missing: [String] = []
    if baseURL.isEmpty { missing.append("--base-url") }
    if nodeID.isEmpty { missing.append("--node-id") }
    if token.isEmpty { missing.append("--token") }
    if !missing.isEmpty { throw ConnectCommandError.missingFields(missing) }
    return ConnectCommandFields(baseURL: baseURL, nodeID: nodeID, token: token,
                                enabledExecutors: enabled)
}

public func conflictingProfileIDs(_ profiles: [Profile]) -> Set<String> {
    var seen: [String: String] = [:]
    var conflicts: Set<String> = []
    for profile in profiles {
        let key = profile.baseURL + "\u{0}" + profile.nodeID
        if let first = seen[key] {
            conflicts.insert(first)
            conflicts.insert(profile.id)
        } else {
            seen[key] = profile.id
        }
    }
    return conflicts
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `swift test --package-path macos 2>&1 | tail -8`
Expected: all tests pass (now 6 total).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/ConnectCommand.swift macos/Tests/NewbroExecutorCoreTests/ConnectCommandTests.swift
git commit -m "feat(macos): parse connect commands and detect duplicate node identities"
```

---

### Task 3: NodeStatus + StatusParser + aggregateStatus

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/NodeStatus.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/NodeStatusTests.swift`

- [ ] **Step 1: Write the failing test**

`macos/Tests/NewbroExecutorCoreTests/NodeStatusTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

final class NodeStatusTests: XCTestCase {
    func testConnectToReady() {
        let p = StatusParser()
        p.onStart()
        p.onLine("[start] executor node node_id=n executors=codex newbro=https://x")
        p.onLine("[connect] executor node attempt=1 url=wss://x")
        p.onLine("[ready] executor node node_id=n executors=codex newbro=https://x")
        XCTAssertEqual(p.status, .ready)
    }

    func testDisconnectAndRetry() {
        let p = StatusParser()
        p.onLine("[ready] executor node node_id=n executors=codex newbro=https://x")
        p.onLine("[warn] executor node disconnected=ConnectionClosed url=wss://x")
        XCTAssertEqual(p.status, .disconnected)
        p.onLine("[retry] executor node retrying in 2.0s")
        XCTAssertEqual(p.status, .retrying)
    }

    func testConnectFailedStaysConnecting() {
        let p = StatusParser()
        p.onLine("[connect] executor node attempt=1 url=wss://x")
        p.onLine("[warn] executor node attempt=1 connect_failed=Timeout url=wss://x")
        XCTAssertEqual(p.status, .connecting)
    }

    func testExitExpectedStoppedUnexpectedError() {
        let a = StatusParser(); a.onStart()
        XCTAssertEqual(a.onExit(code: 0, expected: true), .stopped)
        let b = StatusParser(); b.onStart()
        XCTAssertEqual(b.onExit(code: 1, expected: false), .error)
    }

    func testAggregatePriority() {
        XCTAssertEqual(aggregateStatus([.ready, .error]), .error)
        XCTAssertEqual(aggregateStatus([.ready, .connecting]), .connecting)
        XCTAssertEqual(aggregateStatus([.ready, .stopped]), .ready)
        XCTAssertEqual(aggregateStatus([.stopped, .idle]), .idle)
        XCTAssertEqual(aggregateStatus([]), .idle)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `swift test --package-path macos 2>&1 | tail -20`
Expected: `cannot find 'StatusParser' in scope`.

- [ ] **Step 3: Write minimal implementation**

`macos/Sources/NewbroExecutorCore/NodeStatus.swift`:
```swift
import Foundation

public enum NodeStatus: String, Equatable, Sendable {
    case idle, starting, connecting, ready, disconnected, retrying, error, stopped
}

public final class StatusParser {
    public private(set) var status: NodeStatus = .idle

    public init() {}

    @discardableResult
    public func onStart() -> NodeStatus {
        status = .starting
        return status
    }

    @discardableResult
    public func onLine(_ line: String) -> NodeStatus {
        if line.hasPrefix("[start]") {
            status = .starting
        } else if line.hasPrefix("[connect]") {
            status = .connecting
        } else if line.hasPrefix("[ready]") {
            status = .ready
        } else if line.hasPrefix("[retry]") {
            status = .retrying
        } else if line.hasPrefix("[warn]"), line.contains("disconnected=") {
            status = .disconnected
        } else if line.hasPrefix("[warn]"), line.contains("connect_failed=") {
            status = .connecting
        }
        return status
    }

    @discardableResult
    public func onExit(code: Int32, expected: Bool) -> NodeStatus {
        status = expected ? .stopped : .error
        return status
    }
}

public func aggregateStatus(_ statuses: [NodeStatus]) -> NodeStatus {
    let priority: [NodeStatus] = [.error, .disconnected, .retrying, .connecting, .starting, .ready]
    let present = Set(statuses)
    for candidate in priority where present.contains(candidate) {
        return candidate
    }
    return .idle
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `swift test --package-path macos 2>&1 | tail -8`
Expected: all tests pass (11 total).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/NodeStatus.swift macos/Tests/NewbroExecutorCoreTests/NodeStatusTests.swift
git commit -m "feat(macos): map node output lines to per-profile status"
```

---

### Task 4: NodeProcess (real subprocess supervision)

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/NodeProcess.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/NodeProcessTests.swift`

- [ ] **Step 1: Write the failing test**

`macos/Tests/NewbroExecutorCoreTests/NodeProcessTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

private final class Box<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: T
    init(_ value: T) { stored = value }
    var value: T { lock.lock(); defer { lock.unlock() }; return stored }
    func mutate(_ change: (inout T) -> Void) { lock.lock(); change(&stored); lock.unlock() }
}

final class NodeProcessTests: XCTestCase {
    func testCapturesLinesAndExitCode() {
        let lines = Box<[String]>([])
        let code = Box<Int32>(-1)
        let exited = expectation(description: "exited")
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "printf '[start] hi\\n[ready] go\\n'; exit 0"],
            onLine: { line in lines.mutate { $0.append(line) } },
            onExit: { c in code.mutate { $0 = c }; exited.fulfill() }
        )
        proc.start()
        wait(for: [exited], timeout: 10)
        XCTAssertTrue(lines.value.contains("[start] hi"))
        XCTAssertTrue(lines.value.contains("[ready] go"))
        XCTAssertEqual(code.value, 0)
    }

    func testStopTerminatesLongRunner() {
        let started = expectation(description: "started")
        started.assertForOverFulfill = false
        let exited = expectation(description: "exited")
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "printf '[start] up\\n'; while true; do sleep 0.1; done"],
            onLine: { _ in started.fulfill() },
            onExit: { _ in exited.fulfill() }
        )
        proc.start()
        wait(for: [started], timeout: 10)
        XCTAssertTrue(proc.isRunning)
        proc.stop()
        wait(for: [exited], timeout: 10)
        XCTAssertFalse(proc.isRunning)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `swift test --package-path macos 2>&1 | tail -20`
Expected: `cannot find 'NodeProcess' in scope`.

- [ ] **Step 3: Write minimal implementation**

`macos/Sources/NewbroExecutorCore/NodeProcess.swift`:
```swift
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `swift test --package-path macos 2>&1 | tail -8`
Expected: all tests pass (13 total). The two NodeProcess tests spawn real `/bin/sh` and may take ~1s.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/NodeProcess.swift macos/Tests/NewbroExecutorCoreTests/NodeProcessTests.swift
git commit -m "feat(macos): supervise node subprocess with line capture and stop"
```

---

### Task 5: ProfileLog (file append + tail)

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/ProfileLog.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/ProfileLogTests.swift`

- [ ] **Step 1: Write the failing test**

`macos/Tests/NewbroExecutorCoreTests/ProfileLogTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

final class ProfileLogTests: XCTestCase {
    private func tempLog() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("node.log")
    }

    func testAppendAndRecent() {
        let log = ProfileLog(path: tempLog())
        log.append("[start] one")
        log.append("[ready] two")
        XCTAssertEqual(log.recent(), ["[start] one", "[ready] two"])
    }

    func testRecentCapsToMaxLines() {
        let log = ProfileLog(path: tempLog(), maxLines: 3)
        for index in 0..<10 { log.append("line \(index)") }
        XCTAssertEqual(log.recent(), ["line 7", "line 8", "line 9"])
    }

    func testRecentOnMissingFileIsEmpty() {
        XCTAssertEqual(ProfileLog(path: tempLog()).recent(), [])
    }

    func testDefaultPathUsesProfileID() {
        let path = ProfileLog.defaultPath(profileID: "abc")
        XCTAssertEqual(path.lastPathComponent, "executor-ui-abc.log")
        XCTAssertEqual(path.deletingLastPathComponent().lastPathComponent, "logs")
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `swift test --package-path macos 2>&1 | tail -20`
Expected: `cannot find 'ProfileLog' in scope`.

- [ ] **Step 3: Write minimal implementation**

`macos/Sources/NewbroExecutorCore/ProfileLog.swift`:
```swift
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `swift test --package-path macos 2>&1 | tail -8`
Expected: all tests pass (17 total).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/ProfileLog.swift macos/Tests/NewbroExecutorCoreTests/ProfileLogTests.swift
git commit -m "feat(macos): capture per-profile node logs"
```

---

### Task 6: RuntimeLocator

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`

- [ ] **Step 1: Write the failing test**

`macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

final class RuntimeLocatorTests: XCTestCase {
    private let home = URL(fileURLWithPath: "/Users/test")

    func testResolvesUvLocationWhenPresent() {
        let uv = "/Users/test/.local/bin/newbro"
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { $0 == uv },
            whichNewbro: { nil })
        XCTAssertEqual(locator.resolveNewbro(), uv)
        XCTAssertTrue(locator.isRuntimeAvailable)
    }

    func testOverrideWins() {
        let override = "/opt/newbro"
        let locator = RuntimeLocator(
            overridePath: override, homeDir: home,
            fileExists: { $0 == override || $0 == "/Users/test/.local/bin/newbro" },
            whichNewbro: { nil })
        XCTAssertEqual(locator.resolveNewbro(), override)
    }

    func testFallsBackToLoginShellWhich() {
        let shellPath = "/usr/local/bin/newbro"
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { $0 == shellPath },
            whichNewbro: { shellPath })
        XCTAssertEqual(locator.resolveNewbro(), shellPath)
    }

    func testMissingRuntime() {
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { _ in false }, whichNewbro: { nil })
        XCTAssertNil(locator.resolveNewbro())
        XCTAssertFalse(locator.isRuntimeAvailable)
        XCTAssertNil(locator.nodeArgv(for: Profile(
            id: "p", label: "L", baseURL: "https://x", nodeID: "n", token: "t")))
    }

    func testNodeArgvShape() {
        let uv = "/Users/test/.local/bin/newbro"
        let locator = RuntimeLocator(
            overridePath: nil, homeDir: home,
            fileExists: { $0 == uv }, whichNewbro: { nil })
        let profile = Profile(id: "p", label: "L", baseURL: "https://x",
                              nodeID: "n", token: "t", enabledExecutors: ["codex", "acpx"])
        XCTAssertEqual(locator.nodeArgv(for: profile), [
            uv, "executor", "run",
            "--base-url", "https://x", "--node-id", "n", "--token", "t",
            "--enabled-executor", "codex", "--enabled-executor", "acpx",
        ])
    }

    func testInstallCommandArgv() {
        let locator = RuntimeLocator(overridePath: nil, homeDir: home,
                                     fileExists: { _ in false }, whichNewbro: { nil })
        let argv = locator.installCommandArgv()
        XCTAssertEqual(argv[0], "/bin/sh")
        XCTAssertEqual(argv[1], "-c")
        XCTAssertTrue(argv[2].contains("install-newbro-cli.sh"))
        XCTAssertTrue(argv[2].contains("curl -fsSL"))
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `swift test --package-path macos 2>&1 | tail -20`
Expected: `cannot find 'RuntimeLocator' in scope`.

- [ ] **Step 3: Write minimal implementation**

`macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`:
```swift
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `swift test --package-path macos 2>&1 | tail -8`
Expected: all tests pass (23 total).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/RuntimeLocator.swift macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift
git commit -m "feat(macos): resolve newbro runtime and build node argv"
```

---

### Task 7: LoginItem + ProfileSupervisor

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/LoginItem.swift`, `macos/Sources/NewbroExecutorCore/ProfileSupervisor.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/LoginItemTests.swift`, `macos/Tests/NewbroExecutorCoreTests/ProfileSupervisorTests.swift`

- [ ] **Step 1: Write the failing tests**

`macos/Tests/NewbroExecutorCoreTests/LoginItemTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

final class LoginItemTests: XCTestCase {
    func testRenderPlistContainsLabelAndAppPath() throws {
        let item = LoginItem(plistPath: nil, appPath: "/Applications/Newbro Executor.app")
        let text = item.renderPlist()
        let data = text.data(using: .utf8)!
        let parsed = try PropertyListSerialization.propertyList(
            from: data, options: [], format: nil) as! [String: Any]
        XCTAssertEqual(parsed["Label"] as? String, LoginItem.label)
        XCTAssertEqual(parsed["RunAtLoad"] as? Bool, true)
        let args = parsed["ProgramArguments"] as? [String]
        XCTAssertEqual(args, ["/usr/bin/open", "/Applications/Newbro Executor.app"])
    }

    func testInstallThenRemove() throws {
        let plist = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("\(LoginItem.label).plist")
        let item = LoginItem(plistPath: plist, appPath: "/Applications/Newbro Executor.app")
        XCTAssertFalse(item.isInstalled)
        try item.install()
        XCTAssertTrue(item.isInstalled)
        try item.remove()
        XCTAssertFalse(item.isInstalled)
    }
}
```

`macos/Tests/NewbroExecutorCoreTests/ProfileSupervisorTests.swift`:
```swift
import XCTest
@testable import NewbroExecutorCore

private final class FakeProcess: NodeProcessProtocol {
    let onLine: (String) -> Void
    let onExit: (Int32) -> Void
    private(set) var started = false
    private(set) var stopped = false
    init(onLine: @escaping (String) -> Void, onExit: @escaping (Int32) -> Void) {
        self.onLine = onLine
        self.onExit = onExit
    }
    func start() { started = true }
    func stop(timeout: TimeInterval) { stopped = true }
    var isRunning: Bool { started && !stopped }
}

final class ProfileSupervisorTests: XCTestCase {
    private var created: [FakeProcess] = []

    private func makeSupervisor(logSink: ProfileLogging? = nil) -> ProfileSupervisor {
        created = []
        let factory = ProfileSupervisor.ProcessFactory { _, onLine, onExit in
            let fake = FakeProcess(onLine: onLine, onExit: onExit)
            self.created.append(fake)
            return fake
        }
        return ProfileSupervisor(
            processFactory: factory,
            argvBuilder: { ["run", $0.nodeID] },
            logFactory: logSink == nil ? nil : { _ in logSink })
    }

    private func profile(_ id: String = "p1", _ node: String = "node-1") -> Profile {
        Profile(id: id, label: id, baseURL: "https://x", nodeID: node, token: "t",
                enabledExecutors: ["codex"])
    }

    func testStartReportsStarting() {
        let sup = makeSupervisor()
        sup.start(profile())
        XCTAssertEqual(sup.activeIDs(), Set(["p1"]))
        XCTAssertEqual(sup.status(of: "p1"), .starting)
    }

    func testLinesDriveStatusAndAggregate() {
        let sup = makeSupervisor()
        sup.start(profile())
        created[0].onLine("[ready] executor node node_id=node-1 executors=codex newbro=https://x")
        XCTAssertEqual(sup.status(of: "p1"), .ready)
        XCTAssertEqual(sup.aggregateStatus(), .ready)
    }

    func testUserStopDropsProfile() {
        let sup = makeSupervisor()
        sup.start(profile())
        sup.stop("p1")
        created[0].onExit(0)
        XCTAssertTrue(created[0].stopped)
        XCTAssertEqual(sup.activeIDs(), [])
    }

    func testUnexpectedExitKeepsRecordAsError() {
        let sup = makeSupervisor()
        sup.start(profile())
        created[0].onExit(1)
        XCTAssertEqual(sup.status(of: "p1"), .error)
        XCTAssertEqual(sup.activeIDs(), Set(["p1"]))
    }

    func testStopAllStopsEveryProcess() {
        let sup = makeSupervisor()
        sup.start(profile("p1", "node-1"))
        sup.start(profile("p2", "node-2"))
        sup.stopAll()
        XCTAssertTrue(created.allSatisfy { $0.stopped })
    }

    func testLogFactoryReceivesLines() {
        final class FakeLog: ProfileLogging {
            private(set) var lines: [String] = []
            func append(_ line: String) { lines.append(line) }
        }
        let sink = FakeLog()
        let sup = makeSupervisor(logSink: sink)
        sup.start(profile())
        created[0].onLine("[ready] go")
        XCTAssertEqual(sink.lines, ["[ready] go"])
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `swift test --package-path macos 2>&1 | tail -20`
Expected: `cannot find 'LoginItem' in scope` / `cannot find 'ProfileSupervisor' in scope`.

- [ ] **Step 3: Write minimal implementations**

`macos/Sources/NewbroExecutorCore/LoginItem.swift`:
```swift
import Foundation

public struct LoginItem {
    public static let label = "com.newbro.executor-ui"

    private let plistPath: URL
    private let appPath: String

    public init(plistPath: URL? = nil, appPath: String) {
        self.plistPath = plistPath ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(LoginItem.label).plist")
        self.appPath = appPath
    }

    public func renderPlist() -> String {
        let dict: [String: Any] = [
            "Label": LoginItem.label,
            "ProgramArguments": ["/usr/bin/open", appPath],
            "RunAtLoad": true,
        ]
        let data = (try? PropertyListSerialization.data(
            fromPropertyList: dict, format: .xml, options: 0)) ?? Data()
        return String(data: data, encoding: .utf8) ?? ""
    }

    public var isInstalled: Bool {
        FileManager.default.fileExists(atPath: plistPath.path)
    }

    public func install() throws {
        try FileManager.default.createDirectory(
            at: plistPath.deletingLastPathComponent(), withIntermediateDirectories: true)
        try renderPlist().data(using: .utf8)!.write(to: plistPath)
    }

    public func remove() throws {
        if isInstalled { try FileManager.default.removeItem(at: plistPath) }
    }
}
```

`macos/Sources/NewbroExecutorCore/ProfileSupervisor.swift`:
```swift
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `swift test --package-path macos 2>&1 | tail -8`
Expected: all tests pass (31 total).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/LoginItem.swift macos/Sources/NewbroExecutorCore/ProfileSupervisor.swift macos/Tests/NewbroExecutorCoreTests/LoginItemTests.swift macos/Tests/NewbroExecutorCoreTests/ProfileSupervisorTests.swift
git commit -m "feat(macos): login item and concurrent profile supervisor"
```

---

### Task 8: SwiftUI app (menu bar, windows, wiring)

This task has no unit tests (SwiftUI views hold no logic). Verification is `swift build` success plus a manual launch. Build it incrementally and keep `AppModel` the only place that touches Core.

**Files:**
- Create: `macos/Sources/NewbroExecutor/AppModel.swift`,
  `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`,
  `macos/Sources/NewbroExecutor/MenuContent.swift`,
  `macos/Sources/NewbroExecutor/ProfileEditView.swift`,
  `macos/Sources/NewbroExecutor/LogView.swift`

- [ ] **Step 1: Create `AppModel.swift`**

```swift
import Foundation
import SwiftUI
import NewbroExecutorCore

@MainActor
final class AppModel: ObservableObject {
    @Published var profiles: [Profile] = []
    @Published var runtimeAvailable: Bool = true
    @Published var installLog: String = ""

    let supervisor: ProfileSupervisor
    private let store = ProfileStore()
    private var locator = RuntimeLocator()
    private let loginItem: LoginItem

    init() {
        let locatorRef = RuntimeLocator()
        self.locator = locatorRef
        self.loginItem = LoginItem(appPath: Bundle.main.bundlePath)
        self.supervisor = ProfileSupervisor(
            processFactory: .init(make: { argv, onLine, onExit in
                NodeProcess(argv: argv, onLine: onLine, onExit: onExit)
            }),
            argvBuilder: { profile in
                locatorRef.nodeArgv(for: profile) ?? []
            },
            logFactory: { profile in
                ProfileLog(path: ProfileLog.defaultPath(profileID: profile.id))
            })
        self.profiles = store.load()
        self.runtimeAvailable = locator.isRuntimeAvailable
    }

    func refreshRuntime() { runtimeAvailable = locator.isRuntimeAvailable }

    func autostart() {
        guard runtimeAvailable else { return }
        for profile in profiles where profile.autoActivate && isComplete(profile) {
            supervisor.start(profile)
        }
    }

    func isComplete(_ profile: Profile) -> Bool {
        !profile.baseURL.isEmpty && !profile.nodeID.isEmpty
            && !profile.token.isEmpty && !profile.enabledExecutors.isEmpty
    }

    func status(of profile: Profile) -> NodeStatus { supervisor.status(of: profile.id) }
    func aggregate() -> NodeStatus { supervisor.aggregateStatus() }
    func isActive(_ profile: Profile) -> Bool { supervisor.activeIDs().contains(profile.id) }
    func conflicts() -> Set<String> { conflictingProfileIDs(profiles) }

    func start(_ profile: Profile) {
        guard runtimeAvailable else { return }
        supervisor.start(profile)
    }
    func stop(_ profile: Profile) { supervisor.stop(profile.id) }
    func restart(_ profile: Profile) { supervisor.restart(profile) }

    func toggleAutoActivate(_ profile: Profile) {
        guard let index = profiles.firstIndex(where: { $0.id == profile.id }) else { return }
        profiles[index].autoActivate.toggle()
        try? store.save(profiles)
    }

    func delete(_ profile: Profile) {
        supervisor.stop(profile.id)
        profiles.removeAll { $0.id == profile.id }
        try? store.save(profiles)
    }

    func upsert(_ profile: Profile) {
        if let index = profiles.firstIndex(where: { $0.id == profile.id }) {
            profiles[index] = profile
        } else {
            profiles.append(profile)
        }
        try? store.save(profiles)
    }

    func addFromConnectCommand(_ text: String) throws {
        let fields = try parseConnectCommand(text)
        if let index = profiles.firstIndex(where: {
            $0.nodeID == fields.nodeID && $0.baseURL == fields.baseURL
        }) {
            profiles[index].token = fields.token
            profiles[index].enabledExecutors = fields.enabledExecutors
        } else {
            profiles.append(Profile(
                id: "profile-\(UUID().uuidString.prefix(8))",
                label: fields.baseURL, baseURL: fields.baseURL,
                nodeID: fields.nodeID, token: fields.token,
                enabledExecutors: fields.enabledExecutors))
        }
        try? store.save(profiles)
    }

    func recentLog(_ profile: Profile) -> [String] {
        ProfileLog(path: ProfileLog.defaultPath(profileID: profile.id)).recent()
    }

    // Login item
    var loginItemEnabled: Bool { loginItem.isInstalled }
    func toggleLoginItem() {
        if loginItem.isInstalled { try? loginItem.remove() } else { try? loginItem.install() }
        objectWillChange.send()
    }

    // Install runtime
    func installRuntime() {
        let argv = locator.installCommandArgv()
        installLog = "Installing…\n"
        let process = NodeProcess(
            argv: argv,
            onLine: { [weak self] line in
                Task { @MainActor in self?.installLog += line + "\n" }
            },
            onExit: { [weak self] _ in
                Task { @MainActor in self?.refreshRuntime() }
            })
        process.start()
    }

    func emptyProfile() -> Profile {
        Profile(id: "profile-\(UUID().uuidString.prefix(8))", label: "New profile",
                baseURL: "", nodeID: "", token: "")
    }
}
```

- [ ] **Step 2: Create `NewbroExecutorApp.swift`**

```swift
import SwiftUI
import AppKit
import NewbroExecutorCore

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}

@main
struct NewbroExecutorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model)
        } label: {
            Image(systemName: glyph(for: model.aggregate()))
        }
        .menuBarExtraStyle(.menu)

        WindowGroup("Edit Profile", id: "edit", for: String.self) { $profileID in
            ProfileEditView(model: model, profileID: profileID)
        }
        WindowGroup("Recent Log", id: "log", for: String.self) { $profileID in
            LogView(model: model, profileID: profileID)
        }
    }

    private func glyph(for status: NodeStatus) -> String {
        switch status {
        case .ready: return "circle.fill"
        case .connecting, .starting, .retrying: return "arrow.triangle.2.circlepath"
        case .disconnected, .error: return "exclamationmark.triangle.fill"
        case .stopped, .idle: return "circle"
        }
    }
}
```

- [ ] **Step 3: Create `MenuContent.swift`**

```swift
import SwiftUI
import NewbroExecutorCore

struct MenuContent: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if !model.runtimeAvailable {
            Text("Node runtime not found")
            Button("Install runtime…") { model.installRuntime() }
            Divider()
        }
        ForEach(model.profiles) { profile in
            let active = model.isActive(profile)
            let status = model.status(of: profile)
            let running = active && status != .stopped && status != .error
            Menu("\(profile.label) — \(status.rawValue)\(model.conflicts().contains(profile.id) ? "  (duplicate node id)" : "")") {
                if running {
                    Button("Stop") { model.stop(profile) }
                    Button("Restart") { model.restart(profile) }
                } else {
                    Button("Start") { model.start(profile) }
                }
                Toggle("Auto-activate at login", isOn: Binding(
                    get: { profile.autoActivate },
                    set: { _ in model.toggleAutoActivate(profile) }))
                Button("View recent log…") { openWindow(id: "log", value: profile.id) }
                Button("Edit…") { openWindow(id: "edit", value: profile.id) }
                Button("Delete") { model.delete(profile) }
            }
        }
        Divider()
        Button("Add profile…") {
            let new = model.emptyProfile()
            model.upsert(new)
            openWindow(id: "edit", value: new.id)
        }
        Button("Paste connect command…") { pasteConnectCommand() }
        Toggle("Launch at login", isOn: Binding(
            get: { model.loginItemEnabled },
            set: { _ in model.toggleLoginItem() }))
        Divider()
        Button("Quit") {
            model.supervisor.stopAll()
            NSApplication.shared.terminate(nil)
        }
    }

    private func pasteConnectCommand() {
        guard let text = NSPasteboard.general.string(forType: .string) else { return }
        try? model.addFromConnectCommand(text)
    }
}
```

- [ ] **Step 4: Create `ProfileEditView.swift`**

```swift
import SwiftUI
import NewbroExecutorCore

struct ProfileEditView: View {
    @ObservedObject var model: AppModel
    let profileID: String?
    @Environment(\.dismiss) private var dismiss

    @State private var label = ""
    @State private var baseURL = ""
    @State private var nodeID = ""
    @State private var token = ""
    @State private var codex = false
    @State private var acpx = false
    @State private var autoActivate = false

    var body: some View {
        Form {
            TextField("Label", text: $label)
            TextField("Base URL", text: $baseURL)
            TextField("Node ID", text: $nodeID)
            TextField("Token", text: $token)
            Toggle("codex", isOn: $codex)
            Toggle("acpx", isOn: $acpx)
            Toggle("Auto-activate at login", isOn: $autoActivate)
            HStack {
                Button("Cancel") { dismiss() }
                Button("Save") { save() }
            }
        }
        .padding(20)
        .frame(width: 380)
        .onAppear(perform: load)
    }

    private func load() {
        guard let id = profileID,
              let profile = model.profiles.first(where: { $0.id == id }) else { return }
        label = profile.label
        baseURL = profile.baseURL
        nodeID = profile.nodeID
        token = profile.token
        codex = profile.enabledExecutors.contains("codex")
        acpx = profile.enabledExecutors.contains("acpx")
        autoActivate = profile.autoActivate
    }

    private func save() {
        var executors: [String] = []
        if codex { executors.append("codex") }
        if acpx { executors.append("acpx") }
        let id = profileID ?? "profile-\(UUID().uuidString.prefix(8))"
        model.upsert(Profile(id: id, label: label, baseURL: baseURL, nodeID: nodeID,
                             token: token, enabledExecutors: executors, autoActivate: autoActivate))
        dismiss()
    }
}
```

- [ ] **Step 5: Create `LogView.swift`**

```swift
import SwiftUI
import NewbroExecutorCore

struct LogView: View {
    @ObservedObject var model: AppModel
    let profileID: String?

    var body: some View {
        ScrollView {
            Text(lines.joined(separator: "\n"))
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
        }
        .frame(width: 560, height: 360)
    }

    private var lines: [String] {
        guard let id = profileID,
              let profile = model.profiles.first(where: { $0.id == id }) else { return [] }
        let recent = model.recentLog(profile)
        return recent.isEmpty ? ["No log output yet."] : recent
    }
}
```

- [ ] **Step 6: Build and verify it compiles**

Run: `swift build --package-path macos 2>&1 | tail -20`
Expected: `Build complete!` (no errors). Fix any compile errors before continuing. Do NOT launch the GUI from the agent session (it blocks on the run loop) — the build success is the gate; the user launches it manually in Task 9.

- [ ] **Step 7: Commit**

```bash
git add macos/Sources/NewbroExecutor/
git commit -m "feat(macos): SwiftUI menu-bar app, edit/log windows, runtime self-heal"
```

---

### Task 9: package-app.sh bundle script + manual launch

**Files:**
- Create: `macos/package-app.sh`, `macos/README.md`

- [ ] **Step 1: Create `package-app.sh`**

```bash
#!/usr/bin/env bash
# Build Newbro Executor.app (menu-bar only) from the Swift package.
# The bundle is repo-independent: it resolves `newbro` at runtime.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/dist/Newbro Executor.app"
BIN_NAME="NewbroExecutor"

echo "[package-app] building release binary"
swift build -c release --package-path "$HERE"
BIN_PATH="$(swift build -c release --package-path "$HERE" --show-bin-path)/$BIN_NAME"

echo "[package-app] assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_PATH" "$APP/Contents/MacOS/$BIN_NAME"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Newbro Executor</string>
  <key>CFBundleDisplayName</key><string>Newbro Executor</string>
  <key>CFBundleIdentifier</key><string>com.newbro.executor-ui</string>
  <key>CFBundleExecutable</key><string>NewbroExecutor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

echo "[package-app] done: $APP"
```

- [ ] **Step 2: Make it executable and build the bundle**

Run:
```bash
chmod +x macos/package-app.sh
./macos/package-app.sh 2>&1 | tail -10
```
Expected: ends with `[package-app] done: …/macos/dist/Newbro Executor.app`. Confirm the bundle exists:
```bash
ls "macos/dist/Newbro Executor.app/Contents/MacOS/"
```
Expected: `NewbroExecutor`.

- [ ] **Step 3: Create `macos/README.md`**

```markdown
# Newbro Executor (macOS, SwiftUI)

Native menu-bar app that supervises `newbro executor run` node profiles.

## Build & run

```bash
swift test --package-path macos          # run the Core unit tests
./macos/package-app.sh                    # build dist/Newbro Executor.app
open "macos/dist/Newbro Executor.app"     # launch (menu-bar only, no Dock icon)
```

The app resolves the `newbro` CLI at runtime (override → `~/.local/bin/newbro`
→ login-shell `command -v newbro`). If `newbro` is missing, the menu shows
"Node runtime not found" with an "Install runtime…" action that runs the public
`install-newbro-cli.sh`. Per-executor binaries (codex/acpx) still need a one-time
`newbro executor setup`.

Profiles are stored in `~/.newbro/menubar.json`; logs in
`~/.newbro/logs/executor-ui-<id>.log`.
```

- [ ] **Step 4: Manual verification checklist (performed by the user)**

The agent cannot drive the GUI. Ask the user to run `open "macos/dist/Newbro Executor.app"` and confirm: a menu-bar glyph appears (no Dock icon); "Paste connect command…" adds a profile; Start launches a node and status reaches ready; Auto-activate toggle persists; Quit stops nodes (`pgrep -f "executor run"` empty). Record the result; do not block the commit on GUI verification.

- [ ] **Step 5: Commit**

```bash
git add macos/package-app.sh macos/README.md
git commit -m "build(macos): app bundle packaging script and README"
```

---

### Task 10: Remove the Python rumps app + update docs

**Files:**
- Delete: `src/newbro/executors/ui/`, `tests/unit/executors/ui/`, `src/newbro/cli/commands/executor_ui.py`, `packaging/menubar/`
- Modify: `src/newbro/cli/parser.py`, `src/newbro/cli/dispatch.py`, `pyproject.toml`, `docs/architecture/executors.md`, `docs/memories.md`
- Modify (superseded notes): the two earlier rumps spec/plan docs

- [ ] **Step 1: Remove the Python UI package, tests, command, packaging**

```bash
git rm -r src/newbro/executors/ui tests/unit/executors/ui src/newbro/cli/commands/executor_ui.py packaging/menubar
```

- [ ] **Step 2: Remove the `executor ui` subparser**

In `src/newbro/cli/parser.py`, delete the block added for the UI command:
```python
    executor_subparsers.add_parser(
        "ui",
        help="Launch the macOS menu-bar executor app (requires the 'macos-ui' extra).",
    )
```

- [ ] **Step 3: Remove the `ui` dispatch branch**

In `src/newbro/cli/dispatch.py`, restore `cmd_executor` to only handle setup/run:
```python
def cmd_executor(args: Any, app: Any) -> int:
    if args.executor_command == "setup":
        return setup_command.run_executor_setup(args, cli_factories.setup_context(app), cli_factories.setup_callbacks(app))
    if args.executor_command == "run":
        return run_command.run_executor(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))
    raise app.CliError(f"Unknown executor command: {args.executor_command}")
```

- [ ] **Step 4: Remove the macOS extras from pyproject**

In `pyproject.toml`, delete the `macos-ui` and `macos-ui-build` entries from
`[project.optional-dependencies]` (added in the rumps work), leaving `dev` and
`release` unchanged.

- [ ] **Step 5: Verify Python is clean (no dangling references)**

Run:
```bash
grep -rn "executors.ui\|executor_ui\|macos-ui\|packaging/menubar" src tests pyproject.toml || echo "no dangling references"
.venv/bin/python -m newbro executor --help 2>&1 | tail -5
.venv/bin/python -m pytest -q 2>&1 | tail -5
```
Expected: "no dangling references"; `executor --help` shows only `setup`/`run`, exit 0; full pytest suite passes.

- [ ] **Step 6: Update the architecture doc**

In `docs/architecture/executors.md`, replace the menu-bar app bullet (the one
starting "a macOS menu-bar app (`newbro executor ui`…") with:
```markdown
- a native macOS menu-bar app (SwiftUI, under `macos/`) supervises multiple
  executor-node profiles stored in `~/.newbro/menubar.json`. Each profile runs
  as an independent `newbro executor run` subprocess; several run concurrently.
  The app resolves the installed `newbro` CLI at runtime and only edits
  connection profiles — deeper executor runtime config stays owned by
  `newbro executor setup`. A rejected `node_id`/`token` shows as a continuous
  connecting/retrying state because the node service reconnects unboundedly.
```

- [ ] **Step 7: Append a memory note**

Append to `docs/memories.md`:
```markdown
- Replaced the Python rumps macOS menu-bar executor app with a native SwiftUI
  app under `macos/` (Swift package: `NewbroExecutorCore` logic + `NewbroExecutor`
  app). It supervises multiple concurrent `newbro executor run` profiles from
  `~/.newbro/menubar.json`, resolves the installed `newbro` CLI at runtime
  (`~/.local/bin/newbro`), and self-heals via the public `install-newbro-cli.sh`.
```

- [ ] **Step 8: Add superseded notes to the rumps spec/plan**

At the top of `docs/superpowers/specs/2026-06-01-macos-executor-menubar-app-design.md`
and `docs/superpowers/plans/2026-06-01-macos-executor-menubar-app.md`, add a line
just under the H1 title:
```markdown
> Superseded by the native SwiftUI rewrite
> (`2026-06-01-macos-executor-swiftui-design.md`). Kept for history.
```

- [ ] **Step 9: Final full verification**

Run:
```bash
swift test --package-path macos 2>&1 | tail -5
.venv/bin/python -m pytest -q 2>&1 | tail -5
```
Expected: Swift tests pass (31); Python suite passes.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor(macos): remove Python rumps app in favor of SwiftUI; update docs"
```

---

## Self-Review

**Spec coverage:**
- Multiple concurrent profiles, one subprocess each → Tasks 4 (`NodeProcess`), 7 (`ProfileSupervisor`), 8 (`AppModel`/`RuntimeLocator.nodeArgv`).
- Run/stop/restart + live status → Tasks 3, 4, 7, 8.
- Paste connect command + add/edit/delete → Tasks 2, 8 (`MenuContent`, `ProfileEditView`, `AppModel`).
- Auto-activate + login item + launch at login → Tasks 7 (`LoginItem`), 8 (`AppModel.autostart`, toggles).
- Status parsing from real node prefixes → Task 3.
- Zero-config runtime resolution + install self-heal → Task 6 (`RuntimeLocator`), Task 8 (`installRuntime`, runtime-missing UI).
- Node invoked via `newbro executor run` → Task 6 (`nodeArgv`), Task 8 (`argvBuilder`).
- Menu-bar only (`LSUIElement` + `.accessory`) → Task 8 (`AppDelegate`), Task 9 (Info.plist).
- Logs + view-log window → Tasks 5, 8 (`LogView`).
- Duplicate node_id annotation → Tasks 2, 8 (`MenuContent`).
- Build via SwiftPM + bundle script → Tasks 1, 9.
- Reuse `~/.newbro/menubar.json` snake_case → Task 1 (`Profile` CodingKeys, `ProfileStore`).
- Removal of Python UI + docs/superseded notes → Task 10.
- XCTest coverage of Core units → Tasks 1–7.

**Placeholder scan:** none — every step has concrete Swift/bash code or exact commands.

**Type consistency:** `Profile(id:label:baseURL:nodeID:token:enabledExecutors:autoActivate:)`, `ProfileStore(path:)`, `parseConnectCommand`/`ConnectCommandFields`/`conflictingProfileIDs`, `NodeStatus`/`StatusParser.onStart/onLine/onExit(code:expected:)`/`aggregateStatus`, `NodeProcessProtocol.start()/stop(timeout:)/isRunning` + `NodeProcess(argv:onLine:onExit:)`, `ProfileLogging.append`/`ProfileLog(path:maxLines:)`/`defaultPath(profileID:)`, `RuntimeLocator(overridePath:homeDir:fileExists:whichNewbro:)`/`resolveNewbro`/`isRuntimeAvailable`/`nodeArgv(for:)`/`installCommandArgv`, `LoginItem(plistPath:appPath:)`/`label`/`renderPlist`/`isInstalled`/`install`/`remove`, `ProfileSupervisor(processFactory:argvBuilder:logFactory:)` + `ProcessFactory.make` + `start/stop/restart/stopAll/status(of:)/aggregateStatus/activeIDs` are used identically across tasks and between Core and the app target.

**Intentional carry-over from the rumps design (documented):** no process-restart loop (the node owns reconnection); bad credentials surface as persistent retrying, not error; lightweight `isComplete` check rather than the Python setup resolver.
