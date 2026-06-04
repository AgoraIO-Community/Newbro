# Direct Executor Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the current text/audio push-to-talk executor path from `SessionRuntime` into a deep Direct Executor Interaction module without changing behavior.

**Architecture:** `SessionRuntime` keeps the public runtime facade used by routes and websockets, but delegates direct text/audio instruction behavior to `newbro.runtime.direct_executor`. The new module owns target thread resolution, active Codex run lookup, direct metadata mutation, outbound-turn creation, audio transcription handoff, and executor-node dispatch/start calls. Codex remains the first adapter; do not introduce a generic multi-executor framework in this pass.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, existing `newbro.protocol` models, existing `ExecutorNodeManager`.

---

## File Structure

- Create: `src/newbro/runtime/direct_executor.py`
  - Owns Direct Executor Interaction behavior for text/audio push-to-talk.
  - Exposes `DirectExecutorInteraction.submit_text_instruction(...)`, `submit_audio_instruction(...)`, and `handle_audio_transcript_event(...)`.
  - Contains the thread target resolver and active-run lookup currently embedded in `SessionRuntime`.
- Modify: `src/newbro/runtime/session.py`
  - Removes direct-executor helper functions and large text/audio implementations.
  - Creates one `DirectExecutorInteraction` in `SessionRuntime`.
  - Keeps compatibility methods with current names so API routes do not change.
- Modify: `CONTEXT.md`
  - Already created with the source-aligned domain term.
- Create: `tests/unit/runtime/test_direct_executor_interaction.py`
  - Adds unit tests at the new module interface.
- Keep: `tests/integration/api/test_executor_text.py`
  - Existing source-of-truth integration coverage must keep passing.
- Keep: `tests/integration/api/test_executor_audio.py`
  - Existing source-of-truth integration coverage must keep passing.

## Interface Target

The new module should make this the test surface:

```python
interaction = DirectExecutorInteraction(
    session_id=session_id,
    blackboard=store,
    executor_node_manager=manager,
    imported_codex_threads=imported_threads,
    imported_codex_thread_resume_handles=resume_handles,
    publish_snapshot=publish_snapshot,
    observability=observability,
)

instruction = await interaction.submit_text_instruction(
    target_persona_id="forge",
    text="continue directly",
    target_thread_id="codex-import-1",
    create_new_thread=False,
    workspace_id=None,
    client_request_id="client-1",
    plan_mode=False,
)
```

`SessionRuntime` should keep the existing facade:

```python
async def submit_executor_text_instruction(self, **kwargs) -> ExecutorTextInstruction:
    return await self.direct_executor.submit_text_instruction(**kwargs)

async def submit_executor_audio_instruction(self, **kwargs) -> ExecutorAudioInstruction:
    return await self.direct_executor.submit_audio_instruction(**kwargs)

async def handle_executor_audio_transcript_event(self, run_id: str, metadata: dict[str, object]) -> None:
    await self.direct_executor.handle_audio_transcript_event(run_id, metadata)
```

## Behavior To Preserve

- Text to an active selected Codex run sends `dispatch_text_instruction`.
- Audio to an active selected Codex run sends `dispatch_audio_instruction`.
- Text to an idle imported/completed/new thread creates no `Task`, writes one `OutboundTurnRequest`, and sends `start_codex_turn`.
- Audio to an idle imported/completed/new thread first sends `transcribe_audio_instruction`, then writes one `OutboundTurnRequest`, then sends `start_codex_turn`.
- Direct text/audio does not append normal chat conversation history.
- Direct text/audio suppresses normal Communication notification candidates on touched active tasks.
- Missing explicit thread intent remains a 409.
- `target_thread_id` plus `create_new_thread=true` remains a 409.
- New Codex thread creation requires a known workspace.
- `create_new_thread=true` ignores any currently active selected thread and starts a fresh outbound turn.

---

### Task 1: Add Direct Executor Interaction Unit Tests

**Files:**
- Create: `tests/unit/runtime/test_direct_executor_interaction.py`
- Read: `tests/integration/api/test_executor_text.py`
- Read: `tests/integration/api/test_executor_audio.py`

- [ ] **Step 1: Write failing unit tests for target resolution and outbound text**

