from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from newbro.protocol import (
    NotificationCandidate,
    NotificationCandidateType,
    NotificationDeliveryStatus,
    NotificationPriority,
    RunStatus,
    Task,
    TaskStatus,
    TaskSummary,
    ExecutionRun,
)


class NotificationCandidateBuilder:
    def __init__(
        self,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def build_from_run(
        self,
        *,
        task: Task,
        run: ExecutionRun,
        summary: TaskSummary | None,
        existing: list[NotificationCandidate],
    ) -> NotificationCandidate | None:
        if _suppresses_communication_notifications(task):
            return None
        if task.status == TaskStatus.CANCELLED:
            return None

        if run.status == RunStatus.COMPLETED:
            candidate = NotificationCandidate(
                candidate_id=_candidate_id(
                    task_id=task.task_id,
                    candidate_type=NotificationCandidateType.COMPLETED,
                    source_run_id=run.run_id,
                ),
                task_id=task.task_id,
                candidate_type=NotificationCandidateType.COMPLETED,
                priority=NotificationPriority.P2,
                summary_short=(
                    (summary.conversational_summary if summary is not None else None)
                    or run.output_summary
                    or f"{task.title} is done."
                ),
                source_run_id=run.run_id,
                created_at=self._now_fn().isoformat(),
                delivery_status=NotificationDeliveryStatus.PENDING,
                merge_key="completed_digest",
                requires_immediate_delivery=False,
            )
            return None if _already_exists(candidate, existing) else candidate

        if run.status == RunStatus.BLOCKED:
            candidate = NotificationCandidate(
                candidate_id=_candidate_id(
                    task_id=task.task_id,
                    candidate_type=NotificationCandidateType.BLOCKED,
                    source_run_id=run.run_id,
                ),
                task_id=task.task_id,
                candidate_type=NotificationCandidateType.BLOCKED,
                priority=NotificationPriority.P0,
                summary_short=(
                    (summary.conversational_summary if summary is not None else None)
                    or run.block_reason
                    or f"{task.title} is blocked."
                ),
                source_run_id=run.run_id,
                created_at=self._now_fn().isoformat(),
                delivery_status=NotificationDeliveryStatus.PENDING,
                merge_key=f"blocked:{task.task_id}",
                requires_immediate_delivery=True,
            )
            return None if _already_exists(candidate, existing) else candidate

        return None

    def build_from_summary(
        self,
        *,
        task: Task,
        summary: TaskSummary | None,
        existing: list[NotificationCandidate],
    ) -> NotificationCandidate | None:
        if _suppresses_communication_notifications(task):
            return None
        if summary is None or not summary.needs_user_input:
            return None
        if any(
            candidate.task_id == task.task_id
            and candidate.candidate_type == NotificationCandidateType.BLOCKED
            and candidate.delivery_status != NotificationDeliveryStatus.SUPPRESSED
            for candidate in existing
        ):
            return None

        candidate = NotificationCandidate(
            candidate_id=_candidate_id(
                task_id=task.task_id,
                candidate_type=NotificationCandidateType.NEEDS_INPUT,
                source_run_id=None,
            ),
            task_id=task.task_id,
            candidate_type=NotificationCandidateType.NEEDS_INPUT,
            priority=NotificationPriority.P0,
            summary_short=summary.conversational_summary or f"{task.title} needs your input.",
            source_run_id=None,
            created_at=self._now_fn().isoformat(),
            delivery_status=NotificationDeliveryStatus.PENDING,
            merge_key=f"needs_input:{task.task_id}",
            requires_immediate_delivery=True,
        )
        return None if _already_exists(candidate, existing) else candidate


def _candidate_id(
    *,
    task_id: str,
    candidate_type: NotificationCandidateType,
    source_run_id: str | None,
) -> str:
    suffix = source_run_id or "summary"
    return f"notif-{candidate_type.value}-{task_id}-{suffix}"


def _already_exists(
    candidate: NotificationCandidate,
    existing: list[NotificationCandidate],
) -> bool:
    return any(item.candidate_id == candidate.candidate_id for item in existing)


def _suppresses_communication_notifications(task: Task) -> bool:
    if task.metadata.get("suppress_communication_notifications") is True:
        return True
    return task.metadata.get("source_kind") in {"bro_detail_text", "bro_detail_ptt"}
