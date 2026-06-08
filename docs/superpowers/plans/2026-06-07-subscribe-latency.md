# Reduce Bro-Thread Subscribe Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make opening/switching a bro thread fast and stop opens from timing out, by acking the subscribe before Codex `thread/resume`, dropping the redundant client DELETE on switch, loading the timeline in parallel, and adding timing instrumentation.

**Architecture:** The executor node sends the `CodexThreadSubscribedMessage` ack immediately and runs `create_session` + `thread_resume` in the background streaming task (so the HTTP POST no longer blocks on resume and no longer 409s when resume is slow). The client stops issuing the redundant DELETE on thread switch (the POST replaces the subscription server-side) and loads the timeline concurrently with subscribe. Timing logs attribute the latency.

**Tech Stack:** Python 3.12 (FastAPI runtime + executor node), pytest. React + Vite + TypeScript UI, vitest. Backend tests: `.venv/bin/python -m pytest`. UI from `src/newbro/ui`: `npm run test`, `npm run build`.

**Reference spec:** `docs/superpowers/specs/2026-06-07-subscribe-latency-design.md`

**Sensitive area:** The `codex_thread_event` stream and the multi-message turn contract are locked by `tests/unit/runtime/test_codex_multi_message_turn.py` and `tests/unit/runtime/test_session_runtime.py` (see AGENTS.md). This plan does NOT change the *content/order* of streamed thread events — only when the ack is sent and where resume runs. Keep those suites green.

---

### Task 1: Timing instrumentation for the subscribe round-trip

**Files:**
- Modify: `src/newbro/runtime/executor_node_manager.py` (`subscribe_codex_thread`, ~line 667)
- Modify: `src/newbro/runtime/bro_detail_thread_projection.py` (`subscribe_bro_thread`, ~line 430)
- Test: `tests/unit/runtime/test_executor_node_manager.py`

Add elapsed-time logging around the awaited node round-trip and the projection-level subscribe so we can attribute the latency. (Node-side `create_session` vs `thread_resume` timing is added in Task 2, where that function is restructured.)

- [ ] **Step 1: Write the failing test**

Open `tests/unit/runtime/test_executor_node_manager.py`, find the existing test that exercises `subscribe_codex_thread` successfully (search for `subscribe_codex_thread` and `publish_codex_thread_subscribed`). Add a sibling test that asserts a timing log is emitted, modeled on that existing test's setup (reuse its fake connection / how it resolves the subscribe future):

```python
async def test_subscribe_codex_thread_logs_round_trip_timing(monkeypatch, caplog):
    # ARRANGE: build the manager + fake connection exactly as the existing
    # `subscribe_codex_thread` success test does (copy its setup), then:
    caplog.set_level(logging.INFO, logger="newbro.runtime.executor_node_manager")
    # ACT: drive a successful subscribe_codex_thread the same way the existing test does
    #      (send command, resolve the future via publish_codex_thread_subscribed).
    # ASSERT:
    assert any("codex_thread subscribe round-trip" in r.message for r in caplog.records)
```

Ensure `import logging` is present in the test module.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_executor_node_manager.py -k round_trip_timing -v`
Expected: FAIL (no such log emitted).

- [ ] **Step 3: Implement the timing logs**

In `src/newbro/runtime/executor_node_manager.py`, confirm a module logger exists near the top: `LOGGER = logging.getLogger(__name__)` (and `import logging`, `import time`). Add them if missing.

In `subscribe_codex_thread`, wrap the send + await with a timer. Replace:

```python
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
```

with:

```python
        started = time.perf_counter()
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
            LOGGER.info(
                "codex_thread subscribe round-trip node_id=%s thread_id=%s elapsed_ms=%d",
                node_id,
                thread_id,
                int((time.perf_counter() - started) * 1000),
            )
