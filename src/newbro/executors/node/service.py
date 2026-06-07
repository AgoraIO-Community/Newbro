from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
from dataclasses import dataclass, field
import logging
import sys
import time
from typing import Any, TextIO
from urllib.parse import urlparse, urlunparse

import websockets

from newbro.api.paths import API_PREFIX
from newbro.communication.persona_pool import resolve_workspace
from newbro.executors.adapters.acpx import AcpxExecutor, AcpxExecutorSession
from newbro.executors.adapters.codex import CodexExecutor, CodexExecutorSession
from newbro.executors.core import ExecutorEvent, ExecutorEventType, ExecutorSession
from newbro.executors.node.workspace_files import (
    WorkspaceFileAccessError,
    iter_file_bytes,
    resolve_within_workspace,
)
from newbro.protocol import (
    AckMessage,
    AudioInstructionTranscribedMessage,
    CodexThreadEventMessage,
    CancelRunCommand,
    CodexThreadListItem,
    CodexThreadReadMessage,
    CodexThreadSubscribedMessage,
    CodexThreadTurnsListedMessage,
    CodexThreadsListedMessage,
    CodexThreadUnsubscribedMessage,
    CodexTurnEventMessage,
    DispatchAudioInstructionCommand,
    DispatchRunCommand,
    DispatchTextInstructionCommand,
    ExecutorNodeExecutor,
    ExecutorTextInstruction,
    EXECUTOR_CONTROL_MAX_MESSAGE_BYTES,
    ListCodexThreadTurnsCommand,
    ListCodexThreadsCommand,
    ReadCodexThreadCommand,
    ReadWorkspaceFileCommand,
    RegisterNodeMessage,
    ReleaseRunCommand,
    RunEventMessage,
    StartCodexTurnCommand,
    SubscribeCodexThreadCommand,
    SupplyInteractionResponseCommand,
    TranscribeAudioInstructionCommand,
    UnsubscribeCodexThreadCommand,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
)

from .audio import AudioTranscriber, build_audio_transcriber
from .config import ExecutorNodeSettings

LOGGER = logging.getLogger(__name__)


def _emit_executor_text_metric(message: str, *args: object) -> None:
    LOGGER.info(message, *args)
    print(message % args, file=sys.stderr, flush=True)


@dataclass(slots=True)
class LocalRunContext:
    executor: Any
    execution_session_id: str
    background_task: asyncio.Task[None]


