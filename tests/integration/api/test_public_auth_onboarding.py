from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import SESSION_COOKIE_NAME
from newbro.api.public_auth import PublicAuthStore
from newbro.connectors.voice.agora_convoai.module import AgoraConvoAIConnectorModule
from newbro.connectors.voice.agora_convoai.settings import AgoraConvoAIConnectorSettings
from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.executors.node.registry import ExecutorNodeRegistry
from newbro.runtime.executor_node_manager import ExecutorNodeManager
from newbro.runtime import Settings
from newbro.runtime.container import RuntimeContainer
from tests.helpers.asgi_websocket import ASGIWebSocketSession


def _build_app(tmp_path):
    app = create_app()
    container = RuntimeContainer(
        communication_model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="model_reply", reply_override="Noted.")}
        ),
        settings=Settings(detached_executor_enabled=True),
    )
    container.executor_node_manager = ExecutorNodeManager(
        detached_executor_types=container.settings.detached_executor_types,
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    app.state.runtime_container = container
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    return app


def _build_app_with_agora_connector(tmp_path):
    app = _build_app(tmp_path)
    app.include_router(
        AgoraConvoAIConnectorModule(
            settings=AgoraConvoAIConnectorSettings(
                app_id="agora-app-id",
                app_certificate="agora-app-certificate",
            )
        ).build_router()
    )
    return app


async def _redeem(client: AsyncClient, app, code: str):
    await app.state.public_auth_store.create_invite(code)
    response = await client.post("/api/auth/invites/redeem", json={"code": code})
    assert response.status_code == 200
    return response.json()["user"]["user_id"]


@pytest.mark.anyio
async def test_invited_user_bootstraps_default_session_and_bro(tmp_path):
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        user_id = await _redeem(client, app, "invite-one")
        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["user_id"] == user_id

        bootstrap = await client.get("/api/me/bootstrap")
        assert bootstrap.status_code == 200
        body = bootstrap.json()
        assert body["user"]["user_id"] == user_id
        assert body["session_id"].startswith("session-")
        assert body["default_persona_id"].startswith("persona-")
        assert body["default_bro_detail_session_id"].startswith("bro-detail-")

        snapshot = await client.get(f"/api/sessions/{body['session_id']}")
        assert snapshot.status_code == 200
        assert snapshot.json()["voice_target_persona_id"] == body["default_persona_id"]
        assert snapshot.json()["personas"][0]["persona_id"] == body["default_persona_id"]

        resumed = await client.get("/api/me/bootstrap")
        assert resumed.status_code == 200
        assert resumed.json()["session_id"] == body["session_id"]
        assert resumed.json()["default_persona_id"] == body["default_persona_id"]


@pytest.mark.anyio
async def test_browser_routes_require_authentication(tmp_path):
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/api/sessions")).status_code == 401
        assert (await client.get("/api/me/bootstrap")).status_code == 401
        assert (await client.get("/api/sessions/session-missing")).status_code == 401


@pytest.mark.anyio
async def test_user_cannot_access_other_user_session_or_node(tmp_path):
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_a:
        await _redeem(user_a, app, "invite-a")
        bootstrap_a = (await user_a.get("/api/me/bootstrap")).json()
        session_a = bootstrap_a["session_id"]
        create_node = await user_a.post(
            f"/api/sessions/{session_a}/executor-nodes",
            json={"name": "A laptop", "enabled_executors": ["codex"]},
        )
        assert create_node.status_code == 201
        node_id = create_node.json()["node"]["node_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_b:
        await _redeem(user_b, app, "invite-b")
        bootstrap_b = (await user_b.get("/api/me/bootstrap")).json()
        session_b = bootstrap_b["session_id"]

        assert (await user_b.get(f"/api/sessions/{session_a}")).status_code == 404
        assert (await user_b.get(f"/api/sessions/{session_a}/conversation")).status_code == 404
        assert (await user_b.get(f"/api/sessions/{session_a}/draft")).status_code == 404

        list_nodes = await user_b.get(f"/api/sessions/{session_b}/executor-nodes")
        assert list_nodes.status_code == 200
        assert list_nodes.json() == []

        reveal = await user_b.post(f"/api/sessions/{session_b}/executor-nodes/{node_id}/connect-command")
        assert reveal.status_code == 404
        rotate = await user_b.post(f"/api/sessions/{session_b}/executor-nodes/{node_id}/credentials/rotate")
        assert rotate.status_code == 404
        delete = await user_b.delete(f"/api/sessions/{session_b}/executor-nodes/{node_id}")
        assert delete.status_code == 404


@pytest.mark.anyio
async def test_user_cannot_bind_bro_to_other_user_node(tmp_path):
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_a:
        await _redeem(user_a, app, "invite-a")
        session_a = (await user_a.get("/api/me/bootstrap")).json()["session_id"]
        node = await user_a.post(
            f"/api/sessions/{session_a}/executor-nodes",
            json={"name": "A laptop", "enabled_executors": ["codex"]},
        )
        node_id = node.json()["node"]["node_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_b:
        await _redeem(user_b, app, "invite-b")
        bootstrap_b = (await user_b.get("/api/me/bootstrap")).json()
        session_b = bootstrap_b["session_id"]
        persona_id = bootstrap_b["default_persona_id"]

        bind = await user_b.patch(
            f"/api/sessions/{session_b}/personas/{persona_id}",
            json={"executor_node_id": node_id},
        )
        assert bind.status_code == 400


@pytest.mark.anyio
async def test_user_cannot_open_other_user_session_websocket(tmp_path):
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_a:
        await _redeem(user_a, app, "invite-a")
        session_a = (await user_a.get("/api/me/bootstrap")).json()["session_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_b:
        await _redeem(user_b, app, "invite-b")
        user_b_cookie = user_b.cookies.get(SESSION_COOKIE_NAME)
        assert user_b_cookie

    with pytest.raises(RuntimeError, match="WebSocket connection rejected"):
        async with ASGIWebSocketSession(
            app,
            f"/api/sessions/{session_a}/stream",
            headers=[(b"cookie", f"{SESSION_COOKIE_NAME}={user_b_cookie}".encode())],
        ):
            pass

    with pytest.raises(RuntimeError, match="WebSocket connection rejected"):
        async with ASGIWebSocketSession(app, f"/api/sessions/{session_a}/stream"):
            pass


@pytest.mark.anyio
async def test_agora_connector_stt_prepare_and_start_are_owner_scoped(tmp_path):
    app = _build_app_with_agora_connector(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as anonymous:
        assert (
            await anonymous.post(
                "/api/connectors/agora-convoai/stt/sessions/prepare",
                json={"synapse_session_id": "session-missing", "assigned_bro_id": "bro-1"},
            )
        ).status_code == 401

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_a:
        await _redeem(user_a, app, "invite-a")
        session_a = (await user_a.get("/api/me/bootstrap")).json()["session_id"]
        prepared = await user_a.post(
            "/api/connectors/agora-convoai/stt/sessions/prepare",
            json={"synapse_session_id": session_a, "assigned_bro_id": "bro-1"},
        )
        assert prepared.status_code == 200
        prepared_stt_session_id = prepared.json()["prepared_stt_session_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as user_b:
        await _redeem(user_b, app, "invite-b")
        assert (
            await user_b.post(
                "/api/connectors/agora-convoai/stt/sessions/prepare",
                json={"synapse_session_id": session_a, "assigned_bro_id": "bro-1"},
            )
        ).status_code == 404
        assert (
            await user_b.post(
                "/api/connectors/agora-convoai/stt/sessions/start",
                json={"prepared_stt_session_id": prepared_stt_session_id},
            )
        ).status_code == 404
