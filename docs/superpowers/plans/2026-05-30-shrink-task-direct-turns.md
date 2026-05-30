# Shrink Task for Direct Turns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop creating broad `Task` records for direct Bro Detail text/PTT sends; let the detached Codex executor create native thread/turn state, while Newbro keeps only thin pending request and projection state.

**Architecture:** This is a vertical slice for direct Bro Detail text/PTT only. Draft Send and Communication Brain-created work keep using `Task` until a later migration. Direct sends create an `OutboundTurnRequest`, dispatch a new executor-node command that starts/resumes a Codex thread and turn directly, and project executor events into `BroThread`/`BroTimelineTurn` without a Newbro `Task`.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, pytest, React/Vite/TypeScript, Vitest.

---

## Scope

In scope:

- Direct Bro Detail text sends.
- Direct Bro Detail push-to-talk sends after backend transcription.
- Selected imported Codex thread resume.
- New Codex thread with explicit workspace.
- Existing active-run follow-up compatibility.
- UI timeline rendering from `BroTimelineTurn`.

Out of scope:

- Draft Send.
- Communication Brain `create_task`.
- Generic scheduler removal.
- `Task` removal from public snapshots.
- Notification system migration.

## Target Contract

Direct text/PTT must no longer call `_start_executor_text_task()` when there is no active run.

Instead:

1. Backend validates persona/node/thread intent.
2. Backend stores `OutboundTurnRequest(status="pending")`.
3. Backend sends a `start_codex_turn` command to the executor node.
4. Executor node starts/resumes the Codex thread and calls `turn/start`.
5. Executor node streams `RunEventMessage`-compatible or new `CodexTurnEventMessage` events containing:
   - `client_request_id`
   - `request_id`
   - public `target_thread_id`
   - native `executor_thread_id`
   - native `executor_turn_id`
   - transcript/audio metadata when applicable
6. Backend projects events into `BroTimelineTurn(owner="executor")`.
7. Backend marks the `OutboundTurnRequest` accepted/completed/failed.

## Files

- Modify: `src/newbro/protocol/session.py`
  - Add `OutboundTurnRequest`.
  - Add `outbound_turn_requests` to `SessionSnapshot` if snapshot model lives here; otherwise update `src/newbro/runtime/models.py`.
- Modify: `src/newbro/runtime/models.py`
  - Include outbound turn request read model in snapshots if not in protocol model.
- Modify: `src/newbro/blackboard/interfaces.py`
  - Add put/get/list methods for outbound turn requests.
- Modify: `src/newbro/blackboard/backends/memory.py`
  - Store outbound turn requests and emit write events.
- Modify: `src/newbro/protocol/executor_node.py`
  - Add `StartCodexTurnCommand`.
  - Add `CodexTurnEventMessage` if reusing `RunEventMessage` would force fake task/run ids.
- Modify: `src/newbro/runtime/executor_node_manager.py`
  - Add `start_codex_turn(...)`.
- Modify: `src/newbro/executors/node/service.py`
  - Handle `start_codex_turn`.
- Modify: `src/newbro/executors/adapters/codex/executor.py`
  - Add method to start/resume thread and stream a turn without `Task`.
- Modify: `src/newbro/runtime/session.py`
  - Change `submit_executor_text_instruction` and `submit_executor_audio_instruction` no-active-run branches to use outbound turn requests.
  - Keep active-run dispatch branch temporarily.
  - Project direct executor events into `BroTimelineTurn` without task.
- Modify: `src/newbro/ui/src/types.ts`
  - Add outbound request type if exposed to UI.
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
  - Keep optimistic turn behavior; reconcile by `client_request_id`.
- Modify: `src/newbro/ui/src/components/newbro/adapters.ts`
  - Ensure direct-turn timeline cards do not require `Task`.
- Test: `tests/integration/api/test_executor_text.py`
- Test: `tests/integration/api/test_executor_audio.py`
- Test: `tests/unit/executors/node/test_service.py`
- Test: `tests/unit/executors/adapters/test_codex_executor.py`
- Test: `tests/unit/runtime/test_session_runtime.py`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`
- Docs: `docs/protocol/execution-session-and-run.md`
- Docs: `docs/protocol/task.md`
- Docs: `docs/memories.md`

---

## Task 1: Add Outbound Turn Request Protocol and Storage

**Files:**
- Modify: `src/newbro/protocol/session.py`
- Modify: `src/newbro/runtime/models.py`
- Modify: `src/newbro/blackboard/interfaces.py`
- Modify: `src/newbro/blackboard/backends/memory.py`
- Test: `tests/unit/protocol/test_protocol_models.py`
- Test: `tests/unit/blackboard/test_memory_backend.py`

- [ ] **Step 1: Write failing protocol test**

Add to `tests/unit/protocol/test_protocol_models.py`:

```python
from newbro.protocol import OutboundTurnRequest


