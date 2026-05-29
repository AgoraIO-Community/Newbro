from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    WAITING_EXECUTOR = "waiting_executor"
    RUNNING = "running"
    WAITING_USER_INPUT = "waiting_user_input"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"


class RunStatus(StrEnum):
    CREATED = "created"
    ASSIGNED = "assigned"
    WAITING_EXECUTOR = "waiting_executor"
    RUNNING = "running"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionMode(StrEnum):
    UNDECIDED = "undecided"
    LIGHTWEIGHT = "lightweight"
    MANAGED = "managed"


class SessionStatus(StrEnum):
    IDLE = "idle"
    WARM_IDLE = "warm_idle"
    BUSY = "busy"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class MutationType(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    CONTROL = "control"
    ADD_TASK_NOTE = "add_task_note"
    ADD_CONSTRAINT = "add_constraint"


class TaskCommandType(StrEnum):
    PAUSE_TASK = "pause_task"
    CANCEL_TASK = "cancel_task"
    PREEMPT_TASK = "preempt_task"
    RESUME_TASK = "resume_task"
    RETRY_TASK = "retry_task"


class NotificationPriority(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class NotificationCandidateType(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    NEEDS_INPUT = "needs_input"


class NotificationDeliveryStatus(StrEnum):
    PENDING = "pending"
    EMITTED = "emitted"
    SUPPRESSED = "suppressed"


class InteractionRequestKind(StrEnum):
    PERMISSION = "permission"
    QUESTION = "question"
    CONFIRMATION = "confirmation"
    PLAN_PROPOSAL = "plan_proposal"


class InteractionRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    ANSWERED = "answered"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AttentionPriority(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class AttentionItemKind(StrEnum):
    PERMISSION_REQUEST = "permission_request"
    QUESTION_REQUEST = "question_request"
    CONFIRMATION_REQUEST = "confirmation_request"
    PLAN_PROPOSAL_REQUEST = "plan_proposal_request"
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    TASK_BLOCKED = "task_blocked"
    TASK_COMPLETED = "task_completed"


class AttentionItemStatus(StrEnum):
    ACTIVE = "active"
    ACTED = "acted"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class InterruptionType(StrEnum):
    SPEECH_ONLY = "speech_only"
    TASK_UPDATE = "task_update"
    TASK_CONTROL = "task_control"
    TASK_PREEMPT = "task_preempt"


class ConversationEffect(StrEnum):
    STOP_OUTPUT = "stop_output"
    ACK_AND_LISTEN = "ack_and_listen"
    ASK_CLARIFICATION = "ask_clarification"
    ACK_AND_SWITCH = "ack_and_switch"


class InteractionType(StrEnum):
    COMMUNICATION = "communication"
    DELEGATION = "delegation"
    DRAFT_CORRECTION = "draft_correction"
    TASK_CONTROL = "task_control"
    STATUS_QUERY = "status_query"
    CONFIRMATION = "confirmation"
    CLARIFICATION_RESPONSE = "clarification_response"
    UNCERTAIN = "uncertain"


class AgoraVoiceEventType(StrEnum):
    STT_PARTIAL = "stt.partial"
    STT_FINAL = "stt.final"
    USER_SPEECH_STARTED = "user.speech_started"
    USER_SPEECH_ENDED = "user.speech_ended"
    ASSISTANT_SPEECH_STARTED = "assistant.speech_started"
    ASSISTANT_SPEECH_ENDED = "assistant.speech_ended"
    INTERACTION_INTERRUPTED = "interaction.interrupted"
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"


class RuntimeSessionState(StrEnum):
    IDLE = "idle"
    DRAFTING = "drafting"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    TASK_RUNNING = "task_running"
    TASK_BLOCKED = "task_blocked"
    TASK_COMPLETE = "task_complete"
    USER_REVIEWING_ARTIFACT = "user_reviewing_artifact"


class TaskMode(StrEnum):
    READ_ONLY_FIRST = "read_only_first"
    PROPOSAL_ONLY = "proposal_only"
    MODIFY_ALLOWED = "modify_allowed"
    SUBMIT_ALLOWED = "submit_allowed"


class DispatchGateOutcome(StrEnum):
    ASK_CLARIFICATION = "ask_clarification"
    ASK_CONFIRMATION = "ask_confirmation"
    DISPATCH = "dispatch"
    REJECT = "reject"


class AgentEventImportance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class AgentEventDelivery(StrEnum):
    SILENT = "silent"
    SILENT_UI = "silent_ui"
    BADGE = "badge"
    SHORT_VOICE = "short_voice"
    VOICE_INTERRUPT = "voice_interrupt"


class BindingStatus(StrEnum):
    CREATED = "created"
    CLAIMED = "claimed"
    ACTIVE = "active"
    PAUSED = "paused"
    RELEASED = "released"
