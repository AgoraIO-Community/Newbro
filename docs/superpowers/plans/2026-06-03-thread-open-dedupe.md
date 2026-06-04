# Thread Open Dedupe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Bro Detail thread opening idempotent so selecting one imported Codex thread cannot start duplicate history reads while still preserving selected-thread subscription behavior.

**Architecture:** Backend idempotency lives in `BroDetailThreadProjection`, which already owns imported thread state, timeline status, timeline errors, and selected Codex subscriptions. Frontend request dedupe lives in `NewbroShell`, because desktop and mobile detail views can each create a `useThreadSelection` instance and both delegate to the shell. The change intentionally does not optimize Codex history read latency or add fallback history behavior.

**Tech Stack:** Python 3.12, asyncio, pytest, FastAPI runtime tests, React 19, TypeScript, Vitest, Testing Library.

---

## File Structure

- Modify: `src/newbro/runtime/bro_detail_thread_projection.py`
  - Add a per-public-thread in-flight timeline load map.
  - Split existing history load body into a private one-shot loader.
  - Keep `open_bro_thread` and selected-thread subscription behavior unchanged except for idempotent history load calls.
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py`
  - Add focused backend unit tests for concurrent load sharing, loaded-thread skip, failed-thread retry, and loaded-open subscription preservation.
- Create: `src/newbro/ui/src/lib/thread-open-dedupe.ts`
  - Provide a tiny pure helper for shell-level in-flight request tracking.
- Create: `src/newbro/ui/src/lib/thread-open-dedupe.test.ts`
  - Test the pure helper directly.
- Modify: `src/newbro/ui/src/NewbroShell.tsx`
  - Use the helper to dedupe duplicate open requests for the same `(bro_id, thread_id)` while preserving the existing sequence guard.
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`
  - Add a regression test that a loading snapshot followed by the same selected thread does not schedule a second open.
- Keep: `src/newbro/ui/src/lib/useThreadSelection.ts`
  - Do not change this hook unless a failing test proves the shell dedupe cannot solve the duplicate request. Its local `openedThreadRef` remains useful for one mounted view.

## Implementation Notes

- Do not add fallback behavior. If Codex history loading fails, keep the existing failed status and error message path.
- Key backend history loads by the public Bro Detail thread id, for example `codex-import-a57f75dd1703fa8e`.
- Key frontend open requests by `targetPersonaId + "\u0000" + threadId` through a helper so ids cannot collide when they contain punctuation.
- Do not make `subscribe_codex_thread` wait behind the frontend dedupe. Backend `open_bro_thread` must still schedule or keep the selected-thread subscription when a loaded thread is opened.
- Preserve `threadOpenSequenceRef`: it protects stale response application when the user switches from one thread to another before the first open resolves.

---

### Task 1: Add Backend Timeline Idempotency Tests

**Files:**
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py`

- [ ] **Step 1: Add imports and a projection harness**

At the top of `tests/unit/runtime/test_bro_detail_thread_projection.py`, change the imports to include `asyncio`, `Any`, and executor-node protocol types:

```python
import asyncio
from typing import Any

import pytest

from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.protocol import AgentResumeHandle, BroThread, ExecutorNodeExecutor, Persona
from newbro.runtime import Settings
from newbro.runtime.bro_detail_thread_projection import BroDetailThreadProjection
from newbro.runtime.executor_node_manager import NodeConnectionState
from newbro.runtime.session import create_session_runtime
```

Append this helper after the imports:

```python
async def _projection_harness():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    publish_calls: list[str] = []

    async def publish_snapshot() -> object:
        publish_calls.append("published")
        return await session.snapshot(sync_imported_codex_threads=False)

    projection = BroDetailThreadProjection(
        session_id=session.session_id,
        blackboard=session.blackboard,
        executor_node_manager=session.executor_node_manager,
        interaction_manager=session.interaction_manager,
        observability=session.observability,
        publish_snapshot=publish_snapshot,
    )
    return session, persona, projection, publish_calls
