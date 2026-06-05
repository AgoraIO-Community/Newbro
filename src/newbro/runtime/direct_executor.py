from __future__ import annotations

import base64
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.protocol import (
    AgentResumeHandle,
    ExecutionMode,
    ExecutionRun,
    ExecutionSession,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    MutationType,
    RunStatus,
    Task,
    TaskExecutionMode,
    TaskMutation,
    TaskMode,
    TaskStatus,
)
from newbro.runtime.bro_detail_thread_projection import BroDetailThreadProjection
from newbro.runtime.direct_turn_starter import DirectTurnStarter, workspace_name_from_id
from newbro.runtime.executor_node_manager import ExecutorNodeManager


LOGGER = logging.getLogger(__name__)
AUDIO_ACTIVE_RUN_STATUSES = {RunStatus.ASSIGNED, RunStatus.RUNNING, RunStatus.BLOCKED}


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _title_from_draft_text(text: str) -> str:
    title = " ".join(text.strip().split()).rstrip(".。")
    if len(title) > 72:
        title = title[:69].rstrip() + "..."
    return title or "Draft task"


def _task_metadata_string(task: Task | None, key: str) -> str | None:
    if task is None:
        return None
    value = task.metadata.get(key)
    return value if isinstance(value, str) and value else None


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
    bro_detail_thread_projection: BroDetailThreadProjection
    publish_snapshot: Callable[[], Awaitable[object]]
    observability: object | None = None

    def _direct_turn_starter(self) -> DirectTurnStarter:
        return DirectTurnStarter(
            session_id=self.session_id,
            blackboard=self.blackboard,
            executor_node_manager=self.executor_node_manager,
            publish_snapshot=self.publish_snapshot,
        )

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
        thread_target = await self._thread_target(
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
            start_started_at = time.perf_counter()
            result = await self._direct_turn_starter().start_turn(
                persona=persona,
                public_thread_id=thread_target.public_thread_id,
                continuity_key=thread_target.continuity_key,
                execution_session=thread_target.execution_session,
                resume_handle=thread_target.resume_handle,
                instruction=instruction,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                client_request_id=client_request_id,
                input_modality="text",
                source="bro_detail_text",
                node_not_ready_label="text",
                plan_mode=plan_mode,
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
                    "outbound_turn_request_id": result.request_id,
                    "started": True,
                },
            )
            self._record_direct_executor_text_metric(
                step="runtime.snapshot_published",
                client_request_id=client_request_id,
                instruction_id=instruction.instruction_id,
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target.public_thread_id,
                elapsed_ms=result.snapshot_elapsed_ms,
                details={
                    "total_elapsed_ms": _elapsed_ms(started_at),
                    "outbound_turn_request_id": result.request_id,
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

    async def _thread_target(
        self,
        *,
        persona,
        target_thread_id: str | None,
        create_new_thread: bool,
        workspace_id: str | None = None,
    ) -> ThreadTarget:
        public_thread_id, continuity_key, execution_session, resume_handle = (
            await self.bro_detail_thread_projection.resolve_bro_thread_target(
                persona=persona,
                target_thread_id=target_thread_id,
                create_new_thread=create_new_thread,
                workspace_id=workspace_id,
            )
        )
        return ThreadTarget(
            public_thread_id=public_thread_id,
            continuity_key=continuity_key,
            execution_session=execution_session,
            resume_handle=resume_handle,
        )

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
            if not self.bro_detail_thread_projection.session_matches_thread_id(
                execution_session,
                target_thread_id,
            ):
                continue
            run = await self.blackboard.get_run(execution_session.active_run_id or "")
            if run is None:
                continue
            if run.executor_type != "codex" or run.status not in AUDIO_ACTIVE_RUN_STATUSES:
                continue
            return execution_session, run
        return None, None

    async def _start_text_task_from_direct_input(
        self,
        *,
        persona,
        instruction: ExecutorTextInstruction,
        thread_id: str,
        thread_continuity_key: str,
        selected_execution_session: ExecutionSession | None,
        selected_resume_handle: AgentResumeHandle | None,
        workspace_id: str | None = None,
        source_kind: str = "bro_detail_text",
        created_by: str = "bro_detail_text",
        extra_metadata: dict[str, object] | None = None,
    ) -> Task:
        task_id = f"task-{uuid4().hex[:8]}"
        text = instruction.text.strip()
        created_at = datetime.now(tz=UTC).isoformat()
        metadata = {
            "immutable": True,
            "source_kind": source_kind,
            "assigned_bro_id": persona.persona_id,
            "persona_id": persona.persona_id,
            "persona_name": persona.name,
            "persona_avatar": persona.avatar,
            "bro_detail_session_id": persona.bro_detail_session_id,
            "bro_thread_id": thread_continuity_key,
            "target_thread_id": thread_id,
            "executor_node_id": persona.executor_node_id,
            "instruction_id": instruction.instruction_id,
            "codex_thread_mode": (
                "resume"
                if selected_execution_session is not None or selected_resume_handle is not None
                else "start"
            ),
            "mode": (
                TaskMode.PROPOSAL_ONLY.value
                if instruction.metadata.get("plan_mode") is True
                else TaskMode.MODIFY_ALLOWED.value
            ),
            "created_at": created_at,
            "updated_at": created_at,
            "suppress_communication_notifications": True,
        }
        if workspace_id:
            metadata["workspace_id"] = workspace_id
            metadata["workspace_name"] = workspace_name_from_id(workspace_id) or workspace_id
        if selected_resume_handle is not None and selected_resume_handle.session_handle:
            metadata["codex_import_thread_id"] = selected_resume_handle.session_handle
            metadata["codex_imported_thread"] = True
            cwd = selected_resume_handle.opaque.get("cwd")
            if isinstance(cwd, str) and cwd:
                metadata["codex_import_cwd"] = cwd
            path = selected_resume_handle.opaque.get("path")
            if isinstance(path, str) and path:
                metadata["codex_import_path"] = path
        if extra_metadata:
            metadata.update(extra_metadata)
        session_affinity = f"ws-{thread_continuity_key}"
        if workspace_id:
            session_affinity = workspace_id
        if selected_resume_handle is not None:
            cwd = selected_resume_handle.opaque.get("cwd")
            if isinstance(cwd, str) and cwd:
                session_affinity = cwd
        task = Task(
            task_id=task_id,
            root_task_id=task_id,
            title=_title_from_draft_text(text),
            goal=text,
            status=TaskStatus.QUEUED,
            preferred_executor="codex",
            session_affinity=session_affinity,
            latest_instruction=text,
            metadata=metadata,
        )
        await self.blackboard.put_persona(persona.model_copy(update={"status": "busy"}))
        await self.blackboard.put_task(task)
        await self.blackboard.put_execution_mode(
            TaskExecutionMode(task_id=task_id, mode=ExecutionMode.UNDECIDED)
        )
        await self.blackboard.append_mutation(
            TaskMutation(
                mutation_id=f"mut-{uuid4().hex[:8]}",
                task_id=task_id,
                mutation_type=MutationType.CREATE,
                patch={
                    "title": task.title,
                    "goal": task.goal,
                    "preferred_executor": "codex",
                    "persona_id": persona.persona_id,
                    "persona_name": persona.name,
                    "source_kind": source_kind,
                    "instruction_id": instruction.instruction_id,
                },
                created_by=created_by,
            )
        )
        saved = await self.blackboard.get_task(task_id)
        return saved or task

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
        if not self.executor_node_manager.executor_supports_audio_instruction(
            "codex",
            node_id=persona.executor_node_id,
        ):
            raise ValueError("Selected Bro's executor node does not support audio transcription instructions.")

        resolved_workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else workspace_id
        thread_target = await self._thread_target(
            persona=persona,
            target_thread_id=target_thread_id,
            create_new_thread=create_new_thread,
            workspace_id=resolved_workspace_id,
        )
        audio_instruction_id = f"aud-{uuid4().hex[:12]}"
        audio = ExecutorAudioInstruction(
            audio_instruction_id=audio_instruction_id,
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
            pcm16_b64=base64.b64encode(pcm16).decode("ascii"),
            mime_type=mime_type,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
            size_bytes=len(pcm16),
            metadata={
                "source": "bro_detail_ptt",
                "target_thread_id": thread_target.public_thread_id,
                **({"client_request_id": client_request_id} if client_request_id else {}),
            },
        )
        execution_session, run = await self._active_codex_execution_for_persona(
            persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
        )
        if execution_session is None or run is None:
            try:
                transcription = await self.executor_node_manager.transcribe_audio_instruction(
                    executor_type="codex",
                    node_id=persona.executor_node_id,
                    audio=audio,
                )
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            transcript = (transcription.transcript_text or "").strip()
            if not transcript:
                raise ValueError("Audio transcription produced no instruction text.")
            audio.metadata.update(
                {
                    "source": "executor_node_whisper",
                    "source_audio_instruction_id": audio.audio_instruction_id,
                    "transcript_text": transcript,
                    "transcription_language": transcription.language or "",
                    "transcription_duration_seconds": transcription.duration_seconds or 0,
                    **transcription.metadata,
                }
            )
            instruction = ExecutorTextInstruction(
                instruction_id=f"txt-{audio.audio_instruction_id}",
                target_persona_id=persona.persona_id,
                target_thread_id=thread_target.public_thread_id,
                text=transcript,
                source_audio_instruction_id=audio.audio_instruction_id,
                metadata={
                    "source": "executor_node_whisper",
                    "target_thread_id": thread_target.public_thread_id,
                    "source_audio_instruction_id": audio.audio_instruction_id,
                    "transcript_text": transcript,
                    **({"client_request_id": client_request_id} if client_request_id else {}),
                },
            )
            await self._direct_turn_starter().start_turn(
                persona=persona,
                public_thread_id=thread_target.public_thread_id,
                continuity_key=thread_target.continuity_key,
                execution_session=thread_target.execution_session,
                resume_handle=thread_target.resume_handle,
                instruction=instruction,
                create_new_thread=create_new_thread,
                workspace_id=resolved_workspace_id if create_new_thread else None,
                client_request_id=client_request_id,
                input_modality="audio",
                source="bro_detail_ptt",
                node_not_ready_label="audio",
                audio_instruction_id=audio.audio_instruction_id,
                metadata={
                    "source_audio_instruction_id": audio.audio_instruction_id,
                    "transcript_text": transcript,
                },
            )
            return audio

        task = await self.blackboard.get_task(run.task_id)
        if task is not None:
            task.metadata = mark_direct_executor_input(task.metadata, "bro_detail_ptt")
            task.metadata["bro_thread_id"] = thread_target.continuity_key
            task.metadata["target_thread_id"] = thread_target.public_thread_id
            task.metadata["source_audio_instruction_id"] = audio.audio_instruction_id
            if client_request_id:
                task.metadata["client_request_id"] = client_request_id
            await self.blackboard.put_task(task)
        dispatched = await self.executor_node_manager.dispatch_audio_instruction(
            run_id=run.run_id,
            execution_session_id=execution_session.execution_session_id,
            executor_type="codex",
            task_id=run.task_id,
            node_id=persona.executor_node_id,
            audio=audio,
        )
        if not dispatched:
            raise ValueError("Selected Bro's Codex executor node is not ready for audio.")
        await self.publish_snapshot()
        return audio

    async def handle_audio_transcript_event(self, run_id: str, metadata: dict[str, object]) -> None:
        audio_id = metadata.get("source_audio_instruction_id")
        transcript = metadata.get("transcript_text")
        if not isinstance(audio_id, str) or not audio_id:
            return
        if not isinstance(transcript, str) or not transcript.strip():
            return
        if metadata.get("source") != "executor_node_whisper":
            return
        run = await self.blackboard.get_run(run_id)
        if run is None:
            return
        task = await self.blackboard.get_task(run.task_id)
        if task is None:
            return
        persona_id = task.metadata.get("persona_id")
        if not isinstance(persona_id, str):
            return
        persona = await self.blackboard.get_persona(persona_id)
        if persona is None:
            return
        created_tasks = task.metadata.get("audio_transcript_task_ids")
        if not isinstance(created_tasks, dict):
            created_tasks = {}
        if audio_id in created_tasks:
            return
        task.metadata["audio_transcript_task_ids"] = {**created_tasks, audio_id: "pending"}
        await self.blackboard.put_task(task)

        target_thread_id = metadata.get("target_thread_id")
        if not isinstance(target_thread_id, str) or not target_thread_id:
            task_thread_id = task.metadata.get("target_thread_id")
            target_thread_id = task_thread_id if isinstance(task_thread_id, str) else None
        thread_target = await self._thread_target(
            persona=persona,
            target_thread_id=target_thread_id,
            create_new_thread=False,
        )
        instruction = ExecutorTextInstruction(
            instruction_id=f"txt-{audio_id}",
            target_persona_id=persona.persona_id,
            target_thread_id=thread_target.public_thread_id,
            text=transcript.strip(),
            source_audio_instruction_id=audio_id,
            metadata={
                "source": "executor_node_whisper",
                "target_thread_id": thread_target.public_thread_id,
                "source_audio_instruction_id": audio_id,
                "transcript_text": transcript.strip(),
            },
        )
        transcript_task = await self._start_text_task_from_direct_input(
            persona=persona,
            instruction=instruction,
            thread_id=thread_target.public_thread_id,
            thread_continuity_key=thread_target.continuity_key,
            selected_execution_session=thread_target.execution_session,
            selected_resume_handle=thread_target.resume_handle,
            source_kind="bro_detail_ptt",
            created_by="bro_detail_ptt",
            extra_metadata={
                "source_audio_instruction_id": audio_id,
                "direct_executor_input_sources": ["bro_detail_ptt"],
            },
        )
        refreshed = await self.blackboard.get_task(task.task_id)
        if refreshed is not None:
            current_created = refreshed.metadata.get("audio_transcript_task_ids")
            if not isinstance(current_created, dict):
                current_created = {}
            refreshed.metadata["audio_transcript_task_ids"] = {
                **current_created,
                audio_id: transcript_task.task_id,
            }
            await self.blackboard.put_task(refreshed)
        await self.publish_snapshot()
