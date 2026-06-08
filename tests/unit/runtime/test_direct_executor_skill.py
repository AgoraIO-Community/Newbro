from __future__ import annotations

from dataclasses import dataclass

import pytest

from newbro.blackboard.backends import InMemoryBlackboard
from newbro.executors.core.capabilities import ExecutorSkill
from newbro.protocol import AgentResumeHandle, BroThread, ExecutorNodeExecutor, Persona
from newbro.runtime.bro_detail_thread_projection import BroDetailThreadProjection
from newbro.runtime.direct_executor import DirectExecutorInteraction, _resolve_skill_against_catalog
from newbro.runtime.executor_node_manager import ExecutorNodeManager, NodeConnectionState


def _catalog():
    return [ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")]


def test_resolve_returns_ref_when_present():
    ref, dropped = _resolve_skill_against_catalog("doc", _catalog())
    assert ref == {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}
    assert dropped is None


def test_resolve_drops_when_absent():
    ref, dropped = _resolve_skill_against_catalog("flight-search", _catalog())
    assert ref is None
    assert dropped == {"name": "flight-search", "reason": "not_available"}


def test_resolve_none_when_no_skill_requested():
    assert _resolve_skill_against_catalog(None, _catalog()) == (None, None)


def test_resolve_drops_when_disabled():
    catalog = [ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md", enabled=False)]
    ref, dropped = _resolve_skill_against_catalog("doc", catalog)
    assert ref is None
    assert dropped == {"name": "doc", "reason": "not_available"}


# ---------------------------------------------------------------------------
# Integration tests — wiring through submit_text_instruction
# ---------------------------------------------------------------------------


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


async def _publish_snapshot() -> None:
    return None


@dataclass(slots=True)
class Harness:
    store: InMemoryBlackboard
    manager: ExecutorNodeManager
    websocket: FakeWebSocket
    interaction: DirectExecutorInteraction


async def _harness(skills: list[ExecutorSkill] | None = None) -> Harness:
    store = InMemoryBlackboard()
    manager = ExecutorNodeManager(detached_executor_types=("codex",))
    websocket = FakeWebSocket()
    manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=websocket,
        node_id="node-forge",
        connected_at="2026-06-03T00:00:00+00:00",
        executors={
            "codex": ExecutorNodeExecutor(
                executor_type="codex",
                supports_resume=True,
                supports_follow_up=True,
                skills=skills or [],
            )
        },
    )
    await store.put_persona(
        Persona(
            persona_id="forge",
            name="Forge",
            avatar="bro",
            base_prompt="",
            executor_node_id="node-forge",
            bro_detail_session_id="detail-forge",
            status="idle",
        )
    )
    projection = BroDetailThreadProjection(
        session_id="session-1",
        blackboard=store,
        executor_node_manager=manager,
        interaction_manager=None,
        observability=None,
        publish_snapshot=_publish_snapshot,
    )
    projection.imported_codex_threads["codex-thread-1"] = BroThread(
        thread_id="codex-thread-1",
        persona_id="forge",
        title="Thread",
        status="completed",
        has_resume_handle=True,
    )
    projection.imported_codex_thread_resume_handles["codex-thread-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
        opaque={"cwd": "/tmp/work"},
    )
    interaction = DirectExecutorInteraction(
        session_id="session-1",
        blackboard=store,
        executor_node_manager=manager,
        bro_detail_thread_projection=projection,
        publish_snapshot=_publish_snapshot,
        observability=None,
    )
    return Harness(store=store, manager=manager, websocket=websocket, interaction=interaction)


@pytest.mark.anyio
async def test_skill_present_in_catalog_threads_into_instruction_metadata() -> None:
    """When skill_name matches a skill in the node catalog, skill ref is in instruction metadata."""
    skills = [ExecutorSkill(name="doc", display_name="Word Docs", path="/skills/doc/SKILL.md")]
    harness = await _harness(skills=skills)

    instruction = await harness.interaction.submit_text_instruction(
        target_persona_id="forge",
        text="write a doc",
        target_thread_id="codex-thread-1",
        create_new_thread=False,
        workspace_id=None,
        client_request_id="req-1",
        plan_mode=False,
        skill_name="doc",
    )

    assert instruction.metadata["skill"] == {
        "name": "doc",
        "path": "/skills/doc/SKILL.md",
        "display_name": "Word Docs",
    }
    assert "skill_dropped" not in instruction.metadata


@pytest.mark.anyio
async def test_skill_absent_from_catalog_produces_dropped_marker() -> None:
    """When skill_name is not in the catalog, skill_dropped is set and skill ref is absent."""
    skills = [ExecutorSkill(name="doc", display_name="Word Docs", path="/skills/doc/SKILL.md")]
    harness = await _harness(skills=skills)

    instruction = await harness.interaction.submit_text_instruction(
        target_persona_id="forge",
        text="find a flight",
        target_thread_id="codex-thread-1",
        create_new_thread=False,
        workspace_id=None,
        client_request_id="req-2",
        plan_mode=False,
        skill_name="flight-search",
    )

    assert "skill" not in instruction.metadata
    assert instruction.metadata["skill_dropped"] == {
        "name": "flight-search",
        "reason": "not_available",
    }
