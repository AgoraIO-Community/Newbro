from __future__ import annotations

import asyncio
import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import PublicAuthStore
from newbro.blackboard.store import BlackboardWriteEvent, BlackboardWriteKind
from newbro.protocol import (
    AgentResumeHandle,
    AudioInstructionTranscribedMessage,
    BroThread,
    ExecutionRun,
    ExecutionSession,
    ExecutorNodeExecutor,
    Persona,
    RunStatus,
    Task,
    TaskStatus,
)
from newbro.runtime.executor_node_manager import NodeConnectionState


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


async def _redeem(client: AsyncClient, app, code: str = "invite-audio") -> None:
    await app.state.public_auth_store.create_invite(code)
    response = await client.post("/api/auth/invites/redeem", json={"code": code})
    assert response.status_code == 200


async def _put_connected_audio_forge(runtime_session, manager, websocket: FakeWebSocket | None = None) -> None:
    manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=websocket or FakeWebSocket(),
        node_id="node-forge",
        connected_at="2026-05-26T00:00:00+00:00",
        executors={
            "codex": ExecutorNodeExecutor(
                executor_type="codex",
                supports_resume=True,
                supports_follow_up=True,
                supports_audio_instruction=True,
            )
        },
    )
    await runtime_session.blackboard.put_persona(
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


@pytest.mark.anyio
async def test_executor_audio_instruction_requires_explicit_thread_intent(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-explicit")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_audio_forge(runtime_session, app.state.runtime_container.executor_node_manager)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "duration_ms": 1,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 24,
            },
            content=b"\x00\x00" * 24,
            headers={"Content-Type": "audio/pcm"},
        )

    assert response.status_code == 409
    assert "requires explicit thread intent" in response.text


@pytest.mark.anyio
async def test_executor_audio_instruction_rejects_thread_target_contradiction(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-contradiction")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_audio_forge(runtime_session, app.state.runtime_container.executor_node_manager)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "target_thread_id": "thread-existing",
                "create_new_thread": True,
                "duration_ms": 1,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 24,
            },
            content=b"\x00\x00" * 24,
            headers={"Content-Type": "audio/pcm"},
        )

    assert response.status_code == 409
    assert "cannot target an existing thread and create a new thread" in response.text


@pytest.mark.anyio
async def test_direct_ptt_selected_imported_thread_does_not_create_task_before_executor_acceptance(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-import-outbound")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_audio_forge(runtime_session, app.state.runtime_container.executor_node_manager, websocket)

        runtime_session._bro_detail_thread_projection().imported_codex_threads["codex-import-audio-1"] = BroThread(
            thread_id="codex-import-audio-1",
            persona_id="forge",
            title="Imported",
            status="completed",
            has_resume_handle=True,
        )
        runtime_session._bro_detail_thread_projection().imported_codex_thread_resume_handles["codex-import-audio-1"] = AgentResumeHandle(
            executor_id="codex",
            session_handle="native-thread-1",
            opaque={"cwd": "/tmp/work"},
        )

        post_task = asyncio.create_task(
            client.post(
                f"/api/sessions/{session_id}/executor-audio-instructions",
                params={
                    "target_persona_id": "forge",
                    "target_thread_id": "codex-import-audio-1",
                    "client_request_id": "client-audio-1",
                    "duration_ms": 1,
                    "sample_rate": 24000,
                    "num_channels": 1,
                    "samples_per_channel": 24,
                },
                content=b"\x00\x00" * 24,
                headers={"Content-Type": "audio/pcm"},
            )
        )
        for _ in range(100):
            if websocket.sent:
                break
            await asyncio.sleep(0.01)
        assert websocket.sent[0]["type"] == "transcribe_audio_instruction"
        app.state.runtime_container.executor_node_manager.publish_audio_instruction_transcribed(
            AudioInstructionTranscribedMessage(
                request_id=websocket.sent[0]["request_id"],
                node_id="node-forge",
                executor_type="codex",
                transcript_text="continue from recorded audio",
                language="en",
                duration_seconds=0.1,
            )
        )
        response = await post_task

    assert response.status_code == 200
    assert await runtime_session.blackboard.list_tasks() == []
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].client_request_id == "client-audio-1"
    assert requests[0].input_modality == "audio"
    assert requests[0].audio_instruction_id == response.json()["audio_instruction_id"]
    assert requests[0].text == "continue from recorded audio"
    assert requests[0].status == "accepted"
    assert websocket.sent[1]["type"] == "start_codex_turn"
    assert websocket.sent[1]["target_thread_id"] == "codex-import-audio-1"
    assert websocket.sent[1]["latest_resume_handle"]["session_handle"] == "native-thread-1"
    assert websocket.sent[1]["metadata"]["source_audio_instruction_id"] == response.json()["audio_instruction_id"]
    assert "task_id" not in websocket.sent[1]
    assert "run_id" not in websocket.sent[1]
    assert "execution_session_id" not in websocket.sent[1]


