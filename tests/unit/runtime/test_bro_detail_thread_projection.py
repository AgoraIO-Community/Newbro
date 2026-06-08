import asyncio
from pathlib import Path

import pytest

from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.protocol import (
    AgentResumeHandle,
    BroThread,
    CodexThreadEventMessage,
    CodexThreadListItem,
    ExecutorNodeExecutor,
    NativeReasoningStep,
    Persona,
)
from newbro.runtime import Settings
from newbro.runtime.bro_detail_thread_projection import (
    BroDetailThreadProjection,
    SelectedCodexThreadSubscription,
)
from newbro.runtime.executor_node_manager import CodexThreadListPage, CodexThreadTurnPage, NodeConnectionState
from newbro.runtime.session import create_session_runtime


def test_projection_module_does_not_import_session_runtime_helpers():
    source = Path("src/newbro/runtime/bro_detail_thread_projection.py").read_text()

    assert "from newbro.runtime.session import" not in source


def test_session_runtime_does_not_proxy_projection_private_methods():
    source = Path("src/newbro/runtime/session.py").read_text()
    proxy_names = [
        "_sync_imported_codex_threads",
        "_subscribe_bro_thread_locked",
        "_should_load_bro_thread_timeline",
        "_load_bro_thread_timeline",
        "_replace_selected_codex_thread_subscription",
        "_stop_selected_codex_thread_subscription",
        "_attach_outbound_new_thread_resume_handle",
        "_client_request_id_for_selected_thread_turn",
        "_apply_codex_thread_timeline_event",
        "_pop_selected_thread_pending_user_turn",
        "_upsert_bro_thread_executor_turn",
        "_resolve_bro_thread_target",
        "_validate_new_codex_thread_workspace",
        "_known_codex_workspaces_for_persona",
        "_find_codex_thread_session_for_persona",
        "_find_direct_task_thread_for_persona",
        "_session_belongs_to_persona",
    ]

    for name in proxy_names:
        assert f"def {name}" not in source
        assert f"async def {name}" not in source


def test_session_runtime_does_not_proxy_projection_state():
    source = Path("src/newbro/runtime/session.py").read_text()
    proxy_names = [
        "_imported_codex_threads",
        "_imported_codex_thread_resume_handles",
        "_codex_thread_public_id_aliases",
        "_codex_thread_sync_lock",
        "_last_codex_thread_sync_monotonic",
        "_selected_codex_thread_subscriptions",
        "_subscribe_bro_thread_locks",
        "_bro_thread_executor_turns",
        "_bro_thread_timeline_status",
        "_bro_thread_timeline_errors",
        "_bro_thread_live_message_deltas",
        "_bro_thread_live_plan_deltas",
        "_bro_thread_live_plan_emitted_text",
        "_bro_thread_goals",
    ]

    for name in proxy_names:
        assert f"def {name}" not in source


async def _projection_harness():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    publish_calls: list[str] = []

    async def publish_snapshot() -> object:
        publish_calls.append("published")
        return await session.snapshot(sync_imported_codex_threads=False)

    projection = BroDetailThreadProjection(
        session_id=session.session_id,
        blackboard=session.blackboard,
        executor_node_manager=session.executor_node_manager,
        interaction_manager=session.interaction_manager,
        observability=session.observability,
        publish_snapshot=publish_snapshot,
    )
    return session, persona, projection, publish_calls


@pytest.mark.anyio
async def test_projection_snapshot_uses_cached_imported_codex_threads_without_sync():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
    )
    projection = BroDetailThreadProjection(
        session_id=session.session_id,
        blackboard=session.blackboard,
        executor_node_manager=session.executor_node_manager,
        interaction_manager=session.interaction_manager,
        observability=session.observability,
        publish_snapshot=lambda: session.publish_snapshot(sync_imported_codex_threads=False),
    )
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id="forge",
        persona_name="Forge",
        executor_id="codex",
        executor_node_id="node-forge",
        title="Imported thread",
        status="completed",
        progress=100,
        task_ids=[],
        active_task_id=None,
        latest_task_id=None,
        has_resume_handle=True,
        diagnostics={"codex_thread_id": "native-thread-1"},
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )
    projection.timeline_status["codex-import-1"] = "loaded"

    snapshot = await projection.snapshot_parts(
        tasks=[],
        sessions=[],
        runs=[],
        summaries=[],
        personas=[persona],
        sync_imported_codex_threads=False,
    )

    assert [thread.thread_id for thread in snapshot.bro_threads] == ["codex-import-1"]
    assert snapshot.bro_threads[0].timeline_status == "loaded"
    assert snapshot.bro_threads[0].diagnostics["codex_thread_id"] == "native-thread-1"
    assert snapshot.bro_timeline_turns == []


