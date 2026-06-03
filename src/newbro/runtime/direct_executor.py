from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.protocol import (
    AgentResumeHandle,
    BroThread,
    ExecutionRun,
    ExecutionSession,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    OutboundTurnRequest,
    RunStatus,
    Task,
    TaskStatus,
)
from newbro.runtime.executor_node_manager import ExecutorNodeManager


LOGGER = logging.getLogger(__name__)
BRO_THREAD_PREFIX = "bro-thread-"
IMPORTED_CODEX_THREAD_PREFIX = "codex-import-"
AUDIO_ACTIVE_RUN_STATUSES = {RunStatus.ASSIGNED, RunStatus.RUNNING, RunStatus.BLOCKED}


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _new_bro_thread_id() -> str:
    return f"{BRO_THREAD_PREFIX}{uuid4().hex[:12]}"


def _public_thread_id(session: ExecutionSession) -> str:
    if isinstance(session.continuity_key, str) and session.continuity_key.startswith(BRO_THREAD_PREFIX):
        return session.continuity_key
    if isinstance(session.continuity_key, str) and session.continuity_key.startswith(IMPORTED_CODEX_THREAD_PREFIX):
        return session.continuity_key
    return session.execution_session_id


def _session_matches_thread_id(session: ExecutionSession, thread_id: str) -> bool:
    return thread_id in {
        session.execution_session_id,
        session.continuity_key or "",
        _public_thread_id(session),
    }


def _task_metadata_string(task: Task | None, key: str) -> str | None:
    if task is None:
        return None
    value = task.metadata.get(key)
    return value if isinstance(value, str) and value else None


def _task_belongs_to_persona(task: Task | None, persona_id: str) -> bool:
    if task is None:
        return False
    return task.metadata.get("persona_id") == persona_id or task.metadata.get("assigned_bro_id") == persona_id


def _task_thread_public_id(task: Task) -> str | None:
    return _task_metadata_string(task, "target_thread_id") or _task_metadata_string(task, "bro_thread_id")


def _workspace_name(workspace_id: str | None) -> str | None:
    if not isinstance(workspace_id, str):
        return None
    normalized = workspace_id.strip().rstrip("/\\")
    if not normalized:
        return None
    tail = normalized.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return tail or normalized


def _workspace_from_resume_handle(resume_handle: AgentResumeHandle | None) -> str | None:
    if resume_handle is None:
        return None
    cwd = resume_handle.opaque.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return cwd.strip()
    workspace_id = resume_handle.opaque.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return workspace_id.strip()
    return None


def _task_workspace_id(task: Task | None) -> str | None:
    if task is None:
        return None
    workspace_id = task.metadata.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return workspace_id.strip()
    if isinstance(task.session_affinity, str) and task.session_affinity.strip():
        return task.session_affinity.strip()
    return None


def mark_direct_executor_input(metadata: dict[str, object], source: str) -> dict[str, object]:
    next_metadata = dict(metadata)
    sources = next_metadata.get("direct_executor_input_sources")
    if isinstance(sources, list):
        direct_sources = [item for item in sources if isinstance(item, str)]
    else:
        direct_sources = []
    if source not in direct_sources:
        direct_sources.append(source)
    next_metadata["direct_executor_input_sources"] = direct_sources
    next_metadata["updated_at"] = datetime.now(tz=UTC).isoformat()
    next_metadata["suppress_communication_notifications"] = True
    return next_metadata


@dataclass(slots=True)
class ThreadTarget:
    public_thread_id: str
    continuity_key: str
    execution_session: ExecutionSession | None
    resume_handle: AgentResumeHandle | None


@dataclass(slots=True)
class DirectExecutorInteraction:
    session_id: str
    blackboard: BlackboardStore
    executor_node_manager: ExecutorNodeManager
    imported_codex_threads: dict[str, BroThread]
    imported_codex_thread_resume_handles: dict[str, AgentResumeHandle]
    publish_snapshot: Callable[[], Awaitable[None]]
    observability: object | None = None

    async def submit_text_instruction(
        self,
        *,
        target_persona_id: str,
        text: str,
        target_thread_id: str | None = None,
        create_new_thread: bool = False,
        workspace_id: str | None = None,
        client_request_id: str | None = None,
        plan_mode: bool = False,
    ) -> ExecutorTextInstruction:
        raise NotImplementedError

    async def submit_audio_instruction(
        self,
        *,
        target_persona_id: str,
        target_thread_id: str | None = None,
        create_new_thread: bool = False,
        workspace_id: str | None = None,
        client_request_id: str | None = None,
        pcm16: bytes,
        mime_type: str,
        duration_ms: int,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> ExecutorAudioInstruction:
        raise NotImplementedError

    async def handle_audio_transcript_event(self, run_id: str, metadata: dict[str, object]) -> None:
        raise NotImplementedError
