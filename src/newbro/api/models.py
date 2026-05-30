from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from newbro.observability.schema import DiagnosticEvent
from newbro.protocol import AgoraVoiceEvent, ExecutorNodeCredentialIssue, ExecutorNodeRecord, RuntimeDecision, TaskCommandType
from newbro.runtime.models import SessionSnapshot


class SessionResponse(BaseModel):
    session_id: str


class MessageRequest(BaseModel):
    text: str
    source: Literal["user", "connector"] = "user"
    type: Literal["chat", "text", "stt_partial", "stt_final"] = "chat"
    language: str | None = None
    timestamp_ms: int | None = None
    assigned_bro_id: str | None = None
    target_persona_id: str | None = None


class ToolInvocationSummary(BaseModel):
    tool_name: str
    args: dict[str, object] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    message_id: str
    reply_text: str
    conversational_act: str
    affected_task_ids: list[str] = Field(default_factory=list)
    tool_invocations: list[ToolInvocationSummary] = Field(default_factory=list)


class CommandRequest(BaseModel):
    command_type: TaskCommandType
    task_id: str | None = None
    reference: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    reason: str | None = None


class CommandResponse(BaseModel):
    command_id: str
    status: str = "accepted"
    affected_task_ids: list[str] = Field(default_factory=list)


class ResolveInteractionRequest(BaseModel):
    action: Literal["approve", "deny", "answer", "confirm", "cancel"]
    answer_text: str | None = None
    option_id: str | None = None
    answers: dict[str, list[str]] | None = None
    reason: str | None = None
    client_request_id: str | None = None
    user_visible_text: str | None = None


class ResolveInteractionRequestResponse(BaseModel):
    request_id: str
    status: str = "accepted"
    affected_task_ids: list[str] = Field(default_factory=list)


class SendMessageSocketAction(BaseModel):
    type: Literal["send_message"] = "send_message"
    request_id: str
    text: str
    source: Literal["user", "connector"] = "user"
    target_persona_id: str | None = None


class SendCommandSocketAction(BaseModel):
    type: Literal["send_command"] = "send_command"
    request_id: str
    command_type: TaskCommandType
    task_id: str | None = None
    reference: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    reason: str | None = None


class ResolveInteractionRequestSocketAction(BaseModel):
    type: Literal["resolve_interaction_request"] = "resolve_interaction_request"
    request_id: str
    interaction_request_id: str
    action: Literal["approve", "deny", "answer", "confirm", "cancel"]
    answer_text: str | None = None
    option_id: str | None = None
    answers: dict[str, list[str]] | None = None
    reason: str | None = None
    client_request_id: str | None = None
    user_visible_text: str | None = None


class SubmitAsrTurnSocketAction(BaseModel):
    type: Literal["submit_asr_turn"] = "submit_asr_turn"
    request_id: str
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = None
    started_at: str | None = None
    ended_at: str | None = None
    assigned_bro_id: str | None = None


class SendDraftSocketAction(BaseModel):
    type: Literal["send_draft"] = "send_draft"
    request_id: str
    draft_session_id: str | None = None
    draft_revision_id: str | None = None


class ClearDraftSocketAction(BaseModel):
    type: Literal["clear_draft"] = "clear_draft"
    request_id: str
    draft_session_id: str | None = None


class DiagnosticTimelineResponse(BaseModel):
    events: list[DiagnosticEvent] = Field(default_factory=list)


class PersonaCreateRequest(BaseModel):
    name: str
    avatar: str = ""
    base_prompt: str = ""
    executor_node_id: str | None = None


class PersonaUpdateRequest(BaseModel):
    name: str | None = None
    avatar: str | None = None
    base_prompt: str | None = None
    executor_node_id: str | None = None


class ExecutorNodeCreateRequest(BaseModel):
    name: str
    enabled_executors: list[str] = Field(default_factory=list)
    acpx_agent: str | None = None


class ExecutorNodeUpdateRequest(BaseModel):
    name: str | None = None
    enabled_executors: list[str] | None = None
    acpx_agent: str | None = None


__all__ = [
    "CommandRequest",
    "CommandResponse",
    "AgoraVoiceEvent",
    "ClearDraftSocketAction",
    "DiagnosticTimelineResponse",
    "ExecutorNodeCreateRequest",
    "ExecutorNodeCredentialIssue",
    "ExecutorNodeRecord",
    "ExecutorNodeUpdateRequest",
    "MessageRequest",
    "MessageResponse",
    "RuntimeDecision",
    "ResolveInteractionRequest",
    "ResolveInteractionRequestResponse",
    "ResolveInteractionRequestSocketAction",
    "SendDraftSocketAction",
    "SendCommandSocketAction",
    "SendMessageSocketAction",
    "SubmitAsrTurnSocketAction",
    "SessionResponse",
    "SessionSnapshot",
    "ToolInvocationSummary",
]
