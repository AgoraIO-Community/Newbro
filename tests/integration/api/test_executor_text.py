from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import PublicAuthStore
from newbro.blackboard.store import BlackboardWriteEvent, BlackboardWriteKind
from newbro.executors.node.registry import ExecutorNodeRegistry
from newbro.protocol import AgentResumeHandle, BroThread, CodexThreadListItem, ExecutionRun, ExecutionSession, ExecutorNodeExecutor, Persona, RegisterNodeMessage, RunStatus, Task, TaskStatus
from newbro.runtime.executor_node_manager import CodexThreadListPage, CodexThreadTurnPage, ExecutorNodeManager, NodeConnectionState


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


async def _redeem(client: AsyncClient, app, code: str = "invite-text") -> None:
    await app.state.public_auth_store.create_invite(code)
    response = await client.post("/api/auth/invites/redeem", json={"code": code})
    assert response.status_code == 200


async def _put_connected_forge(runtime_session, manager, websocket: FakeWebSocket | None = None) -> None:
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
async def test_bro_list_api_returns_compact_bro_node_rows(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    app.state.runtime_container.executor_node_manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-bro-list")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        manager = app.state.runtime_container.executor_node_manager
        create_node = await client.post(
            f"/api/sessions/{session_id}/executor-nodes",
            json={"name": "Mac Studio", "enabled_executors": ["codex"]},
        )
        assert create_node.status_code == 201
        node_id = create_node.json()["node"]["node_id"]
        await manager.register_connection(
            websocket=FakeWebSocket(),
            register=RegisterNodeMessage(
                node_id=node_id,
                token=create_node.json()["token"],
                executors=[
                    ExecutorNodeExecutor(
                        executor_type="codex",
                        supports_resume=True,
                        supports_follow_up=True,
                        supports_audio_instruction=True,
                        supports_thread_list=True,
                        version="0.135.0",
                        minimum_version="0.135.0",
                    )
                ],
            ),
        )
        create_persona = await client.post(
            f"/api/sessions/{session_id}/personas",
            json={
                "name": "Forge",
                "avatar": "bro",
                "base_prompt": "",
                "executor_node_id": node_id,
            },
        )
        assert create_persona.status_code == 201

        response = await client.get(f"/api/sessions/{session_id}/bros")

    assert response.status_code == 200
    body = response.json()
    assert body["bros"] == [
        {
            "persona_id": create_persona.json()["persona_id"],
            "name": "Forge",
            "avatar": "bro",
            "status": "idle",
            "executor_node": {
                "node_id": node_id,
                "name": "Mac Studio",
                "connection_status": "connected",
                "enabled_executors": ["codex"],
                "last_connected_at": body["bros"][0]["executor_node"]["last_connected_at"],
                "codex": {
                    "version": "0.135.0",
                    "minimum_version": "0.135.0",
                    "availability_reason": None,
                    "supports_thread_list": True,
                    "supports_audio_instruction": True,
                    "skills": [],
                },
            },
        }
    ]
    assert body["bros"][0]["executor_node"]["last_connected_at"] is not None
    assert "token_hint" not in body["bros"][0]["executor_node"]
    assert "last_seen_at" not in body["bros"][0]["executor_node"]


@pytest.mark.anyio
async def test_direct_text_selected_imported_thread_does_not_create_task_before_executor_acceptance(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-text-outbound")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_forge(runtime_session, app.state.runtime_container.executor_node_manager, websocket)

        runtime_session._bro_detail_thread_projection().imported_codex_threads["codex-import-1"] = BroThread(
            thread_id="codex-import-1",
            persona_id="forge",
            title="Imported",
            status="completed",
            has_resume_handle=True,
        )
        runtime_session._bro_detail_thread_projection().imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
            executor_id="codex",
            session_handle="native-thread-1",
            opaque={"cwd": "/tmp/work"},
        )

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={
                "target_persona_id": "forge",
                "target_thread_id": "codex-import-1",
                "text": "continue directly",
                "client_request_id": "client-text-1",
            },
        )

    assert response.status_code == 200
    assert await runtime_session.blackboard.list_tasks() == []
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].client_request_id == "client-text-1"
    assert requests[0].status == "accepted"
    assert websocket.sent[-1]["type"] == "start_codex_turn"
    assert "task_id" not in websocket.sent[-1]
    assert "run_id" not in websocket.sent[-1]
    assert "execution_session_id" not in websocket.sent[-1]


