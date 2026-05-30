from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from newbro.api.models import ResolveInteractionRequest, ResolveInteractionRequestResponse
from newbro.api.public_auth import require_session_owner
from newbro.observability.context import bind_diagnostic_context

router = APIRouter()
LOGGER = logging.getLogger(__name__)


@router.post(
    "/sessions/{session_id}/interaction-requests/{request_id}/resolve",
    response_model=ResolveInteractionRequestResponse,
)
async def resolve_interaction_request(
    session_id: str,
    request_id: str,
    request: ResolveInteractionRequest,
    http_request: Request,
) -> ResolveInteractionRequestResponse:
    await require_session_owner(http_request, session_id)
    container = http_request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    with bind_diagnostic_context(
        conversation_id=session.session_id,
        request_id=f"http-ireq-{request_id}",
    ):
        try:
            affected_task_ids = await session.resolve_interaction_request(
                request_id,
                action=request.action,
                answer_text=request.answer_text,
                option_id=request.option_id,
                answers=request.answers,
                reason=request.reason,
                client_request_id=request.client_request_id,
                user_visible_text=request.user_visible_text,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            session.schedule_execution()
            await session.publish_snapshot()
        except Exception:
            LOGGER.warning(
                "Resolved interaction request %s in session %s, but follow-up scheduling failed.",
                request_id,
                session_id,
                exc_info=True,
            )
    return ResolveInteractionRequestResponse(
        request_id=request_id,
        affected_task_ids=affected_task_ids,
    )
