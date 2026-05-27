from datetime import UTC, datetime

from newbro.notification import NotificationCandidateBuilder
from newbro.protocol import (
    ExecutionRun,
    NotificationCandidate,
    NotificationCandidateType,
    NotificationDeliveryStatus,
    NotificationPriority,
    RunStatus,
    Task,
    TaskSummary,
)


def test_candidate_builder_creates_completed_candidate():
    builder = NotificationCandidateBuilder(
        now_fn=lambda: datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
    )
    task = Task(task_id="task-1", root_task_id="task-1", title="Report", goal="Finish report")
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="sess-1",
        executor_type="codex",
        status=RunStatus.COMPLETED,
        output_summary="The report is done.",
    )
    summary = TaskSummary(
        task_id="task-1",
        conversational_summary="The report is done.",
    )

    candidate = builder.build_from_run(task=task, run=run, summary=summary, existing=[])

    assert candidate is not None
    assert candidate.candidate_type == NotificationCandidateType.COMPLETED
    assert candidate.merge_key == "completed_digest"


def test_candidate_builder_skips_direct_executor_tasks():
    builder = NotificationCandidateBuilder(
        now_fn=lambda: datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
    )
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Direct task",
        goal="Handle direct input",
        metadata={"suppress_communication_notifications": True},
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="sess-1",
        executor_type="codex",
        status=RunStatus.COMPLETED,
        output_summary="Direct task is done.",
    )
    summary = TaskSummary(
        task_id="task-1",
        conversational_summary="Direct task is done.",
        needs_user_input=True,
    )

    run_candidate = builder.build_from_run(task=task, run=run, summary=summary, existing=[])
    summary_candidate = builder.build_from_summary(task=task, summary=summary, existing=[])

    assert run_candidate is None
    assert summary_candidate is None


def test_candidate_builder_skips_needs_input_when_blocked_candidate_exists():
    builder = NotificationCandidateBuilder(
        now_fn=lambda: datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
    )
    task = Task(task_id="task-1", root_task_id="task-1", title="Report", goal="Finish report")
    summary = TaskSummary(
        task_id="task-1",
        conversational_summary="Need your confirmation.",
        needs_user_input=True,
    )
    existing = [
        NotificationCandidate(
            candidate_id="notif-blocked-task-1-run-1",
            task_id="task-1",
            candidate_type=NotificationCandidateType.BLOCKED,
            priority=NotificationPriority.P0,
            summary_short="Need your confirmation.",
            source_run_id="run-1",
            created_at="2026-04-06T12:00:00+00:00",
            delivery_status=NotificationDeliveryStatus.PENDING,
            merge_key="blocked:task-1",
            requires_immediate_delivery=True,
        )
    ]

    candidate = builder.build_from_summary(task=task, summary=summary, existing=existing)

    assert candidate is None
