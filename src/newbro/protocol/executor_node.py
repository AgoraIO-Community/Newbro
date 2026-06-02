from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .session import AgentResumeHandle


class ExecutorNodeExecutor(BaseModel):
    executor_type: str
    supports_resume: bool = False
    supports_follow_up: bool = False
    supports_audio_instruction: bool = False
    supports_thread_list: bool = False
    supports_pause: bool = False
    supports_cancel: bool = True


class ExecutorNodeRecord(BaseModel):
    node_id: str
    name: str
    enabled_executors: list[str] = Field(default_factory=list)
    acpx_agent: str | None = None
    connected_executors: list[str] = Field(default_factory=list)
    connection_status: Literal["connected", "disconnected"] = "disconnected"
    token_hint: str | None = None
    last_connected_at: str | None = None
    last_seen_at: str | None = None
    connected_executor_capabilities: list[ExecutorNodeExecutor] = Field(default_factory=list)


class ExecutorNodeCredentialIssue(BaseModel):
    node: ExecutorNodeRecord
    token: str


class RegisterNodeMessage(BaseModel):
    type: Literal["register_node"] = "register_node"
    node_id: str
    token: str
    executors: list[ExecutorNodeExecutor] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class RunEventMessage(BaseModel):
    type: Literal["run_event"] = "run_event"
    run_id: str
    execution_session_id: str
    executor_type: str
    session_id: str
    event_type: Literal[
        "progress",
        "plan",
        "waiting_executor",
        "blocked",
        "completed",
        "failed",
        "cancelled",
    ]
    message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    latest_resume_handle: AgentResumeHandle | None = None


class InteractionStateMessage(BaseModel):
    type: Literal["interaction_state"] = "interaction_state"
    run_id: str
    execution_session_id: str
    executor_type: str
    state: str
    prompt: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class NodeStatusMessage(BaseModel):
    type: Literal["node_status"] = "node_status"
    node_id: str
    status: Literal["ready", "degraded"]
    metadata: dict[str, object] = Field(default_factory=dict)


class CodexThreadListItem(BaseModel):
    thread_id: str
    session_id: str | None = None
    preview: str | None = None
    title: str | None = None
    cwd: str | None = None
    path: str | None = None
    status: str | None = None
    created_at: int | None = None
    updated_at: int | None = None
    cli_version: str | None = None
    source: str | None = None
    diagnostics: dict[str, object] = Field(default_factory=dict)


class ListCodexThreadsCommand(BaseModel):
    type: Literal["list_codex_threads"] = "list_codex_threads"
    request_id: str
    executor_type: Literal["codex"] = "codex"
    workspace_id: str | None = None


class CodexThreadsListedMessage(BaseModel):
    type: Literal["codex_threads_listed"] = "codex_threads_listed"
    request_id: str
    node_id: str
    executor_type: Literal["codex"] = "codex"
    ok: bool = True
    error: str | None = None
    threads: list[CodexThreadListItem] = Field(default_factory=list)


class ReadCodexThreadCommand(BaseModel):
    type: Literal["read_codex_thread"] = "read_codex_thread"
    request_id: str
    executor_type: Literal["codex"] = "codex"
    thread_id: str


class CodexThreadReadMessage(BaseModel):
    type: Literal["codex_thread_read"] = "codex_thread_read"
    request_id: str
    node_id: str
    executor_type: Literal["codex"] = "codex"
    ok: bool = True
    error: str | None = None
    thread: dict[str, object] = Field(default_factory=dict)


class SubscribeCodexThreadCommand(BaseModel):
    type: Literal["subscribe_codex_thread"] = "subscribe_codex_thread"
    request_id: str
    subscription_id: str
    session_id: str
    target_persona_id: str
    target_thread_id: str
    executor_type: Literal["codex"] = "codex"
    thread_id: str
    workspace_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CodexThreadSubscribedMessage(BaseModel):
    type: Literal["codex_thread_subscribed"] = "codex_thread_subscribed"
    request_id: str
    subscription_id: str
    node_id: str
    session_id: str
    target_persona_id: str
    target_thread_id: str
    executor_type: Literal["codex"] = "codex"
    thread_id: str
    ok: bool = True
    error: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class UnsubscribeCodexThreadCommand(BaseModel):
    type: Literal["unsubscribe_codex_thread"] = "unsubscribe_codex_thread"
    request_id: str
    subscription_id: str
    executor_type: Literal["codex"] = "codex"
    thread_id: str


class CodexThreadUnsubscribedMessage(BaseModel):
    type: Literal["codex_thread_unsubscribed"] = "codex_thread_unsubscribed"
    request_id: str
    subscription_id: str
    node_id: str
    executor_type: Literal["codex"] = "codex"
    thread_id: str
    ok: bool = True
    error: str | None = None
    status: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CodexThreadEventMessage(BaseModel):
    type: Literal["codex_thread_event"] = "codex_thread_event"
    subscription_id: str
    node_id: str
    session_id: str
    target_persona_id: str
    target_thread_id: str
    executor_type: Literal["codex"] = "codex"
    thread_id: str
    method: str
    params: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class DispatchRunCommand(BaseModel):
    type: Literal["dispatch_run"] = "dispatch_run"
    run_id: str
    execution_session_id: str
    executor_type: str
    task_id: str
    title: str
    goal: str
    latest_instruction: str | None = None
    workspace_id: str | None = None
    task_metadata: dict[str, object] = Field(default_factory=dict)
    latest_resume_handle: AgentResumeHandle | None = None


