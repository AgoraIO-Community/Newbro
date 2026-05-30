from __future__ import annotations

import pytest

from newbro.blackboard.backends import InMemoryBlackboard
from newbro.protocol import (
    AttentionItem,
    AttentionItemKind,
    AttentionItemStatus,
    AttentionPriority,
    BindingStatus,
    ExecutionMode,
    ExecutionRun,
    ExecutionSession,
    InteractionRequest,
    InteractionRequestKind,
    InteractionRequestStatus,
    NotificationCandidate,
    NotificationCandidateType,
    NotificationDeliveryStatus,
    NotificationPriority,
    OutboundTurnRequest,
    RunStatus,
    SessionBinding,
    Task,
    TaskCommand,
    TaskCommandType,
    TaskExecutionDetailEntry,
    TaskExecutionMode,
    TaskMutation,
    TaskStatus,
    TaskSummary,
)


@pytest.mark.anyio
async def test_memory_blackboard_round_trip_for_core_objects():
    store = InMemoryBlackboard()

    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Draft email",
        goal="Draft a reply",
    )
    session = ExecutionSession(
        execution_session_id="sess_1",
        task_id="task_1",
        base_executor_id="codex",
    )
    run = ExecutionRun(
        run_id="run_1",
        task_id="task_1",
        execution_session_id="sess_1",
        executor_type="codex",
    )
    binding = SessionBinding(
        task_id="task_1",
        execution_session_id="sess_1",
        session_id="agent_session_1",
        binding_status=BindingStatus.ACTIVE,
    )
    summary = TaskSummary(
        task_id="task_1",
        conversational_summary="I am working on it.",
    )
    execution_mode = TaskExecutionMode(
        task_id="task_1",
        mode=ExecutionMode.UNDECIDED,
    )
    candidate = NotificationCandidate(
        candidate_id="notif_1",
        task_id="task_1",
        candidate_type=NotificationCandidateType.COMPLETED,
        priority=NotificationPriority.P2,
        summary_short="Task completed.",
        created_at="2026-04-06T00:00:00+00:00",
        delivery_status=NotificationDeliveryStatus.PENDING,
        merge_key="completed_digest",
    )
    interaction_request = InteractionRequest(
        request_id="ireq_1",
        task_id="task_1",
        kind=InteractionRequestKind.QUESTION,
        status=InteractionRequestStatus.PENDING,
        prompt="Need confirmation?",
        available_actions=["answer"],
        created_at="2026-04-06T00:00:00+00:00",
    )
    attention_item = AttentionItem(
        attention_id="attention_1",
        source="interaction_request",
        kind=AttentionItemKind.QUESTION_REQUEST,
        priority=AttentionPriority.P0,
        status=AttentionItemStatus.ACTIVE,
        title="Need your input",
        body="Need confirmation?",
        task_id="task_1",
        request_id="ireq_1",
        created_at="2026-04-06T00:00:00+00:00",
    )

    await store.put_task(task)
    await store.put_session(session)
    await store.put_run(run)
    await store.put_binding(binding)
    await store.put_summary(summary)
    await store.put_execution_mode(execution_mode)
    await store.put_notification_candidate(candidate)
    await store.put_interaction_request(interaction_request)
    await store.put_attention_item(attention_item)

    assert await store.get_task("task_1") == task
    assert await store.get_session("sess_1") == session
    assert await store.get_run("run_1") == run
    assert await store.get_binding("task_1") == binding
    assert await store.get_summary("task_1") == summary
    assert await store.get_execution_mode("task_1") == execution_mode
    assert await store.get_notification_candidate("notif_1") == candidate
    assert await store.get_interaction_request("ireq_1") == interaction_request
    assert await store.get_attention_item("attention_1") == attention_item


@pytest.mark.anyio
async def test_memory_backend_stores_outbound_turn_requests():
    store = InMemoryBlackboard()
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


@pytest.mark.anyio
async def test_memory_blackboard_appends_mutations_and_bumps_task_revision():
    store = InMemoryBlackboard()
    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Investigate issue",
        goal="Investigate the issue",
    )
    await store.put_task(task)

    mutation = TaskMutation(
        mutation_id="mut_1",
        task_id="task_1",
        mutation_type="add_constraint",
        patch={"tone": "casual"},
        created_by="communication_brain",
    )

    await store.append_mutation(mutation)

    saved_task = await store.get_task("task_1")
    assert saved_task is not None
    assert saved_task.task_revision == 1
    assert await store.list_mutations("task_1") == [mutation]
    assert await store.list_all_mutations() == [mutation]


