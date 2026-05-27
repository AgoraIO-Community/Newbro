from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from newbro.blackboard import InMemoryBlackboard
from newbro.execution import ExecutionBrain
from newbro.executors.core import ExecutorCapabilities, ExecutorEvent, ExecutorEventType, ExecutorRegistry, ExecutorSession
from newbro.protocol import ExecutionRun, Persona, Task, TaskStatus


class CapturingExecutor:
    def __init__(self) -> None:
        self.seen_latest_instruction: str | None = None
        self.seen_persona_prompt: str | None = None

    def get_capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(executor_type="capture")

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(session_id="capture-session", executor_type="capture")

    async def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: ExecutorSession,
    ) -> AsyncIterator[ExecutorEvent]:
        self.seen_latest_instruction = task.latest_instruction
        prompt = task.metadata.get("executor_persona_prompt")
        self.seen_persona_prompt = prompt if isinstance(prompt, str) else None
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.COMPLETED,
            message="done",
        )


@pytest.mark.anyio
async def test_execution_persona_prompt_does_not_mutate_latest_instruction():
    store = InMemoryBlackboard()
    executor = CapturingExecutor()
    registry = ExecutorRegistry()
    registry.register(executor)
    brain = ExecutionBrain(store, registry, worker_id="worker-1", default_executor_type="capture")
    await store.put_persona(
        Persona(
            persona_id="persona-1",
            name="Atlas",
            base_prompt="Execute direct typed and push-to-talk instructions in the connected workspace.",
        )
    )
    await store.put_task(
        Task(
            task_id="task-1",
            root_task_id="task-1",
            title="Hello, hello",
            goal="Hello, hello",
            latest_instruction="Hello, hello",
            status=TaskStatus.QUEUED,
            preferred_executor="capture",
            metadata={"persona_id": "persona-1"},
        )
    )

    await brain.tick()

    saved = await store.get_task("task-1")
    assert saved is not None
    assert saved.latest_instruction == "Hello, hello"
    assert saved.metadata.get("executor_persona_prompt") is None
    assert executor.seen_latest_instruction == "Hello, hello"
    assert executor.seen_persona_prompt == "Execute direct typed and push-to-talk instructions in the connected workspace."