Create `tests/unit/runtime/test_direct_executor_interaction.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from newbro.blackboard.backends import InMemoryBlackboard
from newbro.protocol import AgentResumeHandle, BroThread, ExecutorNodeExecutor, Persona
from newbro.runtime.direct_executor import DirectExecutorInteraction
from newbro.runtime.executor_node_manager import NodeConnectionState


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


async def _publish_snapshot() -> None:
    return None


@dataclass(slots=True)
class Harness:
    store: InMemoryBlackboard
    manager: object
    websocket: FakeWebSocket
    interaction: DirectExecutorInteraction


async def _harness() -> Harness:
    from newbro.runtime.executor_node_manager import ExecutorNodeManager

    store = InMemoryBlackboard()
    manager = ExecutorNodeManager(detached_executor_types=("codex",))
    websocket = FakeWebSocket()
    manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=websocket,
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
    await store.put_persona(
        Persona(
            persona_id="forge",
            name="Forge",
            avatar="bro",
            base_prompt="",
            executor_node_id="node-forge",
            bro_detail_session_id="detail-forge",
            status="idle",
        )
    )
    imported_threads = {
        "codex-import-1": BroThread(
            thread_id="codex-import-1",
            persona_id="forge",
            title="Imported",
            status="completed",
            has_resume_handle=True,
        )
    }
    resume_handles = {
        "codex-import-1": AgentResumeHandle(
            executor_id="codex",
            session_handle="native-thread-1",
            opaque={"cwd": "/tmp/work"},
        )
    }
    interaction = DirectExecutorInteraction(
        session_id="session-1",
        blackboard=store,
        executor_node_manager=manager,
        imported_codex_threads=imported_threads,
        imported_codex_thread_resume_handles=resume_handles,
        publish_snapshot=_publish_snapshot,
        observability=None,
    )
    return Harness(store=store, manager=manager, websocket=websocket, interaction=interaction)


@pytest.mark.anyio
async def test_text_to_imported_thread_creates_outbound_turn_without_task() -> None:
    harness = await _harness()

    instruction = await harness.interaction.submit_text_instruction(
        target_persona_id="forge",
        text="continue directly",
        target_thread_id="codex-import-1",
        create_new_thread=False,
        workspace_id=None,
        client_request_id="client-text-1",
        plan_mode=False,
    )

    assert instruction.target_thread_id == "codex-import-1"
    assert await harness.store.list_tasks() == []
    requests = await harness.store.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].client_request_id == "client-text-1"
    assert requests[0].status == "accepted"
    assert harness.websocket.sent[-1]["type"] == "start_codex_turn"
    assert "task_id" not in harness.websocket.sent[-1]
    assert harness.websocket.sent[-1]["latest_resume_handle"]["session_handle"] == "native-thread-1"


@pytest.mark.anyio
async def test_text_requires_explicit_thread_intent() -> None:
    harness = await _harness()

    with pytest.raises(ValueError, match="requires explicit thread intent"):
        await harness.interaction.submit_text_instruction(
            target_persona_id="forge",
            text="ambiguous",
            target_thread_id=None,
            create_new_thread=False,
            workspace_id=None,
            client_request_id=None,
            plan_mode=False,
        )
```

- [ ] **Step 2: Run the new tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_interaction.py -q
```

Expected: FAIL because `newbro.runtime.direct_executor` does not exist.

- [ ] **Step 3: Commit test scaffold**

```bash
git add tests/unit/runtime/test_direct_executor_interaction.py
git commit -m "test: add direct executor interaction contract"
```

---

### Task 2: Create The Direct Executor Interaction Module

**Files:**
- Create: `src/newbro/runtime/direct_executor.py`
- Modify: `tests/unit/runtime/test_direct_executor_interaction.py`

- [ ] **Step 1: Add module skeleton and shared helpers**

Create `src/newbro/runtime/direct_executor.py` with this initial content:

```python
from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.protocol import (
    AgentResumeHandle,
    BroThread,
    ExecutionRun,
    ExecutionSession,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    OutboundTurnRequest,
    RunStatus,
    Task,
    TaskStatus,
)
from newbro.runtime.executor_node_manager import ExecutorNodeManager


LOGGER = logging.getLogger(__name__)
BRO_THREAD_PREFIX = "bro-thread-"
IMPORTED_CODEX_THREAD_PREFIX = "codex-import-"
AUDIO_ACTIVE_RUN_STATUSES = {RunStatus.ASSIGNED, RunStatus.RUNNING, RunStatus.BLOCKED}


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _new_bro_thread_id() -> str:
    return f"{BRO_THREAD_PREFIX}{uuid4().hex[:12]}"