```

- [ ] **Step 2: Write the failing concurrent-load test**

Append this test:

```python
@pytest.mark.anyio
async def test_concurrent_timeline_loads_share_one_codex_history_request(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, publish_calls = await _projection_harness()
    resume_handle = AgentResumeHandle(executor_id="codex", session_handle="native-thread-1")
    release_read = asyncio.Event()
    read_calls: list[tuple[str, str]] = []

    async def fake_request_codex_thread(
        *, node_id: str, thread_id: str, timeout_seconds: float = 8.0
    ) -> dict[str, Any]:
        read_calls.append((node_id, thread_id))
        await release_read.wait()
        return {"id": thread_id, "turns": []}

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fake_request_codex_thread)

    first = asyncio.create_task(
        projection.load_bro_thread_timeline(
            persona=persona,
            public_thread_id="codex-import-1",
            node_id="node-forge",
            resume_handle=resume_handle,
        )
    )
    for _ in range(20):
        await asyncio.sleep(0)
        if read_calls:
            break
    assert read_calls == [("node-forge", "native-thread-1")]

    second = asyncio.create_task(
        projection.load_bro_thread_timeline(
            persona=persona,
            public_thread_id="codex-import-1",
            node_id="node-forge",
            resume_handle=resume_handle,
        )
    )
    await asyncio.sleep(0)
    assert read_calls == [("node-forge", "native-thread-1")]

    release_read.set()
    await asyncio.gather(first, second)

    assert read_calls == [("node-forge", "native-thread-1")]
    assert projection.timeline_status["codex-import-1"] == "loaded"
    assert projection.timeline_errors.get("codex-import-1") is None
    assert publish_calls == ["published"]
```

- [ ] **Step 3: Write loaded-skip and failed-retry tests**

Append these tests:

```python
@pytest.mark.anyio
async def test_loaded_timeline_load_skips_codex_history_request(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, publish_calls = await _projection_harness()
    projection.timeline_status["codex-import-1"] = "loaded"
    projection.timeline_errors["codex-import-1"] = "old error"
    resume_handle = AgentResumeHandle(executor_id="codex", session_handle="native-thread-1")

    async def fail_request_codex_thread(**kwargs):
        raise AssertionError("loaded timeline must not read Codex history again")

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fail_request_codex_thread)

    await projection.load_bro_thread_timeline(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
        resume_handle=resume_handle,
    )

    assert projection.timeline_status["codex-import-1"] == "loaded"
    assert projection.timeline_errors["codex-import-1"] == "old error"
    assert publish_calls == []


