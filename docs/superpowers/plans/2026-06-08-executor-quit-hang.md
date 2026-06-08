# Executor Quit-Hang Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quitting the Newbro Executor Mac app always exits promptly, and no `codex app-server` / `newbro executor` processes are orphaned.

**Architecture:** A three-layer signal-forwarding chain plus a hang-proof reader. The Swift app closes its read pipe on stop so the reader can never wedge on a surviving grandchild; the `newbro executor run` CLI forwards SIGTERM to the node child; the node handles SIGTERM/SIGINT and closes the Codex app-session. No `setsid`/`posix_spawn`.

**Tech Stack:** Swift / XCTest (`executor-apps/macos`); Python 3.12 / pytest (`src/newbro`).

**Spec:** `docs/superpowers/specs/2026-06-08-executor-quit-hang-design.md`
**Branch:** `fix/executor-quit-hang` (off `main`).

**Conventions:**
- Swift tests: `swift test --package-path executor-apps/macos`. Test idiom: XCTest with a `Box<T>` lock wrapper and `expectation`/`wait` (see `executor-apps/macos/Tests/NewbroExecutorCoreTests/NodeProcessTests.swift`).
- Python tests: `.venv/bin/python -m pytest <path>`. Type-check touched Python with `.venv/bin/pyright <file>` (repo gates on pyright; only ensure no NEW errors).

---

## File Structure

- `executor-apps/macos/Sources/NewbroExecutorCore/NodeProcess.swift` — reader uses throwing `read(upToCount:)`; `stop()` closes the read handle + bounded drain. (Task 1)
- `executor-apps/macos/Tests/NewbroExecutorCoreTests/NodeProcessTests.swift` — deadlock regression test. (Task 1)
- `executor-apps/macos/Sources/NewbroExecutor/AppModel.swift` — `quit()` runs `stopAll()` off the main thread + deadline. (Task 2)
- `src/newbro/cli/processes.py` — `run_checked` → `Popen` + SIGTERM/SIGINT forwarding via `_terminate_child`. (Task 3)
- `src/newbro/cli/main.py` — pass `time_module` into the `run_checked` wrapper. (Task 3)
- `tests/unit/cli/test_processes.py` — `_terminate_child` + `run_checked` tests. (Task 3)
- `src/newbro/executors/adapters/codex/executor.py` — `CodexExecutor.aclose()`. (Task 4)
- `src/newbro/executors/node/service.py` — `ExecutorNodeService.aclose()`. (Task 5)
- `src/newbro/executors/node/__main__.py` — async serve wrapper with signal handlers + `finally: aclose()`. (Task 6)
- Python tests under `tests/unit/executors/...` and `tests/unit/executors/node/`. (Tasks 4–6)

---

## Task 1: Swift — EOF-independent, hang-proof `stop()`

**Files:**
- Modify: `executor-apps/macos/Sources/NewbroExecutorCore/NodeProcess.swift`
- Test: `executor-apps/macos/Tests/NewbroExecutorCoreTests/NodeProcessTests.swift`

- [ ] **Step 1: Write the failing regression test**

Add to `NodeProcessTests.swift` (inside the `NodeProcessTests` class):

```swift
    func testStopReturnsWhenGrandchildKeepsPipeOpen() {
        // Regression for the quit hang: the child exits immediately but a
        // backgrounded grandchild keeps stdout open, so the pipe never EOFs.
        // stop() must still return promptly (reader closed) and deliver onExit.
        let exited = expectation(description: "onExit")
        let proc = NodeProcess(
            argv: ["/bin/sh", "-c", "(sleep 30 &) ; printf '[start] up\\n' ; exit 0"],
            onLine: { _ in },
            onExit: { _ in exited.fulfill() }
        )
        proc.start()
        // Give the child time to exit while the grandchild keeps the pipe open.
        Thread.sleep(forTimeInterval: 0.5)

        let returned = expectation(description: "stop returned")
        DispatchQueue.global().async {
            proc.stop(timeout: 2.0)   // must NOT block forever on the wedged reader
            returned.fulfill()
        }
        wait(for: [returned, exited], timeout: 5)
        XCTAssertFalse(proc.isRunning)
    }
```

- [ ] **Step 2: Run test to verify it fails (hangs → times out)**

Run: `swift test --package-path executor-apps/macos --filter testStopReturnsWhenGrandchildKeepsPipeOpen`
Expected: FAIL — `stop()` blocks on `queue.sync {}` (reader never sees EOF), so `returned` is never fulfilled and the wait times out.

