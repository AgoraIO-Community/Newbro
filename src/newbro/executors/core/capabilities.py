from __future__ import annotations

from pydantic import BaseModel, Field

# ExecutorSkill is defined canonically in newbro.protocol.executor_node and
# re-exported here to avoid a circular import (protocol → executors.core).
from newbro.protocol.executor_node import ExecutorSkill

__all__ = ["ExecutorSkill", "ExecutorCapabilities"]


class ExecutorCapabilities(BaseModel):
    executor_type: str
    supports_resume: bool = False
    supports_follow_up: bool = False
    supports_audio_instruction: bool = False
    supports_thread_list: bool = False
    supports_pause: bool = False
    supports_cancel: bool = True
    supports_setup: bool = False
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
    skills: list[ExecutorSkill] = Field(default_factory=list)
