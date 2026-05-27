from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
import logging
import sys
from typing import Any, TextIO
from urllib.parse import urlparse, urlunparse

import websockets

from newbro.api.paths import API_PREFIX
from newbro.communication.persona_pool import resolve_workspace
from newbro.executors.adapters.acpx import AcpxExecutor, AcpxExecutorSession
from newbro.executors.adapters.codex import CodexExecutor, CodexExecutorSession
from newbro.executors.core import ExecutorEvent, ExecutorEventType, ExecutorSession
from newbro.protocol import (
    AckMessage,
    CancelRunCommand,
    DispatchAudioInstructionCommand,
    DispatchRunCommand,
    DispatchTextInstructionCommand,
    ExecutorNodeExecutor,
    ExecutorTextInstruction,
    RegisterNodeMessage,
    ReleaseRunCommand,
    RunEventMessage,
    SupplyInteractionResponseCommand,
)

from .audio import AudioTranscriber, build_audio_transcriber
from .config import ExecutorNodeSettings

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class LocalRunContext:
    executor: Any
    execution_session_id: str
    background_task: asyncio.Task[None]


@dataclass(slots=True)
class ExecutorNodeLifecycleReporter:
    stream: TextIO = field(default_factory=lambda: sys.stdout)

    def starting(self, *, node_id: str, executor_types: list[str], synapse_base_url: str) -> None:
        self._emit(
            "[start] executor node "
            f"node_id={node_id} executors={_format_executor_types(executor_types)} "
            f"newbro={synapse_base_url}"
        )

    def connect_attempt(self, *, attempt: int, control_url: str) -> None:
        self._emit(f"[connect] executor node attempt={attempt} url={control_url}")

    def connect_failed(self, *, attempt: int, control_url: str, error: BaseException) -> None:
        self._emit(
            "[warn] executor node "
            f"attempt={attempt} connect_failed={_format_exception_summary(error)} url={control_url}"
        )

    def ready(self, *, node_id: str, executor_types: list[str], synapse_base_url: str) -> None:
        self._emit(
            "[ready] executor node "
            f"node_id={node_id} executors={_format_executor_types(executor_types)} "
            f"newbro={synapse_base_url}"
        )

    def disconnected(self, *, control_url: str, error: BaseException) -> None:
        self._emit(
            "[warn] executor node "
            f"disconnected={_format_exception_summary(error)} url={control_url}"
        )

    def retrying(self, *, delay_seconds: float) -> None:
        self._emit(f"[retry] executor node retrying in {delay_seconds:.1f}s")

    def _emit(self, message: str) -> None:
        print(message, file=self.stream, flush=True)


