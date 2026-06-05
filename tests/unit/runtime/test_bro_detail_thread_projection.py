import asyncio
from pathlib import Path
from typing import Any

import pytest

from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.protocol import AgentResumeHandle, BroThread, ExecutorNodeExecutor, Persona
from newbro.runtime import Settings
from newbro.runtime.bro_detail_thread_projection import BroDetailThreadProjection
from newbro.runtime.executor_node_manager import NodeConnectionState
from newbro.runtime.session import create_session_runtime


def test_projection_module_does_not_import_session_runtime_helpers():
    source = Path("src/newbro/runtime/bro_detail_thread_projection.py").read_text()

    assert "from newbro.runtime.session import" not in source


def test_session_runtime_does_not_proxy_projection_private_methods():
    source = Path("src/newbro/runtime/session.py").read_text()
    proxy_names = [
        "_sync_imported_codex_threads",
        "_open_bro_thread_locked",
        "_should_load_bro_thread_timeline",
        "_load_bro_thread_timeline",
        "_codex_thread_open_needs_import_sync",
        "_replace_selected_codex_thread_subscription",
        "_schedule_selected_codex_thread_subscription",
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
        "_selected_codex_thread_subscription_tasks",
        "_open_bro_thread_locks",
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

    async def fake_request_codex_thread(
        *, node_id: str, thread_id: str, timeout_seconds: float = 8.0
    ) -> dict[str, Any]:
        read_calls.append((node_id, thread_id))
        read_started.set()
        await release_read.wait()
        return {"id": thread_id, "turns": []}

    monkeypatch.setattr(asyncio, "shield", tracking_shield)
    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fake_request_codex_thread)

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

    async def fake_request_codex_thread(
        *, node_id: str, thread_id: str, timeout_seconds: float = 8.0
    ) -> dict[str, Any]:
        read_calls.append((node_id, thread_id))
        read_started.set()
        await release_read.wait()
        return {"id": thread_id, "turns": []}

    monkeypatch.setattr(asyncio, "shield", tracking_shield)
    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fake_request_codex_thread)

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

    async def fake_request_codex_thread(
        *, node_id: str, thread_id: str, timeout_seconds: float = 8.0
    ) -> dict[str, Any]:
        read_calls.append((node_id, thread_id))
        return {"id": thread_id, "turns": []}

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fake_request_codex_thread)

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

    async def fake_request_codex_thread(
        *, node_id: str, thread_id: str, timeout_seconds: float = 8.0
    ) -> dict[str, Any]:
        read_calls.append((node_id, thread_id))
        return {"id": thread_id, "turns": []}

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fake_request_codex_thread)

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
async def test_open_loaded_imported_thread_skips_history_read_but_subscribes(
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

    async def fail_request_codex_thread(**kwargs):
        raise AssertionError("loaded open must not read Codex history again")

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

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread", fail_request_codex_thread)
    monkeypatch.setattr(session.executor_node_manager, "subscribe_codex_thread", fake_subscribe_codex_thread)

    await projection.open_bro_thread(target_persona_id="forge", thread_id="codex-import-1")
    await asyncio.wait_for(subscription_started.wait(), timeout=1.0)
    subscription_release.set()
    task = projection.selected_codex_thread_subscription_tasks.get("forge")
    if task is not None:
        await asyncio.wait_for(task, timeout=1.0)

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
