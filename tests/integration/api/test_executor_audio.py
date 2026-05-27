from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import PublicAuthStore
from newbro.blackboard.store import BlackboardWriteEvent, BlackboardWriteKind
from newbro.protocol import ExecutionRun, ExecutionSession, ExecutorNodeExecutor, Persona, RunStatus, Task, TaskStatus
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
                current_task_id="task-1",
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
                current_task_id="task-current",
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

        execution_session, run = await runtime_session._active_codex_execution_for_persona("forge")

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
                current_task_id="task-current",
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