@pytest.mark.anyio
async def test_executor_audio_instruction_accepts_valid_pcm_payload_over_default_websocket_limit(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    sample_count = 600_000
    pcm16 = b"\x00\x00" * sample_count
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-large")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_audio_forge(runtime_session, app.state.runtime_container.executor_node_manager, websocket)

        runtime_session._bro_detail_thread_projection().imported_codex_threads["codex-import-audio-large"] = BroThread(
            thread_id="codex-import-audio-large",
            persona_id="forge",
            title="Imported",
            status="completed",
            has_resume_handle=True,
        )
        runtime_session._bro_detail_thread_projection().imported_codex_thread_resume_handles["codex-import-audio-large"] = AgentResumeHandle(
            executor_id="codex",
            session_handle="native-thread-large",
            opaque={"cwd": "/tmp/work"},
        )

        post_task = asyncio.create_task(
            client.post(
                f"/api/sessions/{session_id}/executor-audio-instructions",
                params={
                    "target_persona_id": "forge",
                    "target_thread_id": "codex-import-audio-large",
                    "duration_ms": round((sample_count / 24000) * 1000),
                    "sample_rate": 24000,
                    "num_channels": 1,
                    "samples_per_channel": sample_count,
                },
                content=pcm16,
                headers={"Content-Type": "audio/pcm"},
            )
        )
        for _ in range(100):
            if websocket.sent:
                break
            await asyncio.sleep(0.01)
        assert websocket.sent[0]["type"] == "transcribe_audio_instruction"
        assert len(json.dumps(websocket.sent[0])) > 1_048_576
        app.state.runtime_container.executor_node_manager.publish_audio_instruction_transcribed(
            AudioInstructionTranscribedMessage(
                request_id=websocket.sent[0]["request_id"],
                node_id="node-forge",
                executor_type="codex",
                transcript_text="continue from large audio",
                language="en",
                duration_seconds=25.0,
            )
        )
        response = await post_task

    assert response.status_code == 200
    assert websocket.sent[1]["type"] == "start_codex_turn"


@pytest.mark.anyio
async def test_executor_audio_upload_rejects_unsupported_mime_type(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "duration_ms": 1000,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 24000,
            },
            content=b"\x00\x00",
            headers={"Content-Type": "audio/webm"},
        )

    assert response.status_code == 415


@pytest.mark.anyio
async def test_executor_audio_upload_rejects_pcm_body_size_mismatch(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-mismatch")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "duration_ms": 1,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 24,
            },
            content=b"\x00\x00" * 23,
            headers={"Content-Type": "audio/pcm"},
        )

    assert response.status_code == 400
    assert "Audio PCM byte length does not match sample metadata" in response.text


@pytest.mark.anyio
async def test_executor_audio_upload_rejects_without_active_codex_session(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await runtime_session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id="node-forge",
                bro_detail_session_id="detail-forge",
            )
        )
        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "duration_ms": 1,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 2,
            },
            content=b"\x00\x00\x00\x00",
            headers={"Content-Type": "audio/pcm"},
        )

    assert response.status_code == 409
    assert "Codex executor node is not connected" in response.text


