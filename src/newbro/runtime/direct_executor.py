from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
    TaskMode,
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
    publish_snapshot: Callable[[], Awaitable[object]]
    observability: object | None = None

    def _record_direct_executor_text_metric(
        self,
        *,
        step: str,
        client_request_id: str | None,
        instruction_id: str | None = None,
        target_persona_id: str | None = None,
        target_thread_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        execution_session_id: str | None = None,
        elapsed_ms: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        metric_details: dict[str, object] = {
            "step": step,
            "client_request_id": client_request_id,
            "instruction_id": instruction_id,
            "target_persona_id": target_persona_id,
            "target_thread_id": target_thread_id,
        }
        if elapsed_ms is not None:
            metric_details["elapsed_ms"] = elapsed_ms
        if details:
            metric_details.update(details)
        logger = getattr(self.observability, "logger", None)
        emit_event = getattr(logger, "emit_event", None)
        if callable(emit_event):
            emit_event(
                level="INFO",
                event_name=f"executor_text.{step}",
                component="runtime.direct_executor",
                summary="Executor text instruction timing",
                conversation_id=self.session_id,
                request_id=client_request_id,
                task_id=task_id,
                run_id=run_id,
                execution_session_id=execution_session_id,
                executor_type="codex",
                details=metric_details,
            )
        LOGGER.info(
            "executor_text_metric step=%s session_id=%s client_request_id=%s instruction_id=%s target_persona_id=%s target_thread_id=%s task_id=%s run_id=%s execution_session_id=%s elapsed_ms=%s",
            step,
            self.session_id,
            client_request_id,
            instruction_id,
            target_persona_id,
            target_thread_id,
            task_id,
            run_id,
            execution_session_id,
            elapsed_ms,
        )

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
        started_at = time.perf_counter()
        self._record_direct_executor_text_metric(
            step="runtime.received",
            client_request_id=client_request_id,
            target_persona_id=target_persona_id,
            target_thread_id=target_thread_id,
            details={
                "create_new_thread": create_new_thread,
                "workspace_id": workspace_id,
                "text_length": len(text.strip()),
                "plan_mode": plan_mode,
            },
        )
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        if not persona.executor_node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        if not self.executor_node_manager.is_executor_connected(
            "codex",
            node_id=persona.executor_node_id,
        ):
            raise ValueError("Selected Bro's Codex executor node is not connected.")
        if not self.executor_node_manager.executor_supports_follow_up(
            "codex",
            node_id=persona.executor_node_id,
        ):
            raise ValueError("Selected Bro's executor node does not support text follow-up instructions.")
        self._record_direct_executor_text_metric(
            step="runtime.executor_ready",
            client_request_id=client_request_id,
            target_persona_id=persona.persona_id,
            target_thread_id=target_thread_id,
            elapsed_ms=_elapsed_ms(started_at),
            details={"executor_node_id": persona.executor_node_id},
        )

        resolved_workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else workspace_id
        resolve_started_at = time.perf_counter()
        thread_target = await self._resolve_thread_target(
            persona=persona,
            target_thread_id=target_thread_id,
            create_new_thread=create_new_thread,
            workspace_id=resolved_workspace_id,
        )
        self._record_direct_executor_text_metric(
            step="runtime.thread_resolved",
            client_request_id=client_request_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
            elapsed_ms=_elapsed_ms(resolve_started_at),
            details={
                "total_elapsed_ms": _elapsed_ms(started_at),
                "thread_continuity_key": thread_target.continuity_key,
                "resume_mode": thread_target.execution_session is not None
                or thread_target.resume_handle is not None,
            },
        )
        instruction = ExecutorTextInstruction(
            instruction_id=f"txt-{uuid4().hex[:12]}",
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
            text=text.strip(),
            metadata={
                "source": "bro_detail_text",
                "target_thread_id": thread_target.public_thread_id,
                "client_request_id": client_request_id,
                "plan_mode": plan_mode,
            },
        )

        lookup_started_at = time.perf_counter()
        execution_session, run = await self._active_codex_execution_for_persona(
            persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
        )
        self._record_direct_executor_text_metric(
            step="runtime.active_execution_checked",
            client_request_id=client_request_id,
            instruction_id=instruction.instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
            task_id=run.task_id if run is not None else None,
            run_id=run.run_id if run is not None else None,
            execution_session_id=execution_session.execution_session_id
            if execution_session is not None
            else None,
            elapsed_ms=_elapsed_ms(lookup_started_at),
            details={"total_elapsed_ms": _elapsed_ms(started_at)},
        )
        if execution_session is None or run is None:
            request_id = f"out-turn-{uuid4().hex[:12]}"
            requested_at = datetime.now(tz=UTC).isoformat()
            latest_resume_handle: AgentResumeHandle | None = None
            if thread_target.resume_handle is not None:
                latest_resume_handle = thread_target.resume_handle
            elif (
                thread_target.execution_session is not None
                and thread_target.execution_session.latest_resume_handle is not None
            ):
                latest_resume_handle = thread_target.execution_session.latest_resume_handle
            if not create_new_thread and latest_resume_handle is None:
                raise ValueError("Selected Bro has no active Codex execution session.")
            outbound_metadata: dict[str, object] = {
                "source": "bro_detail_text",
                "instruction_id": instruction.instruction_id,
                "thread_continuity_key": thread_target.continuity_key,
                "thread_mode": "new_thread" if create_new_thread else "resume",
                "resume": not create_new_thread,
                "plan_mode": plan_mode,
            }
            if client_request_id is not None:
                outbound_metadata["client_request_id"] = client_request_id
            if thread_target.execution_session is not None:
                outbound_metadata["execution_session_id"] = (
                    thread_target.execution_session.execution_session_id
                )
            if latest_resume_handle is not None:
                outbound_metadata["latest_resume_handle"] = latest_resume_handle.model_dump(mode="json")
                if latest_resume_handle.session_handle:
                    outbound_metadata["codex_thread_id"] = latest_resume_handle.session_handle
                cwd = latest_resume_handle.opaque.get("cwd")
                if isinstance(cwd, str) and cwd:
                    outbound_metadata["codex_import_cwd"] = cwd
            if create_new_thread and resolved_workspace_id:
                outbound_metadata["workspace_name"] = (
                    _workspace_name(resolved_workspace_id) or resolved_workspace_id
                )
            outbound_request = OutboundTurnRequest(
                request_id=request_id,
                persona_id=persona.persona_id,
                executor_id="codex",
                executor_node_id=persona.executor_node_id,
                target_thread_id=thread_target.public_thread_id,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                client_request_id=client_request_id,
                input_modality="text",
                text=instruction.text,
                plan_mode=plan_mode,
                status="pending",
                created_at=requested_at,
                updated_at=requested_at,
                metadata=outbound_metadata,
            )
            await self.blackboard.put_outbound_turn_request(outbound_request)
            start_started_at = time.perf_counter()
            started = await self.executor_node_manager.start_codex_turn(
                request_id=request_id,
                node_id=persona.executor_node_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target.public_thread_id,
                instruction=instruction,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                latest_resume_handle=latest_resume_handle,
                metadata=outbound_metadata,
            )
            self._record_direct_executor_text_metric(
                step="runtime.outbound_turn_started",
                client_request_id=client_request_id,
                instruction_id=instruction.instruction_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target.public_thread_id,
                elapsed_ms=_elapsed_ms(start_started_at),
                details={
                    "total_elapsed_ms": _elapsed_ms(started_at),
                    "outbound_turn_request_id": request_id,
                    "started": started,
                },
            )
            if not started:
                failed_at = datetime.now(tz=UTC).isoformat()
                await self.blackboard.put_outbound_turn_request(
                    outbound_request.model_copy(
                        update={
                            "status": "failed",
                            "error": "Selected Bro's Codex executor node is not ready for text.",
                            "updated_at": failed_at,
                        }
                    )
                )
                await self.publish_snapshot()
                raise ValueError("Selected Bro's Codex executor node is not ready for text.")
            accepted_at = datetime.now(tz=UTC).isoformat()
            await self.blackboard.put_outbound_turn_request(
                outbound_request.model_copy(update={"status": "accepted", "updated_at": accepted_at})
            )
            publish_started_at = time.perf_counter()
            await self.publish_snapshot()
            self._record_direct_executor_text_metric(
                step="runtime.snapshot_published",
                client_request_id=client_request_id,
                instruction_id=instruction.instruction_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target.public_thread_id,
                elapsed_ms=_elapsed_ms(publish_started_at),
                details={
                    "total_elapsed_ms": _elapsed_ms(started_at),
                    "outbound_turn_request_id": request_id,
                },
            )
            return instruction

        task = await self.blackboard.get_task(run.task_id)
        if task is not None:
            task.metadata = mark_direct_executor_input(task.metadata, "bro_detail_text")
            task.metadata["client_request_id"] = client_request_id
            task.metadata["plan_mode"] = plan_mode
            task.metadata["mode"] = (
                TaskMode.PROPOSAL_ONLY.value if plan_mode else TaskMode.MODIFY_ALLOWED.value
            )
            await self.blackboard.put_task(task)

        dispatch_started_at = time.perf_counter()
        dispatched = await self.executor_node_manager.dispatch_text_instruction(
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            executor_type="codex",
            task_id=run.task_id,
            node_id=persona.executor_node_id,
            instruction=instruction,
        )
        self._record_direct_executor_text_metric(
            step="runtime.dispatch_completed",
            client_request_id=client_request_id,
            instruction_id=instruction.instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
            task_id=run.task_id,
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            elapsed_ms=_elapsed_ms(dispatch_started_at),
            details={
                "total_elapsed_ms": _elapsed_ms(started_at),
                "dispatched": dispatched,
            },
        )
        if not dispatched:
            raise ValueError("Selected Bro's Codex executor node is not ready for text.")
        publish_started_at = time.perf_counter()
        await self.publish_snapshot()
        self._record_direct_executor_text_metric(
            step="runtime.snapshot_published",
            client_request_id=client_request_id,
            instruction_id=instruction.instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
            task_id=run.task_id,
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            elapsed_ms=_elapsed_ms(publish_started_at),
            details={"total_elapsed_ms": _elapsed_ms(started_at)},
        )
        return instruction

    async def _resolve_thread_target(
        self,
        *,
        persona,
        target_thread_id: str | None,
        create_new_thread: bool,
        workspace_id: str | None = None,
    ) -> ThreadTarget:
        if target_thread_id and create_new_thread:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and create a new thread.")
        if target_thread_id and workspace_id:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and choose a new workspace.")

        if create_new_thread:
            await self._validate_new_codex_thread_workspace(persona=persona, workspace_id=workspace_id)
            thread_id = _new_bro_thread_id()
            return ThreadTarget(
                public_thread_id=thread_id,
                continuity_key=thread_id,
                execution_session=None,
                resume_handle=None,
            )

        if target_thread_id:
            session = await self._find_codex_thread_session_for_persona(
                persona.persona_id,
                target_thread_id,
            )
            if session is not None:
                return ThreadTarget(
                    public_thread_id=_public_thread_id(session),
                    continuity_key=session.continuity_key or session.execution_session_id,
                    execution_session=session,
                    resume_handle=None,
                )
            imported = self.imported_codex_threads.get(target_thread_id)
            imported_resume_handle = self.imported_codex_thread_resume_handles.get(target_thread_id)
            if (
                imported is not None
                and imported.persona_id == persona.persona_id
                and imported_resume_handle is not None
            ):
                return ThreadTarget(
                    public_thread_id=imported.thread_id,
                    continuity_key=imported.thread_id,
                    execution_session=None,
                    resume_handle=imported_resume_handle,
                )
            pending_task = await self._find_direct_task_thread_for_persona(
                persona.persona_id,
                target_thread_id,
            )
            if pending_task is not None:
                continuity_key = _task_metadata_string(pending_task, "bro_thread_id") or target_thread_id
                return ThreadTarget(
                    public_thread_id=target_thread_id,
                    continuity_key=continuity_key,
                    execution_session=None,
                    resume_handle=None,
                )
            raise ValueError("Selected Codex thread is not available for this Bro.")

        raise ValueError("Direct Bro Detail instruction requires explicit thread intent.")

    async def _active_codex_execution_for_persona(
        self,
        persona_id: str,
        *,
        target_thread_id: str | None = None,
    ) -> tuple[ExecutionSession | None, ExecutionRun | None]:
        persona = await self.blackboard.get_persona(persona_id)
        if persona is None:
            return None, None
        if target_thread_id is None:
            return None, None
        for execution_session in await self.blackboard.list_sessions():
            if execution_session.base_executor_id != "codex" or not execution_session.active_run_id:
                continue
            if not _session_matches_thread_id(execution_session, target_thread_id):
                continue
            run = await self.blackboard.get_run(execution_session.active_run_id or "")
            if run is None:
                continue
            if run.executor_type != "codex" or run.status not in AUDIO_ACTIVE_RUN_STATUSES:
                continue
            return execution_session, run
        return None, None

    async def _validate_new_codex_thread_workspace(self, *, persona, workspace_id: str | None) -> None:
        normalized_workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else ""
        if not normalized_workspace_id:
            raise ValueError("New Codex thread requires a workspace selection.")
        known_workspaces = await self._known_codex_workspaces_for_persona(persona)
        if normalized_workspace_id not in known_workspaces:
            raise ValueError("Selected Codex workspace is not available for this Bro.")

    async def _known_codex_workspaces_for_persona(self, persona) -> set[str]:
        workspaces: set[str] = set()
        for imported in self.imported_codex_threads.values():
            if imported.persona_id != persona.persona_id:
                continue
            if imported.executor_node_id != persona.executor_node_id:
                continue
            if imported.workspace_id:
                workspaces.add(imported.workspace_id)
            cwd = imported.diagnostics.get("codex_cwd")
            if isinstance(cwd, str) and cwd.strip():
                workspaces.add(cwd.strip())
        for session in await self.blackboard.list_sessions():
            if session.base_executor_id != "codex":
                continue
            if session.executor_node_id != persona.executor_node_id:
                continue
            if not await self._session_belongs_to_persona(session, persona.persona_id):
                continue
            workspace_id = _workspace_from_resume_handle(session.latest_resume_handle)
            if workspace_id:
                workspaces.add(workspace_id)
        for task in await self.blackboard.list_tasks():
            if not _task_belongs_to_persona(task, persona.persona_id):
                continue
            if task.preferred_executor != "codex":
                continue
            executor_node_id = _task_metadata_string(task, "executor_node_id")
            if executor_node_id and executor_node_id != persona.executor_node_id:
                continue
            workspace_id = _task_workspace_id(task)
            if workspace_id:
                workspaces.add(workspace_id)
        return workspaces

    async def _find_codex_thread_session_for_persona(
        self,
        persona_id: str,
        thread_id: str,
    ) -> ExecutionSession | None:
        for session in reversed(await self.blackboard.list_sessions()):
            if session.base_executor_id != "codex" or not _session_matches_thread_id(session, thread_id):
                continue
            if await self._session_belongs_to_persona(session, persona_id):
                return session
        return None

    async def _find_direct_task_thread_for_persona(self, persona_id: str, thread_id: str) -> Task | None:
        for task in reversed(await self.blackboard.list_tasks()):
            if _task_thread_public_id(task) != thread_id:
                continue
            if _task_belongs_to_persona(task, persona_id):
                return task
        return None

    async def _session_belongs_to_persona(self, session: ExecutionSession, persona_id: str) -> bool:
        task_ids = list(session.run_ids)
        if session.latest_run_id and session.latest_run_id not in task_ids:
            task_ids.append(session.latest_run_id)
        for run_id in task_ids:
            run = await self.blackboard.get_run(run_id)
            if run is None:
                continue
            task = await self.blackboard.get_task(run.task_id)
            if _task_belongs_to_persona(task, persona_id):
                return True
        task = await self.blackboard.get_task(session.task_id)
        if _task_belongs_to_persona(task, persona_id):
            return True
        persona = await self.blackboard.get_persona(persona_id)
        return persona is not None and session.continuity_key == persona.bro_detail_session_id

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
