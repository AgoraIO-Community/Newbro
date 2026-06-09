# src/newbro/executors/adapters/hermes/jsonrpc.py
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator


class HermesJsonRpcPeer:
    """Newline-delimited JSON-RPC 2.0 peer over a stdio stream pair."""

    def __init__(self, reader: asyncio.StreamReader, writer: object) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[object]] = {}
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._read_loop())

    async def request(self, method: str, params: dict[str, object] | None = None) -> object:
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        return await future

    async def notify(self, method: str, params: dict[str, object] | None = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def next_event(self) -> dict[str, object]:
        return await self._events.get()

    async def iter_events(self) -> AsyncIterator[dict[str, object]]:
        while True:
            yield await self.next_event()

    async def close(self) -> None:
        self._reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader_task
        self._writer.close()
        await self._writer.wait_closed()

    async def _send(self, payload: dict[str, object]) -> None:
        self._writer.write(json.dumps(payload).encode("utf-8") + b"\n")
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                message = json.loads(stripped.decode("utf-8"))
                if isinstance(message, dict) and "id" in message and ("result" in message or "error" in message):
                    self._handle_response(message)
                    continue
                if isinstance(message, dict):
                    await self._events.put(message)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Hermes gateway connection closed."))
            self._pending.clear()

    def _handle_response(self, message: dict[str, object]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return
        error = message.get("error")
        if error is not None:
            future.set_exception(RuntimeError(str(error)))
            return
        future.set_result(message.get("result"))
