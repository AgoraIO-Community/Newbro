from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request

from newbro.api.public_auth import require_session_owner

router = APIRouter()
LOGGER = logging.getLogger(__name__)


class ExecutorTextInstructionRequest(BaseModel):
    target_persona_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=20_000)
    target_thread_id: str | None = Field(default=None, min_length=1)
    create_new_thread: bool = False
    client_request_id: str | None = Field(default=None, min_length=1, max_length=120)
    plan_mode: bool = False


class ExecutorTextInstructionResponse(BaseModel):
    instruction_id: str
    target_persona_id: str
    target_thread_id: str | None = None
    status: str


@router.post(
    "/sessions/{session_id}/executor-text-instructions",
    response_model=ExecutorTextInstructionResponse,
)
async def submit_executor_text_instruction(
    session_id: str,
    body: ExecutorTextInstructionRequest,
    request: Request,
) -> ExecutorTextInstructionResponse:
    started_at = time.perf_counter()
    await require_session_owner(request, session_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text instruction is empty.")
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session.observability.logger.emit_event(
        level="INFO",
        event_name="api.executor_text.received",
        component="api.executor_text",
        summary="Executor text instruction received",
        conversation_id=session_id,
        request_id=body.client_request_id,
        details={
            "client_request_id": body.client_request_id,
            "target_persona_id": body.target_persona_id,
            "target_thread_id": body.target_thread_id,
            "create_new_thread": body.create_new_thread,
            "text_length": len(text),
            "plan_mode": body.plan_mode,
        },
    )
    LOGGER.info(
        "executor_text_metric step=api.received session_id=%s client_request_id=%s target_persona_id=%s target_thread_id=%s create_new_thread=%s text_length=%s",
        session_id,
        body.client_request_id,
        body.target_persona_id,
        body.target_thread_id,
        body.create_new_thread,
        len(text),
    )
    try:
        instruction = await session.submit_executor_text_instruction(
            target_persona_id=body.target_persona_id,
            text=text,
            target_thread_id=body.target_thread_id,
            create_new_thread=body.create_new_thread,
            client_request_id=body.client_request_id,
            plan_mode=body.plan_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    session.observability.logger.emit_event(
        level="INFO",
        event_name="api.executor_text.accepted",
        component="api.executor_text",
        summary="Executor text instruction accepted",
        conversation_id=session_id,
        request_id=body.client_request_id,
        details={
            "client_request_id": body.client_request_id,
            "instruction_id": instruction.instruction_id,
            "target_persona_id": instruction.target_persona_id,
            "target_thread_id": instruction.target_thread_id,
            "elapsed_ms": elapsed_ms,
        },
    )
    LOGGER.info(
        "executor_text_metric step=api.accepted session_id=%s client_request_id=%s instruction_id=%s target_thread_id=%s elapsed_ms=%s",
        session_id,
        body.client_request_id,
        instruction.instruction_id,
        instruction.target_thread_id,
        elapsed_ms,
    )
    return ExecutorTextInstructionResponse(
        instruction_id=instruction.instruction_id,
        target_persona_id=instruction.target_persona_id,
        target_thread_id=instruction.target_thread_id,
        status="accepted",
    )
