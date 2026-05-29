from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pytest

from newbro.connectors.base import ConnectorBindingRegistry, DuplicateBindingError
from newbro.connectors.voice.agora_convoai.models import (
    ConnectorSessionActivateRequest,
    ConnectorSessionDiagnostics,
    ConnectorSessionPrepareRequest,
    ConnectorSessionStopRequest,
)
from newbro.connectors.voice.agora_convoai.service import ActivatedConvoAISession, PreparedConvoAISession
from newbro.connectors.voice.agora_convoai.session_service import AgoraConnectorSessionService
from newbro.connectors.voice.agora_convoai.settings import AgoraConvoAIConnectorSettings
from newbro.protocol import AgoraVoiceEvent, AgoraVoiceEventType, RuntimeDecision


@dataclass
class _FakeTransport:
    created: int = 0
    agora_events: list[AgoraVoiceEvent] | None = None

    async def create_session(self) -> str:
        self.created += 1
        return "session-1"

    async def submit_agora_event(self, session_id: str, event: AgoraVoiceEvent) -> RuntimeDecision:
        if self.agora_events is None:
            self.agora_events = []
        self.agora_events.append(event)
        assert event.session_id == session_id
        return RuntimeDecision()

    async def watch_notification_texts(self, session_id: str):
        if False:
            yield session_id


@dataclass
class _FakeSpeaker:
    async def speak(self, runtime_session_id: str, text: str) -> None:
        return None


class _QueuedNotificationTransport(_FakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.notifications: asyncio.Queue[str | None] = asyncio.Queue()

    async def watch_notification_texts(self, session_id: str):
        while True:
            item = await self.notifications.get()
            if item is None:
                return
            yield item


class _FailingSpeaker:
    async def speak(self, runtime_session_id: str, text: str) -> None:
        raise RuntimeError("speaker failed")


class _CapturingConvoAIService:
    def __init__(self) -> None:
        self.last_prepare: dict[str, object] | None = None
        self.prepared_by_id: dict[str, PreparedConvoAISession] = {}
        self.next_prepared_id = 1

    async def prepare_session(self, **kwargs) -> PreparedConvoAISession:
        self.last_prepare = kwargs
        prepared = PreparedConvoAISession(
            prepared_session_id=f"prepared-{self.next_prepared_id}",
            app_id="agora-app",
            channel_name=str(kwargs["channel_name"]),
            token="token",
            uid=int(kwargs["user_uid"] or 101),
            user_rtm_uid="101-room",
            agent_uid=str(kwargs["agent_uid"]),
            agent_rtm_uid="9001-room",
            enable_string_uid=False,
            profile=str(kwargs["profile"]),
            display_name=kwargs["display_name"],
            diagnostics=ConnectorSessionDiagnostics(
                convoai_area="US",
                selected_url="https://fake-convoai.local/api",
                runtime_session_id=None,
                asr_vendor="deepgram",
                asr_credential_mode="managed",
                asr_model="nova-3",
                tts_vendor="minimax",
                tts_credential_mode="managed",
                tts_model="speech_2_6_turbo",
                agent_uid=str(kwargs["agent_uid"]),
                agent_rtm_uid="9001-room",
                rtc_uid=int(kwargs["user_uid"] or 101),
                rtm_user_id="101-room",
                enable_string_uid=False,
                enable_rtm=True,
                data_channel="rtm",
                enable_metrics=True,
                enable_error_message=True,
            ),
        )
        self.prepared_by_id[prepared.prepared_session_id] = prepared
        self.next_prepared_id += 1
        return prepared

    async def activate_session(self, prepared_session_id: str, *, chat_completions_url: str):
        prepared = self.prepared_by_id[prepared_session_id]
        return ActivatedConvoAISession(
            prepared_session_id=prepared.prepared_session_id,
            runtime_session_id="runtime-1",
            app_id=prepared.app_id,
            channel_name=prepared.channel_name,
            token=prepared.token,
            uid=prepared.uid,
            user_rtm_uid=prepared.user_rtm_uid,
            agent_uid=prepared.agent_uid,
            agent_rtm_uid=prepared.agent_rtm_uid,
            enable_string_uid=prepared.enable_string_uid,
            profile=prepared.profile,
            display_name=prepared.display_name,
            diagnostics=prepared.diagnostics.model_copy(
                update={"runtime_session_id": "runtime-1"},
            ),
        )

    async def stop_session(self, runtime_session_id: str) -> None:
        return None

    async def speak(self, runtime_session_id: str, text: str) -> None:
        return None


class _CleanupFailingConvoAIService(_CapturingConvoAIService):
    async def stop_session(self, runtime_session_id: str) -> None:
        raise RuntimeError("cleanup failed")


@pytest.mark.anyio
async def test_prepare_session_preserves_empty_string_instruction_overrides():
    service = _CapturingConvoAIService()
    session_service = AgoraConnectorSessionService(
        ConnectorBindingRegistry(_FakeTransport(), _FakeSpeaker()),
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="cert",
            agent_instructions="default instructions",
            agent_greeting="default greeting",
        ),
        convoai_service=service,
    )

    await session_service.prepare_session(
        ConnectorSessionPrepareRequest(
            channel_name="demo-room",
            agent_instructions="",
            agent_greeting="",
        )
    )

    assert service.last_prepare is not None
    assert service.last_prepare["agent_instructions"] == ""
    assert service.last_prepare["agent_greeting"] == ""


