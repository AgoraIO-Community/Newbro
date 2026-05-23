from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BlackboardWriteKind(StrEnum):
    TASK = "task"
    MUTATION = "mutation"
    COMMAND = "command"
    EXECUTION_DETAIL = "execution_detail"
    RUN = "run"
    SESSION = "session"
    BINDING = "binding"
    SUMMARY = "summary"
    EXECUTION_MODE = "execution_mode"
    NOTIFICATION = "notification"
    PERSONA = "persona"
    INTERACTION_REQUEST = "interaction_request"
    ATTENTION = "attention"
    AGENT_EVENT = "agent_event"


@dataclass(slots=True)
class BlackboardWriteEvent:
    kind: BlackboardWriteKind
    entity_id: str | None = None
    task_id: str | None = None
    request_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
