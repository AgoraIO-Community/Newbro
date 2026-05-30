import asyncio
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from newbro.api.models import (
    ClearDraftSocketAction,
    ResolveInteractionRequestSocketAction,
    SendDraftSocketAction,
    SendCommandSocketAction,
    SendMessageSocketAction,
    SubmitAsrTurnSocketAction,
)
from newbro.api.public_auth import user_for_websocket
from newbro.api.snapshots import scope_stream_event_for_user
from newbro.communication.resolver import TaskResolver, describe_candidates
from newbro.observability.context import bind_diagnostic_context
from newbro.protocol import TaskCommand
from newbro.runtime.models import (
    DraftOutputCompletedStreamEvent,
    DraftOutputDeltaStreamEvent,
    DraftOutputFailedStreamEvent,
    DraftOutputStartedStreamEvent,
)
from newbro.runtime.drafts import (
    DraftRewriteInvalidOutput,
    DraftRewriteUnavailable,
    DraftRewriteUpstreamError,
)

router = APIRouter()


@router.websocket("/sessions/{session_id}/stream")
async def session_stream(websocket: WebSocket, session_id: str):
    container = websocket.app.state.runtime_container
    store = websocket.app.state.public_auth_store
    expected = getattr(container.settings, "connector_internal_token", None)
    supplied = websocket.headers.get("X-Newbro-Connector-Token")
    internal = expected and supplied == expected
    user = None
    if not internal:
        user = await user_for_websocket(websocket)
        if user is None:
            await websocket.close(code=4401)
            return
        if not await store.user_owns_session(user_id=user.user_id, session_id=session_id):
            await websocket.close(code=4404)
            return
    try:
        session = container.get_session(session_id)
    except KeyError:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = session.subscribe()
    initial_event = await session.initial_snapshot_event()
    if user is not None:
        initial_event = await scope_stream_event_for_user(store, user, initial_event)
    await websocket.send_json(initial_event.model_dump(mode="json"))
    sender = asyncio.create_task(_send_events(websocket, queue, store=store, user=user))
    try:
        while True:
            payload = await websocket.receive_json()
            await _handle_client_action(session, queue, payload)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        sender.cancel()
        try:
            await sender
        except (asyncio.CancelledError, RuntimeError, WebSocketDisconnect):
            pass
        session.unsubscribe(queue)


async def _send_events(websocket: WebSocket, queue: asyncio.Queue, *, store, user) -> None:
    while True:
        event = await queue.get()
        if user is not None:
            event = await scope_stream_event_for_user(store, user, event)
        await websocket.send_json(event.model_dump(mode="json"))


async def _handle_client_action(session, queue: asyncio.Queue, payload: object) -> None:
    if not isinstance(payload, dict):
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id="",
            action_type="unknown",
            error_code="invalid_payload",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                "",
                action_type="unknown",
                error_code="invalid_payload",
                message="Socket action payload must be an object.",
            ),
        )
        return

    action_type = payload.get("type")
    request_id = payload.get("request_id")
    request_id_value = request_id if isinstance(request_id, str) else ""
    action_type_value = action_type if isinstance(action_type, str) else "unknown"

    if action_type_value == "send_message":
        await _handle_send_message(session, queue, payload)
        return
    if action_type_value == "send_command":
        await _handle_send_command(session, queue, payload)
        return
    if action_type_value == "resolve_interaction_request":
        await _handle_resolve_interaction_request(session, queue, payload)
        return
    if action_type_value == "submit_asr_turn":
        await _handle_submit_asr_turn(session, queue, payload)
        return
    if action_type_value == "send_draft":
        await _handle_send_draft(session, queue, payload)
        return
    if action_type_value == "clear_draft":
        await _handle_clear_draft(session, queue, payload)
        return

    await session.publish_private_event(
        queue,
        session.action_rejected_event(
            request_id_value,
            action_type=action_type_value,
            error_code="unknown_action_type",
            message="Unknown websocket action type.",
        ),
    )
    session.observability.api.ws_action_rejected(
        conversation_id=session.session_id,
        request_id=request_id_value,
        action_type=action_type_value,
        error_code="unknown_action_type",
    )