@pytest.mark.anyio
async def test_imported_codex_threads_snapshot_uses_first_page_only(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()
    session.executor_node_manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=object(),
        node_id="node-forge",
        connected_at="2026-06-05T00:00:00+00:00",
        executors={"codex": ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)},
    )

    async def fake_request_codex_threads(**kwargs):
        assert kwargs["limit"] == 15
        assert kwargs["cursor"] is None
        return CodexThreadListPage(
            threads=[
                CodexThreadListItem(thread_id="native-1", preview="Task: One", updated_at=1780650000),
            ],
            next_cursor="next-page",
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_threads", fake_request_codex_threads)

    snapshot = await projection.snapshot_parts(
        tasks=[],
        sessions=[],
        runs=[],
        summaries=[],
        personas=[persona],
        sync_imported_codex_threads=True,
    )

    assert [thread.title for thread in snapshot.bro_threads] == ["One"]
    assert projection.imported_codex_thread_page_info[persona.persona_id].next_cursor == "next-page"
    assert projection.imported_codex_thread_page_info[persona.persona_id].has_more is True


@pytest.mark.anyio
async def test_list_bro_thread_page_appends_cached_imported_threads(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()

    async def fake_request_codex_threads(**kwargs):
        assert kwargs["limit"] == 25
        assert kwargs["cursor"] == "next-page"
        return CodexThreadListPage(
            threads=[CodexThreadListItem(thread_id="native-2", preview="Task: Two", updated_at=1780650100)],
            next_cursor=None,
            previous_cursor="first-page",
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_threads", fake_request_codex_threads)
    page = await projection.list_bro_thread_page(
        persona=persona,
        sessions=[],
        limit=25,
        cursor="next-page",
    )

    assert [thread.title for thread in page.threads] == ["Two"]
    assert page.page.next_cursor is None
    assert page.page.previous_cursor == "first-page"
    assert any(
        thread.diagnostics["codex_thread_id"] == "native-2"
        for thread in projection.imported_codex_threads.values()
    )


@pytest.mark.anyio
async def test_list_bro_timeline_page_uses_codex_turn_cursor(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        title="Imported thread",
        has_resume_handle=True,
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )

    async def fake_request_codex_thread_turns(**kwargs):
        assert kwargs["node_id"] == "node-forge"
        assert kwargs["thread_id"] == "native-thread-1"
        assert kwargs["limit"] == 100
        assert kwargs["cursor"] == "older"
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-old",
                    "status": "completed",
                    "items": [
                        {"type": "agentMessage", "id": "agent-old", "text": "Old answer", "phase": "final_answer"}
                    ],
                    "startedAt": 1780650000,
                    "completedAt": 1780650010,
                }
            ],
            next_cursor=None,
            previous_cursor="newer",
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    page = await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
        cursor="older",
        limit=100,
    )

    assert page.thread_id == "codex-import-1"
    assert [turn.executor_turn_id for turn in page.turns] == ["turn-old"]
    assert page.page.next_cursor is None
    assert page.page.previous_cursor == "newer"


@pytest.mark.anyio
async def test_list_bro_timeline_page_returns_thread_summary(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        workspace_id="/tmp/workspace",
        workspace_name="workspace",
        title="Thread summary",
        has_resume_handle=True,
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )

    async def fake_request_codex_thread_turns(**kwargs):
        assert kwargs["thread_id"] == "native-thread-1"
        return CodexThreadTurnPage(thread_id="native-thread-1", turns=[])

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    page = await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
    )

    assert page.thread.thread_id == "codex-import-1"
    assert page.thread.title == "Thread summary"
    assert page.thread.workspace_id == "/tmp/workspace"
    assert page.thread.timeline_status == "loaded"
    assert page.thread.timeline_error is None


