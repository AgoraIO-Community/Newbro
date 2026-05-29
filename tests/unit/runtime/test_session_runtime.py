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
    RunStatus,
    SessionBinding,
    TaskCommand,
    TaskCommandType,
    TaskExecutionMode,
)
from newbro.executors.core import ExecutorCapabilities, ExecutorEvent, ExecutorEventType, ExecutorSession
from newbro.protocol import Task, TaskStatus
from newbro.runtime import Settings
from newbro.runtime.session import SelectedCodexThreadSubscription, create_session_runtime


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
