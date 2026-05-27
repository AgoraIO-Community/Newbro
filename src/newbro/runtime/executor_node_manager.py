from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from newbro.executors.core import ExecutorEvent, ExecutorEventType
from newbro.protocol import (
    AckMessage,
    CancelRunCommand,
    DispatchAudioInstructionCommand,
    DispatchRunCommand,
    DispatchTextInstructionCommand,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    ExecutorNodeExecutor,
    ExecutorNodeRecord,
    InteractionRequest,
    RegisterNodeMessage,
    RunEventMessage,
    SupplyInteractionResponseCommand,
)
from newbro.executors.node.registry import (
    ExecutorNodeConnectionView,
    ExecutorNodeRegistry,
)


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


class ExecutorNodeAuthError(RuntimeError):
    pass


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

    async def supply_interaction_response(
        self,
        request: InteractionRequest,
        *,
        action: str,
        answer_text: str | None,
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
        target_node_id = state.node_id if state is not None else node_id
        if target_node_id is None:
            return False
        connection = await self._connection_for_node(target_node_id)
        if connection is None:
            return False
        command = SupplyInteractionResponseCommand(
            interaction_request_id=request.request_id,
            execution_session_id=request.execution_session_id,
            run_id=request.run_id,
            action=action,
            answer_text=answer_text,
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
