from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from newbro.api.public_auth import require_public_user, require_session_owner
from newbro.protocol import AgentEvent, AgentEventDelivery, AgentEventImportance, DraftSession, RuntimeDecision
from newbro.runtime.drafts import (
    DraftRewriteInvalidOutput,
    DraftRewriteUnavailable,
    DraftRewriteUpstreamError,
)

router = APIRouter()


class AsrTurnRequest(BaseModel):
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = None
    started_at: str | None = None
    ended_at: str | None = None
    assigned_bro_id: str | None = None


class SendDraftRequest(BaseModel):
    draft_session_id: str | None = None
    draft_revision_id: str | None = None


class SendDraftResponse(BaseModel):
    task_id: str
    draft_session_id: str
    draft_snapshot_id: str
    draft_revision_id: str | None = None


class ClearDraftRequest(BaseModel):
    draft_session_id: str | None = None


class ClearDraftResponse(BaseModel):
    status: str = "cleared"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    latest_summary: str = ""
    artifacts: list[dict[str, object]] = Field(default_factory=list)
    runtime_decision: RuntimeDecision


class StopTaskResponse(BaseModel):
    task_id: str
    status: str
    spoken_response: str
    runtime_decision: RuntimeDecision


class AgentEventRequest(BaseModel):
    agent_id: str = "codex"
    type: str
    message: str
    importance: AgentEventImportance = AgentEventImportance.LOW
    delivery: AgentEventDelivery = AgentEventDelivery.SILENT_UI
    artifact_id: str | None = None


@router.get("/sessions/{session_id}/draft", response_model=DraftSession | None)
async def get_draft(session_id: str, http_request: Request) -> DraftSession | None:
    session = await _get_session(http_request, session_id)
    return session.draft_manager.active_session


@router.post("/sessions/{session_id}/draft/asr-turns", response_model=DraftSession)
async def submit_asr_turn(
    session_id: str,
    request: AsrTurnRequest,
    http_request: Request,
) -> DraftSession:
    session = await _get_session(http_request, session_id)
    try:
        draft_session = await session.append_asr_turn_to_draft(
            raw_text=request.raw_text,
            normalized_text=request.normalized_text,
            confidence=request.confidence,
            started_at=request.started_at,
            ended_at=request.ended_at,
            assigned_bro_id=request.assigned_bro_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DraftRewriteUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DraftRewriteUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DraftRewriteInvalidOutput as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.publish_snapshot()
    return draft_session


@router.post("/sessions/{session_id}/draft/send", response_model=SendDraftResponse)
async def send_draft(
    session_id: str,
    request: SendDraftRequest,
    http_request: Request,
) -> SendDraftResponse:
    session = await _get_session(http_request, session_id)
    try:
        active = session.draft_manager.active_session
        if request.draft_session_id is not None and active is not None and active.id != request.draft_session_id:
            raise ValueError("Draft session does not match the active draft.")
        decision = await session.confirm_active_dispatch(
            plan_id=active.current_dispatch_plan.plan_id
            if active is not None and active.current_dispatch_plan is not None
            else None,
            draft_revision_id=request.draft_revision_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if decision.task_id is None:
        raise HTTPException(status_code=409, detail=decision.response_text or "Draft cannot be sent yet.")
    task = await session.blackboard.get_task(decision.task_id)
    if task is None:
        raise HTTPException(status_code=409, detail="Confirmed dispatch did not create a task.")
    await session.publish_snapshot()
    return SendDraftResponse(
        task_id=task.task_id,
        draft_session_id=str(task.metadata["draft_session_id"]),
        draft_snapshot_id=str(task.metadata["draft_snapshot_id"]),
        draft_revision_id=task.metadata.get("draft_revision_id"),
    )


@router.post("/dispatch-plans/{plan_id}/confirm", response_model=RuntimeDecision)
async def confirm_dispatch_plan(plan_id: str, http_request: Request) -> RuntimeDecision:
    user = await require_public_user(http_request)
    container = http_request.app.state.runtime_container
    session = container.find_session_by_dispatch_plan(plan_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dispatch plan not found.")
    store = http_request.app.state.public_auth_store
    if not await store.user_owns_session(user_id=user.user_id, session_id=session.session_id):
        raise HTTPException(status_code=404, detail="Dispatch plan not found.")
    try:
        return await session.confirm_active_dispatch(plan_id=plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, http_request: Request) -> TaskStatusResponse:
    user = await require_public_user(http_request)
    container = http_request.app.state.runtime_container
    session = await container.find_session_by_task(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    store = http_request.app.state.public_auth_store
    if not await store.user_owns_session(user_id=user.user_id, session_id=session.session_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    task = await session.blackboard.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    decision = await session.runtime_status_decision(task_id=task_id)
    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status.value,
        latest_summary=decision.response_text,
        runtime_decision=decision,
    )


@router.post("/tasks/{task_id}/stop", response_model=StopTaskResponse)
async def stop_task(task_id: str, http_request: Request) -> StopTaskResponse:
    user = await require_public_user(http_request)
    container = http_request.app.state.runtime_container
    session = await container.find_session_by_task(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    store = http_request.app.state.public_auth_store
    if not await store.user_owns_session(user_id=user.user_id, session_id=session.session_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    decision = await session.stop_active_task_decision(task_id=task_id)
    task = await session.blackboard.get_task(task_id)
    return StopTaskResponse(
        task_id=task_id,
        status=task.status.value if task is not None else "stopped",
        spoken_response=decision.response_text,
        runtime_decision=decision,
    )


@router.post("/tasks/{task_id}/events", response_model=RuntimeDecision)
async def ingest_agent_event(
    task_id: str,
    request: AgentEventRequest,
    http_request: Request,
) -> RuntimeDecision:
    user = await require_public_user(http_request)
    container = http_request.app.state.runtime_container
    session = await container.find_session_by_task(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    store = http_request.app.state.public_auth_store
    if not await store.user_owns_session(user_id=user.user_id, session_id=session.session_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    event = AgentEvent(
        event_id=f"agent-event-{uuid4().hex[:8]}",
        task_id=task_id,
        agent_id=request.agent_id,
        type=request.type,
        message=request.message,
        importance=request.importance,
        delivery=request.delivery,
        artifact_id=request.artifact_id,
        created_at=datetime.now(UTC).isoformat(),
    )
    return await session.ingest_agent_event(event)


@router.post("/sessions/{session_id}/draft/clear", response_model=ClearDraftResponse)
async def clear_draft(
    session_id: str,
    request: ClearDraftRequest,
    http_request: Request,
) -> ClearDraftResponse:
    session = await _get_session(http_request, session_id)
    active = session.draft_manager.active_session
    if request.draft_session_id is not None and active is not None and active.id != request.draft_session_id:
        raise HTTPException(status_code=409, detail="Draft session does not match the active draft.")
    session.clear_draft()
    await session.publish_snapshot()
    return ClearDraftResponse()


async def _get_session(http_request: Request, session_id: str):
    await require_session_owner(http_request, session_id)
    container = http_request.app.state.runtime_container
    try:
        return container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
