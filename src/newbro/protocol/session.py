from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .enums import BindingStatus


class AgentResumeHandle(BaseModel):
    executor_id: str
    session_handle: str | None = None
    turn_handle: str | None = None
    opaque: dict[str, object] = Field(default_factory=dict)


class QueuedRunRequest(BaseModel):
    queued_request_id: str
    task_id: str
    executor_config: dict[str, object] = Field(default_factory=dict)
    latest_instruction: str
    requested_by_message_id: str | None = None


class ExecutionSession(BaseModel):
    execution_session_id: str
    task_id: str
    base_executor_id: str
    executor_node_id: str | None = None
    continuity_key: str | None = None
    run_ids: list[str] = Field(default_factory=list)
    active_run_id: str | None = None
    latest_run_id: str | None = None
    latest_resume_handle: AgentResumeHandle | None = None
    queued_run_request: QueuedRunRequest | None = None


class BroThread(BaseModel):
    thread_id: str
    persona_id: str
    persona_name: str | None = None
    executor_id: str = "codex"
    executor_node_id: str | None = None
    execution_session_id: str | None = None
    status: Literal["pending", "queued", "running", "blocked", "completed", "failed", "cancelled"] = "pending"
    title: str
    preview: str | None = None
    progress: int = 0
    task_ids: list[str] = Field(default_factory=list)
    active_task_id: str | None = None
    latest_task_id: str | None = None
    has_resume_handle: bool = False
    updated_at: str | None = None
    timeline_status: Literal["not_loaded", "loading", "loaded", "failed"] = "not_loaded"
    timeline_error: str | None = None
    diagnostics: dict[str, object] = Field(default_factory=dict)


class BroTimelineMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    kind: Literal["text", "audio"] = "text"
    text: str | None = None
    transcript: str | None = None
    audio_id: str | None = None
    duration_ms: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    status: str = "completed"
    metadata: dict[str, object] = Field(default_factory=dict)


class BroTimelineTask(BaseModel):
    task_id: str
    run_id: str | None = None
    title: str
    status: str
    status_label: str
    progress: int = 0
    description: str | None = None
    summary: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class BroTimelineTurn(BaseModel):
    turn_id: str
    thread_id: str
    persona_id: str
    executor_id: str
    owner: Literal["newbro", "executor"]
    client_request_id: str | None = None
    executor_thread_id: str | None = None
    executor_turn_id: str | None = None
    input_modality: Literal["text", "audio", "unknown"] = "unknown"
    user: BroTimelineMessage | None = None
    assistant: BroTimelineMessage | None = None
    task: BroTimelineTask | None = None
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SessionBinding(BaseModel):
    task_id: str
    execution_session_id: str | None = None
    executor_node_id: str | None = None
    session_id: str | None = None
    claimed_by: str | None = None
    claim_expires_at: str | None = None
    execution_revision: int = 0
    binding_status: BindingStatus = BindingStatus.CREATED
