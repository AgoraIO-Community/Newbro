# macOS App Onboarding Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the macOS menu-bar app self-heal around detectable Codex, simplify profile onboarding, prevent duplicate profiles, auto-start pasted profiles, notify lifecycle events, and harden update display.

**Architecture:** Keep executor runtime ownership in the Python CLI. The Swift app remains a supervisor/config editor: it probes local runtime readiness, renders menu state, manages profile lifecycle, and delegates actual execution to `newbro executor run`. Profile identity and lifecycle rules live in `NewbroExecutorCore` where they can be unit-tested headlessly.

**Tech Stack:** Python 3.12, pytest, Swift 5.9, XCTest, AppKit, UserNotifications.

---

## File Structure

- Modify `src/newbro/cli/setup_resolvers.py`: add pure Codex auto-config resolution.
- Modify `src/newbro/cli/main.py`: call non-interactive Codex auto-config before raising the current no-TTY incomplete-runtime error.
- Modify `tests/unit/cli/test_main.py`: cover non-TTY Codex auto-config, missing Codex error, and TTY behavior.
- Modify `macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`: add testable Codex detection/version probing.
- Modify `macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`: cover Codex status rows and version parsing.
- Modify `macos/Sources/NewbroExecutorCore/ConnectCommand.swift`: add normalized profile identity and unique id helpers.
- Modify `macos/Tests/NewbroExecutorCoreTests/ConnectCommandTests.swift`: cover trailing-slash matching and duplicate detection.
- Modify `macos/Sources/NewbroExecutorCore/ProfileSupervisor.swift`: emit lifecycle events for start/stop/error and support restart after paste.
- Modify `macos/Tests/NewbroExecutorCoreTests/ProfileSupervisorTests.swift`: cover lifecycle events.
- Modify `macos/Sources/NewbroExecutor/AppModel.swift`: remove manual profile creation path, auto-start/restart pasted profiles, gate start on Codex warning, and send notifications.
- Create `macos/Sources/NewbroExecutor/ProfileNotifier.swift`: macOS `UNUserNotificationCenter` wrapper.
- Modify `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`: remove `Add profile...`, add Codex runtime row, improve update rows.
- Modify `macos/Sources/NewbroExecutorCore/ReleaseClient.swift`: switch to `AgoraIO-Community/Newbro`.
- Modify `macos/Tests/NewbroExecutorCoreTests/ReleaseClientTests.swift`: assert correct release URL.
- Modify `docs/architecture/executors.md`, `docs/guides/cli.md`, `macos/README.md`, `docs/memories.md`: document adopted behavior.

---

### Task 1: Python CLI Codex Auto-Configuration

**Files:**
- Modify: `src/newbro/cli/setup_resolvers.py`
- Modify: `src/newbro/cli/main.py`
- Test: `tests/unit/cli/test_main.py`

- [ ] **Step 1: Write failing tests for non-TTY Codex auto-config**

Append these tests near the existing executor runtime setup tests in `tests/unit/cli/test_main.py`:

```python
def test_executor_run_auto_configures_detected_codex_without_tty(monkeypatch, tmp_path: Path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: False)
    monkeypatch.setattr(cli_main, "_detected_codex_command", lambda: "codex")
    monkeypatch.setattr(cli_main, "_command_available", lambda command: command == "codex")
    monkeypatch.setattr(
        cli_main.subprocess,
        "run",
        lambda *_args, **_kwargs: FakeCompletedProcess(returncode=130),
    )

    assert (
        cli_main.main(
            [
                "executor",
                "run",
                "--base-url",
                "http://127.0.0.1:8000",
                "--node-id",
                "node-1",
                "--token",
                "token-1",
                "--enabled-executor",
                "codex",
            ]
        )
        == 130
    )

    config_text = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert "enabled_executors:" in config_text
    assert "  - codex" in config_text
    assert "executors:" in config_text
    assert "  codex:" in config_text
    assert "    command: codex" in config_text


def test_executor_run_does_not_auto_configure_missing_codex_without_tty(monkeypatch, tmp_path: Path, capsys):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_main, "setup_can_prompt", lambda: False)
    monkeypatch.setattr(cli_main, "_detected_codex_command", lambda: None)
    monkeypatch.setattr(cli_main, "_command_available", lambda _command: False)

    assert (
        cli_main.main(
            [
                "executor",
                "run",
                "--base-url",
                "http://127.0.0.1:8000",
                "--node-id",
                "node-1",
                "--token",
                "token-1",
                "--enabled-executor",
                "codex",
            ]
        )
        == 1
    )
    assert "Local executor runtime config is incomplete." in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m pytest tests/unit/cli/test_main.py::test_executor_run_auto_configures_detected_codex_without_tty tests/unit/cli/test_main.py::test_executor_run_does_not_auto_configure_missing_codex_without_tty -q
```