@pytest.mark.anyio
async def test_executor_audio_upload_rejects_connected_codex_without_audio_support(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        manager = app.state.runtime_container.executor_node_manager
        manager._connections_by_node["node-forge"] = NodeConnectionState(
            websocket=object(),
            node_id="node-forge",
            connected_at="2026-05-26T00:00:00+00:00",
            executors={
                "codex": ExecutorNodeExecutor(
                    executor_type="codex",
                    supports_resume=True,
                    supports_follow_up=True,
                    supports_audio_instruction=False,
                )
            },
        )
        await runtime_session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id="node-forge",
                bro_detail_session_id="detail-forge",
                status="busy",
            )
        )
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-1",
                root_task_id="task-1",
                title="Active task",
                goal="Keep working",
                status=TaskStatus.RUNNING,
                preferred_executor="codex",
                metadata={"persona_id": "forge"},
            )
        )
        await runtime_session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-1",
                task_id="task-1",
                base_executor_id="codex",
                executor_node_id="node-forge",
                active_run_id="run-1",
                latest_run_id="run-1",
                run_ids=["run-1"],
            )
        )
        await runtime_session.blackboard.put_run(
            ExecutionRun(
                run_id="run-1",
                task_id="task-1",
                execution_session_id="exec-1",
                executor_type="codex",
                status=RunStatus.RUNNING,
            )
        )
        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "duration_ms": 1,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 2,
            },
            content=b"\x00\x00\x00\x00",
            headers={"Content-Type": "audio/pcm"},
        )

    assert response.status_code == 409
    assert "does not support audio transcription instructions" in response.text


@pytest.mark.anyio
async def test_active_codex_audio_session_allows_continuation_run_task(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await runtime_session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id="node-forge",
                bro_detail_session_id="detail-forge",
                status="busy",
            )
        )
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-current",
                root_task_id="task-current",
                title="Current task",
                goal="Keep working",
                status=TaskStatus.RUNNING,
                preferred_executor="codex",
                metadata={"persona_id": "forge"},
            )
        )
        await runtime_session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-1",
                task_id="task-previous",
                base_executor_id="codex",
                executor_node_id="node-forge",
                active_run_id="run-current",
                latest_run_id="run-current",
                run_ids=["run-previous", "run-current"],
            )
        )
        await runtime_session.blackboard.put_run(
            ExecutionRun(
                run_id="run-current",
                task_id="task-current",
                execution_session_id="exec-1",
                executor_type="codex",
                status=RunStatus.RUNNING,
            )
        )

        execution_session, run = await runtime_session._active_codex_execution_for_persona(
            "forge",
            target_thread_id="exec-1",
        )

    assert execution_session is not None
    assert execution_session.execution_session_id == "exec-1"
    assert run is not None
    assert run.run_id == "run-current"


@pytest.mark.anyio
async def test_executor_audio_instruction_dispatches_to_executor_without_message_route(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        manager = app.state.runtime_container.executor_node_manager
        manager._connections_by_node["node-forge"] = NodeConnectionState(
            websocket=websocket,
            node_id="node-forge",
            connected_at="2026-05-26T00:00:00+00:00",
            executors={
                "codex": ExecutorNodeExecutor(
                    executor_type="codex",
                    supports_resume=True,
                    supports_follow_up=True,
                    supports_audio_instruction=True,
                )
            },
        )
        await runtime_session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id="node-forge",
                bro_detail_session_id="detail-forge",
                status="busy",
            )
        )
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-current",
                root_task_id="task-current",
                title="Current task",
                goal="Keep working",
                status=TaskStatus.RUNNING,
                preferred_executor="codex",
                metadata={"persona_id": "forge"},
            )
        )
        await runtime_session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-1",
                task_id="task-current",
                base_executor_id="codex",
                executor_node_id="node-forge",
                active_run_id="run-current",
                latest_run_id="run-current",
                run_ids=["run-current"],
            )
        )
        await runtime_session.blackboard.put_run(
            ExecutionRun(
                run_id="run-current",
                task_id="task-current",
                execution_session_id="exec-1",
                executor_type="codex",
                status=RunStatus.RUNNING,
            )
        )

        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "target_thread_id": "exec-1",
                "duration_ms": 1,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 24,
            },
            content=b"\x00\x00" * 24,
            headers={"Content-Type": "audio/pcm"},
        )
        run = await runtime_session.blackboard.get_run("run-current")
        assert run is not None
        await runtime_session.blackboard.put_run(
            run.model_copy(update={"status": RunStatus.COMPLETED, "output_summary": "Done from audio instruction."})
        )
        await runtime_session.notification_manager.handle_blackboard_write(
            BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-current")
        )
        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert conversation["conversation_history"] == []
    assert await runtime_session.blackboard.list_notification_candidates() == []
    task = await runtime_session.blackboard.get_task("task-current")
    assert task is not None
    assert task.metadata["suppress_communication_notifications"] is True
    assert task.metadata["direct_executor_input_sources"] == ["bro_detail_ptt"]
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["type"] == "dispatch_audio_instruction"
    assert websocket.sent[0]["task_id"] == "task-current"
    assert websocket.sent[0]["audio"]["target_persona_id"] == "forge"
    assert "artifact_path" not in websocket.sent[0]["audio"]
    assert base64.b64decode(websocket.sent[0]["audio"]["pcm16_b64"], validate=True) == b"\x00\x00" * 24


