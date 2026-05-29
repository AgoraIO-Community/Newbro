from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ExecutorEventType(StrEnum):
    PROGRESS = "progress"
    PLAN = "plan"
    WAITING_EXECUTOR = "waiting_executor"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutorEvent(BaseModel):
    run_id: str
    session_id: str
    event_type: ExecutorEventType
    message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