def test_outbound_turn_request_defaults():
    request = OutboundTurnRequest(
        request_id="out-turn-1",
        persona_id="forge",
        executor_id="codex",
        executor_node_id="node-forge",
        target_thread_id="thread-1",
        client_request_id="client-1",
        input_modality="text",
        text="continue",
    )

    assert request.status == "pending"
    assert request.create_new_thread is False
    assert request.executor_thread_id is None
    assert request.executor_turn_id is None
```

- [ ] **Step 2: Run protocol test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/protocol/test_protocol_models.py::test_outbound_turn_request_defaults
```

Expected: import error or missing model failure.

- [ ] **Step 3: Add model**

Add to `src/newbro/protocol/session.py`:

```python
class OutboundTurnRequest(BaseModel):
    request_id: str
    persona_id: str
    executor_id: str = "codex"
    executor_node_id: str
    target_thread_id: str | None = None
    create_new_thread: bool = False
    workspace_id: str | None = None
    client_request_id: str | None = None
    input_modality: Literal["text", "audio"] = "text"
    text: str | None = None
    audio_instruction_id: str | None = None
    plan_mode: bool = False
    status: Literal["pending", "accepted", "running", "completed", "failed"] = "pending"
    error: str | None = None
    executor_thread_id: str | None = None
    executor_turn_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
```

Export it from `src/newbro/protocol/__init__.py`.

- [ ] **Step 4: Add blackboard storage test**

Add to `tests/unit/blackboard/test_memory_backend.py`:

```python
from newbro.protocol import OutboundTurnRequest


@pytest.mark.anyio
async def test_memory_backend_stores_outbound_turn_requests():
    store = MemoryBlackboardStore()
    request = OutboundTurnRequest(
        request_id="out-turn-1",
        persona_id="forge",
        executor_node_id="node-forge",
        target_thread_id="thread-1",
        text="hello",
    )

    await store.put_outbound_turn_request(request)

    assert await store.get_outbound_turn_request("out-turn-1") == request
    assert await store.list_outbound_turn_requests() == [request]
```

- [ ] **Step 5: Run blackboard test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/blackboard/test_memory_backend.py::test_memory_backend_stores_outbound_turn_requests
```

Expected: missing blackboard methods.

- [ ] **Step 6: Implement blackboard methods**

Add methods to `BlackboardStore` protocol:

```python
async def put_outbound_turn_request(self, request: OutboundTurnRequest) -> None:
    """Store or replace an outbound executor turn request."""

async def get_outbound_turn_request(self, request_id: str) -> OutboundTurnRequest | None:
    """Fetch one outbound executor turn request."""

async def list_outbound_turn_requests(self) -> list[OutboundTurnRequest]:
    """List outbound executor turn requests."""
```

In memory backend, add `_outbound_turn_requests: dict[str, OutboundTurnRequest] = {}` and implement the three methods.

- [ ] **Step 7: Verify task**

Run:

```bash
.venv/bin/python -m pytest tests/unit/protocol/test_protocol_models.py::test_outbound_turn_request_defaults tests/unit/blackboard/test_memory_backend.py::test_memory_backend_stores_outbound_turn_requests
```

Expected: both pass.

---

## Task 2: Add Executor-Owned Start Turn Command

**Files:**
- Modify: `src/newbro/protocol/executor_node.py`
- Modify: `src/newbro/runtime/executor_node_manager.py`
- Modify: `src/newbro/executors/node/service.py`
- Modify: `src/newbro/executors/adapters/codex/executor.py`
- Test: `tests/unit/executors/node/test_service.py`
- Test: `tests/unit/executors/adapters/test_codex_executor.py`

- [ ] **Step 1: Write failing node service test**

Add a test that sends `StartCodexTurnCommand` to node service with a fake Codex executor implementing `start_turn_request(...)`, and asserts the node emits turn events with `request_id`, `executor_thread_id`, and `executor_turn_id`.

Use existing websocket/fake executor patterns in `tests/unit/executors/node/test_service.py`.

- [ ] **Step 2: Run node test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/executors/node/test_service.py::test_node_service_starts_codex_turn_request
```

Expected: missing command/model handler.

- [ ] **Step 3: Add protocol models**

Add to `src/newbro/protocol/executor_node.py`:

```python
class StartCodexTurnCommand(BaseModel):
    type: Literal["start_codex_turn"] = "start_codex_turn"
    request_id: str
    executor_type: Literal["codex"] = "codex"
    target_persona_id: str
    target_thread_id: str
    thread_id: str | None = None
    create_new_thread: bool = False
    workspace_id: str | None = None
    instruction: ExecutorTextInstruction
    latest_resume_handle: AgentResumeHandle | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CodexTurnEventMessage(BaseModel):
    type: Literal["codex_turn_event"] = "codex_turn_event"
    request_id: str
    node_id: str
    executor_type: Literal["codex"] = "codex"
    target_persona_id: str
    target_thread_id: str
    event_type: str
    message: str | None = None
    executor_thread_id: str | None = None
    executor_turn_id: str | None = None
    ok: bool = True
    error: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
```

- [ ] **Step 4: Implement node manager dispatch**

Add `RuntimeExecutorNodeManager.start_codex_turn(...)` that sends `StartCodexTurnCommand` to the selected node. This method should not require `task_id`, `run_id`, or `execution_session_id`.

- [ ] **Step 5: Implement node service handler**

In `NodeExecutorService`, route `"start_codex_turn"` to `_start_codex_turn(...)`.

The handler should:

```python
starter = getattr(executor, "start_turn_request", None)
if starter is None:
    send CodexTurnEventMessage(event_type="failed", ok=False, error="...")
    return
async for event in starter(command):
    send CodexTurnEventMessage(...)
```

- [ ] **Step 6: Implement Codex adapter method**

Add `CodexExecutor.start_turn_request(command)`:

- If `command.create_new_thread`, call `thread_start(cwd=workspace_id)`.
- Else if `command.latest_resume_handle`, resume/open that thread.
- Else use `command.thread_id`.
- Call `turn_start(thread_id=..., prompt=instruction.text, collaborationMode=plan/default)`.
- Stream events using existing `_stream_turn_events` logic adapted to a synthetic event context without `Task`.

- [ ] **Step 7: Verify task**

Run:

```bash
.venv/bin/python -m pytest tests/unit/executors/node/test_service.py::test_node_service_starts_codex_turn_request tests/unit/executors/adapters/test_codex_executor.py -k "turn_request or plan_mode"
```

Expected: new test passes; existing plan-mode Codex tests still pass.

---

## Task 3: Change Direct Text No-Active-Run Path to Outbound Turn Request

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/integration/api/test_executor_text.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/integration/api/test_executor_text.py`:

```python
@pytest.mark.anyio
async def test_direct_text_new_thread_does_not_create_task_before_executor_acceptance(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-text-outbound")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_forge(runtime_session, app.state.runtime_container.executor_node_manager, websocket)

        runtime_session._imported_codex_threads["codex-import-1"] = BroThread(
            thread_id="codex-import-1",
            persona_id="forge",
            title="Imported",
            status="completed",
            has_resume_handle=True,
        )
        runtime_session._imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
            executor_id="codex",
            session_handle="native-thread-1",
            opaque={"cwd": "/tmp/work"},
        )

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={
                "target_persona_id": "forge",
                "target_thread_id": "codex-import-1",
                "text": "continue directly",
                "client_request_id": "client-text-1",
            },
        )

    assert response.status_code == 200
    assert await runtime_session.blackboard.list_tasks() == []
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].client_request_id == "client-text-1"
    assert websocket.sent[-1]["type"] == "start_codex_turn"
    assert "task_id" not in websocket.sent[-1]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py::test_direct_text_new_thread_does_not_create_task_before_executor_acceptance
```

Expected: task is currently created.

- [ ] **Step 3: Implement text no-active-run path**

In `RuntimeSession.submit_executor_text_instruction`, replace the `_start_executor_text_task(...)` branch with:

- Create `OutboundTurnRequest`.
- Store it.
- Call `executor_node_manager.start_codex_turn(...)`.
- Publish snapshot.
- Return `ExecutorTextInstruction`.

Keep the existing active-run branch untouched in this task.

- [ ] **Step 4: Verify text path**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py::test_direct_text_new_thread_does_not_create_task_before_executor_acceptance tests/integration/api/test_executor_text.py::test_executor_text_instruction_targets_imported_codex_thread
```

Expected: both pass after updating old assertions that expected direct tasks.

---

## Task 4: Project Executor Turn Events Without Task

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Modify: `src/newbro/api/ws/executors.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write failing runtime test**

Create a runtime test that:

- Stores an `OutboundTurnRequest(client_request_id="client-text-1")`.
- Feeds a `CodexTurnEventMessage(event_type="progress", executor_thread_id="native-thread-1", executor_turn_id="turn-1")`.
- Asserts `conversation_snapshot().bro_timeline_turns` contains one `BroTimelineTurn` with:
  - `owner == "executor"`
  - `client_request_id == "client-text-1"`
  - `task is None`
  - `executor_thread_id == "native-thread-1"`
  - `executor_turn_id == "turn-1"`

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_codex_turn_event_projects_without_task
```