class ExecutorNodeService:
    def __init__(
        self,
        *,
        settings: ExecutorNodeSettings,
        executors_config: dict[str, Any],
        audio_config: dict[str, Any] | None = None,
        audio_transcriber: AudioTranscriber | None = None,
        reporter: ExecutorNodeLifecycleReporter | None = None,
    ) -> None:
        self._settings = settings
        self._executors = self._build_executors(executors_config)
        self._audio_transcriber = audio_transcriber or build_audio_transcriber(audio_config)
        self._live_sessions: dict[str, ExecutorSession] = {}
        self._active_runs: dict[str, LocalRunContext] = {}
        self._send_lock = asyncio.Lock()
        self._reporter = reporter or ExecutorNodeLifecycleReporter()

    async def run_forever(self) -> None:
        control_url = self._ws_url()
        retry_delay_seconds = 1.0
        attempt = 0
        self._reporter.starting(
            node_id=self._settings.node_id,
            executor_types=list(self._executors.keys()),
            synapse_base_url=self._settings.synapse_base_url,
        )
        while True:
            attempt += 1
            ready = False
            self._reporter.connect_attempt(attempt=attempt, control_url=control_url)
            try:
                async with websockets.connect(
                    control_url,
                    proxy=None,
                    open_timeout=10.0,
                    close_timeout=10.0,
                ) as websocket:
                    await self._send_json(
                        websocket,
                        RegisterNodeMessage(
                            node_id=self._settings.node_id,
                            token=self._settings.token,
                            executors=[
                                await self._descriptor(name, executor)
                                for name, executor in self._executors.items()
                            ],
                        ).model_dump(mode="json"),
                    )
                    ack = AckMessage.model_validate(await self._recv_json(websocket))
                    if not ack.ok or ack.message_type != "register_node":
                        detail = ack.detail or f"unexpected ack for {ack.message_type}"
                        raise RuntimeError(f"registration rejected: {detail}")
                    ready = True
                    self._reporter.ready(
                        node_id=self._settings.node_id,
                        executor_types=list(self._executors.keys()),
                        synapse_base_url=self._settings.synapse_base_url,
                    )
                    while True:
                        payload = await self._recv_json(websocket)
                        await self._handle_message(websocket, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if ready:
                    self._reporter.disconnected(control_url=control_url, error=exc)
                else:
                    self._reporter.connect_failed(
                        attempt=attempt,
                        control_url=control_url,
                        error=exc,
                    )
                await self._cancel_active_runs()
                self._reporter.retrying(delay_seconds=retry_delay_seconds)
                await asyncio.sleep(retry_delay_seconds)

    async def _handle_message(self, websocket: Any, payload: dict[str, object]) -> None:
        message_type = payload.get("type")
        if message_type == "dispatch_run":
            command = DispatchRunCommand.model_validate(payload)
            await self._dispatch_run(websocket, command)
            return
        if message_type == "dispatch_audio_instruction":
            command = DispatchAudioInstructionCommand.model_validate(payload)
            await self._dispatch_audio_instruction(websocket, command)
            return
        if message_type == "dispatch_text_instruction":
            command = DispatchTextInstructionCommand.model_validate(payload)
            await self._dispatch_text_instruction(websocket, command)
            return
        if message_type == "cancel_run":
            command = CancelRunCommand.model_validate(payload)
            await self._cancel_run(command)
            return
        if message_type == "supply_interaction_response":
            command = SupplyInteractionResponseCommand.model_validate(payload)
            await self._supply_interaction_response(command)
            return
        if message_type == "release_run":
            command = ReleaseRunCommand.model_validate(payload)
            self._live_sessions.pop(command.execution_session_id, None)
            return

    async def _dispatch_run(self, websocket: Any, command: DispatchRunCommand) -> None:
        executor = self._executors[command.executor_type]
        session = await self._ensure_session(executor, command)
        run_task = asyncio.create_task(self._run_dispatch(websocket, executor, session, command))
        self._active_runs[command.run_id] = LocalRunContext(
            executor=executor,
            execution_session_id=command.execution_session_id,
            background_task=run_task,
        )

    async def _run_dispatch(
        self,
        websocket: Any,
        executor: Any,
        session: ExecutorSession,
        command: DispatchRunCommand,
    ) -> None:
        try:
            from newbro.protocol import ExecutionRun, Task

            run = ExecutionRun(
                run_id=command.run_id,
                task_id=command.task_id,
                execution_session_id=command.execution_session_id,
                executor_type=command.executor_type,
            )
            task = Task(
                task_id=command.task_id,
                root_task_id=command.task_id,
                title=command.title,
                goal=command.goal,
                preferred_executor=command.executor_type,
                session_affinity=command.workspace_id,
                latest_instruction=command.latest_instruction,
                metadata=dict(command.task_metadata),
            )
            async for event in executor.run_task(run, task, session):
                await self._send_json(
                    websocket,
                    RunEventMessage(
                        run_id=command.run_id,
                        execution_session_id=command.execution_session_id,
                        executor_type=command.executor_type,
                        session_id=session.session_id,
                        event_type=event.event_type.value,
                        message=event.message,
                        metadata=dict(event.metadata),
                        latest_resume_handle=_build_resume_handle(executor, session),
                    ).model_dump(mode="json"),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_json(
                websocket,
                RunEventMessage(
                    run_id=command.run_id,
                    execution_session_id=command.execution_session_id,
                    executor_type=command.executor_type,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.FAILED.value,
                    message=str(exc),
                    metadata={},
                    latest_resume_handle=_build_resume_handle(executor, session),
                ).model_dump(mode="json"),
            )
        finally:
            self._active_runs.pop(command.run_id, None)
            if not _session_is_alive(session):
                self._live_sessions.pop(command.execution_session_id, None)

    async def _cancel_run(self, command: CancelRunCommand) -> None:
        context = self._active_runs.get(command.run_id)
        if context is None:
            return
        if command.mode == "pause":
            await context.executor.pause_run(command.run_id)
            return
        await context.executor.cancel_run(command.run_id)

    async def _dispatch_audio_instruction(
        self,
        websocket: Any,
        command: DispatchAudioInstructionCommand,
    ) -> None:
        context = self._active_runs.get(command.run_id)
        session = self._live_sessions.get(command.execution_session_id)
        if context is None or session is None:
            await self._send_audio_instruction_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED,
                message="No active executor run is available for audio.",
                metadata={"audio_instruction_id": command.audio.audio_instruction_id},
            )
            return
        text_handler = getattr(context.executor, "handle_text_instruction", None)
        native_audio_handler = getattr(context.executor, "handle_audio_instruction", None)
        if text_handler is None and native_audio_handler is None:
            await self._send_audio_instruction_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED,
                message=f"Executor '{command.executor_type}' does not support audio instructions.",
                metadata={"audio_instruction_id": command.audio.audio_instruction_id},
            )
            return
        from newbro.protocol import ExecutionRun

        run = ExecutionRun(
            run_id=command.run_id,
            task_id=command.task_id,
            execution_session_id=command.execution_session_id,
            executor_type=command.executor_type,
        )
        try:
            if text_handler is not None and self._audio_transcriber.available:
                transcription = await self._audio_transcriber.transcribe(command.audio)
                transcript = transcription.text.strip()
                if not transcript:
                    await self._send_audio_instruction_event(
                        websocket,
                        command,
                        event_type=ExecutorEventType.FAILED,
                        message="Audio transcription produced no instruction text.",
                        metadata={"audio_instruction_id": command.audio.audio_instruction_id},
                    )
                    return
                instruction = ExecutorTextInstruction(
                    instruction_id=f"txt-{command.audio.audio_instruction_id}",
                    target_persona_id=command.audio.target_persona_id,
                    text=transcript,
                    source_audio_instruction_id=command.audio.audio_instruction_id,
                    metadata={
                        "source": "executor_node_whisper",
                        "transcript_text": transcript,
                        "transcription_language": transcription.language or "",
                        "transcription_duration_seconds": transcription.duration_seconds or 0,
                        **(transcription.metadata or {}),
                    },
                )
                handler = text_handler
                event_source = instruction
            elif native_audio_handler is not None:
                handler = native_audio_handler
                event_source = command.audio
            else:
                await self._send_audio_instruction_event(
                    websocket,
                    command,
                    event_type=ExecutorEventType.FAILED,
                    message="Local Whisper transcription is not available on this executor node.",
                    metadata={"audio_instruction_id": command.audio.audio_instruction_id},
                )
                return
            async for event in handler(run, session, event_source):
                await self._send_json(
                    websocket,
                    RunEventMessage(
                        run_id=command.run_id,
                        execution_session_id=command.execution_session_id,
                        executor_type=command.executor_type,
                        session_id=session.session_id,
                        event_type=event.event_type.value,
                        message=event.message,
                        metadata=dict(event.metadata),
                        latest_resume_handle=_build_resume_handle(context.executor, session),
                    ).model_dump(mode="json"),
                )
        except Exception as exc:
            await self._send_audio_instruction_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED,
                message=str(exc),
                metadata={"audio_instruction_id": command.audio.audio_instruction_id},
            )

    async def _dispatch_text_instruction(
        self,
        websocket: Any,
        command: DispatchTextInstructionCommand,
    ) -> None:
        context = self._active_runs.get(command.run_id)
        session = self._live_sessions.get(command.execution_session_id)
        if context is None or session is None:
            await self._send_text_instruction_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED,
                message="No active executor run is available for text.",
            )
            return
        text_handler = getattr(context.executor, "handle_text_instruction", None)
        if text_handler is None:
            await self._send_text_instruction_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED,
                message=f"Executor '{command.executor_type}' does not support text follow-up instructions.",
            )
            return
        from newbro.protocol import ExecutionRun

        run = ExecutionRun(
            run_id=command.run_id,
            task_id=command.task_id,
            execution_session_id=command.execution_session_id,
            executor_type=command.executor_type,
        )
        try:
            async for event in text_handler(run, session, command.instruction):
                await self._send_json(
                    websocket,
                    RunEventMessage(
                        run_id=command.run_id,
                        execution_session_id=command.execution_session_id,
                        executor_type=command.executor_type,
                        session_id=session.session_id,
                        event_type=event.event_type.value,
                        message=event.message,
                        metadata=dict(event.metadata),
                        latest_resume_handle=_build_resume_handle(context.executor, session),
                    ).model_dump(mode="json"),
                )
        except Exception as exc:
            await self._send_text_instruction_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED,
                message=str(exc),
            )

    async def _supply_interaction_response(
        self,
        command: SupplyInteractionResponseCommand,
    ) -> None:
        if not isinstance(command.execution_session_id, str) or not command.execution_session_id:
            return
        session = self._live_sessions.get(command.execution_session_id)
        if not isinstance(session, CodexExecutorSession):
            return
        if not isinstance(command.native_response, dict):
            return
        try:
            await session.client.respond_to_request(
                request_id=command.native_response.get("request_id"),
                method=str(command.native_response.get("method") or ""),
                params=dict(command.native_response.get("params") or {}),
                action=command.action,
                answer_text=command.answer_text,
            )
        except Exception as exc:
            LOGGER.warning(
                "Failed to forward interaction response to executor node session "
                "execution_session_id=%s interaction_request_id=%s: %s",
                command.execution_session_id,
                command.interaction_request_id,
                exc,
            )
            return
        session.mark_blocked_resolved()

    async def _send_audio_instruction_event(
        self,
        websocket: Any,
        command: DispatchAudioInstructionCommand,
        *,
        event_type: ExecutorEventType,
        message: str,
        metadata: dict[str, object],
    ) -> None:
        await self._send_json(
            websocket,
            RunEventMessage(
                run_id=command.run_id,
                execution_session_id=command.execution_session_id,
                executor_type=command.executor_type,
                session_id=command.execution_session_id,
                event_type=event_type.value,
                message=message,
                metadata=metadata,
            ).model_dump(mode="json"),
        )

    async def _send_text_instruction_event(
        self,
        websocket: Any,
        command: DispatchTextInstructionCommand,
        *,
        event_type: ExecutorEventType,
        message: str,
    ) -> None:
        await self._send_json(
            websocket,
            RunEventMessage(
                run_id=command.run_id,
                execution_session_id=command.execution_session_id,
                executor_type=command.executor_type,
                session_id=command.execution_session_id,
                event_type=event_type.value,
                message=message,
                metadata={
                    "instruction_id": command.instruction.instruction_id,
                    "source": "executor_text_instruction",
                },
                latest_resume_handle=None,
            ).model_dump(mode="json"),
        )

    async def _ensure_session(self, executor: Any, command: DispatchRunCommand) -> ExecutorSession:
        existing = self._live_sessions.get(command.execution_session_id)
        if existing is not None and _session_is_alive(existing):
            return existing
        workspace_path = str(resolve_workspace(command.workspace_id or command.task_id))
        session = await executor.create_session(workspace_path)
        if command.latest_resume_handle is not None:
            _hydrate_resume_handle(session, command.latest_resume_handle.model_dump(mode="json"))
        self._live_sessions[command.execution_session_id] = session
        return session

    def _build_executors(self, executors_config: dict[str, Any]) -> dict[str, Any]:
        built: dict[str, Any] = {}
        for executor_type in self._settings.enabled_executors:
            config = executors_config.get(executor_type) if isinstance(executors_config, dict) else {}
            if executor_type == "codex":
                built[executor_type] = CodexExecutor(
                    command=str((config or {}).get("command", "codex")),
                    blocked_wait_timeout_seconds=float((config or {}).get("blocked_wait_timeout_seconds", 900.0)),
                )
            elif executor_type == "acpx":
                built[executor_type] = AcpxExecutor(
                    command=str((config or {}).get("command", "acpx")),
                    agent=str((config or {}).get("agent", "codex")),
                    permission_mode=str((config or {}).get("permission_mode", "approve-all")),
                    non_interactive_permissions=str((config or {}).get("non_interactive_permissions", "deny")),
                    timeout_seconds=float((config or {}).get("timeout_seconds"))
                    if (config or {}).get("timeout_seconds") not in (None, "")
                    else None,
                )
        return built

    async def _descriptor(self, executor_type: str, executor: Any) -> ExecutorNodeExecutor:
        refresh = getattr(executor, "refresh_capabilities", None)
        if refresh is not None:
            try:
                capabilities = await refresh()
            except Exception:
                capabilities = executor.get_capabilities()
        else:
            capabilities = executor.get_capabilities()
        return ExecutorNodeExecutor(
            executor_type=executor_type,
            supports_resume=capabilities.supports_resume,
            supports_follow_up=capabilities.supports_follow_up,
            supports_audio_instruction=capabilities.supports_audio_instruction
            or (capabilities.supports_follow_up and self._audio_transcriber.available),
            supports_pause=capabilities.supports_pause,
            supports_cancel=capabilities.supports_cancel,
        )

    async def _cancel_active_runs(self) -> None:
        contexts = list(self._active_runs.items())
        self._active_runs.clear()
        for run_id, context in contexts:
            context.background_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await context.background_task
            with contextlib.suppress(Exception):
                await context.executor.cancel_run(run_id)

    async def _send_json(self, websocket: Any, payload: dict[str, object]) -> None:
        async with self._send_lock:
            await websocket.send(json.dumps(payload))

    async def _recv_json(self, websocket: Any) -> dict[str, object]:
        raw = await websocket.recv()
        if not isinstance(raw, str):
            raise RuntimeError("Executor node websocket received a non-text payload.")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise RuntimeError("Executor node websocket received a non-object payload.")
        return payload

    def _ws_url(self) -> str:
        parsed = urlparse(self._settings.synapse_base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = parsed.path.rstrip("/") + f"{API_PREFIX}/executors/control"
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def _session_is_alive(session: ExecutorSession) -> bool:
    if isinstance(session, AcpxExecutorSession):
        return True
    if isinstance(session, CodexExecutorSession):
        return session.is_alive()
    return True


def _hydrate_resume_handle(session: ExecutorSession, resume_handle: dict[str, object]) -> None:
    if isinstance(session, AcpxExecutorSession) and resume_handle.get("executor_id") == "acpx":
        opaque = dict(resume_handle.get("opaque") or {})
        session.hydrate_resume_handle(
            cwd=str(opaque.get("cwd")) if opaque.get("cwd") is not None else None,
            session_name=str(opaque.get("sessionName")) if opaque.get("sessionName") is not None else None,
            agent=str(opaque.get("agent")) if opaque.get("agent") is not None else None,
            acpx_record_id=str(resume_handle.get("session_handle")) if resume_handle.get("session_handle") is not None else None,
            acp_session_id=str(opaque.get("acpSessionId")) if opaque.get("acpSessionId") is not None else None,
            agent_session_id=str(opaque.get("agentSessionId")) if opaque.get("agentSessionId") is not None else None,
        )
        return
    if isinstance(session, CodexExecutorSession) and resume_handle.get("executor_id") == "codex":
        session.thread_id = str(resume_handle.get("session_handle")) if resume_handle.get("session_handle") is not None else None


def _build_resume_handle(executor: Any, session: ExecutorSession):
    if hasattr(executor, "build_resume_handle"):
        try:
            return executor.build_resume_handle(session)
        except Exception:
            return None
    return None


def _format_executor_types(executor_types: list[str]) -> str:
    if not executor_types:
        return "none"
    return ",".join(executor_types)


def _format_exception_summary(error: BaseException) -> str:
    detail = str(error).strip()
    if not detail:
        return type(error).__name__
    return f"{type(error).__name__}: {detail}"
