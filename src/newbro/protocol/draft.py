from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, Field

from .enums import (
    AgentEventDelivery,
    AgentEventImportance,
    AgoraVoiceEventType,
    DispatchGateOutcome,
    InteractionType,
    RuntimeSessionState,
    TaskMode,
)


class DraftSessionStatus(StrEnum):
    EMPTY = "empty"
    LISTENING = "listening"
    DRAFTING = "drafting"
    READY = "ready"
    SENT = "sent"
    CLEARED = "cleared"


class AsrTurn(BaseModel):
    id: str
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = None
    started_at: str
    ended_at: str


class Draft(BaseModel):
    text: str
    last_update_summary: str = ""
    task_spec: "TaskSpec | None" = None
    missing_context: list[str] = Field(default_factory=list)
    revision_id: str | None = None
    revision_number: int = 0
    updated_at: str | None = None


class DraftSnapshot(BaseModel):
    id: str
    draft: Draft
    source_asr_turn_ids: list[str] = Field(default_factory=list)
    created_at: str
    draft_revision_id: str | None = None
    draft_revision_number: int = 0
    source_boundary: str = "asr_turn"
    transcript_timestamp_ms: int | None = None


class DraftSession(BaseModel):
    id: str
    assigned_bro_id: str
    asr_turns: list[AsrTurn] = Field(default_factory=list)
    current_draft: Draft | None = None
    current_dispatch_plan: "DispatchPlan | None" = None
    runtime_state: RuntimeSessionState = RuntimeSessionState.IDLE
    snapshots: list[DraftSnapshot] = Field(default_factory=list)
    status: DraftSessionStatus = DraftSessionStatus.EMPTY
    current_revision_id: str | None = None
    current_revision_number: int = 0
    live_classification: dict[str, object] | None = None
    live_source_boundary: str | None = None
    live_transcript_timestamp_ms: int | None = None
    created_at: str
    updated_at: str


class TaskSpec(BaseModel):
    title: str
    goal: str
    target_agent: str = "codex"
    mode: TaskMode = TaskMode.READ_ONLY_FIRST
    expected_output: str = "A concise proposal or status summary."
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    context: dict[str, object] = Field(default_factory=dict)
    input_language: str = "en-US"
    output_language: str = "en-US"
    raw_transcript: str | None = None
    normalized_task_language: str = "en-US"
    code_switched: bool = False


class DispatchPlan(BaseModel):
    plan_id: str
    session_id: str
    draft_session_id: str
    draft_revision_id: str | None = None
    draft_revision_number: int = 0
    intent: str = "repo_investigation"
    target_agent: str
    task_title: str
    task_goal: str
    required_context: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    mode: TaskMode = TaskMode.READ_ONLY_FIRST
    risk_level: str = "low"
    confidence: float = 0.9
    requires_user_confirmation: bool = True
    user_confirmed: bool = False
    output_language: str = "en-US"
    task_spec: TaskSpec


class DispatchGateResult(BaseModel):
    outcome: DispatchGateOutcome
    reason: str = ""
    question: str | None = None
    plan_id: str | None = None


class UiUpdate(BaseModel):
    type: str
    payload: dict[str, object] = Field(default_factory=dict)


class RuntimeDecision(BaseModel):
    should_speak: bool = False
    response_text: str = ""
    interaction_type: InteractionType = InteractionType.COMMUNICATION
    session_state: RuntimeSessionState = RuntimeSessionState.IDLE
    ui_updates: list[UiUpdate] = Field(default_factory=list)
    state_updates: list[dict[str, object]] = Field(default_factory=list)
    async_actions: list[dict[str, object]] = Field(default_factory=list)
    draft_session_id: str | None = None
    draft_revision_id: str | None = None
    dispatch_plan_id: str | None = None
    task_id: str | None = None


class AgoraVoiceEvent(BaseModel):
    event_id: str
    session_id: str
    type: AgoraVoiceEventType
    text: str = ""
    language: str | None = None
    timestamp_ms: int | None = None
    target_persona_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    event_id: str
    task_id: str
    agent_id: str = "codex"
    type: str
    message: str
    importance: AgentEventImportance = AgentEventImportance.LOW
    delivery: AgentEventDelivery = AgentEventDelivery.SILENT_UI
    artifact_id: str | None = None
    created_at: str
