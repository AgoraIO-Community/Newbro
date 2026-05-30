from __future__ import annotations

import pytest

from newbro.blackboard import InMemoryBlackboard
from newbro.blackboard.store import BlackboardWriteEvent, BlackboardWriteKind
from newbro.interaction import InteractionManager
from newbro.protocol import (
    AttentionItemKind,
    AttentionItemStatus,
    ExecutionRun,
    InteractionRequestKind,
    InteractionRequestStatus,
    RunStatus,
    Task,
    TaskSummary,
)


@pytest.mark.anyio
async def test_interaction_manager_builds_permission_request_from_blocked_run_metadata():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Permission task",
        goal="Permission task",
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Allow network access?",
        metadata={"blocked_event": {"interaction_kind": "permission"}},
    )
    await store.put_task(task)
    await store.put_run(run)

    handled = await manager.handle_blackboard_write(
        BlackboardWriteEvent(
            kind=BlackboardWriteKind.RUN,
            entity_id="run-1",
            task_id="task-1",
        )
    )

    requests = await store.list_interaction_requests()
    items = await store.list_attention_items()
    assert handled is True
    assert len(requests) == 1
    assert requests[0].kind == InteractionRequestKind.PERMISSION
    assert requests[0].available_actions == ["approve", "deny"]
    assert len(items) == 1
    assert items[0].request_id == requests[0].request_id


@pytest.mark.anyio
async def test_interaction_manager_keeps_full_native_response_in_opaque_but_sanitizes_details():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-native",
        root_task_id="task-native",
        title="Permission task",
        goal="Permission task",
    )
    run = ExecutionRun(
        run_id="run-native",
        task_id="task-native",
        execution_session_id="exec-native",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Allow more access?",
        metadata={
            "blocked_event": {
                "interaction_kind": "permission",
                "blocked_method": "item/permissions/requestApproval",
                "native_response": {
                    "request_id": 7,
                    "method": "item/permissions/requestApproval",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "permissions": {"fileSystem": {"writeRoots": ["/tmp"]}},
                        "cwd": "/secret/path",
                    },
                },
            }
        },
    )
    await store.put_task(task)
    await store.put_run(run)

    await manager.handle_blackboard_write(
        BlackboardWriteEvent(
            kind=BlackboardWriteKind.RUN,
            entity_id="run-native",
            task_id="task-native",
        )
    )

    request = (await store.list_interaction_requests())[0]

    assert request.opaque["native_response"]["params"]["permissions"] == {
        "fileSystem": {"writeRoots": ["/tmp"]}
    }
    blocked_event = request.details["blocked_event"]
    assert blocked_event["interaction_kind"] == "permission"
    assert "permissions" not in blocked_event["native_response"]["params"]
    assert "cwd" not in blocked_event["native_response"]["params"]


@pytest.mark.anyio
async def test_interaction_manager_suppresses_duplicate_pending_request_for_same_run():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Blocked task",
        goal="Blocked task",
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Need confirmation?",
    )
    await store.put_task(task)
    await store.put_run(run)

    first = await manager.handle_blackboard_write(
        BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-1", task_id="task-1")
    )
    second = await manager.handle_blackboard_write(
        BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-1", task_id="task-1")
    )

    assert first is True
    assert second is False
    assert len(await store.list_interaction_requests()) == 1


@pytest.mark.anyio
async def test_interaction_manager_builds_request_from_needs_input_summary():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Input task",
        goal="Input task",
    )
    summary = TaskSummary(
        task_id="task-1",
        conversational_summary="I need one more detail.",
        latest_user_visible_status="waiting_user_input",
        needs_user_input=True,
    )
    await store.put_task(task)
    await store.put_summary(summary)

    handled = await manager.handle_blackboard_write(
        BlackboardWriteEvent(kind=BlackboardWriteKind.SUMMARY, entity_id="task-1", task_id="task-1")
    )

    requests = await store.list_interaction_requests()
    assert handled is True
    assert len(requests) == 1
    assert requests[0].prompt == "I need one more detail."


