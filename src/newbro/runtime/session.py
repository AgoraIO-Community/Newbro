from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from dataclasses import replace
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from newbro.blackboard import InMemoryBlackboard
from newbro.communication import CommunicationBrain
from newbro.communication.persona_pool import (
    create_workspace,
    load_personas_from_file,
)
from newbro.communication.history import InMemoryConversationHistory
from newbro.communication.interaction_classifier import (
    InteractionClassification,
    InteractionClassifier,
    InteractionClassifierState,
    UnavailableInteractionClassifier,
)
from newbro.communication.model import CommunicationModel, LlmTraceRecord, ToolCallRecord
from newbro.communication.tools import build_default_tool_registry
from newbro.communication.types import CommunicationTurnResult
from newbro.executors.adapters.hosted import HostedExecutor
from newbro.executors.adapters.codex.session import CodexExecutorSession
from newbro.execution import ExecutionBrain
from newbro.executors.adapters.mock import MockExecutor
from newbro.executors.core import ExecutorRegistry, UnknownExecutorError
from newbro.interaction import InteractionManager
from newbro.interaction.sanitization import (
    sanitize_interaction_request_details,
    sanitize_interaction_request_opaque,
)
from newbro.notification import NotificationManager
from newbro.observability.bootstrap import SessionObservability, build_session_observability
from newbro.observability.context import bind_diagnostic_context
from newbro.observability.reason_codes import COMMUNICATION_MODEL_FAILURE
from newbro.protocol import (
    AgentEvent,
    AgentEventDelivery,
    AgentEventImportance,
    AgoraVoiceEvent,
    AgoraVoiceEventType,
    AgentResumeHandle,
    AttentionItemKind,
    BroThread,
    BroTimelineMessage,
    BroTimelinePlan,
    BroTimelineTask,
    BroTimelineTurn,
    CodexThreadEventMessage,
    CodexThreadListItem,
    CodexTurnEventMessage,
    DispatchGateOutcome,
    BindingStatus,
    ExecutionMode,
    ExecutionRun,
    ExecutionSession,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    InteractionType,
    InteractionRequest,
    InteractionRequestKind,
    MutationType,
    NotificationDeliveryStatus,
    OutboundTurnRequest,
    RunStatus,
    RuntimeDecision,
    RuntimeSessionState,
    UiUpdate,
    TaskCommand,
    TaskCommandType,
    TaskExecutionMode,
    TaskMutation,
    TaskMode,
    TaskStatus,
    TaskSummary,
    Task,
)

from .config import Settings
from .drafts import (
    DEFAULT_BRO_ID,
    DraftRewriter,
    DraftSessionManager,
    build_dispatch_plan,
    dispatch_gate,
)
from .executor_node_manager import ExecutorNodeManager
from .models import (
    ActionAcceptedStreamEvent,
    ActionRejectedStreamEvent,
    AssistantResponseCompletedStreamEvent,
    AssistantResponseDeltaStreamEvent,
    AssistantResponseFailedStreamEvent,
    AssistantResponseStartedStreamEvent,
    ConversationAppendedStreamEvent,
    ConversationHistoryEntryModel,
    ConversationSnapshot,
    DraftOutputCompletedStreamEvent,
    DraftOutputDeltaStreamEvent,
    DraftOutputFailedStreamEvent,
    DraftOutputStartedStreamEvent,
    SessionSnapshot,
    SessionStreamEventBase,
    SnapshotStreamEvent,
    UserMessageAppendedStreamEvent,
)


FALLBACK_ASSISTANT_ERROR_MESSAGE = "Sorry, something went wrong while generating the reply."
LOGGER = logging.getLogger(__name__)
PLAN_APPROVAL_VISIBLE_TEXT = "Implement it"
MAX_TASK_INSTRUCTION_CHARS = 4000
AUDIO_ACTIVE_RUN_STATUSES = {RunStatus.ASSIGNED, RunStatus.RUNNING, RunStatus.BLOCKED}
SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS = 2.0
BRO_THREAD_PREFIX = "bro-thread-"
IMPORTED_CODEX_THREAD_PREFIX = "codex-import-"


def _title_from_draft_text(text: str) -> str:
    title = " ".join(text.strip().split()).rstrip(".。")
    if len(title) > 72:
        title = title[:69].rstrip() + "..."
    return title or "Draft task"


def _mark_direct_executor_input(
    metadata: dict[str, object],
    source: str,
) -> dict[str, object]:
    next_metadata = dict(metadata)
    sources = next_metadata.get("direct_executor_input_sources")
    if isinstance(sources, list):
        direct_sources = [item for item in sources if isinstance(item, str)]
    else:
        direct_sources = []
    if source not in direct_sources:
        direct_sources.append(source)
    next_metadata["direct_executor_input_sources"] = direct_sources
    next_metadata["updated_at"] = datetime.now(tz=UTC).isoformat()
    next_metadata["suppress_communication_notifications"] = True
    return next_metadata


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


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
        if latest_assistant_message is None and latest_user_message is not None and not has_plan_item:
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
        elif latest_assistant_message is not None:
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


def _merge_timeline_turn(existing: BroTimelineTurn, incoming: BroTimelineTurn) -> BroTimelineTurn:
    user = existing.user or incoming.user
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


def _task_instruction_from_draft(draft) -> str:
    task_spec = getattr(draft, "task_spec", None)
    if task_spec is None:
        return draft.text
    constraints = "\n".join(f"- {item}" for item in task_spec.constraints)
    success = "\n".join(f"- {item}" for item in task_spec.success_criteria)
    stop_conditions = "\n".join(f"- {item}" for item in task_spec.stop_conditions)
    parts = [
        f"Task: {task_spec.goal}",
        f"Mode: {task_spec.mode.value}",
        f"Expected output: {task_spec.expected_output}",
    ]
    if constraints:
        parts.append(f"Constraints:\n{constraints}")
    if success:
        parts.append(f"Success criteria:\n{success}")
    if stop_conditions:
        parts.append(f"Stop conditions:\n{stop_conditions}")
    return "\n\n".join(parts)


def _runtime_state(*, has_draft: bool, active_tasks: list[Task]) -> RuntimeSessionState:
    if has_draft:
        return RuntimeSessionState.WAITING_FOR_CONFIRMATION
    if not active_tasks:
        return RuntimeSessionState.IDLE
    return _state_for_task(active_tasks[-1])


def _state_for_task(task: Task | None) -> RuntimeSessionState:
    if task is None:
        return RuntimeSessionState.IDLE
    if task.status == TaskStatus.WAITING_USER_INPUT:
        return RuntimeSessionState.TASK_BLOCKED
    if task.status == TaskStatus.COMPLETED:
        return RuntimeSessionState.TASK_COMPLETE
    if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED}:
        return RuntimeSessionState.TASK_RUNNING
    return RuntimeSessionState.IDLE


def _should_speak_for_classification(classification: InteractionClassification) -> bool:
    if classification.requires_user_decision:
        return True
    return classification.importance == "urgent"


def _classification_response_text(classification: InteractionClassification) -> str:
    if not _should_speak_for_classification(classification):
        return ""
    if classification.interaction_type == InteractionType.UNCERTAIN:
        return "I need a clearer instruction."
    return ""


def _should_speak_for_draft_decision(
    *,
    interaction: InteractionType,
    classification: InteractionClassification,
    gate: DispatchGateResult,
) -> bool:
    if gate.outcome in {DispatchGateOutcome.ASK_CLARIFICATION, DispatchGateOutcome.REJECT}:
        return True
    if classification.requires_user_decision:
        return True
    return interaction == InteractionType.DELEGATION and gate.outcome == DispatchGateOutcome.ASK_CONFIRMATION


@dataclass(slots=True)
class PendingMessageRequest:
    request_id: str
    user_text: str
    completion: asyncio.Future[CommunicationTurnResult]
    target_persona_id: str | None = None


@dataclass(slots=True)
class LiveTranscriptWork:
    generation: int
    text: str
    language: str | None
    timestamp_ms: int | None
    assigned_bro_id: str | None
    source_boundary: Literal["stt.partial", "stt.final"]
    scheduled_at: float


@dataclass(slots=True)
class SelectedCodexThreadSubscription:
    subscription_id: str
    persona_id: str
    public_thread_id: str
    thread_continuity_key: str
    node_id: str
    codex_thread_id: str
    resume_handle: AgentResumeHandle
    fallback_timestamp: str | None = None


