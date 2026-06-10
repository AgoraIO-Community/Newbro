# Hermes macOS-app + CLI default-command-to-PATH — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes a first-class, operator-visible executor family in the CLI (config-free `executor run`, real `install-hermes`, auth-aware probe) and the macOS menu-bar app (per-family probe state, family-aware start diagnosis, a Hermes Settings pane, and a no-fallback single-choice profile picker).

**Architecture:** CLI changes land first because they define the `newbro executor probe --executor hermes --json` contract (including a new `authenticated` field) that the Swift app consumes. The single-family-per-node invariant is enforced at every local-config writer and the profile editor. Hermes mirrors Codex's existing readiness model (block when missing or unauthenticated) — no new diagnosis status, no Terminal launcher.

**Tech Stack:** Python 3.12 / pytest (CLI), Swift / XCTest via `swift test` (macOS app).

**Spec:** `docs/superpowers/specs/2026-06-09-hermes-macapp-and-cli-design.md`

**Run tests:** Python `.venv/bin/python -m pytest`; Swift `swift test --package-path executor-apps/macos`.

---

## File Structure

CLI (Python):
- Modify `src/newbro/executors/families.py` — add `PROBEABLE_EXECUTOR_FAMILIES`.
- Modify `src/newbro/cli/parser.py` — `probe`/`use` `--executor` choices → probeable.
- Modify `src/newbro/cli/commands/executor_settings.py` — probe/use dispatch, `set_hermes_command`/`set_codex_command` single-family, `hermes_probe_payload` auth field, real `install_hermes_cli`.
- Modify `src/newbro/executors/adapters/hermes/probe.py` — `probe_hermes_authenticated`.
- Modify `src/newbro/cli/setup_resolvers.py` — `executor_runtime_ready` default-command-to-PATH.

macOS (Swift):
- Modify `executor-apps/macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift` — `authenticated` field, family-parameterized `probe`/`use`/`install`.
- Create `executor-apps/macos/Sources/NewbroExecutorCore/ExecutorFamilies.swift` — `supportedExecutorFamilies` / `probeableExecutorFamilies`.
- Modify `executor-apps/macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift` — family-aware diagnosis + Hermes reasons/actions.
- Modify `executor-apps/macos/Sources/NewbroExecutor/AppModel.swift` — per-family state + `refreshProbe(for:)`.
- Modify `executor-apps/macos/Sources/NewbroExecutor/ExecutorSettingsView.swift` — Hermes pane + scoped refresh.
- Modify `executor-apps/macos/Sources/NewbroExecutor/ProfileEditView.swift` — single-choice no-fallback picker.

---

## Task 1: Probeable-families constant + probe/use reject ACPX (A4)

**Files:**
- Modify: `src/newbro/executors/families.py`
- Modify: `src/newbro/cli/parser.py`
- Modify: `src/newbro/cli/commands/executor_settings.py` (`run_executor_probe`, `run_executor_use`)
- Test: `tests/unit/cli/test_executor_probe.py`, `tests/unit/cli/test_executor_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/cli/test_executor_parser.py
from pathlib import Path
from newbro.cli.parser import build_parser


def _p():
    return build_parser(cli_name="newbro", env_file=Path("/tmp/.env"), start_public_port=8000)


def test_probe_rejects_acpx():
    import pytest
    with pytest.raises(SystemExit):
        _p().parse_args(["executor", "probe", "--executor", "acpx"])


def test_probe_still_accepts_hermes_and_codex():
    assert _p().parse_args(["executor", "probe", "--executor", "hermes"]).executor == "hermes"
    assert _p().parse_args(["executor", "use", "--executor", "codex", "--command", "/x"]).executor == "codex"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_parser.py -k acpx -v`
Expected: FAIL — argparse currently allows `acpx` (choices = all families).

- [ ] **Step 3: Add the constant**

In `src/newbro/executors/families.py`, append:

```python
# Families with a meaningful local readiness probe (binary presence/version).
# ACPX is run-only: no probe, no start-readiness gate.
PROBEABLE_EXECUTOR_FAMILIES: tuple[str, ...] = ("codex", "hermes")
```

- [ ] **Step 4: Narrow parser choices**

In `src/newbro/cli/parser.py`, add to the import already pulling `SUPPORTED_EXECUTOR_FAMILIES`:

```python
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES, PROBEABLE_EXECUTOR_FAMILIES
```

Change the two `--executor` arguments (the `probe` and `use` subparsers) from
`choices=list(SUPPORTED_EXECUTOR_FAMILIES)` to `choices=list(PROBEABLE_EXECUTOR_FAMILIES)`.
Leave `--enabled-executor` on the `run` subparser as `SUPPORTED_EXECUTOR_FAMILIES`.

- [ ] **Step 5: Make dispatch explicit (no codex fall-through)**

In `src/newbro/cli/commands/executor_settings.py`, change `run_executor_probe` so it never falls through to codex for a non-codex family:

