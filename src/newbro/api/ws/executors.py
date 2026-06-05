from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from newbro.protocol import (
    AckMessage,
    AudioInstructionTranscribedMessage,
    CodexThreadEventMessage,
    CodexThreadReadMessage,
    CodexThreadSubscribedMessage,
    CodexThreadTurnsListedMessage,
    CodexThreadsListedMessage,
    CodexThreadUnsubscribedMessage,
    CodexTurnEventMessage,
    NodeStatusMessage,
    InteractionStateMessage,
    RegisterNodeMessage,
    RunEventMessage,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
)
from newbro.runtime.executor_node_manager import ExecutorNodeAuthError

router = APIRouter()


@router.websocket("/executors/control")
async def executor_control(websocket: WebSocket):
    container = websocket.app.state.runtime_container
    await websocket.accept()
    registered = False
    try:
        payload = await websocket.receive_json()
        register = RegisterNodeMessage.model_validate(payload)
        ack = await container.executor_node_manager.register_connection(websocket, register)
        registered = True
        await websocket.send_json(ack.model_dump(mode="json"))
        await container.handle_executor_node_connected(register.node_id)

        while True:
            payload = await websocket.receive_json()
            ack = await _handle_control_message(container, websocket, payload)
            await websocket.send_json(ack.model_dump(mode="json"))
    except ValidationError:
        await websocket.close(code=4400)
    except ExecutorNodeAuthError:
        await websocket.close(code=4403)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if registered:
            await container.executor_node_manager.disconnect(websocket=websocket, reason="connection_closed")
            await container.handle_executor_node_disconnected()


async def _handle_control_message(container, websocket: WebSocket, payload: object) -> AckMessage:
    if not isinstance(payload, dict):
        return AckMessage(message_type="unknown", ok=False, detail="invalid_payload")
    message_type = payload.get("type")
    if message_type == "run_event":
        try:
            message = RunEventMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="run_event", ok=False, detail="invalid_payload")
        ack = await container.executor_node_manager.publish_run_event(websocket, message)
        if ack.ok:
            session = await container.find_session_by_run(message.run_id)
            if session is not None:
                await session.handle_executor_audio_transcript_event(message.run_id, dict(message.metadata))
        return ack
    if message_type == "interaction_state":
        try:
            InteractionStateMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="interaction_state", ok=False, detail="invalid_payload")
        return AckMessage(message_type="interaction_state", detail="ignored")
    if message_type == "node_status":
        try:
            NodeStatusMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="node_status", ok=False, detail="invalid_payload")
        return AckMessage(message_type="node_status", detail="ok")
    if message_type == "codex_threads_listed":
        try:
            message = CodexThreadsListedMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="codex_threads_listed", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_codex_threads_listed(message)
    if message_type == "codex_thread_read":
        try:
            message = CodexThreadReadMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="codex_thread_read", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_codex_thread_read(message)
    if message_type == "codex_thread_turns_listed":
        try:
            message = CodexThreadTurnsListedMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="codex_thread_turns_listed", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_codex_thread_turns_listed(message)
    if message_type == "codex_thread_subscribed":
        try:
            message = CodexThreadSubscribedMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="codex_thread_subscribed", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_codex_thread_subscribed(message)
    if message_type == "codex_thread_unsubscribed":
        try:
            message = CodexThreadUnsubscribedMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="codex_thread_unsubscribed", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_codex_thread_unsubscribed(message)
    if message_type == "codex_thread_event":
        try:
            message = CodexThreadEventMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="codex_thread_event", ok=False, detail="invalid_payload")
        ack = await container.executor_node_manager.publish_codex_thread_event(websocket, message)
        if ack.ok:
            try:
                session = container.get_session(message.session_id)
            except KeyError:
                return AckMessage(message_type=message.type, ok=False, detail="unknown_session")
            await session.handle_codex_thread_event(message)
        return ack
    if message_type == "codex_turn_event":
        try:
            message = CodexTurnEventMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="codex_turn_event", ok=False, detail="invalid_payload")
        ack = await container.executor_node_manager.publish_codex_turn_event(websocket, message)
        if ack.ok:
            session = await container.find_session_by_outbound_turn_request(message.request_id)
            if session is None:
                return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
            await session.handle_codex_turn_event(message)
        return ack
    if message_type == "audio_instruction_transcribed":
        try:
            message = AudioInstructionTranscribedMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="audio_instruction_transcribed", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_audio_instruction_transcribed(message)
    if message_type == "workspace_file_chunk":
        try:
            message = WorkspaceFileChunk.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="workspace_file_chunk", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_workspace_file_chunk(message)
    if message_type == "workspace_file_eof":
        try:
            message = WorkspaceFileEof.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="workspace_file_eof", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_workspace_file_eof(message)
    if message_type == "workspace_file_error":
        try:
            message = WorkspaceFileError.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="workspace_file_error", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_workspace_file_error(message)
    return AckMessage(message_type=str(message_type or "unknown"), ok=False, detail="unknown_message_type")
