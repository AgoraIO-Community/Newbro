from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from newbro.api.models import CommandRequest, CommandResponse
from newbro.api.public_auth import require_session_owner
from newbro.communication.resolver import TaskResolver, describe_candidates
from newbro.observability.context import bind_diagnostic_context
from newbro.protocol import TaskCommand

router = APIRouter()


@router.post("/sessions/{session_id}/commands", response_model=CommandResponse)
async def submit_command(
    session_id: str,
    request: CommandRequest,
    http_request: Request,
) -> CommandResponse:
    await require_session_owner(http_request, session_id)
    container = http_request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    tasks = await session.blackboard.list_tasks()
    resolution = TaskResolver().resolve(tasks, task_id=request.task_id, reference=request.reference)
    if resolution.status == "ambiguous":
        raise HTTPException(
            status_code=409,
            detail=(
                "Task reference is ambiguous. Relevant tasks: "
                f"{describe_candidates(resolution.candidates)}."
            ),
        )
    task = resolution.task
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    validation_error = await session.validate_task_command(task, request.command_type)
    if validation_error is not None:
        raise HTTPException(status_code=409, detail=validation_error)

    command = TaskCommand(
        command_id=f"cmd-{uuid4().hex[:8]}",
        task_id=task.task_id,
        command_type=request.command_type,
        payload=request.payload,
        created_by="api",
        reason=request.reason,
    )
    request_id = f"http-cmd-{uuid4().hex[:8]}"
    session.observability.api.command_accepted(
        conversation_id=session.session_id,
        request_id=request_id,
        task_id=task.task_id,
        command_type=request.command_type.value,
        transport="http",
    )
    with bind_diagnostic_context(
        conversation_id=session.session_id,
        request_id=request_id,
        task_id=task.task_id,
    ):
        await session.apply_command(command)
    session.schedule_execution()
    await session.publish_snapshot()
    return CommandResponse(command_id=command.command_id, affected_task_ids=[task.task_id])