@pytest.mark.anyio
async def test_executor_text_instruction_requires_explicit_thread_intent(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-text-explicit")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_forge(runtime_session, app.state.runtime_container.executor_node_manager)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "ambiguous send"},
        )

    assert response.status_code == 409
    assert "requires explicit thread intent" in response.text


@pytest.mark.anyio
async def test_executor_text_instruction_rejects_thread_target_contradiction(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-text-contradiction")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_forge(runtime_session, app.state.runtime_container.executor_node_manager)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={
                "target_persona_id": "forge",
                "target_thread_id": "thread-existing",
                "create_new_thread": True,
                "text": "contradictory send",
            },
        )

    assert response.status_code == 409
    assert "cannot target an existing thread and create a new thread" in response.text


@pytest.mark.anyio
async def test_executor_text_instruction_requires_workspace_for_new_codex_thread(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-new-thread-workspace-required")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_forge(runtime_session, app.state.runtime_container.executor_node_manager)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "start directly", "create_new_thread": True},
        )

    assert response.status_code == 409
    assert "requires a workspace selection" in response.text


@pytest.mark.anyio
async def test_executor_text_instruction_rejects_unknown_new_thread_workspace(tmp_path):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-new-thread-workspace-unknown")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        await _put_connected_forge(runtime_session, app.state.runtime_container.executor_node_manager)
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

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={
                "target_persona_id": "forge",
                "text": "start directly",
                "create_new_thread": True,
                "workspace_id": "/tmp/other",
            },
        )

    assert response.status_code == 409
    assert "workspace is not available" in response.text


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
            json={"target_persona_id": "forge", "target_thread_id": "exec-1", "text": "continue directly"},
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

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "start directly", "create_new_thread": True, "workspace_id": " /tmp/work "},
        )
        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert conversation["conversation_history"] == []
    assert not scheduled
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["type"] == "start_codex_turn"
    assert websocket.sent[0]["create_new_thread"] is True
    assert websocket.sent[0]["workspace_id"] == "/tmp/work"
    assert "task_id" not in websocket.sent[0]
    tasks = await runtime_session.blackboard.list_tasks()
    assert tasks == []
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].target_thread_id == response.json()["target_thread_id"]
    assert requests[0].create_new_thread is True
    assert requests[0].workspace_id == "/tmp/work"
    assert requests[0].text == "start directly"
    assert requests[0].status == "accepted"
    assert not any(thread["thread_id"] == response.json()["target_thread_id"] for thread in snapshot["bro_threads"])
    persona = await runtime_session.blackboard.get_persona("forge")
    assert persona is not None
    assert persona.status == "idle"


@pytest.mark.anyio
async def test_subscribe_new_direct_thread_without_executor_thread_returns_conflict(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-new-thread-open")
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

        def mark_scheduled(self) -> None:
            return None

        async def fake_request_codex_thread_turns(**kwargs):
            raise AssertionError("opening a direct thread must not read Codex history")

        async def fake_subscribe_codex_thread(**kwargs):
            return None

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)
        monkeypatch.setattr(manager, "request_codex_thread_turns", fake_request_codex_thread_turns)
        monkeypatch.setattr(manager, "subscribe_codex_thread", fake_subscribe_codex_thread)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "start directly", "create_new_thread": True, "workspace_id": "/tmp/work"},
        )
        assert response.status_code == 200
        target_thread_id = response.json()["target_thread_id"]
        assert await runtime_session.blackboard.list_tasks() == []

        opened = await client.post(
            f"/api/sessions/{session_id}/bro-threads/{target_thread_id}/subscribe",
            json={"target_persona_id": "forge"},
        )

    assert opened.status_code == 409
    assert await runtime_session.blackboard.list_tasks() == []


