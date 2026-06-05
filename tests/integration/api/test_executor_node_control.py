from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.executors.node import registry as node_registry
from newbro.protocol import (
    BindingStatus,
    ExecutionRun,
    ExecutionSession,
    InteractionRequest,
    InteractionRequestKind,
    InteractionRequestStatus,
    Persona,
    RunStatus,
    SessionBinding,
    Task,
    TaskStatus,
)
from newbro.runtime import Settings

from tests.helpers.asgi_websocket import ASGIWebSocketSession


async def _wait_for_snapshot(client: AsyncClient, session_id: str, predicate, timeout: float = 4.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        if predicate(snapshot):
            return snapshot
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Timed out waiting for expected snapshot state.")
        await asyncio.sleep(0.05)


def _build_app():
    return create_app(
        settings=Settings(
            detached_executor_enabled=True,
        )
    )


async def _issue_node(app, *, name: str = "Node 1", executors: list[str] | None = None):
    return await app.state.runtime_container.executor_node_manager.create_node(
        name=name,
        enabled_executors=executors or ["codex"],
    )


@pytest.mark.anyio
async def test_detached_executor_waits_for_host_when_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_task(
            Task(
                task_id="task-host-wait",
                root_task_id="task-host-wait",
                title="Hosted task",
                goal="Hosted task",
                status=TaskStatus.QUEUED,
                preferred_executor="codex",
            )
        )
        session.schedule_execution()

        snapshot = await _wait_for_snapshot(
            client,
            session_id,
            lambda snap: snap["tasks"][0]["status"] == "waiting_executor",
        )

    assert snapshot["execution_runs"][0]["status"] == "waiting_executor"
    assert snapshot["summaries"][0]["latest_user_visible_status"] == "waiting_executor"
    codex_capability = next(
        capability
        for capability in snapshot["executor_capabilities"]
        if capability["executor_type"] == "codex"
    )
    assert codex_capability["connected"] is False
    assert codex_capability["availability_reason"] == "node_disconnected"


@pytest.mark.anyio
async def test_executor_node_registration_requeues_waiting_task_and_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    app = _build_app()
    issue = await _issue_node(app, name="Node 1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_task(
            Task(
                task_id="task-hosted",
                root_task_id="task-hosted",
                title="Hosted task",
                goal="Hosted task",
                status=TaskStatus.QUEUED,
                preferred_executor="codex",
                metadata={"executor_node_id": issue.node.node_id},
            )
        )
        session.schedule_execution()
        await _wait_for_snapshot(
            client,
            session_id,
            lambda snap: snap["tasks"][0]["status"] == "waiting_executor",
        )

        async with ASGIWebSocketSession(app, "/api/executors/control") as websocket:
            await websocket.send_json(
                {
                    "type": "register_node",
                    "node_id": issue.node.node_id,
                    "token": issue.token,
                    "executors": [
                        {
                            "executor_type": "codex",
                            "supports_resume": True,
                            "supports_follow_up": True,
                            "supports_pause": True,
                            "supports_cancel": True,
                        }
                    ],
                }
            )
            ack = await websocket.receive_json()
            assert ack["type"] == "ack"
            dispatch = await websocket.receive_json()
            assert dispatch["type"] == "dispatch_run"
            await websocket.send_json(
                {
                    "type": "run_event",
                    "run_id": dispatch["run_id"],
                    "execution_session_id": dispatch["execution_session_id"],
                    "executor_type": "codex",
                    "session_id": "codex-session-1",
                    "event_type": "progress",
                    "message": "working",
                }
            )
            assert (await websocket.receive_json())["type"] == "ack"
            await websocket.send_json(
                {
                    "type": "run_event",
                    "run_id": dispatch["run_id"],
                    "execution_session_id": dispatch["execution_session_id"],
                    "executor_type": "codex",
                    "session_id": "codex-session-1",
                    "event_type": "completed",
                    "message": "done",
                }
            )
            assert (await websocket.receive_json())["type"] == "ack"
            snapshot = await _wait_for_snapshot(
                client,
                session_id,
                lambda snap: snap["tasks"][0]["status"] == "completed",
            )

    assert snapshot["execution_runs"][-1]["status"] == "completed"
    codex_capability = next(
        capability
        for capability in snapshot["executor_capabilities"]
        if capability["executor_type"] == "codex"
    )
    assert codex_capability["connected"] is True
    assert codex_capability["node_id"] == issue.node.node_id


@pytest.mark.anyio
async def test_executor_node_connection_invalidates_bro_list_for_subscribers(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    app = _build_app()
    issue = await _issue_node(app, name="Node 1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id=issue.node.node_id,
                bro_detail_session_id="detail-forge",
            )
        )
        subscriber = session.subscribe()

        try:
            async def next_bro_list_invalidated():
                deadline = asyncio.get_running_loop().time() + 1.0
                while asyncio.get_running_loop().time() < deadline:
                    event = await asyncio.wait_for(
                        subscriber.get(),
                        timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
                    )
                    if event.type == "bro_list_invalidated":
                        return event
                raise AssertionError("Timed out waiting for bro_list_invalidated event.")

            async with ASGIWebSocketSession(app, "/api/executors/control") as websocket:
                await websocket.send_json(
                    {
                        "type": "register_node",
                        "node_id": issue.node.node_id,
                        "token": issue.token,
                        "executors": [
                            {
                                "executor_type": "codex",
                                "supports_resume": True,
                                "supports_follow_up": True,
                                "supports_pause": True,
                                "supports_cancel": True,
                            }
                        ],
                    }
                )
                assert (await websocket.receive_json())["type"] == "ack"
                connected = await next_bro_list_invalidated()
                assert connected.reason == "executor_node_connected"
                assert connected.node_id == issue.node.node_id

            disconnected = await next_bro_list_invalidated()
            assert disconnected.reason == "executor_node_disconnected"
            assert disconnected.node_id == issue.node.node_id
        finally:
            session.unsubscribe(subscriber)


@pytest.mark.anyio
async def test_executor_node_connection_invalidates_bro_list_on_session_websocket(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    app = _build_app()
    issue = await _issue_node(app, name="Node 1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id=issue.node.node_id,
                bro_detail_session_id="detail-forge",
            )
        )

        async def next_bro_list_invalidated(websocket):
            deadline = asyncio.get_running_loop().time() + 1.0
            while asyncio.get_running_loop().time() < deadline:
                event = await websocket.receive_json(
                    timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
                )
                if event["type"] == "bro_list_invalidated":
                    return event
            raise AssertionError("Timed out waiting for bro_list_invalidated websocket event.")

        async with ASGIWebSocketSession(app, f"/api/sessions/{session_id}/stream") as stream:
            initial = await stream.receive_json()
            assert initial["type"] == "snapshot"

            async with ASGIWebSocketSession(app, "/api/executors/control") as executor:
                await executor.send_json(
                    {
                        "type": "register_node",
                        "node_id": issue.node.node_id,
                        "token": issue.token,
                        "executors": [
                            {
                                "executor_type": "codex",
                                "supports_resume": True,
                                "supports_follow_up": True,
                                "supports_pause": True,
                                "supports_cancel": True,
                            }
                        ],
                    }
                )
                assert (await executor.receive_json())["type"] == "ack"
                connected = await next_bro_list_invalidated(stream)
                assert connected["reason"] == "executor_node_connected"
                assert connected["node_id"] == issue.node.node_id

            disconnected = await next_bro_list_invalidated(stream)
            assert disconnected["reason"] == "executor_node_disconnected"
            assert disconnected["node_id"] == issue.node.node_id


@pytest.mark.anyio
async def test_executor_node_registration_refreshes_imported_codex_threads_for_subscribers(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    app = _build_app()
    issue = await _issue_node(app, name="Node 1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id=issue.node.node_id,
                bro_detail_session_id="detail-forge",
            )
        )
        subscriber = session.subscribe()

        async with ASGIWebSocketSession(app, "/api/executors/control") as websocket:
            await websocket.send_json(
                {
                    "type": "register_node",
                    "node_id": issue.node.node_id,
                    "token": issue.token,
                    "executors": [
                        {
                            "executor_type": "codex",
                            "supports_resume": True,
                            "supports_follow_up": True,
                            "supports_pause": True,
                            "supports_cancel": True,
                            "supports_thread_list": True,
                        }
                    ],
                }
            )
            ack = await websocket.receive_json()
            assert ack["type"] == "ack"

            list_command = await websocket.receive_json()
            assert list_command["type"] == "list_codex_threads"
            await websocket.send_json(
                {
                    "type": "codex_threads_listed",
                    "request_id": list_command["request_id"],
                    "node_id": issue.node.node_id,
                    "executor_type": "codex",
                    "ok": True,
                    "threads": [
                        {
                            "thread_id": "codex-native-thread-1",
                            "session_id": "codex-native-thread-1",
                            "preview": "Imported thread preview",
                            "title": "Imported thread",
                            "cwd": "/tmp/workspace",
                            "path": "/tmp/codex-thread.jsonl",
                            "status": "idle",
                            "created_at": 1779850000,
                            "updated_at": 1779850100,
                            "cli_version": "0.133.0",
                            "source": "vscode",
                        }
                    ],
                }
            )
            assert (await websocket.receive_json())["type"] == "ack"

            deadline = asyncio.get_running_loop().time() + 4.0
            imported_snapshot = None
            while asyncio.get_running_loop().time() < deadline:
                event = await asyncio.wait_for(subscriber.get(), timeout=4.0)
                if event.type == "snapshot" and event.snapshot.bro_threads:
                    imported_snapshot = event.snapshot
                    break

        session.unsubscribe(subscriber)

    assert imported_snapshot is not None
    imported_thread = imported_snapshot.bro_threads[0]
    assert imported_thread.thread_id.startswith("codex-import-")
    assert imported_thread.diagnostics["codex_thread_id"] == "codex-native-thread-1"
    assert imported_thread.diagnostics["codex_cwd"] == "/tmp/workspace"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("invalid_payload", "message_type"),
    [
        (
            {
                "type": "run_event",
                "run_id": "run-1",
            },
            "run_event",
        ),
        (
            {
                "type": "interaction_state",
                "run_id": "run-1",
            },
            "interaction_state",
        ),
        (
            {
                "type": "node_status",
                "status": "ready",
            },
            "node_status",
        ),
    ],
)
async def test_executor_control_invalid_message_ack_does_not_close_connection(
    monkeypatch,
    tmp_path,
    invalid_payload: dict[str, object],
    message_type: str,
):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    app = _build_app()
    issue = await _issue_node(app, name="Node 1")

    async with ASGIWebSocketSession(app, "/api/executors/control") as websocket:
        await websocket.send_json(
            {
                "type": "register_node",
                "node_id": issue.node.node_id,
                "token": issue.token,
                "executors": [
                    {
                        "executor_type": "codex",
                        "supports_resume": True,
                        "supports_follow_up": True,
                        "supports_pause": True,
                        "supports_cancel": True,
                    }
                ],
            }
        )
        assert (await websocket.receive_json())["type"] == "ack"

        await websocket.send_json(invalid_payload)
        invalid_ack = await websocket.receive_json()
        assert invalid_ack == {
            "type": "ack",
            "message_type": message_type,
            "ok": False,
            "run_id": None,
            "detail": "invalid_payload",
        }

        await websocket.send_json(
            {
                "type": "node_status",
                "node_id": issue.node.node_id,
                "status": "ready",
            }
        )
        valid_ack = await websocket.receive_json()
        assert valid_ack == {
            "type": "ack",
            "message_type": "node_status",
            "ok": True,
            "run_id": None,
            "detail": "ok",
        }


