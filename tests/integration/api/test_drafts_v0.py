import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.communication import persona_pool
from newbro.runtime.config import Settings
from newbro.runtime.container import RuntimeContainer
from newbro.runtime.drafts import DraftRewriteInput, DraftRewriter
from newbro.communication.models.scripted import ScriptedCommunicationModel, ScriptedPlan
from newbro.executors.node import registry as node_registry
from newbro.protocol import Draft, Persona
from tests.helpers.asgi_websocket import ASGIWebSocketSession


class FakeDraftRewriter(DraftRewriter):
    async def rewrite(self, payload: DraftRewriteInput) -> Draft:
        text = (payload.new_turn.normalized_text or payload.new_turn.raw_text).strip()
        draft_text = text
        if "YouMind" in text:
            draft_text = "Make it like YouMind."
        elif "ElevenLabs" in text:
            draft_text = "Make it like ElevenLabs."
        if "Do not add dependencies" in text:
            draft_text = f"{draft_text} Do not add dependencies."
        return Draft(
            text=draft_text,
        )


def _runtime_container(*, settings: Settings | None = None) -> RuntimeContainer:
    return RuntimeContainer(
        communication_model=ScriptedCommunicationModel({"__default__": ScriptedPlan(reply_override="ok")}),
        settings=settings or Settings(),
        draft_rewriter=FakeDraftRewriter(),
    )


async def _register_node_once(app, *, node_id: str, token: str) -> None:
    async with ASGIWebSocketSession(app, "/api/executors/control") as websocket:
        await websocket.send_json(
            {
                "type": "register_node",
                "node_id": node_id,
                "token": token,
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


@pytest.mark.anyio
async def test_draft_api_requires_configured_llm_rewriter():
    app = create_app()
    app.state.runtime_container = RuntimeContainer(
        communication_model=ScriptedCommunicationModel({"__default__": ScriptedPlan(reply_override="ok")}),
        settings=Settings(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        response = await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Improve the page."},
        )

    assert response.status_code == 503
    assert "configured LLM provider" in response.json()["detail"]


@pytest.mark.anyio
async def test_draft_api_asr_clear_send_freeze():
    app = create_app()
    app.state.runtime_container = _runtime_container()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        response = await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Make it like ElevenLabs."},
        )
        assert response.status_code == 200
        draft_session = response.json()
        assert draft_session["current_draft"]["text"]

        response = await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "No, make it like YouMind. Do not add dependencies."},
        )
        draft_session = response.json()
        assert "YouMind" in draft_session["current_draft"]["text"]
        assert "Do not add dependencies." in draft_session["current_draft"]["text"]

        send_response = await client.post(
            f"/api/sessions/{session_id}/draft/send",
            json={"draft_session_id": draft_session["id"]},
        )
        assert send_response.status_code == 200
        task_id = send_response.json()["task_id"]

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        assert snapshot["draft_session"] is None
        task = next(item for item in snapshot["tasks"] if item["task_id"] == task_id)
        assert task["metadata"]["immutable"] is True
        assert task["metadata"]["source_kind"] == "draft_session"
        assert task["metadata"]["draft_session_id"] == draft_session["id"]
        assert "Do not add dependencies." in task["metadata"]["draft_text"]

        response = await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Actually change the direction."},
        )
        assert response.status_code == 200
        new_draft = response.json()
        assert new_draft["id"] != draft_session["id"]
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        frozen = next(item for item in snapshot["tasks"] if item["task_id"] == task_id)
        assert frozen["goal"] == task["goal"]


@pytest.mark.anyio
async def test_clear_draft_does_not_remove_tasks():
    app = create_app()
    app.state.runtime_container = _runtime_container()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        draft = (await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Improve the page."},
        )).json()
        await client.post(f"/api/sessions/{session_id}/draft/send", json={"draft_session_id": draft["id"]})
        draft2 = (await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Prepare another version."},
        )).json()
        response = await client.post(
            f"/api/sessions/{session_id}/draft/clear",
            json={"draft_session_id": draft2["id"]},
        )
        assert response.status_code == 200
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        assert snapshot["draft_session"] is None
        assert len(snapshot["tasks"]) == 1