@dataclass(slots=True)
class SessionRuntime:
    session_id: str
    blackboard: InMemoryBlackboard
    history: InMemoryConversationHistory
    registry: ExecutorRegistry
    communication_brain: CommunicationBrain
    execution_brain: ExecutionBrain
    notification_manager: NotificationManager
    interaction_manager: InteractionManager
    observability: SessionObservability
    executor_node_manager: ExecutorNodeManager
    interaction_classifier: InteractionClassifier = field(default_factory=UnavailableInteractionClassifier)
    live_interaction_classifier_interval_seconds: float = 1.0
    default_executor_type: str = "mock"
    draft_manager: DraftSessionManager = field(default_factory=DraftSessionManager)
    subscribers: list[asyncio.Queue[SessionStreamEventBase]] = field(default_factory=list)
    _message_queue: asyncio.Queue[PendingMessageRequest] = field(default_factory=asyncio.Queue)
    _execution_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _communication_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _notification_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _snapshot_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _diagnostic_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _blackboard_queue: asyncio.Queue | None = field(default=None, init=False, repr=False)
    _notification_blackboard_queue: asyncio.Queue | None = field(default=None, init=False, repr=False)
    _diagnostic_blackboard_queue: asyncio.Queue | None = field(default=None, init=False, repr=False)
    _notification_wakeup: asyncio.Event = field(default_factory=asyncio.Event)
    _next_sequence: int = field(default=1, init=False, repr=False)
    _active_assistant_turns: int = field(default=0, init=False, repr=False)
    _diagnostic_seen_entities: set[tuple[str, str | None]] = field(default_factory=set, init=False, repr=False)
    _voice_target_persona_id: str | None = field(default=None, init=False, repr=False)
    _last_live_classifier_ms: int | None = field(default=None, init=False, repr=False)
    _latest_live_transcript: str = field(default="", init=False, repr=False)
    _live_generation: int = field(default=0, init=False, repr=False)
    _latest_published_live_text: str = field(default="", init=False, repr=False)
    _live_partial_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _live_partial_work: LiveTranscriptWork | None = field(default=None, init=False, repr=False)
    _last_spoken_confirmation_draft_session_id: str | None = field(default=None, init=False, repr=False)
    _last_spoken_confirmation_revision_id: str | None = field(default=None, init=False, repr=False)
    _imported_codex_threads: dict[str, BroThread] = field(default_factory=dict, init=False, repr=False)
    _imported_codex_thread_resume_handles: dict[str, AgentResumeHandle] = field(default_factory=dict, init=False, repr=False)
    _codex_thread_public_id_aliases: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _codex_thread_sync_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _last_codex_thread_sync_monotonic: float = field(default=0.0, init=False, repr=False)
    _selected_codex_thread_subscriptions: dict[str, SelectedCodexThreadSubscription] = field(default_factory=dict, init=False, repr=False)
    _selected_codex_thread_subscription_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict, init=False, repr=False)
    _open_bro_thread_locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)
    _bro_thread_executor_turns: dict[str, list[BroTimelineTurn]] = field(default_factory=dict, init=False, repr=False)
    _bro_thread_timeline_status: dict[str, Literal["not_loaded", "loading", "loaded", "failed"]] = field(default_factory=dict, init=False, repr=False)
    _bro_thread_timeline_errors: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _bro_thread_live_message_deltas: dict[tuple[str, str, str], str] = field(default_factory=dict, init=False, repr=False)
    _bro_thread_live_plan_deltas: dict[tuple[str, str, str], str] = field(default_factory=dict, init=False, repr=False)
    _bro_thread_live_plan_emitted_text: dict[tuple[str, str, str], str] = field(default_factory=dict, init=False, repr=False)
    _bro_thread_goals: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def _record_direct_executor_text_metric(
        self,
        *,
        step: str,
        client_request_id: str | None,
        instruction_id: str | None = None,
        target_persona_id: str | None = None,
        target_thread_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        execution_session_id: str | None = None,
        elapsed_ms: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        metric_details: dict[str, object] = {
            "step": step,
            "client_request_id": client_request_id,
            "instruction_id": instruction_id,
            "target_persona_id": target_persona_id,
            "target_thread_id": target_thread_id,
        }
        if elapsed_ms is not None:
            metric_details["elapsed_ms"] = elapsed_ms
        if details:
            metric_details.update(details)
        self.observability.logger.emit_event(
            level="INFO",
            event_name=f"executor_text.{step}",
            component="runtime.direct_executor",
            summary="Executor text instruction timing",
            conversation_id=self.session_id,
            request_id=client_request_id,
            task_id=task_id,
            run_id=run_id,
            execution_session_id=execution_session_id,
            executor_type="codex",
            details=metric_details,
        )
        LOGGER.info(
            "executor_text_metric step=%s session_id=%s client_request_id=%s instruction_id=%s target_persona_id=%s target_thread_id=%s task_id=%s run_id=%s execution_session_id=%s elapsed_ms=%s",
            step,
            self.session_id,
            client_request_id,
            instruction_id,
            target_persona_id,
            target_thread_id,
            task_id,
            run_id,
            execution_session_id,
            elapsed_ms,
        )

    async def snapshot(self, *, sync_imported_codex_threads: bool = True) -> SessionSnapshot:
        tasks = await self.blackboard.list_tasks()
        sessions = await self.blackboard.list_sessions()
        runs = await self.blackboard.list_runs()
        execution_modes = await self.blackboard.list_execution_modes()
        notification_candidates = await self.blackboard.list_notification_candidates()
        outbound_turn_requests = await self.blackboard.list_outbound_turn_requests()
        bindings = await self.blackboard.list_bindings()
        interaction_requests = await self.blackboard.list_interaction_requests()
        sanitized_interaction_requests = [
            request.model_copy(
                update={
                    "opaque": sanitize_interaction_request_opaque(request.opaque),
                    "details": sanitize_interaction_request_details(request.details),
                }
            )
            for request in interaction_requests
        ]
        attention_items = await self.blackboard.list_attention_items()
        summaries = [
            summary
            for summary in [await self.blackboard.get_summary(task.task_id) for task in tasks]
            if summary is not None
        ]
        personas = await self.blackboard.list_personas()
        imported_threads = (
            await self._sync_imported_codex_threads(
                personas=personas,
                sessions=sessions,
            )
            if sync_imported_codex_threads
            else list(self._imported_codex_threads.values())
        )
        bro_threads = self._with_bro_thread_timeline_state(
            _build_bro_thread_projection(
                tasks=tasks,
                sessions=sessions,
                runs=runs,
                summaries=summaries,
                personas=personas,
                imported_threads=imported_threads,
            )
        )
        return SessionSnapshot(
            session_id=self.session_id,
            voice_target_persona_id=self._voice_target_persona_id,
            tasks=tasks,
            execution_sessions=sessions,
            execution_runs=runs,
            execution_modes=execution_modes,
            bindings=bindings,
            summaries=summaries,
            notification_candidates=notification_candidates,
            outbound_turn_requests=outbound_turn_requests,
            bro_threads=bro_threads,
            bro_timeline_turns=_build_bro_timeline_projection(
                tasks=tasks,
                sessions=sessions,
                runs=runs,
                summaries=summaries,
                executor_turns=self._bro_thread_executor_turn_snapshot(),
            ),
            personas=personas,
            interaction_requests=sanitized_interaction_requests,
            attention_items=attention_items,
            agent_events=await self.blackboard.list_agent_events(),
            executor_capabilities=self._executor_capabilities_snapshot(),
            executor_nodes=await self.executor_node_manager.list_nodes(),
            draft_session=self.draft_manager.active_session,
        )

    def _with_bro_thread_timeline_state(self, threads: list[BroThread]) -> list[BroThread]:
        return [
            thread.model_copy(
                update={
                    "timeline_status": self._bro_thread_timeline_status.get(thread.thread_id, "not_loaded"),
                    "timeline_error": self._bro_thread_timeline_errors.get(thread.thread_id),
                }
            )
            for thread in threads
        ]

    def _bro_thread_executor_turn_snapshot(self) -> list[BroTimelineTurn]:
        turns: list[BroTimelineTurn] = []
        for thread_turns in self._bro_thread_executor_turns.values():
            turns.extend(thread_turns)
        return turns

    async def _sync_imported_codex_threads(
        self,
        *,
        personas,
        sessions: list[ExecutionSession],
    ) -> list[BroThread]:
        eligible_personas = [
            persona
            for persona in personas
            if persona.executor_node_id
            and self.executor_node_manager.is_executor_connected("codex", node_id=persona.executor_node_id)
            and self.executor_node_manager.executor_supports_thread_list("codex", node_id=persona.executor_node_id)
        ]
        if not eligible_personas:
            self._imported_codex_threads = {}
            self._imported_codex_thread_resume_handles = {}
            return []

        now = time.monotonic()
        if self._imported_codex_threads and now - self._last_codex_thread_sync_monotonic < 5.0:
            return list(self._imported_codex_threads.values())

        async with self._codex_thread_sync_lock:
            now = time.monotonic()
            if self._imported_codex_threads and now - self._last_codex_thread_sync_monotonic < 5.0:
                return list(self._imported_codex_threads.values())

            existing_codex_thread_ids = {
                session.latest_resume_handle.session_handle
                for session in sessions
                if session.latest_resume_handle is not None
                and session.latest_resume_handle.executor_id == "codex"
                and isinstance(session.latest_resume_handle.session_handle, str)
                and session.latest_resume_handle.session_handle
            }
            personas_by_node: dict[str, list] = {}
            for persona in eligible_personas:
                personas_by_node.setdefault(persona.executor_node_id, []).append(persona)

            imported_threads: dict[str, BroThread] = {}
            imported_resume_handles: dict[str, AgentResumeHandle] = {}
            for node_id, node_personas in personas_by_node.items():
                try:
                    codex_threads = await self.executor_node_manager.request_codex_threads(node_id=node_id)
                except Exception as exc:
                    LOGGER.warning("Failed to import Codex threads from node %s: %s", node_id, exc)
                    continue
                skipped_ephemeral_count = 0
                imported_thread_count = 0
                for codex_thread in codex_threads:
                    if codex_thread.thread_id in existing_codex_thread_ids:
                        continue
                    if _is_ephemeral_codex_thread(codex_thread):
                        skipped_ephemeral_count += 1
                        continue
                    imported_thread_count += 1
                    for persona in node_personas:
                        public_thread_id = self._codex_thread_public_id_aliases.get(
                            _codex_thread_alias_key(persona.persona_id, codex_thread.thread_id)
                        ) or _imported_bro_thread_id(persona.persona_id, codex_thread.thread_id)
                        status = _codex_thread_status(codex_thread.status)
                        thread_title = _title_from_codex_thread(codex_thread)
                        thread_updated_at = _iso_from_epoch_seconds(codex_thread.updated_at or codex_thread.created_at)
                        resume_handle = AgentResumeHandle(
                            executor_id="codex",
                            session_handle=codex_thread.thread_id,
                            opaque={
                                "cwd": codex_thread.cwd or "",
                                "path": codex_thread.path or "",
                                "cliVersion": codex_thread.cli_version or "",
                                "title": thread_title,
                                "listUpdatedAt": thread_updated_at or "",
                            },
                        )
                        diagnostics = {
                            **codex_thread.diagnostics,
                            "codex_thread_id": codex_thread.thread_id,
                            "codex_session_id": codex_thread.session_id,
                            "codex_cwd": codex_thread.cwd,
                            "codex_path": codex_thread.path,
                            "codex_cli_version": codex_thread.cli_version,
                            "codex_thread_source": codex_thread.source,
                            "imported_from_codex_thread_list": True,
                        }
                        imported_threads[public_thread_id] = BroThread(
                            thread_id=public_thread_id,
                            persona_id=persona.persona_id,
                            persona_name=persona.name,
                            executor_id="codex",
                            executor_node_id=node_id,
                            workspace_id=codex_thread.cwd,
                            workspace_name=_workspace_name(codex_thread.cwd),
                            execution_session_id=None,
                            status=status,  # type: ignore[arg-type]
                            title=thread_title,
                            preview=codex_thread.preview,
                            progress=_thread_progress(status),
                            task_ids=[],
                            active_task_id=None,
                            latest_task_id=None,
                            has_resume_handle=True,
                            updated_at=thread_updated_at,
                            diagnostics=diagnostics,
                        )
                        imported_resume_handles[public_thread_id] = resume_handle
                self.observability.logger.emit_event(
                    level="INFO",
                    event_name="runtime.codex_thread_sync",
                    component="runtime.bro_threads",
                    summary="Codex thread import sync",
                    conversation_id=self.session_id,
                    details={
                        "executor_node_id": node_id,
                        "raw_thread_count": len(codex_threads),
                        "imported_thread_count": imported_thread_count,
                        "skipped_ephemeral_count": skipped_ephemeral_count,
                    },
                )
            self._imported_codex_threads = imported_threads
            self._imported_codex_thread_resume_handles = imported_resume_handles
            self._last_codex_thread_sync_monotonic = time.monotonic()
            return list(imported_threads.values())

    async def open_bro_thread(
        self,
        *,
        target_persona_id: str,
        thread_id: str,
    ) -> SessionSnapshot:
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        if not persona.executor_node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        if not self.executor_node_manager.is_executor_connected("codex", node_id=persona.executor_node_id):
            raise ValueError("Selected Bro's Codex executor node is not connected.")

        sessions = await self.blackboard.list_sessions()
        if await self._codex_thread_open_needs_import_sync(persona=persona, target_thread_id=thread_id):
            await self._sync_imported_codex_threads(
                personas=await self.blackboard.list_personas(),
                sessions=sessions,
            )
        resolved_thread_id, thread_continuity_key, selected_session, imported_resume_handle = await self._resolve_bro_thread_target(
            persona=persona,
            target_thread_id=thread_id,
            create_new_thread=False,
        )
        resume_handle = imported_resume_handle or (
            selected_session.latest_resume_handle if selected_session is not None else None
        )
        if (
            resume_handle is None
            or resume_handle.executor_id != "codex"
            or not isinstance(resume_handle.session_handle, str)
            or not resume_handle.session_handle
        ):
            return await self.publish_snapshot(sync_imported_codex_threads=False)

        node_id = selected_session.executor_node_id if selected_session is not None else persona.executor_node_id
        if not node_id:
            raise ValueError("Selected Codex thread is not connected to an executor node.")

        if persona.persona_id not in self._open_bro_thread_locks:
            self._open_bro_thread_locks[persona.persona_id] = asyncio.Lock()
        async with self._open_bro_thread_locks[persona.persona_id]:
            return await self._open_bro_thread_locked(
                persona=persona,
                resolved_thread_id=resolved_thread_id,
                thread_continuity_key=thread_continuity_key,
                resume_handle=resume_handle,
                node_id=node_id,
            )

    async def _open_bro_thread_locked(
        self,
        *,
        persona,
        resolved_thread_id: str,
        thread_continuity_key: str,
        resume_handle,
        node_id: str,
    ) -> "SessionSnapshot":
        imported_thread = self._imported_codex_threads.get(resolved_thread_id)
        current_subscription = self._selected_codex_thread_subscriptions.get(persona.persona_id)
        should_load_timeline = self._should_load_bro_thread_timeline(
            public_thread_id=resolved_thread_id,
            resume_handle=resume_handle,
        )
        if current_subscription is not None:
            same = (
                current_subscription.public_thread_id == resolved_thread_id
                and current_subscription.codex_thread_id == resume_handle.session_handle
                and current_subscription.node_id == node_id
            )
            if same:
                if should_load_timeline:
                    await self._load_bro_thread_timeline(
                        persona=persona,
                        public_thread_id=resolved_thread_id,
                        node_id=node_id,
                        resume_handle=resume_handle,
                    )
                return await self.publish_snapshot(sync_imported_codex_threads=False)
            await self._stop_selected_codex_thread_subscription(persona_id=persona.persona_id, wait=False)

        self._schedule_selected_codex_thread_subscription(
            persona=persona,
            public_thread_id=resolved_thread_id,
            thread_continuity_key=thread_continuity_key,
            node_id=node_id,
            resume_handle=resume_handle,
            fallback_timestamp=imported_thread.updated_at if imported_thread is not None else None,
        )
        if should_load_timeline:
            await self._load_bro_thread_timeline(
                persona=persona,
                public_thread_id=resolved_thread_id,
                node_id=node_id,
                resume_handle=resume_handle,
            )
        return await self.publish_snapshot(sync_imported_codex_threads=False)

    def _should_load_bro_thread_timeline(
        self,
        *,
        public_thread_id: str,
        resume_handle: AgentResumeHandle,
    ) -> bool:
        if not public_thread_id.startswith(IMPORTED_CODEX_THREAD_PREFIX):
            return False
        if public_thread_id in self._bro_thread_executor_turns:
            return False
        if self._bro_thread_timeline_status.get(public_thread_id) == "loaded":
            return False
        return (
            resume_handle.executor_id == "codex"
            and isinstance(resume_handle.session_handle, str)
            and bool(resume_handle.session_handle)
        )

    async def _load_bro_thread_timeline(
        self,
        *,
        persona,
        public_thread_id: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
    ) -> None:
        native_thread_id = resume_handle.session_handle
        if not isinstance(native_thread_id, str) or not native_thread_id:
            return
        self._bro_thread_timeline_status[public_thread_id] = "loading"
        self._bro_thread_timeline_errors.pop(public_thread_id, None)
        await self.publish_snapshot(sync_imported_codex_threads=False)
        try:
            thread = await self.executor_node_manager.request_codex_thread(
                node_id=node_id,
                thread_id=native_thread_id,
            )
        except Exception as exc:
            message = str(exc).strip() or "Codex thread history could not be loaded."
            self._bro_thread_executor_turns.pop(public_thread_id, None)
            self._bro_thread_timeline_status[public_thread_id] = "failed"
            self._bro_thread_timeline_errors[public_thread_id] = message
            LOGGER.warning(
                "Failed to load Codex thread history for %s/%s: %s",
                public_thread_id,
                native_thread_id,
                message,
            )
            return
        thread_goal = _codex_thread_goal(thread)
        if thread_goal:
            self._bro_thread_goals[public_thread_id] = thread_goal
        for turn in _timeline_turns_from_codex_thread(
            thread=thread,
            public_thread_id=public_thread_id,
            executor_thread_id=native_thread_id,
            persona_id=persona.persona_id,
            executor_id="codex",
        ):
            self._upsert_bro_thread_executor_turn(turn)
        self._bro_thread_timeline_status[public_thread_id] = "loaded"
        self._bro_thread_timeline_errors.pop(public_thread_id, None)

    async def _codex_thread_open_needs_import_sync(self, *, persona, target_thread_id: str) -> bool:
        if await self._find_codex_thread_session_for_persona(persona.persona_id, target_thread_id) is not None:
            return False
        imported = self._imported_codex_threads.get(target_thread_id)
        imported_resume_handle = self._imported_codex_thread_resume_handles.get(target_thread_id)
        return not (
            imported is not None
            and imported.persona_id == persona.persona_id
            and imported_resume_handle is not None
        )

    async def close_bro_thread(
        self,
        *,
        target_persona_id: str,
        thread_id: str | None = None,
    ) -> SessionSnapshot:
        await self._stop_selected_codex_thread_subscription(
            persona_id=target_persona_id,
            public_thread_id=thread_id,
        )
        return await self.publish_snapshot(sync_imported_codex_threads=False)

    async def _replace_selected_codex_thread_subscription(
        self,
        *,
        persona,
        public_thread_id: str,
        thread_continuity_key: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
        fallback_timestamp: str | None,
        stop_wait: bool = True,
    ) -> bool:
        codex_thread_id = resume_handle.session_handle
        if not isinstance(codex_thread_id, str) or not codex_thread_id:
            return False
        current = self._selected_codex_thread_subscriptions.get(persona.persona_id)
        if (
            current is not None
            and current.public_thread_id == public_thread_id
            and current.codex_thread_id == codex_thread_id
            and current.node_id == node_id
        ):
            return False
        await self._stop_selected_codex_thread_subscription(
            persona_id=persona.persona_id,
            wait=stop_wait,
            cancel_pending=False,
        )
        subscription_id = f"codex-sub-{uuid4().hex[:12]}"
        workspace_id = None
        cwd = resume_handle.opaque.get("cwd")
        if isinstance(cwd, str) and cwd:
            workspace_id = cwd
        await self.executor_node_manager.subscribe_codex_thread(
            node_id=node_id,
            subscription_id=subscription_id,
            session_id=self.session_id,
            target_persona_id=persona.persona_id,
            target_thread_id=public_thread_id,
            thread_id=codex_thread_id,
            workspace_id=workspace_id,
            timeout_seconds=SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS,
        )
        self._selected_codex_thread_subscriptions[persona.persona_id] = SelectedCodexThreadSubscription(
            subscription_id=subscription_id,
            persona_id=persona.persona_id,
            public_thread_id=public_thread_id,
            thread_continuity_key=thread_continuity_key,
            node_id=node_id,
            codex_thread_id=codex_thread_id,
            resume_handle=resume_handle,
            fallback_timestamp=fallback_timestamp,
        )
        return True

    def _schedule_selected_codex_thread_subscription(
        self,
        *,
        persona,
        public_thread_id: str,
        thread_continuity_key: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
        fallback_timestamp: str | None,
    ) -> None:
        existing = self._selected_codex_thread_subscription_tasks.pop(persona.persona_id, None)
        if existing is not None and not existing.done():
            existing.cancel()

        async def subscribe() -> None:
            try:
                await self._replace_selected_codex_thread_subscription(
                    persona=persona,
                    public_thread_id=public_thread_id,
                    thread_continuity_key=thread_continuity_key,
                    node_id=node_id,
                    resume_handle=resume_handle,
                    fallback_timestamp=fallback_timestamp,
                    stop_wait=False,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning(
                    "Selected Codex thread subscription failed for %s after open: %s",
                    resume_handle.session_handle,
                    exc,
                )
            finally:
                current = self._selected_codex_thread_subscription_tasks.get(persona.persona_id)
                if current is task:
                    self._selected_codex_thread_subscription_tasks.pop(persona.persona_id, None)

        task = asyncio.create_task(subscribe())
        self._selected_codex_thread_subscription_tasks[persona.persona_id] = task

    async def _stop_selected_codex_thread_subscription(
        self,
        *,
        persona_id: str,
        public_thread_id: str | None = None,
        wait: bool = True,
        cancel_pending: bool = True,
    ) -> None:
        if cancel_pending:
            pending = self._selected_codex_thread_subscription_tasks.pop(persona_id, None)
            if pending is not None and not pending.done():
                pending.cancel()
        current = self._selected_codex_thread_subscriptions.get(persona_id)
        if current is None:
            return
        if public_thread_id is not None and current.public_thread_id != public_thread_id:
            return
        self._selected_codex_thread_subscriptions.pop(persona_id, None)

        async def unsubscribe() -> None:
            try:
                response = await self.executor_node_manager.unsubscribe_codex_thread(
                    node_id=current.node_id,
                    subscription_id=current.subscription_id,
                    thread_id=current.codex_thread_id,
                    timeout_seconds=SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS,
                )
                status = response.status if response is not None else "node_unavailable"
            except Exception as exc:
                status = f"error:{exc}"
            LOGGER.info(
                "Stopped selected Codex thread subscription",
                extra={
                    "session_id": self.session_id,
                    "persona_id": persona_id,
                    "public_thread_id": current.public_thread_id,
                    "codex_thread_id": current.codex_thread_id,
                    "unsubscribe_status": status,
                },
            )

        if not wait:
            asyncio.create_task(unsubscribe())
            return
        await unsubscribe()

    async def handle_codex_thread_event(self, message: CodexThreadEventMessage) -> None:
        current = self._selected_codex_thread_subscriptions.get(message.target_persona_id)
        if current is None:
            return
        if (
            current.subscription_id != message.subscription_id
            or current.public_thread_id != message.target_thread_id
            or current.codex_thread_id != message.thread_id
            or current.node_id != message.node_id
        ):
            return
        if message.method not in {
            "turn/completed",
            "item/agentMessage/delta",
            "item/plan/delta",
            "item/completed",
            "thread/goal/updated",
            "thread/goal/cleared",
            "thread/status/changed",
            "thread/closed",
        }:
            return
        if message.method in {
            "item/agentMessage/delta",
            "item/plan/delta",
            "item/completed",
            "thread/goal/updated",
            "thread/goal/cleared",
        }:
            if await self._apply_codex_thread_timeline_event(message, current):
                await self.publish_snapshot(sync_imported_codex_threads=False)
        if message.method == "thread/closed":
            await self._stop_selected_codex_thread_subscription(
                persona_id=current.persona_id,
                public_thread_id=current.public_thread_id,
            )
        return

    async def handle_codex_turn_event(self, message: CodexTurnEventMessage) -> None:
        request = await self.blackboard.get_outbound_turn_request(message.request_id)
        if request is None:
            return
        if (
            request.persona_id != message.target_persona_id
            or request.executor_node_id != message.node_id
            or request.target_thread_id != message.target_thread_id
        ):
            return
        timestamp = datetime.now(tz=UTC).isoformat()
        request_status = _outbound_request_status_from_codex_event(message)
        updated_request = request.model_copy(
            update={
                "status": request_status,
                "error": message.error if not message.ok or request_status == "failed" else None,
                "executor_thread_id": message.executor_thread_id or request.executor_thread_id,
                "executor_turn_id": message.executor_turn_id or request.executor_turn_id,
                "updated_at": timestamp,
            }
        )
        await self.blackboard.put_outbound_turn_request(updated_request)
        await self._attach_outbound_new_thread_resume_handle(updated_request, message)
        self._upsert_bro_thread_executor_turn(
            _bro_timeline_turn_from_codex_turn_event(
                request=updated_request,
                message=message,
                timestamp=timestamp,
            )
        )
        await self.publish_snapshot(sync_imported_codex_threads=False)

    async def _attach_outbound_new_thread_resume_handle(
        self,
        request: OutboundTurnRequest,
        message: CodexTurnEventMessage,
    ) -> None:
        if not request.create_new_thread:
            return
        if not request.target_thread_id or not message.executor_thread_id:
            return
        persona = await self.blackboard.get_persona(request.persona_id)
        if persona is None:
            return
        alias_key = _codex_thread_alias_key(request.persona_id, message.executor_thread_id)
        self._codex_thread_public_id_aliases[alias_key] = request.target_thread_id
        title = _title_from_draft_text(request.text or message.message or "Direct Codex thread")
        resume_handle = AgentResumeHandle(
            executor_id=request.executor_id,
            session_handle=message.executor_thread_id,
            opaque={
                "cwd": request.workspace_id or "",
                "title": title,
                "createdFromOutboundTurnRequest": request.request_id,
            },
        )
        status = _codex_thread_status_from_outbound_request(request.status)
        self._imported_codex_threads[request.target_thread_id] = BroThread(
            thread_id=request.target_thread_id,
            persona_id=request.persona_id,
            persona_name=persona.name,
            executor_id=request.executor_id,
            executor_node_id=request.executor_node_id,
            workspace_id=request.workspace_id,
            workspace_name=_workspace_name(request.workspace_id),
            execution_session_id=None,
            status=status,  # type: ignore[arg-type]
            title=title,
            progress=_thread_progress(status),
            task_ids=[],
            active_task_id=None,
            latest_task_id=None,
            has_resume_handle=True,
            updated_at=request.updated_at,
            diagnostics={
                "codex_thread_id": message.executor_thread_id,
                "codex_cwd": request.workspace_id,
                "created_from_outbound_turn_request": request.request_id,
                "source": "outbound_turn_request",
            },
        )
        self._imported_codex_thread_resume_handles[request.target_thread_id] = resume_handle

    async def _client_request_id_for_selected_thread_turn(
        self,
        *,
        public_thread_id: str,
        executor_thread_id: str,
        executor_turn_id: str,
    ) -> str | None:
        tasks = await self.blackboard.list_tasks()
        task_by_id = {task.task_id: task for task in tasks}
        for run in await self.blackboard.list_runs():
            task = task_by_id.get(run.task_id)
            if task is None or _task_thread_public_id(task) != public_thread_id:
                continue
            source_kind = _task_metadata_string(task, "source_kind")
            if source_kind not in {"bro_detail_text", "bro_detail_ptt"}:
                continue
            run_thread_id = _event_metadata_string(run, "executor_thread_id") or _event_metadata_string(run, "thread_id")
            run_turn_id = _event_metadata_string(run, "executor_turn_id") or _event_metadata_string(run, "turn_id")
            if run_thread_id != executor_thread_id or run_turn_id != executor_turn_id:
                continue
            client_request_id = _task_metadata_string(task, "client_request_id")
            if client_request_id is not None:
                return client_request_id

        direct_candidates: list[tuple[str, str]] = []
        pending_candidates: list[tuple[str, str]] = []
        for task in tasks:
            if _task_thread_public_id(task) != public_thread_id:
                continue
            source_kind = _task_metadata_string(task, "source_kind")
            if source_kind not in {"bro_detail_text", "bro_detail_ptt"}:
                continue
            client_request_id = _task_metadata_string(task, "client_request_id")
            if client_request_id is None:
                continue
            candidate = (_task_updated_at(task) or "", client_request_id)
            direct_candidates.append(candidate)
            if task.status in {
                TaskStatus.CREATED,
                TaskStatus.QUEUED,
                TaskStatus.WAITING_EXECUTOR,
                TaskStatus.RUNNING,
                TaskStatus.WAITING_USER_INPUT,
            }:
                pending_candidates.append(candidate)
        unique_ids = {client_request_id for _, client_request_id in pending_candidates}
        if len(unique_ids) != 1:
            unique_ids = {client_request_id for _, client_request_id in direct_candidates}
            if len(unique_ids) != 1:
                return None
            direct_candidates.sort()
            return direct_candidates[-1][1] if direct_candidates else None
        pending_candidates.sort()
        return pending_candidates[-1][1] if pending_candidates else None

    async def _apply_codex_thread_timeline_event(
        self,
        message: CodexThreadEventMessage,
        subscription: SelectedCodexThreadSubscription,
    ) -> bool:
        params = message.params
        if message.method in {"thread/goal/updated", "thread/goal/cleared"}:
            if message.method == "thread/goal/cleared":
                self._bro_thread_goals.pop(subscription.public_thread_id, None)
            else:
                goal = _codex_thread_goal(params)
                if not goal:
                    goal_value = params.get("goal") or params.get("text") or params.get("objective")
                    goal = goal_value.strip() if isinstance(goal_value, str) and goal_value.strip() else None
                if goal:
                    self._bro_thread_goals[subscription.public_thread_id] = goal
            existing_turns = self._bro_thread_executor_turns.get(subscription.public_thread_id, [])
            updated: list[BroTimelineTurn] = []
            for turn in existing_turns:
                metadata = dict(turn.metadata)
                if message.method == "thread/goal/cleared":
                    metadata.pop("codex_goal", None)
                else:
                    metadata["codex_goal"] = self._bro_thread_goals.get(subscription.public_thread_id)
                updated.append(turn.model_copy(update={"metadata": metadata}))
            if updated:
                self._bro_thread_executor_turns[subscription.public_thread_id] = updated
            return bool(updated)
        turn_id = params.get("turnId") or params.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            return False
        timestamp = _codex_thread_event_timestamp(params)
        client_request_id = await self._client_request_id_for_selected_thread_turn(
            public_thread_id=subscription.public_thread_id,
            executor_thread_id=subscription.codex_thread_id,
            executor_turn_id=turn_id,
        )
        codex_goal = self._bro_thread_goals.get(subscription.public_thread_id)
        item = params.get("item")
        if isinstance(item, dict):
            if item.get("type") == "plan":
                plan = _extract_codex_plan(item)
                if plan is None:
                    return False
                paired_user_message, original_user_turn_id = self._pop_selected_thread_pending_user_turn(
                    public_thread_id=subscription.public_thread_id,
                    executor_thread_id=subscription.codex_thread_id,
                    plan_turn_id=turn_id,
                    plan_timestamp=timestamp,
                )
                self._upsert_bro_thread_executor_turn(
                    BroTimelineTurn(
                        turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                        thread_id=subscription.public_thread_id,
                        persona_id=subscription.persona_id,
                        executor_id="codex",
                        owner="executor",
                        client_request_id=client_request_id,
                        executor_thread_id=subscription.codex_thread_id,
                        executor_turn_id=turn_id,
                        input_modality="text" if paired_user_message is not None else "unknown",
                        user=_mark_timeline_message_plan_mode(paired_user_message),
                        status="running" if message.method == "item/started" else "completed",
                        created_at=paired_user_message.created_at if paired_user_message is not None else timestamp,
                        updated_at=timestamp,
                        metadata={
                            "source": "selected_thread_event",
                            "executor_thread_id": subscription.codex_thread_id,
                            "executor_turn_id": turn_id,
                            "client_request_id": client_request_id,
                            "codex_goal": codex_goal,
                            "codex_plan": plan,
                            "plan_mode": True,
                            "assistant_title": paired_user_message.text if paired_user_message is not None else None,
                            "original_user_executor_turn_id": original_user_turn_id,
                        },
                    )
                )
                return True
            role = _codex_item_role(item)
            text = _extract_codex_item_text(item)
            if role is None or not text:
                return False
            item_id = item.get("id")
            item_id_text = str(item_id) if isinstance(item_id, str) and item_id else "completed"
            status = item.get("status")
            timeline_message = BroTimelineMessage(
                message_id=f"{subscription.public_thread_id}:{turn_id}:{role}",
                role=role,
                kind="text",
                text=text,
                created_at=timestamp,
                status=status if isinstance(status, str) and status else "completed",
                metadata={
                    "executor_turn_id": turn_id,
                    "codex_item_id": item_id_text,
                    "codex_item_type": item.get("type") if isinstance(item.get("type"), str) else None,
                    "source": "selected_thread_event",
                },
            )
            self._upsert_bro_thread_executor_turn(
                BroTimelineTurn(
                    turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                    thread_id=subscription.public_thread_id,
                    persona_id=subscription.persona_id,
                    executor_id="codex",
                    owner="executor",
                    client_request_id=client_request_id,
                    executor_thread_id=subscription.codex_thread_id,
                    executor_turn_id=turn_id,
                    input_modality="text" if role == "user" else "unknown",
                    user=timeline_message if role == "user" else None,
                    assistant=timeline_message if role == "assistant" else None,
                    status="running" if timeline_message.status in {"running", "inProgress"} else "completed",
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "source": "selected_thread_event",
                        "executor_thread_id": subscription.codex_thread_id,
                        "executor_turn_id": turn_id,
                        "client_request_id": client_request_id,
                        "codex_goal": codex_goal,
                    },
                )
            )
            return True
        if message.method == "item/plan/delta":
            item_id = params.get("itemId") or params.get("item_id")
            delta = params.get("delta")
            if not isinstance(item_id, str) or not item_id or not isinstance(delta, str) or not delta:
                return False
            key = (subscription.public_thread_id, turn_id, item_id)
            text = f"{self._bro_thread_live_plan_deltas.get(key, '')}{delta}"
            self._bro_thread_live_plan_deltas[key] = text
            candidate = text.strip()
            previous = self._bro_thread_live_plan_emitted_text.get(key, "")
            if not candidate or not _should_emit_selected_thread_plan_delta(candidate, previous):
                return False
            self._bro_thread_live_plan_emitted_text[key] = candidate
            self._upsert_bro_thread_executor_turn(
                BroTimelineTurn(
                    turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                    thread_id=subscription.public_thread_id,
                    persona_id=subscription.persona_id,
                    executor_id="codex",
                    owner="executor",
                    client_request_id=client_request_id,
                    executor_thread_id=subscription.codex_thread_id,
                    executor_turn_id=turn_id,
                    input_modality="unknown",
                    status="running",
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "source": "selected_thread_event",
                        "executor_thread_id": subscription.codex_thread_id,
                        "executor_turn_id": turn_id,
                        "client_request_id": client_request_id,
                        "codex_goal": codex_goal,
                        "codex_plan": {"text": text, "steps": []},
                        "plan_mode": True,
                    },
                )
            )
            return True
        if message.method != "item/agentMessage/delta":
            return False
        item_id = params.get("itemId") or params.get("item_id")
        delta = params.get("delta")
        if not isinstance(item_id, str) or not item_id or not isinstance(delta, str) or not delta:
            return False
        key = (subscription.public_thread_id, turn_id, item_id)
        text = f"{self._bro_thread_live_message_deltas.get(key, '')}{delta}"
        self._bro_thread_live_message_deltas[key] = text
        self._upsert_bro_thread_executor_turn(
            BroTimelineTurn(
                turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                thread_id=subscription.public_thread_id,
                persona_id=subscription.persona_id,
                executor_id="codex",
                owner="executor",
                client_request_id=client_request_id,
                executor_thread_id=subscription.codex_thread_id,
                executor_turn_id=turn_id,
                input_modality="unknown",
                assistant=BroTimelineMessage(
                    message_id=f"{subscription.public_thread_id}:{turn_id}:assistant",
                    role="assistant",
                    kind="text",
                    text=text,
                    created_at=timestamp,
                    status="running",
                    metadata={
                        "executor_turn_id": turn_id,
                        "codex_item_id": item_id,
                        "codex_item_type": "agentMessage",
                        "source": "selected_thread_event",
                    },
                ),
                status="running",
                created_at=timestamp,
                updated_at=timestamp,
                metadata={
                    "source": "selected_thread_event",
                    "executor_thread_id": subscription.codex_thread_id,
                    "executor_turn_id": turn_id,
                    "client_request_id": client_request_id,
                    "codex_goal": codex_goal,
                },
            )
        )
        return True

    def _pop_selected_thread_pending_user_turn(
        self,
        *,
        public_thread_id: str,
        executor_thread_id: str,
        plan_turn_id: str,
        plan_timestamp: str,
    ) -> tuple[BroTimelineMessage | None, str | None]:
        turns = list(self._bro_thread_executor_turns.get(public_thread_id, []))
        plan_time = DateParseCache.parse(plan_timestamp)
        for index in range(len(turns) - 1, -1, -1):
            candidate = turns[index]
            if candidate.executor_id != "codex":
                continue
            if candidate.executor_thread_id != executor_thread_id:
                continue
            if candidate.executor_turn_id == plan_turn_id:
                continue
            if candidate.user is None or candidate.assistant is not None or candidate.task is not None:
                continue
            if candidate.metadata.get("source") != "selected_thread_event":
                continue
            if candidate.metadata.get("codex_plan") is not None:
                continue
            candidate_time = DateParseCache.parse(candidate.created_at or candidate.updated_at or "")
            if candidate_time > plan_time:
                continue
            turns.pop(index)
            if turns:
                self._bro_thread_executor_turns[public_thread_id] = turns
            else:
                self._bro_thread_executor_turns.pop(public_thread_id, None)
            return candidate.user, candidate.executor_turn_id
        return None, None

    def _upsert_bro_thread_executor_turn(self, turn: BroTimelineTurn) -> None:
        turns = list(self._bro_thread_executor_turns.get(turn.thread_id, []))
        existing_index = next(
            (
                index
                for index, candidate in enumerate(turns)
                if candidate.turn_id == turn.turn_id
                or (
                    candidate.executor_id == turn.executor_id
                    and candidate.executor_thread_id == turn.executor_thread_id
                    and candidate.executor_turn_id == turn.executor_turn_id
                    and turn.executor_turn_id is not None
                )
            ),
            None,
        )
        if existing_index is None:
            turns.append(turn)
        else:
            turns[existing_index] = _merge_timeline_turn(turns[existing_index], turn)
        self._bro_thread_executor_turns[turn.thread_id] = turns
        if self._bro_thread_timeline_status.get(turn.thread_id) != "failed":
            self._bro_thread_timeline_status[turn.thread_id] = "loaded"
            self._bro_thread_timeline_errors.pop(turn.thread_id, None)

    @property
    def voice_target_persona_id(self) -> str | None:
        return self._voice_target_persona_id

    def set_voice_target(self, persona_id: str | None) -> None:
        self._voice_target_persona_id = persona_id

    async def submit_executor_text_instruction(
        self,
        *,
        target_persona_id: str,
        text: str,
        target_thread_id: str | None = None,
        create_new_thread: bool = False,
        workspace_id: str | None = None,
        client_request_id: str | None = None,
        plan_mode: bool = False,
    ) -> ExecutorTextInstruction:
        started_at = time.perf_counter()
        self._record_direct_executor_text_metric(
            step="runtime.received",
            client_request_id=client_request_id,
            target_persona_id=target_persona_id,
            target_thread_id=target_thread_id,
            details={
                "create_new_thread": create_new_thread,
                "workspace_id": workspace_id,
                "text_length": len(text.strip()),
                "plan_mode": plan_mode,
            },
        )
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        if not persona.executor_node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        if not self.executor_node_manager.is_executor_connected(
            "codex",
            node_id=persona.executor_node_id,
        ):
            raise ValueError("Selected Bro's Codex executor node is not connected.")
        if not self.executor_node_manager.executor_supports_follow_up(
                "codex",
                node_id=persona.executor_node_id,
        ):
            raise ValueError("Selected Bro's executor node does not support text follow-up instructions.")
        self._record_direct_executor_text_metric(
            step="runtime.executor_ready",
            client_request_id=client_request_id,
            target_persona_id=persona.persona_id,
            target_thread_id=target_thread_id,
            elapsed_ms=_elapsed_ms(started_at),
            details={"executor_node_id": persona.executor_node_id},
        )

        resolved_workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else workspace_id
        resolve_started_at = time.perf_counter()
        thread_target_id, thread_continuity_key, thread_session, thread_resume_handle = await self._resolve_bro_thread_target(
            persona=persona,
            target_thread_id=target_thread_id,
            create_new_thread=create_new_thread,
            workspace_id=resolved_workspace_id,
        )
        self._record_direct_executor_text_metric(
            step="runtime.thread_resolved",
            client_request_id=client_request_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target_id,
            elapsed_ms=_elapsed_ms(resolve_started_at),
            details={
                "total_elapsed_ms": _elapsed_ms(started_at),
                "thread_continuity_key": thread_continuity_key,
                "resume_mode": thread_session is not None or thread_resume_handle is not None,
            },
        )
        instruction = ExecutorTextInstruction(
            instruction_id=f"txt-{uuid4().hex[:12]}",
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target_id,
            text=text.strip(),
            metadata={
                "source": "bro_detail_text",
                "target_thread_id": thread_target_id,
                "client_request_id": client_request_id,
                "plan_mode": plan_mode,
            },
        )

        lookup_started_at = time.perf_counter()
        execution_session, run = await self._active_codex_execution_for_persona(
            persona.persona_id,
            target_thread_id=thread_target_id,
        )
        self._record_direct_executor_text_metric(
            step="runtime.active_execution_checked",
            client_request_id=client_request_id,
            instruction_id=instruction.instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target_id,
            task_id=run.task_id if run is not None else None,
            run_id=run.run_id if run is not None else None,
            execution_session_id=execution_session.execution_session_id if execution_session is not None else None,
            elapsed_ms=_elapsed_ms(lookup_started_at),
            details={"total_elapsed_ms": _elapsed_ms(started_at)},
        )
        if execution_session is None or run is None:
            request_id = f"out-turn-{uuid4().hex[:12]}"
            requested_at = datetime.now(tz=UTC).isoformat()
            latest_resume_handle: AgentResumeHandle | None = None
            if thread_resume_handle is not None:
                latest_resume_handle = thread_resume_handle
            elif thread_session is not None and thread_session.latest_resume_handle is not None:
                latest_resume_handle = thread_session.latest_resume_handle
            if not create_new_thread and latest_resume_handle is None:
                raise ValueError("Selected Bro has no active Codex execution session.")
            outbound_metadata: dict[str, object] = {
                "source": "bro_detail_text",
                "instruction_id": instruction.instruction_id,
                "thread_continuity_key": thread_continuity_key,
                "thread_mode": "new_thread" if create_new_thread else "resume",
                "resume": not create_new_thread,
                "plan_mode": plan_mode,
            }
            if client_request_id is not None:
                outbound_metadata["client_request_id"] = client_request_id
            if thread_session is not None:
                outbound_metadata["execution_session_id"] = thread_session.execution_session_id
            if latest_resume_handle is not None:
                outbound_metadata["latest_resume_handle"] = latest_resume_handle.model_dump(mode="json")
                if latest_resume_handle.session_handle:
                    outbound_metadata["codex_thread_id"] = latest_resume_handle.session_handle
                cwd = latest_resume_handle.opaque.get("cwd")
                if isinstance(cwd, str) and cwd:
                    outbound_metadata["codex_import_cwd"] = cwd
            if create_new_thread and resolved_workspace_id:
                outbound_metadata["workspace_name"] = _workspace_name(resolved_workspace_id) or resolved_workspace_id
            outbound_request = OutboundTurnRequest(
                request_id=request_id,
                persona_id=persona.persona_id,
                executor_id="codex",
                executor_node_id=persona.executor_node_id,
                target_thread_id=thread_target_id,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                client_request_id=client_request_id,
                input_modality="text",
                text=instruction.text,
                plan_mode=plan_mode,
                status="pending",
                created_at=requested_at,
                updated_at=requested_at,
                metadata=outbound_metadata,
            )
            await self.blackboard.put_outbound_turn_request(outbound_request)
            start_started_at = time.perf_counter()
            started = await self.executor_node_manager.start_codex_turn(
                request_id=request_id,
                node_id=persona.executor_node_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target_id,
                instruction=instruction,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                latest_resume_handle=latest_resume_handle,
                metadata=outbound_metadata,
            )
            self._record_direct_executor_text_metric(
                step="runtime.outbound_turn_started",
                client_request_id=client_request_id,
                instruction_id=instruction.instruction_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target_id,
                elapsed_ms=_elapsed_ms(start_started_at),
                details={
                    "total_elapsed_ms": _elapsed_ms(started_at),
                    "outbound_turn_request_id": request_id,
                    "started": started,
                },
            )
            if not started:
                failed_at = datetime.now(tz=UTC).isoformat()
                await self.blackboard.put_outbound_turn_request(
                    outbound_request.model_copy(
                        update={
                            "status": "failed",
                            "error": "Selected Bro's Codex executor node is not ready for text.",
                            "updated_at": failed_at,
                        }
                    )
                )
                await self.publish_snapshot()
                raise ValueError("Selected Bro's Codex executor node is not ready for text.")
            accepted_at = datetime.now(tz=UTC).isoformat()
            await self.blackboard.put_outbound_turn_request(
                outbound_request.model_copy(update={"status": "accepted", "updated_at": accepted_at})
            )
            publish_started_at = time.perf_counter()
            await self.publish_snapshot()
            self._record_direct_executor_text_metric(
                step="runtime.snapshot_published",
                client_request_id=client_request_id,
                instruction_id=instruction.instruction_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target_id,
                elapsed_ms=_elapsed_ms(publish_started_at),
                details={
                    "total_elapsed_ms": _elapsed_ms(started_at),
                    "outbound_turn_request_id": request_id,
                },
            )
            return instruction

        task = await self.blackboard.get_task(run.task_id)
        if task is not None:
            task.metadata = _mark_direct_executor_input(task.metadata, "bro_detail_text")
            task.metadata["client_request_id"] = client_request_id
            task.metadata["plan_mode"] = plan_mode
            task.metadata["mode"] = TaskMode.PROPOSAL_ONLY.value if plan_mode else TaskMode.MODIFY_ALLOWED.value
            await self.blackboard.put_task(task)

        dispatch_started_at = time.perf_counter()
        dispatched = await self.executor_node_manager.dispatch_text_instruction(
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            executor_type="codex",
            task_id=run.task_id,
            node_id=persona.executor_node_id,
            instruction=instruction,
        )
        self._record_direct_executor_text_metric(
            step="runtime.dispatch_completed",
            client_request_id=client_request_id,
            instruction_id=instruction.instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target_id,
            task_id=run.task_id,
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            elapsed_ms=_elapsed_ms(dispatch_started_at),
            details={
                "total_elapsed_ms": _elapsed_ms(started_at),
                "dispatched": dispatched,
            },
        )
        if not dispatched:
            raise ValueError("Selected Bro's Codex executor node is not ready for text.")
        publish_started_at = time.perf_counter()
        await self.publish_snapshot()
        self._record_direct_executor_text_metric(
            step="runtime.snapshot_published",
            client_request_id=client_request_id,
            instruction_id=instruction.instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target_id,
            task_id=run.task_id,
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            elapsed_ms=_elapsed_ms(publish_started_at),
            details={"total_elapsed_ms": _elapsed_ms(started_at)},
        )
        return instruction

    async def _start_executor_text_task(
        self,
        *,
        persona,
        instruction: ExecutorTextInstruction,
        thread_id: str,
        thread_continuity_key: str,
        selected_execution_session: ExecutionSession | None,
        selected_resume_handle: AgentResumeHandle | None,
        workspace_id: str | None = None,
        source_kind: str = "bro_detail_text",
        created_by: str = "bro_detail_text",
        extra_metadata: dict[str, object] | None = None,
    ) -> Task:
        task_id = f"task-{uuid4().hex[:8]}"
        text = instruction.text.strip()
        created_at = datetime.now(tz=UTC).isoformat()
        metadata = {
            "immutable": True,
            "source_kind": source_kind,
            "assigned_bro_id": persona.persona_id,
            "persona_id": persona.persona_id,
            "persona_name": persona.name,
            "persona_avatar": persona.avatar,
            "bro_detail_session_id": persona.bro_detail_session_id,
            "bro_thread_id": thread_continuity_key,
            "target_thread_id": thread_id,
            "executor_node_id": persona.executor_node_id,
            "instruction_id": instruction.instruction_id,
            "codex_thread_mode": "resume" if selected_execution_session is not None or selected_resume_handle is not None else "start",
            "mode": (
                TaskMode.PROPOSAL_ONLY.value
                if instruction.metadata.get("plan_mode") is True
                else TaskMode.MODIFY_ALLOWED.value
            ),
            "created_at": created_at,
            "updated_at": created_at,
            "suppress_communication_notifications": True,
        }
        if workspace_id:
            metadata["workspace_id"] = workspace_id
            metadata["workspace_name"] = _workspace_name(workspace_id) or workspace_id
        if selected_resume_handle is not None and selected_resume_handle.session_handle:
            metadata["codex_import_thread_id"] = selected_resume_handle.session_handle
            metadata["codex_imported_thread"] = True
            cwd = selected_resume_handle.opaque.get("cwd")
            if isinstance(cwd, str) and cwd:
                metadata["codex_import_cwd"] = cwd
            path = selected_resume_handle.opaque.get("path")
            if isinstance(path, str) and path:
                metadata["codex_import_path"] = path
        if extra_metadata:
            metadata.update(extra_metadata)
        session_affinity = f"ws-{thread_continuity_key}"
        if workspace_id:
            session_affinity = workspace_id
        if selected_resume_handle is not None:
            cwd = selected_resume_handle.opaque.get("cwd")
            if isinstance(cwd, str) and cwd:
                session_affinity = cwd
        task = Task(
            task_id=task_id,
            root_task_id=task_id,
            title=_title_from_draft_text(text),
            goal=text,
            status=TaskStatus.QUEUED,
            preferred_executor="codex",
            session_affinity=session_affinity,
            latest_instruction=text,
            metadata=metadata,
        )
        await self.blackboard.put_persona(
            persona.model_copy(update={"status": "busy"})
        )
        await self.blackboard.put_task(task)
        await self.blackboard.put_execution_mode(
            TaskExecutionMode(task_id=task_id, mode=ExecutionMode.UNDECIDED)
        )
        await self.blackboard.append_mutation(
            TaskMutation(
                mutation_id=f"mut-{uuid4().hex[:8]}",
                task_id=task_id,
                mutation_type=MutationType.CREATE,
                patch={
                    "title": task.title,
                    "goal": task.goal,
                    "preferred_executor": "codex",
                    "persona_id": persona.persona_id,
                    "persona_name": persona.name,
                    "source_kind": source_kind,
                    "instruction_id": instruction.instruction_id,
                },
                created_by=created_by,
            )
        )
        saved = await self.blackboard.get_task(task_id)
        return saved or task

    async def handle_executor_audio_transcript_event(self, run_id: str, metadata: dict[str, object]) -> None:
        audio_id = metadata.get("source_audio_instruction_id")
        transcript = metadata.get("transcript_text")
        if not isinstance(audio_id, str) or not audio_id:
            return
        if not isinstance(transcript, str) or not transcript.strip():
            return
        if metadata.get("source") != "executor_node_whisper":
            return
        run = await self.blackboard.get_run(run_id)
        if run is None:
            return
        task = await self.blackboard.get_task(run.task_id)
        if task is None:
            return
        persona_id = task.metadata.get("persona_id")
        if not isinstance(persona_id, str):
            return
        persona = await self.blackboard.get_persona(persona_id)
        if persona is None:
            return
        created_tasks = task.metadata.get("audio_transcript_task_ids")
        if not isinstance(created_tasks, dict):
            created_tasks = {}
        if audio_id in created_tasks:
            return
        task.metadata["audio_transcript_task_ids"] = {**created_tasks, audio_id: "pending"}
        await self.blackboard.put_task(task)

        target_thread_id = metadata.get("target_thread_id")
        if not isinstance(target_thread_id, str) or not target_thread_id:
            task_thread_id = task.metadata.get("target_thread_id")
            target_thread_id = task_thread_id if isinstance(task_thread_id, str) else None
        thread_target_id, thread_continuity_key, thread_session, thread_resume_handle = await self._resolve_bro_thread_target(
            persona=persona,
            target_thread_id=target_thread_id,
            create_new_thread=False,
        )
        instruction = ExecutorTextInstruction(
            instruction_id=f"txt-{audio_id}",
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target_id,
            text=transcript.strip(),
            source_audio_instruction_id=audio_id,
            metadata={
                "source": "executor_node_whisper",
                "target_thread_id": thread_target_id,
                "source_audio_instruction_id": audio_id,
                "transcript_text": transcript.strip(),
            },
        )
        transcript_task = await self._start_executor_text_task(
            persona=persona,
            instruction=instruction,
            thread_id=thread_target_id,
            thread_continuity_key=thread_continuity_key,
            selected_execution_session=thread_session,
            selected_resume_handle=thread_resume_handle,
            source_kind="bro_detail_ptt",
            created_by="bro_detail_ptt",
            extra_metadata={
                "source_audio_instruction_id": audio_id,
                "direct_executor_input_sources": ["bro_detail_ptt"],
            },
        )
        refreshed = await self.blackboard.get_task(task.task_id)
        if refreshed is not None:
            current_created = refreshed.metadata.get("audio_transcript_task_ids")
            if not isinstance(current_created, dict):
                current_created = {}
            refreshed.metadata["audio_transcript_task_ids"] = {
                **current_created,
                audio_id: transcript_task.task_id,
            }
            await self.blackboard.put_task(refreshed)
        await self.publish_snapshot()

    async def submit_executor_audio_instruction(
        self,
        *,
        target_persona_id: str,
        target_thread_id: str | None = None,
        create_new_thread: bool = False,
        workspace_id: str | None = None,
        client_request_id: str | None = None,
        pcm16: bytes,
        mime_type: str,
        duration_ms: int,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> ExecutorAudioInstruction:
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        if not persona.executor_node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        if not self.executor_node_manager.is_executor_connected(
            "codex",
            node_id=persona.executor_node_id,
        ):
            raise ValueError("Selected Bro's Codex executor node is not connected.")
        if not self.executor_node_manager.executor_supports_audio_instruction(
            "codex",
                node_id=persona.executor_node_id,
        ):
            raise ValueError("Selected Bro's executor node does not support audio transcription instructions.")

        resolved_workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else workspace_id
        thread_target_id, thread_continuity_key, thread_session, thread_resume_handle = await self._resolve_bro_thread_target(
            persona=persona,
            target_thread_id=target_thread_id,
            create_new_thread=create_new_thread,
            workspace_id=resolved_workspace_id,
        )
        audio_instruction_id = f"aud-{uuid4().hex[:12]}"
        audio = ExecutorAudioInstruction(
            audio_instruction_id=audio_instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target_id,
            pcm16_b64=base64.b64encode(pcm16).decode("ascii"),
            mime_type=mime_type,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
            size_bytes=len(pcm16),
            metadata={
                "source": "bro_detail_ptt",
                "target_thread_id": thread_target_id,
                **({"client_request_id": client_request_id} if client_request_id else {}),
            },
        )
        execution_session, run = await self._active_codex_execution_for_persona(
            persona.persona_id,
            target_thread_id=thread_target_id,
        )
        if execution_session is None or run is None:
            try:
                transcription = await self.executor_node_manager.transcribe_audio_instruction(
                    executor_type="codex",
                    node_id=persona.executor_node_id,
                    audio=audio,
                )
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            transcript = (transcription.transcript_text or "").strip()
            if not transcript:
                raise ValueError("Audio transcription produced no instruction text.")
            audio.metadata.update(
                {
                    "source": "executor_node_whisper",
                    "source_audio_instruction_id": audio.audio_instruction_id,
                    "transcript_text": transcript,
                    "transcription_language": transcription.language or "",
                    "transcription_duration_seconds": transcription.duration_seconds or 0,
                    **transcription.metadata,
                }
            )
            instruction = ExecutorTextInstruction(
                instruction_id=f"txt-{audio.audio_instruction_id}",
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target_id,
                text=transcript,
                source_audio_instruction_id=audio.audio_instruction_id,
                metadata={
                    "source": "executor_node_whisper",
                    "target_thread_id": thread_target_id,
                    "source_audio_instruction_id": audio.audio_instruction_id,
                    "transcript_text": transcript,
                    **({"client_request_id": client_request_id} if client_request_id else {}),
                },
            )
            latest_resume_handle: AgentResumeHandle | None = None
            if thread_resume_handle is not None:
                latest_resume_handle = thread_resume_handle
            elif thread_session is not None and thread_session.latest_resume_handle is not None:
                latest_resume_handle = thread_session.latest_resume_handle
            if not create_new_thread and latest_resume_handle is None:
                raise ValueError("Selected Bro has no active Codex execution session.")
            request_id = f"out-turn-{uuid4().hex[:12]}"
            requested_at = datetime.now(tz=UTC).isoformat()
            outbound_metadata: dict[str, object] = {
                "source": "bro_detail_ptt",
                "instruction_id": instruction.instruction_id,
                "source_audio_instruction_id": audio.audio_instruction_id,
                "thread_continuity_key": thread_continuity_key,
                "thread_mode": "new_thread" if create_new_thread else "resume",
                "resume": not create_new_thread,
                "transcript_text": transcript,
            }
            if client_request_id is not None:
                outbound_metadata["client_request_id"] = client_request_id
            if thread_session is not None:
                outbound_metadata["execution_session_id"] = thread_session.execution_session_id
            if latest_resume_handle is not None:
                outbound_metadata["latest_resume_handle"] = latest_resume_handle.model_dump(mode="json")
                if latest_resume_handle.session_handle:
                    outbound_metadata["codex_thread_id"] = latest_resume_handle.session_handle
                cwd = latest_resume_handle.opaque.get("cwd")
                if isinstance(cwd, str) and cwd:
                    outbound_metadata["codex_import_cwd"] = cwd
            if create_new_thread and resolved_workspace_id:
                outbound_metadata["workspace_name"] = _workspace_name(resolved_workspace_id) or resolved_workspace_id
            outbound_request = OutboundTurnRequest(
                request_id=request_id,
                persona_id=persona.persona_id,
                executor_id="codex",
                executor_node_id=persona.executor_node_id,
                target_thread_id=thread_target_id,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                client_request_id=client_request_id,
                input_modality="audio",
                text=instruction.text,
                audio_instruction_id=audio.audio_instruction_id,
                status="pending",
                created_at=requested_at,
                updated_at=requested_at,
                metadata=outbound_metadata,
            )
            await self.blackboard.put_outbound_turn_request(outbound_request)
            started = await self.executor_node_manager.start_codex_turn(
                request_id=request_id,
                node_id=persona.executor_node_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target_id,
                instruction=instruction,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                latest_resume_handle=latest_resume_handle,
                metadata=outbound_metadata,
            )
            if not started:
                failed_at = datetime.now(tz=UTC).isoformat()
                await self.blackboard.put_outbound_turn_request(
                    outbound_request.model_copy(
                        update={
                            "status": "failed",
                            "error": "Selected Bro's Codex executor node is not ready for audio.",
                            "updated_at": failed_at,
                        }
                    )
                )
                await self.publish_snapshot()
                raise ValueError("Selected Bro's Codex executor node is not ready for audio.")
            accepted_at = datetime.now(tz=UTC).isoformat()
            await self.blackboard.put_outbound_turn_request(
                outbound_request.model_copy(update={"status": "accepted", "updated_at": accepted_at})
            )
            await self.publish_snapshot()
            return audio

        task = await self.blackboard.get_task(run.task_id)
        if task is not None:
            task.metadata = _mark_direct_executor_input(task.metadata, "bro_detail_ptt")
            task.metadata["bro_thread_id"] = thread_continuity_key
            task.metadata["target_thread_id"] = thread_target_id
            task.metadata["source_audio_instruction_id"] = audio.audio_instruction_id
            if client_request_id:
                task.metadata["client_request_id"] = client_request_id
            await self.blackboard.put_task(task)
        dispatched = await self.executor_node_manager.dispatch_audio_instruction(
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            executor_type="codex",
            task_id=run.task_id,
            node_id=persona.executor_node_id,
            audio=audio,
        )
        if not dispatched:
            raise ValueError("Selected Bro's Codex executor node is not ready for audio.")
        await self.publish_snapshot()
        return audio

    async def _active_codex_execution_for_persona(
        self,
        persona_id: str,
        *,
        target_thread_id: str | None = None,
    ) -> tuple[ExecutionSession | None, ExecutionRun | None]:
        persona = await self.blackboard.get_persona(persona_id)
        if persona is None:
            return None, None
        if target_thread_id is None:
            return None, None
        for execution_session in await self.blackboard.list_sessions():
            if execution_session.base_executor_id != "codex" or not execution_session.active_run_id:
                continue
            if not _session_matches_thread_id(execution_session, target_thread_id):
                continue
            run = await self.blackboard.get_run(execution_session.active_run_id or "")
            if run is None:
                continue
            if run.executor_type != "codex" or run.status not in AUDIO_ACTIVE_RUN_STATUSES:
                continue
            return execution_session, run
        return None, None

    async def _resolve_bro_thread_target(
        self,
        *,
        persona,
        target_thread_id: str | None,
        create_new_thread: bool,
        workspace_id: str | None = None,
    ) -> tuple[str, str, ExecutionSession | None, AgentResumeHandle | None]:
        if target_thread_id and create_new_thread:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and create a new thread.")
        if target_thread_id and workspace_id:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and choose a new workspace.")

        if create_new_thread:
            await self._validate_new_codex_thread_workspace(persona=persona, workspace_id=workspace_id)
            thread_id = _new_bro_thread_id()
            return thread_id, thread_id, None, None

        if target_thread_id:
            session = await self._find_codex_thread_session_for_persona(
                persona.persona_id,
                target_thread_id,
            )
            if session is not None:
                return _public_thread_id(session), session.continuity_key or session.execution_session_id, session, None
            imported = self._imported_codex_threads.get(target_thread_id)
            imported_resume_handle = self._imported_codex_thread_resume_handles.get(target_thread_id)
            if (
                imported is not None
                and imported.persona_id == persona.persona_id
                and imported_resume_handle is not None
            ):
                return imported.thread_id, imported.thread_id, None, imported_resume_handle
            pending_task = await self._find_direct_task_thread_for_persona(
                persona.persona_id,
                target_thread_id,
            )
            if pending_task is not None:
                continuity_key = _task_metadata_string(pending_task, "bro_thread_id") or target_thread_id
                return target_thread_id, continuity_key, None, None
            raise ValueError("Selected Codex thread is not available for this Bro.")

        raise ValueError("Direct Bro Detail instruction requires explicit thread intent.")

    async def _validate_new_codex_thread_workspace(self, *, persona, workspace_id: str | None) -> None:
        normalized_workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else ""
        if not normalized_workspace_id:
            raise ValueError("New Codex thread requires a workspace selection.")
        known_workspaces = await self._known_codex_workspaces_for_persona(persona)
        if normalized_workspace_id not in known_workspaces:
            raise ValueError("Selected Codex workspace is not available for this Bro.")

    async def _known_codex_workspaces_for_persona(self, persona) -> set[str]:
        workspaces: set[str] = set()
        for imported in self._imported_codex_threads.values():
            if imported.persona_id != persona.persona_id:
                continue
            if imported.executor_node_id != persona.executor_node_id:
                continue
            if imported.workspace_id:
                workspaces.add(imported.workspace_id)
            cwd = imported.diagnostics.get("codex_cwd")
            if isinstance(cwd, str) and cwd.strip():
                workspaces.add(cwd.strip())
        for session in await self.blackboard.list_sessions():
            if session.base_executor_id != "codex":
                continue
            if session.executor_node_id != persona.executor_node_id:
                continue
            if not await self._session_belongs_to_persona(session, persona.persona_id):
                continue
            workspace_id = _workspace_from_resume_handle(session.latest_resume_handle)
            if workspace_id:
                workspaces.add(workspace_id)
        for task in await self.blackboard.list_tasks():
            if not _task_belongs_to_persona(task, persona.persona_id):
                continue
            if task.preferred_executor != "codex":
                continue
            executor_node_id = _task_metadata_string(task, "executor_node_id")
            if executor_node_id and executor_node_id != persona.executor_node_id:
                continue
            workspace_id = _task_workspace_id(task)
            if workspace_id:
                workspaces.add(workspace_id)
        return workspaces

    async def _find_codex_thread_session_for_persona(
        self,
        persona_id: str,
        thread_id: str,
    ) -> ExecutionSession | None:
        for session in reversed(await self.blackboard.list_sessions()):
            if session.base_executor_id != "codex" or not _session_matches_thread_id(session, thread_id):
                continue
            if await self._session_belongs_to_persona(session, persona_id):
                return session
        return None

    async def _find_direct_task_thread_for_persona(self, persona_id: str, thread_id: str) -> Task | None:
        for task in reversed(await self.blackboard.list_tasks()):
            if _task_thread_public_id(task) != thread_id:
                continue
            if _task_belongs_to_persona(task, persona_id):
                return task
        return None

    async def _session_belongs_to_persona(self, session: ExecutionSession, persona_id: str) -> bool:
        task_ids = list(session.run_ids)
        if session.latest_run_id and session.latest_run_id not in task_ids:
            task_ids.append(session.latest_run_id)
        for run_id in task_ids:
            run = await self.blackboard.get_run(run_id)
            if run is None:
                continue
            task = await self.blackboard.get_task(run.task_id)
            if _task_belongs_to_persona(task, persona_id):
                return True
        task = await self.blackboard.get_task(session.task_id)
        if _task_belongs_to_persona(task, persona_id):
            return True
        persona = await self.blackboard.get_persona(persona_id)
        return persona is not None and session.continuity_key == persona.bro_detail_session_id



    async def conversation_snapshot(self) -> ConversationSnapshot:
        history = [
            ConversationHistoryEntryModel(
                role=entry.role,
                text=entry.text,
                message_id=entry.message_id,
                created_at=entry.created_at,
            )
            for entry in self.history.get_recent(self.session_id, limit=50)
        ]
        return ConversationSnapshot(
            session_id=self.session_id,
            conversation_history=history,
        )

    def diagnostic_timeline(
        self,
        *,
        after_sequence: int | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        execution_session_id: str | None = None,
        notification_id: str | None = None,
        request_id: str | None = None,
        event_prefix: str | None = None,
        min_level: str | None = None,
        limit: int = 200,
    ):
        return self.observability.store.query(
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

    def subscribe(self) -> asyncio.Queue[SessionStreamEventBase]:
        queue: asyncio.Queue[SessionStreamEventBase] = asyncio.Queue()
        self.subscribers.append(queue)
        self._ensure_snapshot_pump()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[SessionStreamEventBase]) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)
        if not self.subscribers and self._snapshot_task is not None:
            self._snapshot_task.cancel()

    async def publish_snapshot(self, *, sync_imported_codex_threads: bool = False) -> SessionSnapshot:
        snapshot = await self.snapshot(sync_imported_codex_threads=sync_imported_codex_threads)
        await self._broadcast_event(self._snapshot_event(snapshot))
        return snapshot

    async def initial_snapshot_event(self) -> SnapshotStreamEvent:
        return self._snapshot_event(await self.snapshot(sync_imported_codex_threads=False))

    async def publish_private_event(
        self,
        queue: asyncio.Queue[SessionStreamEventBase],
        event: SessionStreamEventBase,
    ) -> None:
        await queue.put(event)

    async def submit_message(
        self,
        request_id: str,
        user_text: str,
        *,
        source: Literal["user", "connector"] = "user",
        target_persona_id: str | None = None,
        start_processing: bool = True,
    ) -> tuple[str, asyncio.Future[CommunicationTurnResult]]:
        user_entry = self.communication_brain.append_user_message(self.session_id, user_text)
        await self._broadcast_user_message_append(
            message_id=user_entry.message_id,
            text=user_text,
            source=source,
        )
        completion = asyncio.get_running_loop().create_future()
        await self._message_queue.put(
            PendingMessageRequest(
                request_id=request_id,
                user_text=user_text,
                completion=completion,
                target_persona_id=target_persona_id,
            )
        )
        self._wake_notification_pump()
        if start_processing:
            self._ensure_communication_pump()
        return user_entry.message_id, completion

    def start_message_processing(self) -> None:
        self._ensure_communication_pump()

    def start_notification_processing(self) -> None:
        self._ensure_notification_pump()

    def action_accepted_event(
        self,
        request_id: str,
        *,
        action_type: str,
    ) -> ActionAcceptedStreamEvent:
        return ActionAcceptedStreamEvent(
            sequence=self._next_event_sequence(),
            request_id=request_id,
            action_type=action_type,
        )

    def action_rejected_event(
        self,
        request_id: str,
        *,
        action_type: str,
        error_code: str,
        message: str,
    ) -> ActionRejectedStreamEvent:
        return ActionRejectedStreamEvent(
            sequence=self._next_event_sequence(),
            request_id=request_id,
            action_type=action_type,
            error_code=error_code,
            message=message,
        )

    def schedule_execution(self) -> None:
        # Keep one runtime execution loop active; it drains newly queued work
        # after the current executor run releases.
        if self._execution_task is not None and not self._execution_task.done():
            return
        self._execution_task = asyncio.create_task(self._run_execution_loop())

    async def append_asr_turn_to_draft(
        self,
        *,
        raw_text: str,
        normalized_text: str | None = None,
        confidence: float | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        assigned_bro_id: str | None = None,
        on_text_delta=None,
    ):
        return await self.draft_manager.append_asr_turn(
            raw_text=raw_text,
            normalized_text=normalized_text,
            confidence=confidence,
            started_at=started_at,
            ended_at=ended_at,
            assigned_bro_id=assigned_bro_id,
            on_text_delta=on_text_delta,
        )

    async def update_live_transcript_draft(
        self,
        *,
        raw_text: str,
        normalized_text: str | None = None,
        confidence: float | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        assigned_bro_id: str | None = None,
        source_boundary: str,
        transcript_timestamp_ms: int | None = None,
        classification: InteractionClassification | None = None,
        on_text_delta=None,
    ):
        return await self.draft_manager.update_live_draft(
            raw_text=raw_text,
            normalized_text=normalized_text,
            confidence=confidence,
            started_at=started_at,
            ended_at=ended_at,
            assigned_bro_id=assigned_bro_id,
            source_boundary=source_boundary,
            transcript_timestamp_ms=transcript_timestamp_ms,
            classification=classification.model_dump(mode="json") if classification is not None else None,
            on_text_delta=on_text_delta,
        )

    def _live_classifier_due(self, *, text: str, timestamp_ms: int | None) -> bool:
        normalized = " ".join(text.strip().split())
        if not normalized:
            return False
        if normalized == self._latest_live_transcript and self._last_live_classifier_ms is not None:
            return False
        if self._last_live_classifier_ms is None:
            return True
        if timestamp_ms is None:
            return True
        interval_ms = max(0, int(self.live_interaction_classifier_interval_seconds * 1000))
        return timestamp_ms - self._last_live_classifier_ms >= interval_ms

    def _mark_live_classifier_ran(self, *, text: str, timestamp_ms: int | None) -> None:
        self._latest_live_transcript = " ".join(text.strip().split())
        if timestamp_ms is not None:
            self._last_live_classifier_ms = timestamp_ms

    def _live_text_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def _emit_live_stage(
        self,
        *,
        work: LiveTranscriptWork,
        stage: str,
        started_at: float | None = None,
        outcome: str | None = None,
        stale: bool = False,
    ) -> None:
        self.observability.communication.live_draft_stage(
            conversation_id=self.session_id,
            stage=stage,
            source_boundary=work.source_boundary,
            generation=work.generation,
            transcript_timestamp_ms=work.timestamp_ms,
            text_length=len(work.text),
            text_hash=self._live_text_hash(work.text),
            latency_ms=int((time.perf_counter() - started_at) * 1000) if started_at is not None else None,
            outcome=outcome,
            stale=stale,
        )

    def _next_live_work(
        self,
        *,
        text: str,
        language: str | None,
        timestamp_ms: int | None,
        assigned_bro_id: str | None,
        source_boundary: Literal["stt.partial", "stt.final"],
    ) -> LiveTranscriptWork:
        self._live_generation += 1
        return LiveTranscriptWork(
            generation=self._live_generation,
            text=text,
            language=language,
            timestamp_ms=timestamp_ms,
            assigned_bro_id=assigned_bro_id,
            source_boundary=source_boundary,
            scheduled_at=time.perf_counter(),
        )

    def _live_draft_request_id(self, work: LiveTranscriptWork) -> str:
        return f"live-draft-{work.generation}"

    def _should_speak_for_live_draft_decision(
        self,
        *,
        work: LiveTranscriptWork,
        interaction: InteractionType,
        classification: InteractionClassification,
        gate: DispatchGateResult,
        draft_session_id: str | None,
        draft_revision_id: str | None,
    ) -> bool:
        should_speak = _should_speak_for_draft_decision(
            interaction=interaction,
            classification=classification,
            gate=gate,
        )
        if (
            not should_speak
            and interaction == InteractionType.DRAFT_CORRECTION
            and gate.outcome == DispatchGateOutcome.ASK_CONFIRMATION
        ):
            should_speak = True
        if not should_speak:
            return False
        if gate.outcome != DispatchGateOutcome.ASK_CONFIRMATION:
            return True
        if work.source_boundary == "stt.partial":
            return False
        if draft_session_id is not None:
            if self._last_spoken_confirmation_draft_session_id != draft_session_id:
                self._last_spoken_confirmation_draft_session_id = draft_session_id
                self._last_spoken_confirmation_revision_id = draft_revision_id
                return True
            if (
                interaction == InteractionType.DRAFT_CORRECTION
                and draft_revision_id is not None
                and self._last_spoken_confirmation_revision_id != draft_revision_id
            ):
                self._last_spoken_confirmation_revision_id = draft_revision_id
                return True
            if self._last_spoken_confirmation_draft_session_id == draft_session_id:
                return False
        if draft_revision_id is None:
            return True
        return True

    async def _broadcast_live_draft_started(self, work: LiveTranscriptWork) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputStartedStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
            )
        )

    async def _broadcast_live_draft_delta(self, work: LiveTranscriptWork, delta: str) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputDeltaStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
                delta=delta,
            )
        )

    async def _broadcast_live_draft_completed(self, work: LiveTranscriptWork, *, draft_session_id: str, draft_text: str) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputCompletedStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
                draft_session_id=draft_session_id,
                draft_text=draft_text,
            )
        )

    async def _broadcast_live_draft_failed(self, work: LiveTranscriptWork, message: str) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputFailedStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
                message=message,
            )
        )

    def _cancel_live_partial_task(self) -> None:
        if self._live_partial_task is not None and not self._live_partial_task.done():
            if self._live_partial_work is not None:
                self._emit_live_stage(work=self._live_partial_work, stage="cancelled", stale=True)
            self._live_partial_task.cancel()

    def _schedule_live_partial_work(
        self,
        *,
        text: str,
        language: str | None,
        timestamp_ms: int | None,
        assigned_bro_id: str | None,
    ) -> LiveTranscriptWork:
        work = self._next_live_work(
            text=text,
            language=language,
            timestamp_ms=timestamp_ms,
            assigned_bro_id=assigned_bro_id,
            source_boundary="stt.partial",
        )
        self._mark_live_classifier_ran(text=text, timestamp_ms=timestamp_ms)
        self._cancel_live_partial_task()
        self._emit_live_stage(work=work, stage="scheduled")
        self._live_partial_work = work
        self._live_partial_task = asyncio.create_task(self._run_live_partial_work(work))
        return work

    async def _run_live_partial_work(self, work: LiveTranscriptWork) -> None:
        try:
            await self._process_live_transcript_work(work)
        except asyncio.CancelledError:
            self._emit_live_stage(work=work, stage="cancelled", stale=True)
            raise
        except Exception as exc:
            LOGGER.exception("Live partial draft update failed for %s", self.session_id)
            self.observability.communication.reply_failed(
                conversation_id=self.session_id,
                request_id=None,
                reason_code=COMMUNICATION_MODEL_FAILURE,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        finally:
            if asyncio.current_task() is self._live_partial_task:
                self._live_partial_task = None
                self._live_partial_work = None

    async def _process_live_transcript_work(self, work: LiveTranscriptWork) -> RuntimeDecision:
        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        has_draft = self.draft_manager.active_session is not None
        started_at = time.perf_counter()
        self._emit_live_stage(work=work, stage="classifier_started", started_at=work.scheduled_at)
        classification = await self.interaction_classifier.classify(
            text=work.text,
            state=InteractionClassifierState(
                has_draft=has_draft,
                active_task_count=len(active_tasks),
                target_persona_id=work.assigned_bro_id,
                voice_target_persona_id=self._voice_target_persona_id,
                language=work.language,
            ),
        )
        stale = work.generation != self._live_generation
        self._emit_live_stage(
            work=work,
            stage="classifier_completed",
            started_at=started_at,
            outcome=classification.interaction_type.value,
            stale=stale,
        )
        self.observability.communication.interaction_classified(
            conversation_id=self.session_id,
            interaction_type=classification.interaction_type.value,
            confidence=classification.confidence,
            requires_user_decision=classification.requires_user_decision,
            importance=classification.importance,
            reason=classification.reason,
            control_action=classification.control_action,
            task_mode=classification.task_mode.value if classification.task_mode is not None else None,
        )
        if stale:
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=classification.interaction_type,
                session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
            )

        interaction = classification.interaction_type
        if work.source_boundary == "stt.partial" and interaction not in {InteractionType.DELEGATION, InteractionType.DRAFT_CORRECTION}:
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=interaction,
                session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                ui_updates=[
                    UiUpdate(
                        type="transcript.partial",
                        payload={
                            "text": work.text,
                            "classifier_ran": True,
                            "interaction_type": interaction.value,
                            **({"language": work.language} if work.language else {}),
                        },
                    )
                ],
            )
        if interaction == InteractionType.CONFIRMATION:
            return await self.confirm_active_dispatch()
        if classification.control_action == "clear_draft":
            cleared = self.clear_draft()
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=interaction,
                session_state=RuntimeSessionState.IDLE,
                ui_updates=[UiUpdate(type="draft.cleared", payload={"draft_session_id": cleared.id if cleared else ""})],
            )
        if interaction == InteractionType.STATUS_QUERY:
            return await self.runtime_status_decision()
        if interaction == InteractionType.TASK_CONTROL:
            return await self.stop_active_task_decision(reason=work.text)
        if interaction in {InteractionType.DELEGATION, InteractionType.DRAFT_CORRECTION}:
            normalized = " ".join(work.text.strip().split())
            if work.source_boundary == "stt.partial" and normalized == self._latest_published_live_text:
                return RuntimeDecision(
                    should_speak=False,
                    response_text="",
                    interaction_type=interaction,
                    session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                )
            rewrite_started = time.perf_counter()
            self._emit_live_stage(work=work, stage="draft_rewrite_started", started_at=rewrite_started, outcome=interaction.value)
            await self._broadcast_live_draft_started(work)
            try:
                draft_session = await self.update_live_transcript_draft(
                    raw_text=work.text,
                    normalized_text=work.text,
                    assigned_bro_id=work.assigned_bro_id,
                    source_boundary=work.source_boundary,
                    transcript_timestamp_ms=work.timestamp_ms,
                    classification=classification,
                    on_text_delta=(
                        (lambda delta: self._broadcast_live_draft_delta(work, delta))
                        if self.subscribers
                        else None
                    ),
                )
            except Exception as exc:
                await self._broadcast_live_draft_failed(work, str(exc))
                raise
            self._latest_published_live_text = normalized
            draft = draft_session.current_draft
            if draft is None:
                raise ValueError("Draft manager did not produce a draft.")
            if classification.task_mode is not None and draft.task_spec is not None:
                draft.task_spec.mode = classification.task_mode
            plan = build_dispatch_plan(
                runtime_session_id=self.session_id,
                draft_session=draft_session,
                draft=draft,
            )
            draft_session.current_dispatch_plan = plan
            draft.missing_context = list(plan.missing_context)
            self._emit_live_stage(work=work, stage="draft_rewrite_completed", started_at=rewrite_started, outcome=interaction.value)
            await self._broadcast_live_draft_completed(
                work,
                draft_session_id=draft_session.id,
                draft_text=draft.text,
            )
            self.observability.communication.live_draft_updated(
                conversation_id=self.session_id,
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
                draft_revision_number=draft_session.current_revision_number,
                source_boundary=draft_session.live_source_boundary,
                transcript_timestamp_ms=draft_session.live_transcript_timestamp_ms,
                interaction_type=interaction.value,
            )
            gate = dispatch_gate(plan)
            await self.publish_snapshot()
            should_speak = self._should_speak_for_live_draft_decision(
                work=work,
                interaction=interaction,
                classification=classification,
                gate=gate,
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
            )
            return RuntimeDecision(
                should_speak=should_speak,
                response_text=(gate.question or "") if should_speak else "",
                interaction_type=interaction,
                session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
                ui_updates=[
                    *(
                        [
                            UiUpdate(
                                type="transcript.partial",
                                payload={
                                    "text": work.text,
                                    "classifier_ran": True,
                                    "interaction_type": interaction.value,
                                    **({"language": work.language} if work.language else {}),
                                },
                            )
                        ]
                        if work.source_boundary == "stt.partial"
                        else []
                    ),
                    UiUpdate(type="draft_card.updated", payload={"draft_session_id": draft_session.id, "draft_revision_id": draft_session.current_revision_id}),
                    UiUpdate(type="dispatch_plan.updated", payload={"plan_id": plan.plan_id, "draft_revision_id": draft_session.current_revision_id}),
                ],
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            dispatch_plan_id=plan.plan_id,
        )
        return RuntimeDecision(
            should_speak=_should_speak_for_classification(classification),
            response_text=_classification_response_text(classification),
            interaction_type=interaction,
            session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
        )

    async def _reuse_matching_live_draft_for_final(self, work: LiveTranscriptWork) -> RuntimeDecision | None:
        if work.source_boundary != "stt.final":
            return None
        normalized = " ".join(work.text.strip().split())
        if not normalized or normalized != self._latest_published_live_text:
            return None
        draft_session = self.draft_manager.active_session
        if draft_session is None or draft_session.current_draft is None or draft_session.current_revision_id is None:
            return None

        classification = (
            InteractionClassification.model_validate(draft_session.live_classification)
            if draft_session.live_classification is not None
            else None
        )
        draft_session = self.draft_manager.mark_live_checkpoint(
            source_boundary="stt.final",
            transcript_timestamp_ms=work.timestamp_ms,
            classification=draft_session.live_classification,
        )
        if draft_session is None or draft_session.current_draft is None:
            return None
        plan = draft_session.current_dispatch_plan or build_dispatch_plan(
            runtime_session_id=self.session_id,
            draft_session=draft_session,
            draft=draft_session.current_draft,
        )
        draft_session.current_dispatch_plan = plan
        self._emit_live_stage(
            work=work,
            stage="final_checkpoint_reused",
            started_at=work.scheduled_at,
            outcome=(classification.interaction_type.value if classification is not None else InteractionType.DELEGATION.value),
        )
        self.observability.communication.live_draft_updated(
            conversation_id=self.session_id,
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            draft_revision_number=draft_session.current_revision_number,
            source_boundary=draft_session.live_source_boundary,
            transcript_timestamp_ms=draft_session.live_transcript_timestamp_ms,
            interaction_type=(classification.interaction_type.value if classification is not None else InteractionType.DELEGATION.value),
        )
        await self.publish_snapshot()
        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        gate = dispatch_gate(plan)
        effective_classification = classification or InteractionClassification(
            interaction_type=InteractionType.DELEGATION,
            confidence=1.0,
            reason="final_checkpoint_reused",
        )
        interaction = effective_classification.interaction_type
        should_speak = self._should_speak_for_live_draft_decision(
            work=work,
            interaction=interaction,
            classification=effective_classification,
            gate=gate,
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
        )
        return RuntimeDecision(
            should_speak=should_speak,
            response_text=(gate.question or "") if should_speak else "",
            interaction_type=interaction,
            session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
            ui_updates=[
                UiUpdate(type="draft_card.updated", payload={"draft_session_id": draft_session.id, "draft_revision_id": draft_session.current_revision_id}),
                UiUpdate(type="dispatch_plan.updated", payload={"plan_id": plan.plan_id, "draft_revision_id": draft_session.current_revision_id}),
            ],
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            dispatch_plan_id=plan.plan_id,
        )

    async def handle_runtime_message(
        self,
        *,
        text: str,
        message_type: str = "text",
        language: str | None = None,
        timestamp_ms: int | None = None,
        assigned_bro_id: str | None = None,
    ) -> RuntimeDecision:
        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        has_draft = self.draft_manager.active_session is not None
        if message_type == "stt_partial":
            if not self._live_classifier_due(text=text, timestamp_ms=timestamp_ms):
                return RuntimeDecision(
                    should_speak=False,
                    response_text="",
                    interaction_type=InteractionType.COMMUNICATION,
                    session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                    ui_updates=[UiUpdate(type="transcript.partial", payload={"text": text, **({"language": language} if language else {})})],
                )
            work = self._schedule_live_partial_work(
                text=text,
                language=language,
                timestamp_ms=timestamp_ms,
                assigned_bro_id=assigned_bro_id,
            )
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=InteractionType.COMMUNICATION,
                session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                ui_updates=[
                    UiUpdate(
                        type="transcript.partial",
                        payload={
                            "text": text,
                            "classifier_scheduled": True,
                            "generation": work.generation,
                            **({"language": language} if language else {}),
                        },
                    )
                ],
            )
        if message_type == "stt_final":
            self._cancel_live_partial_task()
            work = self._next_live_work(
                text=text,
                language=language,
                timestamp_ms=timestamp_ms,
                assigned_bro_id=assigned_bro_id,
                source_boundary="stt.final",
            )
            self._emit_live_stage(work=work, stage="scheduled")
            reused = await self._reuse_matching_live_draft_for_final(work)
            if reused is not None:
                return reused
            return await self._process_live_transcript_work(work)
        classification = await self.interaction_classifier.classify(
            text=text,
            state=InteractionClassifierState(
                has_draft=has_draft,
                active_task_count=len(active_tasks),
                target_persona_id=assigned_bro_id,
                voice_target_persona_id=self._voice_target_persona_id,
                language=language,
            ),
        )
        self.observability.communication.interaction_classified(
            conversation_id=self.session_id,
            interaction_type=classification.interaction_type.value,
            confidence=classification.confidence,
            requires_user_decision=classification.requires_user_decision,
            importance=classification.importance,
            reason=classification.reason,
            control_action=classification.control_action,
            task_mode=classification.task_mode.value if classification.task_mode is not None else None,
        )
        interaction = classification.interaction_type
        if interaction == InteractionType.CONFIRMATION:
            return await self.confirm_active_dispatch()
        if classification.control_action == "clear_draft":
            cleared = self.clear_draft()
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=interaction,
                session_state=RuntimeSessionState.IDLE,
                ui_updates=[UiUpdate(type="draft.cleared", payload={"draft_session_id": cleared.id if cleared else ""})],
            )
        if interaction == InteractionType.STATUS_QUERY:
            return await self.runtime_status_decision()
        if interaction == InteractionType.TASK_CONTROL:
            return await self.stop_active_task_decision(reason=text)
        if interaction in {InteractionType.DELEGATION, InteractionType.DRAFT_CORRECTION}:
            draft_session = await self.append_asr_turn_to_draft(
                raw_text=text,
                normalized_text=text,
                assigned_bro_id=assigned_bro_id,
            )
            draft = draft_session.current_draft
            if draft is None:
                raise ValueError("Draft manager did not produce a draft.")
            if classification.task_mode is not None and draft.task_spec is not None:
                draft.task_spec.mode = classification.task_mode
            plan = build_dispatch_plan(
                runtime_session_id=self.session_id,
                draft_session=draft_session,
                draft=draft,
            )
            draft_session.current_dispatch_plan = plan
            draft.missing_context = list(plan.missing_context)
            self.observability.communication.live_draft_updated(
                conversation_id=self.session_id,
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
                draft_revision_number=draft_session.current_revision_number,
                source_boundary=draft_session.live_source_boundary,
                transcript_timestamp_ms=draft_session.live_transcript_timestamp_ms,
                interaction_type=interaction.value,
            )
            gate = dispatch_gate(plan)
            await self.publish_snapshot()
            should_speak = _should_speak_for_draft_decision(
                interaction=interaction,
                classification=classification,
                gate=gate,
            )
            return RuntimeDecision(
                should_speak=should_speak,
                response_text=(gate.question or "") if should_speak else "",
                interaction_type=interaction,
                session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
                ui_updates=[
                    UiUpdate(type="draft_card.updated", payload={"draft_session_id": draft_session.id, "draft_revision_id": draft_session.current_revision_id}),
                    UiUpdate(type="dispatch_plan.updated", payload={"plan_id": plan.plan_id, "draft_revision_id": draft_session.current_revision_id}),
                ],
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
                dispatch_plan_id=plan.plan_id,
            )
        return RuntimeDecision(
            should_speak=_should_speak_for_classification(classification),
            response_text=_classification_response_text(classification),
            interaction_type=interaction,
            session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
        )

    async def handle_agora_event(self, event: AgoraVoiceEvent) -> RuntimeDecision:
        if event.session_id != self.session_id:
            raise ValueError("Agora voice event session_id does not match runtime session.")

        target_persona_id = event.target_persona_id or self._voice_target_persona_id
        if event.target_persona_id:
            self.set_voice_target(event.target_persona_id)

        if event.type == AgoraVoiceEventType.STT_PARTIAL:
            return await self.handle_runtime_message(
                text=event.text,
                message_type="stt_partial",
                language=event.language,
                timestamp_ms=event.timestamp_ms,
                assigned_bro_id=target_persona_id,
            )
        if event.type == AgoraVoiceEventType.STT_FINAL:
            return await self.handle_runtime_message(
                text=event.text,
                message_type="stt_final",
                language=event.language,
                timestamp_ms=event.timestamp_ms,
                assigned_bro_id=target_persona_id,
            )

        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        has_draft = self.draft_manager.active_session is not None
        update_type = f"agora.{event.type.value}"
        payload: dict[str, object] = {
            "event_id": event.event_id,
            "session_id": event.session_id,
        }
        if event.timestamp_ms is not None:
            payload["timestamp_ms"] = event.timestamp_ms
        if event.target_persona_id:
            payload["target_persona_id"] = event.target_persona_id
        if event.metadata:
            payload["metadata"] = event.metadata
        return RuntimeDecision(
            should_speak=False,
            response_text="",
            interaction_type=InteractionType.COMMUNICATION,
            session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
            ui_updates=[UiUpdate(type=update_type, payload=payload)],
        )

    def clear_draft(self):
        return self.draft_manager.clear()

    async def confirm_active_dispatch(
        self,
        *,
        plan_id: str | None = None,
        draft_revision_id: str | None = None,
    ) -> RuntimeDecision:
        draft_session = self.draft_manager.active_session
        if draft_session is None or draft_session.current_draft is None:
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=InteractionType.CONFIRMATION,
                session_state=RuntimeSessionState.IDLE,
            )
        plan = draft_session.current_dispatch_plan
        if plan_id is not None and (plan is None or plan.plan_id != plan_id):
            raise ValueError("Dispatch plan does not match the active draft.")
        if draft_revision_id is not None and draft_session.current_revision_id != draft_revision_id:
            raise ValueError("Draft revision does not match the active draft.")
        if plan is None:
            plan = build_dispatch_plan(
                runtime_session_id=self.session_id,
                draft_session=draft_session,
                draft=draft_session.current_draft,
            )
        confirmed = plan.model_copy(update={"user_confirmed": True})
        gate = dispatch_gate(confirmed)
        if gate.outcome != DispatchGateOutcome.DISPATCH:
            draft_session.current_dispatch_plan = confirmed
            return RuntimeDecision(
                should_speak=True,
                response_text=gate.question or "Cannot send yet.",
                interaction_type=InteractionType.CONFIRMATION,
                session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
                dispatch_plan_id=confirmed.plan_id,
            )
        draft_session.current_dispatch_plan = confirmed
        task = await self.send_draft(
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
        )
        await self.publish_snapshot()
        self.schedule_execution()
        return RuntimeDecision(
            should_speak=True,
            response_text=f"Sent to {confirmed.target_agent}.",
            interaction_type=InteractionType.CONFIRMATION,
            session_state=RuntimeSessionState.TASK_RUNNING,
            ui_updates=[
                UiUpdate(type="draft.cleared", payload={"draft_session_id": confirmed.draft_session_id}),
                UiUpdate(type="task.started", payload={"task_id": task.task_id}),
            ],
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            dispatch_plan_id=confirmed.plan_id,
            task_id=task.task_id,
        )

    async def runtime_status_decision(self, *, task_id: str | None = None) -> RuntimeDecision:
        task = await self._resolve_status_task(task_id)
        if task is None:
            return RuntimeDecision(
                should_speak=True,
                response_text="No active task.",
                interaction_type=InteractionType.STATUS_QUERY,
                session_state=RuntimeSessionState.IDLE,
            )
        summary = await self.blackboard.get_summary(task.task_id)
        events = await self.blackboard.list_agent_events(task.task_id)
        latest_event = events[-1] if events else None
        response = (
            (summary.conversational_summary if summary and summary.conversational_summary else None)
            or (latest_event.message if latest_event else None)
            or f"{task.title} is {task.status.value}."
        )
        return RuntimeDecision(
            should_speak=True,
            response_text=response,
            interaction_type=InteractionType.STATUS_QUERY,
            session_state=_state_for_task(task),
            ui_updates=[UiUpdate(type="task.status", payload={"task_id": task.task_id})],
            task_id=task.task_id,
        )

    async def _resolve_status_task(self, task_id: str | None = None) -> Task | None:
        if task_id is not None:
            return await self.blackboard.get_task(task_id)
        tasks = await self.blackboard.list_tasks()
        preferred_statuses = {
            TaskStatus.RUNNING,
            TaskStatus.QUEUED,
            TaskStatus.WAITING_USER_INPUT,
            TaskStatus.PAUSED,
        }
        for task in reversed(tasks):
            if task.status in preferred_statuses:
                return task
        return tasks[-1] if tasks else None

    async def stop_active_task_decision(self, *, task_id: str | None = None, reason: str | None = None) -> RuntimeDecision:
        task = await self._resolve_status_task(task_id)
        if task is None:
            return RuntimeDecision(
                should_speak=True,
                response_text="No active task to stop.",
                interaction_type=InteractionType.TASK_CONTROL,
                session_state=RuntimeSessionState.IDLE,
            )
        command = TaskCommand(
            command_id=f"cmd-{uuid4().hex[:8]}",
            task_id=task.task_id,
            command_type=TaskCommandType.CANCEL_TASK,
            payload={},
            created_by="runtime",
            reason=reason,
        )
        await self.apply_command(command)
        await self.publish_snapshot()
        return RuntimeDecision(
            should_speak=True,
            response_text="Stopped.",
            interaction_type=InteractionType.TASK_CONTROL,
            session_state=RuntimeSessionState.IDLE,
            ui_updates=[UiUpdate(type="task.stopped", payload={"task_id": task.task_id})],
            task_id=task.task_id,
        )

    async def ingest_agent_event(self, event: AgentEvent) -> RuntimeDecision:
        await self.blackboard.put_agent_event(event)
        task = await self.blackboard.get_task(event.task_id)
        if task is not None:
            if event.type in {"agent.blocked", "task.blocked"}:
                task.status = TaskStatus.WAITING_USER_INPUT
                await self.blackboard.put_task(task)
            elif event.type in {"task.completed", "agent.completed"}:
                task.status = TaskStatus.COMPLETED
                await self.blackboard.put_task(task)
        should_speak = event.delivery in {AgentEventDelivery.SHORT_VOICE, AgentEventDelivery.VOICE_INTERRUPT} or event.importance == AgentEventImportance.URGENT
        if event.type in {"agent.blocked", "task.completed", "agent.completed"}:
            should_speak = True
        if event.type in {"agent.progress"} and event.importance == AgentEventImportance.LOW:
            should_speak = False
        if event.type in {"agent.blocked", "task.blocked"}:
            response = event.message
            state = RuntimeSessionState.TASK_BLOCKED
        elif event.type in {"task.completed", "agent.completed"}:
            response = event.message or "Task finished."
            state = RuntimeSessionState.TASK_COMPLETE
        else:
            response = event.message if should_speak else ""
            state = _state_for_task(task) if task is not None else RuntimeSessionState.IDLE
        await self.publish_snapshot()
        return RuntimeDecision(
            should_speak=should_speak,
            response_text=response,
            interaction_type=InteractionType.COMMUNICATION,
            session_state=state,
            ui_updates=[UiUpdate(type="agent_event.ingested", payload={"event_id": event.event_id, "task_id": event.task_id})],
            task_id=event.task_id,
        )

    async def send_draft(
        self,
        *,
        draft_session_id: str | None = None,
        draft_revision_id: str | None = None,
    ) -> Task:
        draft_session = self.draft_manager.active_session
        if draft_session is None or draft_session.current_draft is None or not draft_session.snapshots:
            raise ValueError("No draft is ready to send.")
        if draft_session_id is not None and draft_session.id != draft_session_id:
            raise ValueError("Draft session does not match the active draft.")
        if draft_revision_id is not None and draft_session.current_revision_id != draft_revision_id:
            raise ValueError("Draft revision does not match the active draft.")

        draft = draft_session.current_draft
        snapshot = draft_session.snapshots[-1]
        task_id = f"task-{uuid4().hex[:8]}"
        assigned_bro_id = draft_session.assigned_bro_id
        personas = await self.blackboard.list_personas()
        persona = await self.blackboard.get_persona(assigned_bro_id) if assigned_bro_id else None
        if persona is None and personas and assigned_bro_id and assigned_bro_id != DEFAULT_BRO_ID:
            raise ValueError(f"Bro '{assigned_bro_id}' is not available.")
        if persona is not None and persona.status == "busy":
            raise ValueError(f"{persona.name} is busy with another task right now.")

        available_executor_types = set(self.registry.list_executor_types())
        preferred_executor = await self._resolve_draft_preferred_executor(
            persona=persona,
            available_executor_types=available_executor_types,
        )
        session_affinity = (
            f"ws-{persona.bro_detail_session_id}"
            if persona is not None
            else create_workspace(task_id)
        )
        metadata = {
            "immutable": True,
            "source_kind": "draft_session",
            "draft_session_id": draft_session.id,
            "draft_snapshot_id": snapshot.id,
            "draft_revision_id": draft_session.current_revision_id,
            "draft_revision_number": draft_session.current_revision_number,
            "asr_turn_ids": [turn.id for turn in draft_session.asr_turns],
            "assigned_bro_id": assigned_bro_id,
            "draft_text": draft.text,
            "task_spec": draft.task_spec.model_dump(mode="json") if draft.task_spec is not None else {},
            "dispatch_plan": draft_session.current_dispatch_plan.model_dump(mode="json") if draft_session.current_dispatch_plan is not None else {},
            "mode": (draft.task_spec.mode.value if draft.task_spec is not None else TaskMode.READ_ONLY_FIRST.value),
            "expected_output": draft.task_spec.expected_output if draft.task_spec is not None else "",
            "constraints": draft.task_spec.constraints if draft.task_spec is not None else [],
            "success_criteria": draft.task_spec.success_criteria if draft.task_spec is not None else [],
            "stop_conditions": draft.task_spec.stop_conditions if draft.task_spec is not None else [],
            "mock_safe": preferred_executor == "mock",
        }
        if persona is not None:
            metadata["persona_id"] = persona.persona_id
            metadata["persona_name"] = persona.name
            metadata["persona_avatar"] = persona.avatar
            metadata["bro_detail_session_id"] = persona.bro_detail_session_id
            if persona.executor_node_id:
                metadata["executor_node_id"] = persona.executor_node_id
        task = Task(
            task_id=task_id,
            root_task_id=task_id,
            title=_title_from_draft_text(draft.text),
            goal=draft.task_spec.goal if draft.task_spec is not None else draft.text,
            status=TaskStatus.QUEUED,
            preferred_executor=preferred_executor,
            session_affinity=session_affinity,
            latest_instruction=_task_instruction_from_draft(draft),
            metadata=metadata,
        )
        if persona is not None:
            await self.blackboard.put_persona(
                persona.model_copy(update={"status": "busy"})
            )
        self.draft_manager.mark_sent(draft_session_id, draft_revision_id=draft_revision_id)
        await self.blackboard.put_task(task)
        await self.blackboard.put_execution_mode(
            TaskExecutionMode(task_id=task_id, mode=ExecutionMode.UNDECIDED)
        )
        await self.blackboard.append_mutation(
            TaskMutation(
                mutation_id=f"mut-{uuid4().hex[:8]}",
                task_id=task_id,
                mutation_type=MutationType.CREATE,
                patch={
                    "title": task.title,
                    "goal": task.goal,
                    "preferred_executor": preferred_executor,
                    "persona_id": persona.persona_id if persona else None,
                    "persona_name": persona.name if persona else None,
                    "source_kind": "draft_session",
                    "draft_session_id": draft_session.id,
                    "draft_snapshot_id": snapshot.id,
                    "draft_revision_id": draft_session.current_revision_id,
                },
                created_by="draft_brain",
            )
        )
        saved = await self.blackboard.get_task(task_id)
        return saved or task

    async def _resolve_draft_preferred_executor(
        self,
        *,
        persona,
        available_executor_types: set[str],
    ) -> str | None:
        if persona is not None and persona.executor_node_id:
            for node in await self.executor_node_manager.list_nodes():
                if node.node_id != persona.executor_node_id:
                    continue
                for executor_type in node.enabled_executors:
                    if executor_type in available_executor_types:
                        return executor_type
                break
        preferred_executor = self.default_executor_type
        if preferred_executor not in available_executor_types:
            preferred_executor = "mock" if "mock" in available_executor_types else None
        return preferred_executor

    async def validate_task_command(self, task: Task, command_type: TaskCommandType) -> str | None:
        if command_type not in {TaskCommandType.PAUSE_TASK, TaskCommandType.PREEMPT_TASK}:
            if command_type == TaskCommandType.RESUME_TASK:
                if task.status == TaskStatus.WAITING_USER_INPUT:
                    return (
                        "This task is waiting for user input. Resolve the pending interaction request "
                        "instead of using resume."
                    )
                if task.status != TaskStatus.PAUSED:
                    return "Only paused tasks can be resumed."
            return None
        if task.status in {TaskStatus.CREATED, TaskStatus.QUEUED}:
            return None
        run, executor_type = await self._resolve_task_command_target(task)
        if run is None and executor_type is None:
            return "Task is not actively running."
        if executor_type is None:
            return "Task executor could not be determined."
        try:
            executor = self.registry.get(executor_type)
        except UnknownExecutorError:
            return f"Executor '{executor_type}' is not available."
        if not executor.get_capabilities().supports_pause:
            return f"Executor '{executor_type}' does not support pause."
        return None

    async def apply_command(self, command: TaskCommand) -> list[str]:
        task = await self.blackboard.get_task(command.task_id)
        if task is None:
            return []
        validation_error = await self.validate_task_command(task, command.command_type)
        if validation_error is not None:
            raise ValueError(validation_error)

        await self.blackboard.append_command(command)

        binding = await self.blackboard.get_binding(task.task_id)
        execution_session = None
        if binding is not None and binding.execution_session_id is not None:
            execution_session = await self.blackboard.get_session(binding.execution_session_id)
        run = await self._select_command_run(execution_session)

        if command.command_type in {TaskCommandType.PAUSE_TASK, TaskCommandType.PREEMPT_TASK}:
            await self._capture_pause_resume_handle(execution_session, run)
            task.status = TaskStatus.PAUSED
            await self._pause_live_run(run)
            if run is not None:
                run.status = RunStatus.PAUSED
                await self.blackboard.put_run(run)
            if binding is not None:
                await self.blackboard.put_binding(
                    binding.model_copy(
                        update={
                            "claimed_by": None,
                            "claim_expires_at": None,
                            "binding_status": BindingStatus.PAUSED,
                        }
                    )
                )
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Paused: {task.title}",
                    conversational_summary=f"I paused {task.title}.",
                    latest_user_visible_status="paused",
                    needs_user_input=False,
                )
            )
            await self.interaction_manager.add_task_signal_attention(
                task=task,
                kind=AttentionItemKind.TASK_PAUSED,
                body=f"{task.title} is paused.",
            )
        elif command.command_type == TaskCommandType.CANCEL_TASK:
            task.status = TaskStatus.CANCELLED
            await self._cancel_live_run(run)
            if run is not None:
                run.status = RunStatus.CANCELLED
                await self.blackboard.put_run(run)
            if execution_session is not None and execution_session.active_run_id == (
                run.run_id if run is not None else None
            ):
                execution_session.active_run_id = None
                await self.blackboard.put_session(execution_session)
            if binding is not None:
                await self.blackboard.put_binding(
                    binding.model_copy(
                        update={
                            "claimed_by": None,
                            "claim_expires_at": None,
                            "binding_status": BindingStatus.RELEASED,
                        }
                    )
                )
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Cancelled: {task.title}",
                    conversational_summary=f"I won't continue with {task.title}.",
                    latest_user_visible_status="cancelled",
                    needs_user_input=False,
                )
            )
            await self._suppress_pending_notifications(task.task_id)
            await self.interaction_manager.cancel_requests_for_task(task.task_id)
        elif command.command_type in {TaskCommandType.RESUME_TASK, TaskCommandType.RETRY_TASK}:
            task.status = TaskStatus.QUEUED
            if execution_session is not None and run is not None and execution_session.active_run_id == run.run_id:
                execution_session.active_run_id = None
                await self.blackboard.put_session(execution_session)
            if binding is not None:
                await self.blackboard.put_binding(
                    binding.model_copy(
                        update={
                            "claimed_by": None,
                            "claim_expires_at": None,
                            "binding_status": BindingStatus.RELEASED,
                        }
                    )
                )
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Queued: {task.title}",
                    conversational_summary=f"I queued {task.title} again.",
                    latest_user_visible_status="queued",
                    needs_user_input=False,
                )
            )
            if command.command_type == TaskCommandType.RESUME_TASK:
                await self.interaction_manager.add_task_signal_attention(
                    task=task,
                    kind=AttentionItemKind.TASK_RESUMED,
                    body=f"{task.title} is queued to continue.",
                )

        await self.blackboard.put_task(task)
        return [task.task_id]

    async def resolve_interaction_request(
        self,
        request_id: str,
        *,
        action: str,
        answer_text: str | None = None,
        option_id: str | None = None,
        answers: dict[str, list[str]] | None = None,
        reason: str | None = None,
        client_request_id: str | None = None,
        user_visible_text: str | None = None,
    ) -> list[str]:
        resolution = await self.interaction_manager.resolve_request(
            request_id,
            action=action,
            answer_text=answer_text,
            option_id=option_id,
            answers=answers,
            reason=reason,
        )
        native_resolved = await self._respond_to_native_interaction_request(
            resolution.request,
            action=action,
            answer_text=resolution.answer_text,
            answers=resolution.answers,
        )
        if native_resolved:
            await self.blackboard.put_interaction_request(
                resolution.request.model_copy(update={"resume_strategy": "native_response"})
            )
            return [resolution.request.task_id]
        task = await self.blackboard.get_task(resolution.request.task_id)
        if task is None:
            raise KeyError(f"Task '{resolution.request.task_id}' not found.")

        await self._detach_follow_up_live_session(resolution.request)
        if resolution.request.kind == InteractionRequestKind.PLAN_PROPOSAL:
            if action == "approve":
                task.metadata.pop("plan_mode", None)
                task.metadata["mode"] = TaskMode.MODIFY_ALLOWED.value
                visible_text = (
                    (user_visible_text or "").strip()
                    or _selected_plan_option_label(resolution.request)
                    or PLAN_APPROVAL_VISIBLE_TEXT
                )
                if client_request_id:
                    task.metadata["client_request_id"] = client_request_id
                task.metadata["user_visible_text"] = visible_text
                task.metadata["source_kind"] = "bro_detail_plan_approval"
            elif action == "deny":
                task.metadata["plan_mode"] = True
                task.metadata["mode"] = TaskMode.PROPOSAL_ONLY.value
        task.latest_instruction = self._merge_follow_up_instruction(
            task.latest_instruction,
            resolution.follow_up_instruction,
        )
        task.status = TaskStatus.QUEUED

        binding = await self.blackboard.get_binding(task.task_id)
        execution_session = None
        if binding is not None and binding.execution_session_id is not None:
            execution_session = await self.blackboard.get_session(binding.execution_session_id)
        if execution_session is not None and resolution.request.run_id is not None:
            if execution_session.active_run_id == resolution.request.run_id:
                execution_session.active_run_id = None
                await self.blackboard.put_session(execution_session)
        if binding is not None:
            await self.blackboard.put_binding(
                binding.model_copy(
                    update={
                        "claimed_by": None,
                        "claim_expires_at": None,
                        "binding_status": BindingStatus.RELEASED,
                    }
                )
            )
        await self.blackboard.put_summary(
            TaskSummary(
                task_id=task.task_id,
                operational_summary=f"Queued: {task.title}",
                conversational_summary=f"I queued {task.title} again.",
                latest_user_visible_status="queued",
                needs_user_input=False,
            )
        )
        await self.blackboard.put_task(task)
        return [task.task_id]

    async def requeue_waiting_executor_tasks(self) -> list[str]:
        changed_task_ids: list[str] = []
        for task in await self.blackboard.list_tasks():
            preferred_executor = task.preferred_executor
            if task.status != TaskStatus.WAITING_EXECUTOR:
                continue
            if not isinstance(preferred_executor, str):
                continue
            executor_node_id = task.metadata.get("executor_node_id")
            if executor_node_id is not None and not isinstance(executor_node_id, str):
                executor_node_id = None
            availability = self.executor_node_manager.executor_availability(
                preferred_executor,
                node_id=executor_node_id,
            )
            if not availability["connected"]:
                continue
            task.status = TaskStatus.QUEUED
            await self.blackboard.put_task(task)
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Queued: {task.title}",
                    conversational_summary=f"I queued {task.title} again.",
                    latest_user_visible_status="queued",
                    needs_user_input=False,
                )
            )
            changed_task_ids.append(task.task_id)
        return changed_task_ids

    async def _select_command_run(
        self,
        execution_session: ExecutionSession | None,
    ) -> ExecutionRun | None:
        if execution_session is None:
            return None
        candidate_run_ids = []
        if execution_session.active_run_id:
            candidate_run_ids.append(execution_session.active_run_id)
        if execution_session.latest_run_id and execution_session.latest_run_id not in candidate_run_ids:
            candidate_run_ids.append(execution_session.latest_run_id)
        for run_id in candidate_run_ids:
            run = await self.blackboard.get_run(run_id)
            if run is not None and run.status in {
                RunStatus.CREATED,
                RunStatus.ASSIGNED,
                RunStatus.RUNNING,
                RunStatus.BLOCKED,
                RunStatus.PAUSED,
            }:
                return run
        return None

    async def _cancel_live_run(self, run) -> None:
        if run is None:
            return
        try:
            executor = self.registry.get(run.executor_type)
        except UnknownExecutorError:
            return
        if not executor.get_capabilities().supports_cancel:
            return
        try:
            await executor.cancel_run(run.run_id)
        except Exception:
            return

    async def _pause_live_run(self, run) -> None:
        if run is None:
            return
        try:
            executor = self.registry.get(run.executor_type)
        except UnknownExecutorError:
            return
        if not executor.get_capabilities().supports_pause:
            return
        try:
            await executor.pause_run(run.run_id)
        except Exception:
            return

    async def _capture_pause_resume_handle(
        self,
        execution_session: ExecutionSession | None,
        run: ExecutionRun | None,
    ) -> None:
        if execution_session is None or run is None:
            return
        try:
            executor = self.registry.get(run.executor_type)
        except UnknownExecutorError:
            return
        if not executor.get_capabilities().supports_resume:
            return
        live_session = self.execution_brain.get_live_session(execution_session.execution_session_id)
        if live_session is None:
            return
        resume_handle = None
        if isinstance(live_session, CodexExecutorSession) and live_session.thread_id:
            resume_handle = AgentResumeHandle(
                executor_id="codex",
                session_handle=live_session.thread_id,
            )
        serialized_resume_handle = live_session.metadata.get("latest_resume_handle")
        if resume_handle is None and isinstance(serialized_resume_handle, dict):
            try:
                resume_handle = AgentResumeHandle.model_validate(serialized_resume_handle)
            except Exception:
                resume_handle = None
        elif resume_handle is None and hasattr(executor, "build_resume_handle"):
            try:
                resume_handle = executor.build_resume_handle(live_session)
            except Exception:
                resume_handle = None
        if resume_handle is None:
            return
        execution_session.latest_resume_handle = resume_handle
        await self.blackboard.put_session(execution_session)

    async def _respond_to_native_interaction_request(
        self,
        request: InteractionRequest,
        *,
        action: str,
        answer_text: str | None,
        answers: dict[str, list[str]] | None = None,
    ) -> bool:
        execution_session_id = request.execution_session_id
        executor_node_id: str | None = None
        if isinstance(execution_session_id, str) and execution_session_id:
            execution_session = await self.blackboard.get_session(execution_session_id)
            if execution_session is not None and isinstance(execution_session.executor_node_id, str):
                executor_node_id = execution_session.executor_node_id
        if await self.executor_node_manager.supply_interaction_response(
            request,
            action=action,
            answer_text=answer_text,
            answers=answers,
            node_id=executor_node_id,
        ):
            return True
        native_response = request.opaque.get("native_response")
        if not isinstance(native_response, dict):
            return False
        method = native_response.get("method")
        params = native_response.get("params")
        request_id = native_response.get("request_id")
        if not isinstance(method, str) or not isinstance(params, dict):
            return False
        if not isinstance(execution_session_id, str) or not execution_session_id:
            return False
        live_session = self.execution_brain.get_live_session(execution_session_id)
        if not isinstance(live_session, CodexExecutorSession):
            return False
        if request_id is None:
            return False
        try:
            await live_session.client.respond_to_request(
                request_id=request_id,
                method=method,
                params=params,
                action=action,
                answer_text=answer_text,
                answers=answers,
            )
        except Exception:
            LOGGER.warning(
                "Failed to send native interaction response for %s in session %s.",
                request.request_id,
                execution_session_id,
                exc_info=True,
            )
            return False
        live_session.mark_blocked_resolved()
        return True

    async def _detach_follow_up_live_session(self, request: InteractionRequest) -> None:
        execution_session_id = request.execution_session_id
        if not isinstance(execution_session_id, str) or not execution_session_id:
            return
        live_session = self.execution_brain.get_live_session(execution_session_id)
        if not isinstance(live_session, CodexExecutorSession):
            return
        execution_session = await self.blackboard.get_session(execution_session_id)
        run = (
            await self.blackboard.get_run(request.run_id)
            if isinstance(request.run_id, str) and request.run_id
            else None
        )
        await self._capture_pause_resume_handle(execution_session, run)
        try:
            await live_session.close()
        except Exception:
            LOGGER.warning(
                "Failed to close blocked Codex session %s while preparing follow-up run.",
                execution_session_id,
                exc_info=True,
            )
        finally:
            self.execution_brain.drop_live_session(execution_session_id)

    async def _suppress_pending_notifications(self, task_id: str) -> None:
        candidates = await self.blackboard.list_notification_candidates()
        for candidate in candidates:
            if (
                candidate.task_id == task_id
                and candidate.delivery_status == NotificationDeliveryStatus.PENDING
            ):
                await self.blackboard.put_notification_candidate(
                    candidate.model_copy(
                        update={"delivery_status": NotificationDeliveryStatus.SUPPRESSED}
                    )
                )

    async def _resolve_task_command_target(
        self,
        task: Task,
    ) -> tuple[ExecutionRun | None, str | None]:
        execution_session = None
        for session in await self.blackboard.list_sessions():
            if session.task_id == task.task_id:
                execution_session = session
                break
        run = None
        if execution_session is not None:
            candidate_run_ids = []
            if execution_session.active_run_id:
                candidate_run_ids.append(execution_session.active_run_id)
            if (
                execution_session.latest_run_id
                and execution_session.latest_run_id not in candidate_run_ids
            ):
                candidate_run_ids.append(execution_session.latest_run_id)
            for run_id in candidate_run_ids:
                run = await self.blackboard.get_run(run_id)
                if run is not None and run.status in {
                    RunStatus.CREATED,
                    RunStatus.ASSIGNED,
                    RunStatus.RUNNING,
                    RunStatus.BLOCKED,
                    RunStatus.PAUSED,
                }:
                    return run, run.executor_type
        executor_type = task.preferred_executor
        return run, executor_type

    def _executor_capabilities_snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "executor_type": capability.executor_type,
                "supports_pause": capability.supports_pause,
                "supports_cancel": capability.supports_cancel,
                "supports_resume": capability.supports_resume,
                "supports_follow_up": capability.supports_follow_up,
                "supports_audio_instruction": capability.supports_audio_instruction,
                "supports_thread_list": capability.supports_thread_list,
                **self.executor_node_manager.executor_availability(capability.executor_type),
            }
            for capability in self.registry.list_capabilities()
        ]

    def _merge_follow_up_instruction(
        self,
        existing: str | None,
        follow_up: str,
    ) -> str:
        if existing and existing.strip():
            merged = f"{existing.strip()}\n\nFollow-up:\n{follow_up}"
        else:
            merged = follow_up
        if len(merged) <= MAX_TASK_INSTRUCTION_CHARS:
            return merged
        marker = "[Earlier instructions truncated]\n\n"
        suffix = f"\n\nFollow-up:\n{follow_up}"
        available = MAX_TASK_INSTRUCTION_CHARS - len(marker) - len(suffix)
        if available <= 0:
            return merged[-MAX_TASK_INSTRUCTION_CHARS:]
        preserved_existing = (existing or "").strip()[-available:].lstrip()
        return f"{marker}{preserved_existing}{suffix}"

    async def _run_execution_loop(self) -> None:
        with bind_diagnostic_context(conversation_id=self.session_id):
            while await self._has_runnable_tasks():
                await self.execution_brain.tick()

    async def _has_runnable_tasks(self) -> bool:
        tasks = await self.blackboard.list_tasks()
        return any(task.status in {TaskStatus.CREATED, TaskStatus.QUEUED} for task in tasks)

    def _ensure_communication_pump(self) -> None:
        if self._communication_task is not None and not self._communication_task.done():
            return
        self._communication_task = asyncio.create_task(self._communication_loop())

    def _ensure_snapshot_pump(self) -> None:
        if self._snapshot_task is not None and not self._snapshot_task.done():
            return
        self._blackboard_queue = self.blackboard.subscribe()
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())

    def _ensure_notification_pump(self) -> None:
        if self._notification_task is not None and not self._notification_task.done():
            return
        self._notification_blackboard_queue = self.blackboard.subscribe()
        self._notification_task = asyncio.create_task(self._notification_loop())

    def _ensure_diagnostic_pump(self) -> None:
        if self._diagnostic_task is not None and not self._diagnostic_task.done():
            return
        self._diagnostic_blackboard_queue = self.blackboard.subscribe()
        self._diagnostic_task = asyncio.create_task(self._diagnostic_loop())

    def _wake_notification_pump(self) -> None:
        self._ensure_notification_pump()
        self._notification_wakeup.set()

    async def _communication_loop(self) -> None:
        try:
            while True:
                request = await self._message_queue.get()
                try:
                    await self._handle_message_request(request)
                finally:
                    self._message_queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            if asyncio.current_task() is self._communication_task:
                self._communication_task = None

    async def _handle_message_request(self, request: PendingMessageRequest) -> None:
        self._active_assistant_turns += 1
        self._wake_notification_pump()
        try:
            with bind_diagnostic_context(
                conversation_id=self.session_id,
                request_id=request.request_id,
            ):
                try:
                    await self._broadcast_event(
                        AssistantResponseStartedStreamEvent(
                            sequence=self._next_event_sequence(),
                            request_id=request.request_id,
                        )
                    )
                    if self.subscribers:
                        result = await self.communication_brain.generate_reply(
                            self.session_id,
                            request.user_text,
                            target_persona_id=request.target_persona_id,
                            on_text_delta=lambda delta: self._broadcast_event(
                                AssistantResponseDeltaStreamEvent(
                                    sequence=self._next_event_sequence(),
                                    request_id=request.request_id,
                                    delta=delta,
                                )
                            ),
                            on_trace=lambda trace: self._record_llm_trace(
                                replace(trace, request_id=request.request_id)
                            ),
                            on_tool_call=lambda record: self._record_tool_call(
                                record.with_request_id(request.request_id)
                            ),
                        )
                    else:
                        result = await self.communication_brain.generate_reply(
                            self.session_id,
                            request.user_text,
                            target_persona_id=request.target_persona_id,
                            on_trace=self._record_llm_trace,
                            on_tool_call=self._record_tool_call,
                        )
                except Exception as exc:
                    self.observability.communication.reply_failed(
                        conversation_id=self.session_id,
                        request_id=request.request_id,
                        reason_code=COMMUNICATION_MODEL_FAILURE,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                    assistant_entry = self.history.append_assistant(
                        self.session_id,
                        FALLBACK_ASSISTANT_ERROR_MESSAGE,
                    )
                    result = CommunicationTurnResult(
                        message_id=assistant_entry.message_id,
                        reply_text=FALLBACK_ASSISTANT_ERROR_MESSAGE,
                        conversational_act="model_reply",
                    )
                    await self._broadcast_event(
                        ConversationAppendedStreamEvent(
                            sequence=self._next_event_sequence(),
                            message_id=assistant_entry.message_id,
                            role="assistant",
                            text=FALLBACK_ASSISTANT_ERROR_MESSAGE,
                            source="system_fallback",
                            created_at=assistant_entry.created_at,
                        )
                    )
                    await self._broadcast_event(
                        AssistantResponseFailedStreamEvent(
                            sequence=self._next_event_sequence(),
                            request_id=request.request_id,
                            message=FALLBACK_ASSISTANT_ERROR_MESSAGE,
                        )
                    )
                else:
                    await self._broadcast_event(
                        AssistantResponseCompletedStreamEvent(
                            sequence=self._next_event_sequence(),
                            request_id=request.request_id,
                            message_id=result.message_id,
                            reply_text=result.reply_text,
                            conversational_act=result.conversational_act,
                            affected_task_ids=result.affected_task_ids,
                            created_at=self._conversation_message_created_at(result.message_id),
                        )
                    )
                await self.publish_snapshot()
                self.schedule_execution()
                if not request.completion.done():
                    request.completion.set_result(result)
        finally:
            self._active_assistant_turns = max(0, self._active_assistant_turns - 1)
            self._wake_notification_pump()

    async def _snapshot_loop(self) -> None:
        queue = self._blackboard_queue
        if queue is None:
            return
        try:
            while True:
                await queue.get()
                while True:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                await self.publish_snapshot()
        except asyncio.CancelledError:
            raise
        finally:
            self.blackboard.unsubscribe(queue)
            if self._blackboard_queue is queue:
                self._blackboard_queue = None
            if asyncio.current_task() is self._snapshot_task:
                self._snapshot_task = None

    async def _notification_loop(self) -> None:
        queue = self._notification_blackboard_queue
        if queue is None:
            return
        try:
            while True:
                with bind_diagnostic_context(conversation_id=self.session_id):
                    result = await self.notification_manager.process_pending(
                        assistant_busy=self._active_assistant_turns > 0,
                        has_pending_user_messages=not self._message_queue.empty(),
                    )
                queue_task = asyncio.create_task(queue.get())
                wake_task = asyncio.create_task(self._notification_wakeup.wait())
                task_kinds: dict[asyncio.Task, str] = {
                    queue_task: "queue",
                    wake_task: "wake",
                }
                if result.next_due_seconds is not None:
                    timer_task = asyncio.create_task(asyncio.sleep(result.next_due_seconds))
                    task_kinds[timer_task] = "timer"

                done, pending = await asyncio.wait(
                    task_kinds.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                blackboard_events = []
                for task in done:
                    kind = task_kinds[task]
                    if kind == "wake":
                        self._notification_wakeup.clear()
                    elif kind == "queue":
                        blackboard_events.append(task.result())
                while True:
                    try:
                        blackboard_events.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                for event in blackboard_events:
                    with bind_diagnostic_context(conversation_id=self.session_id):
                        await self.interaction_manager.handle_blackboard_write(event)
                        await self.notification_manager.handle_blackboard_write(event)
        except asyncio.CancelledError:
            raise
        finally:
            self.blackboard.unsubscribe(queue)
            if self._notification_blackboard_queue is queue:
                self._notification_blackboard_queue = None
            if asyncio.current_task() is self._notification_task:
                self._notification_task = None

    async def _diagnostic_loop(self) -> None:
        queue = self._diagnostic_blackboard_queue
        if queue is None:
            return
        try:
            while True:
                event = await queue.get()
                with bind_diagnostic_context(conversation_id=self.session_id):
                    key = (event.kind.value, event.entity_id)
                    created = key not in self._diagnostic_seen_entities
                    self._diagnostic_seen_entities.add(key)
                    self.observability.blackboard.record_write(
                        event=event,
                        created=created,
                    )
        except asyncio.CancelledError:
            raise
        finally:
            self.blackboard.unsubscribe(queue)
            if self._diagnostic_blackboard_queue is queue:
                self._diagnostic_blackboard_queue = None
            if asyncio.current_task() is self._diagnostic_task:
                self._diagnostic_task = None

    async def _broadcast_event(self, event: SessionStreamEventBase) -> None:
        for queue in list(self.subscribers):
            await queue.put(event)

    async def _record_llm_trace(self, trace: LlmTraceRecord) -> None:
        self.observability.communication.llm_trace(trace)

    async def _record_tool_call(self, record: ToolCallRecord) -> None:
        self.observability.communication.tool_called(
            **{
                "request_id": record.request_id,
                "tool_name": record.tool_name,
                "status": record.status,
                "args": record.args,
                "result_summary": record.result_summary,
                "result_pre" + "view": getattr(record, "result_pre" + "view"),
                "affected_task_ids": record.affected_task_ids,
                "error_code": record.error.code if record.error is not None else None,
                "error_message": record.error.message if record.error is not None else None,
            },
        )

    async def _broadcast_conversation_append(
        self,
        *,
        message_id: str,
        text: str,
        source: str,
    ) -> None:
        await self._broadcast_event(
            ConversationAppendedStreamEvent(
                sequence=self._next_event_sequence(),
                message_id=message_id,
                role="assistant",
                text=text,
                source="notification" if source == "notification" else "system_fallback",
                created_at=self._conversation_message_created_at(message_id),
            )
        )

    def _conversation_message_created_at(self, message_id: str) -> str:
        for entry in reversed(self.history.get_recent(self.session_id, limit=200)):
            if entry.message_id == message_id:
                return entry.created_at
        return datetime.now(tz=UTC).isoformat()

    async def _broadcast_user_message_append(
        self,
        *,
        message_id: str,
        text: str,
        source: Literal["user", "connector"],
    ) -> None:
        await self._broadcast_event(
            UserMessageAppendedStreamEvent(
                sequence=self._next_event_sequence(),
                message_id=message_id,
                text=text,
                source=source,
                created_at=self._conversation_message_created_at(message_id),
            )
        )

    def _snapshot_event(self, snapshot: SessionSnapshot) -> SnapshotStreamEvent:
        return SnapshotStreamEvent(
            sequence=self._next_event_sequence(),
            snapshot=snapshot,
        )

    def _next_event_sequence(self) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        return sequence


def create_session_runtime(
    session_id: str,
    *,
    model: CommunicationModel,
    settings: Settings,
    executor_node_manager: ExecutorNodeManager | None = None,
    draft_rewriter: DraftRewriter | None = None,
    interaction_classifier: InteractionClassifier | None = None,
) -> SessionRuntime:
    executor_node_manager = executor_node_manager or ExecutorNodeManager(
        detached_executor_types=settings.detached_executor_types,
    )
    blackboard = InMemoryBlackboard()
    history = InMemoryConversationHistory()
    registry = ExecutorRegistry()
    observability = build_session_observability(settings)
    registry.register(MockExecutor())
    if settings.detached_executor_enabled:
        for executor_type in settings.detached_executor_types:
            if executor_type == "codex":
                registry.register(
                    HostedExecutor(
                        executor_type="codex",
                        manager=executor_node_manager,
                        supports_resume=True,
                        supports_follow_up=True,
                        supports_thread_list=True,
                        supports_pause=True,
                    )
                )
            elif executor_type == "acpx":
                registry.register(
                    HostedExecutor(
                        executor_type="acpx",
                        manager=executor_node_manager,
                        supports_resume=True,
                        supports_follow_up=True,
                        supports_thread_list=False,
                        supports_pause=True,
                    )
                )
    elif settings.acpx_executor_enabled:
        registry.register(
            HostedExecutor(
                executor_type="acpx",
                manager=executor_node_manager,
                supports_resume=True,
                supports_follow_up=True,
                supports_thread_list=False,
                supports_pause=True,
            )
        )
    if settings.codex_executor_enabled:
        registry.register(
            HostedExecutor(
                executor_type="codex",
                manager=executor_node_manager,
                supports_resume=True,
                supports_follow_up=True,
                supports_thread_list=True,
                supports_pause=True,
            )
        )
    default_executor_type = (
        settings.detached_executor_types[0]
        if settings.detached_executor_enabled and settings.detached_executor_types
        else "mock"
    )
    # Load user-defined personas from ~/.newbro/personas.yaml into the blackboard.
    tool_registry = build_default_tool_registry(
        blackboard,
        executor_types=registry.list_executor_types(),
        default_executor_type=default_executor_type,
        apply_interaction_request=None,
    )
    communication_brain = CommunicationBrain(
        blackboard,
        model,
        history=history,
        tool_registry=tool_registry,
        executor_capabilities=registry.list_capabilities(),
        default_executor_type=default_executor_type,
        observability=observability.communication,
    )
    execution_brain = ExecutionBrain(
        blackboard,
        registry,
        worker_id=f"worker-{session_id}",
        default_executor_type=default_executor_type,
        observability=observability.execution,
    )
    notification_manager = NotificationManager(
        blackboard,
        communication_brain,
        conversation_id=session_id,
        observability=observability.notification,
    )
    interaction_manager = InteractionManager(blackboard)
    runtime = SessionRuntime(
        session_id=session_id,
        blackboard=blackboard,
        history=history,
        registry=registry,
        communication_brain=communication_brain,
        execution_brain=execution_brain,
        notification_manager=notification_manager,
        interaction_manager=interaction_manager,
        observability=observability,
        executor_node_manager=executor_node_manager,
        interaction_classifier=interaction_classifier or UnavailableInteractionClassifier(),
        live_interaction_classifier_interval_seconds=settings.live_interaction_classifier_interval_seconds,
        default_executor_type=default_executor_type,
        draft_manager=(
            DraftSessionManager(rewriter=draft_rewriter)
            if draft_rewriter is not None
            else DraftSessionManager()
        ),
    )
    control_task_handler = tool_registry.get("control_task").handler
    if hasattr(control_task_handler, "set_apply_callback"):
        control_task_handler.set_apply_callback(runtime.apply_command)
    interaction_request_handler = tool_registry.get("resolve_interaction_request").handler
    if hasattr(interaction_request_handler, "set_apply_callback"):
        interaction_request_handler.set_apply_callback(runtime.resolve_interaction_request)
    communication_brain.set_trace_callback(runtime._record_llm_trace)
    notification_manager.set_conversation_event_callback(runtime._broadcast_conversation_append)
    runtime.start_notification_processing()
    runtime._ensure_diagnostic_pump()
    # Load personas from persistent config into the blackboard.
    for persona in load_personas_from_file():
        blackboard._personas[persona.persona_id] = persona
    return runtime