- [ ] **Step 3: Make the reader EOF-independent and `stop()` bounded**

Replace the body of `NodeProcess.swift` with this (changes: add a `readHandle` property; reader uses throwing `read(upToCount:)` so closing the handle unblocks it; `stop()` closes the handle and uses a bounded drain instead of `queue.sync {}`):

```swift
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
        // report. The throwing read(upToCount:) lets stop() unblock the reader
        // by closing the handle even when a surviving grandchild still holds
        // the pipe's write end (so availableData would never EOF).
        queue.async { [weak self] in
            while true {
                let chunk: Data?
                do {
                    chunk = try handle.read(upToCount: 65536)
                } catch {
                    break  // handle closed by stop() → unblock
                }
                guard let data = chunk, !data.isEmpty else { break }  // EOF
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
        // Unblock the reader even if a surviving grandchild still holds the pipe
        // write end: closing the read handle makes read(upToCount:) throw/return,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `swift test --package-path executor-apps/macos --filter testStopReturnsWhenGrandchildKeepsPipeOpen`
Expected: PASS (stop returns within ~2s, onExit fires).

- [ ] **Step 5: Run the full NodeProcess + Supervisor suites for regressions**

Run: `swift test --package-path executor-apps/macos`
Expected: all existing `NodeProcessTests` / `ProfileSupervisorTests` PASS (line capture, exit ordering, terminate-long-runner, custom env, stop-delivers-exit).

- [ ] **Step 6: Commit**

```bash
git add executor-apps/macos/Sources/NewbroExecutorCore/NodeProcess.swift executor-apps/macos/Tests/NewbroExecutorCoreTests/NodeProcessTests.swift
git commit -m "fix(macapp): make NodeProcess.stop EOF-independent so quit can't hang"
```

---

## Task 2: Swift — `quit()` never blocks the main thread

**Files:**
- Modify: `executor-apps/macos/Sources/NewbroExecutor/AppModel.swift` (the `quit()` method, ~line 673)

This is AppKit glue (`NSApplication.terminate`) and is verified manually (Task 7), not unit-tested.

- [ ] **Step 1: Replace `quit()`**

Current:

```swift
    func quit() {
        // Stop every node before exiting so no orphaned subprocess survives.
        supervisor.stopAll()
        NSApplication.shared.terminate(nil)
    }
