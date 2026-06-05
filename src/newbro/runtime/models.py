from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from newbro.protocol import (
    AgentEvent,
    AttentionItem,
    BroThread,
    BroTimelineTurn,
    DraftSession,
    TaskExecutionMode,
    ExecutionRun,
    ExecutionSession,
    ExecutorNodeRecord,
    InteractionRequest,
    NativeReasoningStep,
    NotificationCandidate,
    OutboundTurnRequest,
    Persona,
    SessionBinding,
    Task,
    TaskExecutionDetailEntry,
    TaskSummary,
)


class ConversationHistoryEntryModel(BaseModel):
    role: str
    text: str
    message_id: str
    created_at: str


class CursorPageInfo(BaseModel):
    next_cursor: str | None = None
    previous_cursor: str | None = None
    has_more: bool = False
    status: Literal["not_loaded", "loading", "loaded", "failed"] = "not_loaded"
    error: str | None = None


class BroThreadPageResponse(BaseModel):
    persona_id: str
    threads: list[BroThread] = Field(default_factory=list)
    page: CursorPageInfo = Field(default_factory=CursorPageInfo)


class BroTimelineTurnPageResponse(BaseModel):
    thread_id: str
    thread: BroThread
    turns: list[BroTimelineTurn] = Field(default_factory=list)
    page: CursorPageInfo = Field(default_factory=CursorPageInfo)


class BroExecutorCapabilitySummary(BaseModel):
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
    supports_thread_list: bool = False
    supports_audio_instruction: bool = False


class BroExecutorNodeSummary(BaseModel):
    node_id: str
    name: str
    connection_status: Literal["connected", "disconnected"] = "disconnected"
    enabled_executors: list[str] = Field(default_factory=list)
    codex: BroExecutorCapabilitySummary | None = None


class BroSummary(BaseModel):
    persona_id: str
    name: str
    avatar: str = ""
    status: str = "idle"
    executor_node: BroExecutorNodeSummary | None = None


class BroListResponse(BaseModel):
    bros: list[BroSummary] = Field(default_factory=list)


class BroThreadSubscriptionResponse(BaseModel):
    thread_id: str
    persona_id: str
    subscribed: bool
    timeline_status: Literal["not_loaded", "loading", "loaded", "failed"] = "not_loaded"
    timeline_error: str | None = None


class SessionSnapshot(BaseModel):
    session_id: str
    voice_target_persona_id: str | None = None
    tasks: list[Task] = Field(default_factory=list)
    execution_sessions: list[ExecutionSession] = Field(default_factory=list)
    execution_runs: list[ExecutionRun] = Field(default_factory=list)
    execution_modes: list[TaskExecutionMode] = Field(default_factory=list)
    bindings: list[SessionBinding] = Field(default_factory=list)
    summaries: list[TaskSummary] = Field(default_factory=list)
    notification_candidates: list[NotificationCandidate] = Field(default_factory=list)
    outbound_turn_requests: list[OutboundTurnRequest] = Field(default_factory=list)
    bro_threads: list[BroThread] = Field(default_factory=list)
    bro_timeline_turns: list[BroTimelineTurn] = Field(default_factory=list)
    bro_thread_pages: dict[str, CursorPageInfo] = Field(default_factory=dict)
    bro_timeline_pages: dict[str, CursorPageInfo] = Field(default_factory=dict)
    personas: list[Persona] = Field(default_factory=list)
    interaction_requests: list[InteractionRequest] = Field(default_factory=list)
    attention_items: list[AttentionItem] = Field(default_factory=list)
    agent_events: list[AgentEvent] = Field(default_factory=list)
    executor_capabilities: list[dict[str, object]] = Field(default_factory=list)
    executor_nodes: list[ExecutorNodeRecord] = Field(default_factory=list)
    recent_execution_details: dict[str, list[TaskExecutionDetailEntry]] = Field(default_factory=dict)
    recent_native_turn_reasoning: dict[str, list[NativeReasoningStep]] = Field(default_factory=dict)
    draft_session: DraftSession | None = None
 

class ConversationSnapshot(BaseModel):
    session_id: str
    conversation_history: list[ConversationHistoryEntryModel] = Field(default_factory=list)

class SessionStreamEventBase(BaseModel):
    sequence: int
    type: str


class SnapshotStreamEvent(SessionStreamEventBase):
    type: Literal["snapshot"] = "snapshot"
    snapshot: SessionSnapshot


class ActionAcceptedStreamEvent(SessionStreamEventBase):
    type: Literal["action_accepted"] = "action_accepted"
    request_id: str
    action_type: str


class ActionRejectedStreamEvent(SessionStreamEventBase):
    type: Literal["action_rejected"] = "action_rejected"
    request_id: str
    action_type: str
    error_code: str
    message: str


class UserMessageAppendedStreamEvent(SessionStreamEventBase):
    type: Literal["user_message_appended"] = "user_message_appended"
    message_id: str
    role: Literal["user"] = "user"
    text: str
    source: Literal["user", "connector"]
    created_at: str


class AssistantResponseStartedStreamEvent(SessionStreamEventBase):
    type: Literal["assistant_response_started"] = "assistant_response_started"
    request_id: str


class AssistantResponseDeltaStreamEvent(SessionStreamEventBase):
    type: Literal["assistant_response_delta"] = "assistant_response_delta"
    request_id: str
    delta: str


class AssistantResponseCompletedStreamEvent(SessionStreamEventBase):
    type: Literal["assistant_response_completed"] = "assistant_response_completed"
    request_id: str
    message_id: str
    reply_text: str
    conversational_act: str
    affected_task_ids: list[str] = Field(default_factory=list)
    created_at: str


class AssistantResponseFailedStreamEvent(SessionStreamEventBase):
    type: Literal["assistant_response_failed"] = "assistant_response_failed"
    request_id: str
    message: str


class DraftOutputStartedStreamEvent(SessionStreamEventBase):
    type: Literal["draft_output_started"] = "draft_output_started"
    request_id: str


class DraftOutputDeltaStreamEvent(SessionStreamEventBase):
    type: Literal["draft_output_delta"] = "draft_output_delta"
    request_id: str
    delta: str


class DraftOutputCompletedStreamEvent(SessionStreamEventBase):
    type: Literal["draft_output_completed"] = "draft_output_completed"
    request_id: str
    draft_session_id: str
    draft_text: str


class DraftOutputFailedStreamEvent(SessionStreamEventBase):
    type: Literal["draft_output_failed"] = "draft_output_failed"
    request_id: str
    message: str


class ConversationAppendedStreamEvent(SessionStreamEventBase):
    type: Literal["conversation_appended"] = "conversation_appended"
    message_id: str
    role: Literal["assistant"]
    text: str
    source: Literal["notification", "system_fallback"]
    created_at: str
