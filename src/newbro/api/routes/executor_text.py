from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request

from newbro.api.public_auth import require_session_owner

router = APIRouter()


class ExecutorTextInstructionRequest(BaseModel):
    target_persona_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=20_000)
    target_thread_id: str | None = Field(default=None, min_length=1)
    create_new_thread: bool = False


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
    await require_session_owner(request, session_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text instruction is empty.")
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        instruction = await session.submit_executor_text_instruction(
            target_persona_id=body.target_persona_id,
            text=text,
            target_thread_id=body.target_thread_id,
            create_new_thread=body.create_new_thread,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ExecutorTextInstructionResponse(
        instruction_id=instruction.instruction_id,
        target_persona_id=instruction.target_persona_id,
        target_thread_id=instruction.target_thread_id,
        status="accepted",
    )
