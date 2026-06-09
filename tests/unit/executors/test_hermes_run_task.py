# tests/unit/executors/test_hermes_run_task.py
import asyncio
from pathlib import Path

import pytest

from newbro.executors.adapters.hermes.executor import HermesExecutor
from newbro.executors.adapters.hermes.session import HermesExecutorSession
from newbro.executors.core import ExecutorEventType
from newbro.protocol import ExecutionRun, Task


class _FakeClient:
    """Scripts a gateway event sequence (each item is an event `params` dict)."""

    def __init__(self, event_params: list[dict[str, object]]):
        self._queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        for params in event_params:
            self._queue.put_nowait(params)
        self.submitted: list[tuple[str, str]] = []
        self.interrupted: list[str] = []

    async def submit_prompt(self, session_id, text):
        self.submitted.append((session_id, text))

    async def steer(self, session_id, text):
        self.submitted.append((session_id, text))

    async def interrupt(self, session_id):
        self.interrupted.append(session_id)

    async def events_for(self, session_id):
        return self._queue


def _make(event_params):
    executor = HermesExecutor(command="hermes")
    executor._client = _FakeClient(event_params)  # type: ignore[assignment]
    session = HermesExecutorSession(session_id="sess-1", executor_type="hermes", metadata={})
    session.attach(cwd=Path("/tmp"), gateway_session_id="sess-1")
    run = ExecutionRun(run_id="run-1", execution_session_id="es-1", task_id="t-1", executor_type="hermes")
    task = Task(task_id="t-1", root_task_id="t-1", title="Do it", goal="Do the thing")
    return executor, session, run, task


@pytest.mark.anyio
async def test_run_task_streams_progress_then_completed():
    event_params = [
        {"type": "message.delta", "session_id": "sess-1", "payload": {"text": "working"}},
        {"type": "tool.start", "session_id": "sess-1", "payload": {"name": "shell"}},
        {"type": "message.complete", "session_id": "sess-1", "payload": {"text": "done", "status": "complete"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    types = [event.event_type for event in seen]
    assert types[-1] == ExecutorEventType.COMPLETED
    assert ExecutorEventType.PROGRESS in types
    assert seen[-1].message == "done"
    assert executor._client.submitted == [("sess-1", "Do the thing")]  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_message_complete_interrupted_maps_to_cancelled():
    event_params = [
        {"type": "message.complete", "session_id": "sess-1", "payload": {"text": "Operation interrupted", "status": "interrupted"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    assert seen[-1].event_type == ExecutorEventType.CANCELLED


@pytest.mark.anyio
async def test_message_complete_error_maps_to_failed():
    event_params = [
        {"type": "message.complete", "session_id": "sess-1", "payload": {"text": "boom", "status": "error"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    assert seen[-1].event_type == ExecutorEventType.FAILED


@pytest.mark.anyio
async def test_run_task_maps_blocked_approval_request_terminally():
    event_params = [
        {"type": "approval.request", "session_id": "sess-1", "payload": {"command": "rm -rf /", "description": "Run rm -rf?"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    assert seen[-1].event_type == ExecutorEventType.BLOCKED
    assert "rm -rf" in (seen[-1].message or "")
    assert seen[-1].metadata.get("hermes_event") == "approval.request"