Expected: first test fails because config is not auto-written; second test should already pass or continue passing.

- [ ] **Step 3: Add auto-config resolver**

In `src/newbro/cli/setup_resolvers.py`, add this dataclass near the existing setup result dataclasses:

```python
@dataclass(slots=True)
class CodexAutoSetupResult:
    setup: ConnectorSetupResult
    command: str
```

Then add this function after `resolve_executor_setup_values`:

```python
def resolve_codex_auto_setup_values(
    *,
    existing_config_yaml: dict[str, object],
    callbacks: SetupResolutionCallbacks,
) -> CodexAutoSetupResult | None:
    command = callbacks.detected_codex_command()
    if not command or not callbacks.command_available(command):
        return None

    executors_block = callbacks.existing_executors_config(existing_config_yaml)
    codex_block = dict(executors_block.get("codex", {}))
    codex_block["command"] = command
    codex_block.setdefault("blocked_wait_timeout_seconds", 900.0)
    executors_block["codex"] = codex_block

    return CodexAutoSetupResult(
        command=command,
        setup=ConnectorSetupResult(
            env_values={},
            config_path=callbacks.connector_config_path(),
            config_text=callbacks.render_connector_config(
                runtime=callbacks.existing_runtime_config(existing_config_yaml),
                connector_host=callbacks.existing_connector_host_config(existing_config_yaml),
                connectors=callbacks.existing_connectors_config(existing_config_yaml),
                executor_node={"enabled_executors": ["codex"]},
                executors={
                    key: value
                    for key, value in executors_block.items()
                    if key == "codex"
                },
            ),
        ),
    )
```

- [ ] **Step 4: Wire auto-config into missing-runtime branch**

In `src/newbro/cli/main.py`, add:

```python
def _can_auto_configure_codex(
    existing_config_yaml: dict[str, object],
    *,
    enabled_executors_override: list[str] | None,
) -> bool:
    selected = enabled_executors_override or config_files.existing_executor_enabled_types(existing_config_yaml) or ["codex"]
    return selected == ["codex"]


def _try_auto_configure_codex_executor_runtime(
    existing_config_yaml: dict[str, object],
    *,
    enabled_executors_override: list[str] | None,
) -> bool:
    if not _can_auto_configure_codex(
        existing_config_yaml,
        enabled_executors_override=enabled_executors_override,
    ):
        return False
    result = setup_resolvers.resolve_codex_auto_setup_values(
        existing_config_yaml=existing_config_yaml,
        callbacks=_setup_resolution_callbacks(),
    )
    if result is None:
        return False
    config_files.write_connector_config_if_needed(
        result.setup,
        format_user_path=format_user_path,
    )
    print(f"[setup] auto-configured codex executor command: {result.command}")
    return True
```

Then change `_ensure_executor_runtime_configured_for_run` so the no-TTY branch becomes:

```python
    if not setup_can_prompt():
        if _try_auto_configure_codex_executor_runtime(
            existing_config_yaml,
            enabled_executors_override=enabled_executors_override,
        ):
            refreshed_values, _ = config_files.load_env_assignments(ENV_LOCAL)
            refreshed_config_yaml = config_files.load_existing_connector_yaml(connector_config_path())
            if _executor_runtime_config_complete(
                refreshed_config_yaml,
                refreshed_values,
                enabled_executors_override=enabled_executors_override,
            ):
                return
        raise CliError(
            f"Local executor runtime config is incomplete. Run `{cli_invocation} executor setup` "
            f"or rerun `{cli_invocation} executor run ...` in a TTY."
        )
```