```

(Leave the existing `except`/`return` blocks unchanged.)

In `src/newbro/runtime/bro_detail_thread_projection.py`, confirm `import logging`, `import time`, and `LOGGER = logging.getLogger(__name__)` exist near the top (add if missing). In `subscribe_bro_thread`, time the whole method body: capture `started = time.perf_counter()` at the top of the method, and immediately before each `return`/at the end of the locked path log:

```python
        LOGGER.info(
            "subscribe_bro_thread persona_id=%s thread_id=%s elapsed_ms=%d",
            target_persona_id,
            thread_id,
            int((time.perf_counter() - started) * 1000),
        )
```

To avoid duplicating the log before multiple `return` statements, wrap the body so the timing logs once on the way out. Concretely, rename the existing method body to a private `_subscribe_bro_thread_impl(...)` with the same signature/returns, and make `subscribe_bro_thread` time-and-delegate:

```python
    async def subscribe_bro_thread(self, *, target_persona_id: str, thread_id: str) -> BroThreadSubscriptionResponse:
        started = time.perf_counter()
        try:
            return await self._subscribe_bro_thread_impl(
                target_persona_id=target_persona_id, thread_id=thread_id
            )
        finally:
            LOGGER.info(
                "subscribe_bro_thread persona_id=%s thread_id=%s elapsed_ms=%d",
                target_persona_id,
                thread_id,
                int((time.perf_counter() - started) * 1000),
            )
```

Rename the current `async def subscribe_bro_thread(self, *, target_persona_id, thread_id)` (line ~430) to `async def _subscribe_bro_thread_impl(self, *, target_persona_id, thread_id)`, leaving its body unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_executor_node_manager.py -k round_trip_timing -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py -v`
Expected: PASS (rename is behavior-preserving).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/runtime/executor_node_manager.py src/newbro/runtime/bro_detail_thread_projection.py tests/unit/runtime/test_executor_node_manager.py
git commit -m "feat(runtime): log subscribe round-trip and projection timing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Node acks subscribe before resume (non-blocking + timeout fix)

**Files:**
- Modify: `src/newbro/executors/node/service.py` (`CodexThreadSubscriptionContext` ~line 81; `_subscribe_codex_thread` ~line 527; `_stop_codex_thread_subscription` ~line 601)
- Test: `tests/unit/executors/node/test_service.py`

Today `_subscribe_codex_thread` awaits `subscribe_thread` (which does `create_session` + `thread_resume`) before sending the ack. Move resume into the background streaming task and ack immediately. This removes the resume wait from the awaited round-trip, so a slow resume no longer hits the 2s manager timeout (no HTTP 409). Add node-side timing for `create_session` vs `thread_resume`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/executors/node/test_service.py`, first update the existing `test_subscribe_codex_thread_streams_events_and_unsubscribes` so it tolerates background resume: after `await service._subscribe_codex_thread(websocket, command)`, the ack is `websocket.sent[0]` immediately, but `executor.subscribed` may be set by the background task a tick later. Change:

```python
    await service._subscribe_codex_thread(websocket, command)
    assert executor.subscribed == [("codex-thread-1", "/tmp/workspace")]
    assert websocket.sent[0]["type"] == "codex_thread_subscribed"
    assert websocket.sent[0]["metadata"] == {"source": "thread/resume"}
```

to:

```python
    await service._subscribe_codex_thread(websocket, command)
    assert websocket.sent[0]["type"] == "codex_thread_subscribed"
    assert websocket.sent[0]["metadata"] == {"source": "thread/resume"}
    for _ in range(20):
        if executor.subscribed:
            break
        await asyncio.sleep(0)
    assert executor.subscribed == [("codex-thread-1", "/tmp/workspace")]
