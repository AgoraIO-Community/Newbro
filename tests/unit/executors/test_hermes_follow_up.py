# tests/unit/executors/test_hermes_follow_up.py
import asyncio
from pathlib import Path

import pytest

from newbro.executors.adapters.hermes.executor import HermesExecutor
from newbro.executors.adapters.hermes.session import HermesExecutorSession
from newbro.executors.core import ExecutorEventType
from newbro.protocol import ExecutionRun, ExecutorTextInstruction


class _SteerFailsClient:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self.submitted: list = []

    async def events_for(self, session_id):
        return self._queue

    async def submit_prompt(self, session_id, text):
        self.submitted.append(("submit", text))

    async def steer(self, session_id, text):
        raise RuntimeError("session not steerable")

    async def interrupt(self, session_id):
        return None


def _session():
    session = HermesExecutorSession(session_id="s", executor_type="hermes", metadata={})
    session.attach(cwd=Path("/tmp"), gateway_session_id="s")
    return session


@pytest.mark.anyio
async def test_unsteerable_follow_up_fails_without_submit_fallback():
    executor = HermesExecutor(command="hermes")
    executor._client = _SteerFailsClient()  # type: ignore[assignment]
    session = _session()
    run = ExecutionRun(run_id="r", execution_session_id="e", task_id="t", executor_type="hermes")
    instruction = ExecutorTextInstruction(
        instruction_id="i", target_persona_id="p", text="and now refactor"
    )
    seen = [e async for e in executor.handle_text_instruction(run, session, instruction)]
    assert seen[-1].event_type == ExecutorEventType.FAILED
    assert executor._client.submitted == []  # type: ignore[attr-defined]  # no prompt.submit fallback


@pytest.mark.anyio
async def test_cancel_run_interrupts_the_session():
    executor = HermesExecutor(command="hermes")
    calls: list[str] = []

    class _C:
        async def interrupt(self, session_id):
            calls.append(session_id)

    executor._client = _C()  # type: ignore[assignment]
    session = _session()
    executor._sessions_by_run["r"] = session
    await executor.cancel_run("r")
    assert calls == ["s"]