@pytest.mark.anyio
async def test_list_bro_timeline_page_requires_loaded_thread_summary():
    _session, persona, projection, _publish_calls = await _projection_harness()
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )

    with pytest.raises(ValueError, match="Thread is not loaded; list thread page first."):
        await projection.list_bro_timeline_page(
            persona=persona,
            public_thread_id="codex-import-1",
            node_id="node-forge",
        )


@pytest.mark.anyio
async def test_concurrent_timeline_loads_share_one_codex_history_request(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, publish_calls = await _projection_harness()
    resume_handle = AgentResumeHandle(executor_id="codex", session_handle="native-thread-1")
    read_started = asyncio.Event()
    release_read = asyncio.Event()
    shared_wait_started = asyncio.Event()
    original_shield = asyncio.shield
    shield_calls = 0
    read_calls: list[tuple[str, str]] = []

    def tracking_shield(awaitable):
        nonlocal shield_calls
        shield_calls += 1
        if shield_calls == 2:
            shared_wait_started.set()
        return original_shield(awaitable)

    async def fake_request_codex_thread_turns(
        *, node_id: str, thread_id: str, limit: int = 100, cursor: str | None = None, timeout_seconds: float = 8.0
    ) -> CodexThreadTurnPage:
        read_calls.append((node_id, thread_id))
        read_started.set()
        await release_read.wait()
        return CodexThreadTurnPage(thread_id=thread_id, turns=[])

    monkeypatch.setattr(asyncio, "shield", tracking_shield)
    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    first: asyncio.Task[None] | None = None
    second: asyncio.Task[None] | None = None
    try:
        first = asyncio.create_task(
            projection.load_bro_thread_timeline(
                persona=persona,
                public_thread_id="codex-import-1",
                node_id="node-forge",
                resume_handle=resume_handle,
            )
        )
        await asyncio.wait_for(read_started.wait(), timeout=1.0)
        assert read_calls == [("node-forge", "native-thread-1")]

        second = asyncio.create_task(
            projection.load_bro_thread_timeline(
                persona=persona,
                public_thread_id="codex-import-1",
                node_id="node-forge",
                resume_handle=resume_handle,
            )
        )
        await asyncio.wait_for(shared_wait_started.wait(), timeout=1.0)
        assert read_calls == [("node-forge", "native-thread-1")]

        release_read.set()
        await asyncio.gather(first, second)
    finally:
        release_read.set()
        created_tasks = [task for task in (first, second) if task is not None]
        if created_tasks:
            await asyncio.gather(*created_tasks, return_exceptions=True)

    assert read_calls == [("node-forge", "native-thread-1")]
    assert projection.timeline_status["codex-import-1"] == "loaded"
    assert projection.timeline_errors.get("codex-import-1") is None
    assert publish_calls == ["published"]


@pytest.mark.anyio
async def test_cancelled_timeline_waiter_does_not_cancel_shared_history_load(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, publish_calls = await _projection_harness()
    resume_handle = AgentResumeHandle(executor_id="codex", session_handle="native-thread-1")
    read_started = asyncio.Event()
    release_read = asyncio.Event()
    shared_wait_started = asyncio.Event()
    original_shield = asyncio.shield
    shield_calls = 0
    read_calls: list[tuple[str, str]] = []

    def tracking_shield(awaitable):
        nonlocal shield_calls
        shield_calls += 1
        if shield_calls == 2:
            shared_wait_started.set()
        return original_shield(awaitable)

    async def fake_request_codex_thread_turns(
        *, node_id: str, thread_id: str, limit: int = 100, cursor: str | None = None, timeout_seconds: float = 8.0
    ) -> CodexThreadTurnPage:
        read_calls.append((node_id, thread_id))
        read_started.set()
        await release_read.wait()
        return CodexThreadTurnPage(thread_id=thread_id, turns=[])

    monkeypatch.setattr(asyncio, "shield", tracking_shield)
    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    first: asyncio.Task[None] | None = None
    second: asyncio.Task[None] | None = None
    try:
        first = asyncio.create_task(
            projection.load_bro_thread_timeline(
                persona=persona,
                public_thread_id="codex-import-1",
                node_id="node-forge",
                resume_handle=resume_handle,
            )
        )
        await asyncio.wait_for(read_started.wait(), timeout=1.0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        load_task = projection.timeline_load_tasks.get("codex-import-1")
        assert load_task is not None
        assert not load_task.done()

        second = asyncio.create_task(
            projection.load_bro_thread_timeline(
                persona=persona,
                public_thread_id="codex-import-1",
                node_id="node-forge",
                resume_handle=resume_handle,
            )
        )
        await asyncio.wait_for(shared_wait_started.wait(), timeout=1.0)
        assert read_calls == [("node-forge", "native-thread-1")]

        release_read.set()
        await second
    finally:
        release_read.set()
        created_tasks = [task for task in (first, second) if task is not None]
        if created_tasks:
            await asyncio.gather(*created_tasks, return_exceptions=True)

    assert read_calls == [("node-forge", "native-thread-1")]
    assert projection.timeline_status["codex-import-1"] == "loaded"
    assert projection.timeline_errors.get("codex-import-1") is None
    assert projection.timeline_load_tasks.get("codex-import-1") is None
    assert publish_calls == ["published"]


@pytest.mark.anyio
async def test_loaded_timeline_load_skips_codex_history_request(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, publish_calls = await _projection_harness()
    projection.timeline_status["codex-import-1"] = "loaded"
    projection.timeline_errors["codex-import-1"] = "old error"
    resume_handle = AgentResumeHandle(executor_id="codex", session_handle="native-thread-1")
    read_calls: list[tuple[str, str]] = []

    async def fake_request_codex_thread_turns(
        *, node_id: str, thread_id: str, limit: int = 100, cursor: str | None = None, timeout_seconds: float = 8.0
    ) -> CodexThreadTurnPage:
        read_calls.append((node_id, thread_id))
        return CodexThreadTurnPage(thread_id=thread_id, turns=[])

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    await projection.load_bro_thread_timeline(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
        resume_handle=resume_handle,
    )

    assert read_calls == []
    assert projection.timeline_status["codex-import-1"] == "loaded"
    assert projection.timeline_errors["codex-import-1"] == "old error"
    assert publish_calls == []


@pytest.mark.anyio
async def test_failed_timeline_load_retries_codex_history_request(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, publish_calls = await _projection_harness()
    projection.timeline_status["codex-import-1"] = "failed"
    projection.timeline_errors["codex-import-1"] = "Timed out reading Codex thread history."
    resume_handle = AgentResumeHandle(executor_id="codex", session_handle="native-thread-1")
    read_calls: list[tuple[str, str]] = []

    async def fake_request_codex_thread_turns(
        *, node_id: str, thread_id: str, limit: int = 100, cursor: str | None = None, timeout_seconds: float = 8.0
    ) -> CodexThreadTurnPage:
        read_calls.append((node_id, thread_id))
        return CodexThreadTurnPage(thread_id=thread_id, turns=[])

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    await projection.load_bro_thread_timeline(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
        resume_handle=resume_handle,
    )

    assert read_calls == [("node-forge", "native-thread-1")]
    assert projection.timeline_status["codex-import-1"] == "loaded"
    assert projection.timeline_errors.get("codex-import-1") is None
    assert publish_calls == ["published"]


@pytest.mark.anyio
async def test_subscribe_loaded_imported_thread_skips_history_read(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, _publish_calls = await _projection_harness()
    session.executor_node_manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=object(),
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
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        workspace_id="/tmp/work",
        workspace_name="work",
        title="Imported thread",
        status="completed",
        progress=100,
        task_ids=[],
        active_task_id=None,
        latest_task_id=None,
        has_resume_handle=True,
        updated_at="2026-05-26T22:00:00+00:00",
        diagnostics={"codex_thread_id": "native-thread-1"},
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
        opaque={"cwd": "/tmp/work"},
    )
    projection.timeline_status["codex-import-1"] = "loaded"
    subscription_calls: list[dict[str, object]] = []
    subscription_started = asyncio.Event()
    subscription_release = asyncio.Event()

    async def fail_sync_imported_codex_threads(**kwargs):
        raise AssertionError("subscribe must not sync imported Codex threads")

    async def fail_load_bro_thread_timeline(**kwargs):
        raise AssertionError("subscribe must not hydrate Codex history")

    async def fail_request_codex_thread_turns(**kwargs):
        raise AssertionError("subscribe must not read Codex history")

    async def fake_subscribe_codex_thread(
        *,
        node_id: str,
        subscription_id: str,
        session_id: str,
        target_persona_id: str,
        target_thread_id: str,
        thread_id: str,
        workspace_id=None,
        timeout_seconds: float = 8.0,
    ) -> None:
        subscription_calls.append(
            {
                "node_id": node_id,
                "subscription_id": subscription_id,
                "session_id": session_id,
                "target_persona_id": target_persona_id,
                "target_thread_id": target_thread_id,
                "thread_id": thread_id,
                "workspace_id": workspace_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        subscription_started.set()
        await subscription_release.wait()

    monkeypatch.setattr(projection, "sync_imported_codex_threads", fail_sync_imported_codex_threads)
    monkeypatch.setattr(projection, "load_bro_thread_timeline", fail_load_bro_thread_timeline)
    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fail_request_codex_thread_turns)
    monkeypatch.setattr(session.executor_node_manager, "subscribe_codex_thread", fake_subscribe_codex_thread)

    response_task = asyncio.create_task(
        projection.subscribe_bro_thread(target_persona_id="forge", thread_id="codex-import-1")
    )
    await asyncio.wait_for(subscription_started.wait(), timeout=1.0)
    subscription_release.set()
    response = await asyncio.wait_for(response_task, timeout=1.0)

    assert response.thread_id == "codex-import-1"
    assert response.persona_id == "forge"
    assert response.subscribed is True
    assert response.timeline_status == "loaded"
    assert response.timeline_error is None
    assert len(subscription_calls) == 1
    call = subscription_calls[0]
    assert isinstance(call["subscription_id"], str)
    assert call["subscription_id"]
    assert call == {
        "node_id": "node-forge",
        "subscription_id": call["subscription_id"],
        "session_id": "session-1",
        "target_persona_id": "forge",
        "target_thread_id": "codex-import-1",
        "thread_id": "native-thread-1",
        "workspace_id": "/tmp/work",
        "timeout_seconds": 2.0,
    }
    selected = projection.selected_codex_thread_subscriptions["forge"]
    assert selected.subscription_id
    assert selected.subscription_id == call["subscription_id"]
    assert selected.persona_id == "forge"
    assert selected.public_thread_id == "codex-import-1"
    assert selected.thread_continuity_key == "codex-import-1"
    assert selected.node_id == "node-forge"
    assert selected.codex_thread_id == "native-thread-1"
    assert selected.resume_handle == projection.imported_codex_thread_resume_handles["codex-import-1"]
    assert selected.fallback_timestamp == "2026-05-26T22:00:00+00:00"


@pytest.mark.anyio
async def test_subscribe_unknown_imported_thread_requires_list_page_first(
    monkeypatch: pytest.MonkeyPatch,
):
    session, _persona, projection, _publish_calls = await _projection_harness()
    session.executor_node_manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=object(),
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

    async def fail_sync_imported_codex_threads(**kwargs):
        raise AssertionError("subscribe must not sync imported Codex threads")

    async def fail_request_codex_thread_turns(**kwargs):
        raise AssertionError("subscribe must not read Codex history")

    monkeypatch.setattr(projection, "sync_imported_codex_threads", fail_sync_imported_codex_threads)
    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fail_request_codex_thread_turns)

    with pytest.raises(ValueError, match="Thread is not loaded; list thread page first."):
        await projection.subscribe_bro_thread(target_persona_id="forge", thread_id="codex-import-missing")


@pytest.mark.anyio
async def test_unsubscribe_waits_for_in_flight_subscribe_before_stopping(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, _publish_calls = await _projection_harness()
    session.executor_node_manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=object(),
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
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        title="Imported thread",
        has_resume_handle=True,
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )
    subscribe_started = asyncio.Event()
    subscribe_release = asyncio.Event()
    unsubscribe_calls: list[tuple[str, str]] = []

    async def fake_subscribe_codex_thread(**_kwargs):
        subscribe_started.set()
        await subscribe_release.wait()

    async def fake_unsubscribe_codex_thread(*, subscription_id: str, thread_id: str, **_kwargs):
        unsubscribe_calls.append((subscription_id, thread_id))

    monkeypatch.setattr(session.executor_node_manager, "subscribe_codex_thread", fake_subscribe_codex_thread)
    monkeypatch.setattr(session.executor_node_manager, "unsubscribe_codex_thread", fake_unsubscribe_codex_thread)

    subscribe_task = asyncio.create_task(
        projection.subscribe_bro_thread(target_persona_id="forge", thread_id="codex-import-1")
    )
    await asyncio.wait_for(subscribe_started.wait(), timeout=1.0)
    unsubscribe_task = asyncio.create_task(
        projection.unsubscribe_bro_thread(target_persona_id="forge", thread_id="codex-import-1")
    )
    await asyncio.sleep(0)

    assert unsubscribe_calls == []

    subscribe_release.set()
    subscribe_response = await asyncio.wait_for(subscribe_task, timeout=1.0)
    unsubscribe_response = await asyncio.wait_for(unsubscribe_task, timeout=1.0)

    assert subscribe_response.subscribed is True
    assert unsubscribe_response.subscribed is False
    assert len(unsubscribe_calls) == 1
    assert unsubscribe_calls[0][0]
    assert unsubscribe_calls[0][1] == "native-thread-1"
    assert "forge" not in projection.selected_codex_thread_subscriptions


@pytest.mark.anyio
async def test_subscribe_failure_cleans_up_provisional_executor_subscription(
    monkeypatch: pytest.MonkeyPatch,
):
    session, persona, projection, _publish_calls = await _projection_harness()
    session.executor_node_manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=object(),
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
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        title="Imported thread",
        has_resume_handle=True,
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )
    subscribe_calls: list[str] = []
    unsubscribe_calls: list[tuple[str, str]] = []

    async def fake_subscribe_codex_thread(*, subscription_id: str, **_kwargs):
        subscribe_calls.append(subscription_id)
        raise TimeoutError("Timed out subscribing to Codex thread updates.")

    async def fake_unsubscribe_codex_thread(*, subscription_id: str, thread_id: str, **_kwargs):
        unsubscribe_calls.append((subscription_id, thread_id))

    monkeypatch.setattr(session.executor_node_manager, "subscribe_codex_thread", fake_subscribe_codex_thread)
    monkeypatch.setattr(session.executor_node_manager, "unsubscribe_codex_thread", fake_unsubscribe_codex_thread)

    with pytest.raises(TimeoutError, match="Timed out subscribing"):
        await projection.subscribe_bro_thread(target_persona_id="forge", thread_id="codex-import-1")

    assert subscribe_calls
    assert unsubscribe_calls == [(subscribe_calls[0], "native-thread-1")]
    assert "forge" not in projection.selected_codex_thread_subscriptions


def _register_imported_codex_thread(projection: BroDetailThreadProjection, persona: Persona) -> None:
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        title="Imported thread",
        has_resume_handle=True,
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )


@pytest.mark.anyio
async def test_in_flight_turn_commentary_does_not_fill_answer_slot(monkeypatch: pytest.MonkeyPatch):
    # An in-flight codex turn that has only streamed commentary (no final_answer
    # item yet) must NOT place that commentary text in the assistant answer slot
    # when its history is reloaded — e.g. after a page refresh. Otherwise the
    # commentary renders below the reasoning steps (answer region) and freezes.
    session, persona, projection, _publish_calls = await _projection_harness()
    _register_imported_codex_thread(projection, persona)

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "userMessage", "id": "u1", "text": "Do the thing"},
                        {"type": "agentMessage", "id": "c1", "text": "Reading the files", "phase": "commentary"},
                        {"type": "agentMessage", "id": "c2", "text": "Now editing", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    page = await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
    )

    turn = next(t for t in page.turns if t.executor_turn_id == "turn-live")
    assert turn.status == "running"
    assert turn.assistant is None, "commentary must not fill the answer slot for an in-flight turn"


@pytest.mark.anyio
async def test_final_answer_still_fills_answer_slot(monkeypatch: pytest.MonkeyPatch):
    # Regression guard: a completed turn whose final agentMessage is phase
    # final_answer must still settle into the assistant answer slot.
    session, persona, projection, _publish_calls = await _projection_harness()
    _register_imported_codex_thread(projection, persona)

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-done",
                    "status": "completed",
                    "items": [
                        {"type": "userMessage", "id": "u1", "text": "Do it"},
                        {"type": "agentMessage", "id": "c1", "text": "Working on it", "phase": "commentary"},
                        {"type": "agentMessage", "id": "a1", "text": "Done — here is the result", "phase": "final_answer"},
                    ],
                    "startedAt": 1780650000,
                    "completedAt": 1780650010,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    page = await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
    )

    turn = next(t for t in page.turns if t.executor_turn_id == "turn-done")
    assert turn.status == "completed"
    assert turn.assistant is not None
    assert turn.assistant.text == "Done — here is the result"


@pytest.mark.anyio
async def test_resubscribe_commentary_delta_without_item_started_stays_live(monkeypatch: pytest.MonkeyPatch):
    # After a refresh the thread is re-subscribed mid-turn: the codex node resumes
    # streaming the in-flight commentary item with deltas only — the phase-bearing
    # item/started is in the past and is not replayed. Loading the timeline first
    # must seed the item phase so that those phase-less deltas are still recognised
    # as commentary and never fill the answer slot.
    session, persona, projection, _publish_calls = await _projection_harness()
    _register_imported_codex_thread(projection, persona)

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "Reading", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
    )

    projection.selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="sub-1",
        persona_id="forge",
        public_thread_id="codex-import-1",
        thread_continuity_key="codex-import-1",
        node_id="node-forge",
        codex_thread_id="native-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="native-thread-1"),
    )

    await projection.handle_codex_thread_event(
        CodexThreadEventMessage.model_validate(
            {
                "subscription_id": "sub-1",
                "node_id": "node-forge",
                "session_id": session.session_id,
                "target_persona_id": "forge",
                "target_thread_id": "codex-import-1",
                "thread_id": "native-thread-1",
                "method": "item/agentMessage/delta",
                "params": {"turnId": "turn-live", "itemId": "c1", "delta": " the files"},
            }
        )
    )

    turns = projection.bro_thread_executor_turns.get("codex-import-1") or []
    turn = next(t for t in turns if t.executor_turn_id == "turn-live")
    assert turn.assistant is None, "commentary delta after re-subscribe must not fill the answer slot"


