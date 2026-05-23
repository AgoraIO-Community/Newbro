from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import time
from typing import Any, AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from newbro.api.paths import API_PREFIX, api_path
from newbro.connectors.base import (
    ActiveConnectorBinding,
    BaseConnectorModule,
    ConnectorBindingRegistry,
    HttpNewbroConnectorTransport,
    NewbroConnectorError,
    NewbroConnectorTransport,
)
from newbro.connectors.base.bindings import ConnectorSpeaker
from newbro.protocol import AgoraVoiceEvent, AgoraVoiceEventType, RuntimeDecision

from .models import (
    ChatCompletionRequest,
    ConnectorConfigResponse,
    ConnectorSessionActivateRequest,
    ConnectorSessionActivateResponse,
    ConnectorSessionPrepareRequest,
    ConnectorSessionPrepareResponse,
    ConnectorSessionStopRequest,
    ConnectorSessionStopResponse,
    SttSessionQueryResponse,
    SttSessionPrepareRequest,
    SttSessionPrepareResponse,
    SttSessionHeartbeatRequest,
    SttSessionHeartbeatResponse,
    SttSessionLeaveRequest,
    SttSessionStartRequest,
    SttSessionStartResponse,
    SttSessionStopRequest,
    SttSessionStopResponse,
)
from .service import (
    AGORA_CONVOAI_IMPLEMENTATION_VERSION,
    AGORA_CONVOAI_SDK_LOADER_SIGNATURE,
    AgoraSDKConvoAIService,
    ConvoAIConfigurationError,
    ConvoAIRuntimeError,
)
from .session_service import AgoraConnectorSessionService
from .stt_service import AgoraSttService
from .settings import AGORA_BRIDGE_MODEL, AgoraConvoAIConnectorSettings, load_agora_connector_settings


LOGGER = logging.getLogger(__name__)


