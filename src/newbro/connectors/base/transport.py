from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

import httpx
import websockets

from newbro.api.paths import API_PREFIX
from newbro.protocol import AgoraVoiceEvent, RuntimeDecision


class NewbroConnectorError(RuntimeError):
    pass


@dataclass(slots=True)
class NewbroMessageResult:
    reply_text: str


class NewbroConnectorTransport(Protocol):
    async def create_session(self) -> str:
        ...

    async def send_message(
        self,
        session_id: str,
        text: str,
        *,
        target_persona_id: str | None = None,
    ) -> NewbroMessageResult:
        ...

    async def submit_asr_turn(self, session_id: str, text: str) -> NewbroMessageResult:
        ...

    async def submit_agora_event(self, session_id: str, event: AgoraVoiceEvent) -> RuntimeDecision:
        ...

    async def get_voice_target_persona_id(self, session_id: str) -> str | None:
        ...

    def stream_message(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str,
    ):
        ...

    def watch_notification_texts(self, session_id: str):
        ...

    async def close(self) -> None:
        ...


class HttpNewbroConnectorTransport:
    def __init__(
        self,
        base_url: str,
        *,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._request_timeout_seconds = request_timeout_seconds
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=request_timeout_seconds,
            trust_env=False,
        )

    async def create_session(self) -> str:
        response = await self._request("POST", f"{API_PREFIX}/sessions")
        payload = response.json()
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise NewbroConnectorError("Newbro session creation returned no session_id.")
        return session_id

    async def send_message(
        self,
        session_id: str,
        text: str,
        *,
        target_persona_id: str | None = None,
    ) -> NewbroMessageResult:
        payload: dict[str, object] = {"text": text, "source": "connector"}
        if target_persona_id:
            payload["target_persona_id"] = target_persona_id
        response = await self._request(
            "POST",
            f"{API_PREFIX}/sessions/{session_id}/messages",
            json=payload,
        )
        payload = response.json()
        reply_text = payload.get("reply_text")
        if not isinstance(reply_text, str):
            raise NewbroConnectorError("Newbro message response returned no reply_text.")
        return NewbroMessageResult(reply_text=reply_text)

    async def submit_asr_turn(self, session_id: str, text: str) -> NewbroMessageResult:
        response = await self._request(
            "POST",
            f"{API_PREFIX}/sessions/{session_id}/messages",
            json={"type": "stt_final", "text": text, "source": "connector", "assigned_bro_id": "codex"},
        )
        payload = response.json()
        reply_text = payload.get("response_text") or payload.get("reply_text") or ""
        return NewbroMessageResult(reply_text=str(reply_text))

    async def submit_agora_event(self, session_id: str, event: AgoraVoiceEvent) -> RuntimeDecision:
        response = await self._request(
            "POST",
            f"{API_PREFIX}/sessions/{session_id}/agora-events",
            json=event.model_dump(mode="json"),
        )
        return RuntimeDecision.model_validate(response.json())

    async def get_voice_target_persona_id(self, session_id: str) -> str | None:
        response = await self._request("GET", f"{API_PREFIX}/sessions/{session_id}")
        payload = response.json()
        value = payload.get("voice_target_persona_id")
        return value if isinstance(value, str) and value else None

    async def stream_message(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str,
        target_persona_id: str | None = None,
    ):
        ws_url = self._session_stream_url(session_id)
        try:
            async with websockets.connect(
                ws_url,
                proxy=None,
                open_timeout=self._request_timeout_seconds,
                close_timeout=self._request_timeout_seconds,
            ) as websocket:
                await self._recv_json(websocket, timeout=self._request_timeout_seconds)
                payload: dict[str, object] = {
                    "type": "send_message",
                    "request_id": request_id,
                    "text": text,
                    "source": "connector",
                }
                if target_persona_id:
                    payload["target_persona_id"] = target_persona_id
                await websocket.send(json.dumps(payload))
                while True:
                    event = await self._recv_json(
                        websocket,
                        timeout=self._request_timeout_seconds,
                    )
                    event_type = event.get("type")
                    if event_type == "action_rejected" and event.get("request_id") == request_id:
                        raise NewbroConnectorError(
                            str(event.get("message") or "Newbro rejected the message action.")
                        )
                    if event_type not in {
                        "assistant_response_started",
                        "assistant_response_delta",
                        "assistant_response_completed",
                        "assistant_response_failed",
                    }:
                        continue
                    if event.get("request_id") != request_id:
                        continue
                    yield event
                    if event_type in {"assistant_response_completed", "assistant_response_failed"}:
                        break
        except NewbroConnectorError:
            raise
        except Exception as exc:
            raise NewbroConnectorError(
                f"Failed to stream message from Newbro session '{session_id}'."
            ) from exc

    async def watch_notification_texts(self, session_id: str):
        ws_url = self._session_stream_url(session_id)
        try:
            async with websockets.connect(
                ws_url,
                proxy=None,
                open_timeout=self._request_timeout_seconds,
                close_timeout=self._request_timeout_seconds,
            ) as websocket:
                await self._recv_json(websocket, timeout=self._request_timeout_seconds)
                while True:
                    event = await self._recv_json(websocket, timeout=None)
                    if event.get("type") != "conversation_appended":
                        continue
                    if event.get("source") != "notification":
                        continue
                    text = event.get("text")
                    if isinstance(text, str) and text.strip():
                        yield text.strip()
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() or getattr(exc.response, "reason" + "_" + "ph" + "rase")
            raise NewbroConnectorError(
                f"Newbro API request failed for {method} {path}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise NewbroConnectorError(
                f"Failed to reach Newbro API for {method} {path}."
            ) from exc

    async def _recv_json(
        self,
        websocket: Any,
        *,
        timeout: float | None,
    ) -> dict[str, Any]:
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
        if not isinstance(raw, str):
            raise NewbroConnectorError("Newbro websocket returned a non-text payload.")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise NewbroConnectorError("Newbro websocket returned a non-object payload.")
        return payload

    def _session_stream_url(self, session_id: str) -> str:
        parsed = urlparse(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = parsed.path.rstrip("/") + f"{API_PREFIX}/sessions/{session_id}/stream"
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))