Expected: no handler/projection.

- [ ] **Step 3: Add websocket handler**

In `src/newbro/api/ws/executors.py`, route `codex_turn_event` messages to a new `RuntimeSession.handle_codex_turn_event(...)`.

- [ ] **Step 4: Implement projection**

In `RuntimeSession.handle_codex_turn_event(...)`:

- Find request by `request_id`.
- Update request status.
- Upsert `BroTimelineTurn` by `client_request_id` or `executor_turn_id`.
- Do not create `Task`, `ExecutionRun`, `ExecutionSession`, or `TaskSummary`.
- Publish snapshot.

- [ ] **Step 5: Verify task**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_codex_turn_event_projects_without_task
```

Expected: pass.

---

## Task 5: Change PTT No-Active-Run Path to Outbound Turn Request

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/integration/api/test_executor_audio.py`

- [ ] **Step 1: Write failing integration test**

Add a PTT test mirroring the direct text test:

- POST audio to selected imported thread.
- Fake transcription returns text.
- Assert no `Task` was created.
- Assert one `OutboundTurnRequest(input_modality="audio")`.
- Assert websocket command is `start_codex_turn`.
- Assert command metadata includes `source_audio_instruction_id`.

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py::test_direct_ptt_selected_thread_does_not_create_task_before_executor_acceptance
```

Expected: task is currently created.

- [ ] **Step 3: Implement PTT no-active-run path**

In `RuntimeSession.submit_executor_audio_instruction`, after transcription, create an `OutboundTurnRequest(input_modality="audio")` and call `start_codex_turn` instead of `_start_executor_text_task(...)`.

- [ ] **Step 4: Verify PTT path**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py::test_direct_ptt_selected_thread_does_not_create_task_before_executor_acceptance tests/integration/api/test_executor_audio.py::test_executor_audio_instruction_targets_selected_codex_thread_without_message_route
```

Expected: both pass after updating old assertions that expected direct tasks.

---

## Task 6: Update UI to Treat Direct Sends as Turns, Not Tasks

**Files:**
- Modify: `src/newbro/ui/src/types.ts`
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/components/newbro/adapters.ts`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Write failing UI test**

Add a test where snapshot contains:

- `bro_timeline_turns` for a direct Codex turn.
- No `tasks`.
- A selected Bro/thread.

Assert the turn renders and the send composer remains enabled.

- [ ] **Step 2: Run UI test and verify failure**

Run:

```bash
bun run test src/__tests__/App.test.tsx -- -t "renders direct executor turn without task"
```

Expected: UI currently has some task-derived assumptions.

- [ ] **Step 3: Implement UI changes**

- Add `OutboundTurnRequest` type if exposed.
- Ensure timeline rendering prefers `BroTimelineTurn`.
- Ensure recent task cards only render actual `tasks`; they should not be required for direct turn display.

- [ ] **Step 4: Verify UI**

Run:

```bash
bun run test src/__tests__/App.test.tsx
bun run build
```

Expected: Vitest passes; build passes with existing Vite/Agora warnings only.

---

## Task 7: Docs and Cleanup

**Files:**
- Modify: `docs/protocol/execution-session-and-run.md`
- Modify: `docs/protocol/task.md`
- Modify: `docs/protocol/draft-to-execute.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Update protocol docs**

Document:

- Direct Bro Detail text/PTT creates `OutboundTurnRequest`, not `Task`.
- Executor node owns native thread/turn creation.
- `Task` remains for draft Send and Communication Brain-created scheduled work.

- [ ] **Step 2: Run reference search**

Run:

```bash
rg -n "_start_executor_text_task|source_kind.*bro_detail_text|source_kind.*bro_detail_ptt|direct.*Task|current_task_id" src/newbro docs tests --glob '!src/newbro/ui/node_modules/**'
```

Expected:

- `_start_executor_text_task` is gone or no longer used by direct text/PTT.
- `current_task_id` appears only in removal tests/memory if still present from previous change.
- Docs do not describe direct text/PTT as creating `Task`.

- [ ] **Step 3: Final verification**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py tests/integration/api/test_executor_audio.py tests/unit/runtime/test_session_runtime.py tests/unit/executors/node/test_service.py tests/unit/executors/adapters/test_codex_executor.py
bun run test src/__tests__/App.test.tsx
bun run build
```

Expected: all tests pass; build passes with only existing bundle/eval warnings.

## Self-Review

- The plan does not remove generic `Task`; it shrinks direct text/PTT first.
- The plan avoids fallback behavior: selected/new-thread intent remains explicit.
- The plan keeps Draft Send and scheduler behavior stable.
- The plan creates a testable vertical slice before broader task-model migration.
