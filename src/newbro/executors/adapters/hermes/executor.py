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

_PROGRESS_EVENTS = frozenset({
    "message.delta", "tool.start", "tool.progress", "tool.complete", "tool.generating",
    "reasoning.delta", "reasoning.available", "thinking.delta", "status.update",
})
_BLOCKING_EVENTS = frozenset({"approval.request", "clarify.request"})
_GATEWAY_CLOSED_EVENT = "__gateway_closed__"


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
        self._sessions_by_run[run.run_id] = session
        queue = await self._client.events_for(session.gateway_session_id)
        try:
            if follow_up:
                # Single follow-up contract: steer only, no prompt.submit fallback.
                await self._client.steer(session.gateway_session_id, text)
            else:
                await self._client.submit_prompt(session.gateway_session_id, text)
        except Exception as exc:  # noqa: BLE001 - surface steer/submit failure observably
            yield ExecutorEvent(
                run_id=run.run_id,
                session_id=session.session_id,
                event_type=ExecutorEventType.FAILED,
                message=f"hermes prompt failed: {exc}",
            )
            return

        # Each queue item is an event `params` dict: {"type", "session_id", "payload"}.
        while True:
            try:
                if self._timeout_seconds is not None:
                    params = await asyncio.wait_for(queue.get(), timeout=self._timeout_seconds)
                else:
                    params = await queue.get()
            except asyncio.TimeoutError:
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.FAILED,
                    message=f"hermes turn timed out after {self._timeout_seconds}s with no gateway event",
                )
                return
            etype = params.get("type")
            if etype == _GATEWAY_CLOSED_EVENT:
                returncode = params.get("returncode")
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.FAILED,
                    message=f"hermes gateway exited unexpectedly (returncode={returncode})",
                    metadata={"hermes_event": etype, "returncode": returncode},
                )
                return
            payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
            text_value = payload.get("text")
            progress_text = text_value or payload.get("preview") or payload.get("summary")
            if etype in _PROGRESS_EVENTS:
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.PROGRESS,
                    message=progress_text if isinstance(progress_text, str) else None,
                    metadata={"hermes_event": etype},
                )
                continue
            if etype == "message.complete":
                status = payload.get("status")
                if status == "interrupted":
                    terminal = ExecutorEventType.CANCELLED
                elif status == "error":
                    terminal = ExecutorEventType.FAILED
                else:
                    terminal = ExecutorEventType.COMPLETED
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=terminal,
                    message=text_value if isinstance(text_value, str) else None,
                    metadata={"hermes_event": etype, "status": status},
                )
                return
            if etype in _BLOCKING_EVENTS:
                prompt = payload.get("question") or payload.get("command") or payload.get("description")
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.BLOCKED,
                    message=prompt if isinstance(prompt, str) else f"hermes requested {etype}",
                    metadata={"hermes_event": etype, "request": payload},
                )
                return
            if etype == "error":
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.FAILED,
                    message=payload.get("message") if isinstance(payload.get("message"), str) else None,
                    metadata={"hermes_event": etype},
                )
                return