async def _handle_send_message(session, queue: asyncio.Queue, payload: dict[str, object]) -> None:
    try:
        action = SendMessageSocketAction.model_validate(payload)
    except ValidationError as exc:
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id=_request_id_from_payload(payload),
            action_type="send_message",
            error_code="invalid_payload",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                _request_id_from_payload(payload),
                action_type="send_message",
                error_code="invalid_payload",
                message=str(exc),
            ),
        )
        return

    text = action.text.strip()
    if not text:
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id=action.request_id,
            action_type=action.type,
            error_code="invalid_message_text",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="invalid_message_text",
                message="Message text must not be empty.",
            ),
        )
        return

    await session.submit_message(
        action.request_id,
        text,
        source=action.source,
        target_persona_id=action.target_persona_id,
        start_processing=False,
    )
    session.observability.api.message_accepted(
        conversation_id=session.session_id,
        request_id=action.request_id,
        transport="websocket",
    )
    await session.publish_private_event(
        queue,
        session.action_accepted_event(
            action.request_id,
            action_type=action.type,
        ),
    )
    session.observability.api.ws_action_accepted(
        conversation_id=session.session_id,
        request_id=action.request_id,
        action_type=action.type,
    )
    await session.publish_snapshot()
    session.start_message_processing()


async def _handle_send_command(session, queue: asyncio.Queue, payload: dict[str, object]) -> None:
    try:
        action = SendCommandSocketAction.model_validate(payload)
    except ValidationError as exc:
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id=_request_id_from_payload(payload),
            action_type="send_command",
            error_code="invalid_payload",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                _request_id_from_payload(payload),
                action_type="send_command",
                error_code="invalid_payload",
                message=str(exc),
            ),
        )
        return

    tasks = await session.blackboard.list_tasks()
    resolution = TaskResolver().resolve(tasks, task_id=action.task_id, reference=action.reference)
    if resolution.status == "ambiguous":
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id=action.request_id,
            action_type=action.type,
            error_code="ambiguous_reference",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="ambiguous_reference",
                message=(
                    "Task reference is ambiguous. Relevant tasks: "
                    f"{describe_candidates(resolution.candidates)}."
                ),
            ),
        )
        return
    task = resolution.task
    if task is None:
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id=action.request_id,
            action_type=action.type,
            error_code="task_not_found",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="task_not_found",
                message="Task not found.",
            ),
        )
        return
    validation_error = await session.validate_task_command(task, action.command_type)
    if validation_error is not None:
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id=action.request_id,
            action_type=action.type,
            error_code="unsupported_command",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="unsupported_command",
                message=validation_error,
            ),
        )
        return

    command = TaskCommand(
        command_id=f"cmd-{uuid4().hex[:8]}",
        task_id=task.task_id,
        command_type=action.command_type,
        payload=action.payload,
        created_by="api",
        reason=action.reason,
    )
    await session.publish_private_event(
        queue,
        session.action_accepted_event(
            action.request_id,
            action_type=action.type,
        ),
    )
    session.observability.api.ws_action_accepted(
        conversation_id=session.session_id,
        request_id=action.request_id,
        action_type=action.type,
    )
    session.observability.api.command_accepted(
        conversation_id=session.session_id,
        request_id=action.request_id,
        task_id=task.task_id,
        command_type=action.command_type.value,
        transport="websocket",
    )
    with bind_diagnostic_context(
        conversation_id=session.session_id,
        request_id=action.request_id,
        task_id=task.task_id,
    ):
        await session.apply_command(command)
    session.schedule_execution()
    await session.publish_snapshot()


async def _handle_resolve_interaction_request(
    session,
    queue: asyncio.Queue,
    payload: dict[str, object],
) -> None:
    try:
        action = ResolveInteractionRequestSocketAction.model_validate(payload)
    except ValidationError as exc:
        session.observability.api.ws_action_rejected(
            conversation_id=session.session_id,
            request_id=_request_id_from_payload(payload),
            action_type="resolve_interaction_request",
            error_code="invalid_payload",
        )
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                _request_id_from_payload(payload),
                action_type="resolve_interaction_request",
                error_code="invalid_payload",
                message=str(exc),
            ),
        )
        return

    try:
        affected_task_ids = await session.resolve_interaction_request(
            action.interaction_request_id,
            action=action.action,
            answer_text=action.answer_text,
            option_id=action.option_id,
            reason=action.reason,
            client_request_id=action.client_request_id,
            user_visible_text=action.user_visible_text,
        )
    except KeyError as exc:
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="interaction_request_not_found",
                message=str(exc),
            ),
        )
        return
    except ValueError as exc:
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="invalid_interaction_resolution",
                message=str(exc),
            ),
        )
        return

    await session.publish_private_event(
        queue,
        session.action_accepted_event(
            action.request_id,
            action_type=action.type,
        ),
    )
    session.observability.api.ws_action_accepted(
        conversation_id=session.session_id,
        request_id=action.request_id,
        action_type=action.type,
    )
    session.schedule_execution()
    await session.publish_snapshot()


