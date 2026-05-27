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


async def _redeem(client: AsyncClient, app, code: str = "invite-text") -> None:
    await app.state.public_auth_store.create_invite(code)
    response = await client.post("/api/auth/invites/redeem", json={"code": code})
    assert response.status_code == 200


@pytest.mark.anyio
async def test_executor_text_instruction_dispatches_to_active_executor_without_message_route(tmp_path):
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

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "continue directly"},
        )
        run = await runtime_session.blackboard.get_run("run-current")
        assert run is not None
        await runtime_session.blackboard.put_run(
            run.model_copy(update={"status": RunStatus.COMPLETED, "output_summary": "Done from Codex."})
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
    assert task.metadata["direct_executor_input_sources"] == ["bro_detail_text"]
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["type"] == "dispatch_text_instruction"
    assert websocket.sent[0]["task_id"] == "task-current"
    assert websocket.sent[0]["instruction"]["text"] == "continue directly"


@pytest.mark.anyio
async def test_executor_text_instruction_starts_direct_task_for_connected_idle_bro(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
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
                status="idle",
                current_task_id=None,
            )
        )
        scheduled = False

        def mark_scheduled(self) -> None:
            nonlocal scheduled
            scheduled = True

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "start directly"},
        )
        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert conversation["conversation_history"] == []
    assert scheduled
    assert websocket.sent == []
    tasks = await runtime_session.blackboard.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.status == TaskStatus.QUEUED
    assert task.preferred_executor == "codex"
    assert task.latest_instruction == "start directly"
    assert task.metadata["source_kind"] == "bro_detail_text"
    assert task.metadata["persona_id"] == "forge"
    assert task.metadata["suppress_communication_notifications"] is True
    persona = await runtime_session.blackboard.get_persona("forge")
    assert persona is not None
    assert persona.current_task_id == task.task_id
    assert persona.status == "busy"


@pytest.mark.anyio
async def test_executor_text_instruction_recovers_queued_direct_task_without_active_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
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
                current_task_id="task-stuck",
            )
        )
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-stuck",
                root_task_id="task-stuck",
                title="Stuck direct task",
                goal="first text",
                status=TaskStatus.QUEUED,
                preferred_executor="codex",
                metadata={
                    "source_kind": "bro_detail_text",
                    "persona_id": "forge",
                    "executor_node_id": "node-forge",
                },
                latest_instruction="first text",
            )
        )
        scheduled = False

        def mark_scheduled(self) -> None:
            nonlocal scheduled
            scheduled = True

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "retry text"},
        )

    assert response.status_code == 200
    assert scheduled
    assert websocket.sent == []
    task = await runtime_session.blackboard.get_task("task-stuck")
    assert task is not None
    assert task.status == TaskStatus.QUEUED
    assert "first text" in (task.latest_instruction or "")
    assert "retry text" in (task.latest_instruction or "")
    assert task.metadata["suppress_communication_notifications"] is True
    assert task.metadata["direct_executor_input_sources"] == ["bro_detail_text"]
