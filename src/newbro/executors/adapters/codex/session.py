from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Literal

from pydantic import PrivateAttr

from newbro.executors.core import ExecutorSession

from .client import CodexAppServerClient
from .jsonrpc import JsonRpcPeer


class CodexExecutorSession(ExecutorSession):
    _process: asyncio.subprocess.Process | None = PrivateAttr(default=None)
    _peer: JsonRpcPeer | None = PrivateAttr(default=None)
    _client: CodexAppServerClient | None = PrivateAttr(default=None)
    _cwd: Path | None = PrivateAttr(default=None)
    _stderr_lines: list[str] = PrivateAttr(default_factory=list)
    _stderr_task: asyncio.Task[None] | None = PrivateAttr(default=None)
    _thread_id: str | None = PrivateAttr(default=None)
    _turn_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _blocked_resolution_event: asyncio.Event | None = PrivateAttr(default=None)
    _blocked_wait_result: Literal["resolved", "aborted"] | None = PrivateAttr(default=None)
    _owns_client: bool = PrivateAttr(default=True)

    def attach(
        self,
        *,
        process: asyncio.subprocess.Process,
        peer: JsonRpcPeer,
        client: CodexAppServerClient,
        cwd: Path,
    ) -> None:
        self._process = process
        self._peer = peer
        self._client = client
        self._cwd = cwd
        self._owns_client = True
        self._stderr_task = asyncio.create_task(self._collect_stderr())

    def attach_shared(
        self,
        *,
        client: CodexAppServerClient,
        cwd: Path,
    ) -> None:
        self._client = client
        self._cwd = cwd
        self._owns_client = False

    @property
    def client(self) -> CodexAppServerClient:
        if self._client is None:
            raise RuntimeError("Codex client not attached.")
        return self._client

    @property
    def cwd(self) -> Path:
        if self._cwd is None:
            raise RuntimeError("Codex cwd not attached.")
        return self._cwd

    @property
    def thread_id(self) -> str | None:
        return self._thread_id

    @thread_id.setter
    def thread_id(self, value: str | None) -> None:
        self._thread_id = value

    def is_alive(self) -> bool:
        if self._process is not None:
            return self._process.returncode is None
        return self._client is not None

    @property
    def turn_lock(self) -> asyncio.Lock:
        return self._turn_lock

    async def close(self) -> None:
        self.abort_blocked_wait()
        if self._owns_client and self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        if self._owns_client and self._client is not None:
            await self._client.close()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task

    def stderr_text(self) -> str:
        return "\n".join(self._stderr_lines[-20:])

    async def _collect_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        while True:
            line = await self._process.stderr.readline()
            if not line:
                return
            self._stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())

    def begin_blocked_wait(self) -> None:
        self._blocked_resolution_event = asyncio.Event()
        self._blocked_wait_result = None

    async def wait_for_blocked_resolution(
        self,
        timeout_seconds: float | None = None,
    ) -> Literal["resolved", "aborted", "timed_out"]:
        if self._blocked_resolution_event is None:
            return "resolved"
        try:
            if timeout_seconds is None:
                await self._blocked_resolution_event.wait()
            else:
                await asyncio.wait_for(self._blocked_resolution_event.wait(), timeout_seconds)
        except asyncio.TimeoutError:
            self._blocked_resolution_event = None
            self._blocked_wait_result = None
            return "timed_out"
        result = self._blocked_wait_result or "resolved"
        self._blocked_resolution_event = None
        self._blocked_wait_result = None
        return result

    def mark_blocked_resolved(self) -> None:
        if self._blocked_resolution_event is not None:
            self._blocked_wait_result = "resolved"
            self._blocked_resolution_event.set()

    def abort_blocked_wait(self) -> None:
        if self._blocked_resolution_event is not None:
            self._blocked_wait_result = "aborted"
            self._blocked_resolution_event.set()
