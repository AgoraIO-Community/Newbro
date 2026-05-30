import asyncio

import pytest

from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.protocol import (
    AgentResumeHandle,
    AttentionItem,
    AttentionItemKind,
    AttentionItemStatus,
    AttentionPriority,
    BindingStatus,
    CodexThreadEventMessage,
    CodexTurnEventMessage,
    ExecutionMode,
    ExecutionRun,
    ExecutionSession as RuntimeExecutionSession,
    InteractionRequest,
    InteractionRequestKind,
    InteractionRequestStatus,
    NotificationCandidate,
    NotificationCandidateType,
    NotificationDeliveryStatus,
    NotificationPriority,
    OutboundTurnRequest,
    Persona,
    RunStatus,
    SessionBinding,
    TaskCommand,
    TaskCommandType,
    TaskExecutionMode,
)
from newbro.executors.core import ExecutorCapabilities, ExecutorEvent, ExecutorEventType, ExecutorSession
from newbro.protocol import Task, TaskStatus
from newbro.runtime import Settings
from newbro.runtime.session import (
    SelectedCodexThreadSubscription,
    _timeline_turns_from_codex_thread,
    create_session_runtime,
)


@pytest.mark.anyio
async def test_session_runtime_publish_snapshot_notifies_subscribers():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    queue = session.subscribe()

    snapshot = await session.publish_snapshot()
    published = await queue.get()

    assert snapshot.session_id == "session-1"
    assert published.type == "snapshot"
    assert published.snapshot.session_id == "session-1"

    session.unsubscribe(queue)


@pytest.mark.anyio
async def test_session_runtime_publish_snapshot_uses_cached_codex_threads_by_default(
    monkeypatch: pytest.MonkeyPatch,
):
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    calls = 0

    async def fail_if_synced(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("publish_snapshot must not refresh Codex threads")

    monkeypatch.setattr(type(session), "_sync_imported_codex_threads", fail_if_synced)
    queue = session.subscribe()

    snapshot = await session.publish_snapshot()
    published = await queue.get()
    initial = await session.initial_snapshot_event()

    assert calls == 0
    assert snapshot.session_id == "session-1"
    assert published.type == "snapshot"
    assert initial.type == "snapshot"

    session.unsubscribe(queue)


@pytest.mark.anyio
async def test_session_runtime_snapshot_includes_outbound_turn_requests():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    request = OutboundTurnRequest(
        request_id="out-turn-1",
        persona_id="forge",
        executor_node_id="node-forge",
        target_thread_id="thread-1",
        text="continue",
    )

    await session.blackboard.put_outbound_turn_request(request)

    snapshot = await session.snapshot(sync_imported_codex_threads=False)

    assert snapshot.outbound_turn_requests == [request]


@pytest.mark.anyio
async def test_submit_executor_text_without_active_run_starts_outbound_turn_request(
    monkeypatch: pytest.MonkeyPatch,
):
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_persona(
        Persona(
            persona_id="forge",
            name="Forge",
            avatar="bro",
            base_prompt="",
            executor_node_id="node-forge",
            bro_detail_session_id="detail-forge",
        )
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-done",
            root_task_id="task-done",
            title="Done",
            goal="Done",
            status=TaskStatus.COMPLETED,
            preferred_executor="codex",
            metadata={"persona_id": "forge"},
        )
    )
    await session.blackboard.put_session(
        RuntimeExecutionSession(
            execution_session_id="exec-1",
            task_id="task-done",
            base_executor_id="codex",
            executor_node_id="node-forge",
            continuity_key="thread-1",
            latest_resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
        )
    )
    sent: list[dict[str, object]] = []

    monkeypatch.setattr(
        session.executor_node_manager,
        "is_executor_connected",
        lambda executor_type, *, node_id=None: executor_type == "codex" and node_id == "node-forge",
    )
    monkeypatch.setattr(
        session.executor_node_manager,
        "executor_supports_follow_up",
        lambda executor_type, *, node_id: executor_type == "codex" and node_id == "node-forge",
    )

    async def fake_start_codex_turn(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(session.executor_node_manager, "start_codex_turn", fake_start_codex_turn)

    instruction = await session.submit_executor_text_instruction(
        target_persona_id="forge",
        target_thread_id="exec-1",
        text="continue directly",
        client_request_id="client-text-1",
    )

    assert instruction.target_thread_id == "exec-1"
    assert [task.task_id for task in await session.blackboard.list_tasks()] == ["task-done"]
    requests = await session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].client_request_id == "client-text-1"
    assert requests[0].target_thread_id == "exec-1"
    assert requests[0].status == "accepted"
    assert sent[0]["request_id"] == requests[0].request_id
    assert sent[0]["target_thread_id"] == "exec-1"
    assert sent[0]["latest_resume_handle"] == AgentResumeHandle(
        executor_id="codex",
        session_handle="codex-thread-1",
    )
    assert "task_id" not in sent[0]


@pytest.mark.anyio
async def test_codex_turn_event_projects_without_task():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    request = OutboundTurnRequest(
        request_id="out-turn-1",
        persona_id="forge",
        executor_node_id="node-forge",
        target_thread_id="thread-1",
        client_request_id="client-text-1",
        text="continue directly",
        status="accepted",
        created_at="2026-05-30T08:00:00+00:00",
    )
    await session.blackboard.put_outbound_turn_request(request)

    await session.handle_codex_turn_event(
        CodexTurnEventMessage(
            request_id="out-turn-1",
            node_id="node-forge",
            target_persona_id="forge",
            target_thread_id="thread-1",
            event_type="progress",
            message="Working",
            executor_thread_id="native-thread-1",
            executor_turn_id="turn-1",
        )
    )

    snapshot = await session.snapshot(sync_imported_codex_threads=False)

    updated = await session.blackboard.get_outbound_turn_request("out-turn-1")
    assert updated is not None
    assert updated.status == "running"
    assert updated.executor_thread_id == "native-thread-1"
    assert updated.executor_turn_id == "turn-1"
    assert len(snapshot.bro_timeline_turns) == 1
    turn = snapshot.bro_timeline_turns[0]
    assert turn.owner == "executor"
    assert turn.client_request_id == "client-text-1"
    assert turn.task is None
    assert turn.executor_thread_id == "native-thread-1"
    assert turn.executor_turn_id == "turn-1"
    assert turn.user is not None
    assert turn.user.text == "continue directly"
    assert turn.status == "running"
    assert await session.blackboard.list_tasks() == []


@pytest.mark.anyio
async def test_codex_turn_event_keeps_stable_turn_when_executor_turn_id_arrives_late():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_outbound_turn_request(
        OutboundTurnRequest(
            request_id="out-turn-late-id",
            persona_id="forge",
            executor_node_id="node-forge",
            target_thread_id="thread-1",
            text="continue directly",
            status="accepted",
        )
    )

    await session.handle_codex_turn_event(
        CodexTurnEventMessage(
            request_id="out-turn-late-id",
            node_id="node-forge",
            target_persona_id="forge",
            target_thread_id="thread-1",
            event_type="progress",
            message="Accepted",
            executor_thread_id="native-thread-1",
        )
    )
    await session.handle_codex_turn_event(
        CodexTurnEventMessage(
            request_id="out-turn-late-id",
            node_id="node-forge",
            target_persona_id="forge",
            target_thread_id="thread-1",
            event_type="completed",
            message="Done",
            executor_thread_id="native-thread-1",
            executor_turn_id="turn-1",
        )
    )

    snapshot = await session.snapshot(sync_imported_codex_threads=False)

    assert len(snapshot.bro_timeline_turns) == 1
    assert snapshot.bro_timeline_turns[0].executor_turn_id == "turn-1"
    assert snapshot.bro_timeline_turns[0].status == "completed"