@pytest.mark.anyio
async def test_executor_text_instruction_targets_selected_completed_codex_thread(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-thread")
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
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-done",
                root_task_id="task-done",
                title="Completed task",
                goal="First instruction",
                status=TaskStatus.COMPLETED,
                preferred_executor="codex",
                metadata={"persona_id": "forge", "bro_detail_session_id": "detail-forge"},
            )
        )
        await runtime_session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-1",
                task_id="task-done",
                base_executor_id="codex",
                executor_node_id="node-forge",
                continuity_key="detail-forge",
                active_run_id=None,
                latest_run_id="run-done",
                run_ids=["run-done"],
                latest_resume_handle=AgentResumeHandle(
                    executor_id="codex",
                    session_handle="codex-thread-1",
                ),
            )
        )
        await runtime_session.blackboard.put_run(
            ExecutionRun(
                run_id="run-done",
                task_id="task-done",
                execution_session_id="exec-1",
                executor_type="codex",
                status=RunStatus.COMPLETED,
                output_summary="Done from Codex.",
            )
        )
        scheduled = False

        def mark_scheduled(self) -> None:
            nonlocal scheduled
            scheduled = True

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={
                "target_persona_id": "forge",
                "target_thread_id": "exec-1",
                "text": "resume this exact thread",
            },
        )

    assert snapshot["bro_threads"][0]["thread_id"] == "exec-1"
    assert snapshot["bro_threads"][0]["has_resume_handle"] is True
    assert snapshot["bro_threads"][0]["diagnostics"]["codex_thread_id"] == "codex-thread-1"
    assert snapshot["bro_threads"][0]["active_task_id"] is None
    assert response.status_code == 200
    assert response.json()["target_thread_id"] == "exec-1"
    assert not scheduled
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["type"] == "start_codex_turn"
    assert websocket.sent[0]["target_thread_id"] == "exec-1"
    assert websocket.sent[0]["latest_resume_handle"]["session_handle"] == "codex-thread-1"
    assert "task_id" not in websocket.sent[0]
    tasks = await runtime_session.blackboard.list_tasks()
    created = [task for task in tasks if task.task_id != "task-done"]
    assert created == []
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].target_thread_id == "exec-1"
    assert requests[0].status == "accepted"


@pytest.mark.anyio
async def test_executor_text_instruction_targets_imported_codex_thread(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-import-thread")
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
                    supports_thread_list=True,
                )
            },
        )
        await runtime_session.blackboard.put_task(
            Task(
                task_id="task-other-thread",
                root_task_id="task-other-thread",
                title="Other imported thread task",
                goal="Other imported thread task",
                status=TaskStatus.QUEUED,
                preferred_executor="codex",
                metadata={
                    "persona_id": "forge",
                    "bro_thread_id": "codex-import-other",
                    "target_thread_id": "codex-import-other",
                    "executor_node_id": "node-forge",
                },
            )
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

        list_calls = 0

        async def fake_request_codex_threads(
            *, node_id: str, workspace_id=None, limit: int = 100, cursor=None, timeout_seconds: float = 8.0
        ):
            nonlocal list_calls
            assert node_id == "node-forge"
            list_calls += 1
            return CodexThreadListPage(
                threads=[
                    CodexThreadListItem(
                        thread_id="codex-imported-native-1",
                        session_id="codex-imported-native-1",
                        preview="Task: Imported outside Newbro\nGoal: keep context",
                        status="notLoaded",
                        cwd="/Users/zhangqianze/Documents/Synopse",
                        path="/Users/zhangqianze/.codex/sessions/import.jsonl",
                        created_at=1779850000,
                        updated_at=1779850100,
                        cli_version="0.133.0",
                        source="vscode",
                    )
                ]
            )

        monkeypatch.setattr(manager, "request_codex_threads", fake_request_codex_threads)
        scheduled = False

        def mark_scheduled(self) -> None:
            nonlocal scheduled
            scheduled = True

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)

        page_response = await client.get(
            f"/api/sessions/{session_id}/bro-threads",
            params={"target_persona_id": "forge"},
        )
        assert page_response.status_code == 200
        page = page_response.json()
        imported_thread = next(
            thread
            for thread in page["threads"]
            if thread["diagnostics"].get("codex_thread_id") == "codex-imported-native-1"
        )
        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={
                "target_persona_id": "forge",
                "target_thread_id": imported_thread["thread_id"],
                "text": "continue imported context",
            },
        )
        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()

    assert imported_thread["thread_id"].startswith("codex-import-")
    assert imported_thread["execution_session_id"] is None
    assert imported_thread["title"] == "Imported outside Newbro"
    assert imported_thread["has_resume_handle"] is True
    assert imported_thread["diagnostics"]["codex_thread_id"] == "codex-imported-native-1"
    assert list_calls == 1
    assert response.status_code == 200
    assert response.json()["target_thread_id"] == imported_thread["thread_id"]
    assert conversation["conversation_history"] == []
    assert not scheduled
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["type"] == "start_codex_turn"
    assert websocket.sent[0]["target_thread_id"] == imported_thread["thread_id"]
    assert websocket.sent[0]["latest_resume_handle"]["session_handle"] == "codex-imported-native-1"
    assert "task_id" not in websocket.sent[0]
    tasks = await runtime_session.blackboard.list_tasks()
    assert [task.task_id for task in tasks] == ["task-other-thread"]
    requests = await runtime_session.blackboard.list_outbound_turn_requests()
    assert len(requests) == 1
    assert requests[0].target_thread_id == imported_thread["thread_id"]
    assert requests[0].text == "continue imported context"
    assert requests[0].status == "accepted"


