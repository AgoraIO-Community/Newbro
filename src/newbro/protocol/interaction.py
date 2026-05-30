from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .enums import (
    AttentionItemKind,
    AttentionItemStatus,
    AttentionPriority,
    InteractionRequestKind,
    InteractionRequestStatus,
)


class InteractionRequest(BaseModel):
    request_id: str
    task_id: str | None = None
    outbound_turn_request_id: str | None = None
    execution_session_id: str | None = None
    run_id: str | None = None
    executor_type: str | None = None
    executor_node_id: str | None = None
    kind: InteractionRequestKind
    status: InteractionRequestStatus = InteractionRequestStatus.PENDING
    prompt: str
    details: dict[str, object] = Field(default_factory=dict)
    available_actions: list[str] = Field(default_factory=list)
    answer_schema: dict[str, object] | None = None
    resume_strategy: Literal["follow_up_run", "native_response"] = "follow_up_run"
    opaque: dict[str, object] = Field(default_factory=dict)
    created_at: str
    resolved_at: str | None = None


class AttentionItem(BaseModel):
    attention_id: str
    source: str
    kind: AttentionItemKind
    priority: AttentionPriority
    status: AttentionItemStatus = AttentionItemStatus.ACTIVE
    title: str
    body: str
    task_id: str | None = None
    request_id: str | None = None
    actions: list[dict[str, object]] = Field(default_factory=list)
    dedupe_key: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str
