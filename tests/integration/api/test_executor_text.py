from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import PublicAuthStore
from newbro.blackboard.store import BlackboardWriteEvent, BlackboardWriteKind
from newbro.protocol import AgentResumeHandle, CodexThreadListItem, ExecutionRun, ExecutionSession, ExecutorNodeExecutor, Persona, RunStatus, Task, TaskStatus
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
            current_task_id=None,
        )
    )


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
            json={"target_persona_id": "forge", "text": "start directly", "create_new_thread": True},
        )
        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()

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
    projected_thread = next(
        thread for thread in snapshot["bro_threads"] if thread["thread_id"] == response.json()["target_thread_id"]
    )
    assert projected_thread["execution_session_id"] is None
    assert projected_thread["status"] == "queued"
    assert projected_thread["task_ids"] == [task.task_id]
    assert projected_thread["latest_task_id"] == task.task_id
    assert projected_thread["active_task_id"] == task.task_id
    assert projected_thread["diagnostics"]["pending_execution_session"] is True
    persona = await runtime_session.blackboard.get_persona("forge")
    assert persona is not None
    assert persona.current_task_id == task.task_id
    assert persona.status == "busy"


@pytest.mark.anyio
async def test_open_new_direct_thread_does_not_duplicate_sent_text_as_history(
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
                current_task_id=None,
            )
        )

        def mark_scheduled(self) -> None:
            return None

        async def fake_request_codex_thread(*, node_id: str, thread_id: str, timeout_seconds: float = 8.0):
            raise AssertionError("opening a direct thread must not read Codex history")

        async def fake_subscribe_codex_thread(**kwargs):
            return None

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)
        monkeypatch.setattr(manager, "request_codex_thread", fake_request_codex_thread)
        monkeypatch.setattr(manager, "subscribe_codex_thread", fake_subscribe_codex_thread)

        response = await client.post(
            f"/api/sessions/{session_id}/executor-text-instructions",
            json={"target_persona_id": "forge", "text": "start directly", "create_new_thread": True},
        )
        assert response.status_code == 200
        target_thread_id = response.json()["target_thread_id"]
        tasks = await runtime_session.blackboard.list_tasks()
        assert len(tasks) == 1
        direct_task = tasks[0]
        resume_handle = AgentResumeHandle(
            executor_id="codex",
            session_handle="codex-thread-new",
            opaque={"cwd": "/tmp/work", "title": "start directly"},
        )
        await runtime_session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-new",
                task_id=direct_task.task_id,
                base_executor_id="codex",
                executor_node_id="node-forge",
                continuity_key=target_thread_id,
                run_ids=["run-new"],
                latest_run_id="run-new",
                latest_resume_handle=resume_handle,
            )
        )
        await runtime_session.blackboard.put_run(
            ExecutionRun(
                run_id="run-new",
                task_id=direct_task.task_id,
                execution_session_id="exec-new",
                executor_type="codex",
                status=RunStatus.COMPLETED,
                output_summary="Started.",
            )
        )

        opened = await client.post(
            f"/api/sessions/{session_id}/bro-threads/{target_thread_id}/open",
            json={"target_persona_id": "forge"},
        )

    assert opened.status_code == 200
    tasks = await runtime_session.blackboard.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].task_id == direct_task.task_id
    assert not any(task.metadata.get("source_kind") == "codex_thread_history" for task in tasks)


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
                current_task_id=None,
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
    assert scheduled
    assert websocket.sent == []
    tasks = await runtime_session.blackboard.list_tasks()
    created = [task for task in tasks if task.task_id != "task-done"]
    assert len(created) == 1
    task = created[0]
    assert task.metadata["target_thread_id"] == "exec-1"
    assert task.metadata["bro_thread_id"] == "detail-forge"
    assert task.metadata["codex_thread_mode"] == "resume"
    assert task.metadata["suppress_communication_notifications"] is True


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

        list_calls = 0

        async def fake_request_codex_threads(*, node_id: str, workspace_id=None, timeout_seconds: float = 8.0):
            nonlocal list_calls
            assert node_id == "node-forge"
            list_calls += 1
            return [
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

        monkeypatch.setattr(manager, "request_codex_threads", fake_request_codex_threads)
        scheduled = False

        def mark_scheduled(self) -> None:
            nonlocal scheduled
            scheduled = True

        monkeypatch.setattr(type(runtime_session), "schedule_execution", mark_scheduled)

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        imported_thread = next(
            thread
            for thread in snapshot["bro_threads"]
            if thread["diagnostics"]["codex_thread_id"] == "codex-imported-native-1"
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
    assert scheduled
    tasks = await runtime_session.blackboard.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.metadata["target_thread_id"] == imported_thread["thread_id"]
    assert task.metadata["bro_thread_id"] == imported_thread["thread_id"]
    assert task.metadata["codex_thread_mode"] == "resume"
    assert task.metadata["codex_import_thread_id"] == "codex-imported-native-1"
    assert task.metadata["codex_import_cwd"] == "/Users/zhangqianze/Documents/Synopse"
    assert task.session_affinity == "/Users/zhangqianze/Documents/Synopse"
    assert task.metadata["suppress_communication_notifications"] is True


@pytest.mark.anyio
async def test_open_imported_codex_thread_loads_native_messages_without_task_hydration(
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
                current_task_id=None,
            )
        )

        list_calls = 0

        async def fake_request_codex_threads(*, node_id: str, workspace_id=None, timeout_seconds: float = 8.0):
            nonlocal list_calls
            assert node_id == "node-forge"
            list_calls += 1
            return [
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
                )
            ]

        read_calls: list[tuple[str, str]] = []

        async def fake_request_codex_thread(*, node_id: str, thread_id: str, timeout_seconds: float = 8.0):
            read_calls.append((node_id, thread_id))
            return {
                "id": thread_id,
                "turns": [
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
                    {
                        "id": "turn-assistant",
                        "createdAt": 1779850120,
                        "items": [
                            {"type": "agentMessage", "id": "assistant-commentary", "text": "Checking imported context."},
                            {"type": "agentMessage", "id": "assistant-1", "text": "Imported context is ready."}
                        ],
                    },
                ],
            }

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
        monkeypatch.setattr(manager, "request_codex_thread", fake_request_codex_thread)
        monkeypatch.setattr(manager, "subscribe_codex_thread", fake_subscribe_codex_thread)
        monkeypatch.setattr(manager, "unsubscribe_codex_thread", fake_unsubscribe_codex_thread)

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        assert list_calls == 1
        runtime_session._last_codex_thread_sync_monotonic = 0
        original_thread_ids = [thread["thread_id"] for thread in snapshot["bro_threads"]]
        imported_thread = next(
            thread
            for thread in snapshot["bro_threads"]
            if thread["diagnostics"]["codex_thread_id"] == "codex-imported-native-history"
        )
        response = await asyncio.wait_for(
            client.post(
                f"/api/sessions/{session_id}/bro-threads/{imported_thread['thread_id']}/open",
                json={"target_persona_id": "forge"},
            ),
            timeout=0.5,
        )
        await asyncio.wait_for(subscription_started.wait(), timeout=1.0)
        subscription_release.set()
        await asyncio.sleep(0)
        close_response = await client.request(
            "DELETE",
            f"/api/sessions/{session_id}/bro-threads/{imported_thread['thread_id']}/open",
            json={"target_persona_id": "forge"},
        )

    assert response.status_code == 200
    assert close_response.status_code == 200
    assert list_calls == 1
    assert read_calls == [("node-forge", "codex-imported-native-history")]
    assert len(subscription_calls) == 1
    assert unsubscribe_calls == [(subscription_calls[0][0], "codex-imported-native-history")]
    opened = response.json()
    assert [thread["thread_id"] for thread in opened["bro_threads"]] == original_thread_ids
    opened_thread = next(thread for thread in opened["bro_threads"] if thread["thread_id"] == imported_thread["thread_id"])
    assert opened_thread["thread_id"] == imported_thread["thread_id"]
    assert opened_thread["title"] == imported_thread["title"]
    assert opened_thread["task_ids"] == []
    assert opened_thread["timeline_status"] == "loaded"
    assert opened_thread["timeline_error"] is None
    assert "history_hydrated" not in opened_thread["diagnostics"]
    assert opened_thread["diagnostics"]["codex_cwd"] == "/tmp/elsewhere"
    assert [
        (turn["user"]["text"] if turn["user"] else None, turn["assistant"]["text"] if turn["assistant"] else None, turn["thread_id"])
        for turn in opened["bro_timeline_turns"]
        if turn["thread_id"] == imported_thread["thread_id"]
    ] == [
        ("Open the imported context.", "Imported context is ready.", imported_thread["thread_id"]),
    ]
    assert not any(task["metadata"].get("source_kind") == "codex_thread_history" for task in opened["tasks"])