class AgoraConvoAIConnectorModule(BaseConnectorModule):
    slug = "agora-convoai"

    def __init__(self, settings: AgoraConvoAIConnectorSettings | None = None) -> None:
        self._settings = settings or load_agora_connector_settings()

    def build_router(self) -> APIRouter:
        settings = self._settings
        transport = HttpNewbroConnectorTransport(
            settings.synapse_base_url,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
        service = AgoraSDKConvoAIService(settings)
        stt_service = AgoraSttService(settings)
        binding_registry = ConnectorBindingRegistry(transport, speaker=service)
        chat_completion_turns = ChatCompletionTurnCoalescer(
            transport=transport,
            speaker=service,
            delay_seconds=settings.chat_completion_turn_silence_seconds,
        )
        session_service = AgoraConnectorSessionService(
            binding_registry,
            settings,
            convoai_service=service,
        )

        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            try:
                yield
            finally:
                await chat_completion_turns.close()
                await binding_registry.close()
                await stt_service.close()
                await transport.close()

        router = APIRouter(
            prefix=f"{API_PREFIX}/connectors/agora-convoai",
            tags=["connector:agora-convoai"],
            lifespan=lifespan,
        )

        @router.get("/health")
        async def health() -> dict[str, object]:
            return {
                "status": "ok",
                "implementation_version": AGORA_CONVOAI_IMPLEMENTATION_VERSION,
                "sdk_loader_signature": list(AGORA_CONVOAI_SDK_LOADER_SIGNATURE),
                "synapse_base_url": settings.synapse_base_url,
                "upstream_transport_mode": "direct",
            }

        @router.get("/config", response_model=ConnectorConfigResponse)
        async def config() -> ConnectorConfigResponse:
            return session_service.get_config()

        @router.post("/sessions/prepare", response_model=ConnectorSessionPrepareResponse)
        async def prepare_session(
            payload: ConnectorSessionPrepareRequest,
        ) -> ConnectorSessionPrepareResponse:
            try:
                return await session_service.prepare_session(payload)
            except ConvoAIConfigurationError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ConvoAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @router.post("/sessions/activate", response_model=ConnectorSessionActivateResponse)
        async def activate_session(
            payload: ConnectorSessionActivateRequest,
        ) -> ConnectorSessionActivateResponse:
            try:
                return await session_service.activate_session(payload)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except NewbroConnectorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except ConvoAIConfigurationError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ConvoAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @router.post("/sessions/stop", response_model=ConnectorSessionStopResponse)
        async def stop_session(
            payload: ConnectorSessionStopRequest,
        ) -> ConnectorSessionStopResponse:
            try:
                await chat_completion_turns.flush_now(payload.binding_id)
                return await session_service.stop_session(payload)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ConvoAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc


        @router.post("/stt/sessions/prepare", response_model=SttSessionPrepareResponse)
        async def prepare_stt_session(
            payload: SttSessionPrepareRequest,
        ) -> SttSessionPrepareResponse:
            try:
                return stt_service.prepare_session(payload)
            except ConvoAIConfigurationError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        @router.post("/stt/sessions/start", response_model=SttSessionStartResponse)
        async def start_stt_session(
            payload: SttSessionStartRequest,
        ) -> SttSessionStartResponse:
            try:
                return await stt_service.start_session(payload)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ConvoAIConfigurationError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ConvoAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @router.post("/stt/sessions/heartbeat", response_model=SttSessionHeartbeatResponse)
        async def heartbeat_stt_session(
            payload: SttSessionHeartbeatRequest,
        ) -> SttSessionHeartbeatResponse:
            try:
                return stt_service.heartbeat_session(payload)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        @router.post("/stt/sessions/leave", response_model=SttSessionStopResponse)
        async def leave_stt_session(
            payload: SttSessionLeaveRequest,
        ) -> SttSessionStopResponse:
            try:
                return await stt_service.leave_session(payload)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ConvoAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @router.get("/stt/sessions/{stt_session_id}", response_model=SttSessionQueryResponse)
        async def query_stt_session(stt_session_id: str) -> SttSessionQueryResponse:
            try:
                return await stt_service.query_session(stt_session_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ConvoAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @router.post("/stt/sessions/stop", response_model=SttSessionStopResponse)
        async def stop_stt_session(
            payload: SttSessionStopRequest,
        ) -> SttSessionStopResponse:
            try:
                return await stt_service.stop_session(payload.stt_session_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ConvoAIRuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @router.post("/chat/completions")
        async def chat_completions(
            payload: ChatCompletionRequest,
            request: Request,
        ):
            binding_id = _resolve_binding_id(request)
            binding = binding_registry.get(binding_id)
            if binding is None:
                raise HTTPException(status_code=404, detail="Unknown connector binding.")

            user_text = _extract_latest_user_text(payload.messages)
            if user_text is None:
                raise HTTPException(status_code=400, detail="No user message found in messages.")

            _log_chat_completion_diagnostics(
                binding_id=binding_id,
                payload=payload,
                user_text=user_text,
            )
            target_persona_id = await _resolve_voice_target_persona_id(
                transport=transport,
                synapse_session_id=binding.synapse_session_id,
            )
            event = _compat_event_from_chat_completion(
                payload=payload,
                session_id=binding.synapse_session_id,
                text=user_text,
                target_persona_id=target_persona_id,
            )
            if event is None:
                if payload.stream:
                    return StreamingResponse(
                        _stream_silent_completion(model_name=payload.model or AGORA_BRIDGE_MODEL),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                    )
                return JSONResponse(
                    _build_completion_response(
                        completion_id=f"chatcmpl-{uuid4().hex[:8]}",
                        created=int(time.time()),
                        model_name=payload.model or AGORA_BRIDGE_MODEL,
                        reply_text="",
                    )
                )

            if not _has_explicit_event_type(payload):
                await chat_completion_turns.submit(binding=binding, event=event)
                if payload.stream:
                    return StreamingResponse(
                        _stream_silent_completion(model_name=payload.model or AGORA_BRIDGE_MODEL),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                    )
                return JSONResponse(
                    _build_completion_response(
                        completion_id=f"chatcmpl-{uuid4().hex[:8]}",
                        created=int(time.time()),
                        model_name=payload.model or AGORA_BRIDGE_MODEL,
                        reply_text="",
                    )
                )

            try:
                decision = await transport.submit_agora_event(binding.synapse_session_id, event)
            except NewbroConnectorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            if payload.stream:
                return StreamingResponse(
                    _stream_runtime_decision(
                        decision=decision,
                        model_name=payload.model or AGORA_BRIDGE_MODEL,
                    ),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

            return JSONResponse(
                _build_completion_response(
                    completion_id=f"chatcmpl-{uuid4().hex[:8]}",
                    created=int(time.time()),
                    model_name=payload.model or AGORA_BRIDGE_MODEL,
                    reply_text=decision.response_text if decision.should_speak else "",
                )
            )

        return router


def create_headless_app(settings: AgoraConvoAIConnectorSettings | None = None) -> FastAPI:
    app = FastAPI(
        title="Newbro Agora ConvoAI Connector",
        openapi_url=api_path("/openapi.json"),
        docs_url=api_path("/docs"),
        redoc_url=api_path("/redoc"),
    )
    app.include_router(AgoraConvoAIConnectorModule(settings=settings).build_router())
    return app


@dataclass(slots=True)
class _PendingChatCompletionTurn:
    binding: ActiveConnectorBinding
    event: AgoraVoiceEvent
    task: asyncio.Task[None]


class ChatCompletionTurnCoalescer:
    def __init__(
        self,
        *,
        transport: NewbroConnectorTransport,
        speaker: ConnectorSpeaker,
        delay_seconds: float = 1.2,
    ) -> None:
        self._transport = transport
        self._speaker = speaker
        self._delay_seconds = delay_seconds
        self._pending: dict[str, _PendingChatCompletionTurn] = {}

    async def submit(
        self,
        *,
        binding: ActiveConnectorBinding,
        event: AgoraVoiceEvent,
    ) -> None:
        await self._submit_live_partial(binding=binding, event=event)
        self.cancel(binding.binding_id)
        task = asyncio.create_task(self._flush_after_delay(binding.binding_id))
        self._pending[binding.binding_id] = _PendingChatCompletionTurn(
            binding=binding,
            event=event,
            task=task,
        )

    def cancel(self, binding_id: str) -> None:
        pending = self._pending.pop(binding_id, None)
        if pending is not None:
            pending.task.cancel()

    async def close(self) -> None:
        pending = list(self._pending)
        for binding_id in pending:
            self.cancel(binding_id)

    async def flush_now(self, binding_id: str) -> RuntimeDecision | None:
        pending = self._pending.pop(binding_id, None)
        if pending is None:
            return None
        pending.task.cancel()
        return await self._submit_pending(pending)

    async def _flush_after_delay(self, binding_id: str) -> None:
        try:
            await asyncio.sleep(self._delay_seconds)
            pending = self._pending.pop(binding_id, None)
            if pending is None:
                return
            await self._submit_pending(pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Failed to flush coalesced Agora chat completion turn.")

    async def _submit_pending(self, pending: _PendingChatCompletionTurn) -> RuntimeDecision:
        decision = await self._transport.submit_agora_event(
            pending.binding.synapse_session_id,
            pending.event,
        )
        if decision.should_speak and decision.response_text and pending.binding.runtime_session_id:
            await self._speaker.speak(pending.binding.runtime_session_id, decision.response_text)
        return decision

    async def _submit_live_partial(
        self,
        *,
        binding: ActiveConnectorBinding,
        event: AgoraVoiceEvent,
    ) -> RuntimeDecision:
        return await self._transport.submit_agora_event(
            binding.synapse_session_id,
            _compat_live_partial_event(event),
        )


async def _stream_runtime_decision(
    *,
    decision: RuntimeDecision,
    model_name: str,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid4().hex[:8]}"
    created = int(time.time())
    yield _sse_payload(
        _build_stream_chunk(
            completion_id=completion_id,
            created=created,
            model_name=model_name,
            delta={
                "role": "assistant",
                "content": decision.response_text if decision.should_speak else "",
            },
        )
    )
    yield _sse_payload(
        _build_stream_chunk(
            completion_id=completion_id,
            created=created,
            model_name=model_name,
            delta={},
            finish_reason="stop",
        )
    )
    yield "data: [DONE]\n\n"


async def _resolve_voice_target_persona_id(
    *,
    transport: HttpNewbroConnectorTransport,
    synapse_session_id: str,
) -> str | None:
    try:
        return await transport.get_voice_target_persona_id(synapse_session_id)
    except NewbroConnectorError:
        return None


def _compat_event_from_chat_completion(
    *,
    payload: ChatCompletionRequest,
    session_id: str,
    text: str,
    target_persona_id: str | None,
) -> AgoraVoiceEvent | None:
    event_type = _compat_event_type(payload)
    if event_type is None:
        return None
    metadata = _compat_metadata(payload)
    metadata["compatibility_endpoint"] = "/chat/completions"
    metadata.setdefault("turn_boundary_source", "agora_custom_llm_callback")
    return AgoraVoiceEvent(
        event_id=f"agora-compat-{uuid4().hex[:8]}",
        session_id=session_id,
        type=event_type,
        text=text,
        target_persona_id=target_persona_id,
        metadata=metadata,
    )


def _compat_live_partial_event(event: AgoraVoiceEvent) -> AgoraVoiceEvent:
    metadata = dict(event.metadata)
    metadata["turn_boundary_source"] = "agora_custom_llm_live_callback"
    return event.model_copy(
        update={
            "event_id": f"{event.event_id}-partial",
            "type": AgoraVoiceEventType.STT_PARTIAL,
            "metadata": metadata,
        }
    )


def _compat_event_type(payload: ChatCompletionRequest) -> AgoraVoiceEventType | None:
    extras = payload.model_extra or {}
    raw = extras.get("newbro_event_type") or extras.get("event_type")
    if isinstance(raw, str):
        try:
            return AgoraVoiceEventType(raw)
        except ValueError:
            pass
    return AgoraVoiceEventType.STT_FINAL


def _has_explicit_event_type(payload: ChatCompletionRequest) -> bool:
    extras = payload.model_extra or {}
    raw = extras.get("newbro_event_type") or extras.get("event_type")
    if not isinstance(raw, str):
        return False
    try:
        AgoraVoiceEventType(raw)
    except ValueError:
        return False
    return True


def _compat_metadata(payload: ChatCompletionRequest) -> dict[str, object]:
    extras = payload.model_extra or {}
    raw = extras.get("metadata")
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items() if isinstance(key, str)}
    return {}


def _log_chat_completion_diagnostics(
    *,
    binding_id: str,
    payload: ChatCompletionRequest,
    user_text: str,
) -> None:
    extras = payload.model_extra or {}
    message_roles = [
        message.get("role")
        for message in payload.messages
        if isinstance(message, dict)
    ]
    LOGGER.info(
        "Agora ConvoAI chat completion callback: %s",
        {
            "binding_id": binding_id,
            "model": payload.model,
            "stream": payload.stream,
            "extra_keys": sorted(str(key) for key in extras.keys()),
            "message_roles": message_roles,
            "has_event_type": isinstance(extras.get("newbro_event_type") or extras.get("event_type"), str),
            "has_metadata": isinstance(extras.get("metadata"), dict),
            "user_text_preview": _preview_text(user_text),
        },
    )


def _preview_text(text: str, limit: int = 80) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


async def _stream_silent_completion(*, model_name: str) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid4().hex[:8]}"
    created = int(time.time())
    yield _sse_payload(
        _build_stream_chunk(
            completion_id=completion_id,
            created=created,
            model_name=model_name,
            delta={"role": "assistant", "content": ""},
        )
    )
    yield _sse_payload(
        _build_stream_chunk(
            completion_id=completion_id,
            created=created,
            model_name=model_name,
            delta={},
            finish_reason="stop",
        )
    )
    yield "data: [DONE]\n\n"


def _resolve_binding_id(request: Request) -> str:
    binding_id = request.query_params.get("binding_id")
    if binding_id:
        return binding_id
    header = request.headers.get("x-binding-id")
    if header:
        return header
    raise HTTPException(status_code=400, detail="Missing binding_id.")


def _extract_latest_user_text(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        text = _extract_message_text(message.get("content"))
        if text:
            return text
    return None


def _extract_message_text(content: object) -> str | None:
    if isinstance(content, str):
        stripped = content.strip()
        return stripped or None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            stripped = text.strip()
            if stripped:
                parts.append(stripped)
            continue
        if isinstance(text, dict):
            value = text.get("value")
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    if not parts:
        return None
    return "\n".join(parts)


def _build_completion_response(
    *,
    completion_id: str,
    created: int,
    model_name: str,
    reply_text: str,
) -> dict[str, object]:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": reply_text,
                },
                "finish_reason": "stop",
            }
        ],
    }


def _build_stream_chunk(
    *,
    completion_id: str,
    created: int,
    model_name: str,
    delta: dict[str, object],
    finish_reason: str | None = None,
) -> dict[str, object]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _sse_payload(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"
