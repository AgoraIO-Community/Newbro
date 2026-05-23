from __future__ import annotations

import asyncio
import json
from typing import Any


class ASGIWebSocketSession:
    def __init__(self, app, path: str, *, headers: list[tuple[bytes, bytes]] | None = None) -> None:
        self._app = app
        self._path = path
        self._headers = headers or []
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "ASGIWebSocketSession":
        headers: list[tuple[bytes, bytes]] = list(self._headers)
        cookie_header = getattr(getattr(self._app, "state", None), "_newbro_test_cookie_header", None)
        if isinstance(cookie_header, str) and cookie_header:
            headers.append((b"cookie", cookie_header.encode()))
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "scheme": "ws",
            "http_version": "1.1",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
            "root_path": "",
        }
        self._task = asyncio.create_task(
            self._app(scope, self._receive_from_client, self._send_to_client)
        )
        await self._incoming.put({"type": "websocket.connect"})
        event = await self.receive_raw_event()
        if event["type"] == "websocket.close":
            raise RuntimeError(f"WebSocket connection rejected: {event}")
        if event["type"] != "websocket.accept":
            raise RuntimeError(f"Expected websocket.accept, got: {event}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._task is None:
            return
        if not self._task.done():
            await self._incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(self._task, timeout=1.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send_json(self, payload: dict[str, object]) -> None:
        await self._incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(payload),
            }
        )

    async def receive_json(self, *, timeout: float = 1.0) -> dict[str, Any]:
        while True:
            event = await self.receive_raw_event(timeout=timeout)
            if event["type"] == "websocket.send":
                text = event.get("text")
                if not isinstance(text, str):
                    raise RuntimeError(f"Expected text websocket.send event, got: {event}")
                return json.loads(text)
            if event["type"] == "websocket.close":
                raise RuntimeError(f"WebSocket closed before JSON message: {event}")

    async def receive_raw_event(self, *, timeout: float = 1.0) -> dict[str, Any]:
        return await asyncio.wait_for(self._outgoing.get(), timeout=timeout)

    async def _receive_from_client(self) -> dict[str, Any]:
        return await self._incoming.get()

    async def _send_to_client(self, message: dict[str, Any]) -> None:
        await self._outgoing.put(message)