def _public_thread_id(session: ExecutionSession) -> str:
    if isinstance(session.continuity_key, str) and session.continuity_key.startswith(BRO_THREAD_PREFIX):
        return session.continuity_key
    if isinstance(session.continuity_key, str) and session.continuity_key.startswith(IMPORTED_CODEX_THREAD_PREFIX):
        return session.continuity_key
    return session.execution_session_id


def _session_matches_thread_id(session: ExecutionSession, thread_id: str) -> bool:
    return thread_id in {
        session.execution_session_id,
        session.continuity_key or "",
        _public_thread_id(session),
    }


def _task_metadata_string(task: Task | None, key: str) -> str | None:
    if task is None:
        return None
    value = task.metadata.get(key)
    return value if isinstance(value, str) and value else None


def _task_belongs_to_persona(task: Task | None, persona_id: str) -> bool:
    if task is None:
        return False
    return task.metadata.get("persona_id") == persona_id or task.metadata.get("assigned_bro_id") == persona_id


def _task_thread_public_id(task: Task) -> str | None:
    return _task_metadata_string(task, "target_thread_id") or _task_metadata_string(task, "bro_thread_id")


def _workspace_name(workspace_id: str | None) -> str | None:
    if not isinstance(workspace_id, str):
        return None
    normalized = workspace_id.strip().rstrip("/\\")
    if not normalized:
        return None
    tail = normalized.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return tail or normalized


def _workspace_from_resume_handle(resume_handle: AgentResumeHandle | None) -> str | None:
    if resume_handle is None:
        return None
    cwd = resume_handle.opaque.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return cwd.strip()
    workspace_id = resume_handle.opaque.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return workspace_id.strip()
    return None


def _task_workspace_id(task: Task | None) -> str | None:
    if task is None:
        return None
    workspace_id = task.metadata.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return workspace_id.strip()
    if isinstance(task.session_affinity, str) and task.session_affinity.strip():
        return task.session_affinity.strip()
    return None


def mark_direct_executor_input(metadata: dict[str, object], source: str) -> dict[str, object]:
    next_metadata = dict(metadata)
    sources = next_metadata.get("direct_executor_input_sources")
    if isinstance(sources, list):
        direct_sources = [item for item in sources if isinstance(item, str)]
    else:
        direct_sources = []
    if source not in direct_sources:
        direct_sources.append(source)
    next_metadata["direct_executor_input_sources"] = direct_sources
    next_metadata["updated_at"] = datetime.now(tz=UTC).isoformat()
    next_metadata["suppress_communication_notifications"] = True
    return next_metadata


@dataclass(slots=True)
class ThreadTarget:
    public_thread_id: str
    continuity_key: str
    execution_session: ExecutionSession | None
    resume_handle: AgentResumeHandle | None


