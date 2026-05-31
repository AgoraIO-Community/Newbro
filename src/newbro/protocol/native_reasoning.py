from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class NativeReasoningStep(BaseModel):
    item_id: str
    text: str
    kind: Literal["progress", "plan"]
    created_at: str