@pytest.mark.anyio
async def test_failed_timeline_load_retries_codex_history_request(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, publish_calls = await _projection_harness()
    projection.timeline_status["codex-import-1"] = "failed"
    projection.timeline_errors["codex-import-1"] = "Timed out reading Codex thread history."
    resume_handle = AgentResumeHandle(executor_id="codex", session_handle="native-thread-1")
    read_calls: list[tuple[str, str]] = []

    async def fake_request_codex_thread(
        *, node_id: str, thread_id: str, timeout_seconds: float = 8.0
    ) -> dict[str, Any]:
        read_calls.append((node_id, thread_id))
        return {"id": thread_id, "turns": []}

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fake_request_codex_thread)

    await projection.load_bro_thread_timeline(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
        resume_handle=resume_handle,
    )

    assert read_calls == [("node-forge", "native-thread-1")]
    assert projection.timeline_status["codex-import-1"] == "loaded"
    assert projection.timeline_errors.get("codex-import-1") is None
    assert publish_calls == ["published"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py -q
```

Expected before implementation:

```text
FAILED tests/unit/runtime/test_bro_detail_thread_projection.py::test_concurrent_timeline_loads_share_one_codex_history_request
FAILED tests/unit/runtime/test_bro_detail_thread_projection.py::test_loaded_timeline_load_skips_codex_history_request
```

The exact assertion text may differ, but at least one failure must show duplicate or unwanted `request_codex_thread` calls.

---

### Task 2: Implement Backend Timeline Load Idempotency

**Files:**
- Modify: `src/newbro/runtime/bro_detail_thread_projection.py`
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`

- [ ] **Step 1: Add an in-flight task map to the projection state**

In `BroDetailThreadProjection`, add this field near `timeline_status` and `timeline_errors`:

```python
    timeline_load_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
```

The surrounding fields should look like:

```python
    bro_thread_live_message_deltas: dict[tuple[str, str, str], str] = field(default_factory=dict)
    timeline_status: dict[str, Literal["not_loaded", "loading", "loaded", "failed"]] = field(default_factory=dict)
    timeline_errors: dict[str, str] = field(default_factory=dict)
    timeline_load_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    bro_thread_live_plan_deltas: dict[tuple[str, str, str], str] = field(default_factory=dict)
```

- [ ] **Step 2: Wrap `load_bro_thread_timeline` with idempotency**

Replace the current `load_bro_thread_timeline` method body with this wrapper and add the private one-shot method immediately below it:

```python
    async def load_bro_thread_timeline(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
    ) -> None:
        if self.timeline_status.get(public_thread_id) == "loaded":
            return

        existing_task = self.timeline_load_tasks.get(public_thread_id)
        if existing_task is not None:
            if not existing_task.done():
                await existing_task
                return
            self.timeline_load_tasks.pop(public_thread_id, None)

        load_task = asyncio.create_task(
            self._load_bro_thread_timeline_once(
                persona=persona,
                public_thread_id=public_thread_id,
                node_id=node_id,
                resume_handle=resume_handle,
            )
        )
        self.timeline_load_tasks[public_thread_id] = load_task
        try:
            await load_task
        finally:
            if self.timeline_load_tasks.get(public_thread_id) is load_task:
                self.timeline_load_tasks.pop(public_thread_id, None)

    async def _load_bro_thread_timeline_once(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
    ) -> None:
        from newbro.runtime.session import _codex_thread_goal, _timeline_turns_from_codex_thread

        native_thread_id = resume_handle.session_handle
        if not isinstance(native_thread_id, str) or not native_thread_id:
            return
        self.timeline_status[public_thread_id] = "loading"
        self.timeline_errors.pop(public_thread_id, None)
        await self.publish_snapshot()
        try:
            thread = await self.executor_node_manager.request_codex_thread(
                node_id=node_id,
                thread_id=native_thread_id,
            )
        except Exception as exc:
            message = str(exc).strip() or "Codex thread history could not be loaded."
            self.bro_thread_executor_turns.pop(public_thread_id, None)
            self.timeline_status[public_thread_id] = "failed"
            self.timeline_errors[public_thread_id] = message
            LOGGER.warning(
                "Failed to load Codex thread history for %s/%s: %s",
                public_thread_id,
                native_thread_id,
                message,
            )
            return
        thread_goal = _codex_thread_goal(thread)
        if thread_goal:
            self.bro_thread_goals[public_thread_id] = thread_goal
        for turn in _timeline_turns_from_codex_thread(
            thread=thread,
            public_thread_id=public_thread_id,
            executor_thread_id=native_thread_id,
            persona_id=persona.persona_id,
            executor_id="codex",
        ):
            self.upsert_bro_thread_executor_turn(turn)
        self.timeline_status[public_thread_id] = "loaded"
        self.timeline_errors.pop(public_thread_id, None)
```

- [ ] **Step 3: Run focused backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py -q
```

Expected:

```text
4 passed
```

If the file has more tests by the time this plan runs, the exact count can be higher, but all tests in this file must pass.

- [ ] **Step 4: Commit backend idempotency**

Run:

```bash
git add src/newbro/runtime/bro_detail_thread_projection.py tests/unit/runtime/test_bro_detail_thread_projection.py
git commit -m "fix: dedupe bro thread history loads"
```

---

### Task 3: Prove Loaded Opens Still Preserve Subscription

**Files:**
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py`

- [ ] **Step 1: Add a failing subscription-preservation test**

Append this test to `tests/unit/runtime/test_bro_detail_thread_projection.py`:

```python
@pytest.mark.anyio
async def test_open_loaded_imported_thread_skips_history_read_but_subscribes(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, _publish_calls = await _projection_harness()
    session.executor_node_manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=object(),
        node_id="node-forge",
        connected_at="2026-06-03T00:00:00+00:00",
        executors={
            "codex": ExecutorNodeExecutor(
                executor_type="codex",
                supports_resume=True,
                supports_follow_up=True,
                supports_audio_instruction=True,
                supports_thread_list=True,
            )
        },
    )
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        workspace_id="/tmp/work",
        workspace_name="work",
        title="Imported thread",
        status="completed",
        progress=100,
        task_ids=[],
        active_task_id=None,
        latest_task_id=None,
        has_resume_handle=True,
        diagnostics={"codex_thread_id": "native-thread-1"},
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
        opaque={"cwd": "/tmp/work"},
    )
    projection.timeline_status["codex-import-1"] = "loaded"
    subscription_calls: list[tuple[str, str, str | None]] = []

    async def fail_request_codex_thread(**kwargs):
        raise AssertionError("loaded open must not read Codex history again")

    async def fake_subscribe_codex_thread(
        *,
        node_id: str,
        subscription_id: str,
        session_id: str,
        target_persona_id: str,
        target_thread_id: str,
        thread_id: str,
        workspace_id=None,
        timeout_seconds: float = 8.0,
    ) -> None:
        subscription_calls.append((target_thread_id, thread_id, workspace_id))

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fail_request_codex_thread)
    monkeypatch.setattr(session.executor_node_manager, "subscribe_codex_thread", fake_subscribe_codex_thread)

    await projection.open_bro_thread(target_persona_id="forge", thread_id="codex-import-1")
    task = projection.selected_codex_thread_subscription_tasks.get("forge")
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)

    assert subscription_calls == [("codex-import-1", "native-thread-1", "/tmp/work")]
    selected = projection.selected_codex_thread_subscriptions["forge"]
    assert selected.public_thread_id == "codex-import-1"
    assert selected.codex_thread_id == "native-thread-1"
```

- [ ] **Step 2: Run the new test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_open_loaded_imported_thread_skips_history_read_but_subscribes -q
```

Expected after Task 2:

```text
1 passed
```

If it fails because `websocket=object()` is too strict for `NodeConnectionState`, replace that value with a small fake websocket:

```python
class _FakeWebSocket:
    async def send_json(self, payload: dict[str, object]) -> None:
        return None
```

and use `websocket=_FakeWebSocket()`.

- [ ] **Step 3: Commit the subscription regression test**

Run:

```bash
git add tests/unit/runtime/test_bro_detail_thread_projection.py
git commit -m "test: cover loaded bro thread subscription"
```

---

### Task 4: Add Frontend In-Flight Dedupe Helper

**Files:**
- Create: `src/newbro/ui/src/lib/thread-open-dedupe.ts`
- Create: `src/newbro/ui/src/lib/thread-open-dedupe.test.ts`

- [ ] **Step 1: Write the helper tests first**

Create `src/newbro/ui/src/lib/thread-open-dedupe.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { beginThreadOpen, finishThreadOpen, threadOpenKey } from "./thread-open-dedupe";

describe("thread-open-dedupe", () => {
  it("builds stable collision-resistant keys", () => {
    expect(threadOpenKey("forge", "thread-1")).toBe("forge\u0000thread-1");
    expect(threadOpenKey("for:ge", "thread:1")).toBe("for:ge\u0000thread:1");
  });

  it("allows the first open and rejects duplicates until finished", () => {
    const inFlight = new Set<string>();

    const first = beginThreadOpen(inFlight, "forge", "thread-1");
    const duplicate = beginThreadOpen(inFlight, "forge", "thread-1");
    const otherThread = beginThreadOpen(inFlight, "forge", "thread-2");

    expect(first).toBe("forge\u0000thread-1");
    expect(duplicate).toBeNull();
    expect(otherThread).toBe("forge\u0000thread-2");

    finishThreadOpen(inFlight, first);
    expect(beginThreadOpen(inFlight, "forge", "thread-1")).toBe("forge\u0000thread-1");
  });
});
```

- [ ] **Step 2: Run the helper test to verify it fails**

Run:

```bash
cd src/newbro/ui
bun run test src/lib/thread-open-dedupe.test.ts
```

Expected before implementation:

```text
FAIL src/lib/thread-open-dedupe.test.ts
Error: Failed to resolve import "./thread-open-dedupe"
```

- [ ] **Step 3: Implement the helper**

Create `src/newbro/ui/src/lib/thread-open-dedupe.ts`:

```ts
export function threadOpenKey(targetPersonaId: string, threadId: string): string {
  return `${targetPersonaId}\u0000${threadId}`;
}

export function beginThreadOpen(
  inFlight: Set<string>,
  targetPersonaId: string,
  threadId: string,
): string | null {
  const key = threadOpenKey(targetPersonaId, threadId);
  if (inFlight.has(key)) {
    return null;
  }
  inFlight.add(key);
  return key;
}

export function finishThreadOpen(inFlight: Set<string>, key: string | null): void {
  if (key !== null) {
    inFlight.delete(key);
  }
}
```

- [ ] **Step 4: Run the helper test to verify it passes**

Run:

```bash
cd src/newbro/ui
bun run test src/lib/thread-open-dedupe.test.ts
```

Expected:

```text
PASS src/lib/thread-open-dedupe.test.ts
```

- [ ] **Step 5: Commit the helper**

Run:

```bash
git add src/newbro/ui/src/lib/thread-open-dedupe.ts src/newbro/ui/src/lib/thread-open-dedupe.test.ts
git commit -m "test: add thread open dedupe helper"
```

---

### Task 5: Wire Frontend Dedupe Into `NewbroShell`

**Files:**
- Modify: `src/newbro/ui/src/NewbroShell.tsx`
- Test: `src/newbro/ui/src/lib/thread-open-dedupe.test.ts`

- [ ] **Step 1: Import the helper**

In `src/newbro/ui/src/NewbroShell.tsx`, add this import near the other local `lib` imports:

```ts
import { beginThreadOpen, finishThreadOpen } from "./lib/thread-open-dedupe";
```

- [ ] **Step 2: Add an in-flight ref**

Near the existing thread open refs in `useNewbroShellState`, add:

```ts
  const threadOpenInFlightRef = useRef(new Set<string>());
```

The nearby block should include:

```ts
  const mountedRef = useRef(false);
  const socketRef = useRef<WebSocket | null>(null);
  const threadOpenSequenceRef = useRef(0);
  const threadOpenInFlightRef = useRef(new Set<string>());
```

- [ ] **Step 3: Guard duplicate opens without changing stale response protection**

Replace `openRuntimeBroThread` with this implementation:

```ts
  const openRuntimeBroThread = useEffectEvent(async (targetPersonaId: string, threadId: string) => {
    if (!activeShellSessionId) {
      return;
    }
    const openKey = beginThreadOpen(threadOpenInFlightRef.current, targetPersonaId, threadId);
    if (openKey === null) {
      return;
    }
    const openSequence = ++threadOpenSequenceRef.current;
    setOpeningThreadId(threadId);
    setThreadOpenError(null);
    try {
      const snapshot = await openBroThread(activeShellSessionId, { targetPersonaId, threadId });
      if (!mountedRef.current || threadOpenSequenceRef.current !== openSequence) {
        return;
      }
      startTransition(() => {
        applySnapshot(snapshot);
      });
    } catch (error) {
      if (!mountedRef.current || threadOpenSequenceRef.current !== openSequence) {
        return;
      }
      setThreadOpenError(describeApiFailure(error, "Thread history could not be fetched. Try selecting the thread again."));
    } finally {
      finishThreadOpen(threadOpenInFlightRef.current, openKey);
      if (mountedRef.current) {
        setOpeningThreadId((current) => (current === threadId ? null : current));
      }
    }
  });
```

- [ ] **Step 4: Run focused frontend helper and selection tests**

Run:

```bash
cd src/newbro/ui
bun run test src/lib/thread-open-dedupe.test.ts src/lib/useThreadSelection.test.tsx
```

Expected:

```text
PASS src/lib/thread-open-dedupe.test.ts
PASS src/lib/useThreadSelection.test.tsx
```

- [ ] **Step 5: Commit shell wiring**

Run:

```bash
git add src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/lib/thread-open-dedupe.ts src/newbro/ui/src/lib/thread-open-dedupe.test.ts
git commit -m "fix: dedupe in-flight bro thread opens"
```

---

### Task 6: Add App-Level Regression Coverage

**Files:**
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Add a regression test for loading-to-loaded snapshots**

Add this test near the existing thread history loading and stale-open tests in `src/newbro/ui/src/__tests__/App.test.tsx`:

```tsx
  it("does not re-open the same selected thread when its loading snapshot settles", async () => {
    const snapshot = forgeSnapshot("session-existing");
    const loadingThread = {
      thread_id: "codex-import-dedupe",
      persona_id: "forge",
      persona_name: "Forge",
      executor_id: "codex",
      executor_node_id: "node-forge",
      execution_session_id: null,
      status: "completed",
      title: "Dedupe imported thread",
      preview: "Remote history",
      progress: 100,
      task_ids: [],
      active_task_id: null,
      latest_task_id: null,
      has_resume_handle: true,
      updated_at: "2026-05-26T22:00:00+00:00",
      timeline_status: "loading",
      timeline_error: null,
      diagnostics: { codex_thread_id: "codex-native-dedupe" },
    };
    const loadedSnapshot = {
      ...snapshot,
      bro_threads: [
        {
          ...loadingThread,
          timeline_status: "loaded",
          timeline_error: null,
        },
      ],
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "codex-import-dedupe",
          executor_turn_id: "turn-dedupe",
          assistantText: "Loaded once.",
        }),
      ],
    };
    snapshot.bro_threads = [loadingThread] as any;
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValueOnce(loadedSnapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=codex-import-dedupe");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Loaded once.")).toBeInTheDocument();
    await waitFor(() => {
      expect(clientMock.openBroThread).toHaveBeenCalledTimes(1);
    });
  });