- [ ] **Step 5: Run focused CLI tests**

Run:

```bash
python3 -m pytest tests/unit/cli/test_main.py::test_executor_run_auto_configures_detected_codex_without_tty tests/unit/cli/test_main.py::test_executor_run_does_not_auto_configure_missing_codex_without_tty tests/unit/cli/test_main.py::test_executor_run_triggers_setup_when_local_runtime_config_missing tests/unit/cli/test_main.py::test_executor_run_requires_tty_when_local_runtime_config_missing -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/cli/setup_resolvers.py src/newbro/cli/main.py tests/unit/cli/test_main.py
git commit -m "feat(cli): auto-configure detected codex executor"
```

---

### Task 2: Swift Runtime Probe And Release Source

**Files:**
- Modify: `macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`
- Modify: `macos/Sources/NewbroExecutorCore/ReleaseClient.swift`
- Modify: `macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`
- Modify: `macos/Tests/NewbroExecutorCoreTests/ReleaseClientTests.swift`

- [ ] **Step 1: Write failing RuntimeLocator tests**

Append to `macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`:

```swift
func testCodexStatusReportsVersion() {
    let locator = RuntimeLocator(
        overridePath: nil,
        homeDir: home,
        fileExists: { _ in false },
        whichNewbro: { nil },
        whichCommand: { name in name == "codex" ? "/opt/bin/codex" : nil },
        runCommand: { argv, _ in
            XCTAssertEqual(argv, ["/opt/bin/codex", "--version"])
            return (0, "codex 0.42.0\n")
        })
    XCTAssertEqual(locator.codexRuntimeStatus().menuTitle, "Codex v0.42.0")
    XCTAssertTrue(locator.codexRuntimeStatus().isAvailable)
}

func testCodexStatusWarnsWhenMissing() {
    let locator = RuntimeLocator(
        overridePath: nil,
        homeDir: home,
        fileExists: { _ in false },
        whichNewbro: { nil },
        whichCommand: { _ in nil },
        runCommand: { _, _ in (1, "") })
    XCTAssertEqual(locator.codexRuntimeStatus().menuTitle, "No Codex found. Newbro may not work properly.")
    XCTAssertFalse(locator.codexRuntimeStatus().isAvailable)
}
```

- [ ] **Step 2: Write failing ReleaseClient URL test**

Append to `macos/Tests/NewbroExecutorCoreTests/ReleaseClientTests.swift`:

```swift
func testLatestURLUsesCommunityNewbroRepository() {
    XCTAssertEqual(
        ReleaseClient.latestURL.absoluteString,
        "https://api.github.com/repos/AgoraIO-Community/Newbro/releases/latest")
}
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
swift test --package-path macos --filter RuntimeLocatorTests/testCodexStatusReportsVersion --filter RuntimeLocatorTests/testCodexStatusWarnsWhenMissing --filter ReleaseClientTests/testLatestURLUsesCommunityNewbroRepository
```

Expected: fails because `RuntimeLocator` lacks the new initializer/API and release URL still points at `AgoraIO/Synopse`.

- [ ] **Step 4: Implement runtime probe**

In `macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`, add:

```swift
public struct CommandStatus: Equatable, Sendable {
    public let command: String?
    public let version: String?
    public let menuTitle: String
    public let isAvailable: Bool
}
```

Update stored properties and initializer:

```swift
private let whichCommand: (String) -> String?
private let runCommand: ([String], [String: String]?) -> (Int32, String)

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
```

Add methods:

```swift
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

public static func extractVersion(_ output: String) -> String? {
    output
        .split(whereSeparator: { $0.isWhitespace })
        .last
        .map(String.init)
}

public static func loginShellWhichCommand(_ name: String) -> String? {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
    proc.arguments = ["-lc", "command -v \(name)"]
    let pipe = Pipe()
    proc.standardOutput = pipe
    proc.standardError = FileHandle.nullDevice
    do { try proc.run() } catch { return nil }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    proc.waitUntilExit()
    let output = String(data: data, encoding: .utf8)?
        .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    return output.isEmpty ? nil : output
}

public static func runCommandOutput(_ argv: [String], _ environment: [String: String]?) -> (Int32, String) {
    guard let executable = argv.first else { return (127, "") }
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: executable)
    proc.arguments = Array(argv.dropFirst())
    if let environment { proc.environment = environment }
    let pipe = Pipe()
    proc.standardOutput = pipe
    proc.standardError = pipe
    do { try proc.run() } catch { return (127, "") }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    proc.waitUntilExit()
    return (proc.terminationStatus, String(data: data, encoding: .utf8) ?? "")
}
```

- [ ] **Step 5: Update release URL**

In `macos/Sources/NewbroExecutorCore/ReleaseClient.swift`, change:

```swift
"https://api.github.com/repos/AgoraIO/Synopse/releases/latest"
```

to:

```swift
"https://api.github.com/repos/AgoraIO-Community/Newbro/releases/latest"
```

- [ ] **Step 6: Run focused Swift tests**

Run:

```bash
swift test --package-path macos --filter RuntimeLocatorTests
swift test --package-path macos --filter ReleaseClientTests
```

Expected: both suites pass.

- [ ] **Step 7: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/RuntimeLocator.swift macos/Sources/NewbroExecutorCore/ReleaseClient.swift macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift macos/Tests/NewbroExecutorCoreTests/ReleaseClientTests.swift
git commit -m "feat(macos): probe codex runtime status"
```

---

### Task 3: Profile Identity And Paste Lifecycle Rules

**Files:**
- Modify: `macos/Sources/NewbroExecutorCore/ConnectCommand.swift`
- Modify: `macos/Sources/NewbroExecutor/AppModel.swift`
- Modify: `macos/Tests/NewbroExecutorCoreTests/ConnectCommandTests.swift`

- [ ] **Step 1: Write failing identity tests**

Append to `macos/Tests/NewbroExecutorCoreTests/ConnectCommandTests.swift`:

```swift
func testNormalizedProfileIdentityTrimsTrailingSlash() {
    XCTAssertEqual(
        normalizedProfileIdentity(baseURL: " https://x.example/ ", nodeID: " node-1 "),
        normalizedProfileIdentity(baseURL: "https://x.example", nodeID: "node-1"))
}

func testFirstMatchingProfileIndexUsesNormalizedIdentity() {
    let profiles = [
        Profile(id: "p1", label: "A", baseURL: "https://x.example/", nodeID: "node-1", token: "old"),
        Profile(id: "p2", label: "B", baseURL: "https://x.example", nodeID: "node-2", token: "old"),
    ]
    XCTAssertEqual(firstMatchingProfileIndex(in: profiles, baseURL: "https://x.example", nodeID: "node-1"), 0)
}

func testGeneratedProfileIDSkipsExistingIDs() {
    let profiles = [
        Profile(id: "profile-a", label: "A", baseURL: "https://a", nodeID: "n", token: "t"),
    ]
    var values = ["profile-a", "profile-b"]
    let generated = uniqueProfileID(existing: profiles) {
        values.removeFirst()
    }
    XCTAssertEqual(generated, "profile-b")
}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
swift test --package-path macos --filter ConnectCommandTests
```

Expected: fails because helper functions do not exist.

- [ ] **Step 3: Implement identity helpers**

In `macos/Sources/NewbroExecutorCore/ConnectCommand.swift`, replace `conflictingProfileIDs` key construction and add helpers:

```swift
public func normalizedBaseURL(_ value: String) -> String {
    var text = value.trimmingCharacters(in: .whitespacesAndNewlines)
    while text.hasSuffix("/") { text.removeLast() }
    return text
}

public func normalizedProfileIdentity(baseURL: String, nodeID: String) -> String {
    normalizedBaseURL(baseURL) + "\u{0}" + nodeID.trimmingCharacters(in: .whitespacesAndNewlines)
}