@pytest.mark.anyio
async def test_open_imported_codex_thread_history_timeout_marks_messages_failed(
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
                current_task_id=None,
            )
        )

        async def fake_request_codex_threads(*, node_id: str, workspace_id=None, timeout_seconds: float = 8.0):
            return [
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

        async def fake_request_codex_thread(*, node_id: str, thread_id: str, timeout_seconds: float = 8.0):
            raise TimeoutError("Timed out reading Codex thread history.")

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
        monkeypatch.setattr(manager, "request_codex_thread", fake_request_codex_thread)
        monkeypatch.setattr(manager, "subscribe_codex_thread", fake_subscribe_codex_thread)
        monkeypatch.setattr(manager, "unsubscribe_codex_thread", fake_unsubscribe_codex_thread)

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        imported_thread = snapshot["bro_threads"][0]
        response = await client.post(
            f"/api/sessions/{session_id}/bro-threads/{imported_thread['thread_id']}/open",
            json={"target_persona_id": "forge"},
        )
        await asyncio.wait_for(subscription_started.wait(), timeout=1.0)

    assert response.status_code == 200
    assert subscription_calls
    assert unsubscribe_calls == []
    opened = response.json()
    opened_thread = opened["bro_threads"][0]
    assert opened_thread["timeline_status"] == "failed"
    assert opened_thread["timeline_error"] == "Timed out reading Codex thread history."
    assert opened["bro_timeline_turns"] == []
    assert not any(task["metadata"].get("source_kind") == "codex_thread_history" for task in opened["tasks"])


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