async def _handle_submit_asr_turn(session, queue: asyncio.Queue, payload: dict[str, object]) -> None:
    try:
        action = SubmitAsrTurnSocketAction.model_validate(payload)
    except ValidationError as exc:
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                _request_id_from_payload(payload),
                action_type="submit_asr_turn",
                error_code="invalid_payload",
                message=str(exc),
            ),
        )
        return
    try:
        await session.publish_private_event(
            queue,
            DraftOutputStartedStreamEvent(
                sequence=session._next_event_sequence(),
                request_id=action.request_id,
            ),
        )

        async def on_text_delta(delta: str) -> None:
            await session.publish_private_event(
                queue,
                DraftOutputDeltaStreamEvent(
                    sequence=session._next_event_sequence(),
                    request_id=action.request_id,
                    delta=delta,
                ),
            )

        draft_session = await session.append_asr_turn_to_draft(
            raw_text=action.raw_text,
            normalized_text=action.normalized_text,
            confidence=action.confidence,
            started_at=action.started_at,
            ended_at=action.ended_at,
            assigned_bro_id=action.assigned_bro_id,
            on_text_delta=on_text_delta,
        )
    except ValueError as exc:
        await _publish_draft_output_failed(session, queue, action.request_id, str(exc))
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="invalid_asr_turn",
                message=str(exc),
            ),
        )
        return
    except DraftRewriteUnavailable as exc:
        await _publish_draft_output_failed(session, queue, action.request_id, str(exc))
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="draft_rewriter_unavailable",
                message=str(exc),
            ),
        )
        return
    except DraftRewriteUpstreamError as exc:
        await _publish_draft_output_failed(session, queue, action.request_id, str(exc))
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="draft_rewriter_upstream_error",
                message=str(exc),
            ),
        )
        return
    except DraftRewriteInvalidOutput as exc:
        await _publish_draft_output_failed(session, queue, action.request_id, str(exc))
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="draft_rewriter_invalid_output",
                message=str(exc),
            ),
        )
        return
    draft_text = draft_session.current_draft.text if draft_session.current_draft else ""
    await session.publish_private_event(
        queue,
        DraftOutputCompletedStreamEvent(
            sequence=session._next_event_sequence(),
            request_id=action.request_id,
            draft_session_id=draft_session.id,
            draft_text=draft_text,
        ),
    )
    await session.publish_private_event(
        queue,
        session.action_accepted_event(action.request_id, action_type=action.type),
    )
    await session.publish_snapshot()


async def _publish_draft_output_failed(
    session,
    queue: asyncio.Queue,
    request_id: str,
    message: str,
) -> None:
    await session.publish_private_event(
        queue,
        DraftOutputFailedStreamEvent(
            sequence=session._next_event_sequence(),
            request_id=request_id,
            message=message,
        ),
    )


async def _handle_send_draft(session, queue: asyncio.Queue, payload: dict[str, object]) -> None:
    try:
        action = SendDraftSocketAction.model_validate(payload)
    except ValidationError as exc:
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                _request_id_from_payload(payload),
                action_type="send_draft",
                error_code="invalid_payload",
                message=str(exc),
            ),
        )
        return
    try:
        active = session.draft_manager.active_session
        if action.draft_session_id is not None and active is not None and active.id != action.draft_session_id:
            raise ValueError("Draft session does not match the active draft.")
        decision = await session.confirm_active_dispatch(
            plan_id=active.current_dispatch_plan.plan_id
            if active is not None and active.current_dispatch_plan is not None
            else None,
            draft_revision_id=action.draft_revision_id,
        )
        if decision.task_id is None:
            raise ValueError(decision.response_text or "Draft cannot be sent yet.")
    except ValueError as exc:
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="draft_not_ready",
                message=str(exc),
            ),
        )
        return
    await session.publish_private_event(
        queue,
        session.action_accepted_event(action.request_id, action_type=action.type),
    )
    await session.publish_snapshot()
    session.schedule_execution()


async def _handle_clear_draft(session, queue: asyncio.Queue, payload: dict[str, object]) -> None:
    try:
        action = ClearDraftSocketAction.model_validate(payload)
    except ValidationError as exc:
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                _request_id_from_payload(payload),
                action_type="clear_draft",
                error_code="invalid_payload",
                message=str(exc),
            ),
        )
        return
    active = session.draft_manager.active_session
    if action.draft_session_id is not None and active is not None and active.id != action.draft_session_id:
        await session.publish_private_event(
            queue,
            session.action_rejected_event(
                action.request_id,
                action_type=action.type,
                error_code="draft_session_mismatch",
                message="Draft session does not match the active draft.",
            ),
        )
        return
    session.clear_draft()
    await session.publish_private_event(
        queue,
        session.action_accepted_event(action.request_id, action_type=action.type),
    )
    await session.publish_snapshot()


def _request_id_from_payload(payload: dict[str, object]) -> str:
    request_id = payload.get("request_id")
    return request_id if isinstance(request_id, str) else ""