@pytest.mark.anyio
async def test_subscribe_imported_codex_thread_returns_subscription_without_history_hydration(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-open-thread")
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
                    supports_thread_list=True,
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

        list_calls = 0

        async def fake_request_codex_threads(
            *, node_id: str, workspace_id=None, limit: int = 100, cursor=None, timeout_seconds: float = 8.0
        ):
            nonlocal list_calls
            assert node_id == "node-forge"
            list_calls += 1
            return CodexThreadListPage(
                threads=[
                    CodexThreadListItem(
                        thread_id="codex-imported-newer-history",
                        session_id="codex-imported-newer-history",
                        preview="Task: Newer imported history",
                        status="notLoaded",
                        cwd="/tmp/newer",
                        path="/tmp/codex-newer-history.jsonl",
                        created_at=1779850200,
                        updated_at=1779850300,
                        cli_version="0.133.0",
                        source="vscode",
                    ),
                    CodexThreadListItem(
                        thread_id="codex-imported-native-history",
                        session_id="codex-imported-native-history",
                        preview="Task: Imported history",
                        status="notLoaded",
                        cwd="/tmp/elsewhere",
                        path="/tmp/codex-history.jsonl",
                        created_at=1779850000,
                        updated_at=1779850100,
                        cli_version="0.133.0",
                        source="vscode",
                    ),
                ]
            )

        read_calls: list[tuple[str, str]] = []

        async def fake_request_codex_thread_turns(
            *, node_id: str, thread_id: str, limit: int = 100, cursor=None, timeout_seconds: float = 8.0
        ):
            read_calls.append((node_id, thread_id))
            return CodexThreadTurnPage(
                thread_id=thread_id,
                turns=[
                    {
                        "id": "turn-assistant",
                        "createdAt": 1779850120,
                        "items": [
                            {"type": "agentMessage", "id": "assistant-commentary", "text": "Checking imported context."},
                            {"type": "agentMessage", "id": "assistant-1", "text": "Imported context is ready."}
                        ],
                    },
                    {
                        "id": "turn-user",
                        "createdAt": 1779850110,
                        "items": [
                            {
                                "type": "event_msg",
                                "id": "user-1",
                                "payload": {"type": "user_message", "message": "Open the imported context."},
                            }
                        ],
                    },
                ],
            )

        subscription_calls: list[tuple[str, str, str]] = []
        unsubscribe_calls: list[tuple[str, str]] = []
        subscription_started = asyncio.Event()
        subscription_release = asyncio.Event()
        expected_session_id = session_id

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
        ):
            assert node_id == "node-forge"
            assert session_id == expected_session_id
            assert target_persona_id == "forge"
            assert target_thread_id == imported_thread["thread_id"]
            assert thread_id == "codex-imported-native-history"
            assert workspace_id == "/tmp/elsewhere"
            subscription_calls.append((subscription_id, target_thread_id, thread_id))
            subscription_started.set()
            await subscription_release.wait()

        async def fake_unsubscribe_codex_thread(
            *,
            node_id: str,
            subscription_id: str,
            thread_id: str,
            timeout_seconds: float = 8.0,
        ):
            assert node_id == "node-forge"
            unsubscribe_calls.append((subscription_id, thread_id))

        monkeypatch.setattr(manager, "request_codex_threads", fake_request_codex_threads)
        monkeypatch.setattr(manager, "request_codex_thread_turns", fake_request_codex_thread_turns)
        monkeypatch.setattr(manager, "subscribe_codex_thread", fake_subscribe_codex_thread)
        monkeypatch.setattr(manager, "unsubscribe_codex_thread", fake_unsubscribe_codex_thread)

        page_response = await client.get(
            f"/api/sessions/{session_id}/bro-threads",
            params={"target_persona_id": "forge"},
        )
        assert page_response.status_code == 200
        page = page_response.json()
        assert list_calls == 1
        runtime_session._bro_detail_thread_projection().last_codex_thread_sync_monotonic = 0
        imported_thread = next(
            thread
            for thread in page["threads"]
            if thread["diagnostics"]["codex_thread_id"] == "codex-imported-native-history"
        )
        old_open_response = await client.post(
            f"/api/sessions/{session_id}/bro-threads/{imported_thread['thread_id']}/open",
            json={"target_persona_id": "forge"},
        )
        response_task = asyncio.create_task(
            client.post(
                f"/api/sessions/{session_id}/bro-threads/{imported_thread['thread_id']}/subscribe",
                json={"target_persona_id": "forge"},
            )
        )
        await asyncio.wait_for(subscription_started.wait(), timeout=1.0)
        subscription_release.set()
        response = await asyncio.wait_for(response_task, timeout=1.0)
        close_response = await client.request(
            "DELETE",
            f"/api/sessions/{session_id}/bro-threads/{imported_thread['thread_id']}/subscribe",
            json={"target_persona_id": "forge"},
        )

    assert old_open_response.status_code == 404
    assert response.status_code == 200
    assert close_response.status_code == 200
    assert list_calls == 1
    assert read_calls == []
    assert len(subscription_calls) == 1
    assert unsubscribe_calls == [(subscription_calls[0][0], "codex-imported-native-history")]
    assert response.json() == {
        "thread_id": imported_thread["thread_id"],
        "persona_id": "forge",
        "subscribed": True,
        "timeline_status": "not_loaded",
        "timeline_error": None,
    }
    assert close_response.json() == {
        "thread_id": imported_thread["thread_id"],
        "persona_id": "forge",
        "subscribed": False,
        "timeline_status": "not_loaded",
        "timeline_error": None,
    }