```

Then add three new tests:

```python
@pytest.mark.anyio
async def test_subscribe_codex_thread_acks_before_resume(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)

    resume_gate = asyncio.Event()

    class SlowExecutor(FakeThreadSubscribingExecutor):
        async def subscribe_thread(self, thread_id: str, *, workspace_id: str | None = None):
            await resume_gate.wait()
            return await super().subscribe_thread(thread_id, workspace_id=workspace_id)

    executor = SlowExecutor()
    service._executors["codex"] = executor
    websocket = FakeWebSocket([])
    command = SubscribeCodexThreadCommand(
        request_id="req-sub-2",
        subscription_id="sub-2",
        session_id="session-1",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        workspace_id="/tmp/workspace",
    )

    await service._subscribe_codex_thread(websocket, command)
    # Ack is sent even though resume is still blocked.
    assert executor.subscribed == []
    assert websocket.sent[0]["type"] == "codex_thread_subscribed"

    # Let resume finish, then clean up.
    resume_gate.set()
    for _ in range(20):
        if executor.subscribed:
            break
        await asyncio.sleep(0)
    assert executor.subscribed == [("codex-thread-1", "/tmp/workspace")]
    await service._unsubscribe_codex_thread(
        websocket,
        UnsubscribeCodexThreadCommand(request_id="req-unsub-2", subscription_id="sub-2", thread_id="codex-thread-1"),
    )


@pytest.mark.anyio
async def test_unsubscribe_during_pending_resume_cancels_cleanly(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)

    resume_gate = asyncio.Event()

    class HangingExecutor(FakeThreadSubscribingExecutor):
        async def subscribe_thread(self, thread_id: str, *, workspace_id: str | None = None):
            await resume_gate.wait()  # never set in this test
            return await super().subscribe_thread(thread_id, workspace_id=workspace_id)

    executor = HangingExecutor()
    service._executors["codex"] = executor
    websocket = FakeWebSocket([])
    command = SubscribeCodexThreadCommand(
        request_id="req-sub-3",
        subscription_id="sub-3",
        session_id="session-1",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        workspace_id=None,
    )

    await service._subscribe_codex_thread(websocket, command)
    await service._unsubscribe_codex_thread(
        websocket,
        UnsubscribeCodexThreadCommand(request_id="req-unsub-3", subscription_id="sub-3", thread_id="codex-thread-1"),
    )
    assert service._codex_thread_subscriptions == {}
    assert websocket.sent[-1]["type"] == "codex_thread_unsubscribed"
    # subscribe_thread never completed, so nothing was actually subscribed.
    assert executor.subscribed == []


@pytest.mark.anyio
async def test_subscribe_codex_thread_resume_failure_is_logged(monkeypatch: pytest.MonkeyPatch, caplog):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)

    class FailingResumeExecutor(FakeThreadSubscribingExecutor):
        async def subscribe_thread(self, thread_id: str, *, workspace_id: str | None = None):
            raise RuntimeError("resume boom")

    service._executors["codex"] = FailingResumeExecutor()
    websocket = FakeWebSocket([])
    command = SubscribeCodexThreadCommand(
        request_id="req-sub-4",
        subscription_id="sub-4",
        session_id="session-1",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        workspace_id=None,
    )

    caplog.set_level(logging.WARNING, logger="newbro.executors.node.service")
    await service._subscribe_codex_thread(websocket, command)
    assert websocket.sent[0]["type"] == "codex_thread_subscribed"
    for _ in range(20):
        if any("resume" in r.message.lower() for r in caplog.records):
            break
        await asyncio.sleep(0)
    assert any("resume boom" in r.message or "resume" in r.message.lower() for r in caplog.records)
    # Failed resume must not leave a dangling subscription context after the task ends.
    assert "sub-4" not in service._codex_thread_subscriptions or service._codex_thread_subscriptions["sub-4"].session is None
```

Ensure `import logging` is present in the test module (add if missing).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py -k "codex_thread" -v`
Expected: the new tests FAIL (current code resumes before ack; `test_subscribe_codex_thread_acks_before_resume` fails because the call blocks on `resume_gate`).

- [ ] **Step 3: Make the subscription context's session optional**

In `src/newbro/executors/node/service.py`, change the dataclass (~line 81):

```python
@dataclass(slots=True)
class CodexThreadSubscriptionContext:
    executor: Any
    command: SubscribeCodexThreadCommand
    background_task: asyncio.Task[None]
    session: CodexExecutorSession | None = None
```

- [ ] **Step 4: Restructure `_subscribe_codex_thread` to ack before resume**