public func firstMatchingProfileIndex(in profiles: [Profile], baseURL: String, nodeID: String) -> Int? {
    let target = normalizedProfileIdentity(baseURL: baseURL, nodeID: nodeID)
    return profiles.firstIndex {
        normalizedProfileIdentity(baseURL: $0.baseURL, nodeID: $0.nodeID) == target
    }
}

public func uniqueProfileID(existing profiles: [Profile],
                            generate: () -> String = { "profile-\(UUID().uuidString.prefix(8))" }) -> String {
    let existingIDs = Set(profiles.map(\.id))
    while true {
        let candidate = generate()
        if !existingIDs.contains(candidate) { return candidate }
    }
}
```

Then update `conflictingProfileIDs`:

```swift
let key = normalizedProfileIdentity(baseURL: profile.baseURL, nodeID: profile.nodeID)
```

- [ ] **Step 4: Update AppModel paste logic**

In `macos/Sources/NewbroExecutor/AppModel.swift`, replace `addFromConnectCommand(_:)` with:

```swift
@discardableResult
func addFromConnectCommand(_ text: String) throws -> Profile {
    let fields = try parseConnectCommand(text)
    let profile: Profile
    if let index = firstMatchingProfileIndex(in: profiles, baseURL: fields.baseURL, nodeID: fields.nodeID) {
        profiles[index].token = fields.token
        profiles[index].enabledExecutors = fields.enabledExecutors
        profile = profiles[index]
    } else {
        profile = Profile(
            id: uniqueProfileID(existing: profiles),
            label: fields.baseURL,
            baseURL: fields.baseURL,
            nodeID: fields.nodeID,
            token: fields.token,
            enabledExecutors: fields.enabledExecutors)
        profiles.append(profile)
    }
    try? store.save(profiles)
    autoStartPastedProfile(profile)
    return profile
}

private func autoStartPastedProfile(_ profile: Profile) {
    guard runtimeAvailable, isComplete(profile), canStart(profile) else { return }
    if isActive(profile) {
        restart(profile)
    } else {
        start(profile)
    }
}

func canStart(_ profile: Profile) -> Bool {
    if profile.enabledExecutors.contains("codex") {
        return locator.codexRuntimeStatus().isAvailable
    }
    return true
}
```

Then change `start(_:)` and `restart(_:)` guards:

```swift
func start(_ profile: Profile) {
    guard runtimeAvailable, canStart(profile) else { return }
    supervisor.start(profile)
}

func restart(_ profile: Profile) {
    guard runtimeAvailable, canStart(profile) else { return }
    controlQueue.async { [supervisor] in supervisor.restart(profile) }
}
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
swift test --package-path macos --filter ConnectCommandTests
```

Expected: all `ConnectCommandTests` pass.

- [ ] **Step 6: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/ConnectCommand.swift macos/Sources/NewbroExecutor/AppModel.swift macos/Tests/NewbroExecutorCoreTests/ConnectCommandTests.swift
git commit -m "feat(macos): coalesce pasted profiles"
```

---

### Task 4: Lifecycle Events And Notifications

**Files:**
- Modify: `macos/Sources/NewbroExecutorCore/ProfileSupervisor.swift`
- Modify: `macos/Tests/NewbroExecutorCoreTests/ProfileSupervisorTests.swift`
- Create: `macos/Sources/NewbroExecutor/ProfileNotifier.swift`
- Modify: `macos/Sources/NewbroExecutor/AppModel.swift`

- [ ] **Step 1: Write failing ProfileSupervisor event test**

Append to `macos/Tests/NewbroExecutorCoreTests/ProfileSupervisorTests.swift`:

```swift
func testLifecycleEventsForStartStopAndError() {
    var events: [ProfileLifecycleEvent] = []
    created = []
    let factory = ProfileSupervisor.ProcessFactory { _, onLine, onExit in
        let fake = FakeProcess(onLine: onLine, onExit: onExit)
        self.created.append(fake)
        return fake
    }
    let sup = ProfileSupervisor(
        processFactory: factory,
        argvBuilder: { ["run", $0.nodeID] },
        onEvent: { events.append($0) })

    let p = profile()
    sup.start(p)
    XCTAssertEqual(events, [.started(profileID: "p1", label: "p1")])
    sup.stop("p1")
    created[0].onExit(0)
    XCTAssertEqual(events.last, .stopped(profileID: "p1", label: "p1"))

    sup.start(p)
    created[1].onExit(1)
    XCTAssertEqual(events.last, .error(profileID: "p1", label: "p1", exitCode: 1))
}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
swift test --package-path macos --filter ProfileSupervisorTests/testLifecycleEventsForStartStopAndError
```