@pytest.mark.anyio
async def test_subscribe_imported_codex_thread_does_not_read_timeline_history(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-open-thread-timeout")
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
                    supports_thread_list=True,
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

        async def fake_request_codex_threads(
            *, node_id: str, workspace_id=None, limit: int = 100, cursor=None, timeout_seconds: float = 8.0
        ):
            return CodexThreadListPage(
                threads=[
                    CodexThreadListItem(
                        thread_id="codex-timeout-history",
                        session_id="codex-timeout-history",
                        preview="Task: Timeout history",
                        status="notLoaded",
                        cwd="/tmp/elsewhere",
                        path="/tmp/codex-timeout.jsonl",
                        created_at=1779850000,
                        updated_at=1779850100,
                        cli_version="0.133.0",
                        source="vscode",
                    )
                ]
            )

        read_calls: list[tuple[str, str]] = []

        async def fake_request_codex_thread_turns(
            *, node_id: str, thread_id: str, limit: int = 100, cursor=None, timeout_seconds: float = 8.0
        ):
            read_calls.append((node_id, thread_id))
            raise AssertionError("subscribe must not read Codex thread history")

        subscription_calls: list[str] = []
        unsubscribe_calls: list[tuple[str, str]] = []
        subscription_started = asyncio.Event()

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
        ):
            subscription_calls.append(subscription_id)
            subscription_started.set()

        async def fake_unsubscribe_codex_thread(
            *,
            node_id: str,
            subscription_id: str,
            thread_id: str,
            timeout_seconds: float = 8.0,
        ):
            unsubscribe_calls.append((subscription_id, thread_id))

        monkeypatch.setattr(manager, "request_codex_threads", fake_request_codex_threads)
        monkeypatch.setattr(manager, "request_codex_thread_turns", fake_request_codex_thread_turns)
        monkeypatch.setattr(manager, "subscribe_codex_thread", fake_subscribe_codex_thread)
        monkeypatch.setattr(manager, "unsubscribe_codex_thread", fake_unsubscribe_codex_thread)

        page_response = await client.get(
            f"/api/sessions/{session_id}/bro-threads",
            params={"target_persona_id": "forge"},
        )
        assert page_response.status_code == 200
        imported_thread = page_response.json()["threads"][0]
        response = await client.post(
            f"/api/sessions/{session_id}/bro-threads/{imported_thread['thread_id']}/subscribe",
            json={"target_persona_id": "forge"},
        )
        await asyncio.wait_for(subscription_started.wait(), timeout=1.0)

    assert response.status_code == 200
    assert subscription_calls
    assert unsubscribe_calls == []
    assert read_calls == []
    assert response.json() == {
        "thread_id": imported_thread["thread_id"],
        "persona_id": "forge",
        "subscribed": True,
        "timeline_status": "not_loaded",
        "timeline_error": None,
    }