@pytest.mark.anyio
async def test_interaction_manager_resolve_answer_marks_request_and_returns_follow_up_instruction():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Question task",
        goal="Question task",
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Which project name should I use?",
    )
    await store.put_task(task)
    await store.put_run(run)
    await manager.handle_blackboard_write(
        BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-1", task_id="task-1")
    )
    request = (await store.list_interaction_requests())[0]

    resolution = await manager.resolve_request(
        request.request_id,
        action="answer",
        answer_text="Use Synopse",
    )

    updated = await store.get_interaction_request(request.request_id)
    attention = (await store.list_attention_items())[0]
    assert resolution.request.status == InteractionRequestStatus.ANSWERED
    assert updated is not None and updated.status == InteractionRequestStatus.ANSWERED
    assert "Use Synopse" in resolution.follow_up_instruction
    assert attention.status.value == "acted"


@pytest.mark.anyio
async def test_interaction_manager_rejects_invalid_resolution_action():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Permission task",
        goal="Permission task",
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Allow network access?",
        metadata={"blocked_event": {"interaction_kind": "permission"}},
    )
    await store.put_task(task)
    await store.put_run(run)
    await manager.handle_blackboard_write(
        BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-1", task_id="task-1")
    )
    request = (await store.list_interaction_requests())[0]

    with pytest.raises(ValueError, match="not allowed"):
        await manager.resolve_request(request.request_id, action="answer", answer_text="yes")


@pytest.mark.anyio
async def test_interaction_manager_requires_answer_text_for_answer_action():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-question",
        root_task_id="task-question",
        title="Question task",
        goal="Question task",
    )
    run = ExecutionRun(
        run_id="run-question",
        task_id="task-question",
        execution_session_id="exec-question",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Which project name should I use?",
    )
    await store.put_task(task)
    await store.put_run(run)
    await manager.handle_blackboard_write(
        BlackboardWriteEvent(
            kind=BlackboardWriteKind.RUN,
            entity_id="run-question",
            task_id="task-question",
        )
    )
    request = (await store.list_interaction_requests())[0]

    with pytest.raises(ValueError, match="answer_text is required"):
        await manager.resolve_request(request.request_id, action="answer", answer_text=None)


@pytest.mark.anyio
async def test_interaction_manager_builds_and_resolves_plan_proposal():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-plan",
        root_task_id="task-plan",
        title="Plan task",
        goal="Plan task",
        metadata={
            "persona_id": "persona-forge",
            "target_thread_id": "thread-public",
            "client_request_id": "text-client-1",
            "source_kind": "bro_detail_text",
        },
    )
    run = ExecutionRun(
        run_id="run-plan",
        task_id="task-plan",
        execution_session_id="exec-plan",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Pick a plan",
        metadata={
            "blocked_event": {
                "interaction_kind": "plan_proposal",
                "proposal": {
                    "summary": "Pick a plan",
                    "options": [
                        {"id": "small", "label": "Small", "description": "Minimal change"},
                        {"id": "full", "label": "Full", "description": "Complete feature"},
                    ],
                },
                "native_response": {
                    "request_id": "native-1",
                    "method": "item/tool/requestUserInput",
                    "params": {"threadId": "thread-1"},
                },
            },
        },
    )
    await store.put_task(task)
    await store.put_run(run)

    await manager.handle_blackboard_write(
        BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-plan", task_id="task-plan")
    )

    request = (await store.list_interaction_requests())[0]
    attention = (await store.list_attention_items())[0]
    assert request.kind == InteractionRequestKind.PLAN_PROPOSAL
    assert request.available_actions == ["approve", "deny"]
    assert request.details["proposal"] == {
        "summary": "Pick a plan",
        "options": [
            {"id": "small", "label": "Small", "description": "Minimal change"},
            {"id": "full", "label": "Full", "description": "Complete feature"},
        ],
    }
    assert request.details["persona_id"] == "persona-forge"
    assert request.details["target_thread_id"] == "thread-public"
    assert request.details["client_request_id"] == "text-client-1"
    assert request.details["source_kind"] == "bro_detail_text"
    assert attention.kind == AttentionItemKind.PLAN_PROPOSAL_REQUEST
    assert attention.actions == [
        {"action": "approve", "label": "Approve & run"},
        {"action": "deny", "label": "Keep planning"},
    ]

    resolution = await manager.resolve_request(
        request.request_id,
        action="approve",
        option_id="full",
    )

    assert resolution.answer_text == "Full"
    assert resolution.request.status == InteractionRequestStatus.APPROVED
    assert resolution.request.details["selected_option_id"] == "full"


