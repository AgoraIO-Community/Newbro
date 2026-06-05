from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from newbro.blackboard.backends import InMemoryBlackboard
from newbro.protocol import (
    AgentResumeHandle,
    AudioInstructionTranscribedMessage,
    BroThread,
    ExecutorNodeExecutor,
    Persona,
)
from newbro.runtime.direct_executor import DirectExecutorInteraction
from newbro.runtime.bro_detail_thread_projection import BroDetailThreadProjection
from newbro.runtime.executor_node_manager import NodeConnectionState


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


async def _publish_snapshot() -> None:
    return None


def test_direct_executor_does_not_duplicate_projection_thread_targeting():
    source = Path("src/newbro/runtime/direct_executor.py").read_text()
    duplicate_names = [
        "_resolve_thread_target",
        "_validate_new_codex_thread_workspace",
        "_known_codex_workspaces_for_persona",
        "_find_codex_thread_session_for_persona",
        "_find_direct_task_thread_for_persona",
        "_session_belongs_to_persona",
    ]

    for name in duplicate_names:
        assert f"def {name}" not in source
        assert f"async def {name}" not in source


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
    projection = BroDetailThreadProjection(
        session_id="session-1",
        blackboard=store,
        executor_node_manager=manager,
        interaction_manager=None,
        observability=None,
        publish_snapshot=_publish_snapshot,
    )
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id="forge",
        title="Imported",
        status="completed",
        has_resume_handle=True,
    )
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
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


@pytest.mark.anyio
async def test_audio_to_imported_thread_transcribes_then_starts_outbound_turn() -> None:
    harness = await _harness()

    post_task = asyncio.create_task(
        harness.interaction.submit_audio_instruction(
            target_persona_id="forge",
            target_thread_id="codex-import-1",
            create_new_thread=False,
            workspace_id=None,
            client_request_id="client-audio-1",
            pcm16=b"\x00\x00" * 24,
            mime_type="audio/pcm",
            duration_ms=1,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=24,
        )
    )
    for _ in range(100):
        if harness.websocket.sent:
            break
        await asyncio.sleep(0.01)
    assert harness.websocket.sent[0]["type"] == "transcribe_audio_instruction"
    harness.manager.publish_audio_instruction_transcribed(
        AudioInstructionTranscribedMessage(
            request_id=harness.websocket.sent[0]["request_id"],
            node_id="node-forge",
            executor_type="codex",
            transcript_text="continue from recorded audio",
            language="en",
            duration_seconds=0.1,
        )
    )

    audio = await post_task

    assert audio.metadata["transcript_text"] == "continue from recorded audio"
    assert await harness.store.list_tasks() == []
    requests = await harness.store.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].client_request_id == "client-audio-1"
    assert requests[0].input_modality == "audio"
    assert requests[0].text == "continue from recorded audio"
    assert requests[0].audio_instruction_id == audio.audio_instruction_id
    assert harness.websocket.sent[1]["type"] == "start_codex_turn"
    assert harness.websocket.sent[1]["target_thread_id"] == "codex-import-1"
    assert "task_id" not in harness.websocket.sent[1]