@pytest.mark.anyio
async def test_executor_audio_instruction_starts_outbound_turn_for_connected_idle_bro(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-idle")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        manager = app.state.runtime_container.executor_node_manager
        manager._connections_by_node["node-forge"] = NodeConnectionState(
            websocket=websocket,
            node_id="node-forge",
            connected_at="2026-05-26T00:00:00+00:00",
            executors={
                "codex": ExecutorNodeExecutor(
                    executor_type="codex",
                    supports_resume=True,
                    supports_follow_up=True,
                    supports_audio_instruction=True,
                )
            },
        )
        await runtime_session.blackboard.put_persona(
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
        runtime_session._bro_detail_thread_projection().imported_codex_threads["workspace-thread"] = BroThread(
            thread_id="workspace-thread",
            persona_id="forge",
            persona_name="Forge",
            executor_id="codex",
            executor_node_id="node-forge",
            workspace_id="/tmp/work",
            workspace_name="work",
            title="Known workspace",
        )
        scheduled = False

        def mark_scheduled(self) -> None:
            nonlocal scheduled
            scheduled = True

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)

        post_task = asyncio.create_task(
            client.post(
                f"/api/sessions/{session_id}/executor-audio-instructions",
                params={
                    "target_persona_id": "forge",
                    "create_new_thread": True,
                    "workspace_id": "/tmp/work",
                    "duration_ms": 1,
                    "sample_rate": 24000,
                    "num_channels": 1,
                    "samples_per_channel": 24,
                },
                content=b"\x00\x00" * 24,
                headers={"Content-Type": "audio/pcm"},
            )
        )
        for _ in range(100):
            if websocket.sent:
                break
            await asyncio.sleep(0.01)
        assert len(websocket.sent) == 1
        assert websocket.sent[0]["type"] == "transcribe_audio_instruction"
        assert "artifact_path" not in websocket.sent[0]["audio"]
        assert base64.b64decode(websocket.sent[0]["audio"]["pcm16_b64"], validate=True) == b"\x00\x00" * 24
        manager.publish_audio_instruction_transcribed(
            AudioInstructionTranscribedMessage(
                request_id=websocket.sent[0]["request_id"],
                node_id="node-forge",
                executor_type="codex",
                transcript_text="start from recorded audio",
                language="en",
                duration_seconds=0.1,
                metadata={"whisper_model": "fake"},
            )
        )
        response = await post_task
        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["transcript_text"] == "start from recorded audio"
    assert conversation["conversation_history"] == []
    assert not scheduled
    assert len(websocket.sent) == 2
    assert websocket.sent[1]["type"] == "start_codex_turn"
    assert websocket.sent[1]["create_new_thread"] is True
    assert websocket.sent[1]["workspace_id"] == "/tmp/work"
    assert websocket.sent[1]["instruction"]["source_audio_instruction_id"] == response.json()["audio_instruction_id"]
    assert "task_id" not in websocket.sent[1]
    assert "run_id" not in websocket.sent[1]
    assert "execution_session_id" not in websocket.sent[1]
    tasks = await runtime_session.blackboard.list_tasks()
    assert tasks == []
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].input_modality == "audio"
    assert requests[0].audio_instruction_id == response.json()["audio_instruction_id"]
    assert requests[0].target_thread_id == response.json()["target_thread_id"]
    assert requests[0].workspace_id == "/tmp/work"
    assert requests[0].text == "start from recorded audio"
    assert requests[0].status == "accepted"
    assert not any(thread["thread_id"] == response.json()["target_thread_id"] for thread in snapshot["bro_threads"])


