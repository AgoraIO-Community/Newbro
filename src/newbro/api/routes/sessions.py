from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from newbro.api.models import DiagnosticTimelineResponse, SessionResponse
from newbro.api.public_auth import require_public_user, require_session_owner, require_session_owner_or_internal
from newbro.api.snapshots import scope_session_snapshot_for_user
from newbro.observability.schema import LEVEL_PRIORITY

router = APIRouter()


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: Request,
) -> SessionResponse:
    user = await require_public_user(request)
    container = request.app.state.runtime_container
    store = request.app.state.public_auth_store
    session = container.create_session()
    await store.claim_session(user_id=user.user_id, session_id=session.session_id)
    personas = await store.list_personas(user_id=user.user_id)
    await container.sync_user_personas(session_id=session.session_id, personas=personas)
    session.observability.api.session_created(conversation_id=session.session_id)
    return SessionResponse(session_id=session.session_id)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
):
    user = await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snapshot = await session.snapshot()
    if user is None:
        return snapshot
    return await scope_session_snapshot_for_user(
        request.app.state.public_auth_store,
        user,
        snapshot,
    )


@router.get("/sessions/{session_id}/conversation")
async def get_session_conversation(
    session_id: str,
    request: Request,
):
    await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await session.conversation_snapshot()


@router.get("/sessions/{session_id}/tasks")
async def list_tasks(
    session_id: str,
    request: Request,
):
    await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await session.blackboard.list_tasks()


@router.get(
    "/sessions/{session_id}/diagnostics/timeline",
    response_model=DiagnosticTimelineResponse,
)
async def get_session_diagnostic_timeline(
    session_id: str,
    request: Request,
    after_sequence: int | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    execution_session_id: str | None = None,
    notification_id: str | None = None,
    request_id: str | None = None,
    event_prefix: str | None = None,
    min_level: str | None = None,
    limit: int = 200,
) -> DiagnosticTimelineResponse:
    await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if min_level is not None:
        min_level = min_level.upper()
        if min_level not in LEVEL_PRIORITY:
            raise HTTPException(status_code=400, detail="Invalid min_level.")
    return DiagnosticTimelineResponse(
        events=session.diagnostic_timeline(
            after_sequence=after_sequence,
            task_id=task_id,
            run_id=run_id,
            execution_session_id=execution_session_id,
            notification_id=notification_id,
            request_id=request_id,
            event_prefix=event_prefix,
            min_level=min_level,
            limit=limit,
        )
    )

class VoiceTargetRequest(BaseModel):
    target_persona_id: str


class OpenBroThreadRequest(BaseModel):
    target_persona_id: str


def _conflict_detail(exc: Exception, fallback: str) -> str:
    detail = str(exc).strip()
    return detail or fallback


@router.get("/sessions/{session_id}/bro-threads")
async def list_bro_thread_page(
    session_id: str,
    request: Request,
    target_persona_id: str,
    limit: int = 25,
    cursor: str | None = None,
):
    await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
        return await session.list_bro_thread_page(
            target_persona_id=target_persona_id,
            limit=limit,
            cursor=cursor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=_conflict_detail(exc, "Thread page could not be listed."),
        ) from exc


@router.get("/sessions/{session_id}/bro-threads/{thread_id}/timeline")
async def list_bro_timeline_page(
    session_id: str,
    thread_id: str,
    request: Request,
    target_persona_id: str,
    limit: int = 15,
    cursor: str | None = None,
):
    await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
        return await session.list_bro_timeline_page(
            target_persona_id=target_persona_id,
            thread_id=thread_id,
            limit=limit,
            cursor=cursor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=_conflict_detail(exc, "Timeline page could not be listed."),
        ) from exc


@router.post("/sessions/{session_id}/bro-threads/{thread_id}/open")
async def open_bro_thread(
    session_id: str,
    thread_id: str,
    body: OpenBroThreadRequest,
    request: Request,
):
    user = await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        snapshot = await session.open_bro_thread(
            target_persona_id=body.target_persona_id,
            thread_id=thread_id,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=409,
            detail=_conflict_detail(exc, "Timed out reading Codex thread history."),
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=_conflict_detail(exc, "Unable to open this thread.")) from exc
    if user is None:
        return snapshot
    return await scope_session_snapshot_for_user(
        request.app.state.public_auth_store,
        user,
        snapshot,
    )


@router.delete("/sessions/{session_id}/bro-threads/{thread_id}/open")
async def close_bro_thread(
    session_id: str,
    thread_id: str,
    body: OpenBroThreadRequest,
    request: Request,
):
    user = await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        snapshot = await session.close_bro_thread(
            target_persona_id=body.target_persona_id,
            thread_id=thread_id,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=409,
            detail=_conflict_detail(exc, "Timed out closing Codex thread history."),
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=_conflict_detail(exc, "Unable to close this thread.")) from exc
    if user is None:
        return snapshot
    return await scope_session_snapshot_for_user(
        request.app.state.public_auth_store,
        user,
        snapshot,
    )


@router.put("/sessions/{session_id}/voice-target")
async def set_voice_target(
    session_id: str,
    body: VoiceTargetRequest,
    request: Request,
):
    await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.set_voice_target(body.target_persona_id)
    return {"target_persona_id": body.target_persona_id}


@router.delete("/sessions/{session_id}/voice-target")
async def clear_voice_target(
    session_id: str,
    request: Request,
):
    await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.set_voice_target(None)
    return {"target_persona_id": None}