Replace the body of `_subscribe_codex_thread` (the part from `try:` through the final ack send, i.e. lines ~547–586) so it: registers the context with a background task that resumes + streams, then sends the ack immediately. Keep the early "executor missing / no subscribe_thread support" branch (~lines 529–546) unchanged. New body after that branch:

```python
        task = asyncio.create_task(self._resume_and_stream_codex_thread(websocket, executor, command))
        self._codex_thread_subscriptions[command.subscription_id] = CodexThreadSubscriptionContext(
            executor=executor,
            command=command,
            background_task=task,
        )
        await self._send_json(
            websocket,
            CodexThreadSubscribedMessage(
                request_id=command.request_id,
                subscription_id=command.subscription_id,
                node_id=self._settings.node_id,
                session_id=command.session_id,
                target_persona_id=command.target_persona_id,
                target_thread_id=command.target_thread_id,
                thread_id=command.thread_id,
                metadata={"source": "thread/resume"},
            ).model_dump(mode="json"),
        )
```

Then add the new background coroutine (place it directly above `_stream_codex_thread_events`). It performs resume (with timing), records the session on the context for cleanup, sets the workspace, and streams; on resume failure it logs and returns (graceful degradation):

```python
    async def _resume_and_stream_codex_thread(
        self,
        websocket: Any,
        executor: Any,
        command: SubscribeCodexThreadCommand,
    ) -> None:
        subscribe_thread = getattr(executor, "subscribe_thread", None)
        if subscribe_thread is None:
            return
        try:
            started = time.perf_counter()
            session = await subscribe_thread(command.thread_id, workspace_id=command.workspace_id)
            LOGGER.info(
                "codex thread resume subscription_id=%s thread_id=%s elapsed_ms=%d",
                command.subscription_id,
                command.thread_id,
                int((time.perf_counter() - started) * 1000),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning(
                "Codex thread resume failed subscription_id=%s thread_id=%s: %s",
                command.subscription_id,
                command.thread_id,
                exc,
            )
            self._codex_thread_subscriptions.pop(command.subscription_id, None)
            return
        if command.workspace_id:
            self._thread_workspaces[command.thread_id] = str(resolve_workspace(command.workspace_id))
        context = self._codex_thread_subscriptions.get(command.subscription_id)
        if context is None:
            # Unsubscribed during resume; close the just-created session.
            with contextlib.suppress(Exception):
                await session.close()
            return
        context.session = session
        await self._stream_codex_thread_events(websocket, session, command)
```

Confirm `import time` and `LOGGER = logging.getLogger(__name__)` exist at the top of `service.py` (the module already uses `LOGGER` — verify; add `import time` if missing). `contextlib` is already imported (used in `_stop_codex_thread_subscription`).

Note on `create_session` timing: `create_session` runs inside the executor's `subscribe_thread`, so the single "codex thread resume" span covers both `create_session` and `thread_resume`. That is sufficient for attribution given `create_session` reuses a warm app-server; finer split is unnecessary (YAGNI).

- [ ] **Step 5: Handle a None session in `_stop_codex_thread_subscription`**

In `_stop_codex_thread_subscription` (~line 601), the unsubscribe path calls `unsubscribe_thread(context.session)` / `context.session.close()`, which now must tolerate `context.session is None` (unsubscribe arrived before resume finished). Replace the body's session-handling so it cancels the task first, then only touches the session if present:

```python
    async def _stop_codex_thread_subscription(self, subscription_id: str) -> str:
        context = self._codex_thread_subscriptions.pop(subscription_id, None)
        if context is None:
            return "notSubscribed"
        context.background_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await context.background_task
        if context.session is None:
            return "notLoaded"
        status = "unsubscribed"
        unsubscribe_thread = getattr(context.executor, "unsubscribe_thread", None)
        try:
            if unsubscribe_thread is not None:
                response = await unsubscribe_thread(context.session)
                response_status = response.get("status") if isinstance(response, dict) else None
                if isinstance(response_status, str) and response_status:
                    status = response_status
            else:
                await context.session.close()
        except Exception as exc:
            status = f"error:{exc}"
            with contextlib.suppress(Exception):
                await context.session.close()
        return status
```