@pytest.mark.anyio
async def test_send_draft_assigns_runtime_bro_and_exposes_progress_state():
    app = create_app()
    app.state.runtime_container = _runtime_container(settings=Settings(detached_executor_enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_persona(
            Persona(
                persona_id="persona-rook",
                name="Rook",
                avatar="fox",
                base_prompt="Be direct.",
                executor_node_id="node-offline",
            )
        )
        draft = (await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Prepare a short execution plan.", "assigned_bro_id": "persona-rook"},
        )).json()

        response = await client.post(
            f"/api/sessions/{session_id}/draft/send",
            json={"draft_session_id": draft["id"]},
        )

        assert response.status_code == 200
        task_id = response.json()["task_id"]
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        bros = (await client.get(f"/api/sessions/{session_id}/bros")).json()
        persona = next(item for item in bros["bros"] if item["persona_id"] == "persona-rook")
        task = next(item for item in snapshot["tasks"] if item["task_id"] == task_id)
        assert persona["status"] == "busy"
        assert "current_task_id" not in persona
        assert task["preferred_executor"] == "codex"
        assert task["session_affinity"]
        assert task["metadata"]["persona_id"] == "persona-rook"
        assert task["metadata"]["persona_name"] == "Rook"
        assert task["metadata"]["executor_node_id"] == "node-offline"
        assert task["metadata"]["assigned_bro_id"] == "persona-rook"


@pytest.mark.anyio
async def test_send_draft_prefers_bound_node_executor_family(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    monkeypatch.setattr(persona_pool, "PERSONAS_FILE", tmp_path / "personas.yaml")
    app = create_app()
    app.state.runtime_container = _runtime_container(settings=Settings(detached_executor_enabled=True))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        node_issue = (
            await client.post(
                f"/api/sessions/{session_id}/executor-nodes",
                json={"name": "OpenClaw Node", "enabled_executors": ["acpx"], "acpx_agent": "openclaw"},
            )
        ).json()
        node_id = node_issue["node"]["node_id"]

        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_persona(
            Persona(
                persona_id="persona-rook",
                name="Rook",
                avatar="fox",
                base_prompt="Be direct.",
                executor_node_id=node_id,
            )
        )
        draft = (
            await client.post(
                f"/api/sessions/{session_id}/draft/asr-turns",
                json={"raw_text": "Prepare a short execution plan.", "assigned_bro_id": "persona-rook"},
            )
        ).json()

        response = await client.post(
            f"/api/sessions/{session_id}/draft/send",
            json={"draft_session_id": draft["id"]},
        )

        assert response.status_code == 200
        task_id = response.json()["task_id"]
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        task = next(item for item in snapshot["tasks"] if item["task_id"] == task_id)
        assert task["preferred_executor"] == "acpx"
        assert task["metadata"]["executor_node_id"] == node_id


@pytest.mark.anyio
async def test_rebinding_bro_rotates_detail_session_without_deleting_old_tasks(monkeypatch, tmp_path):
    monkeypatch.setattr(node_registry, "EXECUTOR_NODES_FILE", tmp_path / "executor_nodes.yaml")
    monkeypatch.setattr(persona_pool, "PERSONAS_FILE", tmp_path / "personas.yaml")
    app = create_app()
    app.state.runtime_container = _runtime_container(settings=Settings(detached_executor_enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        persona_response = await client.post(
            f"/api/sessions/{session_id}/personas",
            json={"name": "Rook", "avatar": "fox", "base_prompt": "Be direct."},
        )
        assert persona_response.status_code == 201
        persona = persona_response.json()
        original_detail_session_id = persona["bro_detail_session_id"]

        draft = (await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Prepare a short execution plan.", "assigned_bro_id": persona["persona_id"]},
        )).json()
        send_response = await client.post(
            f"/api/sessions/{session_id}/draft/send",
            json={"draft_session_id": draft["id"]},
        )
        assert send_response.status_code == 200

        node_issue = (await client.post(
            f"/api/sessions/{session_id}/executor-nodes",
            json={"name": "Studio Mac", "enabled_executors": ["codex"]},
        )).json()
        node_id = node_issue["node"]["node_id"]
        await _register_node_once(app, node_id=node_id, token=node_issue["token"])
        patch_response = await client.patch(
            f"/api/sessions/{session_id}/personas/{persona['persona_id']}",
            json={"executor_node_id": node_id},
        )
        assert patch_response.status_code == 200
        updated_persona = patch_response.json()
        assert updated_persona["bro_detail_session_id"] != original_detail_session_id

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        assert len(snapshot["tasks"]) == 1
        old_task = snapshot["tasks"][0]
        assert old_task["metadata"]["bro_detail_session_id"] == original_detail_session_id
        assert updated_persona["bro_detail_session_id"] != original_detail_session_id


@pytest.mark.anyio
async def test_send_draft_rejects_busy_runtime_bro_without_clearing_draft():
    app = create_app()
    app.state.runtime_container = _runtime_container(settings=Settings(detached_executor_enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        session = app.state.runtime_container.get_session(session_id)
        await session.blackboard.put_persona(
            Persona(
                persona_id="persona-rook",
                name="Rook",
                status="busy",
            )
        )
        draft = (await client.post(
            f"/api/sessions/{session_id}/draft/asr-turns",
            json={"raw_text": "Prepare a short execution plan.", "assigned_bro_id": "persona-rook"},
        )).json()

        response = await client.post(
            f"/api/sessions/{session_id}/draft/send",
            json={"draft_session_id": draft["id"]},
        )

        assert response.status_code == 409
        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        assert snapshot["draft_session"]["id"] == draft["id"]
        assert snapshot["tasks"] == []
