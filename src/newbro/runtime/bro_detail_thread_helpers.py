from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from newbro.protocol import (
    AgentResumeHandle,
    BroThread,
    BroTimelineMessage,
    BroTimelinePlan,
    BroTimelineTask,
    BroTimelineTurn,
    CodexThreadListItem,
    CodexTurnEventMessage,
    ExecutionRun,
    ExecutionSession,
    InteractionRequest,
    OutboundTurnRequest,
    RunStatus,
    Task,
    TaskStatus,
    TaskSummary,
)

SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS = 2.0
BRO_THREAD_PREFIX = "bro-thread-"
IMPORTED_CODEX_THREAD_PREFIX = "codex-import-"
AUDIO_ACTIVE_RUN_STATUSES = {RunStatus.ASSIGNED, RunStatus.RUNNING, RunStatus.BLOCKED}


def _title_from_draft_text(text: str) -> str:
    title = " ".join(text.strip().split()).rstrip(".。")
    if len(title) > 72:
        title = title[:69].rstrip() + "..."
    return title or "Draft task"


def _new_bro_thread_id() -> str:
    return f"{BRO_THREAD_PREFIX}{uuid4().hex[:12]}"


def _imported_bro_thread_id(persona_id: str, codex_thread_id: str) -> str:
    digest = hashlib.sha256(f"{persona_id}:{codex_thread_id}".encode("utf-8")).hexdigest()
    return f"{IMPORTED_CODEX_THREAD_PREFIX}{digest[:16]}"


def _codex_thread_alias_key(persona_id: str, codex_thread_id: str) -> str:
    return f"{persona_id}:{codex_thread_id}"


def _public_thread_id(session: ExecutionSession) -> str:
    if isinstance(session.continuity_key, str) and session.continuity_key.startswith(BRO_THREAD_PREFIX):
        return session.continuity_key
    if isinstance(session.continuity_key, str) and session.continuity_key.startswith(IMPORTED_CODEX_THREAD_PREFIX):
        return session.continuity_key
    return session.execution_session_id


def _session_matches_thread_id(session: ExecutionSession, thread_id: str) -> bool:
    return thread_id in {
        session.execution_session_id,
        session.continuity_key or "",
        _public_thread_id(session),
    }


def _task_belongs_to_persona(task: Task | None, persona_id: str) -> bool:
    if task is None:
        return False
    return task.metadata.get("persona_id") == persona_id or task.metadata.get("assigned_bro_id") == persona_id


def _task_metadata_string(task: Task | None, key: str) -> str | None:
    if task is None:
        return None
    value = task.metadata.get(key)
    return value if isinstance(value, str) and value else None


def _selected_plan_option_label(request: InteractionRequest) -> str | None:
    selected_option_id = request.details.get("selected_option_id")
    if not isinstance(selected_option_id, str) or not selected_option_id:
        return None
    proposal = request.details.get("proposal")
    if not isinstance(proposal, dict):
        return None
    options = proposal.get("options")
    if not isinstance(options, list):
        return None
    for option in options:
        if not isinstance(option, dict) or option.get("id") != selected_option_id:
            continue
        label = option.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return None


def _task_thread_public_id(task: Task) -> str | None:
    return _task_metadata_string(task, "target_thread_id") or _task_metadata_string(task, "bro_thread_id")


def _task_updated_at(task: Task | None) -> str | None:
    return (
        _task_metadata_string(task, "updated_at")
        or _task_metadata_string(task, "completed_at")
        or _task_metadata_string(task, "created_at")
    )


def _resume_handle_string(handle: AgentResumeHandle | None, key: str) -> str | None:
    if handle is None:
        return None
    value = handle.opaque.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _thread_status(task: Task | None, run: ExecutionRun | None) -> str:
    status = run.status if run is not None else (task.status if task is not None else None)
    if status in {RunStatus.COMPLETED, TaskStatus.COMPLETED}:
        return "completed"
    if status in {RunStatus.FAILED, TaskStatus.FAILED}:
        return "failed"
    if status in {RunStatus.CANCELLED, TaskStatus.CANCELLED, TaskStatus.STOPPED}:
        return "cancelled"
    if status in {RunStatus.BLOCKED, TaskStatus.WAITING_USER_INPUT}:
        return "blocked"
    if status in {RunStatus.RUNNING, RunStatus.ASSIGNED, TaskStatus.RUNNING}:
        return "running"
    if status in {RunStatus.WAITING_EXECUTOR, TaskStatus.WAITING_EXECUTOR, TaskStatus.QUEUED, TaskStatus.CREATED}:
        return "queued"
    return "pending"


def _thread_progress(status: str) -> int:
    if status == "completed":
        return 100
    if status == "running":
        return 60
    if status == "blocked":
        return 45
    if status == "queued":
        return 20
    return 0


def _codex_thread_status(status: str | None) -> str:
    normalized = (status or "").lower()
    if normalized in {"running", "busy"}:
        return "running"
    if normalized in {"failed", "error", "systemerror"}:
        return "failed"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    return "completed"


def _codex_thread_status_from_outbound_request(
    status: str,
) -> Literal["pending", "queued", "running", "blocked", "completed", "failed", "cancelled"]:
    if status in {"accepted", "running"}:
        return "running"
    if status == "completed":
        return "completed"
    if status == "failed":
        return "failed"
    return "pending"


def _outbound_request_status_from_codex_event(
    message: CodexTurnEventMessage,
) -> Literal["accepted", "running", "completed", "failed"]:
    event_type = message.event_type.lower()
    if not message.ok or event_type in {"failed", "cancelled"}:
        return "failed"
    if event_type == "completed":
        return "completed"
    if event_type in {"progress", "plan", "blocked", "waiting_executor"}:
        return "running"
    return "accepted"


