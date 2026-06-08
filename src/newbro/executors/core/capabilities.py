from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutorSkill(BaseModel):
    name: str
    display_name: str
    description: str = ""
    hint: str | None = None
    path: str
    enabled: bool = True


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
