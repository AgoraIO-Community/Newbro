from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from newbro.executors.core import ExecutorEvent, ExecutorEventType
from newbro.protocol import (
    AckMessage,
    AgentResumeHandle,
    AudioInstructionTranscribedMessage,
    CancelRunCommand,
    CodexThreadEventMessage,
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
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    ExecutorNodeExecutor,
    ExecutorNodeRecord,
    InteractionRequest,
    ListCodexThreadTurnsCommand,
    ListCodexThreadsCommand,
    ReadCodexThreadCommand,
    ReadWorkspaceFileCommand,
    RegisterNodeMessage,
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
from newbro.executors.node.registry import (
    ExecutorNodeConnectionView,
    ExecutorNodeRegistry,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class NodeRunEnvelope:
    event: ExecutorEvent
    latest_resume_handle: dict[str, object] | None = None


@dataclass(slots=True)
class RunDispatchState:
    run_id: str
    execution_session_id: str
    executor_type: str
    node_id: str | None = None


@dataclass(slots=True)
class NodeConnectionState:
    websocket: Any
    node_id: str
    connected_at: str
    metadata: dict[str, object] = field(default_factory=dict)
    executors: dict[str, ExecutorNodeExecutor] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


@dataclass(frozen=True, slots=True)
class CodexThreadListPage:
    threads: list[CodexThreadListItem]
    next_cursor: str | None = None
    previous_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CodexThreadTurnPage:
    thread_id: str
    turns: list[dict[str, object]]
    goal: str | None = None
    next_cursor: str | None = None
    previous_cursor: str | None = None


class ExecutorNodeAuthError(RuntimeError):
    pass


class WorkspaceFileUnavailable(Exception):
    """The node is offline / unreachable / timed out."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkspaceFileDenied(Exception):
    """The node refused the file (denied / not_found / too_large / read_error)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ExecutorNodeManager:
    def __init__(
        self,
        *,
        detached_executor_types: tuple[str, ...],
        registry: ExecutorNodeRegistry | None = None,
    ) -> None:
        self._detached_executor_types = detached_executor_types
        self._registry = registry or ExecutorNodeRegistry()
        self._connections_by_node: dict[str, NodeConnectionState] = {}
        self._connections_lock = asyncio.Lock()
        self._run_queues: dict[str, asyncio.Queue[NodeRunEnvelope]] = {}
        self._run_states: dict[str, RunDispatchState] = {}
        self._audio_transcription_requests: dict[str, asyncio.Future[AudioInstructionTranscribedMessage]] = {}
        self._codex_thread_list_requests: dict[str, asyncio.Future[CodexThreadsListedMessage]] = {}
        self._codex_thread_read_requests: dict[str, asyncio.Future[CodexThreadReadMessage]] = {}
        self._codex_thread_subscribe_requests: dict[str, asyncio.Future[CodexThreadSubscribedMessage]] = {}
        self._codex_thread_unsubscribe_requests: dict[str, asyncio.Future[CodexThreadUnsubscribedMessage]] = {}
        self._codex_thread_event_queue: asyncio.Queue[CodexThreadEventMessage] = asyncio.Queue()
        self._workspace_file_streams: dict[
            str, asyncio.Queue[WorkspaceFileChunk | WorkspaceFileEof | WorkspaceFileError]
        ] = {}
        self._codex_thread_turn_list_requests: dict[str, asyncio.Future[CodexThreadTurnsListedMessage]] = {}

    @property
    def detached_executor_types(self) -> tuple[str, ...]:
        return self._detached_executor_types

    @property
    def node_id(self) -> str | None:
        if len(self._connections_by_node) == 1:
            return next(iter(self._connections_by_node))
        return None

    @property
    def connected(self) -> bool:
        return bool(self._connections_by_node)

    def is_detached_executor(self, executor_type: str) -> bool:
        return executor_type in self._detached_executor_types

    def is_node_connected(self, node_id: str) -> bool:
        return node_id in self._connections_by_node

    def is_executor_connected(self, executor_type: str, *, node_id: str | None = None) -> bool:
        if node_id is not None:
            state = self._connections_by_node.get(node_id)
            return state is not None and executor_type in state.executors
        return any(executor_type in state.executors for state in self._connections_by_node.values())

    def executor_supports_audio_instruction(self, executor_type: str, *, node_id: str) -> bool:
        state = self._connections_by_node.get(node_id)
        if state is None:
            return False
        executor = state.executors.get(executor_type)
        return executor is not None and executor.supports_audio_instruction

    def executor_supports_follow_up(self, executor_type: str, *, node_id: str) -> bool:
        state = self._connections_by_node.get(node_id)
        if state is None:
            return False
        executor = state.executors.get(executor_type)
        return executor is not None and executor.supports_follow_up

    def executor_supports_thread_list(self, executor_type: str, *, node_id: str) -> bool:
        state = self._connections_by_node.get(node_id)
        if state is None:
            return False
        executor = state.executors.get(executor_type)
        return (
            executor is not None
            and executor.supports_thread_list
            and executor.availability_reason is None
        )

    def codex_thread_events(self) -> asyncio.Queue[CodexThreadEventMessage]:
        return self._codex_thread_event_queue

    def executor_availability(self, executor_type: str, *, node_id: str | None = None) -> dict[str, object]:
        if not self.is_detached_executor(executor_type):
            return {
                "connected": True,
                "node_id": None,
                "availability_reason": None,
            }
        if node_id is None:
            if not self._connections_by_node:
                return {
                    "connected": False,
                    "node_id": None,
                    "availability_reason": "node_disconnected",
                }
            if self.is_executor_connected(executor_type):
                first_match = next(
                    (
                        state.node_id
                        for state in self._connections_by_node.values()
                        if executor_type in state.executors
                    ),
                    None,
                )
                return {
                    "connected": True,
                    "node_id": first_match,
                    "availability_reason": None,
                }
            return {
                "connected": False,
                "node_id": self.node_id,
                "availability_reason": "node_missing_executor",
            }
        state = self._connections_by_node.get(node_id)
        if state is not None and executor_type in state.executors:
            return {
                "connected": True,
                "node_id": node_id,
                "availability_reason": None,
            }
        return {
            "connected": False,
            "node_id": node_id,
            "availability_reason": "node_disconnected" if state is None else "node_missing_executor",
        }

    async def register_connection(self, websocket: Any, register: RegisterNodeMessage) -> AckMessage:
        record = await self._registry.verify_credentials(
            node_id=register.node_id,
            token=register.token,
        )
        if record is None:
            raise ExecutorNodeAuthError("Invalid executor node credentials.")
        displaced_node_id: str | None = None
        async with self._connections_lock:
            existing_node_id = self._node_id_for_websocket_locked(websocket)
            if existing_node_id is not None and existing_node_id != register.node_id:
                displaced_node_id = existing_node_id
                self._connections_by_node.pop(existing_node_id, None)
            existing_state = self._connections_by_node.get(register.node_id)
            if existing_state is not None and existing_state.websocket is not websocket:
                raise ExecutorNodeAuthError(f"Executor node '{register.node_id}' is already connected.")
            self._connections_by_node[register.node_id] = NodeConnectionState(
                websocket=websocket,
                node_id=register.node_id,
                connected_at=_timestamp(),
                metadata=dict(register.metadata),
                executors={executor.executor_type: executor for executor in register.executors},
            )
        if displaced_node_id is not None:
            await self._handle_node_disconnected(displaced_node_id, reason="re_registered")
        await self._registry.note_connected(register.node_id)
        return AckMessage(message_type=register.type, detail="registered")

    async def disconnect(self, *, websocket: Any, reason: str) -> None:
        async with self._connections_lock:
            node_id = self._node_id_for_websocket_locked(websocket)
            if node_id is not None:
                self._connections_by_node.pop(node_id, None)
        if node_id is None:
            return
        await self._handle_node_disconnected(node_id, reason=reason)

    async def dispatch_run(
        self,
        *,
        run_id: str,
        execution_session_id: str,
        executor_type: str,
        task_id: str,
        title: str,
        goal: str,
        latest_instruction: str | None,
        workspace_id: str | None,
        task_metadata: dict[str, object],
        latest_resume_handle: dict[str, object] | None,
        node_id: str | None,
    ) -> asyncio.Queue[NodeRunEnvelope]:
        queue: asyncio.Queue[NodeRunEnvelope] = asyncio.Queue()
        self._run_queues[run_id] = queue
        self._run_states[run_id] = RunDispatchState(
            run_id=run_id,
            execution_session_id=execution_session_id,
            executor_type=executor_type,
            node_id=node_id,
        )
        if node_id is None:
            await queue.put(
                NodeRunEnvelope(
                    event=ExecutorEvent(
                        run_id=run_id,
                        session_id=execution_session_id,
                        event_type=ExecutorEventType.WAITING_EXECUTOR,
                        message="Waiting for this bro to be bound to an executor node.",
                        metadata={
                            "executor_node_id": None,
                            "availability_reason": "bro_unbound",
                        },
                    )
                )
            )
            return queue
        if not self.is_executor_connected(executor_type, node_id=node_id):
            node_label = node_id
            await queue.put(
                NodeRunEnvelope(
                    event=ExecutorEvent(
                        run_id=run_id,
                        session_id=execution_session_id,
                        event_type=ExecutorEventType.WAITING_EXECUTOR,
                        message=f"Waiting for {node_label} to connect.",
                        metadata={
                            "executor_node_id": node_id,
                            "availability_reason": self.executor_availability(
                                executor_type,
                                node_id=node_id,
                            )["availability_reason"],
                        },
                    )
                )
            )
            return queue

        command = DispatchRunCommand(
            run_id=run_id,
            execution_session_id=execution_session_id,
            executor_type=executor_type,
            task_id=task_id,
            title=title,
            goal=goal,
            latest_instruction=latest_instruction,
            workspace_id=workspace_id,
            task_metadata=task_metadata,
            latest_resume_handle=latest_resume_handle,
        )
        connection = await self._connection_for_node(node_id)
        if connection is None:
            await queue.put(
                NodeRunEnvelope(
                    event=ExecutorEvent(
                        run_id=run_id,
                        session_id=execution_session_id,
                        event_type=ExecutorEventType.WAITING_EXECUTOR,
                        message=f"Waiting for {node_id} to connect.",
                        metadata={
                            "executor_node_id": node_id,
                            "availability_reason": "node_disconnected",
                        },
                    )
                )
            )
            return queue
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
        except Exception:
            await self.disconnect(websocket=connection.websocket, reason="dispatch_failed")
        return queue

    async def cancel_run(self, run_id: str, *, mode: str = "cancel") -> None:
        state = self._run_states.get(run_id)
        if state is None or state.node_id is None:
            return
        connection = await self._connection_for_node(state.node_id)
        if connection is None:
            return
        command = CancelRunCommand(
            run_id=run_id,
            execution_session_id=state.execution_session_id,
            mode="pause" if mode == "pause" else "cancel",
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
        except Exception:
            await self.disconnect(websocket=connection.websocket, reason="cancel_failed")

    async def dispatch_audio_instruction(
        self,
        *,
        run_id: str,
        execution_session_id: str,
        executor_type: str,
        task_id: str,
        node_id: str,
        audio: ExecutorAudioInstruction,
    ) -> bool:
        connection = await self._connection_for_node(node_id)
        if connection is None:
            return False
        executor = connection.executors.get(executor_type)
        if executor is None or not executor.supports_audio_instruction:
            return False
        command = DispatchAudioInstructionCommand(
            run_id=run_id,
            execution_session_id=execution_session_id,
            executor_type=executor_type,
            task_id=task_id,
            audio=audio,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
        except Exception:
            await self.disconnect(websocket=connection.websocket, reason="audio_instruction_failed")
            return False
        return True

    async def transcribe_audio_instruction(
        self,
        *,
        executor_type: str,
        node_id: str,
        audio: ExecutorAudioInstruction,
        timeout_seconds: float = 30.0,
    ) -> AudioInstructionTranscribedMessage:
        connection = await self._connection_for_node(node_id)
        if connection is None:
            raise RuntimeError("Codex executor node is not connected.")
        executor = connection.executors.get(executor_type)
        if executor is None or not executor.supports_audio_instruction:
            raise RuntimeError("Selected Bro's executor node does not support audio transcription instructions.")
        request_id = f"audio-transcribe-{uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[AudioInstructionTranscribedMessage] = loop.create_future()
        self._audio_transcription_requests[request_id] = future
        command = TranscribeAudioInstructionCommand(
            request_id=request_id,
            executor_type=executor_type,
            audio=audio,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
        except Exception:
            self._audio_transcription_requests.pop(request_id, None)
            raise
        if not response.ok:
            raise RuntimeError(response.error or "Audio transcription failed.")
        return response

    def publish_audio_instruction_transcribed(self, message: AudioInstructionTranscribedMessage) -> AckMessage:
        future = self._audio_transcription_requests.pop(message.request_id, None)
        if future is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        if not future.done():
            future.set_result(message)
        return AckMessage(message_type=message.type, detail="queued")

    async def dispatch_text_instruction(
        self,
        *,
        run_id: str,
        execution_session_id: str,
        executor_type: str,
        task_id: str,
        node_id: str,
        instruction: ExecutorTextInstruction,
    ) -> bool:
        connection = await self._connection_for_node(node_id)
        if connection is None:
            return False
        executor = connection.executors.get(executor_type)
        if executor is None or not executor.supports_follow_up:
            return False
        command = DispatchTextInstructionCommand(
            run_id=run_id,
            execution_session_id=execution_session_id,
            executor_type=executor_type,
            task_id=task_id,
            instruction=instruction,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
        except Exception:
            await self.disconnect(websocket=connection.websocket, reason="text_instruction_failed")
            return False
        return True

    async def start_codex_turn(
        self,
        *,
        request_id: str,
        node_id: str,
        target_persona_id: str,
        target_thread_id: str,
        instruction: ExecutorTextInstruction,
        thread_id: str | None = None,
        create_new_thread: bool = False,
        workspace_id: str | None = None,
        latest_resume_handle: AgentResumeHandle | None = None,
        metadata: dict[str, object] | None = None,
    ) -> bool:
        connection = await self._connection_for_node(node_id)
        if connection is None:
            return False
        if "codex" not in connection.executors:
            return False
        command = StartCodexTurnCommand(
            request_id=request_id,
            target_persona_id=target_persona_id,
            target_thread_id=target_thread_id,
            thread_id=thread_id,
            create_new_thread=create_new_thread,
            workspace_id=workspace_id,
            instruction=instruction,
            latest_resume_handle=latest_resume_handle,
            metadata=dict(metadata or {}),
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
        except Exception:
            await self.disconnect(websocket=connection.websocket, reason="codex_turn_start_failed")
            return False
        return True

    async def request_codex_threads(
        self,
        *,
        node_id: str,
        workspace_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        sort_key: Literal["created_at", "updated_at"] = "updated_at",
        sort_direction: Literal["asc", "desc"] = "desc",
        timeout_seconds: float = 8.0,
    ) -> CodexThreadListPage:
        connection = await self._connection_for_node(node_id)
        if connection is None or "codex" not in connection.executors:
            return CodexThreadListPage(threads=[])
        executor = connection.executors["codex"]
        if not executor.supports_thread_list:
            return CodexThreadListPage(threads=[])
        request_id = f"codex-thread-list-{uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodexThreadsListedMessage] = loop.create_future()
        self._codex_thread_list_requests[request_id] = future
        command = ListCodexThreadsCommand(
            request_id=request_id,
            workspace_id=workspace_id,
            limit=limit,
            cursor=cursor,
            sort_key=sort_key,
            sort_direction=sort_direction,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            self._codex_thread_list_requests.pop(request_id, None)
            raise TimeoutError("Timed out listing Codex threads.") from exc
        except Exception:
            self._codex_thread_list_requests.pop(request_id, None)
            raise
        if not response.ok:
            raise RuntimeError(response.error or "Codex thread/list failed.")
        return CodexThreadListPage(
            threads=response.threads,
            next_cursor=response.next_cursor,
            previous_cursor=response.previous_cursor,
        )

    def publish_codex_threads_listed(self, message: CodexThreadsListedMessage) -> AckMessage:
        future = self._codex_thread_list_requests.pop(message.request_id, None)
        if future is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        if not future.done():
            future.set_result(message)
        return AckMessage(message_type=message.type, detail="queued")

    async def request_codex_thread_turns(
        self,
        *,
        node_id: str,
        thread_id: str,
        limit: int = 100,
        cursor: str | None = None,
        timeout_seconds: float = 8.0,
    ) -> CodexThreadTurnPage:
        connection = await self._connection_for_node(node_id)
        if connection is None or "codex" not in connection.executors:
            raise RuntimeError("Codex executor node is not connected.")
        request_id = f"codex-thread-turns-{uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodexThreadTurnsListedMessage] = loop.create_future()
        self._codex_thread_turn_list_requests[request_id] = future
        command = ListCodexThreadTurnsCommand(
            request_id=request_id,
            thread_id=thread_id,
            limit=limit,
            cursor=cursor,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            self._codex_thread_turn_list_requests.pop(request_id, None)
            raise TimeoutError("Timed out listing Codex thread turns.") from exc
        except Exception:
            self._codex_thread_turn_list_requests.pop(request_id, None)
            raise
        if not response.ok:
            raise RuntimeError(response.error or "Codex thread/turns/list failed.")
        return CodexThreadTurnPage(
            thread_id=response.thread_id,
            turns=response.turns,
            goal=response.goal,
            next_cursor=response.next_cursor,
            previous_cursor=response.previous_cursor,
        )

    def publish_codex_thread_turns_listed(self, message: CodexThreadTurnsListedMessage) -> AckMessage:
        future = self._codex_thread_turn_list_requests.pop(message.request_id, None)
        if future is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        if not future.done():
            future.set_result(message)
        return AckMessage(message_type=message.type, detail="queued")

    async def request_codex_thread(
        self,
        *,
        node_id: str,
        thread_id: str,
        timeout_seconds: float = 8.0,
    ) -> dict[str, object]:
        connection = await self._connection_for_node(node_id)
        if connection is None or "codex" not in connection.executors:
            raise RuntimeError("Codex executor node is not connected.")
        request_id = f"codex-thread-read-{uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodexThreadReadMessage] = loop.create_future()
        self._codex_thread_read_requests[request_id] = future
        command = ReadCodexThreadCommand(request_id=request_id, thread_id=thread_id)
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            self._codex_thread_read_requests.pop(request_id, None)
            raise TimeoutError("Timed out reading Codex thread history.") from exc
        except Exception:
            self._codex_thread_read_requests.pop(request_id, None)
            raise
        if not response.ok:
            raise RuntimeError(response.error or "Codex thread/read failed.")
        return response.thread

    def publish_codex_thread_read(self, message: CodexThreadReadMessage) -> AckMessage:
        future = self._codex_thread_read_requests.pop(message.request_id, None)
        if future is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        if not future.done():
            future.set_result(message)
        return AckMessage(message_type=message.type, detail="queued")

    async def subscribe_codex_thread(
        self,
        *,
        node_id: str,
        subscription_id: str,
        session_id: str,
        target_persona_id: str,
        target_thread_id: str,
        thread_id: str,
        workspace_id: str | None,
        timeout_seconds: float = 8.0,
    ) -> CodexThreadSubscribedMessage:
        connection = await self._connection_for_node(node_id)
        if connection is None or "codex" not in connection.executors:
            raise RuntimeError("Codex executor node is not connected.")
        request_id = f"codex-thread-sub-{uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodexThreadSubscribedMessage] = loop.create_future()
        self._codex_thread_subscribe_requests[request_id] = future
        command = SubscribeCodexThreadCommand(
            request_id=request_id,
            subscription_id=subscription_id,
            session_id=session_id,
            target_persona_id=target_persona_id,
            target_thread_id=target_thread_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
        )
        started = time.perf_counter()
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
            LOGGER.info(
                "codex_thread subscribe round-trip node_id=%s thread_id=%s elapsed_ms=%d outcome=ok",
                node_id,
                thread_id,
                int((time.perf_counter() - started) * 1000),
            )
        except asyncio.CancelledError:
            self._codex_thread_subscribe_requests.pop(request_id, None)
            raise
        except TimeoutError as exc:
            self._codex_thread_subscribe_requests.pop(request_id, None)
            LOGGER.warning(
                "codex_thread subscribe round-trip node_id=%s thread_id=%s elapsed_ms=%d outcome=timeout",
                node_id,
                thread_id,
                int((time.perf_counter() - started) * 1000),
            )
            raise TimeoutError("Timed out subscribing to Codex thread updates.") from exc
        except Exception:
            self._codex_thread_subscribe_requests.pop(request_id, None)
            raise
        if not response.ok:
            raise RuntimeError(response.error or "Codex thread subscription failed.")
        return response

    def publish_codex_thread_subscribed(self, message: CodexThreadSubscribedMessage) -> AckMessage:
        future = self._codex_thread_subscribe_requests.pop(message.request_id, None)
        if future is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        if not future.done():
            future.set_result(message)
        return AckMessage(message_type=message.type, detail="queued")

    async def unsubscribe_codex_thread(
        self,
        *,
        node_id: str,
        subscription_id: str,
        thread_id: str,
        timeout_seconds: float = 8.0,
    ) -> CodexThreadUnsubscribedMessage | None:
        connection = await self._connection_for_node(node_id)
        if connection is None or "codex" not in connection.executors:
            return None
        request_id = f"codex-thread-unsub-{uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CodexThreadUnsubscribedMessage] = loop.create_future()
        self._codex_thread_unsubscribe_requests[request_id] = future
        command = UnsubscribeCodexThreadCommand(
            request_id=request_id,
            subscription_id=subscription_id,
            thread_id=thread_id,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.CancelledError:
            self._codex_thread_unsubscribe_requests.pop(request_id, None)
            raise
        except TimeoutError as exc:
            self._codex_thread_unsubscribe_requests.pop(request_id, None)
            raise TimeoutError("Timed out unsubscribing from Codex thread updates.") from exc
        except Exception:
            self._codex_thread_unsubscribe_requests.pop(request_id, None)
            raise
        if not response.ok:
            raise RuntimeError(response.error or "Codex thread unsubscribe failed.")
        return response

    def publish_codex_thread_unsubscribed(self, message: CodexThreadUnsubscribedMessage) -> AckMessage:
        future = self._codex_thread_unsubscribe_requests.pop(message.request_id, None)
        if future is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        if not future.done():
            future.set_result(message)
        return AckMessage(message_type=message.type, detail="queued")

    async def publish_codex_thread_event(self, websocket: Any, message: CodexThreadEventMessage) -> AckMessage:
        node_id = await self._node_id_for_websocket(websocket)
        if node_id != message.node_id:
            return AckMessage(message_type=message.type, ok=False, detail="unauthorized_node")
        await self._codex_thread_event_queue.put(message)
        if node_id is not None:
            await self._registry.note_seen(node_id)
        return AckMessage(message_type=message.type, detail="queued")

    async def publish_codex_turn_event(self, websocket: Any, message: CodexTurnEventMessage) -> AckMessage:
        node_id = await self._node_id_for_websocket(websocket)
        if node_id != message.node_id:
            return AckMessage(message_type=message.type, ok=False, detail="unauthorized_node")
        if node_id is not None:
            await self._registry.note_seen(node_id)
        return AckMessage(message_type=message.type, detail="queued")

    async def supply_interaction_response(
        self,
        request: InteractionRequest,
        *,
        action: str,
        answer_text: str | None,
        answers: dict[str, list[str]] | None = None,
        node_id: str | None = None,
    ) -> bool:
        native_response = request.opaque.get("native_response")
        if not isinstance(native_response, dict):
            return False
        state = None
        if isinstance(request.run_id, str):
            state = self._run_states.get(request.run_id)
        if state is None and isinstance(request.execution_session_id, str):
            state = next(
                (
                    candidate
                    for candidate in self._run_states.values()
                    if candidate.execution_session_id == request.execution_session_id
                ),
                None,
            )
        target_node_id = (
            state.node_id if state is not None else (request.executor_node_id or node_id)
        )
        if target_node_id is None:
            return False
        connection = await self._connection_for_node(target_node_id)
        if connection is None:
            return False
        command = SupplyInteractionResponseCommand(
            interaction_request_id=request.request_id,
            execution_session_id=request.execution_session_id,
            run_id=request.run_id,
            outbound_turn_request_id=request.outbound_turn_request_id,
            action=action,
            answer_text=answer_text,
            answers=answers,
            native_response=native_response,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
        except Exception:
            await self.disconnect(websocket=connection.websocket, reason="interaction_response_failed")
            return False
        return True

    async def publish_run_event(self, websocket: Any, message: RunEventMessage) -> AckMessage:
        node_id = await self._node_id_for_websocket(websocket)
        queue = self._run_queues.get(message.run_id)
        if queue is None:
            return AckMessage(message_type=message.type, run_id=message.run_id, ok=False, detail="unknown_run")
        state = self._run_states.get(message.run_id)
        if state is None:
            return AckMessage(message_type=message.type, run_id=message.run_id, ok=False, detail="unknown_run")
        if state.node_id != node_id:
            return AckMessage(message_type=message.type, run_id=message.run_id, ok=False, detail="unauthorized_run")
        latest_resume_handle = (
            message.latest_resume_handle.model_dump(mode="json")
            if message.latest_resume_handle is not None
            else None
        )
        if node_id is not None:
            await self._registry.note_seen(node_id)
        await queue.put(
            NodeRunEnvelope(
                event=ExecutorEvent(
                    run_id=message.run_id,
                    session_id=message.session_id,
                    event_type=ExecutorEventType(message.event_type),
                    message=message.message,
                    metadata=dict(message.metadata),
                ),
                latest_resume_handle=latest_resume_handle,
            )
        )
        return AckMessage(message_type=message.type, run_id=message.run_id, detail="queued")

    def finish_run(self, run_id: str) -> None:
        self._run_queues.pop(run_id, None)
        self._run_states.pop(run_id, None)

    async def list_nodes(self) -> list[ExecutorNodeRecord]:
        return await self._registry.list_records(self._connection_views())

    async def node_exists(self, node_id: str) -> bool:
        return await self._registry.has_node(node_id)

    async def create_node(
        self,
        *,
        name: str,
        enabled_executors: list[str],
        acpx_agent: str | None = None,
    ):
        return await self._registry.create_node(
            name=name,
            enabled_executors=enabled_executors,
            acpx_agent=acpx_agent,
        )

    async def update_node(
        self,
        node_id: str,
        *,
        name: str | None = None,
        enabled_executors: list[str] | None = None,
        acpx_agent: str | None = None,
    ) -> ExecutorNodeRecord:
        return await self._registry.update_node(
            node_id,
            name=name,
            enabled_executors=enabled_executors,
            acpx_agent=acpx_agent,
            connection=self._connection_views().get(node_id),
        )

    async def rotate_node_credentials(self, node_id: str):
        issue = await self._registry.rotate_credentials(
            node_id,
            connection=self._connection_views().get(node_id),
        )
        connection = await self._connection_for_node(node_id)
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.websocket.close(code=4403)
            await self.disconnect(websocket=connection.websocket, reason="credentials_rotated")
        return issue

    async def reveal_node_credentials(self, node_id: str):
        return await self._registry.reveal_token(node_id)

    async def delete_node(self, node_id: str) -> bool:
        connection = await self._connection_for_node(node_id)
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.websocket.close(code=4403)
            await self.disconnect(websocket=connection.websocket, reason="credentials_revoked")
        return await self._registry.delete_node(node_id)

    async def read_workspace_file(
        self,
        *,
        node_id: str,
        thread_id: str,
        path: str,
        executor_thread_id: str | None = None,
        timeout: float = 30.0,
    ) -> AsyncIterator[bytes]:
        connection = self._connections_by_node.get(node_id)
        if connection is None:
            raise WorkspaceFileUnavailable("node_offline", "executor node not connected")
        request_id = f"workspace-file-{uuid4().hex[:12]}"
        queue: asyncio.Queue[WorkspaceFileChunk | WorkspaceFileEof | WorkspaceFileError] = asyncio.Queue()
        self._workspace_file_streams[request_id] = queue
        command = ReadWorkspaceFileCommand(
            request_id=request_id,
            thread_id=thread_id,
            executor_thread_id=executor_thread_id,
            path=path,
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError as exc:
                    raise WorkspaceFileUnavailable("node_offline", "timed out") from exc
                if isinstance(message, WorkspaceFileChunk):
                    yield base64.b64decode(message.data)
                elif isinstance(message, WorkspaceFileEof):
                    return
                else:  # WorkspaceFileError
                    raise WorkspaceFileDenied(message.code, message.message)
        finally:
            self._workspace_file_streams.pop(request_id, None)

    def publish_workspace_file_chunk(self, message: WorkspaceFileChunk) -> AckMessage:
        return self._publish_workspace_file(message)

    def publish_workspace_file_eof(self, message: WorkspaceFileEof) -> AckMessage:
        return self._publish_workspace_file(message)

    def publish_workspace_file_error(self, message: WorkspaceFileError) -> AckMessage:
        return self._publish_workspace_file(message)

    def _publish_workspace_file(
        self, message: WorkspaceFileChunk | WorkspaceFileEof | WorkspaceFileError
    ) -> AckMessage:
        queue = self._workspace_file_streams.get(message.request_id)
        if queue is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        queue.put_nowait(message)
        return AckMessage(message_type=message.type, detail="ok")

    async def _send_json(self, connection: NodeConnectionState, payload: dict[str, object]) -> None:
        async with connection.send_lock:
            await connection.websocket.send_json(payload)

    def _connection_views(self) -> dict[str, ExecutorNodeConnectionView]:
        return {
            node_id: ExecutorNodeConnectionView(
                connected=True,
                executors=sorted(state.executors),
                executor_capabilities=[
                    state.executors[executor_type].model_copy(deep=True)
                    for executor_type in sorted(state.executors)
                ],
            )
            for node_id, state in self._connections_by_node.items()
        }

    async def _connection_for_node(self, node_id: str) -> NodeConnectionState | None:
        async with self._connections_lock:
            return self._connections_by_node.get(node_id)

    async def _node_id_for_websocket(self, websocket: Any) -> str | None:
        async with self._connections_lock:
            return self._node_id_for_websocket_locked(websocket)

    def _node_id_for_websocket_locked(self, websocket: Any) -> str | None:
        for node_id, state in self._connections_by_node.items():
            if state.websocket is websocket:
                return node_id
        return None

    async def _handle_node_disconnected(self, node_id: str, *, reason: str) -> None:
        await self._registry.note_seen(node_id)
        for run_id, state in list(self._run_states.items()):
            if state.node_id != node_id:
                continue
            queue = self._run_queues.get(run_id)
            if queue is None:
                continue
            await queue.put(
                NodeRunEnvelope(
                    event=ExecutorEvent(
                        run_id=run_id,
                        session_id=state.execution_session_id,
                        event_type=ExecutorEventType.WAITING_EXECUTOR,
                        message=f"Waiting for executor node '{node_id}' to reconnect.",
                        metadata={
                            "executor_node_id": node_id,
                            "availability_reason": reason,
                        },
                    )
                )
            )
            self._run_queues.pop(run_id, None)
            self._run_states.pop(run_id, None)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