@dataclass(slots=True)
class DirectExecutorInteraction:
    session_id: str
    blackboard: BlackboardStore
    executor_node_manager: ExecutorNodeManager
    imported_codex_threads: dict[str, BroThread]
    imported_codex_thread_resume_handles: dict[str, AgentResumeHandle]
    publish_snapshot: Callable[[], Awaitable[None]]
    observability: object | None = None

    async def submit_text_instruction(
        self,
        *,
        target_persona_id: str,
        text: str,
        target_thread_id: str | None = None,
        create_new_thread: bool = False,
        workspace_id: str | None = None,
        client_request_id: str | None = None,
        plan_mode: bool = False,
    ) -> ExecutorTextInstruction:
        raise NotImplementedError

    async def submit_audio_instruction(
        self,
        *,
        target_persona_id: str,
        target_thread_id: str | None = None,
        create_new_thread: bool = False,
        workspace_id: str | None = None,
        client_request_id: str | None = None,
        pcm16: bytes,
        mime_type: str,
        duration_ms: int,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> ExecutorAudioInstruction:
        raise NotImplementedError

    async def handle_audio_transcript_event(self, run_id: str, metadata: dict[str, object]) -> None:
        raise NotImplementedError
```

- [ ] **Step 2: Run tests to verify import works and method failure is expected**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_interaction.py -q
```

Expected: FAIL with `NotImplementedError` from `submit_text_instruction`.

---

### Task 3: Move Text Direct Executor Behavior

**Files:**
- Modify: `src/newbro/runtime/direct_executor.py`
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/unit/runtime/test_direct_executor_interaction.py`
- Test: `tests/integration/api/test_executor_text.py`

- [ ] **Step 1: Implement thread target and active run helpers in `DirectExecutorInteraction`**

Add these methods inside `DirectExecutorInteraction`:

```python
    async def _resolve_thread_target(
        self,
        *,
        persona,
        target_thread_id: str | None,
        create_new_thread: bool,
        workspace_id: str | None = None,
    ) -> ThreadTarget:
        if target_thread_id and create_new_thread:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and create a new thread.")
        if target_thread_id and workspace_id:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and choose a new workspace.")
        if create_new_thread:
            await self._validate_new_codex_thread_workspace(persona=persona, workspace_id=workspace_id)
            thread_id = _new_bro_thread_id()
            return ThreadTarget(thread_id, thread_id, None, None)
        if target_thread_id:
            session = await self._find_codex_thread_session_for_persona(persona.persona_id, target_thread_id)
            if session is not None:
                return ThreadTarget(_public_thread_id(session), session.continuity_key or session.execution_session_id, session, None)
            imported = self.imported_codex_threads.get(target_thread_id)
            imported_resume_handle = self.imported_codex_thread_resume_handles.get(target_thread_id)
            if imported is not None and imported.persona_id == persona.persona_id and imported_resume_handle is not None:
                return ThreadTarget(imported.thread_id, imported.thread_id, None, imported_resume_handle)
            pending_task = await self._find_direct_task_thread_for_persona(persona.persona_id, target_thread_id)
            if pending_task is not None:
                continuity_key = _task_metadata_string(pending_task, "bro_thread_id") or target_thread_id
                return ThreadTarget(target_thread_id, continuity_key, None, None)
            raise ValueError("Selected Codex thread is not available for this Bro.")
        raise ValueError("Direct Bro Detail instruction requires explicit thread intent.")

    async def _active_codex_execution_for_persona(
        self,
        persona_id: str,
        *,
        target_thread_id: str | None = None,
    ) -> tuple[ExecutionSession | None, ExecutionRun | None]:
        persona = await self.blackboard.get_persona(persona_id)
        if persona is None or target_thread_id is None:
            return None, None
        for execution_session in await self.blackboard.list_sessions():
            if execution_session.base_executor_id != "codex" or not execution_session.active_run_id:
                continue
            if not _session_matches_thread_id(execution_session, target_thread_id):
                continue
            run = await self.blackboard.get_run(execution_session.active_run_id or "")
            if run is None:
                continue
            if run.executor_type != "codex" or run.status not in AUDIO_ACTIVE_RUN_STATUSES:
                continue
            return execution_session, run
        return None, None
```

Also move `_validate_new_codex_thread_workspace`, `_known_codex_workspaces_for_persona`, `_find_codex_thread_session_for_persona`, `_find_direct_task_thread_for_persona`, and `_session_belongs_to_persona` from `SessionRuntime` into `DirectExecutorInteraction`, changing `self.blackboard` references accordingly.

- [ ] **Step 2: Implement `submit_text_instruction` by moving existing behavior**

Move the body of `SessionRuntime.submit_executor_text_instruction` into `DirectExecutorInteraction.submit_text_instruction`. Use these substitutions:

```python
thread_target = await self._resolve_thread_target(
    persona=persona,
    target_thread_id=target_thread_id,
    create_new_thread=create_new_thread,
    workspace_id=resolved_workspace_id,
)
thread_target_id = thread_target.public_thread_id
thread_continuity_key = thread_target.continuity_key
thread_session = thread_target.execution_session
thread_resume_handle = thread_target.resume_handle
```

Replace `await self.publish_snapshot()` with:

```python
await self.publish_snapshot()
```

Keep the same metadata keys:

```python
"source": "bro_detail_text",
"instruction_id": instruction.instruction_id,
"thread_continuity_key": thread_continuity_key,
"thread_mode": "new_thread" if create_new_thread else "resume",
"resume": not create_new_thread,
"plan_mode": plan_mode,
```

When an active run exists, keep:

```python
task.metadata = mark_direct_executor_input(task.metadata, "bro_detail_text")
task.metadata["client_request_id"] = client_request_id
task.metadata["plan_mode"] = plan_mode
```

- [ ] **Step 3: Wire `SessionRuntime` to delegate text behavior**

In `src/newbro/runtime/session.py`, import:

```python
from .direct_executor import DirectExecutorInteraction, mark_direct_executor_input
```

Add a field:

```python
direct_executor: DirectExecutorInteraction | None = field(default=None, init=False, repr=False)
```

Add this helper:

```python
    def _direct_executor(self) -> DirectExecutorInteraction:
        if self.direct_executor is None:
            self.direct_executor = DirectExecutorInteraction(
                session_id=self.session_id,
                blackboard=self.blackboard,
                executor_node_manager=self.executor_node_manager,
                imported_codex_threads=self._imported_codex_threads,
                imported_codex_thread_resume_handles=self._imported_codex_thread_resume_handles,
                publish_snapshot=lambda: self.publish_snapshot(sync_imported_codex_threads=False),
                observability=self.observability,
            )
        return self.direct_executor
```

Replace `submit_executor_text_instruction` with:

```python
    async def submit_executor_text_instruction(self, **kwargs) -> ExecutorTextInstruction:
        return await self._direct_executor().submit_text_instruction(**kwargs)
```

Keep `_active_codex_execution_for_persona` as a delegating compatibility method for existing tests:

```python
    async def _active_codex_execution_for_persona(
        self,
        persona_id: str,
        *,
        target_thread_id: str | None = None,
    ) -> tuple[ExecutionSession | None, ExecutionRun | None]:
        return await self._direct_executor()._active_codex_execution_for_persona(
            persona_id,
            target_thread_id=target_thread_id,
        )
```

- [ ] **Step 4: Run text tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_interaction.py tests/integration/api/test_executor_text.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit text extraction**

```bash
git add src/newbro/runtime/direct_executor.py src/newbro/runtime/session.py tests/unit/runtime/test_direct_executor_interaction.py
git commit -m "refactor: extract direct executor text interaction"
```

---

### Task 4: Move Audio Direct Executor Behavior

**Files:**
- Modify: `src/newbro/runtime/direct_executor.py`
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/unit/runtime/test_direct_executor_interaction.py`
- Test: `tests/integration/api/test_executor_audio.py`

- [ ] **Step 1: Add unit coverage for idle audio outbound turn**

Append this test to `tests/unit/runtime/test_direct_executor_interaction.py`:

```python
from newbro.protocol import AudioInstructionTranscribedMessage


@pytest.mark.anyio
async def test_audio_to_imported_thread_transcribes_then_starts_outbound_turn() -> None:
    harness = await _harness()

    post_task = asyncio.create_task(
        harness.interaction.submit_audio_instruction(
            target_persona_id="forge",
            target_thread_id="codex-import-1",
            create_new_thread=False,
            workspace_id=None,
            client_request_id="client-audio-1",
            pcm16=b"\x00\x00" * 24,
            mime_type="audio/pcm",
            duration_ms=1,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=24,
        )
    )
    for _ in range(100):
        if harness.websocket.sent:
            break
        await asyncio.sleep(0.01)
    assert harness.websocket.sent[0]["type"] == "transcribe_audio_instruction"
    harness.manager.publish_audio_instruction_transcribed(
        AudioInstructionTranscribedMessage(
            request_id=harness.websocket.sent[0]["request_id"],
            node_id="node-forge",
            executor_type="codex",
            transcript_text="continue from recorded audio",
            language="en",
            duration_seconds=0.1,
        )
    )

    audio = await post_task

    assert audio.metadata["transcript_text"] == "continue from recorded audio"
    assert await harness.store.list_tasks() == []
    requests = await harness.store.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].input_modality == "audio"
    assert requests[0].text == "continue from recorded audio"
    assert harness.websocket.sent[1]["type"] == "start_codex_turn"
    assert "task_id" not in harness.websocket.sent[1]
```

- [ ] **Step 2: Run the audio unit test to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_interaction.py::test_audio_to_imported_thread_transcribes_then_starts_outbound_turn -q
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `submit_audio_instruction` by moving existing behavior**

Move the body of `SessionRuntime.submit_executor_audio_instruction` into `DirectExecutorInteraction.submit_audio_instruction`. Preserve:

```python
audio = ExecutorAudioInstruction(
    audio_instruction_id=audio_instruction_id,
    target_persona_id=persona.persona_id,
    target_thread_id=thread_target_id,
    pcm16_b64=base64.b64encode(pcm16).decode("ascii"),
    mime_type=mime_type,
    duration_ms=duration_ms,
    sample_rate=sample_rate,
    num_channels=num_channels,
    samples_per_channel=samples_per_channel,
    size_bytes=len(pcm16),
    metadata={
        "source": "bro_detail_ptt",
        "target_thread_id": thread_target_id,
        **({"client_request_id": client_request_id} if client_request_id else {}),
    },
)
```

Preserve idle behavior:

```python
transcription = await self.executor_node_manager.transcribe_audio_instruction(
    executor_type="codex",
    node_id=persona.executor_node_id,
    audio=audio,
)
```

Preserve active-run behavior:

```python
task.metadata = mark_direct_executor_input(task.metadata, "bro_detail_ptt")
task.metadata["bro_thread_id"] = thread_continuity_key
task.metadata["target_thread_id"] = thread_target_id
task.metadata["source_audio_instruction_id"] = audio.audio_instruction_id
```

- [ ] **Step 4: Move direct text task creation helper for transcript follow-up**

Move `_start_executor_text_task` from `SessionRuntime` into `DirectExecutorInteraction` as `_start_text_task_from_direct_input`.

Add these imports to `src/newbro/runtime/direct_executor.py`:

```python
from newbro.protocol import (
    ExecutionMode,
    MutationType,
    TaskExecutionMode,
    TaskMode,
    TaskMutation,
)
```

Keep the same task metadata contract:

```python
metadata = {
    "immutable": True,
    "source_kind": source_kind,
    "assigned_bro_id": persona.persona_id,
    "persona_id": persona.persona_id,
    "persona_name": persona.name,
    "persona_avatar": persona.avatar,
    "bro_detail_session_id": persona.bro_detail_session_id,
    "bro_thread_id": thread_continuity_key,
    "target_thread_id": thread_id,
    "executor_node_id": persona.executor_node_id,
    "instruction_id": instruction.instruction_id,
    "codex_thread_mode": "resume" if selected_execution_session is not None or selected_resume_handle is not None else "start",
    "mode": TaskMode.PROPOSAL_ONLY.value
    if instruction.metadata.get("plan_mode") is True
    else TaskMode.MODIFY_ALLOWED.value,
    "created_at": created_at,
    "updated_at": created_at,
    "suppress_communication_notifications": True,
}
```

Keep the same blackboard writes:

```python
await self.blackboard.put_persona(persona.model_copy(update={"status": "busy"}))
await self.blackboard.put_task(task)
await self.blackboard.put_execution_mode(
    TaskExecutionMode(task_id=task_id, mode=ExecutionMode.UNDECIDED)
)
await self.blackboard.append_mutation(
    TaskMutation(
        mutation_id=f"mut-{uuid4().hex[:8]}",
        task_id=task_id,
        mutation_type=MutationType.CREATE,
        patch={
            "title": task.title,
            "goal": task.goal,
            "preferred_executor": "codex",
            "persona_id": persona.persona_id,
            "persona_name": persona.name,
            "source_kind": source_kind,
            "instruction_id": instruction.instruction_id,
        },
        created_by=created_by,
    )
)
```

- [ ] **Step 5: Implement `handle_audio_transcript_event` by moving existing behavior**

Move `SessionRuntime.handle_executor_audio_transcript_event` into `DirectExecutorInteraction.handle_audio_transcript_event`.

Important: keep idempotency by preserving:

```python
created_tasks = task.metadata.get("audio_transcript_task_ids")
if not isinstance(created_tasks, dict):
    created_tasks = {}
if audio_id in created_tasks:
    return
task.metadata["audio_transcript_task_ids"] = {**created_tasks, audio_id: "pending"}
await self.blackboard.put_task(task)
```

Replace the old helper call with the moved helper:

```python
transcript_task = await self._start_text_task_from_direct_input(
    persona=persona,
    instruction=instruction,
    thread_id=thread_target.public_thread_id,
    thread_continuity_key=thread_target.continuity_key,
    selected_execution_session=thread_target.execution_session,
    selected_resume_handle=thread_target.resume_handle,
    source_kind="bro_detail_ptt",
    created_by="bro_detail_ptt",
    extra_metadata={
        "source_audio_instruction_id": audio_id,
        "direct_executor_input_sources": ["bro_detail_ptt"],
    },
)
```

- [ ] **Step 6: Wire `SessionRuntime` to delegate audio behavior**

Replace `submit_executor_audio_instruction` with:

```python
    async def submit_executor_audio_instruction(self, **kwargs) -> ExecutorAudioInstruction:
        return await self._direct_executor().submit_audio_instruction(**kwargs)
```

If `handle_audio_transcript_event` moved, replace `handle_executor_audio_transcript_event` with:

```python
    async def handle_executor_audio_transcript_event(self, run_id: str, metadata: dict[str, object]) -> None:
        await self._direct_executor().handle_audio_transcript_event(run_id, metadata)
```

- [ ] **Step 7: Run audio tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_interaction.py tests/integration/api/test_executor_audio.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit audio extraction**

```bash
git add src/newbro/runtime/direct_executor.py src/newbro/runtime/session.py tests/unit/runtime/test_direct_executor_interaction.py
git commit -m "refactor: extract direct executor audio interaction"
```

---

### Task 5: Remove Duplicated SessionRuntime Helpers

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Modify: `src/newbro/runtime/direct_executor.py`
- Test: `tests/integration/api/test_executor_text.py`
- Test: `tests/integration/api/test_executor_audio.py`

- [ ] **Step 1: Remove helpers from `SessionRuntime` that are only used by Direct Executor Interaction**

Delete from `src/newbro/runtime/session.py` if no remaining local callers exist:

```python
_mark_direct_executor_input
_elapsed_ms
_new_bro_thread_id
_workspace_name
_workspace_from_resume_handle
_task_workspace_id
_active_codex_execution_for_persona implementation body
_resolve_bro_thread_target implementation body
_validate_new_codex_thread_workspace implementation body
_known_codex_workspaces_for_persona implementation body
_find_codex_thread_session_for_persona implementation body
_find_direct_task_thread_for_persona implementation body
_session_belongs_to_persona implementation body
```

Keep helpers in `SessionRuntime` when thread projection still uses them. Do not force a full Bro Detail projection extraction into this plan.

- [ ] **Step 2: Keep projection helper imports explicit**

If `SessionRuntime` still needs helpers that now live in `direct_executor.py`, import only named helpers:

```python
from .direct_executor import (
    DirectExecutorInteraction,
    mark_direct_executor_input,
)
```

Do not import `*`.

- [ ] **Step 3: Run import and type smoke tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_interaction.py tests/integration/api/test_executor_text.py tests/integration/api/test_executor_audio.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit cleanup**

```bash
git add src/newbro/runtime/direct_executor.py src/newbro/runtime/session.py
git commit -m "refactor: narrow session runtime direct executor surface"
```

---

### Task 6: Full Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_interaction.py tests/integration/api/test_executor_text.py tests/integration/api/test_executor_audio.py tests/integration/api/test_executor_node_control.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full Python test suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: PASS.

- [ ] **Step 3: Check source code for accidental behavior drift**

Run:

```bash
rg -n "submit_executor_text_instruction|submit_executor_audio_instruction|handle_executor_audio_transcript_event|DirectExecutorInteraction|OutboundTurnRequest|start_codex_turn|dispatch_text_instruction|dispatch_audio_instruction" src/newbro tests
```

Expected:
- API routes still call `SessionRuntime` compatibility methods.
- `SessionRuntime` compatibility methods delegate to `DirectExecutorInteraction`.
- `DirectExecutorInteraction` owns `OutboundTurnRequest`, `start_codex_turn`, `dispatch_text_instruction`, and `dispatch_audio_instruction` behavior.

- [ ] **Step 4: Review diff**

Run:

```bash
git diff --stat HEAD~3..HEAD
git diff HEAD~3..HEAD -- src/newbro/runtime/session.py src/newbro/runtime/direct_executor.py tests/unit/runtime/test_direct_executor_interaction.py
```

Expected:
- `runtime/session.py` loses direct text/audio implementation mass.
- `runtime/direct_executor.py` contains the moved behavior.
- Integration test expectations are unchanged.

---

## Self-Review

- **Spec coverage:** The plan covers text PTT, audio PTT, active-run follow-up, idle outbound turns, thread resolution, workspace validation, task-notification suppression, and compatibility with existing routes.
- **Completion scan:** No task contains unresolved markers or vague error-handling instructions. Audio transcript handling is included in the extraction by moving the supporting direct text task creation helper.
- **Type consistency:** Public facade names remain `submit_executor_text_instruction`, `submit_executor_audio_instruction`, and `handle_executor_audio_transcript_event`. New module names are `DirectExecutorInteraction`, `submit_text_instruction`, `submit_audio_instruction`, and `handle_audio_transcript_event`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-03-direct-executor-interaction.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