@pytest.mark.anyio
async def test_in_flight_commentary_seeds_native_reasoning(monkeypatch: pytest.MonkeyPatch):
    # An in-flight turn opened from codex history has no answer (commentary is kept
    # out of the answer slot) and no live reasoning stream on a fresh page. Its
    # commentary must be seeded as native reasoning so the bubble renders the
    # reasoning line instead of a perpetual "connecting" shimmer.
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    projection = session._bro_detail_thread_projection()
    _register_imported_codex_thread(projection, persona)

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "Reading the files", "phase": "commentary"},
                        {"type": "agentMessage", "id": "c2", "text": "Now editing", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
    )

    recent = session._recent_native_turn_reasoning()
    key = "codex::native-thread-1::turn-live"
    assert key in recent, f"native reasoning was not seeded; keys={list(recent)}"
    assert [step.text for step in recent[key]] == ["Reading the files", "Now editing"]


@pytest.mark.anyio
async def test_completed_turn_does_not_seed_native_reasoning(monkeypatch: pytest.MonkeyPatch):
    # Completed turns settle on their final answer and must not gain synthetic
    # reasoning steps from history seeding.
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    projection = session._bro_detail_thread_projection()
    _register_imported_codex_thread(projection, persona)

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-done",
                    "status": "completed",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "Working", "phase": "commentary"},
                        {"type": "agentMessage", "id": "a1", "text": "Done", "phase": "final_answer"},
                    ],
                    "startedAt": 1780650000,
                    "completedAt": 1780650010,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
    )

    assert session._recent_native_turn_reasoning() == {}