@pytest.mark.anyio
async def test_codex_turn_cancelled_event_keeps_request_and_timeline_status_consistent():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_outbound_turn_request(
        OutboundTurnRequest(
            request_id="out-turn-cancelled",
            persona_id="forge",
            executor_node_id="node-forge",
            target_thread_id="thread-1",
            status="accepted",
        )
    )

    await session.handle_codex_turn_event(
        CodexTurnEventMessage(
            request_id="out-turn-cancelled",
            node_id="node-forge",
            target_persona_id="forge",
            target_thread_id="thread-1",
            event_type="cancelled",
            message="Cancelled",
            ok=False,
            error="Cancelled",
        )
    )

    updated = await session.blackboard.get_outbound_turn_request("out-turn-cancelled")
    snapshot = await session.snapshot(sync_imported_codex_threads=False)

    assert updated is not None
    assert updated.status == "failed"
    assert snapshot.bro_timeline_turns[0].status == "failed"


@pytest.mark.anyio
async def test_codex_turn_event_attaches_new_thread_resume_handle_for_follow_up(
    monkeypatch: pytest.MonkeyPatch,
):
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_persona(
        Persona(
            persona_id="forge",
            name="Forge",
            avatar="bro",
            base_prompt="",
            executor_node_id="node-forge",
            bro_detail_session_id="detail-forge",
        )
    )
    await session.blackboard.put_outbound_turn_request(
        OutboundTurnRequest(
            request_id="out-turn-new-thread",
            persona_id="forge",
            executor_node_id="node-forge",
            target_thread_id="bro-thread-new",
            create_new_thread=True,
            workspace_id="/tmp/work",
            text="start directly",
            status="accepted",
        )
    )

    await session.handle_codex_turn_event(
        CodexTurnEventMessage(
            request_id="out-turn-new-thread",
            node_id="node-forge",
            target_persona_id="forge",
            target_thread_id="bro-thread-new",
            event_type="progress",
            executor_thread_id="native-thread-new",
            executor_turn_id="turn-1",
        )
    )
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        session.executor_node_manager,
        "is_executor_connected",
        lambda executor_type, *, node_id=None: executor_type == "codex" and node_id == "node-forge",
    )
    monkeypatch.setattr(
        session.executor_node_manager,
        "executor_supports_follow_up",
        lambda executor_type, *, node_id: executor_type == "codex" and node_id == "node-forge",
    )

    async def fake_start_codex_turn(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(session.executor_node_manager, "start_codex_turn", fake_start_codex_turn)

    snapshot = await session.snapshot(sync_imported_codex_threads=False)
    instruction = await session.submit_executor_text_instruction(
        target_persona_id="forge",
        target_thread_id="bro-thread-new",
        text="follow up",
    )

    assert any(thread.thread_id == "bro-thread-new" and thread.has_resume_handle for thread in snapshot.bro_threads)
    assert instruction.target_thread_id == "bro-thread-new"
    assert sent[0]["latest_resume_handle"] == AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-new",
        opaque={
            "cwd": "/tmp/work",
            "title": "start directly",
            "createdFromOutboundTurnRequest": "out-turn-new-thread",
        },
    )
    assert await session.blackboard.list_tasks() == []


def test_codex_native_history_marks_user_turn_with_final_plan_item_as_plan_mode():
    turns = _timeline_turns_from_codex_thread(
        thread={
            "turns": [
                {
                    "id": "turn-plan",
                    "createdAt": "2026-05-26T22:01:00+00:00",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "user-1",
                            "text": "Plan the cleanup first.",
                        },
                        {
                            "type": "plan",
                            "id": "plan-1",
                            "text": "Audit, edit, verify.",
                        },
                    ],
                }
            ]
        },
        public_thread_id="thread-public",
        executor_thread_id="codex-thread-1",
        persona_id="forge",
        executor_id="codex",
    )

    assert len(turns) == 1
    assert turns[0].metadata["plan_mode"] is True
    assert turns[0].metadata["codex_plan"] == {"text": "Audit, edit, verify.", "steps": []}
    assert turns[0].user is not None
    assert turns[0].user.metadata["plan_mode"] is True


def test_codex_native_history_marks_split_user_turn_when_next_turn_has_plan_item():
    turns = _timeline_turns_from_codex_thread(
        thread={
            "turns": [
                {
                    "id": "turn-user",
                    "createdAt": "2026-05-26T22:01:00+00:00",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "user-1",
                            "text": "Plan before changing files.",
                        }
                    ],
                },
                {
                    "id": "turn-plan",
                    "createdAt": "2026-05-26T22:02:00+00:00",
                    "items": [
                        {
                            "type": "plan",
                            "id": "plan-1",
                            "text": "Read contracts, patch projection, test.",
                        }
                    ],
                },
            ]
        },
        public_thread_id="thread-public",
        executor_thread_id="codex-thread-1",
        persona_id="forge",
        executor_id="codex",
    )

    assert len(turns) == 1
    assert turns[0].executor_turn_id == "turn-plan"
    assert turns[0].metadata["original_user_executor_turn_id"] == "turn-user"
    assert turns[0].metadata["plan_mode"] is True
    assert turns[0].user is not None
    assert turns[0].user.text == "Plan before changing files."
    assert turns[0].user.metadata["plan_mode"] is True


def test_codex_native_history_does_not_mark_ordinary_turns_as_plan_mode():
    turns = _timeline_turns_from_codex_thread(
        thread={
            "turns": [
                {
                    "id": "turn-ordinary",
                    "createdAt": "2026-05-26T22:01:00+00:00",
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "user-1",
                            "text": "Summarize status.",
                        },
                        {
                            "type": "agentMessage",
                            "id": "assistant-1",
                            "text": "Status summarized.",
                        },
                    ],
                }
            ]
        },
        public_thread_id="thread-public",
        executor_thread_id="codex-thread-1",
        persona_id="forge",
        executor_id="codex",
    )

    assert len(turns) == 1
    assert "plan_mode" not in turns[0].metadata
    assert turns[0].user is not None
    assert "plan_mode" not in turns[0].user.metadata


@pytest.mark.anyio
async def test_selected_codex_thread_events_do_not_read_history_on_control_path(
    monkeypatch: pytest.MonkeyPatch,
):
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )
    calls = 0

    async def fail_if_read(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("selected-thread events must not block on Codex thread/read")

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fail_if_read)

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={"item": {"type": "assistantMessage"}},
        )
    )

    assert calls == 0
    assert "forge" in session._selected_codex_thread_subscriptions


@pytest.mark.anyio
async def test_selected_codex_thread_message_events_replace_latest_assistant_turn_message():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-1",
                "item": {
                    "type": "agentMessage",
                    "id": "commentary-1",
                    "text": "Checking files.",
                },
            },
        )
    )
    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-1",
                "item": {
                    "type": "agentMessage",
                    "id": "final-1",
                    "text": "Final answer.",
                },
            },
        )
    )

    turns = session._bro_thread_executor_turns["thread-public"]
    assert len(turns) == 1
    assert turns[0].turn_id == "thread-public:codex:turn-1"
    assert turns[0].assistant is not None
    assert turns[0].assistant.text == "Final answer."
    assert turns[0].assistant.metadata["codex_item_id"] == "final-1"