```

- [ ] **Step 2: Run the focused App test**

Run:

```bash
cd src/newbro/ui
bun run test src/__tests__/App.test.tsx -t "does not re-open the same selected thread when its loading snapshot settles"
```

Expected:

```text
PASS src/__tests__/App.test.tsx
```

- [ ] **Step 3: Run nearby App regressions**

Run:

```bash
cd src/newbro/ui
bun run test src/__tests__/App.test.tsx -t "thread"
```

Expected:

```text
PASS src/__tests__/App.test.tsx
```

- [ ] **Step 4: Commit frontend regression test**

Run:

```bash
git add src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "test: cover bro thread open dedupe"
```

---

### Task 7: Run Cross-Boundary Verification

**Files:**
- Read: `src/newbro/runtime/bro_detail_thread_projection.py`
- Read: `src/newbro/ui/src/NewbroShell.tsx`
- Read: `tests/unit/runtime/test_bro_detail_thread_projection.py`
- Read: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Run focused Python projection and API slices**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py tests/unit/runtime/test_session_runtime.py tests/integration/api/test_executor_text.py -q
```

Expected:

```text
passed
```

The exact count can vary as tests are added. There must be no failures.

- [ ] **Step 2: Run focused frontend tests**

Run:

```bash
cd src/newbro/ui
bun run test src/lib/thread-open-dedupe.test.ts src/lib/useThreadSelection.test.tsx src/__tests__/App.test.tsx
```