Expected: fails because `ProfileLifecycleEvent` and `onEvent` do not exist.

- [ ] **Step 3: Implement lifecycle event emission**

In `macos/Sources/NewbroExecutorCore/ProfileSupervisor.swift`, add:

```swift
public enum ProfileLifecycleEvent: Equatable, Sendable {
    case started(profileID: String, label: String)
    case stopped(profileID: String, label: String)
    case error(profileID: String, label: String, exitCode: Int32)
}
```

Add property and initializer parameter:

```swift
private let onEvent: ((ProfileLifecycleEvent) -> Void)?

public init(processFactory: ProcessFactory,
            argvBuilder: @escaping (Profile) -> [String],
            logFactory: ((Profile) -> ProfileLogging?)? = nil,
            onEvent: ((ProfileLifecycleEvent) -> Void)? = nil) {
    self.processFactory = processFactory
    self.argvBuilder = argvBuilder
    self.logFactory = logFactory
    self.onEvent = onEvent
}
```

At the end of `start(_:)`, after `notifyChange()`:

```swift
onEvent?(.started(profileID: profile.id, label: profile.label))
```

In `handleExit`, capture event while locked:

```swift
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
```

Then after unlock and `notifyChange()`:

```swift
onEvent?(event)
```

- [ ] **Step 4: Create macOS notifier**

Create `macos/Sources/NewbroExecutor/ProfileNotifier.swift`:

```swift
import Foundation
import UserNotifications

@MainActor
protocol ProfileNotifying {
    func notify(title: String, body: String)
}

@MainActor
final class MacProfileNotifier: ProfileNotifying {
    private let center: UNUserNotificationCenter

    init(center: UNUserNotificationCenter = .current()) {
        self.center = center
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func notify(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        let request = UNNotificationRequest(
            identifier: "newbro-profile-\(UUID().uuidString)",
            content: content,
            trigger: nil)
        center.add(request)
    }
}
```

- [ ] **Step 5: Wire notifications in AppModel**

In `macos/Sources/NewbroExecutor/AppModel.swift`, add:

```swift
private let notifier: ProfileNotifying
```

Change `init()` signature:

```swift
init(notifier: ProfileNotifying = MacProfileNotifier()) {
    self.notifier = notifier
    ...
```

When constructing `ProfileSupervisor`, add:

```swift
onEvent: { event in
    Task { @MainActor in
        switch event {
        case let .started(_, label):
            notifier.notify(title: "Profile started", body: label)
        case let .stopped(_, label):
            notifier.notify(title: "Profile stopped", body: label)
        case let .error(_, label, _):
            notifier.notify(title: "Profile error", body: label)
        }
    }
}
```

In `addFromConnectCommand(_:)`, track whether create or update occurred and whether auto-start/restart was requested, then emit exactly one paste notification:

```swift
let wasUpdate = firstMatchingProfileIndex(in: profiles, baseURL: fields.baseURL, nodeID: fields.nodeID) != nil
...
notifier.notify(
    title: pasteNotificationTitle(wasUpdate: wasUpdate, started: didRequestStart),
    body: profile.label)
```

Add this helper in `AppModel.swift`:

```swift
private func pasteNotificationTitle(wasUpdate: Bool, started: Bool) -> String {
    switch (wasUpdate, started) {
    case (false, true): return "Profile created and started"
    case (false, false): return "Profile created"
    case (true, true): return "Profile updated and started"
    case (true, false): return "Profile updated"
    }
}
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
swift test --package-path macos --filter ProfileSupervisorTests
```

Expected: all profile supervisor tests pass.