@pytest.mark.anyio
async def test_interaction_manager_records_multi_question_plan_answers():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-multi-question",
        root_task_id="task-multi-question",
        title="Plan questions",
        goal="Plan questions",
    )
    run = ExecutionRun(
        run_id="run-multi-question",
        task_id="task-multi-question",
        execution_session_id="exec-multi-question",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Answer planning questions",
        metadata={
            "blocked_event": {
                "interaction_kind": "plan_proposal",
                "proposal": {
                    "summary": "Answer planning questions",
                    "questions": [
                        {
                            "question_id": "audience",
                            "header": "Audience",
                            "summary": "Who is this for?",
                            "options": [{"id": "boss", "label": "Boss / leadership"}],
                        },
                        {
                            "question_id": "period",
                            "header": "Period",
                            "summary": "Which period?",
                            "options": [{"id": "latest", "label": "Latest update"}],
                        },
                    ],
                    "question_id": "audience",
                    "options": [{"id": "boss", "label": "Boss / leadership"}],
                },
            },
        },
    )
    await store.put_task(task)
    await store.put_run(run)
    await manager.handle_blackboard_write(
        BlackboardWriteEvent(
            kind=BlackboardWriteKind.RUN,
            entity_id="run-multi-question",
            task_id="task-multi-question",
        )
    )
    request = (await store.list_interaction_requests())[0]

    resolution = await manager.resolve_request(
        request.request_id,
        action="approve",
        answers={
            "audience": ["Boss / leadership"],
            "period": ["Latest update"],
        },
    )

    assert resolution.answer_text == "Audience: Boss / leadership; Period: Latest update"
    assert resolution.answers == {
        "audience": ["Boss / leadership"],
        "period": ["Latest update"],
    }
    assert resolution.request.details["selected_answers"] == {
        "audience": ["Boss / leadership"],
        "period": ["Latest update"],
    }


@pytest.mark.anyio
async def test_interaction_manager_requires_all_multi_question_plan_answers():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    await store.put_task(
        Task(
            task_id="task-missing-question",
            root_task_id="task-missing-question",
            title="Plan questions",
            goal="Plan questions",
        )
    )
    await store.put_run(
        ExecutionRun(
            run_id="run-missing-question",
            task_id="task-missing-question",
            execution_session_id="exec-missing-question",
            executor_type="codex",
            status=RunStatus.BLOCKED,
            block_reason="Answer planning questions",
            metadata={
                "blocked_event": {
                    "interaction_kind": "plan_proposal",
                    "proposal": {
                        "summary": "Answer planning questions",
                        "questions": [
                            {"question_id": "audience", "header": "Audience", "summary": "Who is this for?"},
                            {"question_id": "period", "header": "Period", "summary": "Which period?"},
                        ],
                    },
                },
            },
        )
    )
    await manager.handle_blackboard_write(
        BlackboardWriteEvent(
            kind=BlackboardWriteKind.RUN,
            entity_id="run-missing-question",
            task_id="task-missing-question",
        )
    )
    request = (await store.list_interaction_requests())[0]

    with pytest.raises(ValueError, match="period"):
        await manager.resolve_request(
            request.request_id,
            action="approve",
            answers={"audience": ["Boss / leadership"]},
        )


@pytest.mark.anyio
async def test_interaction_manager_cancel_requests_for_task_marks_request_and_attention():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Permission task",
        goal="Permission task",
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
        status=RunStatus.BLOCKED,
        block_reason="Allow network access?",
        metadata={"blocked_event": {"interaction_kind": "permission"}},
    )
    await store.put_task(task)
    await store.put_run(run)
    await manager.handle_blackboard_write(
        BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-1", task_id="task-1")
    )

    await manager.cancel_requests_for_task("task-1")

    request = (await store.list_interaction_requests())[0]
    attention = (await store.list_attention_items())[0]
    assert request.status == InteractionRequestStatus.CANCELLED
    assert attention.status == AttentionItemStatus.DISMISSED


@pytest.mark.anyio
async def test_interaction_manager_add_task_signal_attention_creates_attention_item():
    store = InMemoryBlackboard()
    manager = InteractionManager(store)
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Pause task",
        goal="Pause task",
    )
    await store.put_task(task)

    item = await manager.add_task_signal_attention(
        task=task,
        kind=AttentionItemKind.TASK_PAUSED,
        body="Pause task is paused.",
    )

    saved = await store.get_attention_item(item.attention_id)
    assert saved is not None
    assert saved.kind == AttentionItemKind.TASK_PAUSED
    assert saved.body == "Pause task is paused."
