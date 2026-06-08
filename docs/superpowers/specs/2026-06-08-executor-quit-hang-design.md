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

## Approach (chosen): signal-forwarding chain + hang-proof reader

The executor is a **three-level process tree**, and the middle level blocks without forwarding signals:

```
Swift app ──spawn──► newbro executor run        (X: CLI; blocks in subprocess.run; only catches SIGINT)
                         └─spawn──► python -m newbro.executors.node   (Y: node; asyncio run_forever)
                                       └─spawn──► codex app-server     (Z)
```

The app sends SIGTERM to **X only**; X does not forward it, so Y and Z orphan and hold the inherited pipe → the reader never EOFs → quit deadlocks.

The fix makes each layer clean up its own child (a signal-forwarding chain) and makes the Swift reader EOF-independent so it can never wedge. **No `os.setsid`/`setpgrp` and no `posix_spawn`** — process-group tricks were rejected because `setpgrp` in the CLI breaks terminal Ctrl-C job control, and `posix_spawn` is a heavy, risky rewrite of the Swift spawn path.

## Section 1 — Swift: hang-proof, non-blocking stop (fixes the freeze)

**File:** `executor-apps/macos/Sources/NewbroExecutorCore/NodeProcess.swift`, `ProfileSupervisor.swift`, `…/NewbroExecutor/AppModel.swift`.

1. **Make the reader EOF-independent.** Store the read `FileHandle` (and `Pipe`) as properties. In `stop()`, after signalling the process, **close the read handle**. Closing the read end unblocks the reader's `availableData` even when a surviving grandchild still holds the write end, so the reader loop ends, `onExit` fires, and the final `queue.sync {}` returns. This is the direct fix for the reported hang.
2. **Bound the drain.** Replace the unbounded `queue.sync {}` with a bounded wait; never wait forever for the reader.
3. **Keep the existing direct-child escalation:** `terminate()` (SIGTERM to X) → bounded wait → SIGKILL. Orphan cleanup of Y/Z is handled by Sections 2–3 (the signal-forwarding chain), not by the app.
4. **Quit never blocks the UI.** Run `stopAll()` off the main thread (or give the whole stop a hard overall deadline, e.g. 3s) before `NSApplication.terminate`. Because the read-handle-close guarantees the per-process stop completes, quit settles fast even in the bad case.

**Outcome:** `stop()` cannot wedge on a surviving writer; quit is bounded and non-blocking.

## Section 2 — CLI: forward SIGTERM to the node child

**File:** `src/newbro/cli/processes.py` (`run_checked`).

`run_checked` currently calls `subprocess_module.run(...)` (blocking) and only catches `KeyboardInterrupt`. Change it to:
- Launch the node with `subprocess_module.Popen(...)` and keep the handle.
- Install handlers for `SIGTERM` and `SIGINT` (via the injected `signal_module`) that **forward `terminate()` to the child**, wait a bounded time (e.g. 5s), then `kill()` the child if still alive.
- Preserve current behavior: return 130 on interrupt; raise `SystemExit(returncode)` on non-zero; return 0 on success.

**Outcome:** when the app SIGTERMs the CLI (X), X forwards SIGTERM to the node (Y) instead of dying and orphaning it.

## Section 3 — Node: handle signals + close executors

**File:** `src/newbro/executors/node/__main__.py`, `src/newbro/executors/node/service.py`, `src/newbro/executors/adapters/codex/executor.py`.

- Replace the bare `asyncio.run(service.run_forever())` with an async main that:
  - Installs `loop.add_signal_handler(signal.SIGTERM, …)` and `(signal.SIGINT, …)`, both cancelling the `run_forever` task. (Fall back to default `KeyboardInterrupt` handling if `add_signal_handler` is unavailable.)
  - Logs `[stop] executor node interrupted` on signal.
  - Calls `await service.aclose()` in a `finally` so **every** exit path (signal, cancel, error) tears down executors.
- Add `ExecutorNodeService.aclose()` that iterates `self._executors` and awaits an optional `aclose()` on each via `getattr(executor, "aclose", None)` (keeps acpx/mock/hosted untouched — YAGNI).
- Add `CodexExecutor.aclose()` (new public method) → `await self._close_app_session()` (terminates the `codex app-server` child Z).

**Outcome:** the node (Y) shuts down gracefully on SIGTERM/SIGINT from any launcher and closes the Codex app-server; no orphaned Z.

## Section 4 — Testing & verification

**Swift** (`swift test --package-path executor-apps/macos`; extend `NodeProcessTests` / `ProfileSupervisorTests`):
- Regression for the deadlock: a child that exits immediately while a **grandchild keeps stdout open** (`/bin/sh -c "(sleep 30 &); printf '[start]\n'; exit 0"`). `stop()` must return within a short bound and deliver `onExit` — proving the reader is closed/unblocked rather than wedged. (Run `stop()` on a background queue with an XCTest expectation + timeout so a regression fails fast instead of hanging the suite.)
- `onExit` is delivered exactly once after `stop()`.
- `stopAll()` returns within the overall deadline with multiple records.

**Python — CLI** (`.venv/bin/python -m pytest tests/unit/cli`):
- `run_checked` installs SIGTERM/SIGINT handlers (assert via the injected fake `signal_module`) and, on signal, forwards `terminate()` to the child `Popen` and escalates to `kill()` after the bound (assert via a fake `subprocess_module`/fake process). Preserves the existing return-code contract (0 / 130 / `SystemExit(rc)`).

**Python — node** (`.venv/bin/python -m pytest tests/unit/executors/node`):
- `ExecutorNodeService.aclose()` awaits an `aclose()` on each executor that defines one (assert `CodexExecutor.aclose()` → `_close_app_session`/terminate invoked via a fake session/process; acpx/mock without `aclose` are skipped cleanly).
- Shutdown path: cancelling `run_forever` runs `aclose()` in `finally` (assert cleanup ran). Focused on the contract, not real OS signals.

**Manual verification** (the real proof, per AGENTS.md "verify activation"):
1. Start the branch node; confirm a `codex app-server` child exists (`pgrep -f "codex app-server"`).
2. Quit the app → exits immediately (no beachball); `pgrep -f "codex app-server"` and `pgrep -f "newbro executor"` return nothing.
3. Repeat several times — confirms "every time" is fixed and nothing accumulates.

## Out of scope

- Reworking the executor node's reconnect/run loop beyond adding shutdown.
- Changing the menu-bar app's profile model, UI, or update flow.
- Skill-picker work (separate branch/spec).
