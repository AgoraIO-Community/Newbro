# Executor Mac app quit hang — design

**Date:** 2026-06-08
**Status:** Approved design, pre-implementation
**Scope:** Bug fix across two layers (macOS menu-bar app + Python executor node). Independent of the skill-picker feature.

## Symptom

Quitting "Newbro Executor.app" hangs every time — the app becomes unresponsive (beachball) and never exits. Separately, orphaned `codex app-server` processes accumulate across runs.

## Root cause (confirmed in code)

A cross-layer deadlock on the quit path:

1. **The Python node ignores SIGTERM.** `src/newbro/executors/node/__main__.py` runs `asyncio.run(service.run_forever())` and only catches `KeyboardInterrupt` (SIGINT). The Mac app's stop sends **SIGTERM** (`Process.terminate()`), which Python does not handle → the process dies via the default action without running any cleanup.
2. **No executor shutdown on exit.** `ExecutorNodeService.run_forever` (`src/newbro/executors/node/service.py:153`) re-raises `CancelledError` (line 198) and has no `finally` that closes executors. The `CodexExecutor` app-session (and its `codex app-server` child) is never closed on shutdown, so the grandchild is orphaned on every exit.
3. **The grandchild keeps the pipe open.** `NodeProcess` (`executor-apps/macos/Sources/NewbroExecutorCore/NodeProcess.swift`) spawns the child with a shared `Pipe` for stdout/stderr and **no process-group isolation** (plain `Process.run`). The surviving `codex app-server` inherited the pipe's write end, so the reader loop's `handle.availableData` never returns EOF; the reader never finishes and `onExit` never fires.
4. **Quit blocks the main thread on that reader.** `AppModel.quit()` (`…/AppModel.swift:673`) calls `supervisor.stopAll()` synchronously on the main thread. `stopAll` → `NodeProcess.stop()` ends with `queue.sync {}` (`NodeProcess.swift:100`) to wait for the reader to drain. Because EOF never arrives, that `sync` blocks the main thread forever → permanent "no response". The SIGKILL fallback (`stop()` line 92) kills only the direct child, not the grandchild holding the pipe, so it does not help.

## Goals

- Quitting the app always exits promptly (no beachball), every time.
- No orphaned `codex app-server` / `newbro executor` processes remain after quit.
- The node shuts down cleanly on SIGTERM and SIGINT from any launcher (app, CLI, future systemd).

## Approach (chosen)

Graceful-first with a force-kill fallback and a hang-proof reader, fixed at both layers so the normal path is clean and the pathological path cannot freeze the UI.

## Section 1 — Python node: signal handling + executor shutdown

**File:** `src/newbro/executors/node/__main__.py`, `src/newbro/executors/node/service.py`, `src/newbro/executors/adapters/codex/executor.py`.

- Replace the bare `asyncio.run(service.run_forever())` with an async main that:
  - Installs `loop.add_signal_handler(signal.SIGTERM, …)` and `(signal.SIGINT, …)`, both cancelling the `run_forever` task. (Fall back to default `KeyboardInterrupt` handling if `add_signal_handler` is unavailable on the platform.)
  - Logs `[stop] executor node interrupted` on signal.
  - Calls `await service.aclose()` in a `finally` so **every** exit path (signal, cancel, error) tears down executors.
- Add `ExecutorNodeService.aclose()` that iterates `self._executors` and awaits a shutdown hook on each:
  - `CodexExecutor.aclose()` (new public method) → `await self._close_app_session()` (terminates the `codex app-server` child).
  - `AcpxExecutor` / `MockExecutor` / `HostedExecutor`: no-op `aclose()` (or guard with `getattr`).
- Call `os.setsid()` at node startup so the node leads its own session/process group; this makes group-kill (Section 2) reliable and prevents the node + codex child from receiving signals aimed only at the parent app.

**Outcome:** SIGTERM and SIGINT both trigger a graceful shutdown that closes the codex app-server; no orphaned grandchildren on normal exit.

## Section 2 — Swift: process-group kill + hang-proof, non-blocking stop

**File:** `executor-apps/macos/Sources/NewbroExecutorCore/NodeProcess.swift`, `ProfileSupervisor.swift`, `…/NewbroExecutor/AppModel.swift`.

1. **Isolate the child's process group at spawn.** Foundation `Process` cannot `setpgid` directly; spawn via `posix_spawn` with `POSIX_SPAWN_SETPGROUP` (or a minimal launcher that calls `setsid()` before exec). Combined with the node's own `os.setsid()`, the node + codex app-server form one killable group.
2. **Group-signal on stop.** In `stop()`, `kill(-pgid, SIGTERM)` → bounded wait (existing 5s, run off the main thread) → `kill(-pgid, SIGKILL)`. This reaches the codex grandchild, so nothing is orphaned.
3. **Make the reader EOF-independent.** Store the read `FileHandle` (and `Pipe`) as properties; in `stop()`, after the process is gone, **close the read handle**. Closing the read end unblocks `availableData` so the reader loop ends, `onExit` fires, and `queue.sync {}` returns. Bound the final drain with a timeout instead of waiting forever.
4. **Quit never blocks the UI.** Run `stopAll()` off the main thread (or give the whole stop a hard overall deadline, e.g. 3s) before calling `NSApplication.terminate`. Because the group-kill and read-handle-close guarantee completion, quit settles fast even in the bad case.

**Outcome:** `stop()` cannot wedge on a surviving writer; quit is bounded and non-blocking; the whole process group dies.

## Section 3 — Testing & verification

**Swift** (`swift test --package-path executor-apps/macos`; extend `NodeProcess` / `ProfileSupervisor` Core tests):
- Regression for the deadlock: `stop()` completes within its bound even when a fake child keeps the pipe write-end open (reader is closed/unblocked; `queue.sync` returns).
- `stop()` group-signals then escalates to SIGKILL after the timeout; `onExit` delivered exactly once.
- `stopAll()` returns within the overall deadline with multiple records.

**Python** (`.venv/bin/python -m pytest tests/unit/executors/node`):
- `ExecutorNodeService.aclose()` awaits each executor's shutdown; `CodexExecutor.aclose()` closes the app-session (assert `_close_app_session`/terminate invoked via a fake session/process).
- Shutdown path: cancelling `run_forever` runs `aclose()` in `finally` (assert cleanup ran). Focused on the contract, not real OS signals.

**Manual verification** (the real proof, per AGENTS.md "verify activation"):
1. Start the branch node; confirm a `codex app-server` child exists (`pgrep -f "codex app-server"`).
2. Quit the app → exits immediately (no beachball); `pgrep -f "codex app-server"` and `pgrep -f "newbro executor"` return nothing.
3. Repeat several times — confirms "every time" is fixed and nothing accumulates.

## Out of scope

- Reworking the executor node's reconnect/run loop beyond adding shutdown.
- Changing the menu-bar app's profile model, UI, or update flow.
- Skill-picker work (separate branch/spec).
