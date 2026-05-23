from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.connectors.host.config import ConnectorHostSettings
from newbro.communication.interaction_classifier import (
    InteractionClassification,
    ScriptedInteractionClassifier,
)
from newbro.protocol import InteractionType
from newbro.runtime.config import Settings
from newbro.runtime.drafts import DeterministicDraftRewriter
from newbro.service.app import create_app


def _classifier(interaction_type: InteractionType) -> ScriptedInteractionClassifier:
    return ScriptedInteractionClassifier(
        {},
        default=InteractionClassification(
            interaction_type=interaction_type,
            confidence=1.0,
            reason="integration-test",
        ),
    )


@pytest.mark.anyio
async def test_typed_message_dispatch_plan_confirm_status_stop_and_events(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    app = create_app(
        settings=Settings(),
        frontend_dist=dist_dir,
        connector_settings=ConnectorHostSettings(enabled=False),
    )
    app.state.runtime_container.draft_rewriter = DeterministicDraftRewriter()
    app.state.runtime_container.interaction_classifier = _classifier(InteractionType.DELEGATION)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]

        staged = await client.post(
            f"/api/sessions/{session_id}/messages",
            json={
                "type": "stt_final",
                "text": "让 Hermes 看一下 new console 的 Home page，参考 Linear，不要改代码，给我 proposal。",
                "language": "zh-CN",
            },
        )
        assert staged.status_code == 200
        staged_payload = staged.json()
        assert staged_payload["should_speak"] is False
        assert staged_payload["dispatch_plan_id"]
        assert staged_payload["draft_revision_id"]
        assert staged_payload["response_text"] == ""

        confirmed = await client.post(f"/api/dispatch-plans/{staged_payload['dispatch_plan_id']}/confirm")
        assert confirmed.status_code == 200
        confirmed_payload = confirmed.json()
        assert confirmed_payload["task_id"]
        assert confirmed_payload["should_speak"] is True
        assert "Sent to codex" in confirmed_payload["response_text"]

        progress = await client.post(
            f"/api/tasks/{confirmed_payload['task_id']}/events",
            json={
                "agent_id": "hermes",
                "type": "agent.progress",
                "message": "Compared Home page against Linear.",
                "importance": "low",
                "delivery": "silent_ui",
            },
        )
        assert progress.status_code == 200
        assert progress.json()["should_speak"] is False

        status = await client.get(f"/api/tasks/{confirmed_payload['task_id']}/status")
        assert status.status_code == 200
        assert "Compared Home page against Linear." in status.json()["latest_summary"]

        blocked = await client.post(
            f"/api/tasks/{confirmed_payload['task_id']}/events",
            json={
                "agent_id": "hermes",
                "type": "agent.blocked",
                "message": "Hermes needs the prototype URL.",
                "importance": "high",
                "delivery": "short_voice",
            },
        )
        assert blocked.status_code == 200
        assert blocked.json()["should_speak"] is True
        assert blocked.json()["response_text"] == "Hermes needs the prototype URL."

        stopped = await client.post(f"/api/tasks/{confirmed_payload['task_id']}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["spoken_response"] == "Stopped."


@pytest.mark.anyio
async def test_agora_events_api_keeps_partial_silent_and_final_decision_runtime_owned(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    app = create_app(
        settings=Settings(),
        frontend_dist=dist_dir,
        connector_settings=ConnectorHostSettings(enabled=False),
    )
    app.state.runtime_container.draft_rewriter = DeterministicDraftRewriter()
    app.state.runtime_container.interaction_classifier = _classifier(InteractionType.DELEGATION)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]

        partial = await client.post(
            f"/api/sessions/{session_id}/agora-events",
            json={
                "event_id": "event-partial",
                "session_id": session_id,
                "type": "stt.partial",
                "text": "Ask Codex",
                "target_persona_id": "codex",
            },
        )
        assert partial.status_code == 200
        assert partial.json()["should_speak"] is False

        conversation = (await client.get(f"/api/sessions/{session_id}/conversation")).json()
        assert conversation["conversation_history"] == []

        final = await client.post(
            f"/api/sessions/{session_id}/agora-events",
            json={
                "event_id": "event-final",
                "session_id": session_id,
                "type": "stt.final",
                "text": "Ask Codex to inspect the docs.",
                "target_persona_id": "codex",
            },
        )
        assert final.status_code == 200
        payload = final.json()
        assert payload["should_speak"] is False
        assert payload["dispatch_plan_id"]
        assert payload["draft_revision_id"]

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        assert snapshot["voice_target_persona_id"] == "codex"
        assert snapshot["draft_session"]["current_revision_id"] == payload["draft_revision_id"]
        assert snapshot["draft_session"]["asr_turns"] == []


@pytest.mark.anyio
async def test_agora_events_api_live_cadence_revision_stream_and_stale_send_guard(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    app = create_app(
        settings=Settings(live_interaction_classifier_interval_seconds=1.0),
        frontend_dist=dist_dir,
        connector_settings=ConnectorHostSettings(enabled=False),
    )
    app.state.runtime_container.draft_rewriter = DeterministicDraftRewriter()
    app.state.runtime_container.interaction_classifier = _classifier(InteractionType.DELEGATION)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_id = (await client.post("/api/sessions")).json()["session_id"]

        first = await client.post(
            f"/api/sessions/{session_id}/agora-events",
            json={
                "event_id": "event-partial-1",
                "session_id": session_id,
                "type": "stt.partial",
                "text": "Plan a trip to the US",
                "timestamp_ms": 0,
                "target_persona_id": "codex",
            },
        )
        await asyncio.sleep(0)
        skipped = await client.post(
            f"/api/sessions/{session_id}/agora-events",
            json={
                "event_id": "event-partial-2",
                "session_id": session_id,
                "type": "stt.partial",
                "text": "Plan a trip to the US actually",
                "timestamp_ms": 500,
                "target_persona_id": "codex",
            },
        )
        corrected = await client.post(
            f"/api/sessions/{session_id}/agora-events",
            json={
                "event_id": "event-partial-3",
                "session_id": session_id,
                "type": "stt.partial",
                "text": "Plan a trip to the US actually make it UK",
                "timestamp_ms": 1000,
                "target_persona_id": "codex",
            },
        )
        await asyncio.sleep(0)
        final = await client.post(
            f"/api/sessions/{session_id}/agora-events",
            json={
                "event_id": "event-final",
                "session_id": session_id,
                "type": "stt.final",
                "text": "Plan a trip to the US actually make it UK",
                "timestamp_ms": 1100,
                "target_persona_id": "codex",
            },
        )

        assert first.status_code == 200
        assert skipped.status_code == 200
        assert corrected.status_code == 200
        assert final.status_code == 200
        assert [first.json()["should_speak"], skipped.json()["should_speak"], corrected.json()["should_speak"], final.json()["should_speak"]] == [False, False, False, False]
        assert skipped.json()["ui_updates"][0]["type"] == "transcript.partial"
        first_revision = (await client.get(f"/api/sessions/{session_id}")).json()["draft_session"]["snapshots"][0]["draft_revision_id"]
        latest_revision = final.json()["draft_revision_id"]
        assert first_revision
        assert latest_revision
        assert latest_revision != first_revision

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        draft_session = snapshot["draft_session"]
        assert draft_session["current_revision_id"] == latest_revision
        assert draft_session["current_draft"]["text"] == "Plan a trip to the US actually make it UK."
        assert draft_session["asr_turns"] == []
        assert [item["source_boundary"] for item in draft_session["snapshots"]] == [
            "stt.partial",
            "stt.partial",
            "stt.final",
        ]

        diagnostics = (
            await client.get(
                f"/api/sessions/{session_id}/diagnostics/timeline",
                params={"event_prefix": "comm.", "limit": 20},
            )
        ).json()["events"]
        classified = [event for event in diagnostics if event["event_name"] == "comm.interaction.classified"]
        live_updates = [event for event in diagnostics if event["event_name"] == "comm.live_draft.updated"]
        stages = [event for event in diagnostics if event["event_name"] == "comm.live_draft.stage"]
        assert len(classified) == 2
        assert len(live_updates) == 3
        assert any(event["details"]["stage"] == "final_checkpoint_reused" for event in stages)
        assert live_updates[-1]["details"]["draft_revision_id"] == latest_revision
        assert live_updates[-1]["details"]["source_boundary"] == "stt.final"

        stale_send = await client.post(
            f"/api/sessions/{session_id}/draft/send",
            json={
                "draft_session_id": draft_session["id"],
                "draft_revision_id": first_revision,
            },
        )
        assert stale_send.status_code == 409
        assert "Draft revision" in stale_send.json()["detail"]

        sent = await client.post(
            f"/api/sessions/{session_id}/draft/send",
            json={
                "draft_session_id": draft_session["id"],
                "draft_revision_id": latest_revision,
            },
        )
        assert sent.status_code == 200
        assert sent.json()["draft_revision_id"] == latest_revision