@pytest.mark.anyio
async def test_selected_codex_thread_delta_events_replace_previous_turn_item():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    for item_id, delta in [
        ("commentary-1", "Checking"),
        ("commentary-1", " files."),
        ("final-1", "Final"),
        ("final-1", " answer."),
    ]:
        await session.handle_codex_thread_event(
            CodexThreadEventMessage(
                subscription_id="codex-sub-1",
                node_id="node-forge",
                session_id="session-1",
                target_persona_id="forge",
                target_thread_id="thread-public",
                thread_id="codex-thread-1",
                method="item/agentMessage/delta",
                params={"turnId": "turn-1", "itemId": item_id, "delta": delta},
            )
        )

    turns = session._bro_thread_executor_turns["thread-public"]
    assert len(turns) == 1
    assert turns[0].turn_id == "thread-public:codex:turn-1"
    assert turns[0].assistant is not None
    assert turns[0].assistant.text == "Final answer."
    assert turns[0].assistant.status == "running"
    assert turns[0].assistant.metadata["codex_item_id"] == "final-1"


@pytest.mark.anyio
async def test_selected_codex_thread_projects_plan_and_goal_without_reasoning():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="thread/goal/updated",
            params={"threadId": "codex-thread-1", "goal": "Ship plan projection"},
        )
    )
    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-1",
                "item": {
                    "type": "reasoning",
                    "text": "Do not show this.",
                },
            },
        )
    )
    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-1",
                "item": {
                    "type": "plan",
                    "id": "plan-1",
                    "text": "Use documented plan events.",
                },
            },
        )
    )

    turns = session._bro_thread_executor_turns["thread-public"]
    assert len(turns) == 1
    assert turns[0].metadata["codex_goal"] == "Ship plan projection"
    assert turns[0].metadata["codex_plan"] == {"text": "Use documented plan events.", "steps": []}
    assert turns[0].assistant is None


@pytest.mark.anyio
async def test_selected_codex_thread_events_merge_with_newbro_owned_task_timeline():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-direct",
            root_task_id="task-direct",
            parent_task_id=None,
            title="Continue directly",
            goal="Continue directly",
            status=TaskStatus.RUNNING,
            metadata={
                "persona_id": "forge",
                "bro_thread_id": "thread-public",
                "target_thread_id": "thread-public",
                "source_kind": "bro_detail_text",
                "client_request_id": "text-client-1",
            },
        )
    )
    await session.blackboard.put_run(
        ExecutionRun(
            run_id="run-direct",
            task_id="task-direct",
            execution_session_id="exec-direct",
            executor_type="codex",
            status=RunStatus.RUNNING,
            metadata={
                "latest_progress_event": {
                    "executor_thread_id": "codex-thread-1",
                    "executor_turn_id": "turn-1",
                }
            },
        )
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-1",
                "item": {
                    "type": "agentMessage",
                    "id": "final-1",
                    "text": "Task-backed response.",
                },
            },
        )
    )

    assert len(session._bro_thread_executor_turns["thread-public"]) == 1
    snapshot = await session.snapshot()
    timeline_turns = [turn for turn in snapshot.bro_timeline_turns if turn.thread_id == "thread-public"]
    assert len(timeline_turns) == 1
    assert timeline_turns[0].owner == "newbro"
    assert timeline_turns[0].assistant is not None
    assert timeline_turns[0].assistant.text == "Task-backed response."


@pytest.mark.anyio
async def test_selected_codex_thread_events_merge_with_pending_newbro_turn_by_client_request_id():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-direct",
            root_task_id="task-direct",
            parent_task_id=None,
            title="Continue directly",
            goal="Continue directly",
            status=TaskStatus.RUNNING,
            metadata={
                "persona_id": "forge",
                "bro_thread_id": "thread-public",
                "target_thread_id": "thread-public",
                "source_kind": "bro_detail_text",
                "client_request_id": "text-client-1",
            },
        )
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-1",
                "item": {
                    "type": "agentMessage",
                    "id": "final-1",
                    "text": "Pending task-backed response.",
                },
            },
        )
    )

    executor_turns = session._bro_thread_executor_turns["thread-public"]
    assert len(executor_turns) == 1
    assert executor_turns[0].client_request_id == "text-client-1"
    snapshot = await session.snapshot()
    timeline_turns = [turn for turn in snapshot.bro_timeline_turns if turn.thread_id == "thread-public"]
    assert len(timeline_turns) == 1
    assert timeline_turns[0].turn_id == "thread-public:newbro:text-client-1"
    assert timeline_turns[0].assistant is not None
    assert timeline_turns[0].assistant.text == "Pending task-backed response."


@pytest.mark.anyio
async def test_selected_codex_thread_plan_deltas_are_coalesced_but_final_plan_is_projected():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    for delta in ("Draft", " plan"):
        await session.handle_codex_thread_event(
            CodexThreadEventMessage(
                subscription_id="codex-sub-1",
                node_id="node-forge",
                session_id="session-1",
                target_persona_id="forge",
                target_thread_id="thread-public",
                thread_id="codex-thread-1",
                method="item/plan/delta",
                params={
                    "turnId": "turn-plan",
                    "itemId": "plan-1",
                    "delta": delta,
                },
            )
        )

    assert session._bro_thread_executor_turns.get("thread-public") is None

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-plan",
                "item": {
                    "type": "plan",
                    "id": "plan-1",
                    "text": "Final selected-thread plan.",
                },
            },
        )
    )

    turns = session._bro_thread_executor_turns["thread-public"]
    assert len(turns) == 1
    assert turns[0].metadata["codex_plan"] == {
        "text": "Final selected-thread plan.",
        "steps": [],
    }
    assert turns[0].metadata["plan_mode"] is True


@pytest.mark.anyio
async def test_selected_codex_thread_split_user_turn_pairs_with_final_plan_item():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-user",
                "timestamp": "2026-05-26T22:01:00+00:00",
                "item": {
                    "type": "userMessage",
                    "id": "user-1",
                    "text": "Plan this before changing files.",
                },
            },
        )
    )
    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-plan",
                "timestamp": "2026-05-26T22:02:00+00:00",
                "item": {
                    "type": "plan",
                    "id": "plan-1",
                    "text": "Read contracts, patch projection, run tests.",
                },
            },
        )
    )

    turns = session._bro_thread_executor_turns["thread-public"]
    assert len(turns) == 1
    assert turns[0].executor_turn_id == "turn-plan"
    assert turns[0].metadata["original_user_executor_turn_id"] == "turn-user"
    assert turns[0].metadata["plan_mode"] is True
    assert turns[0].metadata["codex_plan"] == {
        "text": "Read contracts, patch projection, run tests.",
        "steps": [],
    }
    assert turns[0].user is not None
    assert turns[0].user.text == "Plan this before changing files."
    assert turns[0].user.metadata["plan_mode"] is True
    snapshot = await session.snapshot()
    thread_turns = [turn for turn in snapshot.bro_timeline_turns if turn.thread_id == "thread-public"]
    assert len(thread_turns) == 1
    assert thread_turns[0].user is not None
    assert thread_turns[0].user.text == "Plan this before changing files."