- [ ] **Step 7: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/ProfileSupervisor.swift macos/Tests/NewbroExecutorCoreTests/ProfileSupervisorTests.swift macos/Sources/NewbroExecutor/ProfileNotifier.swift macos/Sources/NewbroExecutor/AppModel.swift
git commit -m "feat(macos): notify profile lifecycle events"
```

---

### Task 5: Menu Simplification And Update Rows

**Files:**
- Modify: `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`
- Modify: `macos/Sources/NewbroExecutor/AppModel.swift`
- Modify: `macos/Sources/NewbroExecutorCore/UpdateStatus.swift`
- Modify: `macos/Tests/NewbroExecutorCoreTests/UpdateStatusTests.swift`

- [ ] **Step 1: Write failing update display model tests**

Append to `macos/Tests/NewbroExecutorCoreTests/UpdateStatusTests.swift`:

```swift
func testComponentVersionRows() {
    let rows = updateMenuRows(installedCLI: "0.1.0", installedApp: "0.1.0", status: UpdateStatus(cliUpdate: "v0.2.0", appUpdate: "v0.2.0"))
    XCTAssertEqual(rows.cliVersionRow, "newbro CLI v0.1.0")
    XCTAssertEqual(rows.appVersionRow, "App v0.1.0")
    XCTAssertEqual(rows.cliUpdateRow, "CLI update available: v0.2.0")
    XCTAssertEqual(rows.appUpdateRow, "App update available: v0.2.0")
}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
swift test --package-path macos --filter UpdateStatusTests/testComponentVersionRows
```

Expected: fails because `updateMenuRows` does not exist.

- [ ] **Step 3: Implement menu row helper**

In `macos/Sources/NewbroExecutorCore/UpdateStatus.swift`, add:

```swift
public struct UpdateMenuRows: Equatable, Sendable {
    public let cliVersionRow: String
    public let appVersionRow: String
    public let cliUpdateRow: String?
    public let appUpdateRow: String?
}

public func updateMenuRows(installedCLI: String?, installedApp: String?, status: UpdateStatus) -> UpdateMenuRows {
    UpdateMenuRows(
        cliVersionRow: installedCLI.map { "newbro CLI v\($0)" } ?? "newbro CLI version unknown",
        appVersionRow: installedApp.map { "App v\($0)" } ?? "App version unknown",
        cliUpdateRow: status.cliUpdate.map { "CLI update available: \($0)" },
        appUpdateRow: status.appUpdate.map { "App update available: \($0)" })
}
```

- [ ] **Step 4: Expose Codex runtime title from AppModel**

In `macos/Sources/NewbroExecutor/AppModel.swift`, add:

```swift
@Published var codexStatus = CommandStatus(
    command: nil,
    version: nil,
    menuTitle: "No Codex found. Newbro may not work properly.",
    isAvailable: false)
```

In `init()`, after runtime resolution:

```swift
self.codexStatus = locator.codexRuntimeStatus()
```

In `refreshRuntime()`:

```swift
func refreshRuntime() {
    runtimeAvailable = locator.isRuntimeAvailable
    codexStatus = locator.codexRuntimeStatus()
}
```

- [ ] **Step 5: Simplify menu**

In `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`:

Remove:

```swift
menu.addItem(ActionMenuItem(title: "Add profile…") { [weak self] in self?.model.addProfile() })
```

Add a disabled Codex status row before profile rows:

```swift
let codexRow = NSMenuItem(title: model.codexStatus.menuTitle, action: nil, keyEquivalent: "")
codexRow.isEnabled = false
menu.addItem(codexRow)
menu.addItem(.separator())
```

Replace the update status construction with:

```swift
let rows = updateMenuRows(
    installedCLI: updates.installedCLI,
    installedApp: model.appVersion,
    status: updates.status)
for title in [rows.cliVersionRow, rows.appVersionRow] {
    let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
    item.isEnabled = false
    menu.addItem(item)
}
if updates.isUpdating {
    let item = NSMenuItem(title: "Updating CLI…", action: nil, keyEquivalent: "")
    item.isEnabled = false
    menu.addItem(item)
} else if let title = rows.cliUpdateRow {
    let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
    item.isEnabled = false
    menu.addItem(item)
}
```

Keep `Update CLI to ...`, `Check for Updates...`, and `Download app update ...` actions.

- [ ] **Step 6: Remove dead manual-add API**

Delete these methods from `macos/Sources/NewbroExecutor/AppModel.swift`:

```swift
func addProfile() {
    let new = emptyProfile()
    upsert(new)
    editProfile(new.id)
}

