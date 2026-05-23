from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import logging
import re
from time import monotonic
from uuid import uuid4

import httpx

from .models import (
    SttSessionHeartbeatRequest,
    SttSessionHeartbeatResponse,
    SttSessionLeaveRequest,
    SttSessionPrepareRequest,
    SttSessionPrepareResponse,
    SttSessionQueryResponse,
    SttSessionStartRequest,
    SttSessionStartResponse,
    SttSessionStopResponse,
)
from .service import ConvoAIConfigurationError, ConvoAIRuntimeError
from .settings import AgoraConvoAIConnectorSettings
from .token_utils import build_rtc_token


PREPARED_SESSION_TTL_SECONDS = 60.0
ACTIVE_HEARTBEAT_TIMEOUT_SECONDS = 60.0
WATCHDOG_INTERVAL_SECONDS = 15.0
MAX_AGORA_CHANNEL_NAME_LENGTH = 64

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PreparedSttSessionHandle:
    prepared_stt_session_id: str
    channel_name: str
    uid: int
    token: str
    assigned_bro_id: str
    synapse_session_id: str
    created_at: float


@dataclass(slots=True)
class SttSessionHandle:
    stt_session_id: str
    agent_id: str
    channel_name: str
    uid: int
    pub_bot_uid: int
    sub_bot_uid: int
    token: str
    assigned_bro_id: str
    synapse_session_id: str
    last_heartbeat_at: float


