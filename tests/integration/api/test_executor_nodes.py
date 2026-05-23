from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import PublicAuthStore
from newbro.communication import persona_pool
from newbro.executors.node import registry as node_registry
from newbro.executors.node.registry import _hash_token
from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.runtime import Settings
from newbro.runtime.container import RuntimeContainer


def _build_app(tmp_path):
    app = create_app()
    app.state.runtime_container = RuntimeContainer(
        communication_model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="model_reply", reply_override="Noted.")}
        ),
        settings=Settings(detached_executor_enabled=True),
    )
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    return app


async def _redeem(client: AsyncClient, app, code: str = "invite-test"):
    await app.state.public_auth_store.create_invite(code)
    response = await client.post("/api/auth/invites/redeem", json={"code": code})
    assert response.status_code == 200
    return response.json()["user"]["user_id"]


@pytest.mark.anyio
async def test_executor_node_crud_and_rotation(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    monkeypatch.setattr(persona_pool, "PERSONAS_FILE", tmp_path / "personas.yaml")
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]

        create_response = await client.post(
            f"/api/sessions/{session_id}/executor-nodes",
            json={
                "name": "Studio Mac",
                "enabled_executors": ["acpx"],
                "acpx_agent": "openclaw",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        node_id = created["node"]["node_id"]
        assert created["token"]
        assert created["node"]["name"] == "Studio Mac"
        assert created["node"]["acpx_agent"] == "openclaw"
        assert created["node"]["connection_status"] == "disconnected"

        list_response = await client.get(f"/api/sessions/{session_id}/executor-nodes")
        assert list_response.status_code == 200
        listed = list_response.json()
        assert len(listed) == 1
        assert listed[0]["node_id"] == node_id
        assert "session_id" not in listed[0]
        assert "token" not in listed[0]

        reveal_response = await client.post(
            f"/api/sessions/{session_id}/executor-nodes/{node_id}/connect-command",
        )
        assert reveal_response.status_code == 200
        revealed = reveal_response.json()
        assert revealed["node"]["node_id"] == node_id
        assert revealed["token"] == created["token"]

        patch_response = await client.patch(
            f"/api/sessions/{session_id}/executor-nodes/{node_id}",
            json={"name": "Studio Mac Mini", "enabled_executors": ["codex"], "acpx_agent": None},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["name"] == "Studio Mac Mini"
        assert patch_response.json()["enabled_executors"] == ["codex"]
        assert patch_response.json()["acpx_agent"] is None

        rotate_response = await client.post(
            f"/api/sessions/{session_id}/executor-nodes/{node_id}/credentials/rotate",
        )
        assert rotate_response.status_code == 200
        rotated = rotate_response.json()
        assert rotated["node"]["node_id"] == node_id
        assert rotated["token"] != created["token"]

        reveal_response = await client.post(
            f"/api/sessions/{session_id}/executor-nodes/{node_id}/connect-command",
        )
        assert reveal_response.status_code == 200
        assert reveal_response.json()["token"] == rotated["token"]


@pytest.mark.anyio
async def test_delete_executor_node_rejects_bound_bros_until_unbound(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    monkeypatch.setattr(persona_pool, "PERSONAS_FILE", tmp_path / "personas.yaml")
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        create_response = await client.post(
            f"/api/sessions/{session_id}/executor-nodes",
            json={
                "name": "Travel Laptop",
                "enabled_executors": ["codex"],
            },
        )
        node_id = create_response.json()["node"]["node_id"]

        persona_response = await client.post(
            f"/api/sessions/{session_id}/personas",
            json={
                "name": "Alex",
                "avatar": "A",
                "base_prompt": "Be direct.",
                "executor_node_id": node_id,
            },
        )
        assert persona_response.status_code == 201

        # Simulate file drift: the persisted file says the bro is unbound, but
        # the live blackboard for this active session still has the binding.
        (tmp_path / "personas.yaml").write_text(
            "\n".join(
                [
                    "personas:",
                    '  - name: "Alex"',
                    f'    persona_id: "{persona_response.json()["persona_id"]}"',
                    '    avatar: "A"',
                    '    base_prompt: "Be direct."',
                    "    executor_node_id: null",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        delete_response = await client.delete(f"/api/sessions/{session_id}/executor-nodes/{node_id}")
        assert delete_response.status_code == 409

        patch_persona = await client.patch(
            f"/api/sessions/{session_id}/personas/{persona_response.json()['persona_id']}",
            json={"executor_node_id": None},
        )
        assert patch_persona.status_code == 200

        delete_response = await client.delete(f"/api/sessions/{session_id}/executor-nodes/{node_id}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"deleted": node_id}


@pytest.mark.anyio
async def test_executor_node_rejects_multiple_executor_families(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    monkeypatch.setattr(persona_pool, "PERSONAS_FILE", tmp_path / "personas.yaml")
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app)
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        response = await client.post(
            f"/api/sessions/{session_id}/executor-nodes",
            json={
                "name": "Mixed Node",
                "enabled_executors": ["codex", "acpx"],
                "acpx_agent": "openclaw",
            },
        )

    assert response.status_code == 400
    assert "exactly one executor family" in response.text


@pytest.mark.anyio
async def test_reveal_connect_command_requires_rotation_for_legacy_hash_only_nodes(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    monkeypatch.setattr(persona_pool, "PERSONAS_FILE", tmp_path / "personas.yaml")
    (tmp_path / "executor_nodes.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "executor_nodes:",
                '  - node_id: "node-legacy"',
                '    name: "Legacy Node"',
                "    enabled_executors:",
                '      - "codex"',
                "    raw_token: null",
                f'    token_hash: "{_hash_token("legacy-token")}"',
                '    token_hint: "lega...oken"',
                "    last_connected_at: null",
                "    last_seen_at: null",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    app = _build_app(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        user_id = await _redeem(client, app)
        await app.state.public_auth_store.claim_executor_node(user_id=user_id, node_id="node-legacy")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        reveal_response = await client.post(
            f"/api/sessions/{session_id}/executor-nodes/node-legacy/connect-command",
        )

    assert reveal_response.status_code == 409
    assert "Rotate credentials first" in reveal_response.text