@pytest.mark.anyio
async def test_executor_audio_create_new_thread_ignores_active_thread_and_starts_outbound_turn(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-new-thread")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        manager = app.state.runtime_container.executor_node_manager
        await _put_connected_audio_forge(runtime_session, manager, websocket)
        await runtime_session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id="node-forge",
                bro_detail_session_id="detail-forge",
                status="busy",
            )
        )
        runtime_session._bro_detail_thread_projection().imported_codex_threads["workspace-thread"] = BroThread(
            thread_id="workspace-thread",
            persona_id="forge",
            persona_name="Forge",
            executor_id="codex",
            executor_node_id="node-forge",
            workspace_id="/tmp/work",
            workspace_name="work",
            title="Known workspace",
        )
        old_metadata = {
            "persona_id": "forge",
            "bro_thread_id": "exec-old",
            "target_thread_id": "exec-old",
        }
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-active",
                root_task_id="task-active",
                title="Active old task",
                goal="Keep the old thread running",
                status=TaskStatus.RUNNING,
                preferred_executor="codex",
                metadata=dict(old_metadata),
            )
        )
        await runtime_session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-old",
                task_id="task-active",
                base_executor_id="codex",
                executor_node_id="node-forge",
                continuity_key="exec-old",
                active_run_id="run-active",
                latest_run_id="run-active",
                run_ids=["run-active"],
            )
        )
        await runtime_session.blackboard.put_run(
            ExecutionRun(
                run_id="run-active",
                task_id="task-active",
                execution_session_id="exec-old",
                executor_type="codex",
                status=RunStatus.RUNNING,
            )
        )
        scheduled = False

        def mark_scheduled(self) -> None:
            nonlocal scheduled
            scheduled = True

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)

        post_task = asyncio.create_task(
            client.post(
                f"/api/sessions/{session_id}/executor-audio-instructions",
                params={
                    "target_persona_id": "forge",
                    "create_new_thread": True,
                    "workspace_id": "/tmp/work",
                    "duration_ms": 1,
                    "sample_rate": 24000,
                    "num_channels": 1,
                    "samples_per_channel": 24,
                },
                content=b"\x00\x00" * 24,
                headers={"Content-Type": "audio/pcm"},
            )
        )
        for _ in range(100):
            if websocket.sent:
                break
            await asyncio.sleep(0.01)
        assert len(websocket.sent) == 1
        assert websocket.sent[0]["type"] == "transcribe_audio_instruction"
        assert websocket.sent[0]["audio"]["target_thread_id"] != "exec-old"
        manager.publish_audio_instruction_transcribed(
            AudioInstructionTranscribedMessage(
                request_id=websocket.sent[0]["request_id"],
                node_id="node-forge",
                executor_type="codex",
                transcript_text="start a fresh audio thread",
                language="en",
                duration_seconds=0.1,
            )
        )
        response = await post_task

    assert response.status_code == 200
    new_thread_id = response.json()["target_thread_id"]
    assert new_thread_id != "exec-old"
    assert not scheduled
    assert len(websocket.sent) == 2
    assert websocket.sent[1]["type"] == "start_codex_turn"
    assert websocket.sent[1]["target_thread_id"] == new_thread_id
    assert websocket.sent[1]["instruction"]["text"] == "start a fresh audio thread"
    assert "task_id" not in websocket.sent[1]
    old_task = await runtime_session.blackboard.get_task("task-active")
    assert old_task is not None
    assert old_task.status == TaskStatus.RUNNING
    assert old_task.metadata == old_metadata
    old_session = await runtime_session.blackboard.get_session("exec-old")
    assert old_session is not None
    assert old_session.active_run_id == "run-active"
    tasks = await runtime_session.blackboard.list_tasks()
    new_tasks = [task for task in tasks if task.task_id != "task-active"]
    assert new_tasks == []
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].target_thread_id == new_thread_id
    assert requests[0].text == "start a fresh audio thread"
    assert requests[0].status == "accepted"