@pytest.mark.anyio
async def test_selected_codex_thread_same_turn_plan_marks_existing_user_message_plan_mode():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
    )

    for item in [
        {"type": "userMessage", "id": "user-1", "text": "Plan this turn."},
        {"type": "plan", "id": "plan-1", "text": "First inspect, then edit."},
    ]:
        await session.handle_codex_thread_event(
            CodexThreadEventMessage(
                subscription_id="codex-sub-1",
                node_id="node-forge",
                session_id="session-1",
                target_persona_id="forge",
                target_thread_id="thread-public",
                thread_id="codex-thread-1",
                method="item/completed",
                params={
                    "turnId": "turn-1",
                    "timestamp": "2026-05-26T22:01:00+00:00",
                    "item": item,
                },
            )
        )

    turns = session._bro_thread_executor_turns["thread-public"]
    assert len(turns) == 1
    assert turns[0].metadata["plan_mode"] is True
    assert turns[0].user is not None
    assert turns[0].user.text == "Plan this turn."
    assert turns[0].user.metadata["plan_mode"] is True
    assert turns[0].metadata["codex_plan"] == {"text": "First inspect, then edit.", "steps": []}


@pytest.mark.anyio
async def test_selected_codex_thread_late_event_merges_with_completed_direct_turn_by_client_request_id():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-direct",
            root_task_id="task-direct",
            parent_task_id=None,
            title="Continue directly",
            goal="Continue directly",
            status=TaskStatus.COMPLETED,
            metadata={
                "persona_id": "forge",
                "bro_thread_id": "thread-public",
                "target_thread_id": "thread-public",
                "source_kind": "bro_detail_ptt",
                "client_request_id": "audio-client-1",
                "source_audio_instruction_id": "aud-1",
                "created_at": "2026-05-26T22:01:00+00:00",
                "updated_at": "2026-05-26T22:01:10+00:00",
            },
        )
    )
    await session.blackboard.put_run(
        ExecutionRun(
            run_id="run-direct",
            task_id="task-direct",
            execution_session_id="exec-direct",
            executor_type="codex",
            status=RunStatus.COMPLETED,
            output_summary="Task-backed response.",
            metadata={},
        )
    )
    session._selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="codex-sub-1",
        persona_id="forge",
        public_thread_id="thread-public",
        thread_continuity_key="thread-public",
        node_id="node-forge",
        codex_thread_id="codex-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="codex-thread-1"),
        fallback_timestamp="2026-05-26T21:00:00+00:00",
    )

    await session.handle_codex_thread_event(
        CodexThreadEventMessage(
            subscription_id="codex-sub-1",
            node_id="node-forge",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="thread-public",
            thread_id="codex-thread-1",
            method="item/completed",
            params={
                "turnId": "turn-1",
                "timestamp": "2026-05-26T22:01:12+00:00",
                "item": {
                    "type": "agentMessage",
                    "id": "final-1",
                    "text": "Late native response.",
                },
            },
        )
    )

    executor_turns = session._bro_thread_executor_turns["thread-public"]
    assert len(executor_turns) == 1
    assert executor_turns[0].client_request_id == "audio-client-1"
    assert executor_turns[0].created_at == "2026-05-26T22:01:12+00:00"
    snapshot = await session.snapshot()
    timeline_turns = [turn for turn in snapshot.bro_timeline_turns if turn.thread_id == "thread-public"]
    assert len(timeline_turns) == 1
    assert timeline_turns[0].turn_id == "thread-public:newbro:audio-client-1"
    assert timeline_turns[0].user is not None
    assert timeline_turns[0].user.kind == "audio"
    assert timeline_turns[0].assistant is not None
    assert timeline_turns[0].assistant.text == "Late native response."


@pytest.mark.anyio
async def test_session_runtime_registers_codex_when_enabled(tmp_path):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nexit 0\n")
    fake_codex.chmod(0o755)

    session = create_session_runtime(
        "session-2",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(codex_executor_enabled=True, codex_command=str(fake_codex)),
    )

    assert sorted(session.registry.list_executor_types()) == ["codex", "mock"]


class BackgroundTestExecutor:
    def __init__(self) -> None:
        self._capabilities = ExecutorCapabilities(executor_type="background")

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(session_id="background-session", executor_type="background")

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def pause_run(self, run_id: str) -> None:
        return None

    async def run_task(self, run, task, session):
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.PROGRESS,
            message="working",
        )
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.COMPLETED,
            message="done",
        )


class PlanProposalLifecycleExecutor:
    def __init__(self, executor_type: str = "plan-lifecycle") -> None:
        self._capabilities = ExecutorCapabilities(
            executor_type=executor_type,
            supports_follow_up=True,
        )
        self.calls: list[dict[str, object]] = []

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(
            session_id=f"{self._capabilities.executor_type}-session",
            executor_type=self._capabilities.executor_type,
        )

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def pause_run(self, run_id: str) -> None:
        return None

    async def run_task(self, run, task, session):
        self.calls.append({
            "latest_instruction": task.latest_instruction,
            "metadata": dict(task.metadata),
        })
        if task.metadata.get("plan_mode") is True:
            yield ExecutorEvent(
                run_id=run.run_id,
                session_id=session.session_id,
                event_type=ExecutorEventType.BLOCKED,
                message="Review the proposed lifecycle plan before execution.",
                metadata={
                    "interaction_kind": "plan_proposal",
                    "proposal": {
                        "summary": "Review the proposed lifecycle plan before execution.",
                        "options": [
                            {
                                "id": "approved_codex_plan",
                                "label": "Run proposed plan",
                                "description": "Implement the approved lifecycle plan.",
                            }
                        ],
                    },
                },
            )
            return
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.COMPLETED,
            message="Implemented the approved lifecycle plan.",
        )


class CancelTrackingExecutor:
    def __init__(self) -> None:
        self._capabilities = ExecutorCapabilities(executor_type="cancellable", supports_cancel=True)
        self.cancelled_runs: list[str] = []

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(session_id="cancellable-session", executor_type="cancellable")

    async def cancel_run(self, run_id: str) -> None:
        self.cancelled_runs.append(run_id)

    async def pause_run(self, run_id: str) -> None:
        return None

    async def run_task(self, run, task, session):
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.PROGRESS,
            message="working",
        )


class NoPauseExecutor:
    def __init__(self) -> None:
        self._capabilities = ExecutorCapabilities(
            executor_type="no-pause",
            supports_pause=False,
            supports_cancel=True,
        )

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(session_id="no-pause-session", executor_type="no-pause")

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def pause_run(self, run_id: str) -> None:
        return None

    async def run_task(self, run, task, session):
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.PROGRESS,
            message="working",
        )


class ManagedPauseExecutor:
    def __init__(self) -> None:
        self._capabilities = ExecutorCapabilities(
            executor_type="managed-pause",
            supports_pause=True,
            supports_resume=True,
            supports_cancel=True,
        )
        self.paused_runs: list[str] = []

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(session_id="managed-pause-session", executor_type="managed-pause")

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def pause_run(self, run_id: str) -> None:
        self.paused_runs.append(run_id)

    async def run_task(self, run, task, session):
        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.PROGRESS,
            message="working",
        )

    def build_resume_handle(self, session: ExecutorSession) -> AgentResumeHandle:
        return AgentResumeHandle(
            executor_id="managed-pause",
            session_handle=session.session_id,
            opaque={"mode": "managed-pause"},
        )


class FakeNativeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def respond_to_request(self, **kwargs) -> None:
        self.calls.append(kwargs)

    async def close(self) -> None:
        self.closed = True


class FakeNativeCodexSession:
    def __init__(self) -> None:
        from newbro.executors.adapters.codex.session import CodexExecutorSession

        self.session = CodexExecutorSession(
            session_id="codex-session-native",
            executor_type="codex",
        )
        self.client = FakeNativeClient()
        self.session._client = self.client  # noqa: SLF001
        self.session._blocked_resolution_event = asyncio.Event()  # noqa: SLF001

    def mark_blocked_resolved(self) -> None:
        self.session.mark_blocked_resolved()