func emptyProfile() -> Profile {
    Profile(id: "profile-\(UUID().uuidString.prefix(8))", label: "New profile",
            baseURL: "", nodeID: "", token: "")
}
```

Run:

```bash
rg "addProfile|emptyProfile" macos
```

Expected: no matches.

- [ ] **Step 7: Run Swift tests**

Run:

```bash
swift test --package-path macos
```

Expected: all Swift tests pass.

- [ ] **Step 8: Commit**

```bash
git add macos/Sources/NewbroExecutor/NewbroExecutorApp.swift macos/Sources/NewbroExecutor/AppModel.swift macos/Sources/NewbroExecutorCore/UpdateStatus.swift macos/Tests/NewbroExecutorCoreTests/UpdateStatusTests.swift
git commit -m "feat(macos): simplify onboarding menu"
```

---

### Task 6: Stable Docs And Memory

**Files:**
- Modify: `docs/architecture/executors.md`
- Modify: `docs/guides/cli.md`
- Modify: `macos/README.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Update executor architecture doc**

In `docs/architecture/executors.md`, update the macOS app bullet to mention:

```markdown
  The app probes Codex during launch, displays the detected Codex version or
  `No Codex found. Newbro may not work properly.`, and relies on the CLI to
  auto-configure the minimal Codex executor runtime when Codex is detectable.
  `newbro executor setup` remains the advanced/recovery path for custom Codex
  paths, ACPX, and broken local config.
```

- [ ] **Step 2: Update CLI guide**

In `docs/guides/cli.md`, under "Detached Executor Nodes", add:

```markdown
For the macOS menu-bar app, `newbro executor setup` is not required on the
happy path when Codex is already installed and discoverable. On first
`newbro executor run`, a non-interactive app launch may auto-write the minimal
Codex executor config. Use `newbro executor setup` for custom Codex paths,
ACPX, or recovery when Codex is not on the app/login-shell PATH.
```

- [ ] **Step 3: Update macOS README**

In `macos/README.md`, replace the sentence saying per-executor binaries still need a one-time setup with:

```markdown
On launch the app probes `codex` through the login-shell PATH. If Codex is
found, the menu shows its version and the CLI can auto-write the minimal Codex
executor config on first run. If Codex is not found, the menu shows
"No Codex found. Newbro may not work properly." Use `newbro executor setup`
for custom Codex paths, ACPX, or recovery.
```

- [ ] **Step 4: Append memory note**

Append to `docs/memories.md`:

```markdown
- Updated the macOS executor app onboarding contract: the app probes Codex on launch, shows the detected Codex version or a missing-Codex warning, and pasted connect-command profiles are coalesced by normalized `(base_url, node_id)`, auto-started/restarted when possible, and surfaced through lifecycle notifications. The CLI may auto-configure minimal Codex executor runtime in non-interactive runs when Codex is detectable; `newbro executor setup` remains the advanced/recovery path.
```

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/executors.md docs/guides/cli.md macos/README.md docs/memories.md
git commit -m "docs: update macos executor onboarding contract"
```

---

### Task 7: Final Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run Swift suite**

Run:

```bash
swift test --package-path macos
```

Expected: all Swift tests pass.

- [ ] **Step 2: Run Python focused suite**

Run:

```bash
python3 -m pytest tests/unit/cli/test_version.py tests/unit/cli/test_main.py -q
```

Expected: all selected Python tests pass. If the environment lacks `pytest`, create/use the repo virtualenv with `./install.sh` or report the missing dependency explicitly.

- [ ] **Step 3: Package the app**

Run:

```bash
./macos/package-app.sh
```

Expected: `macos/dist/Newbro Executor.app` is built and ad-hoc signed.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status --short
git log --oneline -8
```

Expected: worktree is clean and recent commits correspond to this plan's tasks.