@pytest.mark.anyio
async def test_executor_text_instruction_rejects_queued_direct_task_without_executor_thread(
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
                    "bro_thread_id": "thread-stuck",
                    "target_thread_id": "thread-stuck",
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
            json={"target_persona_id": "forge", "target_thread_id": "thread-stuck", "text": "retry text"},
        )

    assert response.status_code == 409
    assert not scheduled
    assert websocket.sent == []
    task = await runtime_session.blackboard.get_task("task-stuck")
    assert task is not None
    assert task.status == TaskStatus.QUEUED
    assert task.latest_instruction == "first text"
    assert "suppress_communication_notifications" not in task.metadata
    assert await runtime_session.blackboard.list_outbound_turn_requests() == []


@pytest.mark.anyio
async def test_sync_imported_codex_threads_skips_ephemeral_entries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-ephemeral-skip")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        manager = app.state.runtime_container.executor_node_manager
        manager._connections_by_node["node-forge"] = NodeConnectionState(
            websocket=websocket,
            node_id="node-forge",
            connected_at="2026-05-30T00:00:00+00:00",
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

        async def fake_request_codex_threads(
            *, node_id: str, workspace_id=None, limit: int = 100, cursor=None, timeout_seconds: float = 8.0
        ):
            assert node_id == "node-forge"
            return CodexThreadListPage(
                threads=[
                    CodexThreadListItem(
                        thread_id="codex-real",
                        session_id="codex-real",
                        preview="Real project work",
                        status="notLoaded",
                        cwd="/Users/zhangqianze/Documents/Synopse",
                        created_at=1779850000,
                        updated_at=1779850100,
                        cli_version="0.133.0",
                        source="vscode",
                        diagnostics={"ephemeral": False},
                    ),
                    CodexThreadListItem(
                        thread_id="codex-scratch",
                        session_id="codex-scratch",
                        preview="Scratch turn",
                        status="notLoaded",
                        cwd="/Users/zhangqianze/.codex/scratch/abc",
                        created_at=1779850200,
                        updated_at=1779850300,
                        cli_version="0.133.0",
                        source="cli",
                        diagnostics={"ephemeral": True},
                    ),
                ]
            )

        monkeypatch.setattr(manager, "request_codex_threads", fake_request_codex_threads)

        page_response = await client.get(
            f"/api/sessions/{session_id}/bro-threads",
            params={"target_persona_id": "forge"},
        )
        assert page_response.status_code == 200
        page = page_response.json()
        imported = [
            thread
            for thread in page["threads"]
            if thread.get("diagnostics", {}).get("imported_from_codex_thread_list") is True
        ]
        assert len(imported) == 1, imported
        assert imported[0]["workspace_id"] == "/Users/zhangqianze/Documents/Synopse"
        assert imported[0]["diagnostics"].get("ephemeral") is False

        workspaces = await runtime_session._bro_detail_thread_projection().known_codex_workspaces_for_persona(
            await runtime_session.blackboard.get_persona("forge")
        )
        assert "/Users/zhangqianze/Documents/Synopse" in workspaces
        assert "/Users/zhangqianze/.codex/scratch/abc" not in workspaces