```

Replace with:

```swift
    func quit() {
        // Stop every node off the main thread so the menu-bar UI never freezes,
        // then terminate. A deadline guarantees we exit even if a stop lags.
        DispatchQueue.global().async { [supervisor] in
            supervisor.stopAll()
            DispatchQueue.main.async { NSApplication.shared.terminate(nil) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            NSApplication.shared.terminate(nil)
        }
    }
```

> `supervisor` is a stored property on `AppModel`; capturing it in the closure list avoids a `self` retain cycle. If the compiler reports `supervisor` is not capturable that way (e.g. it's `private let`), use `[weak self]` and call `self?.supervisor.stopAll()` instead.

- [ ] **Step 2: Build to verify it compiles**

Run: `swift build --package-path executor-apps/macos`
Expected: builds with no errors.

- [ ] **Step 3: Commit**

```bash
git add executor-apps/macos/Sources/NewbroExecutor/AppModel.swift
git commit -m "fix(macapp): run node shutdown off the main thread on quit"
```

---

## Task 3: CLI — `run_checked` forwards SIGTERM/SIGINT to the node child

**Files:**
- Modify: `src/newbro/cli/processes.py`
- Modify: `src/newbro/cli/main.py` (the `run_checked` wrapper, ~line 251)
- Test: `tests/unit/cli/test_processes.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/cli/test_processes.py`:

```python
from __future__ import annotations

from newbro.cli import processes


class FakeProc:
    def __init__(self, alive_polls: int = 0, returncode: int = 0):
        # poll() returns None for `alive_polls` calls, then `returncode`.
        self._remaining = alive_polls
        self._returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        if self._remaining > 0:
            self._remaining -= 1
            return None
        return self._returncode

    def wait(self):
        return self._returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakeTime:
    def __init__(self):
        self._t = 0.0

    def time(self):
        return self._t

    def sleep(self, seconds):
        self._t += seconds


def test_terminate_child_terminates_then_kills_if_still_alive():
    # Stays alive past the deadline → escalates to kill().
    proc = FakeProc(alive_polls=1000)
    clock = FakeTime()
    processes._terminate_child(proc, time_module=clock, timeout=5.0)
    assert proc.terminated is True
    assert proc.killed is True


def test_terminate_child_skips_kill_when_child_exits():
    # Exits right after terminate() → no kill().
    proc = FakeProc(alive_polls=0)
    clock = FakeTime()
    processes._terminate_child(proc, time_module=clock, timeout=5.0)
    assert proc.terminated is True
    assert proc.killed is False


class FakeSignal:
    SIGINT = 2
    SIGTERM = 15

    def __init__(self):
        self.handlers = {}

    def signal(self, signum, handler):
        previous = self.handlers.get(signum)
        self.handlers[signum] = handler
        return previous


def test_run_checked_registers_handlers_and_returns_zero():
    sig = FakeSignal()
    captured = {}

    class FakeSubprocess:
        def Popen(self, cmd, cwd=None):
            captured["cmd"] = cmd
            return FakeProc(alive_polls=0, returncode=0)

    rc = processes.run_checked(
        ["python", "-m", "newbro.executors.node"],
        cwd=__import__("pathlib").Path("."),
        subprocess_module=FakeSubprocess(),
        signal_module=sig,
        time_module=FakeTime(),
    )
    assert rc == 0
    assert sig.SIGTERM in sig.handlers and sig.SIGINT in sig.handlers


def test_run_checked_raises_systemexit_on_nonzero():
    sig = FakeSignal()

    class FakeSubprocess:
        def Popen(self, cmd, cwd=None):
            return FakeProc(alive_polls=0, returncode=3)

    try:
        processes.run_checked(
            ["x"],
            cwd=__import__("pathlib").Path("."),
            subprocess_module=FakeSubprocess(),
            signal_module=sig,
            time_module=FakeTime(),
        )
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_processes.py -v`
Expected: FAIL — `processes._terminate_child` does not exist; `run_checked` does not accept `time_module`.

- [ ] **Step 3: Rewrite `run_checked` + add `_terminate_child`**

In `src/newbro/cli/processes.py`, replace the existing `run_checked` function with:

```python
def _terminate_child(process: Any, *, time_module: ModuleType, timeout: float = 5.0) -> None:
    """SIGTERM the child, wait up to `timeout`, then SIGKILL if still alive."""
    if process.poll() is not None:
        return
    process.terminate()
    deadline = time_module.time() + timeout
    while process.poll() is None and time_module.time() < deadline:
        time_module.sleep(0.1)
    if process.poll() is None:
        process.kill()


def run_checked(
    cmd: list[str],
    *,
    cwd: Path,
    subprocess_module: ModuleType,
    signal_module: ModuleType,
    time_module: ModuleType,
) -> int:
    print(f"[run] {' '.join(cmd)}")
    process = subprocess_module.Popen(cmd, cwd=cwd)

    def _forward(_signum: int, _frame: FrameType | None) -> None:
        print("[stop] forwarding shutdown to executor node")
        _terminate_child(process, time_module=time_module)

    previous_term = signal_module.signal(signal_module.SIGTERM, _forward)
    previous_int = signal_module.signal(signal_module.SIGINT, _forward)
    try:
        returncode = process.wait()
    except KeyboardInterrupt:
        print("[stop] interrupted")
        _terminate_child(process, time_module=time_module)
        return 130
    finally:
        signal_module.signal(signal_module.SIGTERM, previous_term)
        signal_module.signal(signal_module.SIGINT, previous_int)
    if returncode in {130, -signal_module.SIGINT}:
        return 130
    if returncode != 0:
        raise SystemExit(returncode)
    return returncode
```

`Any`, `FrameType`, `ModuleType`, and `Path` are already imported at the top of `processes.py`. Add `import time` is NOT needed here (time is injected); leave imports as-is.

- [ ] **Step 4: Wire `time_module` through the `main.py` wrapper**

In `src/newbro/cli/main.py`, update the `run_checked` wrapper (~line 251) to pass `time_module`:

```python
def run_checked(cmd: list[str], cwd: Path) -> int:
    return cli_processes.run_checked(
        cmd,
        cwd=cwd,
        subprocess_module=subprocess,
        signal_module=signal,
        time_module=time,
    )
```

`time` is already imported in `main.py` (used by `run_managed_processes`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_processes.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Run existing CLI tests + pyright**

Run: `.venv/bin/python -m pytest tests/unit/cli -q`
Expected: PASS (no regression in `test_main.py`).
Run: `.venv/bin/pyright src/newbro/cli/processes.py src/newbro/cli/main.py 2>&1 | tail -2`
Expected: no NEW errors from these changes.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/cli/processes.py src/newbro/cli/main.py tests/unit/cli/test_processes.py
git commit -m "fix(cli): forward SIGTERM/SIGINT from executor run to the node child"
```

---

## Task 4: `CodexExecutor.aclose()`

**Files:**
- Modify: `src/newbro/executors/adapters/codex/executor.py`
- Test: `tests/unit/executors/adapters/codex/test_executor_aclose.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/executors/adapters/codex/test_executor_aclose.py`:

```python
import pytest

from newbro.executors.adapters.codex.executor import CodexExecutor


@pytest.mark.anyio
async def test_aclose_closes_app_session(monkeypatch):
    executor = CodexExecutor(command="codex")
    calls = {"closed": 0}

    async def fake_close():
        calls["closed"] += 1

    monkeypatch.setattr(executor, "_close_app_session", fake_close)
    await executor.aclose()
    assert calls["closed"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/adapters/codex/test_executor_aclose.py -v`
Expected: FAIL — `CodexExecutor` has no attribute `aclose`.

- [ ] **Step 3: Add `aclose()`**

In `src/newbro/executors/adapters/codex/executor.py`, add a public method on `CodexExecutor` (place it next to `_close_app_session`):

```python
    async def aclose(self) -> None:
        """Shut down the executor: close the app-session so the codex
        app-server child process is terminated. Safe to call when idle."""
        async with self._app_lock:
            if self._app_session is not None:
                await self._close_app_session()
```

> `self._app_lock` already guards `_app_session` lifecycle (see `_ensure_app_session`). `_close_app_session` already sets `self._app_session = None`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/adapters/codex/test_executor_aclose.py -v`
Expected: PASS.

- [ ] **Step 5: pyright (no new errors) + commit**

Run: `.venv/bin/pyright src/newbro/executors/adapters/codex/executor.py 2>&1 | tail -2`
Expected: no NEW errors from this addition.

```bash
git add src/newbro/executors/adapters/codex/executor.py tests/unit/executors/adapters/codex/test_executor_aclose.py
git commit -m "feat: add CodexExecutor.aclose to terminate the app-server"
```

---

## Task 5: `ExecutorNodeService.aclose()`

**Files:**
- Modify: `src/newbro/executors/node/service.py`
- Test: `tests/unit/executors/node/test_service_aclose.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/executors/node/test_service_aclose.py`:

```python
import pytest

from newbro.executors.node.service import ExecutorNodeService


@pytest.mark.anyio
async def test_aclose_calls_executor_aclose_when_present(monkeypatch):
    closed = []

    class FakeCodex:
        async def aclose(self):
            closed.append("codex")

    class FakeAcpx:
        pass  # no aclose → must be skipped cleanly

    # Build a bare service instance without running __init__ side effects.
    service = ExecutorNodeService.__new__(ExecutorNodeService)
    service._executors = {"codex": FakeCodex(), "acpx": FakeAcpx()}

    await service.aclose()
    assert closed == ["codex"]
```

> Confirm `ExecutorNodeService` stores executors as `self._executors` (it does — `service.py:139`). If `aclose` needs other attributes, set them on the bare instance in the test.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_service_aclose.py -v`
Expected: FAIL — `ExecutorNodeService` has no `aclose`.

- [ ] **Step 3: Add `aclose()`**

In `src/newbro/executors/node/service.py`, add a method on `ExecutorNodeService` (near `run_forever`):

```python
    async def aclose(self) -> None:
        """Shut down all executors that expose an async aclose() hook."""
        for executor in self._executors.values():
            aclose = getattr(executor, "aclose", None)
            if aclose is None:
                continue
            try:
                await aclose()
            except Exception:
                # Best-effort teardown: one executor failing must not block
                # the others or the process exit.
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_service_aclose.py -v`
Expected: PASS.

- [ ] **Step 5: pyright (no new errors) + commit**

Run: `.venv/bin/pyright src/newbro/executors/node/service.py 2>&1 | tail -2`
Expected: no NEW errors.

```bash
git add src/newbro/executors/node/service.py tests/unit/executors/node/test_service_aclose.py
git commit -m "feat: add ExecutorNodeService.aclose to shut down executors"
```

---

## Task 6: Node `__main__` — signal handlers + `finally: aclose()`

**Files:**
- Modify: `src/newbro/executors/node/__main__.py`
- Test: `tests/unit/executors/node/test_executor_node_main.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/executors/node/test_executor_node_main.py`:

```python
import asyncio


def test_serve_runs_aclose_in_finally(monkeypatch):
    closed = {"n": 0}

    class FakeService:
        async def run_forever(self):
            raise asyncio.CancelledError()

        async def aclose(self):
            closed["n"] += 1

    # _serve must always call aclose(), even when run_forever is cancelled.
    async def drive():
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await executor_node_main._serve(FakeService())

    asyncio.run(drive())
    assert closed["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_executor_node_main.py::test_serve_runs_aclose_in_finally -v`
Expected: FAIL — `_serve` does not exist.

- [ ] **Step 3: Add `_serve` + install signal handlers; route `main` through it**

In `src/newbro/executors/node/__main__.py`:

Add imports at the top (after the existing imports):

```python
import contextlib
import signal
```

Add the `_serve` coroutine (module level, above `main`):

```python
async def _serve(service: ExecutorNodeService) -> None:
    """Run the node until cancelled, installing SIGTERM/SIGINT handlers that
    request a graceful shutdown, and always closing executors on exit."""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(service.run_forever())

    def _request_stop() -> None:
        print("[stop] executor node interrupted")
        task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_stop)

    try:
        await task
    finally:
        await service.aclose()
```

Change the `try/except` in `main()` from:

```python
    try:
        asyncio.run(service.run_forever())
    except KeyboardInterrupt:
        print("[stop] executor node interrupted")
        return 130
    return 0
```

to:

```python
    try:
        asyncio.run(_serve(service))
    except KeyboardInterrupt:
        print("[stop] executor node interrupted")
        return 130
    except asyncio.CancelledError:
        return 130
    return 0
```

> The existing `test_main_returns_130_on_keyboard_interrupt` monkeypatches `asyncio.run` to raise `KeyboardInterrupt`, so it still passes (the `except KeyboardInterrupt` branch is unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_executor_node_main.py -v`
Expected: PASS (new `_serve` test + existing main tests).

- [ ] **Step 5: pyright (no new errors) + commit**

Run: `.venv/bin/pyright src/newbro/executors/node/__main__.py 2>&1 | tail -2`
Expected: no NEW errors.

```bash
git add src/newbro/executors/node/__main__.py tests/unit/executors/node/test_executor_node_main.py
git commit -m "feat: handle SIGTERM/SIGINT in the executor node and close executors on exit"
```

---

## Task 7: Full verification

- [ ] **Step 1: Swift suite**

Run: `swift test --package-path executor-apps/macos`
Expected: all PASS. Fix any regression before continuing.

- [ ] **Step 2: Python suites**

Run: `.venv/bin/python -m pytest tests/unit/cli tests/unit/executors -q`
Expected: all PASS.

- [ ] **Step 3: Build the app**

Run: `./executor-apps/macos/package-app.sh`
Expected: builds `executor-apps/macos/dist/Newbro Executor.app`.

- [ ] **Step 4: Manual smoke (the real proof)**

1. Quit any old Executor.app. Start the rebuilt app pointed at this branch's CLI:
   ```bash
   launchctl setenv NEWBRO_BIN "$PWD/newbro"
   open "executor-apps/macos/dist/Newbro Executor.app"
   ```
2. Start a node profile; confirm the chain is up: `pgrep -fl "codex app-server"` and `pgrep -fl "newbro executor"` show processes.
3. Quit the app from the menu bar. Confirm: the app exits **immediately** (no beachball), and within a couple seconds `pgrep -f "codex app-server"` and `pgrep -f "newbro executor"` return **nothing**.
4. Repeat 3–4 times → no hang ever, no accumulation.

- [ ] **Step 5: Commit any verification fixes**

```bash
git add -A && git commit -m "fix: address issues found during quit-hang verification"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §1 Swift hang-proof stop → Task 1 (EOF-independent reader + close handle + bounded drain) and Task 2 (off-main quit).
- §2 CLI forwards SIGTERM → Task 3 (`run_checked` Popen + `_terminate_child`).
- §3 Node signals + executor close → Task 4 (`CodexExecutor.aclose`), Task 5 (`ExecutorNodeService.aclose`), Task 6 (`_serve` signal handlers + finally aclose).
- §4 Testing → tests in Tasks 1, 3, 4, 5, 6 + manual smoke in Task 7.

**Placeholder scan:** none — every code step shows complete code; every command has an expected result.

**Type/name consistency:** `_terminate_child(process, *, time_module, timeout)` used identically in `run_checked` and its tests; `aclose()` is the method name on both `CodexExecutor` and `ExecutorNodeService` and is what `_serve`/`run_checked` rely on; `_serve(service)` matches the node test; Swift `readHandle` / `stop(timeout:)` consistent between `start()`, `stop()`, and the test.
