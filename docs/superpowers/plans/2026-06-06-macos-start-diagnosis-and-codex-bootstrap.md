# macOS Start Diagnosis And Codex Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make macOS profile Start diagnose missing Newbro/Codex readiness, guide normal users through one-click Codex setup, and start the profile once readiness passes.

**Architecture:** The CLI owns Codex installation and executor command selection through `newbro executor install-codex`; Swift owns diagnosis presentation and profile-start routing. `NewbroExecutorCore` gets pure diagnosis/action models, while `NewbroExecutor` wires those models to menu/settings actions and existing `ProfileSupervisor` launch behavior.

**Tech Stack:** Python 3.12 CLI, pytest, Swift 5.9, SwiftUI/AppKit menu-bar app, XCTest.

---

## File Structure

- Create `macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift`
  - Pure diagnosis model, reason/action enums, and classifier helpers.
- Modify `macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift`
  - Add install-Codex command execution, lightweight CLI version helper, and error mapping needed by diagnosis.
- Modify `macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`
  - Add display title helpers for Newbro CLI status and Codex status without changing process launch ownership.
- Modify `macos/Sources/NewbroExecutor/AppModel.swift`
  - Store per-profile diagnosis, route user-triggered Start through diagnosis, run Codex setup, and rerun/start after successful setup.
- Modify `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`
  - Render top-level runtime rows and profile submenu blocked-reason/action rows.
- Modify `macos/Sources/NewbroExecutor/ExecutorSettingsView.swift`
  - Show diagnosis summary and actionable setup/fix buttons.
- Modify `src/newbro/cli/parser.py`
  - Add `newbro executor install-codex`.
- Modify `src/newbro/cli/dispatch.py`
  - Dispatch the new executor subcommand.
- Modify `src/newbro/cli/commands/executor_settings.py`
  - Implement Codex bootstrap and validated `executor use` registration.
- Modify `tests/unit/cli/test_executor_probe.py`
  - Add CLI install-Codex tests with fake runners/probes.
- Create `macos/Tests/NewbroExecutorCoreTests/ProfileStartDiagnosisTests.swift`
  - Cover diagnosis classification and start blocking.
- Modify `macos/Tests/NewbroExecutorCoreTests/ExecutorSettingsClientTests.swift`
  - Cover install-Codex client command and error mapping.
- Modify `macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`
  - Cover Newbro CLI menu titles.
- Modify stable docs:
  - `docs/architecture/executors.md`
  - `docs/guides/cli.md`
  - `macos/README.md`
  - `docs/memories.md`

---

### Task 1: Add CLI-Owned Codex Bootstrap Command

**Files:**
- Modify: `src/newbro/cli/parser.py`
- Modify: `src/newbro/cli/dispatch.py`
- Modify: `src/newbro/cli/commands/executor_settings.py`
- Test: `tests/unit/cli/test_executor_probe.py`

- [ ] **Step 1: Write failing parser/dispatch tests**

Append these tests to `tests/unit/cli/test_executor_probe.py`:

```python
def test_executor_install_codex_uses_existing_codex_without_install(monkeypatch, tmp_path: Path, capsys):
    selected = tmp_path / "bin" / "codex"
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.codex import probe as codex_probe

    calls: list[list[str]] = []

    monkeypatch.setattr(
        codex_probe,
        "discover_codex_commands",
        lambda configured_command=None: [str(selected)],
    )
    monkeypatch.setattr(
        codex_probe,
        "probe_codex_command",
        lambda command: codex_probe.CodexProbeResult(
            path=str(selected),
            version="codex-cli 0.137.0",
            ok=True,
            error=None,
        ),
    )
    monkeypatch.setattr(
        executor_settings,
        "_run_logged",
        lambda argv, *, env=None: calls.append(argv) or 0,
    )

    assert cli_main.main(["executor", "install-codex"]) == 0

    assert calls == []
    assert "Codex is ready" in capsys.readouterr().out
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert f"command: {selected}" in configured


def test_executor_install_codex_bootstraps_bun_and_installs_codex(monkeypatch, tmp_path: Path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    installed = home / ".bun" / "bin" / "codex"
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.codex import probe as codex_probe

    calls: list[list[str]] = []
    available: set[str] = {"sh"}

    def fake_which(name: str, path: str | None = None):
        if name == "codex" and installed.exists():
            return str(installed)
        if name in available:
            return f"/fake/bin/{name}"
        return None

    def fake_run(argv: list[str], *, env=None) -> int:
        calls.append(argv)
        if argv[:3] == ["sh", "-c", "curl -fsSL https://bun.sh/install | bash"]:
            (home / ".bun" / "bin").mkdir(parents=True)
            available.add("bun")
            return 0
        if argv[:4] == [str(home / ".bun" / "bin" / "bun"), "add", "-g", "@openai/codex"]:
            installed.write_text("#!/bin/sh\n", encoding="utf-8")
            return 0
        return 99

    monkeypatch.setattr(executor_settings.shutil, "which", fake_which)
    monkeypatch.setattr(executor_settings, "_run_logged", fake_run)
    monkeypatch.setattr(
        codex_probe,
        "probe_codex_command",
        lambda command: codex_probe.CodexProbeResult(
            path=str(installed),
            version="codex-cli 0.137.0",
            ok=Path(command) == installed,
            error=None if Path(command) == installed else "missing",
        ),
    )
    monkeypatch.setattr(codex_probe, "discover_codex_commands", lambda configured_command=None: [str(installed)])

    assert cli_main.main(["executor", "install-codex"]) == 0

    assert calls == [
        ["sh", "-c", "curl -fsSL https://bun.sh/install | bash"],
        [str(home / ".bun" / "bin" / "bun"), "add", "-g", "@openai/codex"],
    ]
    assert "Installing required runtime" in capsys.readouterr().out
    configured = (tmp_path / ".newbro" / "config.yaml").read_text(encoding="utf-8")
    assert f"command: {installed}" in configured


def test_executor_install_codex_reports_failed_runtime_bootstrap(monkeypatch, tmp_path: Path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _write_config(tmp_path, codex_command="codex")
    configure_repo_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        cli_main,
        "ensure_newbro_home",
        lambda **_kwargs: ConfigHomeMigrationResult(migrated=False),
    )

    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.codex import probe as codex_probe

    monkeypatch.setattr(executor_settings.shutil, "which", lambda _name, path=None: None)
    monkeypatch.setattr(executor_settings, "_run_logged", lambda argv, *, env=None: 7)
    monkeypatch.setattr(codex_probe, "discover_codex_commands", lambda configured_command=None: [])

    assert cli_main.main(["executor", "install-codex"]) == 1

    captured = capsys.readouterr()
    assert "Codex setup failed while installing required runtime" in captured.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_executor_probe.py -q
```

Expected: FAIL because `install-codex` is not a recognized executor subcommand.

- [ ] **Step 3: Add parser and dispatch**

In `src/newbro/cli/parser.py`, add this after the `executor_use_parser` block and before `executor_run_parser`:

```python
    executor_subparsers.add_parser(
        "install-codex",
        help="Install or repair the local Codex CLI used by executor nodes.",
    )
```

In `src/newbro/cli/dispatch.py`, update `cmd_executor`:

```python
def cmd_executor(args: Any, app: Any) -> int:
    if args.executor_command == "setup":
        return setup_command.run_executor_setup(args, cli_factories.setup_context(app), cli_factories.setup_callbacks(app))
    if args.executor_command == "probe":
        return executor_settings_command.run_executor_probe(args, app)
    if args.executor_command == "use":
        return executor_settings_command.run_executor_use(args, app)
    if args.executor_command == "install-codex":
        return executor_settings_command.run_executor_install_codex(args, app)
    if args.executor_command == "run":
        return run_command.run_executor(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))
    raise app.CliError(f"Unknown executor command: {args.executor_command}")
```

- [ ] **Step 4: Implement the CLI installer helpers**

Add these imports to `src/newbro/cli/commands/executor_settings.py`:

```python
import shutil
import subprocess
```

Add these functions to `src/newbro/cli/commands/executor_settings.py` after `run_executor_use`:

```python
def run_executor_install_codex(args: Any, app: Any) -> int:
    del args
    config_path = app.ENV_LOCAL.with_name("config.yaml")
    try:
        command = install_codex_cli(config_path=config_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Codex is ready: {command}")
    return 0


def install_codex_cli(*, config_path: Path) -> str:
    existing = _first_usable_codex_command(config_path=config_path)
    if existing:
        set_codex_command(config_path=config_path, command=existing)
        return existing

    env = _tool_environment()
    bun = shutil.which("bun", path=env.get("PATH"))
    if not bun:
        print("Installing required runtime...")
        code = _run_logged(["sh", "-c", "curl -fsSL https://bun.sh/install | bash"], env=env)
        if code != 0:
            raise RuntimeError("Codex setup failed while installing required runtime.")
        env = _tool_environment()
        bun = shutil.which("bun", path=env.get("PATH"))
    if not bun:
        raise RuntimeError("Codex setup failed: required runtime installed but bun is still unavailable.")

    print("Installing Codex...")
    code = _run_logged([bun, "add", "-g", "@openai/codex"], env=env)
    if code != 0:
        raise RuntimeError("Codex setup failed while installing Codex.")

    print("Checking Codex...")
    command = _first_usable_codex_command(config_path=config_path)
    if not command:
        raise RuntimeError("Codex setup finished, but codex --version is still unavailable.")
    set_codex_command(config_path=config_path, command=command)
    return command


def _first_usable_codex_command(*, config_path: Path) -> str | None:
    raw = config_files.load_existing_connector_yaml(config_path)
    executors = config_files.existing_executors_config(raw)
    configured_command = str((executors.get("codex") or {}).get("command") or "codex")
    for candidate in codex_probe.discover_codex_commands(configured_command=configured_command):
        result = codex_probe.probe_codex_command(candidate)
        if result.ok:
            return result.path
    return None


def _tool_environment() -> dict[str, str]:
    env = os.environ.copy()
    home = Path(env.get("HOME") or str(Path.home()))
    paths = [
        str(home / ".bun" / "bin"),
        str(home / ".local" / "bin"),
        env.get("PATH", ""),
    ]
    env["PATH"] = os.pathsep.join(path for path in paths if path)
    return env


def _run_logged(argv: list[str], *, env: dict[str, str] | None = None) -> int:
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip())
    return proc.wait()
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_executor_probe.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/newbro/cli/parser.py src/newbro/cli/dispatch.py src/newbro/cli/commands/executor_settings.py tests/unit/cli/test_executor_probe.py
git commit -m "feat(cli): add codex bootstrap command"
```

---

### Task 2: Add Pure Swift Diagnosis Model

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/ProfileStartDiagnosisTests.swift`

- [ ] **Step 1: Write failing diagnosis tests**

Create `macos/Tests/NewbroExecutorCoreTests/ProfileStartDiagnosisTests.swift`:

```swift
import XCTest
@testable import NewbroExecutorCore

final class ProfileStartDiagnosisTests: XCTestCase {
    private func profile(_ executors: [String] = ["codex"], token: String = "t") -> Profile {
        Profile(id: "p1", label: "Prod", baseURL: "https://x", nodeID: "node-1", token: token, enabledExecutors: executors)
    }

    func testIncompleteProfileBlocksStart() {
        let diagnosis = diagnoseProfileStart(
            profile(["codex"], token: ""),
            newbroPath: "/Users/test/.local/bin/newbro",
            cliVersion: "0.1.2",
            probe: nil,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .profileIncomplete)
        XCTAssertEqual(diagnosis.primaryAction, .openProfileSettings)
    }

    func testMissingNewbroBlocksWithInstallAction() {
        let diagnosis = diagnoseProfileStart(
            profile(),
            newbroPath: nil,
            cliVersion: nil,
            probe: nil,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .newbroMissing)
        XCTAssertEqual(diagnosis.primaryAction, .installNewbroCLI)
    }

    func testNonCodexProfileDoesNotRequireCodexProbe() {
        let diagnosis = diagnoseProfileStart(
            profile(["acpx"]),
            newbroPath: "/Users/test/.local/bin/newbro",
            cliVersion: nil,
            probe: nil,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .ready)
        XCTAssertEqual(diagnosis.reason, .ready)
        XCTAssertEqual(diagnosis.primaryAction, .none)
    }

    func testMissingCodexMapsToSetupAction() {
        let probe = ExecutorProbe(
            supportedExecutors: ["codex"],
            current: CurrentExecutorProbe(
                executor: "codex",
                command: "codex",
                resolvedPath: nil,
                version: nil,
                ok: false,
                error: "command not found"
            ),
            candidates: []
        )

        let diagnosis = diagnoseProfileStart(
            profile(),
            newbroPath: "/Users/test/.local/bin/newbro",
            cliVersion: "0.1.2",
            probe: probe,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .codexMissing)
        XCTAssertEqual(diagnosis.primaryAction, .setUpCodex)
    }

    func testBrokenCodexWithCandidateMapsToChooseBinary() {
        let probe = ExecutorProbe(
            supportedExecutors: ["codex"],
            current: CurrentExecutorProbe(
                executor: "codex",
                command: "/broken/codex",
                resolvedPath: "/broken/codex",
                version: nil,
                ok: false,
                error: "vendor executable missing"
            ),
            candidates: [
                ExecutorCandidateProbe(
                    path: "/Users/test/.bun/bin/codex",
                    version: "codex-cli 0.137.0",
                    ok: true,
                    source: "discovered",
                    error: nil,
                    isCurrent: false
                )
            ]
        )

        let diagnosis = diagnoseProfileStart(
            profile(),
            newbroPath: "/Users/test/.local/bin/newbro",
            cliVersion: nil,
            probe: probe,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .blocked)
        XCTAssertEqual(diagnosis.reason, .codexConfiguredButBroken)
        XCTAssertEqual(diagnosis.primaryAction, .openCodexSettings)
    }