Expected:

```text
PASS
```

Vitest may print one line per file. There must be no failed tests.

- [ ] **Step 3: Run the full Python suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected:

```text
passed
```

The previous full suite baseline on this branch was `591 passed`; this change should not reduce coverage or introduce failures.

- [ ] **Step 4: Run the full frontend suite**

Run:

```bash
cd src/newbro/ui
bun run test
```

Expected:

```text
PASS
```

- [ ] **Step 5: Inspect the final diff**

Run:

```bash
git status --short
git diff -- src/newbro/runtime/bro_detail_thread_projection.py src/newbro/ui/src/NewbroShell.tsx
git diff -- tests/unit/runtime/test_bro_detail_thread_projection.py src/newbro/ui/src/lib/thread-open-dedupe.ts src/newbro/ui/src/lib/thread-open-dedupe.test.ts src/newbro/ui/src/__tests__/App.test.tsx
```

Expected:

```text
src/newbro/runtime/bro_detail_thread_projection.py
src/newbro/ui/src/NewbroShell.tsx
tests/unit/runtime/test_bro_detail_thread_projection.py
src/newbro/ui/src/lib/thread-open-dedupe.ts
src/newbro/ui/src/lib/thread-open-dedupe.test.ts
src/newbro/ui/src/__tests__/App.test.tsx
```

