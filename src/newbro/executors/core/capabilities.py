from __future__ import annotations

from pydantic import BaseModel


class ExecutorCapabilities(BaseModel):
    executor_type: str
    supports_resume: bool = False
    supports_follow_up: bool = False
    supports_audio_instruction: bool = False
    supports_thread_list: bool = False
    supports_pause: bool = False
    supports_cancel: bool = True
    supports_setup: bool = False