def _timeline_status_from_codex_event(
    message: CodexTurnEventMessage,
) -> Literal["pending", "running", "completed", "failed", "cancelled"]:
    event_type = message.event_type.lower()
    if not message.ok or event_type in {"failed", "cancelled"}:
        return "failed"
    if event_type == "completed":
        return "completed"
    if event_type in {"progress", "plan", "blocked", "waiting_executor"}:
        return "running"
    return "pending"


_NATIVE_REASONING_TEXT_LIMIT = 280
_NATIVE_REASONING_STORE_STEPS = 16
_NATIVE_REASONING_STORE_TURNS = 20
_NATIVE_REASONING_PROJECT_STEPS = 8
_NATIVE_REASONING_PROJECT_TURNS = 10


def _native_reasoning_key(
    executor_id: str,
    executor_thread_id: str | None,
    executor_turn_id: str | None,
) -> str | None:
    if not executor_thread_id or not executor_turn_id:
        return None
    return f"{executor_id}::{executor_thread_id}::{executor_turn_id}"


def _bro_timeline_turn_from_codex_turn_event(
    *,
    request: OutboundTurnRequest,
    message: CodexTurnEventMessage,
    timestamp: str,
) -> BroTimelineTurn:
    executor_thread_id = message.executor_thread_id or request.executor_thread_id
    executor_turn_id = message.executor_turn_id or request.executor_turn_id
    client_request_id = request.client_request_id
    stable_turn_key = client_request_id or request.request_id
    timeline_status = _timeline_status_from_codex_event(message)
    # Codex emits a premature "completed" turn-event (the dispatch ack) with no
    # message text; the real answer streams in afterward via native thread sync.
    # A contentless completion is not a finished answer — keep the turn live so
    # the UI shows a working state instead of settling into a blank turn.
    if timeline_status == "completed" and not (message.message and message.message.strip()):
        timeline_status = "running"
    input_modality = request.input_modality
    user = None
    if request.text:
        user = BroTimelineMessage(
            message_id=f"{request.target_thread_id}:{stable_turn_key}:user",
            role="user",
            kind="audio" if input_modality == "audio" else "text",
            text=request.text if input_modality == "text" else None,
            transcript=request.text if input_modality == "audio" else None,
            audio_id=request.audio_instruction_id,
            created_at=request.created_at or timestamp,
            updated_at=timestamp,
            status="completed",
            metadata={
                "source": "outbound_turn_request",
                "request_id": request.request_id,
                "instruction_id": request.metadata.get("instruction_id"),
                "source_audio_instruction_id": request.audio_instruction_id,
            },
        )
    assistant = None
    if message.message and timeline_status in {"completed", "failed"}:
        assistant = BroTimelineMessage(
            message_id=f"{request.target_thread_id}:{stable_turn_key}:assistant",
            role="assistant",
            kind="text",
            text=message.message,
            created_at=timestamp,
            updated_at=timestamp,
            status=timeline_status,
            metadata={
                "source": "codex_turn_event",
                "request_id": request.request_id,
                "event_type": message.event_type,
            },
        )
    metadata = {
        "source": "codex_turn_event",
        "request_id": request.request_id,
        "event_type": message.event_type,
        "executor_thread_id": executor_thread_id,
        "executor_turn_id": executor_turn_id,
        "client_request_id": client_request_id,
        **dict(message.metadata),
    }
    return BroTimelineTurn(
        turn_id=f"{request.target_thread_id}:outbound:{stable_turn_key}",
        thread_id=request.target_thread_id or "",
        persona_id=request.persona_id,
        executor_id=request.executor_id,
        owner="executor",
        client_request_id=client_request_id,
        executor_thread_id=executor_thread_id,
        executor_turn_id=executor_turn_id,
        input_modality=input_modality,
        user=user,
        assistant=assistant,
        status=timeline_status,
        created_at=request.created_at or timestamp,
        updated_at=timestamp,
        metadata=metadata,
    )


def _iso_from_epoch_seconds(value: int | float | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _title_from_codex_thread(item: CodexThreadListItem) -> str:
    if item.title and item.title.strip():
        return _title_from_draft_text(item.title)
    preview = (item.preview or "").strip()
    for line in preview.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.lower().startswith("task:"):
            candidate = candidate.split(":", 1)[1].strip()
        return _title_from_draft_text(candidate)
    return "Imported Codex thread"


def _workspace_name(workspace_id: str | None) -> str | None:
    if not isinstance(workspace_id, str):
        return None
    normalized = workspace_id.strip().rstrip("/\\")
    if not normalized:
        return None
    tail = normalized.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return tail or normalized


def _workspace_from_resume_handle(resume_handle: AgentResumeHandle | None) -> str | None:
    if resume_handle is None:
        return None
    cwd = resume_handle.opaque.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return cwd.strip()
    workspace_id = resume_handle.opaque.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return workspace_id.strip()
    return None


def _task_workspace_id(task: Task | None) -> str | None:
    if task is None:
        return None
    workspace_id = task.metadata.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return workspace_id.strip()
    if isinstance(task.session_affinity, str) and task.session_affinity.strip():
        return task.session_affinity.strip()
    return None


def _is_ephemeral_codex_thread(codex_thread: "CodexThreadListItem") -> bool:
    return codex_thread.diagnostics.get("ephemeral") is True


def _thread_timestamp_from_turn(turn: dict[str, object]) -> str | None:
    for key in ("createdAt", "created_at", "timestamp", "updatedAt", "updated_at"):
        value = turn.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, int | float):
            return _iso_from_epoch_seconds(value)
    return None