    func testReadyCodexAllowsStartEvenWhenCliVersionUnknown() {
        let probe = ExecutorProbe(
            supportedExecutors: ["codex"],
            current: CurrentExecutorProbe(
                executor: "codex",
                command: "/Users/test/.bun/bin/codex",
                resolvedPath: "/Users/test/.bun/bin/codex",
                version: "codex-cli 0.137.0",
                ok: true,
                error: nil
            ),
            candidates: []
        )

        let diagnosis = diagnoseProfileStart(
            profile(),
            newbroPath: "/Users/test/.local/bin/newbro",
            cliVersion: nil,
            probe: probe,
            probeError: nil
        )

        XCTAssertEqual(diagnosis.status, .ready)
        XCTAssertEqual(diagnosis.reason, .newbroVersionUnknown)
        XCTAssertEqual(diagnosis.primaryAction, .none)
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
swift test --package-path macos --filter ProfileStartDiagnosisTests
```

Expected: FAIL because `ProfileStartDiagnosis` and `diagnoseProfileStart` do not exist.

- [ ] **Step 3: Implement diagnosis model**

Create `macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift`:

```swift
import Foundation

public enum ProfileStartDiagnosisStatus: String, Equatable, Sendable {
    case ready
    case blocked
    case checking
}

public enum ProfileStartDiagnosisReason: String, Equatable, Sendable {
    case ready
    case profileIncomplete
    case newbroMissing
    case newbroTooOldForProbe
    case newbroVersionUnknown
    case codexMissing
    case codexConfiguredButBroken
    case codexProbeFailed
    case codexLoginRequired
    case installerFailed
}

public enum ProfileStartDiagnosisAction: String, Equatable, Sendable {
    case none
    case installNewbroCLI
    case updateNewbroCLI
    case setUpCodex
    case openCodexSettings
    case signInCodex
    case viewLog
    case rerunDiagnosis
    case openProfileSettings
}

public struct ProfileStartDiagnosis: Equatable, Sendable {
    public let status: ProfileStartDiagnosisStatus
    public let reason: ProfileStartDiagnosisReason
    public let title: String
    public let detail: String?
    public let primaryAction: ProfileStartDiagnosisAction

    public init(status: ProfileStartDiagnosisStatus,
                reason: ProfileStartDiagnosisReason,
                title: String,
                detail: String? = nil,
                primaryAction: ProfileStartDiagnosisAction) {
        self.status = status
        self.reason = reason
        self.title = title
        self.detail = detail
        self.primaryAction = primaryAction
    }
}

public func diagnoseProfileStart(_ profile: Profile,
                                 newbroPath: String?,
                                 cliVersion: String?,
                                 probe: ExecutorProbe?,
                                 probeError: String?) -> ProfileStartDiagnosis {
    guard profileIsComplete(profile) else {
        return ProfileStartDiagnosis(
            status: .blocked,
            reason: .profileIncomplete,
            title: "Start blocked: profile settings are incomplete",
            detail: "The profile needs a URL, node id, token, and at least one executor.",
            primaryAction: .openProfileSettings)
    }

    guard let newbroPath, !newbroPath.isEmpty else {
        return ProfileStartDiagnosis(
            status: .blocked,
            reason: .newbroMissing,
            title: "Start blocked: Newbro CLI is not installed",
            detail: nil,
            primaryAction: .installNewbroCLI)
    }

    guard profile.enabledExecutors.contains("codex") else {
        return ProfileStartDiagnosis(
            status: .ready,
            reason: cliVersion == nil ? .newbroVersionUnknown : .ready,
            title: "Ready",
            detail: cliVersion.map { "newbro CLI \($0) at \(newbroPath)" } ?? "newbro CLI version unknown at \(newbroPath)",
            primaryAction: .none)
    }

    if let probe {
        if probe.current.ok {
            return ProfileStartDiagnosis(
                status: .ready,
                reason: cliVersion == nil ? .newbroVersionUnknown : .ready,
                title: "Ready",
                detail: probe.current.version ?? probe.current.resolvedPath ?? probe.current.command,
                primaryAction: .none)
        }
        let hasUsableCandidate = probe.candidates.contains { $0.ok }
        if hasUsableCandidate {
            return ProfileStartDiagnosis(
                status: .blocked,
                reason: .codexConfiguredButBroken,
                title: "Start blocked: selected Codex is broken",
                detail: probe.current.error ?? probe.current.resolvedPath ?? probe.current.command,
                primaryAction: .openCodexSettings)
        }
        return ProfileStartDiagnosis(
            status: .blocked,
            reason: .codexMissing,
            title: "Start blocked: Codex is not set up",
            detail: probe.current.error,
            primaryAction: .setUpCodex)
    }

    if let probeError, probeError.contains("newer Newbro CLI") {
        return ProfileStartDiagnosis(
            status: .blocked,
            reason: .newbroTooOldForProbe,
            title: "Start blocked: Newbro CLI needs an update",
            detail: probeError,
            primaryAction: .updateNewbroCLI)
    }

    return ProfileStartDiagnosis(
        status: .blocked,
        reason: .codexProbeFailed,
        title: "Start blocked: Codex check failed",
        detail: probeError,
        primaryAction: .rerunDiagnosis)
}
```

- [ ] **Step 4: Run Swift diagnosis tests**

Run:

```bash
swift test --package-path macos --filter ProfileStartDiagnosisTests
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift macos/Tests/NewbroExecutorCoreTests/ProfileStartDiagnosisTests.swift
git commit -m "feat(macos): add profile start diagnosis model"
```

---

### Task 3: Add Swift Client Hooks For Diagnosis And Codex Setup

**Files:**
- Modify: `macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift`
- Modify: `macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/ExecutorSettingsClientTests.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`

- [ ] **Step 1: Write failing client tests**

Append to `macos/Tests/NewbroExecutorCoreTests/ExecutorSettingsClientTests.swift`:

```swift
func testClientInvokesInstallCodexCommand() throws {
    var calls: [[String]] = []
    let client = ExecutorSettingsClient(newbroPath: "/usr/local/bin/newbro") { argv, _ in
        calls.append(argv)
        return "Preparing Codex setup...\nCodex is ready: /Users/test/.bun/bin/codex\n"
    }

    let output = try client.installCodex()

    XCTAssertTrue(output.contains("Codex is ready"))
    XCTAssertEqual(calls, [
        ["/usr/local/bin/newbro", "executor", "install-codex"],
    ])
}

func testUnsupportedInstallCodexMapsToRuntimeTooOld() throws {
    let output = """
    usage: newbro executor [-h] {setup,probe,use,run} ...
    newbro executor: error: argument executor_command: invalid choice: 'install-codex'
    """
    let client = ExecutorSettingsClient(newbroPath: "/usr/local/bin/newbro") { argv, _ in
        if argv == ["/usr/local/bin/newbro", "--version"] {
            return "newbro 0.1.2\n"
        }
        throw ExecutorSettingsClientError.commandFailed(status: 2, output: output)
    }

    XCTAssertThrowsError(try client.installCodex()) { error in
        XCTAssertEqual(error as? ExecutorSettingsClientError, .runtimeTooOld(installedVersion: "0.1.2"))
    }
}
```

Append to `macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift`:

```swift
func testNewbroStatusTitles() {
    XCTAssertEqual(newbroRuntimeMenuTitle(path: nil, version: nil), "newbro CLI not found")
    XCTAssertEqual(newbroRuntimeMenuTitle(path: "/Users/test/.local/bin/newbro", version: nil), "newbro CLI version unknown")
    XCTAssertEqual(newbroRuntimeMenuTitle(path: "/Users/test/.local/bin/newbro", version: "0.1.2"), "newbro CLI v0.1.2")
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
swift test --package-path macos --filter ExecutorSettingsClientTests
swift test --package-path macos --filter RuntimeLocatorTests/testNewbroStatusTitles
```

Expected: FAIL because `installCodex` and `newbroRuntimeMenuTitle` do not exist.

- [ ] **Step 3: Implement client hooks**

In `macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift`, add this public method after `useCodex(path:)`:

```swift
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
```

Extend the private error helper:

```swift
private extension ExecutorSettingsClientError {
    var isUnsupportedProbeSubcommand: Bool {
        guard case .commandFailed(_, let output) = self else { return false }
        return output.contains("executor_command: invalid choice: 'probe'")
    }

    var isUnsupportedInstallCodexSubcommand: Bool {
        guard case .commandFailed(_, let output) = self else { return false }
        return output.contains("executor_command: invalid choice: 'install-codex'")
    }
}
```

In `macos/Sources/NewbroExecutorCore/RuntimeLocator.swift`, add this helper near `refreshCommandStatus`:

```swift
public func newbroRuntimeMenuTitle(path: String?, version: String?) -> String {
    guard path != nil else { return "newbro CLI not found" }
    guard let version, !version.isEmpty else { return "newbro CLI version unknown" }
    return "newbro CLI v\(version)"
}
```

- [ ] **Step 4: Run client/runtime tests**

Run:

```bash
swift test --package-path macos --filter ExecutorSettingsClientTests
swift test --package-path macos --filter RuntimeLocatorTests
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift macos/Sources/NewbroExecutorCore/RuntimeLocator.swift macos/Tests/NewbroExecutorCoreTests/ExecutorSettingsClientTests.swift macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift
git commit -m "feat(macos): add executor setup client hooks"
```

---

### Task 4: Route AppModel Start Through Diagnosis

**Files:**
- Modify: `macos/Sources/NewbroExecutor/AppModel.swift`
- Test: Manual compile through `swift test --package-path macos`

- [ ] **Step 1: Add diagnosis state and helpers**

In `macos/Sources/NewbroExecutor/AppModel.swift`, add published state near existing executor settings state:

```swift
@Published var profileDiagnoses: [String: ProfileStartDiagnosis] = [:]
@Published var codexSetupLog: String = ""
@Published var codexSetupBusy: Bool = false
```

Add these helpers after `refreshExecutorProbe()`:

```swift
func diagnosis(for profile: Profile) -> ProfileStartDiagnosis? {
    profileDiagnoses[profile.id]
}

@discardableResult
func diagnoseStart(for profile: Profile) -> ProfileStartDiagnosis {
    let newbro = locator.resolveNewbro()
    let version = newbro == nil ? nil : installedCLIVersion()
    if newbro == nil {
        let diagnosis = diagnoseProfileStart(
            profile,
            newbroPath: nil,
            cliVersion: nil,
            probe: nil,
            probeError: nil)
        profileDiagnoses[profile.id] = diagnosis
        return diagnosis
    }
    if executorProbe == nil && executorSettingsError == nil {
        refreshExecutorProbe()
    }
    let diagnosis = diagnoseProfileStart(
        profile,
        newbroPath: newbro,
        cliVersion: version,
        probe: executorProbe,
        probeError: executorSettingsError)
    profileDiagnoses[profile.id] = diagnosis
    return diagnosis
}
```

- [ ] **Step 2: Replace user-triggered Start path**

Replace `func start(_ profile: Profile)` with:

```swift
func start(_ profile: Profile) {
    refreshRuntime()
    let diagnosis = diagnoseStart(for: profile)
    guard diagnosis.status == .ready else {
        objectWillChange.send()
        return
    }
    profileDiagnoses.removeValue(forKey: profile.id)
    perform(.start(profile))
}
```

Replace `func start(profileID id: String)` with:

```swift
func start(profileID id: String) {
    guard let profile = profiles.first(where: { $0.id == id }) else { return }
    start(profile)
}
```

Keep `restart(_:)` using the existing gate for now; Task 6 will add recovery actions for blocked states.

- [ ] **Step 3: Add setup action**

Add this method to `AppModel`:

```swift
func setUpCodex(for profile: Profile?) {
    guard !codexSetupBusy, let newbro = locator.resolveNewbro() else { return }
    codexSetupBusy = true
    codexSetupLog = "Preparing Codex setup...\n"
    executorSettingsBusy = true
    let client = ExecutorSettingsClient(newbroPath: newbro)
    DispatchQueue.global(qos: .userInitiated).async { [weak self] in
        let result = Result { try client.installCodex() }
        DispatchQueue.main.async {
            guard let self else { return }
            self.codexSetupBusy = false
            self.executorSettingsBusy = false
            switch result {
            case .success(let output):
                self.codexSetupLog += output
                self.executorSettingsError = nil
                self.refreshRuntime()
                self.refreshExecutorProbe()
                if let profile {
                    let diagnosis = self.diagnoseStart(for: profile)
                    if diagnosis.status == .ready {
                        self.profileDiagnoses.removeValue(forKey: profile.id)
                        self.perform(.start(profile))
                    }
                }
            case .failure(let error):
                self.executorSettingsError = error.localizedDescription
                self.codexSetupLog += error.localizedDescription + "\n"
                if let profile {
                    self.profileDiagnoses[profile.id] = ProfileStartDiagnosis(
                        status: .blocked,
                        reason: .installerFailed,
                        title: "Codex setup failed",
                        detail: error.localizedDescription,
                        primaryAction: .setUpCodex)
                }
            }
        }
    }
}
```

- [ ] **Step 4: Run Swift build/tests**

Run:

```bash
swift test --package-path macos
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add macos/Sources/NewbroExecutor/AppModel.swift
git commit -m "feat(macos): diagnose blocked profile starts"
```

---

### Task 5: Render Menu Diagnosis And Runtime Rows

**Files:**
- Modify: `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`
- Test: `swift test --package-path macos`

- [ ] **Step 1: Add runtime rows**

In `build(into menu:)`, add these rows after the missing-runtime block and before the profile loop:

```swift
let cliTitle = newbroRuntimeMenuTitle(path: model.runtimeAvailable ? "newbro" : nil,
                                      version: model.installedCLIVersion())
menu.addItem(disabledMenuItem(title: cliTitle))
menu.addItem(disabledMenuItem(title: model.codexStatus.menuTitle))
menu.addItem(.separator())
```

- [ ] **Step 2: Add profile blocked reason/action rows**

In the stopped-profile submenu branch, replace:

```swift
sub.addItem(ActionMenuItem(title: "Start") { [weak self] in self?.model.start(profile) })
```

with:

```swift
sub.addItem(ActionMenuItem(title: "Start") { [weak self] in self?.model.start(profile) })
if let diagnosis = model.diagnosis(for: profile), diagnosis.status == .blocked {
    sub.addItem(disabledMenuItem(title: diagnosis.title))
    if let detail = diagnosis.detail, !detail.isEmpty {
        sub.addItem(disabledMenuItem(title: detail))
    }
    switch diagnosis.primaryAction {
    case .setUpCodex:
        sub.addItem(ActionMenuItem(title: "Set Up Codex...") { [weak self] in
            self?.model.setUpCodex(for: profile)
        })
    case .installNewbroCLI, .updateNewbroCLI:
        sub.addItem(ActionMenuItem(title: "Install/Update Newbro CLI...") { [weak self] in
            self?.model.updateCLIFromExecutorSettings()
        })
    case .openCodexSettings:
        sub.addItem(ActionMenuItem(title: "Open Codex Settings...") { [weak self] in
            guard let self else { return }
            self.model.showSettings(updates: self.updates)
        })
    case .rerunDiagnosis:
        sub.addItem(ActionMenuItem(title: "Run Diagnosis") { [weak self] in
            _ = self?.model.diagnoseStart(for: profile)
        })
    default:
        break
    }
}
```

- [ ] **Step 3: Run Swift tests**

Run:

```bash
swift test --package-path macos
```

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add macos/Sources/NewbroExecutor/NewbroExecutorApp.swift
git commit -m "feat(macos): show start diagnosis in menu"
```

---

### Task 6: Add Diagnosis And Setup Controls To Settings

**Files:**
- Modify: `macos/Sources/NewbroExecutor/ExecutorSettingsView.swift`
- Test: `swift test --package-path macos`

- [ ] **Step 1: Add diagnosis summary UI**

In `CodexSettingsPane.body`, insert this after the header `HStack` and before the error row:

```swift
DiagnosisSummaryView(
    model: model,
    diagnosis: model.profiles.compactMap { model.diagnosis(for: $0) }.first
)
```

Add this view before `CandidateRow`:

```swift
private struct DiagnosisSummaryView: View {
    @ObservedObject var model: AppModel
    let diagnosis: ProfileStartDiagnosis?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SettingsInfoRow(
                title: "Newbro CLI",
                detail: newbroRuntimeMenuTitle(
                    path: model.runtimeAvailable ? "newbro" : nil,
                    version: model.installedCLIVersion()
                )
            )
            SettingsInfoRow(title: "Codex", detail: model.codexStatus.menuTitle)
            if let diagnosis {
                Text(diagnosis.title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(diagnosis.status == .blocked ? .red : .secondary)
                    .textSelection(.enabled)
                if let detail = diagnosis.detail {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                Button(primaryActionTitle(diagnosis.primaryAction)) {
                    runPrimaryAction(diagnosis.primaryAction)
                }
                .disabled(diagnosis.primaryAction == .none || model.executorSettingsBusy || model.codexSetupBusy)
            }
            if model.codexSetupBusy || !model.codexSetupLog.isEmpty {
                Text(model.codexSetupLog)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
            }
        }
        .padding(10)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func primaryActionTitle(_ action: ProfileStartDiagnosisAction) -> String {
        switch action {
        case .installNewbroCLI, .updateNewbroCLI: return "Install/Update Newbro CLI..."
        case .setUpCodex: return "Set Up Codex..."
        case .openCodexSettings: return "Choose Codex Binary"
        case .signInCodex: return "Sign in to Codex..."
        case .rerunDiagnosis: return "Run Diagnosis"
        case .openProfileSettings: return "Edit Profile..."
        case .viewLog: return "View Log..."
        case .none: return "Ready"
        }
    }

    private func runPrimaryAction(_ action: ProfileStartDiagnosisAction) {
        let profile = model.profiles.first
        switch action {
        case .installNewbroCLI, .updateNewbroCLI:
            model.updateCLIFromExecutorSettings()
        case .setUpCodex:
            model.setUpCodex(for: profile)
        case .rerunDiagnosis:
            if let profile { _ = model.diagnoseStart(for: profile) }
        default:
            break
        }
    }
}
```

- [ ] **Step 2: Run Swift tests**

Run:

```bash
swift test --package-path macos
```

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```bash
git add macos/Sources/NewbroExecutor/ExecutorSettingsView.swift
git commit -m "feat(macos): add codex diagnosis settings"
```

---

### Task 7: Update Docs And Memory

**Files:**
- Modify: `docs/architecture/executors.md`
- Modify: `docs/guides/cli.md`
- Modify: `macos/README.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Update executor architecture doc**

In `docs/architecture/executors.md`, update the macOS menu-bar app bullet to include:

```markdown
  User-triggered profile Start first runs a local readiness diagnosis. If the
  app cannot resolve a usable `newbro` CLI or a required Codex command, the
  profile remains stopped and the menu/settings show the blocker plus a repair
  action instead of silently leaving a gray stopped row. Missing Codex is repaired
  through the CLI-owned `newbro executor install-codex` path; Swift does not edit
  executor YAML directly.
```

- [ ] **Step 2: Update CLI guide**

In `docs/guides/cli.md`, add this after the macOS menu app paragraph in Detached Executor Nodes:

```markdown
The macOS app's normal missing-Codex recovery path is **Set Up Codex**, which
calls `newbro executor install-codex`. The command installs or repairs the local
Codex CLI for the current user, validates `codex --version`, and records the
validated command with `newbro executor use`. Terminal users can run the same
command directly when recovering a detached node setup.
```

- [ ] **Step 3: Update macOS README**

In `macos/README.md`, replace the Codex probing paragraph with:

```markdown
On launch and before profile Start, the app diagnoses Newbro CLI and Codex
readiness. If Start is blocked, the profile stays stopped with a gray dot, and
the menu/settings show the reason plus a recovery action. Missing Codex is fixed
through **Set Up Codex**, a one-click flow that calls `newbro executor
install-codex`, streams progress, reruns diagnosis, and starts the profile once
ready.
```

- [ ] **Step 4: Append memory note**

Append to `docs/memories.md`:

```markdown
- 2026-06-06: macOS executor profile Start now diagnoses local readiness before
  launch. Missing or broken Codex is repaired through the CLI-owned
  `newbro executor install-codex` one-click setup path rather than leaving a
  stopped gray profile with only settings/log hints.
```

- [ ] **Step 5: Commit docs**

Run:

```bash
git add docs/architecture/executors.md docs/guides/cli.md macos/README.md docs/memories.md
git commit -m "docs: document macos start diagnosis"
```

---

### Task 8: Full Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_executor_probe.py tests/unit/scripts/test_install_newbro_cli_sh.py -q
```

Expected: PASS.

- [ ] **Step 2: Run macOS Swift tests**

Run:

```bash
swift test --package-path macos
```

Expected: PASS.

- [ ] **Step 3: Run full Python tests**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: PASS. If a pre-existing unrelated failure appears, copy the failing
test name and first assertion/error line into the implementation handoff before
continuing.

- [ ] **Step 4: Manual app sanity check**

Run:

```bash
./macos/package-app.sh
```

Expected: package completes and `macos/dist/Newbro Executor.app` exists.

Launch the app with a controlled missing-Codex environment:

```bash
NEWBRO_BIN="$(pwd)/newbro" open "macos/dist/Newbro Executor.app"
```

Expected: clicking Start on a Codex profile that cannot find Codex leaves the profile stopped, shows `Start blocked: Codex is not set up`, and exposes `Set Up Codex...`.

- [ ] **Step 5: Final commit if verification caused fixes**

If verification required fixes, commit them:

```bash
git status --short
git add src/newbro/cli/parser.py src/newbro/cli/dispatch.py src/newbro/cli/commands/executor_settings.py tests/unit/cli/test_executor_probe.py macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift macos/Sources/NewbroExecutorCore/RuntimeLocator.swift macos/Sources/NewbroExecutor/AppModel.swift macos/Sources/NewbroExecutor/NewbroExecutorApp.swift macos/Sources/NewbroExecutor/ExecutorSettingsView.swift macos/Tests/NewbroExecutorCoreTests/ProfileStartDiagnosisTests.swift macos/Tests/NewbroExecutorCoreTests/ExecutorSettingsClientTests.swift macos/Tests/NewbroExecutorCoreTests/RuntimeLocatorTests.swift docs/architecture/executors.md docs/guides/cli.md macos/README.md docs/memories.md
git commit -m "fix: complete macos start diagnosis verification"
```

If `git status --short` is empty, do not create an empty commit.