class AgoraSttService:
    def __init__(
        self,
        settings: AgoraConvoAIConnectorSettings,
        *,
        now: Callable[[], float] = monotonic,
    ) -> None:
        self._settings = settings
        self._now = now
        self._prepared_sessions: dict[str, PreparedSttSessionHandle] = {}
        self._sessions: dict[str, SttSessionHandle] = {}
        self._http = httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False)
        self._watchdog_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        await self._http.aclose()

    def prepare_session(self, request: SttSessionPrepareRequest) -> SttSessionPrepareResponse:
        if not self._settings.stt.enabled:
            raise ConvoAIConfigurationError("Agora STT is disabled in connector config.")
        app_id = _require(self._settings.app_id, _app_id_requirement_name(self._settings))
        app_certificate = _require(
            self._settings.app_certificate,
            _app_certificate_requirement_name(self._settings),
        )
        channel_name = _build_unique_channel_name(request.synapse_session_id, request.assigned_bro_id)
        uid = request.user_uid or self._settings.user_uid
        user_token = build_rtc_token(
            channel_name=channel_name,
            rtc_uid=uid,
            app_id=app_id,
            app_certificate=app_certificate,
            token_expire=self._settings.stt.token_ttl_seconds,
        ).token
        prepared_stt_session_id = f"prepared-stt-{uuid4().hex[:8]}"
        self._prepared_sessions[prepared_stt_session_id] = PreparedSttSessionHandle(
            prepared_stt_session_id=prepared_stt_session_id,
            channel_name=channel_name,
            uid=uid,
            token=user_token,
            assigned_bro_id=request.assigned_bro_id,
            synapse_session_id=request.synapse_session_id,
            created_at=self._now(),
        )
        return SttSessionPrepareResponse(
            prepared_stt_session_id=prepared_stt_session_id,
            app_id=app_id,
            channel_name=channel_name,
            token=user_token,
            uid=uid,
        )

    def prepared_synapse_session_id(self, prepared_stt_session_id: str) -> str | None:
        prepared = self._prepared_sessions.get(prepared_stt_session_id)
        return prepared.synapse_session_id if prepared is not None else None

    def active_synapse_session_id(self, stt_session_id: str) -> str | None:
        handle = self._sessions.get(stt_session_id)
        return handle.synapse_session_id if handle is not None else None

    async def start_session(self, request: SttSessionStartRequest) -> SttSessionStartResponse:
        if not self._settings.stt.enabled:
            raise ConvoAIConfigurationError("Agora STT is disabled in connector config.")
        await self.sweep_expired_sessions()
        self._ensure_watchdog()
        app_id = _require(self._settings.app_id, _app_id_requirement_name(self._settings))
        app_certificate = _require(
            self._settings.app_certificate,
            _app_certificate_requirement_name(self._settings),
        )
        prepared = self._prepared_sessions.pop(request.prepared_stt_session_id, None)
        if prepared is None:
            raise KeyError("Unknown prepared STT session.")
        channel_name = prepared.channel_name
        uid = prepared.uid
        pub_bot_uid = _next_bot_uid(uid, offset=100000)
        sub_bot_uid = _next_bot_uid(uid, offset=100001)
        languages = request.languages or list(self._settings.stt.languages)
        name = _build_stt_task_name(prepared.synapse_session_id, prepared.assigned_bro_id, channel_name)
        token = build_rtc_token(
            channel_name=channel_name,
            rtc_uid=pub_bot_uid,
            app_id=app_id,
            app_certificate=app_certificate,
            token_expire=self._settings.stt.token_ttl_seconds,
        ).token
        sub_bot_token = build_rtc_token(
            channel_name=channel_name,
            rtc_uid=sub_bot_uid,
            app_id=app_id,
            app_certificate=app_certificate,
            token_expire=self._settings.stt.token_ttl_seconds,
        ).token
        payload = {
            "name": name,
            "languages": languages,
            "maxIdleTime": self._settings.stt.max_idle_time,
            "rtcConfig": {
                "channelName": channel_name,
                "pubBotUid": str(pub_bot_uid),
                "pubBotToken": token,
                "subBotUid": str(sub_bot_uid),
                "subBotToken": sub_bot_token,
                "subscribeAudioUids": [str(uid)],
            },
        }
        logger.info("Agora STT join payload: %s", _redact_stt_join_payload(payload))
        response = await self._http.post(
            f"https://api.agora.io/api/speech-to-text/v1/projects/{app_id}/join",
            headers={"Authorization": f"agora token={token}"},
            json=payload,
        )
        if response.status_code >= 400:
            raise ConvoAIRuntimeError(response.text or f"Agora STT join failed: {response.status_code}")
        body = response.json()
        agent_id = str(body.get("agent_id") or body.get("agentId") or body.get("taskId") or "")
        if not agent_id:
            raise ConvoAIRuntimeError("Agora STT join response did not include agent_id.")
        stt_session_id = f"stt-{uuid4().hex[:8]}"
        self._sessions[stt_session_id] = SttSessionHandle(
            stt_session_id=stt_session_id,
            agent_id=agent_id,
            channel_name=channel_name,
            uid=uid,
            pub_bot_uid=pub_bot_uid,
            sub_bot_uid=sub_bot_uid,
            token=token,
            assigned_bro_id=prepared.assigned_bro_id,
            synapse_session_id=prepared.synapse_session_id,
            last_heartbeat_at=self._now(),
        )
        return SttSessionStartResponse(
            stt_session_id=stt_session_id,
            app_id=app_id,
            channel_name=channel_name,
            token=prepared.token,
            uid=uid,
            pub_bot_uid=pub_bot_uid,
            sub_bot_uid=sub_bot_uid,
            agent_id=agent_id,
            status=str(body.get("status") or "started"),
            languages=languages,
            subscribe_audio_uids=[str(uid)],
        )

    async def query_session(self, stt_session_id: str) -> SttSessionQueryResponse:
        handle = self._get_handle(stt_session_id)
        app_id = _require(self._settings.app_id, _app_id_requirement_name(self._settings))
        response = await self._http.get(
            f"https://api.agora.io/api/speech-to-text/v1/projects/{app_id}/agents/{handle.agent_id}/query",
            headers={"Authorization": f"agora token={handle.token}"},
        )
        if response.status_code >= 400:
            raise ConvoAIRuntimeError(response.text or f"Agora STT query failed: {response.status_code}")
        body = response.json()
        return SttSessionQueryResponse(
            stt_session_id=stt_session_id,
            agent_id=handle.agent_id,
            status=str(body.get("status") or "unknown"),
            raw=body,
        )

    def heartbeat_session(self, request: SttSessionHeartbeatRequest) -> SttSessionHeartbeatResponse:
        handle = self._get_handle(request.stt_session_id)
        handle.last_heartbeat_at = self._now()
        return SttSessionHeartbeatResponse()

    async def leave_session(self, request: SttSessionLeaveRequest) -> SttSessionStopResponse:
        if request.stt_session_id:
            handle = self._sessions.pop(request.stt_session_id, None)
            if handle is None:
                return SttSessionStopResponse()
            await self._stop_handle(handle)
            return SttSessionStopResponse()
        if request.prepared_stt_session_id:
            self._prepared_sessions.pop(request.prepared_stt_session_id, None)
            return SttSessionStopResponse()
        raise KeyError("Missing STT session id.")

    async def stop_session(self, stt_session_id: str) -> SttSessionStopResponse:
        handle = self._sessions.pop(stt_session_id, None)
        if handle is None:
            raise KeyError("Unknown STT session.")
        await self._stop_handle(handle)
        return SttSessionStopResponse()

    async def sweep_expired_sessions(self) -> None:
        now = self._now()
        for prepared_id, prepared in list(self._prepared_sessions.items()):
            if now - prepared.created_at > PREPARED_SESSION_TTL_SECONDS:
                self._prepared_sessions.pop(prepared_id, None)
        for stt_session_id, handle in list(self._sessions.items()):
            if now - handle.last_heartbeat_at > ACTIVE_HEARTBEAT_TIMEOUT_SECONDS:
                self._sessions.pop(stt_session_id, None)
                await self._stop_handle(handle)

    async def _stop_handle(self, handle: SttSessionHandle) -> None:
        app_id = _require(self._settings.app_id, _app_id_requirement_name(self._settings))
        response = await self._http.post(
            f"https://api.agora.io/api/speech-to-text/v1/projects/{app_id}/agents/{handle.agent_id}/leave",
            headers={"Authorization": f"agora token={handle.token}"},
        )
        if response.status_code >= 400:
            raise ConvoAIRuntimeError(response.text or f"Agora STT leave failed: {response.status_code}")

    def _get_handle(self, stt_session_id: str) -> SttSessionHandle:
        try:
            return self._sessions[stt_session_id]
        except KeyError as exc:
            raise KeyError("Unknown STT session.") from exc

    def _ensure_watchdog(self) -> None:
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def _watchdog_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
                await self.sweep_expired_sessions()
        except asyncio.CancelledError:
            raise