```python
def run_executor_probe(args: Any, app: Any) -> int:
    if args.executor not in PROBEABLE_EXECUTOR_FAMILIES:
        print(f"Executor '{args.executor}' has no probe.", file=sys.stderr)
        return 1
    config_path = app.ENV_LOCAL.with_name("config.yaml")
    if args.executor == "hermes":
        payload = hermes_probe_payload(config_path=config_path)
    elif args.executor == "codex":
        payload = codex_probe_payload(config_path=config_path)
    else:  # unreachable given the guard, but explicit
        print(f"Executor '{args.executor}' has no probe.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human_probe(payload)
    return 0
```

Add the import at the top: `from newbro.executors.families import PROBEABLE_EXECUTOR_FAMILIES`.
Apply the same `args.executor == "hermes"` / `== "codex"` explicit dispatch in
`run_executor_use` (it already branches on hermes; ensure the `else` is codex-only and
both are within `PROBEABLE_EXECUTOR_FAMILIES`).

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_parser.py tests/unit/cli/test_executor_probe.py -v`
Expected: PASS. Also `.venv/bin/python -m pytest tests/unit/cli -q`.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/executors/families.py src/newbro/cli/parser.py src/newbro/cli/commands/executor_settings.py tests/unit/cli/test_executor_parser.py
git commit -m "feat(cli): limit probe/use to probeable families; reject acpx probe"
```

---

## Task 2: Default-command-to-PATH in readiness (A1)

**Files:**
- Modify: `src/newbro/cli/setup_resolvers.py` (`executor_runtime_ready`, generic branch)
- Test: `tests/unit/cli/test_setup_resolvers_hermes.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/cli/test_setup_resolvers_hermes.py
from newbro.cli.setup_resolvers import executor_runtime_ready


class _Cb:
    def detected_codex_command(self):
        return None

    def command_available(self, command):
        return command == "hermes"  # pretend only `hermes` resolves on PATH


def test_hermes_ready_with_no_configured_command_when_on_path():
    # No executors.hermes.command configured, but `hermes` resolves on PATH.
    assert executor_runtime_ready(
        "hermes", existing_block={}, existing_values={}, callbacks=_Cb()
    ) is True


def test_hermes_not_ready_when_not_on_path():
    class _CbMissing(_Cb):
        def command_available(self, command):
            return False

    assert executor_runtime_ready(
        "hermes", existing_block={}, existing_values={}, callbacks=_CbMissing()
    ) is False
```

(Confirm the real `SetupResolutionCallbacks` shape; the fake only needs the methods
`executor_runtime_ready` actually calls — `command_available` for the generic branch.)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_setup_resolvers_hermes.py -k ready -v`
Expected: FAIL — generic branch requires `existing_block.get("command")` (empty → not ready).

- [ ] **Step 3: Default the command to the family name**

In `src/newbro/cli/setup_resolvers.py`, change the generic branch of `executor_runtime_ready` (the lines after the codex/acpx branches):

```python
    # Generic families (e.g. hermes): default the command to the family name and
    # PATH-check it, matching what the executor node's _build_executors already does.
    command = str(existing_block.get("command") or executor_type).strip()
    return bool(command) and callbacks.command_available(command)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_setup_resolvers_hermes.py -v`
Expected: PASS. Also `.venv/bin/python -m pytest tests/unit/cli -q`.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/cli/setup_resolvers.py tests/unit/cli/test_setup_resolvers_hermes.py
git commit -m "feat(cli): default unconfigured family command to its name for readiness"
```

---

## Task 3: Single-family local config writers (set_hermes_command + set_codex_command)

**Files:**
- Modify: `src/newbro/cli/commands/executor_settings.py` (`set_hermes_command`, `set_codex_command`)
- Test: `tests/unit/cli/test_executor_settings_hermes.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/cli/test_executor_settings_hermes.py
from newbro.cli.commands import executor_settings
from newbro.cli import config_files


def _enabled(config_path):
    raw = config_files.load_existing_connector_yaml(config_path)
    return config_files.existing_executor_node_config(raw).get("enabled_executors")


def test_set_hermes_command_replaces_enabled_with_single_family(tmp_path):
    config_path = tmp_path / "config.yaml"
    executor_settings.set_codex_command(config_path=config_path, command="/usr/local/bin/codex")
    executor_settings.set_hermes_command(config_path=config_path, command="/usr/local/bin/hermes")
    assert _enabled(config_path) == ["hermes"]  # not ["codex", "hermes"]


def test_set_codex_command_writes_single_family(tmp_path):
    config_path = tmp_path / "config.yaml"
    executor_settings.set_hermes_command(config_path=config_path, command="/usr/local/bin/hermes")
    executor_settings.set_codex_command(config_path=config_path, command="/usr/local/bin/codex")
    assert _enabled(config_path) == ["codex"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_settings_hermes.py -k single_family -v`