def _codex_thread_event_timestamp(params: dict[str, object]) -> str:
    timestamp = _thread_timestamp_from_turn(params)
    item = params.get("item")
    if timestamp is None and isinstance(item, dict):
        timestamp = _thread_timestamp_from_turn(item)
    return timestamp or datetime.now(tz=UTC).isoformat()


def _extract_codex_item_text(item: dict[str, object]) -> str | None:
    direct_text = item.get("text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()
    content = item.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, dict):
                text = entry.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(entry, str):
                parts.append(entry)
        text = "".join(parts).strip()
        if text:
            return text
    payload = item.get("payload")
    if isinstance(payload, dict):
        for key in ("message", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("message", "input"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _codex_item_role(item: dict[str, object]) -> Literal["user", "assistant"] | None:
    item_type = item.get("type")
    if item_type in {"assistantMessage", "agentMessage"}:
        return "assistant"
    if item_type in {"userMessage", "user_message"}:
        return "user"
    payload = item.get("payload")
    if isinstance(payload, dict) and payload.get("type") == "user_message":
        return "user"
    role = item.get("role")
    if role in {"user", "assistant"}:
        return role  # type: ignore[return-value]
    return None


def _normalize_codex_plan_status(value: object) -> Literal["pending", "inProgress", "completed"]:
    if isinstance(value, str):
        normalized = value.replace("_", "").replace("-", "").lower()
        if normalized in {"inprogress", "running", "active"}:
            return "inProgress"
        if normalized in {"completed", "complete", "done"}:
            return "completed"
    return "pending"


def _extract_codex_plan_step(value: object) -> dict[str, str] | None:
    if isinstance(value, str):
        text = value.strip()
        return {"step": text, "status": "pending"} if text else None
    if not isinstance(value, dict):
        return None
    text = None
    for key in ("step", "text", "title", "description", "content"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            text = candidate.strip()
            break
    if text is None:
        return None
    return {"step": text, "status": _normalize_codex_plan_status(value.get("status"))}


def _extract_codex_plan_steps(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    steps: list[dict[str, str]] = []
    for item in value:
        step = _extract_codex_plan_step(item)
        if step is not None:
            steps.append(step)
    return steps


def _extract_codex_plan(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    source = value
    raw_plan = value.get("plan")
    if isinstance(raw_plan, dict):
        source = raw_plan
        raw_steps = raw_plan.get("plan") or raw_plan.get("steps") or raw_plan.get("items")
    else:
        raw_steps = raw_plan or value.get("steps") or value.get("items")
    steps = _extract_codex_plan_steps(raw_steps)
    text = None
    for key in ("text", "content"):
        candidate = source.get(key)
        if isinstance(candidate, str) and candidate.strip():
            text = candidate.strip()
            break
    explanation = None
    for key in ("explanation", "summary"):
        candidate = source.get(key)
        if isinstance(candidate, str) and candidate.strip():
            explanation = candidate.strip()
            break
    if not text:
        text = _extract_codex_item_text(value)
    if not steps and not text and not explanation:
        return None
    plan: dict[str, object] = {"steps": steps}
    if text:
        plan["text"] = text
    if explanation:
        plan["explanation"] = explanation
    return plan


def _timeline_plan(value: object) -> BroTimelinePlan | None:
    if not isinstance(value, dict):
        return None
    try:
        plan = BroTimelinePlan.model_validate(value)
    except Exception:
        return None
    if plan.text or plan.explanation or plan.steps:
        return plan
    return None


def _run_timeline_plan(run: ExecutionRun | None) -> BroTimelinePlan | None:
    event = _run_metadata_dict(run, "latest_plan_event")
    plan_value = event.get("codex_plan")
    return _timeline_plan(plan_value)


def _mark_timeline_message_plan_mode(message: BroTimelineMessage | None) -> BroTimelineMessage | None:
    if message is None:
        return None
    return message.model_copy(update={"metadata": {**message.metadata, "plan_mode": True}})


def _codex_thread_goal(thread: dict[str, object]) -> str | None:
    for key in ("goal", "objective"):
        value = thread.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    goal = thread.get("goal")
    if isinstance(goal, dict):
        for key in ("text", "objective", "goal"):
            value = goal.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _timeline_status(task: Task | None, run: ExecutionRun | None, fallback: str = "pending") -> str:
    status = _thread_status(task, run)
    if status == "blocked":
        return "running"
    if status == "queued":
        return "pending"
    if status in {"pending", "running", "completed", "failed", "cancelled"}:
        return status
    return fallback


def _task_status_label(status: str) -> str:
    return status.replace("_", " ")


def _timeline_task_progress(status: str) -> int:
    if status == "completed":
        return 100
    if status == "running":
        return 60
    if status == "failed":
        return 30
    if status == "cancelled":
        return 30
    return 15


def _event_metadata_string(run: ExecutionRun | None, key: str) -> str | None:
    if run is None:
        return None
    for event_key in ("latest_terminal_event", "latest_progress_event", "blocked_event"):
        event = run.metadata.get(event_key)
        if isinstance(event, dict):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _task_input_modality(task: Task) -> Literal["text", "audio", "unknown"]:
    source_kind = task.metadata.get("source_kind")
    if source_kind == "bro_detail_ptt":
        return "audio"
    if source_kind == "bro_detail_text":
        return "text"
    if task.metadata.get("source_audio_instruction_id"):
        return "audio"
    return "text" if task.latest_instruction or task.goal else "unknown"


def _direct_user_text(task: Task) -> str:
    visible_text = _task_metadata_string(task, "user_visible_text")
    if visible_text is not None:
        return visible_text
    goal = task.goal.strip()
    title = task.title.strip()
    instruction = (task.latest_instruction or "").strip()
    if not instruction:
        return goal or title
    if goal and goal in instruction:
        return goal
    if title and title in instruction:
        return title
    return instruction


def _timeline_turns_from_codex_thread(
    *,
    thread: dict[str, object],
    public_thread_id: str,
    executor_thread_id: str,
    persona_id: str,
    executor_id: str = "codex",
) -> list[BroTimelineTurn]:
    turns = thread.get("turns")
    if not isinstance(turns, list):
        return []
    timeline_turns: list[BroTimelineTurn] = []
    pending_user_message: BroTimelineMessage | None = None
    pending_user_turn_id: str | None = None
    pending_user_timestamp: str | None = None
    thread_goal = _codex_thread_goal(thread)

    def append_user_only_turn() -> None:
        nonlocal pending_user_message, pending_user_turn_id, pending_user_timestamp
        if pending_user_message is None or pending_user_turn_id is None:
            return
        timeline_turns.append(
            BroTimelineTurn(
                turn_id=f"{public_thread_id}:{executor_id}:{pending_user_turn_id}",
                thread_id=public_thread_id,
                persona_id=persona_id,
                executor_id=executor_id,
                owner="executor",
                executor_thread_id=executor_thread_id,
                executor_turn_id=pending_user_turn_id,
                input_modality="text",
                user=pending_user_message,
                status="completed",
                created_at=pending_user_timestamp,
                updated_at=pending_user_timestamp,
                metadata={
                    "source": "native_history",
                    "executor_thread_id": executor_thread_id,
                    "executor_turn_id": pending_user_turn_id,
                    "assistant_title": pending_user_message.text,
                    "codex_goal": thread_goal,
                },
            )
        )
        pending_user_message = None
        pending_user_turn_id = None
        pending_user_timestamp = None

    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        turn_id = turn.get("id")
        turn_id_text = str(turn_id) if isinstance(turn_id, str) and turn_id else f"turn-{turn_index}"
        timestamp = _thread_timestamp_from_turn(turn)
        items = turn.get("items")
        if not isinstance(items, list):
            continue
        latest_user_message: BroTimelineMessage | None = None
        latest_assistant_message: BroTimelineMessage | None = None
        latest_plan: dict[str, object] | None = None
        has_plan_item = False
        has_assistant_item = False
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "plan":
                has_plan_item = True
                latest_plan = _extract_codex_plan(item)
                continue
            role = _codex_item_role(item)
            if role is None:
                continue
            text = _extract_codex_item_text(item)
            if not text:
                continue
            item_id = item.get("id")
            item_id_text = str(item_id) if isinstance(item_id, str) and item_id else f"item-{item_index}"
            status = item.get("status")
            if role == "assistant":
                has_assistant_item = True
                if item.get("phase") == "commentary":
                    # Commentary is intermediate working narration surfaced as a
                    # reasoning step, never the settled answer. Keeping it out of
                    # the answer slot stops an in-flight turn's commentary from
                    # rendering as a frozen answer below the steps when the
                    # timeline is reloaded (e.g. after a page refresh).
                    continue
            message = BroTimelineMessage(
                message_id=f"{public_thread_id}:{turn_id_text}:{role}",
                role=role,
                kind="text",
                text=text,
                created_at=timestamp,
                status=status if isinstance(status, str) and status else "completed",
                metadata={
                    "executor_turn_id": turn_id_text,
                    "codex_item_id": item_id_text,
                    "codex_item_type": item.get("type") if isinstance(item.get("type"), str) else None,
                },
            )
            if role == "assistant":
                latest_assistant_message = message
            else:
                latest_user_message = message
        if latest_user_message is None and latest_assistant_message is None and latest_plan is None:
            continue
        status_text = str(turn.get("status") or "").lower()
        turn_status: Literal["pending", "running", "completed", "failed", "cancelled"] = "completed"
        if status_text in {"running", "inprogress", "in_progress"}:
            turn_status = "running"
        elif status_text == "failed":
            turn_status = "failed"
        elif status_text in {"cancelled", "canceled"}:
            turn_status = "cancelled"
        if (
            latest_assistant_message is None
            and latest_user_message is not None
            and not has_plan_item
            and not has_assistant_item
        ):
            append_user_only_turn()
            pending_user_message = latest_user_message
            pending_user_turn_id = turn_id_text
            pending_user_timestamp = timestamp
            continue
        paired_user_message = latest_user_message
        original_user_turn_id: str | None = None
        if (
            (latest_assistant_message is not None or has_plan_item)
            and paired_user_message is None
            and pending_user_message is not None
        ):
            paired_user_message = pending_user_message
            original_user_turn_id = pending_user_turn_id
            pending_user_message = None
            pending_user_turn_id = None
            pending_user_timestamp = None
        elif latest_assistant_message is not None or has_assistant_item:
            append_user_only_turn()
        if has_plan_item:
            paired_user_message = _mark_timeline_message_plan_mode(paired_user_message)
        metadata = {
            "source": "native_history",
            "executor_thread_id": executor_thread_id,
            "executor_turn_id": turn_id_text,
            "assistant_title": paired_user_message.text if paired_user_message is not None else None,
            "original_user_executor_turn_id": original_user_turn_id,
            "codex_goal": thread_goal,
            "codex_plan": latest_plan,
        }
        if has_plan_item:
            metadata["plan_mode"] = True
        timeline_turns.append(
            BroTimelineTurn(
                turn_id=f"{public_thread_id}:{executor_id}:{turn_id_text}",
                thread_id=public_thread_id,
                persona_id=persona_id,
                executor_id=executor_id,
                owner="executor",
                executor_thread_id=executor_thread_id,
                executor_turn_id=turn_id_text,
                input_modality="text" if paired_user_message is not None else "unknown",
                user=paired_user_message,
                assistant=latest_assistant_message,
                status=turn_status,
                created_at=paired_user_message.created_at if paired_user_message is not None else timestamp,
                updated_at=timestamp,
                metadata=metadata,
            )
        )
    append_user_only_turn()
    return timeline_turns


def _build_bro_thread_projection(
    *,
    tasks: list[Task],
    sessions: list[ExecutionSession],
    runs: list[ExecutionRun],
    summaries: list[TaskSummary],
    personas,
    imported_threads: list[BroThread] | None = None,
) -> list[BroThread]:
    task_by_id = {task.task_id: task for task in tasks}
    run_by_id = {run.run_id: run for run in runs}
    summary_by_task_id = {summary.task_id: summary for summary in summaries}
    persona_by_id = {persona.persona_id: persona for persona in personas}
    threads: list[BroThread] = []
    for session in sessions:
        if session.base_executor_id != "codex":
            continue
        session_runs = [run_by_id[run_id] for run_id in session.run_ids if run_id in run_by_id]
        if not session_runs and session.latest_run_id in run_by_id:
            session_runs.append(run_by_id[session.latest_run_id])
        task_ids = []
        for run in session_runs:
            if run.task_id not in task_ids:
                task_ids.append(run.task_id)
        if session.task_id and session.task_id not in task_ids:
            task_ids.insert(0, session.task_id)
        session_tasks = [task_by_id[task_id] for task_id in task_ids if task_id in task_by_id]
        latest_run = run_by_id.get(session.latest_run_id or "") if session.latest_run_id else (session_runs[-1] if session_runs else None)
        latest_task = (
            task_by_id.get(latest_run.task_id)
            if latest_run is not None
            else (session_tasks[-1] if session_tasks else task_by_id.get(session.task_id))
        )
        persona_id = _task_metadata_string(latest_task, "persona_id") or _task_metadata_string(latest_task, "assigned_bro_id")
        if persona_id is None:
            for persona in personas:
                if session.continuity_key == persona.bro_detail_session_id:
                    persona_id = persona.persona_id
                    break
        if persona_id is None or persona_id not in persona_by_id:
            continue
        summary = summary_by_task_id.get(latest_task.task_id) if latest_task is not None else None
        status = _thread_status(latest_task, latest_run)
        resume_handle = session.latest_resume_handle
        has_resume_handle = (
            resume_handle is not None
            and resume_handle.executor_id == "codex"
            and isinstance(resume_handle.session_handle, str)
            and bool(resume_handle.session_handle)
        )
        preview = (
            summary.conversational_summary
            if summary is not None and summary.conversational_summary
            else summary.operational_summary
            if summary is not None and summary.operational_summary
            else latest_run.output_summary
            if latest_run is not None and latest_run.output_summary
            else latest_run.latest_progress_message
            if latest_run is not None and latest_run.latest_progress_message
            else latest_task.goal
            if latest_task is not None
            else None
        )
        latest_task_updated_at = _task_updated_at(latest_task)
        updated_at = latest_task_updated_at
        if _task_metadata_string(latest_task, "source_kind") == "codex_thread_history":
            updated_at = _resume_handle_string(resume_handle, "listUpdatedAt") or latest_task_updated_at
        diagnostics: dict[str, object] = {
            "has_codex_resume_handle": has_resume_handle,
        }
        if has_resume_handle:
            diagnostics["codex_thread_id"] = resume_handle.session_handle
            cwd = resume_handle.opaque.get("cwd")
            if isinstance(cwd, str):
                diagnostics["codex_cwd"] = cwd
        workspace_id = _workspace_from_resume_handle(resume_handle) or _task_workspace_id(latest_task)
        if any(task.metadata.get("codex_history_hydrated") for task in session_tasks):
            diagnostics["history_hydrated"] = True
        active_task_id = None
        if (
            latest_run is not None
            and session.active_run_id == latest_run.run_id
            and latest_run.status in AUDIO_ACTIVE_RUN_STATUSES
        ):
            active_task_id = latest_run.task_id
        display_title = (
            _resume_handle_string(resume_handle, "title")
            or _resume_handle_string(resume_handle, "displayTitle")
            or (latest_task.title if latest_task is not None else "Current session")
        )
        threads.append(
            BroThread(
                thread_id=_public_thread_id(session),
                persona_id=persona_id,
                persona_name=persona_by_id[persona_id].name,
                executor_node_id=session.executor_node_id,
                workspace_id=workspace_id,
                workspace_name=_workspace_name(workspace_id),
                execution_session_id=session.execution_session_id,
                status=status,  # type: ignore[arg-type]
                title=display_title,
                preview=preview,
                progress=_thread_progress(status),
                task_ids=task_ids,
                active_task_id=active_task_id,
                latest_task_id=latest_task.task_id if latest_task is not None else None,
                has_resume_handle=has_resume_handle,
                updated_at=updated_at,
                diagnostics=diagnostics,
            )
        )
    existing_codex_thread_keys = {
        (thread.persona_id, thread.diagnostics.get("codex_thread_id"))
        for thread in threads
        if isinstance(thread.diagnostics.get("codex_thread_id"), str)
    }
    existing_thread_ids = {thread.thread_id for thread in threads}
    for imported in imported_threads or []:
        if imported.thread_id in existing_thread_ids:
            continue
        if (imported.persona_id, imported.diagnostics.get("codex_thread_id")) in existing_codex_thread_keys:
            continue
        imported_task_ids = [
            task.task_id
            for task in tasks
            if task.metadata.get("bro_thread_id") == imported.thread_id
            and (
                task.metadata.get("persona_id") == imported.persona_id
                or task.metadata.get("assigned_bro_id") == imported.persona_id
            )
        ]
        if imported_task_ids:
            latest_task = task_by_id.get(imported_task_ids[-1])
            latest_run = None
            for run in reversed(runs):
                if run.task_id == imported_task_ids[-1]:
                    latest_run = run
                    break
            summary = summary_by_task_id.get(imported_task_ids[-1])
            preview = (
                summary.conversational_summary
                if summary is not None and summary.conversational_summary
                else latest_run.output_summary
                if latest_run is not None and latest_run.output_summary
                else imported.preview
            )
            imported = imported.model_copy(
                update={
                    "task_ids": imported_task_ids,
                    "latest_task_id": imported_task_ids[-1],
                    "preview": preview,
                    "updated_at": _task_updated_at(latest_task) or imported.updated_at,
                    "diagnostics": {
                        **imported.diagnostics,
                        "history_hydrated": True,
                    },
                }
            )
        threads.append(imported)

    existing_thread_ids = {thread.thread_id for thread in threads}
    task_thread_groups: dict[tuple[str, str], list[Task]] = {}
    for task in tasks:
        public_thread_id = _task_thread_public_id(task)
        if public_thread_id is None or public_thread_id in existing_thread_ids:
            continue
        persona_id = _task_metadata_string(task, "persona_id") or _task_metadata_string(task, "assigned_bro_id")
        if persona_id is None or persona_id not in persona_by_id:
            continue
        task_thread_groups.setdefault((persona_id, public_thread_id), []).append(task)

    for (persona_id, public_thread_id), thread_tasks in task_thread_groups.items():
        sorted_tasks = sorted(thread_tasks, key=lambda task: _task_updated_at(task) or task.task_id)
        latest_task = sorted_tasks[-1]
        task_ids = [task.task_id for task in sorted_tasks]
        latest_run = None
        for run in reversed(runs):
            if run.task_id == latest_task.task_id:
                latest_run = run
                break
        summary = summary_by_task_id.get(latest_task.task_id)
        status = _thread_status(latest_task, latest_run)
        preview = (
            summary.conversational_summary
            if summary is not None and summary.conversational_summary
            else summary.operational_summary
            if summary is not None and summary.operational_summary
            else latest_run.output_summary
            if latest_run is not None and latest_run.output_summary
            else latest_run.latest_progress_message
            if latest_run is not None and latest_run.latest_progress_message
            else latest_task.goal
        )
        has_resume_handle = bool(_task_metadata_string(latest_task, "codex_import_thread_id"))
        diagnostics: dict[str, object] = {"pending_execution_session": True}
        codex_thread_id = _task_metadata_string(latest_task, "codex_import_thread_id")
        if codex_thread_id is not None:
            diagnostics["has_codex_resume_handle"] = True
            diagnostics["codex_thread_id"] = codex_thread_id
        workspace_id = _task_workspace_id(latest_task)
        codex_import_cwd = _task_metadata_string(latest_task, "codex_import_cwd")
        if codex_import_cwd is not None:
            workspace_id = codex_import_cwd
        executor_node_id = _task_metadata_string(latest_task, "executor_node_id") or persona_by_id[persona_id].executor_node_id
        active_task_id = latest_task.task_id if status in {"queued", "running", "blocked"} else None
        threads.append(
            BroThread(
                thread_id=public_thread_id,
                persona_id=persona_id,
                persona_name=persona_by_id[persona_id].name,
                executor_node_id=executor_node_id,
                workspace_id=workspace_id,
                workspace_name=_workspace_name(workspace_id),
                execution_session_id=None,
                status=status,  # type: ignore[arg-type]
                title=latest_task.title or "Current session",
                preview=preview,
                progress=_thread_progress(status),
                task_ids=task_ids,
                active_task_id=active_task_id,
                latest_task_id=latest_task.task_id,
                has_resume_handle=has_resume_handle,
                updated_at=_task_updated_at(latest_task),
                diagnostics=diagnostics,
            )
        )
    return sorted(
        threads,
        key=lambda thread: (
            1 if thread.status in {"running", "blocked", "queued"} else 0,
            thread.updated_at or "",
            thread.execution_session_id or "",
        ),
        reverse=True,
    )


def _summary_text_for_timeline(
    *,
    task: Task,
    run: ExecutionRun | None,
    summary: TaskSummary | None,
) -> str:
    if summary is not None:
        if summary.conversational_summary:
            return summary.conversational_summary
        if summary.operational_summary:
            return summary.operational_summary
    if run is not None:
        if run.output_summary:
            return run.output_summary
        if run.failure_reason:
            return run.failure_reason
        if run.block_reason:
            return run.block_reason
        if run.latest_progress_message:
            return run.latest_progress_message
    return task.goal or task.title


def _run_metadata_dict(run: ExecutionRun | None, key: str) -> dict[str, object]:
    if run is None:
        return {}
    value = run.metadata.get(key)
    return value if isinstance(value, dict) else {}


def _audio_transcript_for_task(task: Task, run: ExecutionRun | None) -> str | None:
    audio_id = task.metadata.get("source_audio_instruction_id")
    if not isinstance(audio_id, str) or not audio_id:
        return None
    transcripts = _run_metadata_dict(run, "audio_transcripts")
    transcript = transcripts.get(audio_id)
    if isinstance(transcript, str) and transcript.strip():
        return transcript.strip()
    instruction = (task.latest_instruction or "").strip()
    return instruction or None


def _build_newbro_timeline_turns(
    *,
    tasks: list[Task],
    sessions: list[ExecutionSession],
    runs: list[ExecutionRun],
    summaries: list[TaskSummary],
) -> list[BroTimelineTurn]:
    runs_by_task: dict[str, list[ExecutionRun]] = {}
    for run in runs:
        runs_by_task.setdefault(run.task_id, []).append(run)
    session_by_id = {session.execution_session_id: session for session in sessions}
    summary_by_task_id = {summary.task_id: summary for summary in summaries}
    turns: list[BroTimelineTurn] = []
    for task in tasks:
        public_thread_id = _task_thread_public_id(task)
        if public_thread_id is None:
            continue
        persona_id = _task_metadata_string(task, "persona_id") or _task_metadata_string(task, "assigned_bro_id")
        if persona_id is None:
            continue
        task_runs = runs_by_task.get(task.task_id, [])
        run = task_runs[-1] if task_runs else None
        execution_session = session_by_id.get(run.execution_session_id) if run is not None else None
        status = _timeline_status(task, run)
        created_at = _task_metadata_string(task, "created_at")
        updated_at = _task_updated_at(task) or created_at
        client_request_id = _task_metadata_string(task, "client_request_id")
        executor_id = task.preferred_executor or (run.executor_type if run is not None else "codex")
        executor_thread_id = (
            _event_metadata_string(run, "executor_thread_id")
            or _event_metadata_string(run, "thread_id")
            or _task_metadata_string(task, "codex_import_thread_id")
        )
        if executor_thread_id is None and execution_session is not None and execution_session.latest_resume_handle:
            handle = execution_session.latest_resume_handle
            if isinstance(handle.session_handle, str) and handle.session_handle:
                executor_thread_id = handle.session_handle
        executor_turn_id = (
            _event_metadata_string(run, "executor_turn_id")
            or _event_metadata_string(run, "turn_id")
        )
        plan_mode = task.metadata.get("plan_mode") is True
        message_metadata = {
            "source_kind": task.metadata.get("source_kind"),
            **({"plan_mode": True} if plan_mode else {}),
        }
        input_modality = _task_input_modality(task)
        user_text = _direct_user_text(task)
        audio_id = _task_metadata_string(task, "source_audio_instruction_id")
        if input_modality == "audio":
            user_message = BroTimelineMessage(
                message_id=f"{task.task_id}:user",
                role="user",
                kind="audio",
                text=None,
                transcript=_audio_transcript_for_task(task, run) or user_text or None,
                audio_id=audio_id,
                status="sent" if status != "failed" else "failed",
                created_at=created_at,
                updated_at=updated_at,
                metadata=message_metadata,
            )
        else:
            user_message = BroTimelineMessage(
                message_id=f"{task.task_id}:user",
                role="user",
                kind="text",
                text=user_text or None,
                status="sent" if status != "failed" else "failed",
                created_at=created_at,
                updated_at=updated_at,
                metadata=message_metadata,
            )
        summary_text = _summary_text_for_timeline(task=task, run=run, summary=summary_by_task_id.get(task.task_id))
        plan = _run_timeline_plan(run)
        assistant_text = None
        if run is not None:
            assistant_text = run.output_summary or run.failure_reason or run.block_reason or run.latest_progress_message
        assistant = (
            BroTimelineMessage(
                message_id=f"{task.task_id}:assistant",
                role="assistant",
                kind="text",
                text=assistant_text,
                status=status,
                created_at=updated_at,
                updated_at=updated_at,
                metadata={"source": "newbro_task"},
            )
            if assistant_text
            else None
        )
        task_status = run.status.value if run is not None else task.status.value
        turns.append(
            BroTimelineTurn(
                turn_id=(
                    f"{public_thread_id}:newbro:{client_request_id}"
                    if client_request_id
                    else f"{public_thread_id}:newbro:{task.task_id}"
                ),
                thread_id=public_thread_id,
                persona_id=persona_id,
                executor_id=executor_id,
                owner="newbro",
                client_request_id=client_request_id,
                executor_thread_id=executor_thread_id,
                executor_turn_id=executor_turn_id,
                input_modality=input_modality,
                user=user_message,
                assistant=assistant,
                task=BroTimelineTask(
                    task_id=task.task_id,
                    run_id=run.run_id if run is not None else None,
                    title=task.title,
                    status=task_status,
                    status_label=_task_status_label(task_status),
                    progress=_timeline_task_progress(status),
                    goal=task.goal.strip() or None,
                    plan=plan,
                    description=summary_text,
                    summary=summary_text,
                    created_at=created_at,
                    updated_at=updated_at,
                    metadata={
                        "source_kind": task.metadata.get("source_kind"),
                        "target_thread_id": public_thread_id,
                        **({"plan_mode": True} if plan_mode else {}),
                    },
                ),
                status=status,  # type: ignore[arg-type]
                created_at=created_at,
                updated_at=updated_at,
                metadata={
                    "source": "newbro_task",
                    "task_id": task.task_id,
                    **({"plan_mode": True} if plan_mode else {}),
                    **({"run_id": run.run_id} if run is not None else {}),
                },
            )
        )
    return turns


def _timeline_identity(turn: BroTimelineTurn) -> tuple[str, str, str] | None:
    if not turn.executor_thread_id or not turn.executor_turn_id:
        return None
    return (turn.executor_id, turn.executor_thread_id, turn.executor_turn_id)


_STREAMING_MESSAGE_STATUSES = {"running", "in_progress", "inprogress", "pending", "streaming"}


def _message_status(message: BroTimelineMessage | None) -> str:
    return (message.status or "").lower() if message is not None else ""


def _merge_timeline_turn(existing: BroTimelineTurn, incoming: BroTimelineTurn) -> BroTimelineTurn:
    user = existing.user or incoming.user
    # A turn is "truly settled" only when it failed/cancelled, or completed with a
    # real final answer already present. A contentless "completed" (premature
    # dispatch ack) is NOT settled — the answer is still streaming.
    existing_settled = existing.status in {"failed", "cancelled"} or (
        existing.status == "completed"
        and existing.assistant is not None
        and _message_status(existing.assistant) not in _STREAMING_MESSAGE_STATUSES
    )
    # Once a turn has truly settled (a final answer / turn-level completion),
    # later still-streaming echoes for the SAME turn are stale and must not
    # overwrite the final answer or un-settle the bubble.
    if existing_settled and _message_status(incoming.assistant) in _STREAMING_MESSAGE_STATUSES:
        assistant = existing.assistant
    else:
        assistant = incoming.assistant or existing.assistant
    task = existing.task or incoming.task
    if existing.task is not None and incoming.task is not None:
        task = existing.task.model_copy(
            update={
                "goal": existing.task.goal or incoming.task.goal,
                "plan": incoming.task.plan or existing.task.plan,
                "summary": incoming.task.summary or existing.task.summary,
                "description": incoming.task.description or existing.task.description,
            }
        )
    status = existing.status
    if existing.status in {"pending", "running"} and incoming.status in {"completed", "failed", "cancelled", "running"}:
        status = incoming.status
        # A contentless "completed" is a premature / eventually-consistent signal
        # (codex marks the thread turn completed before the answer streams). If no
        # assistant answer exists yet, the turn is still in flight — keep it running.
        if status == "completed" and assistant is None:
            status = "running"
    # A turn whose assistant message is still streaming is not done, even if an
    # earlier (outbound) event reported "completed". Trust the streaming assistant
    # so the live cue stays until the answer is actually complete — but never
    # un-settle a turn that already reached a terminal turn-level completion.
    if not existing_settled and status not in {"failed", "cancelled"} and assistant is not None:
        if _message_status(assistant) in _STREAMING_MESSAGE_STATUSES:
            status = "running"
    metadata = {**existing.metadata}
    for key, value in incoming.metadata.items():
        if value is not None or key not in metadata:
            metadata[key] = value
    if metadata.get("plan_mode") is True:
        user = _mark_timeline_message_plan_mode(user)
    return existing.model_copy(
        update={
            "user": user,
            "assistant": assistant,
            "task": task,
            "status": status,
            "client_request_id": existing.client_request_id or incoming.client_request_id,
            "executor_thread_id": existing.executor_thread_id or incoming.executor_thread_id,
            "executor_turn_id": existing.executor_turn_id or incoming.executor_turn_id,
            "input_modality": existing.input_modality if existing.input_modality != "unknown" else incoming.input_modality,
            "updated_at": incoming.updated_at or existing.updated_at,
            "metadata": metadata,
        }
    )


def _sort_timeline_turns(turns: list[BroTimelineTurn]) -> list[BroTimelineTurn]:
    def key(turn: BroTimelineTurn) -> tuple[float, str]:
        timestamp = turn.created_at or turn.updated_at or ""
        parsed = DateParseCache.parse(timestamp)
        return (parsed, turn.turn_id)

    return sorted(turns, key=key)


def _should_emit_selected_thread_plan_delta(candidate: str, previous: str) -> bool:
    if candidate == previous:
        return False
    if not previous:
        return len(candidate) >= 240 or candidate.endswith(("\n\n", ".", "。", "!", "！", "?", "？"))
    added = candidate[len(previous) :]
    return len(added) >= 240 or candidate.endswith(("\n\n", ".", "。", "!", "！", "?", "？"))


class DateParseCache:
    _cache: dict[str, float] = {}

    @classmethod
    def parse(cls, value: str) -> float:
        if not value:
            return float("-inf")
        cached = cls._cache.get(value)
        if cached is not None:
            return cached
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            parsed = float("-inf")
        cls._cache[value] = parsed
        return parsed


def _build_bro_timeline_projection(
    *,
    tasks: list[Task],
    sessions: list[ExecutionSession],
    runs: list[ExecutionRun],
    summaries: list[TaskSummary],
    executor_turns: list[BroTimelineTurn],
) -> list[BroTimelineTurn]:
    merged: dict[str, BroTimelineTurn] = {}
    by_executor_identity: dict[tuple[str, str, str], str] = {}
    by_client_request_id: dict[str, str] = {}
    for turn in _build_newbro_timeline_turns(tasks=tasks, sessions=sessions, runs=runs, summaries=summaries):
        merged[turn.turn_id] = turn
        if turn.client_request_id:
            by_client_request_id[turn.client_request_id] = turn.turn_id
        identity = _timeline_identity(turn)
        if identity is not None:
            by_executor_identity[identity] = turn.turn_id
    for turn in executor_turns:
        existing_id = by_client_request_id.get(turn.client_request_id) if turn.client_request_id else None
        if existing_id is not None and existing_id in merged:
            merged[existing_id] = _merge_timeline_turn(merged[existing_id], turn)
            identity = _timeline_identity(merged[existing_id])
            if identity is not None:
                by_executor_identity[identity] = existing_id
            continue
        identity = _timeline_identity(turn)
        existing_id = by_executor_identity.get(identity) if identity is not None else None
        if existing_id is not None and existing_id in merged:
            merged[existing_id] = _merge_timeline_turn(merged[existing_id], turn)
            continue
        merged[turn.turn_id] = turn
        if turn.client_request_id:
            by_client_request_id[turn.client_request_id] = turn.turn_id
        if identity is not None:
            by_executor_identity[identity] = turn.turn_id
    return _sort_timeline_turns(list(merged.values()))
