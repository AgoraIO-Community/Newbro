from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from newbro.api.models import AgoraVoiceEvent, MessageRequest, MessageResponse, ToolInvocationSummary
from newbro.api.public_auth import require_session_owner_or_internal
from newbro.protocol import RuntimeDecision

router = APIRouter()


@router.post("/sessions/{session_id}/agora-events", response_model=RuntimeDecision)
async def submit_agora_event(
    session_id: str,
    event: AgoraVoiceEvent,
    http_request: Request,
) -> RuntimeDecision:
    await require_session_owner_or_internal(http_request, session_id)
    if event.session_id != session_id:
        raise HTTPException(status_code=400, detail="Agora voice event session_id does not match path.")
    container = http_request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        return await session.handle_agora_event(event)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse | RuntimeDecision)
async def submit_message(
    session_id: str,
    request: MessageRequest,
    http_request: Request,
) -> MessageResponse:
    await require_session_owner_or_internal(http_request, session_id)
    container = http_request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if request.type != "chat":
        try:
            decision = await session.handle_runtime_message(
                text=request.text,
                message_type=request.type,
                language=request.language,
                timestamp_ms=request.timestamp_ms,
                assigned_bro_id=request.assigned_bro_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return decision

    request_id = f"http-msg-{uuid4().hex[:8]}"
    _, completion = await session.submit_message(
        request_id,
        request.text,
        source=request.source,
        target_persona_id=request.target_persona_id,
        start_processing=False,
    )
    session.observability.api.message_accepted(
        conversation_id=session.session_id,
        request_id=request_id,
        transport="http",
    )
    await session.publish_snapshot()
    session.start_message_processing()
    result = await completion
    return MessageResponse(
        message_id=result.message_id,
        reply_text=result.reply_text,
        conversational_act=result.conversational_act,
        affected_task_ids=result.affected_task_ids,
        tool_invocations=[
            ToolInvocationSummary(tool_name=item.tool_name, args=item.args)
            for item in result.tool_invocations
        ],
    )
