import pytest

from newbro.blackboard import InMemoryBlackboard
from newbro.execution import ExecutionBrain
from newbro.executors.adapters.mock import MockExecutor
from newbro.executors.core import ExecutorCapabilities, ExecutorEvent, ExecutorEventType, ExecutorRegistry, ExecutorSession
from newbro.protocol import ExecutionRun, RunStatus, Task, TaskStatus


class FailingExecutor:
    def get_capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(executor_type="failing")

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(session_id="failing-session", executor_type="failing")

    async def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: ExecutorSession,
    ):
        if False:
            yield
        raise RuntimeError("executor exploded")


class InvalidResumeHandleExecutor:
    def get_capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(executor_type="invalid-resume")

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(session_id="invalid-resume-session", executor_type="invalid-resume")

    async def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: ExecutorSession,
    ):
        session.metadata["latest_resume_handle"] = {"executor_id": 123}
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.COMPLETED,
            message="Completed before invalid resume handle.",
        )


@pytest.mark.anyio
async def test_execution_brain_tick_claims_runs_and_completes():
    store = InMemoryBlackboard()
    registry = ExecutorRegistry()
    registry.register(MockExecutor())
    brain = ExecutionBrain(store, registry, worker_id="worker-1", default_executor_type="mock")
    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Complete task",
        goal="Complete task",
        status=TaskStatus.QUEUED,
        preferred_executor="mock",
    )
    await store.put_task(task)

    run_ids = await brain.tick()

    assert len(run_ids) == 1
    saved_task = await store.get_task("task_1")
    assert saved_task is not None
    assert saved_task.status == TaskStatus.COMPLETED
    summary = await store.get_summary("task_1")
    assert summary is not None
    assert summary.latest_user_visible_status == "completed"
    execution_mode = await store.get_execution_mode("task_1")
    assert execution_mode is not None
    assert execution_mode.mode.value == "lightweight"


@pytest.mark.anyio
async def test_execution_brain_marks_unknown_executor_tasks_failed():
    store = InMemoryBlackboard()
    registry = ExecutorRegistry()
    registry.register(MockExecutor())
    brain = ExecutionBrain(store, registry, worker_id="worker-1", default_executor_type="mock")
    task = Task(
        task_id="task_bad",
        root_task_id="task_bad",
        title="Bad executor task",
        goal="Bad executor task",
        status=TaskStatus.QUEUED,
        preferred_executor="User",
    )
    await store.put_task(task)

    run_ids = await brain.tick()

    assert run_ids == []
    saved_task = await store.get_task("task_bad")
    assert saved_task is not None
    assert saved_task.status == TaskStatus.FAILED
    summary = await store.get_summary("task_bad")
    assert summary is not None
    assert summary.latest_user_visible_status == "failed"
    assert "Unknown executor 'User'" in str(summary.operational_summary)


@pytest.mark.anyio
async def test_execution_brain_surfaces_executor_exceptions_as_failed_state():
    store = InMemoryBlackboard()
    registry = ExecutorRegistry()
    registry.register(FailingExecutor())
    brain = ExecutionBrain(store, registry, worker_id="worker-1", default_executor_type="failing")
    task = Task(
        task_id="task_runtime_error",
        root_task_id="task_runtime_error",
        title="Runtime error task",
        goal="Runtime error task",
        status=TaskStatus.QUEUED,
        preferred_executor="failing",
    )
    await store.put_task(task)

    run_ids = await brain.tick()

    assert run_ids == []
    saved_task = await store.get_task("task_runtime_error")
    assert saved_task is not None
    assert saved_task.status == TaskStatus.FAILED
    runs = await store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    assert runs[0].failure_reason == "executor exploded"
    summary = await store.get_summary("task_runtime_error")
    assert summary is not None
    assert summary.latest_user_visible_status == "failed"
    details = await store.list_task_execution_details("task_runtime_error")
    assert len(details) == 1
    assert details[0].payload["metadata"]["reason_code"] == "execution_exception"


@pytest.mark.anyio
async def test_execution_brain_rejects_invalid_executor_resume_handle():
    store = InMemoryBlackboard()
    registry = ExecutorRegistry()
    registry.register(InvalidResumeHandleExecutor())
    brain = ExecutionBrain(store, registry, worker_id="worker-1", default_executor_type="invalid-resume")
    task = Task(
        task_id="task_invalid_resume",
        root_task_id="task_invalid_resume",
        title="Invalid resume task",
        goal="Invalid resume task",
        status=TaskStatus.QUEUED,
        preferred_executor="invalid-resume",
    )
    await store.put_task(task)

    run_ids = await brain.tick()

    assert run_ids == []
    saved_task = await store.get_task("task_invalid_resume")
    assert saved_task is not None
    assert saved_task.status == TaskStatus.FAILED
    runs = await store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    assert runs[0].failure_reason == "Executor returned an invalid resume handle."
    execution_sessions = await store.list_sessions()
    assert execution_sessions[0].latest_resume_handle is None
