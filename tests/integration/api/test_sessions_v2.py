import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app


@pytest.mark.anyio
async def test_sessions_v2_create_and_get_snapshot():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/api/sessions")
        assert response.status_code == 200
        session_id = response.json()["session_id"]

        snapshot = await client.get(f"/api/sessions/{session_id}")
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert body["session_id"] == session_id
        assert body["voice_target_persona_id"] is None
        assert body["tasks"] == []
        assert "mutations" not in body
        assert "commands" not in body
        assert "recent_blackboard_writes" not in body

        conversation = await client.get(f"/api/sessions/{session_id}/conversation")
        assert conversation.status_code == 200
        assert conversation.json() == {
            "session_id": session_id,
            "conversation_history": [],
        }

        debug = await client.get(f"/api/sessions/{session_id}/debug")
        assert debug.status_code == 404

        diagnostics = await client.get(f"/api/sessions/{session_id}/diagnostics/timeline")
        assert diagnostics.status_code == 200
        assert diagnostics.json()["events"][0]["event_name"] == "api.session.created"

        target = await client.put(
            f"/api/sessions/{session_id}/voice-target",
            json={"target_persona_id": "persona-forge"},
        )
        assert target.status_code == 200
        snapshot = await client.get(f"/api/sessions/{session_id}")
        assert snapshot.status_code == 200
        assert snapshot.json()["voice_target_persona_id"] == "persona-forge"