@pytest.mark.anyio
async def test_seeded_in_flight_turn_settles_final_answer_keeping_commentary_reasoning(
    monkeypatch: pytest.MonkeyPatch,
):
    # Load an in-flight commentary turn (seeds native reasoning, assistant empty),
    # then a final_answer arrives over the subscription: the answer settles into the
    # assistant slot while the commentary remains a reasoning step (not duplicated).
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    projection = session._bro_detail_thread_projection()
    _register_imported_codex_thread(projection, persona)

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "Reading", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )

    projection.selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="sub-1",
        persona_id="forge",
        public_thread_id="codex-import-1",
        thread_continuity_key="codex-import-1",
        node_id="node-forge",
        codex_thread_id="native-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="native-thread-1"),
    )

    await projection.handle_codex_thread_event(
        CodexThreadEventMessage.model_validate(
            {
                "subscription_id": "sub-1",
                "node_id": "node-forge",
                "session_id": session.session_id,
                "target_persona_id": "forge",
                "target_thread_id": "codex-import-1",
                "thread_id": "native-thread-1",
                "method": "item/completed",
                "params": {
                    "turnId": "turn-live",
                    "item": {
                        "type": "agentMessage",
                        "id": "a1",
                        "text": "Done",
                        "phase": "final_answer",
                        "status": "completed",
                    },
                },
            }
        )
    )

    turns = projection.bro_thread_executor_turns.get("codex-import-1") or []
    turn = next(t for t in turns if t.executor_turn_id == "turn-live")
    assert turn.assistant is not None and turn.assistant.text == "Done"

    recent = session._recent_native_turn_reasoning()
    assert recent.get("codex::native-thread-1::turn-live") is not None