@pytest.mark.anyio
async def test_executor_audio_instruction_targets_selected_codex_thread_without_message_route(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-audio-thread")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        manager = app.state.runtime_container.executor_node_manager
        manager._connections_by_node["node-forge"] = NodeConnectionState(
            websocket=websocket,
            node_id="node-forge",
            connected_at="2026-05-26T00:00:00+00:00",
            executors={
                "codex": ExecutorNodeExecutor(
                    executor_type="codex",
                    supports_resume=True,
                    supports_follow_up=True,
                    supports_audio_instruction=True,
                )
            },
        )
        await runtime_session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id="node-forge",
                bro_detail_session_id="detail-forge",
                status="busy",
            )
        )
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-current",
                root_task_id="task-current",
                title="Current selected thread task",
                goal="Keep working",
                status=TaskStatus.RUNNING,
                preferred_executor="codex",
                metadata={"persona_id": "forge", "bro_thread_id": "bro-thread-selected"},
            )
        )
        await runtime_session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-selected",
                task_id="task-current",
                base_executor_id="codex",
                executor_node_id="node-forge",
                continuity_key="bro-thread-selected",
                active_run_id="run-current",
                latest_run_id="run-current",
                run_ids=["run-current"],
                latest_resume_handle=AgentResumeHandle(
                    executor_id="codex",
                    session_handle="codex-thread-selected",
                ),
            )
        )
        await runtime_session.blackboard.put_run(
            ExecutionRun(
                run_id="run-current",
                task_id="task-current",
                execution_session_id="exec-selected",
                executor_type="codex",
                status=RunStatus.RUNNING,
            )
        )

        response = await client.post(
            f"/api/sessions/{session_id}/executor-audio-instructions",
            params={
                "target_persona_id": "forge",
                "target_thread_id": "bro-thread-selected",
                "duration_ms": 1,
                "sample_rate": 24000,
                "num_channels": 1,
                "samples_per_channel": 24,
            },
            content=b"\x00\x00" * 24,
            headers={"Content-Type": "audio/pcm"},
        )
        run = await runtime_session.blackboard.get_run("run-current")
        assert run is not None
        await runtime_session.blackboard.put_run(
            run.model_copy(update={"status": RunStatus.COMPLETED, "output_summary": "Done from selected audio."})
        )
        await runtime_session.notification_manager.handle_blackboard_write(
            BlackboardWriteEvent(kind=BlackboardWriteKind.RUN, entity_id="run-current")
        )
        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()

    assert response.status_code == 200
    assert response.json()["target_thread_id"] == "bro-thread-selected"
    assert conversation["conversation_history"] == []
    assert await runtime_session.blackboard.list_notification_candidates() == []
    task = await runtime_session.blackboard.get_task("task-current")
    assert task is not None
    assert task.metadata["target_thread_id"] == "bro-thread-selected"
    assert task.metadata["bro_thread_id"] == "bro-thread-selected"
    assert task.metadata["direct_executor_input_sources"] == ["bro_detail_ptt"]
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["type"] == "dispatch_audio_instruction"
    assert websocket.sent[0]["execution_session_id"] == "exec-selected"
    assert websocket.sent[0]["audio"]["target_thread_id"] == "bro-thread-selected"
    assert "artifact_path" not in websocket.sent[0]["audio"]
    assert base64.b64decode(websocket.sent[0]["audio"]["pcm16_b64"], validate=True) == b"\x00\x00" * 24
