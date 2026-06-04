import asyncio
from typing import Any

import pytest

from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.protocol import AgentResumeHandle, BroThread, Persona
from newbro.runtime import Settings
from newbro.runtime.bro_detail_thread_projection import BroDetailThreadProjection
from newbro.runtime.session import create_session_runtime


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
