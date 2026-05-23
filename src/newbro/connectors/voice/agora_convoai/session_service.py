from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from newbro.connectors.base import DuplicateBindingError, ConnectorBindingRegistry, MissingRegistrationConfigError
from newbro.protocol import AgoraVoiceEvent, AgoraVoiceEventType

from .models import (
    ConnectorConfigResponse,
    ConnectorSessionDefaults,
    ConnectorPrepareAgentModel,
    ConnectorSessionActivateRequest,
    ConnectorSessionActivateResponse,
    ConnectorSessionPrepareRequest,
    ConnectorSessionPrepareResponse,
    ConnectorSessionStopRequest,
    ConnectorSessionStopResponse,
)
from .service import (
    ActivatedConvoAISession,
    ConvoAIRuntimeError,
    ConvoAIService,
    PreparedConvoAISession,
)
from .settings import AgoraConvoAIConnectorSettings


@dataclass(slots=True)
class ConnectorSessionHandle:
    binding_id: str
    synapse_session_id: str
    runtime_session_id: str
    channel_name: str
    profile: str | None


class AgoraConnectorSessionService:
    def __init__(
        self,
        binding_registry: ConnectorBindingRegistry,
        settings: AgoraConvoAIConnectorSettings,
        *,
        convoai_service: ConvoAIService,
    ) -> None:
        self._binding_registry = binding_registry
        self._settings = settings
        self._convoai_service = convoai_service
        self._sessions: dict[str, ConnectorSessionHandle] = {}
        self._prepared_synapse_session_ids: dict[str, str | None] = {}

    def get_config(self) -> ConnectorConfigResponse:
        missing: list[str] = []
        if not self._settings.app_id:
            missing.append(
                "connectors.agora-convoai.app_id"
                if self._settings.uses_yaml_config
                else "SYNAPSE_CONNECTOR_AGORA_CONVOAI_APP_ID"
            )
        if not self._settings.synapse_base_url:
            missing.append("SYNAPSE_CONNECTOR_SYNAPSE_BASE_URL")
        if not self._settings.app_certificate:
            missing.append(
                "connectors.agora-convoai.app_certificate"
                if self._settings.uses_yaml_config
                else "SYNAPSE_CONNECTOR_AGORA_CONVOAI_APP_CERTIFICATE"
            )
        if self._settings.asr.credential_mode == "byok" and not self._settings.asr.api_key:
            missing.append(
                "connectors.agora-convoai.asr.api_key"
                if self._settings.uses_yaml_config
                else "SYNAPSE_CONNECTOR_AGORA_CONVOAI_DEEPGRAM_API_KEY"
            )
        if self._settings.tts.credential_mode == "byok" and not self._settings.tts.api_key:
            missing.append(
                "connectors.agora-convoai.tts.api_key"
                if self._settings.uses_yaml_config
                else "SYNAPSE_CONNECTOR_AGORA_CONVOAI_ELEVENLABS_API_KEY"
            )
        if self._settings.tts.credential_mode == "byok" and not self._settings.tts.voice:
            missing.append(
                "connectors.agora-convoai.tts.voice"
                if self._settings.uses_yaml_config
                else "SYNAPSE_CONNECTOR_AGORA_CONVOAI_ELEVENLABS_VOICE_ID"
            )

        return ConnectorConfigResponse(
            ready=not missing,
            service_base_url=self._settings.service_base_url.rstrip("/"),
            defaults=ConnectorSessionDefaults(
                profile=self._settings.default_profile,
                channel_name=None,
                display_name=self._settings.default_display_name,
                agent_instructions=self._settings.agent_instructions,
                agent_greeting=self._settings.agent_greeting,
                agent_uid=self._settings.agent_uid,
                user_uid=self._settings.user_uid,
            ),
            missing_requirements=missing,
        )

    async def prepare_session(
        self,
        request_payload: ConnectorSessionPrepareRequest,
    ) -> ConnectorSessionPrepareResponse:
        synapse_session_id = self._normalize_synapse_session_id(request_payload.synapse_session_id)
        profile = request_payload.profile or self._settings.default_profile
        channel_name = self._resolve_channel_name(
            request_payload.channel_name,
            synapse_session_id=synapse_session_id,
        )
        display_name = request_payload.display_name or self._settings.default_display_name
        prepared = await self._convoai_service.prepare_session(
            profile=profile,
            channel_name=channel_name,
            display_name=display_name,
            agent_instructions=(
                request_payload.agent_instructions
                if request_payload.agent_instructions is not None
                else self._settings.agent_instructions
            ),
            agent_greeting=(
                request_payload.agent_greeting
                if request_payload.agent_greeting is not None
                else self._settings.agent_greeting
            ),
            agent_uid=(
                request_payload.agent_uid
                if request_payload.agent_uid is not None
                else self._settings.agent_uid
            ),
            user_uid=request_payload.user_uid,
        )
        self._prepared_synapse_session_ids[prepared.prepared_session_id] = synapse_session_id
        return self._build_prepare_response(prepared)

    async def activate_session(
        self,
        request_payload: ConnectorSessionActivateRequest,
    ) -> ConnectorSessionActivateResponse:
        requested_synapse_session_id = self._prepared_synapse_session_ids.get(
            request_payload.prepared_session_id,
        )
        reserved = await self._binding_registry.reserve(
            synapse_session_id=requested_synapse_session_id,
        )
        chat_completions_url = self._build_chat_completions_url(reserved.binding_id)
        activated: ActivatedConvoAISession | None = None
        try:
            activated = await self._convoai_service.activate_session(
                request_payload.prepared_session_id,
                chat_completions_url=chat_completions_url,
            )
            binding = await self._binding_registry.finalize(
                reserved.binding_id,
                runtime_session_id=activated.runtime_session_id,
                metadata={"channel_name": activated.channel_name},
            )
        except (DuplicateBindingError, MissingRegistrationConfigError, KeyError):
            self._prepared_synapse_session_ids.pop(request_payload.prepared_session_id, None)
            if activated is not None:
                try:
                    await self._convoai_service.stop_session(activated.runtime_session_id)
                except Exception:
                    pass
            await self._binding_registry.unregister(reserved.binding_id)
            raise
        except ConvoAIRuntimeError:
            self._prepared_synapse_session_ids.pop(request_payload.prepared_session_id, None)
            await self._binding_registry.unregister(reserved.binding_id)
            raise
        except Exception:
            self._prepared_synapse_session_ids.pop(request_payload.prepared_session_id, None)
            await self._binding_registry.unregister(reserved.binding_id)
            raise

        if binding.runtime_session_id != activated.runtime_session_id:
            self._prepared_synapse_session_ids.pop(request_payload.prepared_session_id, None)
            try:
                await self._convoai_service.stop_session(activated.runtime_session_id)
            except Exception:
                pass
            await self._binding_registry.unregister(binding.binding_id)
            raise RuntimeError("Connector binding did not finalize correctly.")

        self._prepared_synapse_session_ids.pop(request_payload.prepared_session_id, None)
        self._sessions[binding.binding_id] = ConnectorSessionHandle(
            binding_id=binding.binding_id,
            synapse_session_id=binding.synapse_session_id,
            runtime_session_id=activated.runtime_session_id,
            channel_name=activated.channel_name,
            profile=activated.profile,
        )
        await self._binding_registry.submit_agora_event(
            binding.synapse_session_id,
            agora_lifecycle_event(
                "started",
                synapse_session_id=binding.synapse_session_id,
                runtime_session_id=activated.runtime_session_id,
                metadata={"channel_name": activated.channel_name},
            ),
        )
        return self._build_activate_response(
            binding.binding_id,
            binding.synapse_session_id,
            activated,
        )

    async def stop_session(
        self,
        request_payload: ConnectorSessionStopRequest,
    ) -> ConnectorSessionStopResponse:
        handle = self._sessions.pop(request_payload.binding_id, None)
        if handle is None:
            raise KeyError("Unknown connector binding.")

        runtime_error: ConvoAIRuntimeError | None = None
        try:
            await self._convoai_service.stop_session(handle.runtime_session_id)
        except KeyError:
            pass
        except ConvoAIRuntimeError as exc:
            runtime_error = exc

        await self._binding_registry.submit_agora_event(
            handle.synapse_session_id,
            agora_lifecycle_event(
                "stopped",
                synapse_session_id=handle.synapse_session_id,
                runtime_session_id=handle.runtime_session_id,
                metadata={"channel_name": handle.channel_name},
            ),
        )
        await self._binding_registry.unregister(request_payload.binding_id)
        if runtime_error is not None:
            raise runtime_error
        return ConnectorSessionStopResponse()

    def _build_prepare_response(
        self,
        prepared: PreparedConvoAISession,
    ) -> ConnectorSessionPrepareResponse:
        return ConnectorSessionPrepareResponse(
            prepared_session_id=prepared.prepared_session_id,
            app_id=prepared.app_id,
            channel_name=prepared.channel_name,
            token=prepared.token,
            uid=prepared.uid,
            user_rtm_uid=prepared.user_rtm_uid,
            agent=ConnectorPrepareAgentModel(uid=prepared.agent_uid),
            agent_rtm_uid=prepared.agent_rtm_uid,
            enable_string_uid=prepared.enable_string_uid,
            profile=prepared.profile,
            display_name=prepared.display_name,
            diagnostics=prepared.diagnostics,
        )

    def _build_activate_response(
        self,
        binding_id: str,
        synapse_session_id: str,
        activated: ActivatedConvoAISession,
    ) -> ConnectorSessionActivateResponse:
        return ConnectorSessionActivateResponse(
            prepared_session_id=activated.prepared_session_id,
            binding_id=binding_id,
            synapse_session_id=synapse_session_id,
            runtime_session_id=activated.runtime_session_id,
            chat_completions_url=self._build_chat_completions_url(binding_id),
            app_id=activated.app_id,
            channel_name=activated.channel_name,
            token=activated.token,
            uid=activated.uid,
            user_rtm_uid=activated.user_rtm_uid,
            agent=ConnectorPrepareAgentModel(uid=activated.agent_uid),
            agent_rtm_uid=activated.agent_rtm_uid,
            enable_string_uid=activated.enable_string_uid,
            profile=activated.profile,
            display_name=activated.display_name,
            diagnostics=activated.diagnostics,
        )

    def _build_chat_completions_url(self, binding_id: str) -> str:
        return (
            f"{self._settings.service_base_url.rstrip('/')}"
            f"/api/connectors/agora-convoai/chat/completions?binding_id={binding_id}"
        )

    def _resolve_channel_name(
        self,
        requested_channel_name: str | None,
        *,
        synapse_session_id: str | None,
    ) -> str:
        if requested_channel_name is not None and requested_channel_name.strip():
            return requested_channel_name
        if synapse_session_id is not None:
            return synapse_session_id
        return f"newbro-voice-{uuid4().hex[:8]}"

    def _normalize_synapse_session_id(self, session_id: str | None) -> str | None:
        if session_id is None:
            return None
        normalized = session_id.strip()
        return normalized or None


def agora_lifecycle_event(
    sdk_event_name: str,
    *,
    synapse_session_id: str,
    runtime_session_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> AgoraVoiceEvent:
    event_type = {
        "started": AgoraVoiceEventType.SESSION_STARTED,
        "stopped": AgoraVoiceEventType.SESSION_ENDED,
    }.get(sdk_event_name, AgoraVoiceEventType.INTERACTION_INTERRUPTED)
    payload = dict(metadata or {})
    if runtime_session_id:
        payload["agora_runtime_session_id"] = runtime_session_id
    payload["sdk_event_name"] = sdk_event_name
    return AgoraVoiceEvent(
        event_id=f"agora-sdk-{uuid4().hex[:8]}",
        session_id=synapse_session_id,
        type=event_type,
        metadata=payload,
    )