The runtime diff should show idempotency only. The UI diff should show in-flight request tracking only. Test diffs should cover the backend idempotency and frontend duplicate-open regression. No protocol contract or memory-doc changes are needed for this bugfix.

- [ ] **Step 6: Commit verification-only fixes if needed**

If verification reveals a small issue and the fix is directly part of thread open dedupe, commit it:

```bash
git add src/newbro/runtime/bro_detail_thread_projection.py tests/unit/runtime/test_bro_detail_thread_projection.py src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/lib/thread-open-dedupe.ts src/newbro/ui/src/lib/thread-open-dedupe.test.ts src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "fix: stabilize bro thread open dedupe"
```

If verification passes without additional edits, skip this commit step.

---

## Acceptance Criteria

- Concurrent backend history loads for one public Bro Detail thread call `request_codex_thread` exactly once.
- Opening a loaded imported thread does not call `request_codex_thread`.
- Opening a failed imported thread retries history loading.
- Opening a loaded imported thread still schedules or preserves the selected Codex thread subscription.
- Duplicate frontend open attempts for the same `(targetPersonaId, threadId)` while a request is in flight call the HTTP `openBroThread` path once.
- Stale response protection still works when switching quickly between different threads.
- Focused backend tests, focused frontend tests, full Python tests, and full frontend tests pass.

## Self-Review Notes

- Spec coverage: Backend idempotency is covered by Tasks 1-3. Frontend in-flight dedupe is covered by Tasks 4-6. Verification is covered by Task 7.
- Placeholder scan: This plan contains concrete files, test snippets, implementation snippets, commands, and expected outcomes.
- Type consistency: Backend snippets use existing `Persona`, `AgentResumeHandle`, `BroThread`, `ExecutorNodeExecutor`, and `NodeConnectionState` types. Frontend snippets use `Set<string>` and exported helper functions with consistent names across tests and implementation.
