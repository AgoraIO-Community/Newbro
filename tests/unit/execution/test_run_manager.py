from __future__ import annotations

import pytest

from newbro.blackboard import InMemoryBlackboard
from newbro.execution import RunManager
from newbro.executors.core import ExecutorEvent, ExecutorEventType
from newbro.protocol import ExecutionRun, RunStatus, Task, TaskStatus


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("event_type", "message", "expected_run_status", "expected_task_status"),
    [
        (ExecutorEventType.PROGRESS, "Working through step 1.", RunStatus.RUNNING, TaskStatus.RUNNING),
        (ExecutorEventType.PLAN, "Plan updated.", RunStatus.RUNNING, TaskStatus.RUNNING),
        (
            ExecutorEventType.BLOCKED,
            "Need user confirmation.",
            RunStatus.BLOCKED,
            TaskStatus.WAITING_USER_INPUT,
        ),
        (ExecutorEventType.COMPLETED, "All done.", RunStatus.COMPLETED, TaskStatus.COMPLETED),
        (ExecutorEventType.FAILED, "Something broke.", RunStatus.FAILED, TaskStatus.FAILED),
        (ExecutorEventType.CANCELLED, None, RunStatus.CANCELLED, TaskStatus.CANCELLED),
    ],
)
async def test_run_manager_appends_execution_detail_entries_for_events(
    event_type: ExecutorEventType,
    message: str | None,
    expected_run_status: RunStatus,
    expected_task_status: TaskStatus,
):
    store = InMemoryBlackboard()
    manager = RunManager()
    task = Task(task_id="task-1", root_task_id="task-1", title="Draft email", goal="Draft email")
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="session-1",
        executor_type="mock",
    )

    await manager.apply_event(
        store,
        task,
        run,
        ExecutorEvent(
            run_id="run-1",
            session_id="executor-session-1",
            event_type=event_type,
            message=message,
        ),
    )

    saved_run = await store.get_run("run-1")
    saved_task = await store.get_task("task-1")
    detail_entries = await store.list_task_execution_details("task-1")

    assert saved_run is not None and saved_run.status == expected_run_status
    assert saved_task is not None and saved_task.status == expected_task_status
    assert len(detail_entries) == 1
    assert detail_entries[0].event_type == event_type.value
    assert detail_entries[0].run_id == "run-1"
    assert detail_entries[0].execution_session_id == "session-1"
    assert detail_entries[0].payload["session_id"] == "executor-session-1"
    if message is not None:
        assert detail_entries[0].text == message
    else:
        assert detail_entries[0].text == "Cancelled: Draft email"


@pytest.mark.anyio
async def test_run_manager_skips_duplicate_progress_detail_and_task_refresh():
    store = InMemoryBlackboard()
    manager = RunManager()
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Draft email",
        goal="Draft email",
        status=TaskStatus.RUNNING,
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="session-1",
        executor_type="mock",
        status=RunStatus.RUNNING,
        latest_progress_message="Working through step 1.",
    )
    await store.put_task(task)
    await store.put_run(run)
    writes_before = len(await store.list_recent_writes())

    await manager.apply_event(
        store,
        task,
        run,
        ExecutorEvent(
            run_id="run-1",
            session_id="executor-session-1",
            event_type=ExecutorEventType.PROGRESS,
            message="Working through step 1.",
        ),
    )

    writes_after = await store.list_recent_writes()
    detail_entries = await store.list_task_execution_details("task-1")

    assert detail_entries == []
    assert len(writes_after) == writes_before


@pytest.mark.anyio
async def test_run_manager_stores_plan_event_separately_from_progress():
    store = InMemoryBlackboard()
    manager = RunManager()
    task = Task(task_id="task-1", root_task_id="task-1", title="Draft email", goal="Draft email")
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="session-1",
        executor_type="codex",
        latest_progress_message="Reading files.",
    )

    await manager.apply_event(
        store,
        task,
        run,
        ExecutorEvent(
            run_id="run-1",
            session_id="executor-session-1",
            event_type=ExecutorEventType.PLAN,
            message="Plan updated.",
            metadata={
                "source": "codex",
                "codex_plan": {
                    "steps": [{"step": "Patch files", "status": "inProgress"}],
                },
            },
        ),
    )

    saved_run = await store.get_run("run-1")
    assert saved_run is not None
    assert saved_run.latest_progress_message == "Reading files."
    assert saved_run.metadata["latest_plan_event"] == {
        "source": "codex",
        "codex_plan": {
            "steps": [{"step": "Patch files", "status": "inProgress"}],
        },
    }


@pytest.mark.anyio
async def test_run_manager_ignores_stale_non_cancel_event_after_task_cancelled():
    store = InMemoryBlackboard()
    manager = RunManager()
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Draft email",
        goal="Draft email",
        status=TaskStatus.CANCELLED,
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="session-1",
        executor_type="mock",
        status=RunStatus.CANCELLED,
    )
    await store.put_task(task)
    await store.put_run(run)
    writes_before = len(await store.list_recent_writes())

    await manager.apply_event(
        store,
        task,
        run,
        ExecutorEvent(
            run_id="run-1",
            session_id="executor-session-1",
            event_type=ExecutorEventType.PROGRESS,
            message="late progress",
        ),
    )

    writes_after = await store.list_recent_writes()
    detail_entries = await store.list_task_execution_details("task-1")

    assert detail_entries == []
    assert len(writes_after) == writes_before
