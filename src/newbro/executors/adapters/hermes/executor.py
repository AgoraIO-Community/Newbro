from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from newbro.executors.core import ExecutorCapabilities, ExecutorEvent, ExecutorEventType
from newbro.protocol import ExecutionRun, ExecutorTextInstruction, Task

from .client import HermesGatewayClient
from .probe import probe_hermes_command
from .session import HermesExecutorSession


class HermesExecutor:
    def __init__(
        self,
        *,
        command: str = "hermes",
        project_root: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._command = command
        self._timeout_seconds = timeout_seconds
        self._client = HermesGatewayClient(command=command, project_root=project_root)
        self._capabilities = ExecutorCapabilities(
            executor_type="hermes",
            supports_resume=False,
            supports_follow_up=True,
            supports_audio_instruction=False,
            supports_thread_list=False,
            supports_pause=False,
            supports_cancel=True,
            supports_setup=False,
        )
        self._sessions_by_run: dict[str, HermesExecutorSession] = {}

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def refresh_capabilities(self) -> ExecutorCapabilities:
        probe = await asyncio.to_thread(probe_hermes_command, self._command)
        self._capabilities.version = probe.version
        self._capabilities.minimum_version = None
        self._capabilities.availability_reason = None if probe.ok else (probe.error or "hermes_not_found")
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> HermesExecutorSession:
        cwd = Path(workspace_id or os.getcwd()).resolve()
        gateway_session_id = await self._client.create_session(cwd)
        session = HermesExecutorSession(
            session_id=gateway_session_id,
            executor_type="hermes",
            metadata={},
        )
        session.attach(cwd=cwd, gateway_session_id=gateway_session_id)
        return session

    async def cancel_run(self, run_id: str) -> None:
        session = self._sessions_by_run.get(run_id)
        if session is not None:
            await self._client.interrupt(session.gateway_session_id)

    async def pause_run(self, run_id: str) -> None:
        # supports_pause is False, so the runtime never calls this. Implemented
        # as an explicit unsupported no-op rather than aliasing cancel, to avoid
        # promising a resumable paused state we do not have.
        return None

    async def aclose(self) -> None:
        await self._client.aclose()

    def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: HermesExecutorSession,
    ) -> AsyncIterator[ExecutorEvent]:
        return self._drive_prompt(run, session, task.goal or task.title)

    def handle_text_instruction(
        self,
        run: ExecutionRun,
        session: HermesExecutorSession,
        instruction: ExecutorTextInstruction,
    ) -> AsyncIterator[ExecutorEvent]:
        return self._drive_prompt(run, session, instruction.text, follow_up=True)

    def handle_audio_instruction(self, run, session, audio):  # pragma: no cover - unsupported
        raise NotImplementedError("Hermes V1 does not support audio instructions.")

    async def _drive_prompt(
        self,
        run: ExecutionRun,
        session: HermesExecutorSession,
        text: str,
        *,
        follow_up: bool = False,
    ) -> AsyncIterator[ExecutorEvent]:
        # Implemented in Task 7.
        raise NotImplementedError
