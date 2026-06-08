from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.protocol import (
    AgentResumeHandle,
    ExecutionSession,
    ExecutorTextInstruction,
    OutboundTurnRequest,
    Persona,
)
from newbro.runtime.executor_node_manager import ExecutorNodeManager


def workspace_name_from_id(workspace_id: str | None) -> str | None:
    if not isinstance(workspace_id, str):
        return None
    normalized = workspace_id.strip().rstrip("/\\")
    if not normalized:
        return None
    tail = normalized.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return tail or normalized


@dataclass(slots=True)
class DirectTurnStartResult:
    request_id: str
    snapshot_elapsed_ms: int


@dataclass(slots=True)
class DirectTurnStarter:
    session_id: str
    blackboard: BlackboardStore
    executor_node_manager: ExecutorNodeManager
    publish_snapshot: Callable[[], Awaitable[object]]

    async def start_turn(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        continuity_key: str,
        execution_session: ExecutionSession | None,
        resume_handle: AgentResumeHandle | None,
        instruction: ExecutorTextInstruction,
        create_new_thread: bool,
        workspace_id: str | None,
        client_request_id: str | None,
        input_modality: str,
        source: str,
        node_not_ready_label: str,
        plan_mode: bool = False,
        skill: dict[str, object] | None = None,
        audio_instruction_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> DirectTurnStartResult:
        latest_resume_handle = self._latest_resume_handle(
            execution_session=execution_session,
            resume_handle=resume_handle,
        )
        if not create_new_thread and latest_resume_handle is None:
            raise ValueError("Selected Bro has no active Codex execution session.")

        request_id = f"out-turn-{uuid4().hex[:12]}"
        requested_at = datetime.now(tz=UTC).isoformat()
        outbound_metadata = self._outbound_metadata(
            source=source,
            instruction=instruction,
            continuity_key=continuity_key,
            create_new_thread=create_new_thread,
            workspace_id=workspace_id,
            client_request_id=client_request_id,
            execution_session=execution_session,
            latest_resume_handle=latest_resume_handle,
            plan_mode=plan_mode,
            skill=skill,
            metadata=metadata,
        )
        outbound_request = OutboundTurnRequest(
            request_id=request_id,
            persona_id=persona.persona_id,
            executor_id="codex",
            executor_node_id=persona.executor_node_id,
            target_thread_id=public_thread_id,
            create_new_thread=create_new_thread,
            workspace_id=workspace_id if create_new_thread else None,
            client_request_id=client_request_id,
            input_modality=input_modality,
            text=instruction.text,
            audio_instruction_id=audio_instruction_id,
            plan_mode=plan_mode,
            status="pending",
            created_at=requested_at,
            updated_at=requested_at,
            metadata=outbound_metadata,
        )
        await self.blackboard.put_outbound_turn_request(outbound_request)
        started = await self.executor_node_manager.start_codex_turn(
            request_id=request_id,
            node_id=persona.executor_node_id or "",
            target_persona_id=persona.persona_id,
            target_thread_id=public_thread_id,
            instruction=instruction,
            create_new_thread=create_new_thread,
            workspace_id=workspace_id if create_new_thread else None,
            latest_resume_handle=latest_resume_handle,
            metadata=outbound_metadata,
        )
        if not started:
            failed_at = datetime.now(tz=UTC).isoformat()
            message = f"Selected Bro's Codex executor node is not ready for {node_not_ready_label}."
            await self.blackboard.put_outbound_turn_request(
                outbound_request.model_copy(
                    update={
                        "status": "failed",
                        "error": message,
                        "updated_at": failed_at,
                    }
                )
            )
            await self.publish_snapshot()
            raise ValueError(message)

        accepted_at = datetime.now(tz=UTC).isoformat()
        await self.blackboard.put_outbound_turn_request(
            outbound_request.model_copy(update={"status": "accepted", "updated_at": accepted_at})
        )
        snapshot_started_at = time.perf_counter()
        await self.publish_snapshot()
        return DirectTurnStartResult(
            request_id=request_id,
            snapshot_elapsed_ms=int((time.perf_counter() - snapshot_started_at) * 1000),
        )

    def _latest_resume_handle(
        self,
        *,
        execution_session: ExecutionSession | None,
        resume_handle: AgentResumeHandle | None,
    ) -> AgentResumeHandle | None:
        if resume_handle is not None:
            return resume_handle
        if execution_session is not None and execution_session.latest_resume_handle is not None:
            return execution_session.latest_resume_handle
        return None

    def _outbound_metadata(
        self,
        *,
        source: str,
        instruction: ExecutorTextInstruction,
        continuity_key: str,
        create_new_thread: bool,
        workspace_id: str | None,
        client_request_id: str | None,
        execution_session: ExecutionSession | None,
        latest_resume_handle: AgentResumeHandle | None,
        plan_mode: bool,
        skill: dict[str, object] | None,
        metadata: dict[str, object] | None,
    ) -> dict[str, object]:
        outbound_metadata: dict[str, object] = {
            "source": source,
            "instruction_id": instruction.instruction_id,
            "thread_continuity_key": continuity_key,
            "thread_mode": "new_thread" if create_new_thread else "resume",
            "resume": not create_new_thread,
        }
        if plan_mode:
            outbound_metadata["plan_mode"] = True
        elif source == "bro_detail_text":
            outbound_metadata["plan_mode"] = False
        if skill:
            outbound_metadata["skill"] = skill
        if client_request_id is not None:
            outbound_metadata["client_request_id"] = client_request_id
        if execution_session is not None:
            outbound_metadata["execution_session_id"] = execution_session.execution_session_id
        if latest_resume_handle is not None:
            outbound_metadata["latest_resume_handle"] = latest_resume_handle.model_dump(mode="json")
            if latest_resume_handle.session_handle:
                outbound_metadata["codex_thread_id"] = latest_resume_handle.session_handle
            cwd = latest_resume_handle.opaque.get("cwd")
            if isinstance(cwd, str) and cwd:
                outbound_metadata["codex_import_cwd"] = cwd
        if create_new_thread and workspace_id:
            outbound_metadata["workspace_name"] = workspace_name_from_id(workspace_id) or workspace_id
        if metadata:
            outbound_metadata.update(metadata)
        return outbound_metadata
