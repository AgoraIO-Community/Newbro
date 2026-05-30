"""User-defined persona model.

Each persona is a named worker that can be assigned to one task at a time.
Personas are created by the user before task execution and persist across sessions.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field


class Persona(BaseModel):
    persona_id: str
    name: str
    avatar: str = ""
    base_prompt: str = ""
    executor_node_id: str | None = None
    bro_detail_session_id: str = Field(default_factory=lambda: f"bro-detail-{uuid4().hex[:8]}")
    status: str = "idle"  # "idle" | "busy"
