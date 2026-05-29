from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.executors.core import ExecutorEvent, ExecutorEventType
from newbro.observability.emitters.execution import ExecutionDiagnosticEmitter
from newbro.protocol import (
    ExecutionRun,
    ExecutionSession,
    RunStatus,
    Task,
    TaskExecutionDetailEntry,
    TaskStatus,
)


class RunManager:
    def __init__(self, *, observability: ExecutionDiagnosticEmitter | None = None) -> None:
        self._observability = observability

    async def create_run(
        self,
        store: BlackboardStore,
        task: Task,
        session: ExecutionSession,
        *,
        claimed_by: str | None,
        executor_type: str,
    ) -> ExecutionRun:
        run = ExecutionRun(
            run_id=f"run-{uuid4().hex[:8]}",
            task_id=task.task_id,
            execution_session_id=session.execution_session_id,
            executor_type=executor_type,
            status=RunStatus.ASSIGNED,
            claimed_by=claimed_by,
            run_revision=task.task_revision,
        )
        session.run_ids.append(run.run_id)
        session.active_run_id = run.run_id
        session.latest_run_id = run.run_id
        await store.put_run(run)
        await store.put_session(session)
        if self._observability is not None:
            self._observability.run_started(
                task_id=task.task_id,
                run_id=run.run_id,
                execution_session_id=session.execution_session_id,
                executor_type=executor_type,
                claimed_by=claimed_by,
            )
        return run

    async def apply_event(
        self,
        store: BlackboardStore,
        task: Task,
        run: ExecutionRun,
        event: ExecutorEvent,
    ) -> None:
        if task.status == TaskStatus.CANCELLED and event.event_type != ExecutorEventType.CANCELLED:
            return

        previous_run = run.model_copy(deep=True)
        previous_task = task.model_copy(deep=True)
        detail_text = _detail_text(task, event)
        should_append_detail = False
        if event.event_type == ExecutorEventType.PROGRESS:
            if run.status != RunStatus.RUNNING:
                run.status = RunStatus.RUNNING
            if (
                isinstance(event.message, str)
                and event.message.strip()
                and event.message != previous_run.latest_progress_message
            ):
                run.latest_progress_message = event.message
                should_append_detail = True
            if event.metadata:
                metadata = dict(event.metadata)
                run.metadata["latest_progress_event"] = metadata
                audio_id = metadata.get("source_audio_instruction_id")
                transcript = metadata.get("transcript_text")
                if isinstance(audio_id, str) and audio_id and isinstance(transcript, str) and transcript.strip():
                    transcripts = run.metadata.get("audio_transcripts")
                    if not isinstance(transcripts, dict):
                        transcripts = {}
                    transcripts[audio_id] = transcript.strip()
                    run.metadata["audio_transcripts"] = transcripts
            if task.status != TaskStatus.RUNNING:
                task.status = TaskStatus.RUNNING
        elif event.event_type == ExecutorEventType.WAITING_EXECUTOR:
            run.status = RunStatus.WAITING_EXECUTOR
            if isinstance(event.message, str) and event.message.strip():
                run.latest_progress_message = event.message
            if event.metadata:
                run.metadata["executor_wait_event"] = dict(event.metadata)
            task.status = TaskStatus.WAITING_EXECUTOR
            should_append_detail = True
        elif event.event_type == ExecutorEventType.BLOCKED:
            run.status = RunStatus.BLOCKED
            run.block_reason = event.message
            if event.metadata:
                run.metadata["blocked_event"] = dict(event.metadata)
            task.status = TaskStatus.WAITING_USER_INPUT
            should_append_detail = True
            if self._observability is not None:
                self._observability.run_terminal(
                    event_name="exec.run.blocked",
                    task_id=task.task_id,
                    run_id=run.run_id,
                    execution_session_id=run.execution_session_id,
                    executor_type=run.executor_type,
                    summary=event.message,
                )
        elif event.event_type == ExecutorEventType.COMPLETED:
            run.status = RunStatus.COMPLETED
            run.output_summary = event.message
            if event.metadata:
                run.metadata["latest_terminal_event"] = dict(event.metadata)
            task.status = TaskStatus.COMPLETED
            should_append_detail = True
            if self._observability is not None:
                self._observability.run_terminal(
                    event_name="exec.run.completed",
                    task_id=task.task_id,
                    run_id=run.run_id,
                    execution_session_id=run.execution_session_id,
                    executor_type=run.executor_type,
                    summary=event.message,
                )
        elif event.event_type == ExecutorEventType.FAILED:
            run.status = RunStatus.FAILED
            run.failure_reason = event.message
            if event.metadata:
                run.metadata["latest_terminal_event"] = dict(event.metadata)
            task.status = TaskStatus.FAILED
            should_append_detail = True
            if self._observability is not None:
                self._observability.run_terminal(
                    event_name="exec.run.failed",
                    task_id=task.task_id,
                    run_id=run.run_id,
                    execution_session_id=run.execution_session_id,
                    executor_type=run.executor_type,
                    summary=event.message,
                    reason_code="executor_run_failed",
                )
        elif event.event_type == ExecutorEventType.CANCELLED:
            run.status = RunStatus.CANCELLED
            task.status = TaskStatus.CANCELLED
            should_append_detail = True

        if should_append_detail:
            await store.append_task_execution_detail(
                TaskExecutionDetailEntry(
                    detail_id=f"detail-{uuid4().hex[:8]}",
                    task_id=task.task_id,
                    run_id=run.run_id,
                    execution_session_id=run.execution_session_id,
                    event_type=event.event_type.value,
                    text=detail_text,
                    created_at=datetime.now(UTC).isoformat(),
                    payload={
                        "session_id": event.session_id,
                        "message": event.message,
                        "metadata": event.metadata,
                    },
                )
            )
        if _run_changed(previous_run, run):
            await store.put_run(run)
        if _task_changed(previous_task, task):
            await store.put_task(task)


def _detail_text(task: Task, event: ExecutorEvent) -> str:
    if isinstance(event.message, str) and event.message.strip():
        return event.message.strip()
    if event.event_type == ExecutorEventType.PROGRESS:
        return f"Running: {task.title}"
    if event.event_type == ExecutorEventType.WAITING_EXECUTOR:
        return event.message.strip() if isinstance(event.message, str) and event.message.strip() else f"Waiting for executor: {task.title}"
    if event.event_type == ExecutorEventType.BLOCKED:
        return f"Blocked: {task.title}"
    if event.event_type == ExecutorEventType.COMPLETED:
        return f"Completed: {task.title}"
    if event.event_type == ExecutorEventType.FAILED:
        return f"Failed: {task.title}"
    return f"Cancelled: {task.title}"


def _run_changed(previous: ExecutionRun, current: ExecutionRun) -> bool:
    return previous != current


def _task_changed(previous: Task, current: Task) -> bool:
    return previous != current
