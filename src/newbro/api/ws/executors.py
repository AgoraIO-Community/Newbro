from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from newbro.protocol import (
    AckMessage,
    AudioInstructionTranscribedMessage,
    CodexThreadReadMessage,
    CodexThreadsListedMessage,
    NodeStatusMessage,
    InteractionStateMessage,
    RegisterNodeMessage,
    RunEventMessage,
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
        await container.handle_executor_node_connected()

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
    if message_type == "audio_instruction_transcribed":
        try:
            message = AudioInstructionTranscribedMessage.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="audio_instruction_transcribed", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_audio_instruction_transcribed(message)
    return AckMessage(message_type=str(message_type or "unknown"), ok=False, detail="unknown_message_type")