@pytest.mark.anyio
async def test_memory_blackboard_appends_commands_in_order():
    store = InMemoryBlackboard()
    command_one = TaskCommand(
        command_id="cmd_1",
        task_id="task_1",
        command_type=TaskCommandType.PAUSE_TASK,
        created_by="communication_brain",
    )
    command_two = TaskCommand(
        command_id="cmd_2",
        task_id="task_1",
        command_type=TaskCommandType.CANCEL_TASK,
        created_by="communication_brain",
    )

    await store.append_command(command_one)
    await store.append_command(command_two)

    assert await store.list_commands("task_1") == [command_one, command_two]
    assert await store.list_all_commands() == [command_one, command_two]


@pytest.mark.anyio
async def test_memory_blackboard_appends_execution_details_and_lists_recent_task_windows():
    store = InMemoryBlackboard()
    entries = [
        TaskExecutionDetailEntry(
            detail_id="detail-1",
            task_id="task-1",
            run_id="run-1",
            execution_session_id="session-1",
            event_type="progress",
            text="step 1",
            created_at="2026-04-21T00:00:01+00:00",
        ),
        TaskExecutionDetailEntry(
            detail_id="detail-2",
            task_id="task-2",
            run_id="run-2",
            execution_session_id="session-2",
            event_type="progress",
            text="step 2",
            created_at="2026-04-21T00:00:02+00:00",
        ),
        TaskExecutionDetailEntry(
            detail_id="detail-3",
            task_id="task-1",
            run_id="run-1",
            execution_session_id="session-1",
            event_type="blocked",
            text="waiting",
            created_at="2026-04-21T00:00:03+00:00",
        ),
    ]

    for entry in entries:
        await store.append_task_execution_detail(entry)

    assert await store.list_task_execution_details("task-1") == [entries[0], entries[2]]
    assert await store.list_task_execution_details("task-1", limit=1) == [entries[2]]
    assert await store.list_task_execution_details("task-1", limit=0) == []
    assert await store.list_task_execution_details("missing") == []

    recent = await store.list_recent_task_execution_details(task_limit=2, entry_limit=1)

    assert list(recent.keys()) == ["task-1", "task-2"]
    assert recent["task-1"] == [entries[2]]
    assert recent["task-2"] == [entries[1]]


@pytest.mark.anyio
async def test_memory_blackboard_notifies_subscribers_on_writes():
    store = InMemoryBlackboard()
    queue = store.subscribe()
    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Check prices",
        goal="Check prices",
        status=TaskStatus.QUEUED,
    )

    await store.put_task(task)
    event = await queue.get()

    assert event.kind.value == "task"
    assert event.task_id == "task_1"
    recent_writes = await store.list_recent_writes()
    assert recent_writes[-1].task_id == "task_1"
    assert recent_writes[-1].payload["change_kind"] == "created"
    assert recent_writes[-1].payload["status"] == "queued"

    store.unsubscribe(queue)


@pytest.mark.anyio
async def test_memory_blackboard_put_run_and_put_task_publish_change_metadata():
    store = InMemoryBlackboard()
    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Draft email",
        goal="Draft email",
    )
    run = ExecutionRun(
        run_id="run_1",
        task_id="task_1",
        execution_session_id="sess_1",
        executor_type="codex",
    )

    await store.put_task(task)
    await store.put_run(run)

    task.status = TaskStatus.RUNNING
    run.status = RunStatus.RUNNING
    run.latest_progress_message = "Working through step 1."

    await store.put_task(task)
    await store.put_run(run)

    recent_writes = await store.list_recent_writes(limit=4)
    assert recent_writes[-2].payload["change_kind"] == "status_change"
    assert recent_writes[-2].payload["previous_status"] == "created"
    assert recent_writes[-1].payload["change_kind"] == "status_change"
    assert recent_writes[-1].payload["previous_status"] == "created"
    assert recent_writes[-1].payload["latest_progress_message"] == "Working through step 1."