class ExecutorAudioInstruction(BaseModel):
    audio_instruction_id: str
    target_persona_id: str
    target_thread_id: str | None = None
    pcm16_b64: str
    mime_type: str
    duration_ms: int
    sample_rate: int
    num_channels: int
    samples_per_channel: int
    size_bytes: int
    metadata: dict[str, object] = Field(default_factory=dict)


class ExecutorTextInstruction(BaseModel):
    instruction_id: str
    target_persona_id: str
    target_thread_id: str | None = None
    text: str
    source_audio_instruction_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class StartCodexTurnCommand(BaseModel):
    type: Literal["start_codex_turn"] = "start_codex_turn"
    request_id: str
    executor_type: Literal["codex"] = "codex"
    target_persona_id: str
    target_thread_id: str
    thread_id: str | None = None
    create_new_thread: bool = False
    workspace_id: str | None = None
    instruction: ExecutorTextInstruction
    latest_resume_handle: AgentResumeHandle | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_thread_intent(self) -> StartCodexTurnCommand:
        has_thread_id = self.thread_id is not None
        has_resume_handle = self.latest_resume_handle is not None
        if self.thread_id is not None and not self.thread_id.strip():
            raise ValueError("start_codex_turn thread_id cannot be empty.")
        if self.create_new_thread:
            if has_thread_id or has_resume_handle:
                raise ValueError("start_codex_turn create_new_thread cannot include existing thread intent.")
            return self
        if has_thread_id == has_resume_handle:
            raise ValueError("start_codex_turn requires exactly one existing thread intent.")
        return self


class CodexTurnEventMessage(BaseModel):
    type: Literal["codex_turn_event"] = "codex_turn_event"
    request_id: str
    node_id: str
    executor_type: Literal["codex"] = "codex"
    target_persona_id: str
    target_thread_id: str
    event_type: str
    message: str | None = None
    executor_thread_id: str | None = None
    executor_turn_id: str | None = None
    ok: bool = True
    error: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DispatchAudioInstructionCommand(BaseModel):
    type: Literal["dispatch_audio_instruction"] = "dispatch_audio_instruction"
    run_id: str
    execution_session_id: str
    executor_type: str
    task_id: str
    audio: ExecutorAudioInstruction


class TranscribeAudioInstructionCommand(BaseModel):
    type: Literal["transcribe_audio_instruction"] = "transcribe_audio_instruction"
    request_id: str
    executor_type: str
    audio: ExecutorAudioInstruction


class AudioInstructionTranscribedMessage(BaseModel):
    type: Literal["audio_instruction_transcribed"] = "audio_instruction_transcribed"
    request_id: str
    node_id: str
    executor_type: str
    ok: bool = True
    error: str | None = None
    transcript_text: str | None = None
    language: str | None = None
    duration_seconds: float | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DispatchTextInstructionCommand(BaseModel):
    type: Literal["dispatch_text_instruction"] = "dispatch_text_instruction"
    run_id: str
    execution_session_id: str
    executor_type: str
    task_id: str
    instruction: ExecutorTextInstruction


class CancelRunCommand(BaseModel):
    type: Literal["cancel_run"] = "cancel_run"
    run_id: str
    execution_session_id: str
    mode: Literal["cancel", "pause"] = "cancel"


class SupplyInteractionResponseCommand(BaseModel):
    type: Literal["supply_interaction_response"] = "supply_interaction_response"
    interaction_request_id: str
    execution_session_id: str | None = None
    run_id: str | None = None
    outbound_turn_request_id: str | None = None
    action: Literal["approve", "deny", "answer", "confirm", "cancel"]
    answer_text: str | None = None
    answers: dict[str, list[str]] | None = None
    native_response: dict[str, object] | None = None


class ReleaseRunCommand(BaseModel):
    type: Literal["release_run"] = "release_run"
    run_id: str
    execution_session_id: str


class AckMessage(BaseModel):
    type: Literal["ack"] = "ack"
    message_type: str
    ok: bool = True
    run_id: str | None = None
    detail: str | None = None


class ReadWorkspaceFileCommand(BaseModel):
    type: Literal["read_workspace_file"] = "read_workspace_file"
    request_id: str
    thread_id: str
    path: str


class WorkspaceFileChunk(BaseModel):
    type: Literal["workspace_file_chunk"] = "workspace_file_chunk"
    request_id: str
    seq: int
    data: str  # base64-encoded bytes


class WorkspaceFileEof(BaseModel):
    type: Literal["workspace_file_eof"] = "workspace_file_eof"
    request_id: str
    total_bytes: int
    sha256: str | None = None


class WorkspaceFileError(BaseModel):
    type: Literal["workspace_file_error"] = "workspace_file_error"
    request_id: str
    code: Literal["denied", "not_found", "too_large", "read_error"]
    message: str