@dataclass(slots=True)
class CodexThreadSubscriptionContext:
    executor: Any
    session: CodexExecutorSession
    command: SubscribeCodexThreadCommand
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
        self._thread_workspaces: dict[str, str] = {}
        # Codex thread id -> its own cwd, learned from list_threads. Lets Gate 2
        # resolve a workspace root for imported/history threads that were never
        # subscribed with a workspace_id.
        self._codex_thread_workspaces: dict[str, str] = {}
        self._active_runs: dict[str, LocalRunContext] = {}
        self._codex_thread_subscriptions: dict[str, CodexThreadSubscriptionContext] = {}
        self._background_commands: set[asyncio.Task[None]] = set()
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
                    max_size=EXECUTOR_CONTROL_MAX_MESSAGE_BYTES,
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
                await self._cancel_codex_thread_subscriptions()
                await self._cancel_background_commands()
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
        if message_type == "transcribe_audio_instruction":
            command = TranscribeAudioInstructionCommand.model_validate(payload)
            await self._transcribe_audio_instruction(websocket, command)
            return
        if message_type == "dispatch_text_instruction":
            command = DispatchTextInstructionCommand.model_validate(payload)
            await self._dispatch_text_instruction(websocket, command)
            return
        if message_type == "start_codex_turn":
            command = StartCodexTurnCommand.model_validate(payload)
            self._schedule_background_command(self._start_codex_turn(websocket, command))
            return
        if message_type == "list_codex_threads":
            command = ListCodexThreadsCommand.model_validate(payload)
            self._schedule_background_command(self._list_codex_threads(websocket, command))
            return
        if message_type == "list_codex_thread_turns":
            command = ListCodexThreadTurnsCommand.model_validate(payload)
            self._schedule_background_command(self._list_codex_thread_turns(websocket, command))
            return
        if message_type == "read_codex_thread":
            command = ReadCodexThreadCommand.model_validate(payload)
            self._schedule_background_command(self._read_codex_thread(websocket, command))
            return
        if message_type == "read_workspace_file":
            command = ReadWorkspaceFileCommand.model_validate(payload)
            self._schedule_background_command(self._read_workspace_file(websocket, command))
            return
        if message_type == "subscribe_codex_thread":
            command = SubscribeCodexThreadCommand.model_validate(payload)
            self._schedule_background_command(self._subscribe_codex_thread(websocket, command))
            return
        if message_type == "unsubscribe_codex_thread":
            command = UnsubscribeCodexThreadCommand.model_validate(payload)
            self._schedule_background_command(self._unsubscribe_codex_thread(websocket, command))
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

    def _schedule_background_command(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background_commands.add(task)
        task.add_done_callback(self._finish_background_command)

    def _finish_background_command(self, task: asyncio.Task[None]) -> None:
        self._background_commands.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            LOGGER.warning("Executor node background command failed: %s", exc)

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

    async def _list_codex_threads(self, websocket: Any, command: ListCodexThreadsCommand) -> None:
        executor = self._executors.get(command.executor_type)
        list_threads_page = getattr(executor, "list_threads_page", None)
        if list_threads_page is None:
            await self._send_json(
                websocket,
                CodexThreadsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    ok=False,
                    error="Codex executor does not support thread/list.",
                ).model_dump(mode="json"),
            )
            return
        try:
            raw_page = await list_threads_page(
                command.workspace_id,
                limit=command.limit,
                cursor=command.cursor,
            )
            threads = [_codex_thread_list_item(item) for item in raw_page.items]
            for item in threads:
                if item.cwd:
                    self._codex_thread_workspaces[item.thread_id] = item.cwd
            await self._send_json(
                websocket,
                CodexThreadsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    threads=threads,
                    next_cursor=raw_page.next_cursor,
                    previous_cursor=raw_page.previous_cursor,
                ).model_dump(mode="json"),
            )
        except Exception as exc:
            await self._send_json(
                websocket,
                CodexThreadsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    ok=False,
                    error=str(exc),
                ).model_dump(mode="json"),
            )

    async def _list_codex_thread_turns(self, websocket: Any, command: ListCodexThreadTurnsCommand) -> None:
        executor = self._executors.get(command.executor_type)
        list_turns = getattr(executor, "list_thread_turns_page", None)
        if list_turns is None:
            await self._send_json(
                websocket,
                CodexThreadTurnsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    thread_id=command.thread_id,
                    ok=False,
                    error="Codex executor does not support thread/turns/list.",
                ).model_dump(mode="json"),
            )
            return
        try:
            raw_page = await list_turns(
                thread_id=command.thread_id,
                limit=command.limit,
                cursor=command.cursor,
            )
            await self._send_json(
                websocket,
                CodexThreadTurnsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    thread_id=command.thread_id,
                    turns=raw_page.turns,
                    goal=raw_page.goal,
                    next_cursor=raw_page.next_cursor,
                    previous_cursor=raw_page.previous_cursor,
                ).model_dump(mode="json"),
            )
        except Exception as exc:
            await self._send_json(
                websocket,
                CodexThreadTurnsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    thread_id=command.thread_id,
                    ok=False,
                    error=str(exc),
                ).model_dump(mode="json"),
            )

    async def _read_codex_thread(self, websocket: Any, command: ReadCodexThreadCommand) -> None:
        executor = self._executors.get(command.executor_type)
        read_thread = getattr(executor, "read_thread", None)
        if read_thread is None:
            await self._send_json(
                websocket,
                CodexThreadReadMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    ok=False,
                    error="Codex executor does not support thread/read.",
                ).model_dump(mode="json"),
            )
            return
        try:
            thread = await read_thread(command.thread_id)
            await self._send_json(
                websocket,
                CodexThreadReadMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    thread=thread,
                ).model_dump(mode="json"),
            )
        except Exception as exc:
            await self._send_json(
                websocket,
                CodexThreadReadMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    ok=False,
                    error=str(exc),
                ).model_dump(mode="json"),
            )

    async def _start_codex_turn(self, websocket: Any, command: StartCodexTurnCommand) -> None:
        executor = self._executors.get(command.executor_type)
        starter = getattr(executor, "start_turn_request", None)
        failure_message = f"Executor '{command.executor_type}' does not support start_codex_turn."
        if starter is None:
            await self._send_codex_turn_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED.value,
                message=failure_message,
                ok=False,
                error=failure_message,
                metadata=_codex_turn_command_metadata(command),
            )
            return
        try:
            async for event in starter(command):
                metadata = _codex_turn_command_metadata(command, event.metadata)
                event_type = event.event_type.value
                failed = event.event_type == ExecutorEventType.FAILED
                await self._send_codex_turn_event(
                    websocket,
                    command,
                    event_type=event_type,
                    message=event.message,
                    executor_thread_id=_metadata_str(metadata, "executor_thread_id")
                    or _metadata_str(metadata, "thread_id"),
                    executor_turn_id=_metadata_str(metadata, "executor_turn_id")
                    or _metadata_str(metadata, "turn_id"),
                    ok=not failed,
                    error=event.message if failed else None,
                    metadata=metadata,
                )
        except Exception as exc:
            await self._send_codex_turn_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED.value,
                message=str(exc),
                ok=False,
                error=str(exc),
                metadata=_codex_turn_command_metadata(command),
            )

    async def _subscribe_codex_thread(self, websocket: Any, command: SubscribeCodexThreadCommand) -> None:
        await self._stop_codex_thread_subscription(command.subscription_id)
        executor = self._executors.get(command.executor_type)
        subscribe_thread = getattr(executor, "subscribe_thread", None)
        if subscribe_thread is None:
            await self._send_json(
                websocket,
                CodexThreadSubscribedMessage(
                    request_id=command.request_id,
                    subscription_id=command.subscription_id,
                    node_id=self._settings.node_id,
                    session_id=command.session_id,
                    target_persona_id=command.target_persona_id,
                    target_thread_id=command.target_thread_id,
                    thread_id=command.thread_id,
                    ok=False,
                    error="Codex executor does not support selected-thread subscription.",
                ).model_dump(mode="json"),
            )
            return
        try:
            session = await subscribe_thread(command.thread_id, workspace_id=command.workspace_id)
        except Exception as exc:
            await self._send_json(
                websocket,
                CodexThreadSubscribedMessage(
                    request_id=command.request_id,
                    subscription_id=command.subscription_id,
                    node_id=self._settings.node_id,
                    session_id=command.session_id,
                    target_persona_id=command.target_persona_id,
                    target_thread_id=command.target_thread_id,
                    thread_id=command.thread_id,
                    ok=False,
                    error=str(exc),
                ).model_dump(mode="json"),
            )
            return
        if command.workspace_id:
            self._thread_workspaces[command.thread_id] = str(resolve_workspace(command.workspace_id))
        task = asyncio.create_task(self._stream_codex_thread_events(websocket, session, command))
        self._codex_thread_subscriptions[command.subscription_id] = CodexThreadSubscriptionContext(
            executor=executor,
            session=session,
            command=command,
            background_task=task,
        )
        await self._send_json(
            websocket,
            CodexThreadSubscribedMessage(
                request_id=command.request_id,
                subscription_id=command.subscription_id,
                node_id=self._settings.node_id,
                session_id=command.session_id,
                target_persona_id=command.target_persona_id,
                target_thread_id=command.target_thread_id,
                thread_id=command.thread_id,
                metadata={"source": "thread/resume"},
            ).model_dump(mode="json"),
        )

    async def _unsubscribe_codex_thread(self, websocket: Any, command: UnsubscribeCodexThreadCommand) -> None:
        status = await self._stop_codex_thread_subscription(command.subscription_id)
        await self._send_json(
            websocket,
            CodexThreadUnsubscribedMessage(
                request_id=command.request_id,
                subscription_id=command.subscription_id,
                node_id=self._settings.node_id,
                thread_id=command.thread_id,
                status=status,
            ).model_dump(mode="json"),
        )

    async def _stop_codex_thread_subscription(self, subscription_id: str) -> str:
        context = self._codex_thread_subscriptions.pop(subscription_id, None)
        if context is None:
            return "notSubscribed"
        status = "unsubscribed"
        unsubscribe_thread = getattr(context.executor, "unsubscribe_thread", None)
        try:
            if unsubscribe_thread is not None:
                response = await unsubscribe_thread(context.session)
                response_status = response.get("status") if isinstance(response, dict) else None
                if isinstance(response_status, str) and response_status:
                    status = response_status
            else:
                await context.session.close()
        except Exception as exc:
            status = f"error:{exc}"
            with contextlib.suppress(Exception):
                await context.session.close()
        context.background_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await context.background_task
        return status

    async def _stream_codex_thread_events(
        self,
        websocket: Any,
        session: CodexExecutorSession,
        command: SubscribeCodexThreadCommand,
    ) -> None:
        executor = self._executors.get(command.executor_type)
        next_thread_event = getattr(executor, "next_thread_event", None)
        try:
            while True:
                if next_thread_event is not None:
                    event = await next_thread_event(session)
                else:
                    event = await session.client.next_event()
                method = str(event.get("method") or "")
                if not method:
                    continue
                params = event.get("params")
                if not isinstance(params, dict):
                    params = {}
                event_thread_id = _event_thread_id(params) or command.thread_id
                if event_thread_id != command.thread_id:
                    continue
                await self._send_json(
                    websocket,
                    CodexThreadEventMessage(
                        subscription_id=command.subscription_id,
                        node_id=self._settings.node_id,
                        session_id=command.session_id,
                        target_persona_id=command.target_persona_id,
                        target_thread_id=command.target_thread_id,
                        thread_id=command.thread_id,
                        method=method,
                        params=params,
                    ).model_dump(mode="json"),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning(
                "Selected Codex thread subscription stopped subscription_id=%s thread_id=%s: %s",
                command.subscription_id,
                command.thread_id,
                exc,
            )

    async def _transcribe_audio_instruction(
        self,
        websocket: Any,
        command: TranscribeAudioInstructionCommand,
    ) -> None:
        if not self._audio_transcriber.available:
            await self._send_json(
                websocket,
                AudioInstructionTranscribedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    executor_type=command.executor_type,
                    ok=False,
                    error="Local Whisper transcription is not available on this executor node.",
                ).model_dump(mode="json"),
            )
            return
        try:
            transcription = await self._audio_transcriber.transcribe(command.audio)
            transcript = transcription.text.strip()
            if not transcript:
                raise RuntimeError("Audio transcription produced no instruction text.")
            await self._send_json(
                websocket,
                AudioInstructionTranscribedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    executor_type=command.executor_type,
                    transcript_text=transcript,
                    language=transcription.language,
                    duration_seconds=transcription.duration_seconds,
                    metadata={
                        "source": "executor_node_whisper",
                        "source_audio_instruction_id": command.audio.audio_instruction_id,
                        "target_thread_id": command.audio.target_thread_id or "",
                        **(transcription.metadata or {}),
                    },
                ).model_dump(mode="json"),
            )
        except Exception as exc:
            await self._send_json(
                websocket,
                AudioInstructionTranscribedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    executor_type=command.executor_type,
                    ok=False,
                    error=str(exc),
                ).model_dump(mode="json"),
            )

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
        client_request_id = command.audio.metadata.get("client_request_id")
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
                transcription_metadata = {
                    "source": "executor_node_whisper",
                    "source_audio_instruction_id": command.audio.audio_instruction_id,
                    "target_thread_id": command.audio.target_thread_id or "",
                    "transcript_text": transcript,
                    "transcription_language": transcription.language or "",
                    "transcription_duration_seconds": transcription.duration_seconds or 0,
                    "client_request_id": client_request_id,
                    **(transcription.metadata or {}),
                }
                await self._send_json(
                    websocket,
                    RunEventMessage(
                        run_id=command.run_id,
                        execution_session_id=command.execution_session_id,
                        executor_type=command.executor_type,
                        session_id=session.session_id,
                        event_type=ExecutorEventType.PROGRESS.value,
                        message="Audio instruction transcribed.",
                        metadata=transcription_metadata,
                        latest_resume_handle=_build_resume_handle(context.executor, session),
                    ).model_dump(mode="json"),
                )
                return
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
                event_metadata = dict(event.metadata)
                event_metadata.setdefault("client_request_id", client_request_id)
                event_metadata.setdefault("source_audio_instruction_id", command.audio.audio_instruction_id)
                await self._send_json(
                    websocket,
                    RunEventMessage(
                        run_id=command.run_id,
                        execution_session_id=command.execution_session_id,
                        executor_type=command.executor_type,
                        session_id=session.session_id,
                        event_type=event.event_type.value,
                        message=event.message,
                        metadata=event_metadata,
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
        started_at = time.perf_counter()
        client_request_id = command.instruction.metadata.get("client_request_id")
        _emit_executor_text_metric(
            "executor_text_metric step=node.dispatch.received node_id=%s client_request_id=%s instruction_id=%s task_id=%s run_id=%s execution_session_id=%s",
            self._settings.node_id,
            client_request_id,
            command.instruction.instruction_id,
            command.task_id,
            command.run_id,
            command.execution_session_id,
        )
        context = self._active_runs.get(command.run_id)
        session = self._live_sessions.get(command.execution_session_id)
        if context is None or session is None:
            _emit_executor_text_metric(
                "executor_text_metric step=node.dispatch.rejected node_id=%s client_request_id=%s instruction_id=%s task_id=%s run_id=%s elapsed_ms=%s reason=no_active_run",
                self._settings.node_id,
                client_request_id,
                command.instruction.instruction_id,
                command.task_id,
                command.run_id,
                int((time.perf_counter() - started_at) * 1000),
            )
            await self._send_text_instruction_event(
                websocket,
                command,
                event_type=ExecutorEventType.FAILED,
                message="No active executor run is available for text.",
            )
            return
        text_handler = getattr(context.executor, "handle_text_instruction", None)
        if text_handler is None:
            _emit_executor_text_metric(
                "executor_text_metric step=node.dispatch.rejected node_id=%s client_request_id=%s instruction_id=%s task_id=%s run_id=%s elapsed_ms=%s reason=unsupported",
                self._settings.node_id,
                client_request_id,
                command.instruction.instruction_id,
                command.task_id,
                command.run_id,
                int((time.perf_counter() - started_at) * 1000),
            )
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
                event_metadata = dict(event.metadata)
                event_metadata.setdefault("client_request_id", client_request_id)
                event_metadata.setdefault("instruction_id", command.instruction.instruction_id)
                _emit_executor_text_metric(
                    "executor_text_metric step=node.event.%s node_id=%s client_request_id=%s instruction_id=%s task_id=%s run_id=%s elapsed_ms=%s",
                    event.event_type.value,
                    self._settings.node_id,
                    client_request_id,
                    command.instruction.instruction_id,
                    command.task_id,
                    command.run_id,
                    int((time.perf_counter() - started_at) * 1000),
                )
                await self._send_json(
                    websocket,
                    RunEventMessage(
                        run_id=command.run_id,
                        execution_session_id=command.execution_session_id,
                        executor_type=command.executor_type,
                        session_id=session.session_id,
                        event_type=event.event_type.value,
                        message=event.message,
                        metadata=event_metadata,
                        latest_resume_handle=_build_resume_handle(context.executor, session),
                    ).model_dump(mode="json"),
                )
        except Exception as exc:
            _emit_executor_text_metric(
                "executor_text_metric step=node.dispatch.failed node_id=%s client_request_id=%s instruction_id=%s task_id=%s run_id=%s elapsed_ms=%s",
                self._settings.node_id,
                client_request_id,
                command.instruction.instruction_id,
                command.task_id,
                command.run_id,
                int((time.perf_counter() - started_at) * 1000),
            )
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
        if not isinstance(command.native_response, dict):
            return
        session = self._resolve_interaction_target_session(command)
        if session is None:
            return
        try:
            await session.client.respond_to_request(
                request_id=command.native_response.get("request_id"),
                method=str(command.native_response.get("method") or ""),
                params=dict(command.native_response.get("params") or {}),
                action=command.action,
                answer_text=command.answer_text,
                answers=command.answers,
            )
        except Exception as exc:
            LOGGER.warning(
                "Failed to forward interaction response to executor node session "
                "execution_session_id=%s outbound_turn_request_id=%s interaction_request_id=%s: %s",
                command.execution_session_id,
                command.outbound_turn_request_id,
                command.interaction_request_id,
                exc,
            )
            return
        session.mark_blocked_resolved()

    def _resolve_interaction_target_session(
        self,
        command: SupplyInteractionResponseCommand,
    ) -> CodexExecutorSession | None:
        if isinstance(command.execution_session_id, str) and command.execution_session_id:
            candidate = self._live_sessions.get(command.execution_session_id)
            if isinstance(candidate, CodexExecutorSession):
                return candidate
        if isinstance(command.outbound_turn_request_id, str) and command.outbound_turn_request_id:
            executor = self._executors.get("codex")
            active_runs = getattr(executor, "_active_runs", None)
            if isinstance(active_runs, dict):
                candidate = active_runs.get(command.outbound_turn_request_id)
                if isinstance(candidate, CodexExecutorSession):
                    return candidate
        return None

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
                    "client_request_id": command.instruction.metadata.get("client_request_id"),
                    "source": "executor_text_instruction",
                },
                latest_resume_handle=None,
            ).model_dump(mode="json"),
        )

    async def _send_codex_turn_event(
        self,
        websocket: Any,
        command: StartCodexTurnCommand,
        *,
        event_type: str,
        message: str | None,
        executor_thread_id: str | None = None,
        executor_turn_id: str | None = None,
        ok: bool = True,
        error: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self._send_json(
            websocket,
            CodexTurnEventMessage(
                request_id=command.request_id,
                node_id=self._settings.node_id,
                target_persona_id=command.target_persona_id,
                target_thread_id=command.target_thread_id,
                event_type=event_type,
                message=message,
                executor_thread_id=executor_thread_id,
                executor_turn_id=executor_turn_id,
                ok=ok,
                error=error,
                metadata=dict(metadata or {}),
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
            supports_thread_list=bool(
                executor_type == "codex"
                and hasattr(executor, "list_threads_page")
                and capabilities.availability_reason is None
            ),
            supports_pause=capabilities.supports_pause,
            supports_cancel=capabilities.supports_cancel,
            version=capabilities.version,
            minimum_version=capabilities.minimum_version,
            availability_reason=capabilities.availability_reason,
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

    async def _cancel_codex_thread_subscriptions(self) -> None:
        subscription_ids = list(self._codex_thread_subscriptions)
        for subscription_id in subscription_ids:
            await self._stop_codex_thread_subscription(subscription_id)

    async def _cancel_background_commands(self) -> None:
        tasks = list(self._background_commands)
        self._background_commands.clear()
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _read_workspace_file(
        self, websocket: Any, command: ReadWorkspaceFileCommand
    ) -> None:
        root = self._thread_workspaces.get(command.thread_id)
        if root is None and command.executor_thread_id:
            # Imported/history thread: resolve the workspace from the codex
            # thread's own cwd learned during list_threads.
            root = self._codex_thread_workspaces.get(command.executor_thread_id)
        if root is None:
            await self._send_json(
                websocket,
                WorkspaceFileError(
                    request_id=command.request_id,
                    code="denied",
                    message="no workspace binding for thread",
                ).model_dump(mode="json"),
            )
            return
        try:
            real = resolve_within_workspace(command.path, root)
        except WorkspaceFileAccessError as exc:
            await self._send_json(
                websocket,
                WorkspaceFileError(
                    request_id=command.request_id, code=exc.code, message=exc.message
                ).model_dump(mode="json"),
            )
            return

        digest = hashlib.sha256()
        seq = 0
        total = 0
        try:
            # iter_file_bytes does the size-cap check before the first yield, so a
            # too_large file errors before any chunk is sent.
            for block in iter_file_bytes(real):
                digest.update(block)
                total += len(block)
                await self._send_json(
                    websocket,
                    WorkspaceFileChunk(
                        request_id=command.request_id,
                        seq=seq,
                        data=base64.b64encode(block).decode("ascii"),
                    ).model_dump(mode="json"),
                )
                seq += 1
        except WorkspaceFileAccessError as exc:
            await self._send_json(
                websocket,
                WorkspaceFileError(
                    request_id=command.request_id, code=exc.code, message=exc.message
                ).model_dump(mode="json"),
            )
            return
        await self._send_json(
            websocket,
            WorkspaceFileEof(
                request_id=command.request_id,
                total_bytes=total,
                sha256=digest.hexdigest(),
            ).model_dump(mode="json"),
        )

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


def _codex_thread_list_item(item: dict[str, object]) -> CodexThreadListItem:
    thread_id = item.get("id") or item.get("threadId") or item.get("sessionId")
    if not isinstance(thread_id, str) or not thread_id:
        raise RuntimeError("Codex thread/list returned a thread without an id.")
    status_value = item.get("status")
    if isinstance(status_value, dict):
        status = status_value.get("type")
    else:
        status = status_value
    name = item.get("name")
    return CodexThreadListItem(
        thread_id=thread_id,
        session_id=str(item.get("sessionId")) if item.get("sessionId") is not None else None,
        preview=str(item.get("preview")) if item.get("preview") is not None else None,
        title=str(name) if isinstance(name, str) and name.strip() else None,
        cwd=str(item.get("cwd")) if item.get("cwd") is not None else None,
        path=str(item.get("path")) if item.get("path") is not None else None,
        status=str(status) if status is not None else None,
        created_at=item.get("createdAt") if isinstance(item.get("createdAt"), int) else None,
        updated_at=item.get("updatedAt") if isinstance(item.get("updatedAt"), int) else None,
        cli_version=str(item.get("cliVersion")) if item.get("cliVersion") is not None else None,
        source=str(item.get("source")) if item.get("source") is not None else None,
        diagnostics={
            "forked_from_id": item.get("forkedFromId"),
            "ephemeral": item.get("ephemeral"),
            "model_provider": item.get("modelProvider"),
            "thread_source": item.get("threadSource"),
            "agent_nickname": item.get("agentNickname"),
            "agent_role": item.get("agentRole"),
            "git_info": item.get("gitInfo"),
        },
    )


def _event_thread_id(params: dict[str, object]) -> str | None:
    value = params.get("threadId")
    if isinstance(value, str) and value:
        return value
    thread = params.get("thread")
    if isinstance(thread, dict):
        value = thread.get("id") or thread.get("threadId")
        if isinstance(value, str) and value:
            return value
    turn = params.get("turn")
    if isinstance(turn, dict):
        value = turn.get("threadId")
        if isinstance(value, str) and value:
            return value
    item = params.get("item")
    if isinstance(item, dict):
        value = item.get("threadId")
        if isinstance(value, str) and value:
            return value
    return None


def _metadata_str(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _codex_turn_command_metadata(
    command: StartCodexTurnCommand,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata = dict(command.metadata)
    metadata.update(extra or {})
    metadata["instruction_id"] = command.instruction.instruction_id
    metadata["target_persona_id"] = command.target_persona_id
    metadata["target_thread_id"] = command.target_thread_id
    client_request_id = command.instruction.metadata.get("client_request_id")
    if isinstance(client_request_id, str) and client_request_id:
        metadata["client_request_id"] = client_request_id
    if command.instruction.source_audio_instruction_id is not None:
        metadata["source_audio_instruction_id"] = command.instruction.source_audio_instruction_id
    return metadata


def _format_executor_types(executor_types: list[str]) -> str:
    if not executor_types:
        return "none"
    return ",".join(executor_types)


def _format_exception_summary(error: BaseException) -> str:
    detail = str(error).strip()
    if not detail:
        return type(error).__name__
    return f"{type(error).__name__}: {detail}"