def _next_bot_uid(user_uid: int, *, offset: int) -> int:
    return user_uid + offset if user_uid < 2147483647 - offset else user_uid - offset


def _build_unique_channel_name(synapse_session_id: str, assigned_bro_id: str) -> str:
    session_hash = _short_hash(synapse_session_id)
    bro_hash = _short_hash(assigned_bro_id)
    random_suffix = uuid4().hex[:8]
    channel_name = f"nbstt-{session_hash}-{bro_hash}-{random_suffix}"
    return channel_name[:MAX_AGORA_CHANNEL_NAME_LENGTH]


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _build_stt_task_name(synapse_session_id: str, assigned_bro_id: str, fallback: str) -> str:
    session_hash = _short_hash(synapse_session_id)
    bro_hash = _short_hash(assigned_bro_id)
    unique_suffix = _short_hash(fallback)
    raw = f"nbstt-task-{session_hash}-{bro_hash}-{unique_suffix}"
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-_")
    return (sanitized or f"nbstt-task-{unique_suffix}")[:64]


def _redact_stt_join_payload(payload: dict) -> dict:
    rtc_config = payload.get("rtcConfig") if isinstance(payload.get("rtcConfig"), dict) else {}
    return {
        "name": payload.get("name"),
        "languages": payload.get("languages"),
        "maxIdleTime": payload.get("maxIdleTime"),
        "rtcConfig": {
            "channelName": rtc_config.get("channelName"),
            "pubBotUid": rtc_config.get("pubBotUid"),
            "pubBotToken": "<redacted>" if rtc_config.get("pubBotToken") else None,
            "subBotUid": rtc_config.get("subBotUid"),
            "subBotToken": "<redacted>" if rtc_config.get("subBotToken") else None,
            "subscribeAudioUids": rtc_config.get("subscribeAudioUids"),
        },
    }


def _require(value: str | None, name: str) -> str:
    if value:
        return value
    raise ConvoAIConfigurationError(f"Missing required Agora setting: {name}")


def _app_id_requirement_name(settings: AgoraConvoAIConnectorSettings) -> str:
    return "connectors.agora-convoai.app_id" if settings.uses_yaml_config else "SYNAPSE_CONNECTOR_AGORA_CONVOAI_APP_ID"


def _app_certificate_requirement_name(settings: AgoraConvoAIConnectorSettings) -> str:
    return "connectors.agora-convoai.app_certificate" if settings.uses_yaml_config else "SYNAPSE_CONNECTOR_AGORA_CONVOAI_APP_CERTIFICATE"