@pytest.mark.anyio
async def test_resolve_interaction_request_routes_native_response_to_executor_node(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    app = _build_app()
    issue = await _issue_node(app, name="Node 1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_task(
            Task(
                task_id="task-native",
                root_task_id="task-native",
                title="Native task",
                goal="Native task",
                status=TaskStatus.WAITING_USER_INPUT,
                preferred_executor="codex",
                metadata={"executor_node_id": issue.node.node_id},
            )
        )
        await session.blackboard.put_session(
            ExecutionSession(
                execution_session_id="exec-native",
                task_id="task-native",
                base_executor_id="codex",
                executor_node_id=issue.node.node_id,
                active_run_id="run-native",
                latest_run_id="run-native",
                run_ids=["run-native"],
            )
        )
        await session.blackboard.put_binding(
            SessionBinding(
                task_id="task-native",
                execution_session_id="exec-native",
                executor_node_id=issue.node.node_id,
                session_id="session-native",
                claimed_by="worker-native",
                claim_expires_at="2026-04-16T00:10:00+00:00",
                binding_status=BindingStatus.ACTIVE,
            )
        )
        await session.blackboard.put_run(
            ExecutionRun(
                run_id="run-native",
                task_id="task-native",
                execution_session_id="exec-native",
                executor_type="codex",
                status=RunStatus.BLOCKED,
                block_reason="Need approval.",
            )
        )
        await session.blackboard.put_interaction_request(
            InteractionRequest(
                request_id="ireq-native",
                task_id="task-native",
                execution_session_id="exec-native",
                run_id="run-native",
                executor_type="codex",
                kind=InteractionRequestKind.PERMISSION,
                status=InteractionRequestStatus.PENDING,
                prompt="Need approval.",
                available_actions=["approve"],
                opaque={
                    "native_response": {
                        "request_id": "req-native",
                        "method": "item/permissions/requestApproval",
                        "params": {"prompt": "Need approval."},
                    }
                },
                created_at="2026-04-06T00:00:00+00:00",
            )
        )

        async with ASGIWebSocketSession(app, "/api/executors/control") as websocket:
            await websocket.send_json(
                {
                    "type": "register_node",
                    "node_id": issue.node.node_id,
                    "token": issue.token,
                    "executors": [
                        {
                            "executor_type": "codex",
                            "supports_resume": True,
                            "supports_follow_up": True,
                            "supports_pause": True,
                            "supports_cancel": True,
                        }
                    ],
                }
            )
            assert (await websocket.receive_json())["type"] == "ack"
            response = await client.post(
                f"/api/sessions/{session_id}/interaction-requests/ireq-native/resolve",
                json={"action": "approve"},
            )
            assert response.status_code == 200
            command = await websocket.receive_json()

    assert command["type"] == "supply_interaction_response"
    assert command["interaction_request_id"] == "ireq-native"
    assert command["action"] == "approve"