async def _wait_for_runtime_state(predicate, timeout: float = 4.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = await predicate()
        if result:
            return result
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Timed out waiting for expected runtime state.")
        await asyncio.sleep(0.05)


async def _pending_plan_request(session, task_id: str):
    requests = await session.blackboard.list_interaction_requests()
    for request in requests:
        if (
            request.task_id == task_id
            and request.kind == InteractionRequestKind.PLAN_PROPOSAL
            and request.status == InteractionRequestStatus.PENDING
        ):
            return request
    return None


async def _completed_task(session, task_id: str):
    task = await session.blackboard.get_task(task_id)
    if task is not None and task.status == TaskStatus.COMPLETED:
        return task
    return None


@pytest.mark.anyio
async def test_session_runtime_snapshot_pump_publishes_background_execution_updates():
    session = create_session_runtime(
        "session-3",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session.registry.register(BackgroundTestExecutor())
    queue = session.subscribe()
    await session.blackboard.put_task(
        Task(
            task_id="task-bg",
            root_task_id="task-bg",
            title="Background task",
            goal="Background task",
            status=TaskStatus.QUEUED,
            preferred_executor="background",
        )
    )
    session.schedule_execution()

    snapshots = []
    for _ in range(3):
        snapshots.append(await asyncio.wait_for(queue.get(), timeout=1.0))
        if (
            snapshots[-1].type == "snapshot"
            and snapshots[-1].snapshot.execution_runs
            and snapshots[-1].snapshot.execution_runs[0].status == "completed"
        ):
            break

    snapshot_payloads = [event.snapshot for event in snapshots if event.type == "snapshot"]
    assert any(snapshot.execution_runs for snapshot in snapshot_payloads)
    assert snapshot_payloads[-1].tasks[0].status == "completed"
    session.unsubscribe(queue)


@pytest.mark.anyio
async def test_session_runtime_snapshot_includes_execution_modes():
    session = create_session_runtime(
        "session-4",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_execution_mode(
        TaskExecutionMode(
            task_id="task-1",
            mode=ExecutionMode.MANAGED,
            decided_from_run_id="run-1",
            elapsed_seconds=32.0,
        )
    )

    snapshot = await session.snapshot()

    assert snapshot.execution_modes[0].mode == ExecutionMode.MANAGED


@pytest.mark.anyio
async def test_session_runtime_snapshot_includes_notification_candidates():
    session = create_session_runtime(
        "session-5",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_notification_candidate(
        NotificationCandidate(
            candidate_id="notif-1",
            task_id="task-1",
            candidate_type=NotificationCandidateType.COMPLETED,
            priority=NotificationPriority.P2,
            summary_short="Task completed.",
            created_at="2026-04-06T00:00:00+00:00",
            delivery_status=NotificationDeliveryStatus.PENDING,
            merge_key="completed_digest",
        )
    )

    snapshot = await session.snapshot()

    assert snapshot.notification_candidates[0].candidate_id == "notif-1"


@pytest.mark.anyio
async def test_session_runtime_snapshot_includes_interaction_requests_and_attention_items():
    session = create_session_runtime(
        "session-5b",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-1",
            task_id="task-1",
            kind=InteractionRequestKind.QUESTION,
            status=InteractionRequestStatus.PENDING,
            prompt="Need confirmation?",
            available_actions=["answer"],
            created_at="2026-04-06T00:00:00+00:00",
        )
    )
    await session.blackboard.put_attention_item(
        AttentionItem(
            attention_id="attention-1",
            source="interaction_request",
            kind=AttentionItemKind.QUESTION_REQUEST,
            priority=AttentionPriority.P0,
            status=AttentionItemStatus.ACTIVE,
            title="Need your input",
            body="Need confirmation?",
            task_id="task-1",
            request_id="ireq-1",
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    snapshot = await session.snapshot()

    assert snapshot.interaction_requests[0].request_id == "ireq-1"
    assert snapshot.attention_items[0].attention_id == "attention-1"


@pytest.mark.anyio
async def test_session_runtime_snapshot_sanitizes_interaction_request_opaque():
    session = create_session_runtime(
        "session-5c",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-2",
            task_id="task-2",
            kind=InteractionRequestKind.PERMISSION,
            status=InteractionRequestStatus.PENDING,
            prompt="Allow deleting the folder?",
            available_actions=["approve", "deny"],
            details={
                "blocked_event": {
                    "interaction_kind": "permission",
                    "blocked_method": "item/commandExecution/requestApproval",
                    "native_response": {
                        "request_id": 9,
                        "method": "item/commandExecution/requestApproval",
                        "params": {
                            "threadId": "thread-1",
                            "turnId": "turn-1",
                            "itemId": "call-1",
                            "command": "rm -rf /tmp/x",
                            "cwd": "/secret/path",
                            "proposedExecpolicyAmendment": ["rm", "-rf", "/tmp/x"],
                        },
                    },
                }
            },
            opaque={
                "native_response": {
                    "request_id": 9,
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "itemId": "call-1",
                        "command": "rm -rf /tmp/x",
                        "cwd": "/secret/path",
                        "proposedExecpolicyAmendment": ["rm", "-rf", "/tmp/x"],
                    },
                }
            },
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    snapshot = await session.snapshot()
    opaque = snapshot.interaction_requests[0].opaque["native_response"]

    assert opaque["request_id"] == 9
    assert opaque["method"] == "item/commandExecution/requestApproval"
    assert opaque["params"]["command"] == "rm -rf /tmp/x"
    assert "cwd" not in opaque["params"]
    assert "proposedExecpolicyAmendment" not in opaque["params"]
    blocked_event = snapshot.interaction_requests[0].details["blocked_event"]
    assert blocked_event["interaction_kind"] == "permission"
    assert blocked_event["native_response"]["params"]["command"] == "rm -rf /tmp/x"
    assert "cwd" not in blocked_event["native_response"]["params"]
    assert "proposedExecpolicyAmendment" not in blocked_event["native_response"]["params"]


@pytest.mark.anyio
async def test_session_runtime_apply_command_cancels_live_run_and_suppresses_pending_notifications():
    session = create_session_runtime(
        "session-6",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    executor = CancelTrackingExecutor()
    session.registry.register(executor)
    await session.blackboard.put_task(
        Task(
            task_id="task-cancel",
            root_task_id="task-cancel",
            title="Cancelable task",
            goal="Cancelable task",
            status=TaskStatus.RUNNING,
            preferred_executor="cancellable",
        )
    )
    await session.blackboard.put_session(
        RuntimeExecutionSession(
            execution_session_id="exec-session-cancel",
            task_id="task-cancel",
            base_executor_id="cancellable",
            active_run_id="run-cancel",
            latest_run_id="run-cancel",
            run_ids=["run-cancel"],
        )
    )
    await session.blackboard.put_binding(
        SessionBinding(
            task_id="task-cancel",
            execution_session_id="exec-session-cancel",
            session_id="cancellable-session",
            claimed_by="worker-session-6",
            claim_expires_at="2026-04-16T00:10:00+00:00",
            binding_status=BindingStatus.ACTIVE,
        )
    )
    await session.blackboard.put_run(
        ExecutionRun(
            run_id="run-cancel",
            task_id="task-cancel",
            execution_session_id="exec-session-cancel",
            executor_type="cancellable",
            status=RunStatus.RUNNING,
        )
    )
    await session.blackboard.put_notification_candidate(
        NotificationCandidate(
            candidate_id="notif-cancel",
            task_id="task-cancel",
            candidate_type=NotificationCandidateType.COMPLETED,
            priority=NotificationPriority.P2,
            summary_short="Should not emit.",
            created_at="2026-04-16T00:00:00+00:00",
            delivery_status=NotificationDeliveryStatus.PENDING,
            merge_key="completed_digest",
        )
    )

    await session.apply_command(
        TaskCommand(
            command_id="cmd-cancel",
            task_id="task-cancel",
            command_type=TaskCommandType.CANCEL_TASK,
            created_by="test",
        )
    )

    task = await session.blackboard.get_task("task-cancel")
    run = await session.blackboard.get_run("run-cancel")
    execution_session = await session.blackboard.get_session("exec-session-cancel")
    binding = await session.blackboard.get_binding("task-cancel")
    summary = await session.blackboard.get_summary("task-cancel")
    candidate = await session.blackboard.get_notification_candidate("notif-cancel")

    assert executor.cancelled_runs == ["run-cancel"]
    assert task is not None and task.status == TaskStatus.CANCELLED
    assert run is not None and run.status == RunStatus.CANCELLED
    assert execution_session is not None and execution_session.active_run_id is None
    assert binding is not None and binding.binding_status == BindingStatus.RELEASED
    assert summary is not None and summary.latest_user_visible_status == "cancelled"
    assert candidate is not None and candidate.delivery_status == NotificationDeliveryStatus.SUPPRESSED


@pytest.mark.anyio
async def test_session_runtime_apply_command_rejects_pause_when_executor_cannot_pause():
    session = create_session_runtime(
        "session-6b",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    session.registry.register(NoPauseExecutor())
    await session.blackboard.put_task(
        Task(
            task_id="task-no-pause",
            root_task_id="task-no-pause",
            title="No pause task",
            goal="No pause task",
            status=TaskStatus.RUNNING,
            preferred_executor="no-pause",
        )
    )
    await session.blackboard.put_session(
        RuntimeExecutionSession(
            execution_session_id="exec-session-no-pause",
            task_id="task-no-pause",
            base_executor_id="no-pause",
            active_run_id="run-no-pause",
            latest_run_id="run-no-pause",
            run_ids=["run-no-pause"],
        )
    )
    await session.blackboard.put_run(
        ExecutionRun(
            run_id="run-no-pause",
            task_id="task-no-pause",
            execution_session_id="exec-session-no-pause",
            executor_type="no-pause",
            status=RunStatus.RUNNING,
        )
    )

    with pytest.raises(ValueError, match="does not support pause"):
        await session.apply_command(
            TaskCommand(
                command_id="cmd-no-pause",
                task_id="task-no-pause",
                command_type=TaskCommandType.PAUSE_TASK,
                created_by="test",
            )
        )


@pytest.mark.anyio
async def test_session_runtime_pause_captures_resume_handle_for_managed_pause_executor():
    session = create_session_runtime(
        "session-6c",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    executor = ManagedPauseExecutor()
    session.registry.register(executor)
    await session.blackboard.put_task(
        Task(
            task_id="task-managed-pause",
            root_task_id="task-managed-pause",
            title="Managed pause task",
            goal="Managed pause task",
            status=TaskStatus.RUNNING,
            preferred_executor="managed-pause",
        )
    )
    await session.blackboard.put_session(
        RuntimeExecutionSession(
            execution_session_id="exec-session-managed-pause",
            task_id="task-managed-pause",
            base_executor_id="managed-pause",
            active_run_id="run-managed-pause",
            latest_run_id="run-managed-pause",
            run_ids=["run-managed-pause"],
        )
    )
    await session.blackboard.put_binding(
        SessionBinding(
            task_id="task-managed-pause",
            execution_session_id="exec-session-managed-pause",
            session_id="managed-pause-session",
            claimed_by="worker-session-6c",
            claim_expires_at="2026-04-16T00:10:00+00:00",
            binding_status=BindingStatus.ACTIVE,
        )
    )
    await session.blackboard.put_run(
        ExecutionRun(
            run_id="run-managed-pause",
            task_id="task-managed-pause",
            execution_session_id="exec-session-managed-pause",
            executor_type="managed-pause",
            status=RunStatus.RUNNING,
        )
    )
    session.execution_brain._loop._sessions._live_sessions["exec-session-managed-pause"] = (
        ExecutorSession(
            session_id="managed-pause-session",
            executor_type="managed-pause",
        )
    )

    await session.apply_command(
        TaskCommand(
            command_id="cmd-managed-pause",
            task_id="task-managed-pause",
            command_type=TaskCommandType.PAUSE_TASK,
            created_by="test",
        )
    )

    execution_session = await session.blackboard.get_session("exec-session-managed-pause")
    task = await session.blackboard.get_task("task-managed-pause")
    assert execution_session is not None and execution_session.latest_resume_handle is not None
    assert execution_session.latest_resume_handle.session_handle == "managed-pause-session"
    assert task is not None and task.status == TaskStatus.PAUSED
    assert executor.paused_runs == ["run-managed-pause"]


@pytest.mark.anyio
async def test_session_runtime_native_interaction_resolution_sets_native_resume_strategy():
    session = create_session_runtime(
        "session-6d",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    native = FakeNativeCodexSession()
    session.execution_brain._loop._sessions._live_sessions["exec-session-native"] = native.session
    await session.blackboard.put_task(
        Task(
            task_id="task-native",
            root_task_id="task-native",
            title="Native interaction task",
            goal="Native interaction task",
            status=TaskStatus.WAITING_USER_INPUT,
            preferred_executor="codex",
        )
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-native",
            task_id="task-native",
            execution_session_id="exec-session-native",
            run_id="run-native",
            executor_type="codex",
            kind=InteractionRequestKind.PERMISSION,
            status=InteractionRequestStatus.PENDING,
            prompt="Allow deleting the folder?",
            available_actions=["approve", "deny"],
            opaque={
                "native_response": {
                    "request_id": 3,
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "itemId": "call-1",
                        "command": "rm -rf /tmp/x",
                        "proposedExecpolicyAmendment": ["rm", "-rf", "/tmp/x"],
                    },
                }
            },
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    affected = await session.resolve_interaction_request("ireq-native", action="approve")
    request = await session.blackboard.get_interaction_request("ireq-native")

    assert affected == ["task-native"]
    assert request is not None and request.resume_strategy == "native_response"
    assert native.client.calls


@pytest.mark.anyio
async def test_session_runtime_native_plan_proposal_approval_uses_native_response_without_requeue_echo():
    session = create_session_runtime(
        "session-6d-native-plan",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    native = FakeNativeCodexSession()
    session.execution_brain._loop._sessions._live_sessions["exec-session-native-plan"] = native.session
    await session.blackboard.put_task(
        Task(
            task_id="task-native-plan",
            root_task_id="task-native-plan",
            title="Native plan task",
            goal="Native plan task",
            status=TaskStatus.WAITING_USER_INPUT,
            preferred_executor="codex",
            metadata={
                "plan_mode": True,
                "mode": "proposal_only",
                "persona_id": "forge",
                "target_thread_id": "thread-native-plan",
            },
        )
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-native-plan",
            task_id="task-native-plan",
            execution_session_id="exec-session-native-plan",
            run_id="run-native-plan",
            executor_type="codex",
            kind=InteractionRequestKind.PLAN_PROPOSAL,
            status=InteractionRequestStatus.PENDING,
            prompt="Review the native plan before execution.",
            details={
                "proposal": {
                    "summary": "Review the native plan before execution.",
                    "options": [
                        {
                            "id": "approved_codex_plan",
                            "label": "Run proposed plan",
                            "description": "Native plan payload.",
                        }
                    ],
                }
            },
            available_actions=["approve", "deny"],
            opaque={
                "native_response": {
                    "request_id": 5,
                    "method": "item/plan/requestApproval",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "itemId": "plan-1",
                    },
                }
            },
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    affected = await session.resolve_interaction_request(
        "ireq-native-plan",
        action="approve",
        option_id="approved_codex_plan",
        client_request_id="native-plan-approval-client",
        user_visible_text="Implement it",
    )

    request = await session.blackboard.get_interaction_request("ireq-native-plan")
    task = await session.blackboard.get_task("task-native-plan")
    snapshot = await session.snapshot(sync_imported_codex_threads=False)

    assert affected == ["task-native-plan"]
    assert request is not None and request.resume_strategy == "native_response"
    assert native.client.calls
    assert native.client.calls[0]["answer_text"] == "Run proposed plan"
    assert task is not None
    assert task.status == TaskStatus.WAITING_USER_INPUT
    assert task.metadata["plan_mode"] is True
    assert "client_request_id" not in task.metadata
    assert not [
        turn
        for turn in snapshot.bro_timeline_turns
        if turn.client_request_id == "native-plan-approval-client"
    ]


@pytest.mark.anyio
async def test_session_runtime_native_interaction_resolution_preserves_permissions_payload():
    session = create_session_runtime(
        "session-6e",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    native = FakeNativeCodexSession()
    session.execution_brain._loop._sessions._live_sessions["exec-session-permissions"] = (
        native.session
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-permissions",
            root_task_id="task-permissions",
            title="Permission task",
            goal="Permission task",
            status=TaskStatus.WAITING_USER_INPUT,
            preferred_executor="codex",
        )
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-permissions",
            task_id="task-permissions",
            execution_session_id="exec-session-permissions",
            run_id="run-permissions",
            executor_type="codex",
            kind=InteractionRequestKind.PERMISSION,
            status=InteractionRequestStatus.PENDING,
            prompt="Allow more permissions?",
            available_actions=["approve", "deny"],
            opaque={
                "native_response": {
                    "request_id": 4,
                    "method": "item/permissions/requestApproval",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "permissions": {"fileSystem": {"writeRoots": ["/tmp"]}},
                    },
                }
            },
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    await session.resolve_interaction_request("ireq-permissions", action="approve")

    assert native.client.calls[0]["params"]["permissions"] == {
        "fileSystem": {"writeRoots": ["/tmp"]}
    }


@pytest.mark.anyio
async def test_session_runtime_follow_up_resolution_detaches_live_codex_session():
    session = create_session_runtime(
        "session-6f",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(codex_executor_enabled=True),
    )
    native = FakeNativeCodexSession()
    native.session.thread_id = "thread-follow-up"
    session.execution_brain._loop._sessions._live_sessions["exec-session-follow-up"] = (
        native.session
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-follow-up",
            root_task_id="task-follow-up",
            title="Follow-up task",
            goal="Follow-up task",
            status=TaskStatus.WAITING_USER_INPUT,
            preferred_executor="codex",
        )
    )
    await session.blackboard.put_session(
        RuntimeExecutionSession(
            execution_session_id="exec-session-follow-up",
            task_id="task-follow-up",
            base_executor_id="codex",
            active_run_id="run-follow-up",
            latest_run_id="run-follow-up",
            run_ids=["run-follow-up"],
        )
    )
    await session.blackboard.put_binding(
        SessionBinding(
            task_id="task-follow-up",
            execution_session_id="exec-session-follow-up",
            session_id="codex-session-native",
            claimed_by="worker-session-6f",
            claim_expires_at="2026-04-16T00:10:00+00:00",
            binding_status=BindingStatus.ACTIVE,
        )
    )
    await session.blackboard.put_run(
        ExecutionRun(
            run_id="run-follow-up",
            task_id="task-follow-up",
            execution_session_id="exec-session-follow-up",
            executor_type="codex",
            status=RunStatus.BLOCKED,
            block_reason="Need more input.",
        )
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-follow-up",
            task_id="task-follow-up",
            execution_session_id="exec-session-follow-up",
            run_id="run-follow-up",
            executor_type="codex",
            kind=InteractionRequestKind.QUESTION,
            status=InteractionRequestStatus.PENDING,
            prompt="Need more input.",
            available_actions=["answer"],
            opaque={},
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    await session.resolve_interaction_request(
        "ireq-follow-up",
        action="answer",
        answer_text="Use the same thread.",
    )

    execution_session = await session.blackboard.get_session("exec-session-follow-up")
    binding = await session.blackboard.get_binding("task-follow-up")
    task = await session.blackboard.get_task("task-follow-up")
    summary = await session.blackboard.get_summary("task-follow-up")

    assert execution_session is not None
    assert execution_session.active_run_id is None
    assert execution_session.latest_resume_handle is not None
    assert execution_session.latest_resume_handle.session_handle == "thread-follow-up"
    assert binding is not None and binding.binding_status == BindingStatus.RELEASED
    assert task is not None and task.status == TaskStatus.QUEUED
    assert summary is not None and summary.latest_user_visible_status == "queued"
    assert native.client.closed is True
    assert (
        session.execution_brain.get_live_session("exec-session-follow-up") is None
    )


@pytest.mark.anyio
async def test_session_runtime_plan_proposal_approval_requeues_execution_mode_and_drops_live_session():
    session = create_session_runtime(
        "session-6g",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(codex_executor_enabled=True),
    )
    native = FakeNativeCodexSession()
    native.session.thread_id = "thread-plan-approval"
    session.execution_brain._loop._sessions._live_sessions["exec-session-plan-approval"] = (
        native.session
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-plan-approval",
            root_task_id="task-plan-approval",
            title="Plan approval task",
            goal="Plan approval task",
            status=TaskStatus.WAITING_USER_INPUT,
            preferred_executor="codex",
            metadata={
                "plan_mode": True,
                "mode": "proposal_only",
                "persona_id": "forge",
                "target_thread_id": "thread-plan-approval",
            },
        )
    )
    await session.blackboard.put_session(
        RuntimeExecutionSession(
            execution_session_id="exec-session-plan-approval",
            task_id="task-plan-approval",
            base_executor_id="codex",
            active_run_id="run-plan-approval",
            latest_run_id="run-plan-approval",
            run_ids=["run-plan-approval"],
        )
    )
    await session.blackboard.put_binding(
        SessionBinding(
            task_id="task-plan-approval",
            execution_session_id="exec-session-plan-approval",
            session_id="codex-session-native",
            claimed_by="worker-session-6g",
            claim_expires_at="2026-04-16T00:10:00+00:00",
            binding_status=BindingStatus.ACTIVE,
        )
    )
    await session.blackboard.put_run(
        ExecutionRun(
            run_id="run-plan-approval",
            task_id="task-plan-approval",
            execution_session_id="exec-session-plan-approval",
            executor_type="codex",
            status=RunStatus.BLOCKED,
            block_reason="Review the proposed plan before execution.",
        )
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-plan-approval",
            task_id="task-plan-approval",
            execution_session_id="exec-session-plan-approval",
            run_id="run-plan-approval",
            executor_type="codex",
            kind=InteractionRequestKind.PLAN_PROPOSAL,
            status=InteractionRequestStatus.PENDING,
            prompt="Review the proposed plan before execution.",
            details={
                "proposal": {
                    "summary": "Review the proposed plan before execution.",
                    "options": [
                        {
                            "id": "approved_codex_plan",
                            "label": "Run proposed plan",
                            "description": "Final plan text.",
                        }
                    ],
                }
            },
            available_actions=["approve", "deny"],
            opaque={},
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    affected = await session.resolve_interaction_request(
        "ireq-plan-approval",
        action="approve",
        option_id="approved_codex_plan",
        client_request_id="approval-client-1",
        user_visible_text="Implement it",
    )

    task = await session.blackboard.get_task("task-plan-approval")
    execution_session = await session.blackboard.get_session("exec-session-plan-approval")

    assert affected == ["task-plan-approval"]
    assert native.client.calls == []
    assert native.client.closed is True
    assert session.execution_brain.get_live_session("exec-session-plan-approval") is None
    assert task is not None and task.status == TaskStatus.QUEUED
    assert "plan_mode" not in task.metadata
    assert task.metadata["mode"] == "modify_allowed"
    assert task.metadata["client_request_id"] == "approval-client-1"
    assert task.metadata["user_visible_text"] == "Implement it"
    assert task.metadata["source_kind"] == "bro_detail_plan_approval"
    assert task.latest_instruction is not None
    assert "Proceed with that plan." in task.latest_instruction
    assert execution_session is not None and execution_session.active_run_id is None
    snapshot = await session.snapshot(sync_imported_codex_threads=False)
    approval_turn = next(
        turn for turn in snapshot.bro_timeline_turns if turn.client_request_id == "approval-client-1"
    )
    assert approval_turn.user is not None
    assert approval_turn.user.text == "Implement it"


@pytest.mark.anyio
async def test_session_runtime_plan_proposal_approval_runs_follow_up_to_completion():
    session = create_session_runtime(
        "session-6g-lifecycle",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    executor = PlanProposalLifecycleExecutor()
    session.registry.register(executor)
    await session.blackboard.put_task(
        Task(
            task_id="task-plan-lifecycle",
            root_task_id="task-plan-lifecycle",
            title="Plan lifecycle task",
            goal="Plan lifecycle task",
            status=TaskStatus.QUEUED,
            preferred_executor="plan-lifecycle",
            metadata={"plan_mode": True, "mode": "proposal_only"},
        )
    )

    session.schedule_execution()
    pending_request = await _wait_for_runtime_state(
        lambda: _pending_plan_request(session, "task-plan-lifecycle")
    )

    affected = await session.resolve_interaction_request(
        pending_request.request_id,
        action="approve",
        option_id="approved_codex_plan",
    )
    session.schedule_execution()
    completed_task = await _wait_for_runtime_state(
        lambda: _completed_task(session, "task-plan-lifecycle")
    )

    requests = await session.blackboard.list_interaction_requests()
    execution_sessions = await session.blackboard.list_sessions()
    assert len(execution_sessions) == 1
    assert execution_sessions[0].latest_run_id is not None
    latest_run = await session.blackboard.get_run(execution_sessions[0].latest_run_id)
    assert latest_run is not None

    assert affected == ["task-plan-lifecycle"]
    assert completed_task.status == TaskStatus.COMPLETED
    assert len(executor.calls) == 2
    assert executor.calls[0]["metadata"] == {"plan_mode": True, "mode": "proposal_only"}
    assert executor.calls[1]["metadata"] == {
        "mode": "modify_allowed",
        "user_visible_text": "Run proposed plan",
        "source_kind": "bro_detail_plan_approval",
    }
    assert isinstance(executor.calls[1]["latest_instruction"], str)
    assert "Proceed with that plan." in executor.calls[1]["latest_instruction"]
    assert latest_run.status == RunStatus.COMPLETED
    assert latest_run.output_summary == "Implemented the approved lifecycle plan."
    assert [request.status for request in requests] == [InteractionRequestStatus.APPROVED]
    assert not [
        request
        for request in requests
        if request.kind == InteractionRequestKind.PLAN_PROPOSAL
        and request.status == InteractionRequestStatus.PENDING
    ]


@pytest.mark.anyio
async def test_session_runtime_plan_proposal_approval_defaults_visible_text_to_acknowledgement():
    session = create_session_runtime(
        "session-6g-visible-default",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-plan-visible-default",
            root_task_id="task-plan-visible-default",
            title="Plan visible default task",
            goal="Plan visible default task",
            status=TaskStatus.WAITING_USER_INPUT,
            preferred_executor="codex",
            metadata={
                "plan_mode": True,
                "mode": "proposal_only",
                "persona_id": "forge",
                "target_thread_id": "thread-plan-visible-default",
            },
        )
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-plan-visible-default",
            task_id="task-plan-visible-default",
            execution_session_id="exec-session-plan-visible-default",
            run_id="run-plan-visible-default",
            executor_type="codex",
            kind=InteractionRequestKind.PLAN_PROPOSAL,
            status=InteractionRequestStatus.PENDING,
            prompt="Review the proposed plan before execution.",
            details={
                "proposal": {
                    "summary": "Review the proposed plan before execution.",
                    "options": [
                        {
                            "id": "approved_codex_plan",
                            "label": "Run proposed plan",
                            "description": "Full approved plan payload.",
                        }
                    ],
                }
            },
            available_actions=["approve", "deny"],
            opaque={},
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    affected = await session.resolve_interaction_request(
        "ireq-plan-visible-default",
        action="approve",
        option_id="approved_codex_plan",
        client_request_id="approval-client-default",
    )

    task = await session.blackboard.get_task("task-plan-visible-default")
    assert affected == ["task-plan-visible-default"]
    assert task is not None
    assert task.metadata["user_visible_text"] == "Run proposed plan"
    assert task.latest_instruction is not None
    assert "Run proposed plan" in task.latest_instruction
    assert "Full approved plan payload." not in task.latest_instruction
    assert "Proceed with that plan." in task.latest_instruction

    snapshot = await session.snapshot(sync_imported_codex_threads=False)
    approval_turn = next(
        turn for turn in snapshot.bro_timeline_turns if turn.client_request_id == "approval-client-default"
    )
    assert approval_turn.user is not None
    assert approval_turn.user.text == "Run proposed plan"


@pytest.mark.anyio
async def test_session_runtime_plan_proposal_denial_requeues_planning_mode():
    session = create_session_runtime(
        "session-6h",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-plan-denial",
            root_task_id="task-plan-denial",
            title="Plan denial task",
            goal="Plan denial task",
            status=TaskStatus.WAITING_USER_INPUT,
            preferred_executor="codex",
            metadata={"plan_mode": True, "mode": "proposal_only"},
        )
    )
    await session.blackboard.put_interaction_request(
        InteractionRequest(
            request_id="ireq-plan-denial",
            task_id="task-plan-denial",
            execution_session_id="exec-session-plan-denial",
            run_id="run-plan-denial",
            executor_type="codex",
            kind=InteractionRequestKind.PLAN_PROPOSAL,
            status=InteractionRequestStatus.PENDING,
            prompt="Review the proposed plan before execution.",
            available_actions=["approve", "deny"],
            opaque={},
            created_at="2026-04-06T00:00:00+00:00",
        )
    )

    affected = await session.resolve_interaction_request("ireq-plan-denial", action="deny")

    task = await session.blackboard.get_task("task-plan-denial")

    assert affected == ["task-plan-denial"]
    assert task is not None and task.status == TaskStatus.QUEUED
    assert task.metadata["plan_mode"] is True
    assert task.metadata["mode"] == "proposal_only"
    assert task.latest_instruction is not None
    assert "keep planning" in task.latest_instruction