@pytest.mark.anyio
async def test_prepare_session_defaults_channel_name_to_synapse_session_id():
    service = _CapturingConvoAIService()
    session_service = AgoraConnectorSessionService(
        ConnectorBindingRegistry(_FakeTransport(), _FakeSpeaker()),
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="cert",
        ),
        convoai_service=service,
    )

    response = await session_service.prepare_session(
        ConnectorSessionPrepareRequest(
            synapse_session_id="session-existing",
        )
    )

    assert service.last_prepare is not None
    assert service.last_prepare["channel_name"] == "session-existing"
    assert response.channel_name == "session-existing"


@pytest.mark.anyio
async def test_prepare_session_generates_unique_channel_name_without_requested_binding():
    service = _CapturingConvoAIService()
    session_service = AgoraConnectorSessionService(
        ConnectorBindingRegistry(_FakeTransport(), _FakeSpeaker()),
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="cert",
        ),
        convoai_service=service,
    )

    first = await session_service.prepare_session(ConnectorSessionPrepareRequest())
    second = await session_service.prepare_session(ConnectorSessionPrepareRequest())

    assert first.channel_name.startswith("newbro-voice-")
    assert second.channel_name.startswith("newbro-voice-")
    assert first.channel_name != second.channel_name


@pytest.mark.anyio
async def test_activate_session_reuses_prepared_synapse_session_id_without_creating_new_session():
    service = _CapturingConvoAIService()
    transport = _FakeTransport()
    session_service = AgoraConnectorSessionService(
        ConnectorBindingRegistry(transport, _FakeSpeaker()),
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="cert",
        ),
        convoai_service=service,
    )

    prepared = await session_service.prepare_session(
        ConnectorSessionPrepareRequest(
            synapse_session_id="session-existing",
        )
    )
    activated = await session_service.activate_session(
        ConnectorSessionActivateRequest(
            prepared_session_id=prepared.prepared_session_id,
        )
    )

    assert activated.synapse_session_id == "session-existing"
    assert activated.channel_name == "session-existing"
    assert transport.created == 0


@pytest.mark.anyio
async def test_activate_and_stop_submit_typed_agora_lifecycle_events():
    service = _CapturingConvoAIService()
    transport = _FakeTransport()
    session_service = AgoraConnectorSessionService(
        ConnectorBindingRegistry(transport, _FakeSpeaker()),
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="cert",
        ),
        convoai_service=service,
    )

    prepared = await session_service.prepare_session(ConnectorSessionPrepareRequest())
    activated = await session_service.activate_session(
        ConnectorSessionActivateRequest(prepared_session_id=prepared.prepared_session_id)
    )
    await session_service.stop_session(ConnectorSessionStopRequest(binding_id=activated.binding_id))

    assert transport.agora_events is not None
    assert [event.type for event in transport.agora_events] == [
        AgoraVoiceEventType.SESSION_STARTED,
        AgoraVoiceEventType.SESSION_ENDED,
    ]
    assert transport.agora_events[0].metadata["agora_runtime_session_id"] == "runtime-1"


@pytest.mark.anyio
async def test_connector_binding_logs_notification_speaker_failures(caplog):
    transport = _QueuedNotificationTransport()
    registry = ConnectorBindingRegistry(transport, _FailingSpeaker())
    binding = await registry.reserve(synapse_session_id="session-1")
    await registry.finalize(binding.binding_id, runtime_session_id="runtime-1")

    with caplog.at_level(logging.ERROR, logger="newbro.connectors.base.bindings"):
        await transport.notifications.put("Task completed.")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    await registry.unregister(binding.binding_id)

    assert "Connector notification speech delivery failed" in caplog.text
    assert "speaker failed" in caplog.text


@pytest.mark.anyio
async def test_activate_session_logs_cleanup_failure_without_hiding_primary_error(caplog):
    service = _CleanupFailingConvoAIService()
    registry = ConnectorBindingRegistry(_FakeTransport(), _FakeSpeaker())
    existing = await registry.reserve(synapse_session_id="session-existing")
    await registry.finalize(existing.binding_id, runtime_session_id="runtime-1")
    session_service = AgoraConnectorSessionService(
        registry,
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="cert",
        ),
        convoai_service=service,
    )

    prepared = await session_service.prepare_session(ConnectorSessionPrepareRequest())
    with caplog.at_level(logging.ERROR, logger="newbro.connectors.voice.agora_convoai.session_service"):
        with pytest.raises(DuplicateBindingError):
            await session_service.activate_session(
                ConnectorSessionActivateRequest(prepared_session_id=prepared.prepared_session_id)
            )

    await registry.unregister(existing.binding_id)

    assert "Failed to clean up activated ConvoAI session after connector binding failure" in caplog.text
    assert "cleanup failed" in caplog.text