@pytest.mark.anyio
async def test_list_bro_timeline_page_publishes_only_when_it_seeds_reasoning(
    monkeypatch: pytest.MonkeyPatch,
):
    # list_bro_timeline_page must publish a snapshot when it seeds in-flight commentary
    # (so a refreshed client receives it promptly) and must NOT publish when there is
    # nothing to seed.
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)

    publish_calls: list[str] = []

    async def counting_publish() -> object:
        publish_calls.append("published")
        return None

    seeded_calls: list[tuple[str, str, str]] = []

    def record_history(executor_id, executor_thread_id, executor_turn_id, steps):
        seeded_calls.append((executor_id, executor_thread_id, executor_turn_id))

    projection = BroDetailThreadProjection(
        session_id=session.session_id,
        blackboard=session.blackboard,
        executor_node_manager=session.executor_node_manager,
        interaction_manager=session.interaction_manager,
        observability=session.observability,
        publish_snapshot=counting_publish,
        record_history_native_reasoning=record_history,
    )
    _register_imported_codex_thread(projection, persona)

    async def in_flight_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "Reading", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", in_flight_turns)
    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )
    assert seeded_calls == [("codex", "native-thread-1", "turn-live")]
    assert len(publish_calls) == 1

    async def completed_only_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-done",
                    "status": "completed",
                    "items": [
                        {"type": "agentMessage", "id": "a1", "text": "Done", "phase": "final_answer"},
                    ],
                    "startedAt": 1780650000,
                    "completedAt": 1780650010,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", completed_only_turns)
    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )
    # No new seed -> no new publish.
    assert len(publish_calls) == 1


@pytest.mark.anyio
async def test_history_seeding_does_not_clobber_live_native_reasoning(
    monkeypatch: pytest.MonkeyPatch,
):
    # If the live native-reasoning store already holds a turn (in-session dispatch),
    # loading history must NOT overwrite it with the (possibly staler) history items.
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    projection = session._bro_detail_thread_projection()
    _register_imported_codex_thread(projection, persona)

    key = "codex::native-thread-1::turn-live"
    session._native_turn_reasoning[key] = [
        NativeReasoningStep(item_id="live", text="LIVE step", kind="progress", created_at="t9"),
    ]

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "HISTORY step", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)
    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )

    assert [s.text for s in session._native_turn_reasoning[key]] == ["LIVE step"]
