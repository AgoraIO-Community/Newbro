from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from ..schema import DiagnosticEvent
from .types import DiagnosticSink

LOGGER = logging.getLogger("runtime.latency_export")

Poster = Callable[[str, dict[str, str], list[dict[str, Any]]], Awaitable[None]]


def _record_from_event(event: DiagnosticEvent) -> dict[str, Any]:
    details = event.details or {}
    return {
        "event": event.event_name,
        "ts": event.ts.isoformat(),
        "request_id": event.request_id,
        "model_name": event.model_name,
        "outcome": event.outcome,
        "total_ms": details.get("total_ms"),
        "steps": details.get("steps", {}),
    }


class HttpExporterSink(DiagnosticSink):
    """Non-blocking: emit() enqueues; a background task batches and POSTs."""

    def __init__(
        self,
        *,
        url: str | None,
        headers: dict[str, str],
        post: Poster | None,
        event_name: str = "turn.latency",
        batch_size: int = 50,
        flush_seconds: float = 5.0,
        queue_max: int = 1000,
        max_retries: int = 3,
        retry_base: float = 0.5,
    ) -> None:
        self._url = url
        self._headers = headers
        self._post = post or _httpx_post
        self._event_name = event_name
        self._batch_size = batch_size
        self._flush_seconds = flush_seconds
        self._queue_max = queue_max
        self._max_retries = max_retries
        self._retry_base = retry_base
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self.dropped = 0

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def emit(self, event: DiagnosticEvent) -> None:
        if not self.enabled or event.event_name != self._event_name:
            return
        if self._task is None:
            try:
                self.start_sync()
            except RuntimeError:
                return  # no running loop yet; drop (startup ordering)
        if self._queue.qsize() >= self._queue_max:
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(_record_from_event(event))

    def start_sync(self) -> None:
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run())

    async def start(self) -> None:
        if self._task is None and self.enabled:
            self.start_sync()

    async def drain(self) -> None:
        # test helper: let the background task process the queue
        await asyncio.sleep(0)
        while not self._queue.empty():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.01)

    async def aclose(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._closed:
            batch = await self._collect_batch()
            if batch:
                await self._flush(batch)

    async def _collect_batch(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=self._flush_seconds)
        except asyncio.TimeoutError:
            return batch
        batch.append(first)
        while len(batch) < self._batch_size and not self._queue.empty():
            batch.append(self._queue.get_nowait())
        return batch

    async def _flush(self, batch: list[dict[str, Any]]) -> None:
        delay = self._retry_base
        for attempt in range(self._max_retries + 1):
            try:
                await self._post(self._url, self._headers, batch)
                return
            except Exception:
                if attempt >= self._max_retries:
                    LOGGER.warning("latency export dropped %d events after retries", len(batch))
                    return
                await asyncio.sleep(delay)
                delay *= 2


async def _httpx_post(url: str, headers: dict[str, str], payload: list[dict[str, Any]]) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