Expected: FAIL — both writers currently append, yielding `["codex", "hermes"]`.

- [ ] **Step 3: Make both writers replace, not append**

In `set_hermes_command`, replace the enabled-list block:

```python
    # Single-family node invariant: a local node runs exactly one family.
    executor_node["enabled_executors"] = ["hermes"]
```

In `set_codex_command`, replace its enabled-list block the same way:

```python
    executor_node["enabled_executors"] = ["codex"]
```

(Remove the `enabled = list(...); if "x" not in enabled: enabled.append("x")` logic in
both functions.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_settings_hermes.py -v`
Expected: PASS. Then run the full CLI + setup suites and fix any existing test that
asserted the old append/preserve behavior:
`.venv/bin/python -m pytest tests/unit/cli -q`
Expected: PASS (update any test that expected `set_codex_command` to preserve other
families — the invariant now forbids that).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/cli/commands/executor_settings.py tests/unit/cli/test_executor_settings_hermes.py
git commit -m "fix(cli): local config writers enforce single-family enabled_executors"
```

---

## Task 4: `authenticated` field via `hermes auth list` (A3)

**Files:**
- Modify: `src/newbro/executors/adapters/hermes/probe.py` (add `probe_hermes_authenticated`)
- Modify: `src/newbro/cli/commands/executor_settings.py` (`hermes_probe_payload`)
- Test: `tests/unit/executors/test_hermes_probe.py`, `tests/unit/cli/test_executor_settings_hermes.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/executors/test_hermes_probe.py
from newbro.executors.adapters.hermes.probe import interpret_hermes_auth_list


def test_auth_list_with_credentials_is_authenticated():
    out = "copilot (1 credentials):\n  #1  gh auth token  api_key gh_cli\n"
    assert interpret_hermes_auth_list(returncode=0, output=out) is True


def test_auth_list_empty_is_unauthenticated():
    assert interpret_hermes_auth_list(returncode=0, output="\n") is False


def test_auth_list_failure_is_unknown():
    assert interpret_hermes_auth_list(returncode=1, output="boom") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_probe.py -k auth -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement the auth interpretation + probe**

Append to `src/newbro/executors/adapters/hermes/probe.py`:

```python
import re as _re


def interpret_hermes_auth_list(*, returncode: int, output: str) -> bool | None:
    """Best-effort: True if any credential is listed, False if none, None if unknown."""
    if returncode != 0:
        return None
    text = (output or "").strip()
    if not text:
        return False
    # `hermes auth list` prints "<provider> (N credentials):" blocks and "#<n>" lines.
    if _re.search(r"\(\s*[1-9]\d*\s+credentials?\s*\)", text) or _re.search(r"^\s*#\d+", text, _re.MULTILINE):
        return True
    return False


def probe_hermes_authenticated(command: str) -> bool | None:
    path = command if os.path.isabs(command) else (shutil.which(command) or command)
    try:
        completed = subprocess.run(
            [path, "auth", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            stdin=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001 - auth status must never break the probe
        return None
    return interpret_hermes_auth_list(returncode=completed.returncode, output=completed.stdout or completed.stderr or "")
```

- [ ] **Step 4: Add `authenticated` to the payload**

In `hermes_probe_payload` (`executor_settings.py`), after computing the version
probe `result`, add the auth field:

```python
    authenticated = hermes_probe.probe_hermes_authenticated(configured_command) if result.ok else None
    return {
        "supported_executors": list(SUPPORTED_EXECUTORS),
        "current": {
            "executor": "hermes",
            "command": configured_command,
            "resolved_path": result.path,
            "version": result.version,
            "ok": result.ok,
            "error": result.error,
            "authenticated": authenticated,
        },
        "candidates": [],
    }
```

- [ ] **Step 5: Test the payload field**

```python
# add to tests/unit/cli/test_executor_settings_hermes.py
def test_hermes_probe_payload_has_authenticated_key(tmp_path, monkeypatch):
    from newbro.cli.commands import executor_settings
    from newbro.executors.adapters.hermes import probe as hermes_probe

    monkeypatch.setattr(hermes_probe, "probe_hermes_command", lambda cmd: hermes_probe.HermesProbeResult(path="/h", version="0.12.0", ok=True))
    monkeypatch.setattr(hermes_probe, "probe_hermes_authenticated", lambda cmd: True)
    payload = executor_settings.hermes_probe_payload(config_path=tmp_path / "config.yaml")
    assert payload["current"]["authenticated"] is True
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_probe.py tests/unit/cli/test_executor_settings_hermes.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/executors/adapters/hermes/probe.py src/newbro/cli/commands/executor_settings.py tests/unit/executors/test_hermes_probe.py tests/unit/cli/test_executor_settings_hermes.py
git commit -m "feat(cli): hermes probe reports best-effort authenticated state"
```

---

## Task 5: Real `install-hermes` via the vendor script (A2)

**Files:**
- Modify: `src/newbro/cli/commands/executor_settings.py` (`install_hermes_cli`)
- Test: `tests/unit/cli/test_executor_settings_hermes.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/cli/test_executor_settings_hermes.py
import pytest
from newbro.cli.commands import executor_settings
from newbro.executors.adapters.hermes import probe as hermes_probe


def test_install_hermes_runs_vendor_script_then_sets_command(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(executor_settings, "_run_install_step", lambda argv, msg, env=None: calls.append(argv))
    # First probe (pre-install) fails; after "install" it resolves.
    seq = iter([
        hermes_probe.HermesProbeResult(path="hermes", version=None, ok=False, error="command not found"),
        hermes_probe.HermesProbeResult(path="/Users/me/.local/bin/hermes", version="0.12.0", ok=True),
    ])
    monkeypatch.setattr(hermes_probe, "probe_hermes_command", lambda cmd: next(seq))
    command = executor_settings.install_hermes_cli(tmp_path / "config.yaml")
    assert command.endswith("/hermes")
    assert any("install.sh" in " ".join(argv) for argv in calls)  # vendor script was run


def test_install_hermes_raises_when_still_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_settings, "_run_install_step", lambda argv, msg, env=None: None)
    monkeypatch.setattr(hermes_probe, "probe_hermes_command",
                        lambda cmd: hermes_probe.HermesProbeResult(path="hermes", version=None, ok=False, error="command not found"))
    with pytest.raises(RuntimeError, match="hermes setup --portal"):
        executor_settings.install_hermes_cli(tmp_path / "config.yaml")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_settings_hermes.py -k install_hermes -v`
Expected: FAIL — current `install_hermes_cli` is validate-only (doesn't run a script; doesn't raise with that guidance).

- [ ] **Step 3: Implement the real, defensive install**

Replace `install_hermes_cli` in `executor_settings.py`:

```python
HERMES_INSTALL_URL = "https://hermes-agent.nousresearch.com/install.sh"


def _first_usable_hermes_command() -> str | None:
    result = hermes_probe.probe_hermes_command("hermes")
    return _absolute_command_path(result.path) if result.ok else None


def install_hermes_cli(config_path: Path) -> str:
    existing = _first_usable_hermes_command()
    if existing is not None:
        set_hermes_command(config_path=config_path, command=existing)
        return existing
    if not SYSTEM_CURL.exists() or not SYSTEM_BASH.exists():
        raise RuntimeError(
            "Hermes setup needs curl and bash. Install Hermes manually with "
            f"`curl -fsSL {HERMES_INSTALL_URL} | bash` then run `hermes setup --portal`."
        )
    print("Installing Hermes...")
    env = _bootstrap_environment()
    with tempfile.TemporaryDirectory(prefix="newbro-hermes-") as directory:
        installer = str(Path(directory) / "hermes-install.sh")
        failure = (
            "Hermes setup failed. Install Hermes manually with "
            f"`curl -fsSL {HERMES_INSTALL_URL} | bash` then run `hermes setup --portal`."
        )
        _run_install_step([str(SYSTEM_CURL), "-fsSL", HERMES_INSTALL_URL, "-o", installer], failure, env=env)
        # Defensive: no inherited TTY (stdin from /dev/null), bounded by _run_logged's timeout.
        _run_install_step([str(SYSTEM_BASH), installer], failure, env=env)
    command = _first_usable_hermes_command()
    if command is None:
        raise RuntimeError(
            "Hermes setup finished, but `hermes --version` is still unavailable. "
            f"Install Hermes manually with `curl -fsSL {HERMES_INSTALL_URL} | bash` "
            "then run `hermes setup --portal`."
        )
    set_hermes_command(config_path=config_path, command=command)
    return command
```

Then make `_run_logged` pass `stdin=subprocess.DEVNULL` so the installer can never
block on a prompt:

```python
        completed = subprocess.run(argv, check=False, env=env, timeout=timeout_seconds, stdin=subprocess.DEVNULL)
```

(`run_executor_install_hermes`, already wired from the earlier feature, calls
`install_hermes_cli` and prints `Hermes is ready: <command>`. After it returns, it
should also print: `Sign in with: hermes setup --portal` — add that line.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_settings_hermes.py -v`
Expected: PASS. Also `.venv/bin/python -m pytest tests/unit/cli -q` (codex install tests unaffected — `_run_logged` stdin change is benign for them).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/cli/commands/executor_settings.py tests/unit/cli/test_executor_settings_hermes.py
git commit -m "feat(cli): install-hermes runs the vendor installer defensively"
```

---

## Task 6: Swift probe model + family-parameterized client

**Files:**
- Modify: `executor-apps/macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift`
- Test: `executor-apps/macos/Tests/NewbroExecutorCoreTests/ExecutorSettingsClientTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
// add to ExecutorSettingsClientTests.swift
func testProbeUsesRequestedFamilyAndDecodesAuthenticated() throws {
    var seenArgv: [String] = []
    let client = ExecutorSettingsClient(newbroPath: "/n", environment: nil) { argv, _ in
        seenArgv = argv
        return #"{"supported_executors":["codex","acpx","hermes"],"current":{"executor":"hermes","command":"hermes","version":"0.12.0","ok":true,"authenticated":true},"candidates":[]}"#
    }
    let probe = try client.probe(executor: "hermes")
    XCTAssertTrue(seenArgv.contains("hermes"))
    XCTAssertEqual(probe.current.authenticated, true)
}

func testInstallHermesInvokesInstallHermes() throws {
    var seenArgv: [String] = []
    let client = ExecutorSettingsClient(newbroPath: "/n", environment: nil) { argv, _ in
        seenArgv = argv
        return "Hermes is ready: /h"
    }
    _ = try client.installHermes()
    XCTAssertEqual(seenArgv, ["/n", "executor", "install-hermes"])
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `swift test --package-path executor-apps/macos --filter ExecutorSettingsClientTests`
Expected: FAIL — `authenticated` not decoded; `probe(executor:)` / `installHermes()` don't exist.

- [ ] **Step 3: Add the `authenticated` field and family-parameterized methods**

In `ExecutorSettingsClient.swift`, add to `CurrentExecutorProbe`:

```swift
    public var authenticated: Bool?
```
and add `authenticated` to its `CodingKeys` (`case executor, command, version, ok, error, authenticated`).

Replace `probe()` with a family-parameterized version (keep a no-arg overload defaulting to codex for existing callers):

```swift
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
```

Add Hermes use/install parallel to the codex ones:

```swift
    public func useHermes(path: String) throws {
        _ = try runner([newbroPath, "executor", "use", "--executor", "hermes", "--command", path], environment)
    }

    public func installHermes() throws -> String {
        try runner([newbroPath, "executor", "install-hermes"], environment)
    }

    public func installHermesStreaming(onLine: @escaping @Sendable (String) -> Void) throws -> String {
        try Self.runProcessStreaming(argv: [newbroPath, "executor", "install-hermes"], environment: environment, onLine: onLine)
    }
```

- [ ] **Step 4: Run tests**

Run: `swift test --package-path executor-apps/macos --filter ExecutorSettingsClientTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add executor-apps/macos/Sources/NewbroExecutorCore/ExecutorSettingsClient.swift executor-apps/macos/Tests/NewbroExecutorCoreTests/ExecutorSettingsClientTests.swift
git commit -m "feat(macapp): family-parameterized probe with authenticated; hermes use/install"
```

---

## Task 7: Family-aware ProfileStartDiagnosis + families constant

**Files:**
- Create: `executor-apps/macos/Sources/NewbroExecutorCore/ExecutorFamilies.swift`
- Modify: `executor-apps/macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift`
- Test: `executor-apps/macos/Tests/NewbroExecutorCoreTests/ProfileStartRulesTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
// add to ProfileStartRulesTests.swift
private func hermesProfile() -> Profile {
    Profile(id: "p", label: "h", baseURL: "u", nodeID: "n", token: "t", enabledExecutors: ["hermes"])
}
private func hermesProbe(ok: Bool, authenticated: Bool?) -> ExecutorProbe {
    ExecutorProbe(supportedExecutors: ["codex", "acpx", "hermes"],
                  current: CurrentExecutorProbe(executor: "hermes", command: "hermes", resolvedPath: nil,
                                                version: ok ? "0.12.0" : nil, ok: ok, error: ok ? nil : "command not found",
                                                authenticated: authenticated),
                  candidates: [])
}

func testHermesMissingBlocksWithSetUp() {
    let d = diagnoseProfileStart(hermesProfile(), newbroPath: "/n", cliVersion: "9.9.9",
                                 probe: hermesProbe(ok: false, authenticated: nil), probeError: nil)
    XCTAssertEqual(d.status, .blocked)
    XCTAssertEqual(d.primaryAction, .setUpHermes)
}

func testHermesPresentUnauthedBlocksWithSignIn() {
    let d = diagnoseProfileStart(hermesProfile(), newbroPath: "/n", cliVersion: "9.9.9",
                                 probe: hermesProbe(ok: true, authenticated: false), probeError: nil)
    XCTAssertEqual(d.status, .blocked)
    XCTAssertEqual(d.primaryAction, .signInHermes)
}

func testHermesPresentAuthedOrUnknownReady() {
    for auth in [true, nil] as [Bool?] {
        let d = diagnoseProfileStart(hermesProfile(), newbroPath: "/n", cliVersion: "9.9.9",
                                     probe: hermesProbe(ok: true, authenticated: auth), probeError: nil)
        XCTAssertEqual(d.status, .ready)
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `swift test --package-path executor-apps/macos --filter ProfileStartRulesTests`
Expected: FAIL — `.setUpHermes` / `.signInHermes` don't exist; hermes profiles currently fall through to `readyDiagnosis`.

- [ ] **Step 3: Add the families constant**

Create `executor-apps/macos/Sources/NewbroExecutorCore/ExecutorFamilies.swift`:

```swift
import Foundation

/// Mirror of the backend's SUPPORTED_EXECUTOR_FAMILIES / PROBEABLE_EXECUTOR_FAMILIES.
public let supportedExecutorFamilies: [String] = ["codex", "acpx", "hermes"]
public let probeableExecutorFamilies: [String] = ["codex", "hermes"]
```

- [ ] **Step 4: Add Hermes reasons/actions and the family-aware branch**

In `ProfileStartDiagnosis.swift`, add to `ProfileStartDiagnosisReason`:
`case hermesMissing` and `case hermesSignInRequired`.
Add to `ProfileStartDiagnosisAction`: `case setUpHermes` and `case signInHermes`.

In `diagnoseProfileStart`, after the profile-incomplete and newbroPath gates, replace
the `let requiresCodex = profile.enabledExecutors.contains("codex")` logic with a
family switch on `profile.enabledExecutors.first`:

```swift
    let family = profile.enabledExecutors.first
    switch family {
    case "codex":
        // ... existing codex diagnosis body unchanged ...
    case "hermes":
        guard let probe else {
            return ProfileStartDiagnosis(status: .checking, reason: .ready, title: "Checking Hermes setup", primaryAction: .none)
        }
        if !probe.current.ok {
            return ProfileStartDiagnosis(status: .blocked, reason: .hermesMissing,
                                         title: "Start blocked: Hermes is not set up",
                                         detail: probe.current.error, primaryAction: .setUpHermes)
        }
        if probe.current.authenticated == false {
            return ProfileStartDiagnosis(status: .blocked, reason: .hermesSignInRequired,
                                         title: "Start blocked: Hermes sign-in required",
                                         detail: "Run `hermes setup --portal` in a terminal, then Refresh.",
                                         primaryAction: .signInHermes)
        }
        return readyDiagnosis(cliVersion: cliVersion)  // authenticated == true or nil
    default:
        return readyDiagnosis(cliVersion: cliVersion)  // acpx / unknown: run-only, no gate
    }
```

Keep the existing codex body verbatim inside the `case "codex":` branch (move it; do
not change its logic). The `probeError` handling that today applies to codex stays
inside the codex branch.

- [ ] **Step 5: Run tests**

Run: `swift test --package-path executor-apps/macos --filter ProfileStartRulesTests`
Expected: PASS. Also run `swift test --package-path executor-apps/macos --filter ProfileStartDiagnosisTests` and fix any codex test that depended on the old `requiresCodex` structure (behavior must be identical for codex).

- [ ] **Step 6: Commit**

```bash
git add executor-apps/macos/Sources/NewbroExecutorCore/ExecutorFamilies.swift executor-apps/macos/Sources/NewbroExecutorCore/ProfileStartDiagnosis.swift executor-apps/macos/Tests/NewbroExecutorCoreTests/ProfileStartRulesTests.swift
git commit -m "feat(macapp): family-aware start diagnosis with hermes missing/sign-in"
```

---

## Task 8: Per-family probe state + scoped refresh in AppModel

**Files:**
- Modify: `executor-apps/macos/Sources/NewbroExecutor/AppModel.swift`
- Test: `executor-apps/macos/Tests/NewbroExecutorCoreTests/` (new `AppModelProbeScopeTests.swift` if AppModel is testable; otherwise assert via a injected probe-runner)

**Note:** `AppModel` lives in the app target (`NewbroExecutor`), which may not be unit-tested today. If the app target has no test host, extract the scoping decision into a small pure helper in `NewbroExecutorCore` and test that; keep `AppModel` as a thin caller. Check whether `Tests/NewbroExecutorCoreTests` can import `NewbroExecutor`; if not, use the helper approach.

- [ ] **Step 1: Write the failing test (pure helper)**

Create `executor-apps/macos/Sources/NewbroExecutorCore/ProbeScope.swift` target helper and test it:

```swift
// ProbeScopeTests.swift
func testProbeScopeUnionsProfileFamiliesAndViewedFamily() {
    let profiles = [
        Profile(id: "a", label: "", baseURL: "", nodeID: "", token: "", enabledExecutors: ["codex"]),
        Profile(id: "b", label: "", baseURL: "", nodeID: "", token: "", enabledExecutors: ["acpx"]),
    ]
    // acpx is not probeable; codex is; viewing hermes adds hermes.
    XCTAssertEqual(Set(probeScope(profiles: profiles, viewedFamily: "hermes")), Set(["codex", "hermes"]))
    XCTAssertEqual(Set(probeScope(profiles: profiles, viewedFamily: nil)), Set(["codex"]))
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `swift test --package-path executor-apps/macos --filter ProbeScopeTests`
Expected: FAIL — `probeScope` not defined.

- [ ] **Step 3: Implement the scope helper**

Create `executor-apps/macos/Sources/NewbroExecutorCore/ProbeScope.swift`:

```swift
import Foundation

/// Families worth probing: those any profile actually uses (and that are probeable),
/// plus the Settings family currently being viewed. ACPX has no probe.
public func probeScope(profiles: [Profile], viewedFamily: String?) -> [String] {
    var families = Set<String>()
    for profile in profiles {
        if let f = profile.enabledExecutors.first, probeableExecutorFamilies.contains(f) {
            families.insert(f)
        }
    }
    if let viewed = viewedFamily, probeableExecutorFamilies.contains(viewed) {
        families.insert(viewed)
    }
    return probeableExecutorFamilies.filter { families.contains($0) }
}
```

- [ ] **Step 4: Rework AppModel state to per-family**

In `AppModel.swift`: replace `executorProbe`/`codexStatus`/`codexSetupLog`/`codexSetupBusy`
with `probeByFamily: [String: ExecutorProbe]`, `statusByFamily: [String: CommandStatus]`,
`setupLogByFamily: [String: String]`, `setupBusyByFamily: [String: Bool]`. Add:

```swift
func refreshProbe(for family: String) {
    guard probeableExecutorFamilies.contains(family), let newbro = resolvedNewbroPath() else { return }
    // off-main-thread probe via ExecutorSettingsClient(newbroPath: newbro).probe(executor: family),
    // store into probeByFamily[family]/statusByFamily[family], then re-derive stored diagnoses.
}
```

Replace blanket `refreshExecutorProbeAndStoredDiagnoses()` callers per the spec:
- the Codex pane Refresh → `refreshProbe(for: "codex")`
- the Hermes pane Refresh → `refreshProbe(for: "hermes")`
- profile start (`continueStartIfReady`) → `refreshProbe(for: profile.enabledExecutors.first ?? "codex")`
- launch → `for f in probeScope(profiles: profiles, viewedFamily: nil) { refreshProbe(for: f) }`

`diagnoseStart(for:)` reads `probeByFamily[profile.enabledExecutors.first ?? "codex"]`.

(This is the largest single edit; keep the existing codex setup-streaming flow but key
its log/busy by `"codex"`, and add a parallel `setUpHermes(for:)` using
`installHermesStreaming`.)

- [ ] **Step 5: Run the whole Swift suite**

Run: `swift test --package-path executor-apps/macos`
Expected: PASS (ProbeScopeTests + all existing core tests). Fix references to the
removed `codexStatus`/`executorProbe` in views in Task 9.

- [ ] **Step 6: Commit**

```bash
git add executor-apps/macos/Sources/NewbroExecutorCore/ProbeScope.swift executor-apps/macos/Sources/NewbroExecutor/AppModel.swift executor-apps/macos/Tests/NewbroExecutorCoreTests/ProbeScopeTests.swift
git commit -m "feat(macapp): per-family probe state and scoped refresh"
```

---

## Task 9: Hermes Settings pane (two panes, scoped refresh)

**Files:**
- Modify: `executor-apps/macos/Sources/NewbroExecutor/ExecutorSettingsView.swift`

This is SwiftUI view wiring (no unit test host); verify by build + the diagnosis/action
rules already covered in Task 7. Keep changes mechanical.

- [ ] **Step 1: Add the Hermes pane case**

In the `SettingsPane` enum add `case hermes`. In the sidebar "Executors" `Section`, add
a second entry `Text("Hermes").tag(SettingsPane.hermes)` after the Codex one. In the
detail switch, add `case .hermes: HermesSettingsPane(model: model)`.

- [ ] **Step 2: Implement `HermesSettingsPane`**

Mirror `CodexSettingsPane`, reading `model.statusByFamily["hermes"]` /
`model.probeByFamily["hermes"]`:
- status row: `Hermes vX` / `No Hermes found.`
- a sign-in row driven by `probeByFamily["hermes"]?.current.authenticated`:
  `true` → "Signed in"; `false`/`nil` → informational text "Run `hermes setup --portal`
  in a terminal, then Refresh."
- `Button("Set Up Hermes…") { model.setUpHermes(for: nil) }` disabled while
  `setupBusyByFamily["hermes"] == true`; show `setupLogByFamily["hermes"]` when present.
- `Button("Refresh") { model.refreshProbe(for: "hermes") }`.

- [ ] **Step 3: Scope the Codex pane Refresh**

Change `CodexSettingsPane`'s `Button("Refresh")` to call `model.refreshProbe(for: "codex")`.
Fix any remaining references to the removed `model.codexStatus` / `model.executorProbe`
to use `statusByFamily["codex"]` / `probeByFamily["codex"]`. Add the `.setUpHermes` and
`.signInHermes` cases to the two action-button `switch`es (setUpHermes → button;
signInHermes → informational text mirroring `.signInCodex`).

- [ ] **Step 4: Build**

Run: `swift build --package-path executor-apps/macos`
Expected: build succeeds (no references to removed symbols).

- [ ] **Step 5: Commit**

```bash
git add executor-apps/macos/Sources/NewbroExecutor/ExecutorSettingsView.swift
git commit -m "feat(macapp): add Hermes Settings pane with scoped refresh and sign-in text"
```

---

## Task 10: No-fallback single-choice picker in ProfileEditView

**Files:**
- Modify: `executor-apps/macos/Sources/NewbroExecutor/ProfileEditView.swift`
- Test: `executor-apps/macos/Tests/NewbroExecutorCoreTests/ProfileFamilySelectionTests.swift` (pure helper)

- [ ] **Step 1: Write the failing test (pure helper)**

```swift
// ProfileFamilySelectionTests.swift
func testInitialFamilyIsNilForNewProfileAndValidatesExisting() {
    XCTAssertNil(initialPickerFamily(for: nil))                       // new profile: no default
    XCTAssertEqual(initialPickerFamily(for: ["hermes"]), "hermes")    // existing valid
    XCTAssertNil(initialPickerFamily(for: []))                        // empty -> unselected/flag
    XCTAssertNil(initialPickerFamily(for: ["bogus"]))                 // legacy/unknown -> unselected/flag
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `swift test --package-path executor-apps/macos --filter ProfileFamilySelectionTests`
Expected: FAIL — `initialPickerFamily` not defined.

- [ ] **Step 3: Implement the helper**

Add to `ExecutorFamilies.swift`:

```swift
/// The picker's initial selection: a supported family for an existing profile, or nil
/// (no default) so the user must choose explicitly — no fallback to codex.
public func initialPickerFamily(for enabledExecutors: [String]?) -> String? {
    guard let first = enabledExecutors?.first, supportedExecutorFamilies.contains(first) else { return nil }
    return first
}
```

- [ ] **Step 4: Rework the editor**

In `ProfileEditView.swift`: replace `@State private var codex/acpx` toggles with
`@State private var family: String?` initialized in `load()` via
`initialPickerFamily(for: profile?.enabledExecutors)`. Render a single `Picker` over
`supportedExecutorFamilies` with a placeholder "Choose an agent client" when `family ==
nil`. When `family == nil` for an existing profile, show a flag text "This profile has
no valid agent client — choose one." In `save()`, build
`executors = family.map { [$0] } ?? []` and **disable Save when `family == nil`**.

- [ ] **Step 5: Run tests + build**

Run: `swift test --package-path executor-apps/macos --filter ProfileFamilySelectionTests && swift build --package-path executor-apps/macos`
Expected: PASS + build succeeds.

- [ ] **Step 6: Commit**

```bash
git add executor-apps/macos/Sources/NewbroExecutorCore/ExecutorFamilies.swift executor-apps/macos/Sources/NewbroExecutor/ProfileEditView.swift executor-apps/macos/Tests/NewbroExecutorCoreTests/ProfileFamilySelectionTests.swift
git commit -m "feat(macapp): single-choice no-fallback executor picker in profile editor"
```

---

## Task 11: Full verification + docs

**Files:**
- Modify: `docs/architecture/executors.md`, `docs/memories.md`

- [ ] **Step 1: Run both suites**

Run: `.venv/bin/python -m pytest -q` and `swift test --package-path executor-apps/macos`
Expected: both green. Run `.venv/bin/ruff check src/newbro/cli src/newbro/executors/adapters/hermes`.

- [ ] **Step 2: Update docs**

In `docs/architecture/executors.md`, note that the macOS app now supports per-family
readiness and a single-family executor picker (codex/acpx/hermes), and that `acpx` is
run-only (no probe). Append a dated note to `docs/memories.md` summarizing:
default-command-to-PATH, real `install-hermes`, `authenticated` probe field via
`hermes auth list`, single-family local-config writers, and the macOS per-family
panes + no-fallback picker.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/executors.md docs/memories.md
git commit -m "docs: record hermes macapp + cli default-command changes"
```

---

## Notes for the implementer

- **Order matters:** Tasks 1–5 (CLI) define the `--json` contract Tasks 6–10 consume. Do them first.
- **Task 3 risk:** aligning `set_codex_command` to single-element may break an existing test that asserted append/preserve, and could interact with `_try_auto_configure_codex_executor_runtime`. Run the full `tests/unit/cli` suite and update expectations to the single-family invariant.
- **Task 8 is the heaviest** (AppModel rework). Keep the pure scoping/decision logic in `NewbroExecutorCore` (testable) and `AppModel` as a thin caller. If `AppModel` can't be unit-tested, that's expected — the rules live in tested helpers (`probeScope`, `diagnoseProfileStart`, `initialPickerFamily`).
- **No Terminal launcher anywhere** — sign-in and install-failure are informational text + the in-app streamed install, mirroring Codex exactly.
