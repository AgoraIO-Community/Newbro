import pytest

from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.protocol import AgentResumeHandle, BroThread, Persona
from newbro.runtime import Settings
from newbro.runtime.bro_detail_thread_projection import BroDetailThreadProjection
from newbro.runtime.session import create_session_runtime


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
