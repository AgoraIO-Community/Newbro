from __future__ import annotations

from dataclasses import dataclass

import pytest

from newbro.blackboard.backends import InMemoryBlackboard
from newbro.protocol import AgentResumeHandle, BroThread, ExecutorNodeExecutor, Persona
from newbro.runtime.direct_executor import DirectExecutorInteraction
from newbro.runtime.executor_node_manager import NodeConnectionState


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
    manager: object
    websocket: FakeWebSocket
    interaction: DirectExecutorInteraction


async def _harness() -> Harness:
    from newbro.runtime.executor_node_manager import ExecutorNodeManager

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
                supports_audio_instruction=True,
                supports_thread_list=True,
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
    imported_threads = {
        "codex-import-1": BroThread(
            thread_id="codex-import-1",
            persona_id="forge",
            title="Imported",
            status="completed",
            has_resume_handle=True,
        )
    }
    resume_handles = {
        "codex-import-1": AgentResumeHandle(
            executor_id="codex",
            session_handle="native-thread-1",
            opaque={"cwd": "/tmp/work"},
        )
    }
    interaction = DirectExecutorInteraction(
        session_id="session-1",
        blackboard=store,
        executor_node_manager=manager,
        imported_codex_threads=imported_threads,
        imported_codex_thread_resume_handles=resume_handles,
        publish_snapshot=_publish_snapshot,
        observability=None,
    )
    return Harness(store=store, manager=manager, websocket=websocket, interaction=interaction)


@pytest.mark.anyio
async def test_text_to_imported_thread_creates_outbound_turn_without_task() -> None:
    harness = await _harness()

    instruction = await harness.interaction.submit_text_instruction(
        target_persona_id="forge",
        text="continue directly",
        target_thread_id="codex-import-1",
        create_new_thread=False,
        workspace_id=None,
        client_request_id="client-text-1",
        plan_mode=False,
    )

    assert instruction.target_thread_id == "codex-import-1"
    assert await harness.store.list_tasks() == []
    requests = await harness.store.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].client_request_id == "client-text-1"
    assert requests[0].status == "accepted"
    assert harness.websocket.sent[-1]["type"] == "start_codex_turn"
    assert "task_id" not in harness.websocket.sent[-1]
    assert harness.websocket.sent[-1]["latest_resume_handle"]["session_handle"] == "native-thread-1"


@pytest.mark.anyio
async def test_text_requires_explicit_thread_intent() -> None:
    harness = await _harness()

    with pytest.raises(ValueError, match="requires explicit thread intent"):
        await harness.interaction.submit_text_instruction(
            target_persona_id="forge",
            text="ambiguous",
            target_thread_id=None,
            create_new_thread=False,
            workspace_id=None,
            client_request_id=None,
            plan_mode=False,
        )
