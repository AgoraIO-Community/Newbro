from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(slots=True)
class ConversationEntry:
    role: str
    text: str
    focused_task_id: str | None = None
    focused_task_ids: list[str] = field(default_factory=list)
    affected_task_ids: list[str] = field(default_factory=list)
    message_id: str = field(default_factory=lambda: f"msg-{uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


class InMemoryConversationHistory:
    def __init__(self) -> None:
        self._entries: dict[str, list[ConversationEntry]] = {}

    def append_user(
        self,
        conversation_id: str,
        text: str,
        *,
        focused_task_id: str | None = None,
        focused_task_ids: list[str] | None = None,
        affected_task_ids: list[str] | None = None,
    ) -> ConversationEntry:
        resolved_affected = list(affected_task_ids or [])
        resolved_focus_ids = list(focused_task_ids or resolved_affected)
        entry = ConversationEntry(
            role="user",
            text=text,
            focused_task_id=focused_task_id or (resolved_focus_ids[0] if resolved_focus_ids else None),
            focused_task_ids=resolved_focus_ids,
            affected_task_ids=resolved_affected,
        )
        self._entries.setdefault(conversation_id, []).append(entry)
        return entry

    def append_assistant(
        self,
        conversation_id: str,
        text: str,
        *,
        focused_task_id: str | None = None,
        focused_task_ids: list[str] | None = None,
        affected_task_ids: list[str] | None = None,
    ) -> ConversationEntry:
        resolved_affected = list(affected_task_ids or [])
        resolved_focus_ids = list(focused_task_ids or resolved_affected)
        entry = ConversationEntry(
            role="assistant",
            text=text,
            focused_task_id=focused_task_id or (resolved_focus_ids[0] if resolved_focus_ids else None),
            focused_task_ids=resolved_focus_ids,
            affected_task_ids=resolved_affected,
        )
        self._entries.setdefault(conversation_id, []).append(entry)
        return entry

    def get_recent(self, conversation_id: str, *, limit: int = 10) -> list[ConversationEntry]:
        return list(self._entries.get(conversation_id, [])[-limit:])

    def latest_focused_task_id(self, conversation_id: str) -> str | None:
        for entry in reversed(self._entries.get(conversation_id, [])):
            if entry.focused_task_id:
                return entry.focused_task_id
        return None

    def latest_focused_task_ids(self, conversation_id: str) -> list[str]:
        for entry in reversed(self._entries.get(conversation_id, [])):
            if entry.focused_task_ids:
                return list(entry.focused_task_ids)
            if entry.affected_task_ids:
                return list(entry.affected_task_ids)
            if entry.focused_task_id:
                return [entry.focused_task_id]
        return []