(Cancelling the task before touching the session ensures a mid-resume unsubscribe stops the in-flight resume; the background coroutine's `context is None` guard then closes any session it created after cancellation.)

- [ ] **Step 6: Run the node tests**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py -k "codex_thread" -v`
Expected: PASS (updated + 3 new tests).

- [ ] **Step 7: Run the locked codex-contract suites**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_codex_multi_message_turn.py tests/unit/runtime/test_session_runtime.py -v`
Expected: PASS (event content/order unchanged).

- [ ] **Step 8: Commit**

```bash
git add src/newbro/executors/node/service.py tests/unit/executors/node/test_service.py
git commit -m "feat(node): ack codex thread subscribe before resume (non-blocking)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Client — drop redundant switch-DELETE and load timeline in parallel

**Files:**
- Modify: `src/newbro/ui/src/lib/useThreadSelection.ts` (`selectThread` ~line 89; `selectWorkspace` ~line 110)
- Modify: `src/newbro/ui/src/NewbroShell.tsx` (`openRuntimeBroThread` ~line 666–682)
- Test: `src/newbro/ui/src/lib/useThreadSelection.test.tsx`

The explicit DELETE on switch is redundant (the POST replaces the subscription server-side). Stop closing on switch (keep close on unmount). And load the timeline concurrently with subscribe so history renders without waiting on the subscription.

- [ ] **Step 1: Update the failing test**

In `src/newbro/ui/src/lib/useThreadSelection.test.tsx`, the test "selectThread closes the previously active runtime thread before switching" (~line 82) asserts the old behavior. Replace it with one asserting the new behavior — switching does NOT close, the unmount cleanup still does (that's covered by the existing "does not close the live thread on re-render..." test, which stays). Replace that test body with:

```python
  it("selectThread does not close the previous thread on switch (POST replaces server-side)", () => {
    const closeThread = vi.fn();
    const threads: T[] = [{ threadId: "a" }, { threadId: "b" }];
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ threads, closeThread })));
    act(() => result.current.selectThread("b"));
    expect(closeThread).not.toHaveBeenCalled();
  });
```

(Keep the surrounding TS test syntax — this block uses `it(...)`/`vi.fn()` as in the existing file; do not paste Python.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd src/newbro/ui && npm run test -- useThreadSelection.test.tsx -t "does not close the previous thread"`
Expected: FAIL (current `selectThread` calls `closeThread`).

- [ ] **Step 3: Remove the switch-close from `selectThread` and `selectWorkspace`**

In `src/newbro/ui/src/lib/useThreadSelection.ts`, in `selectThread` remove the close call. Change:

```tsx
  function selectThread(threadId: string) {
    if (broId && broSource === "runtime" && activeThreadId && activeThreadId !== threadId) {
      closeThreadRef.current(broId, activeThreadId);
      activeThreadRef.current = null;
    }
    setPendingNewThread(false);
```

to:

```tsx
  function selectThread(threadId: string) {
    // No close on switch: the new thread's subscribe POST replaces the previous
    // subscription server-side. The old thread's cached timeline can stay.
    setPendingNewThread(false);
```

In `selectWorkspace`, remove its close call. Change:

```tsx
  function selectWorkspace(workspaceId: string) {
    if (broId && broSource === "runtime") {
      closeThreadRef.current(broId, activeThreadId);
      activeThreadRef.current = null;
    }
    setPendingNewThread(true);
```

to:

```tsx
  function selectWorkspace(workspaceId: string) {
    setPendingNewThread(true);
```

Leave the unmount-cleanup effect (the `useEffect` returning `closeThreadRef.current(...)`, ~line 81) and `closeThreadRef` itself unchanged — the DELETE still fires when leaving the detail.

- [ ] **Step 4: Load the timeline concurrently with subscribe**

In `src/newbro/ui/src/NewbroShell.tsx` `openRuntimeBroThread`, change the serial subscribe→timeline into a concurrent load where subscribe failure does not block the visible history. Replace:

```tsx
      setBroThreads((current) => markThreadTimeline(current, threadId, "loading"));
      await subscribeBroThread(activeShellSessionId, { targetPersonaId, threadId });
      const page = await listBroTimelinePage(activeShellSessionId, {
        targetPersonaId,
        threadId,
        cursor: null,
        limit: 15,
      });
```

with:

```tsx
      setBroThreads((current) => markThreadTimeline(current, threadId, "loading"));
      // Subscribe (live updates) runs concurrently with the timeline fetch and must not
      // block the visible history; a subscribe failure only loses live attach.
      const subscribePromise = subscribeBroThread(activeShellSessionId, { targetPersonaId, threadId }).catch(
        (error) => {
          console.warn("bro thread subscribe failed", error);
        },
      );
      const page = await listBroTimelinePage(activeShellSessionId, {
        targetPersonaId,
        threadId,
        cursor: null,
        limit: 15,
      });
      void subscribePromise;
```

- [ ] **Step 5: Run the targeted + full UI suites**

Run: `cd src/newbro/ui && npm run test -- useThreadSelection.test.tsx`
Expected: PASS.
Run: `cd src/newbro/ui && npm run test`
Expected: PASS. If any test in `App.test.tsx` asserted an unsubscribe/DELETE on thread switch, update it to the new behavior (DELETE only on leaving the detail, not on switch); re-run until green (run twice — this suite is order/timing flaky).

- [ ] **Step 6: Build**

Run: `cd src/newbro/ui && npm run build`
Expected: success (vite build + tsc --noEmit).

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/lib/useThreadSelection.ts src/newbro/ui/src/lib/useThreadSelection.test.tsx src/newbro/ui/src/NewbroShell.tsx
git commit -m "fix(ui): drop redundant switch-DELETE and load thread timeline in parallel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Backend tests**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py tests/unit/runtime/test_executor_node_manager.py tests/unit/runtime/test_bro_detail_thread_projection.py tests/unit/runtime/test_codex_multi_message_turn.py tests/unit/runtime/test_session_runtime.py -v`
Expected: PASS.

- [ ] **Step 2: Full backend suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS.

- [ ] **Step 3: UI build + tests**

Run: `cd src/newbro/ui && npm run build && npm run test`
Expected: build succeeds; tests PASS (run the suite twice to rule out flakiness).

- [ ] **Step 4: Manual check (against a real executor node)**

Open a thread on desktop: the message history appears without waiting on the subscription; the request no longer returns 409 "Timed out subscribing" when Codex resume is slow. Switching threads issues a single POST (no DELETE); leaving the detail issues a DELETE. Inspect logs for `subscribe_bro_thread ... elapsed_ms`, `codex_thread subscribe round-trip ... elapsed_ms`, and `codex thread resume ... elapsed_ms` to attribute the latency.

---

## Self-Review Notes

- **Spec coverage:** Task 1 → instrumentation (handler/round-trip; node create_session+thread_resume covered by Task 2's resume span); Task 2 → node ack-before-resume, unsubscribe-during-resume cleanup, resume-failure logging/graceful degradation, and the timeout fix (slow resume no longer 409s because the ack resolves the future fast); Task 3 → drop redundant switch-DELETE + parallel timeline load; Task 4 → full verification incl. locked codex-contract suites and manual timeout/latency check. Approach B/C remain out of scope per spec.
- **Placeholder scan:** none — exact paths, full code, exact commands. (The instrumentation test in Task 1 and any App.test switch-assertion update reference modeling on existing tests rather than inventing fixtures, because those harnesses already exist in-repo.)
- **Type consistency:** `CodexThreadSubscriptionContext` now has `session: CodexExecutorSession | None`; `_resume_and_stream_codex_thread(self, websocket, executor, command)` matches the create_task call; `_subscribe_bro_thread_impl` matches the renamed body and the timing wrapper; `subscribeBroThread`/`listBroTimelinePage` signatures unchanged.
