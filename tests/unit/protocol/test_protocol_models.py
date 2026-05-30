import pytest
from pydantic import ValidationError

from newbro.protocol import (
    AgentResumeHandle,
    AssignmentLease,
    ConversationEffect,
    ExecutionMode,
    ExecutionRun,
    ExecutionSession,
    ExecutorTextInstruction,
    Interruption,
    InterruptionType,
    NotificationCandidate,
    NotificationCandidateType,
    NotificationDeliveryStatus,
    NotificationPriority,
    OutboundTurnRequest,
    RunStatus,
    SessionBinding,
    StartCodexTurnCommand,
    Task,
    TaskCommand,
    TaskCommandType,
    TaskExecutionDetailEntry,
    TaskExecutionMode,
    TaskMutation,
    TaskStatus,
    TaskSummary,
    Persona,
)


def _codex_turn_instruction() -> ExecutorTextInstruction:
    return ExecutorTextInstruction(
        instruction_id="txt-1",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        text="Continue.",
    )


def test_task_model_defaults():
    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Investigate bug",
        goal="Investigate the reported issue",
    )

    assert task.status == TaskStatus.CREATED
    assert task.priority == 5
    assert task.task_revision == 0


def test_persona_does_not_expose_current_task_pointer():
    persona = Persona(persona_id="forge", name="Forge")

    assert "current_task_id" not in persona.model_dump()
    assert "current_task_id" not in Persona.model_json_schema()["properties"]


def test_mutation_and_command_models():
    mutation = TaskMutation(
        mutation_id="mut_1",
        task_id="task_1",
        mutation_type="update",
        patch={"tone": "casual"},
        created_by="communication_brain",
    )
    command = TaskCommand(
        command_id="cmd_1",
        task_id="task_1",
        command_type=TaskCommandType.PAUSE_TASK,
        created_by="communication_brain",
    )

    assert mutation.mutation_type.value == "update"
    assert command.command_type.value == "pause_task"


def test_execution_lineage_models():
    session = ExecutionSession(
        execution_session_id="sess_1",
        task_id="task_1",
        base_executor_id="codex",
    )
    run = ExecutionRun(
        run_id="run_1",
        task_id="task_1",
        execution_session_id="sess_1",
        executor_type="codex",
    )
    binding = SessionBinding(
        task_id="task_1",
        execution_session_id="sess_1",
        session_id="agent_sess_1",
    )

    assert session.active_run_id is None
    assert run.status == RunStatus.CREATED
    assert binding.execution_revision == 0

    execution_mode = TaskExecutionMode(task_id="task_1", mode=ExecutionMode.UNDECIDED)
    assert execution_mode.mode == ExecutionMode.UNDECIDED

    detail = TaskExecutionDetailEntry(
        detail_id="detail_1",
        task_id="task_1",
        run_id="run_1",
        execution_session_id="sess_1",
        event_type="progress",
        text="Working on it.",
        created_at="2026-04-21T00:00:00+00:00",
    )
    assert detail.payload == {}


def test_summary_notification_and_interruption_models():
    summary = TaskSummary(task_id="task_1", conversational_summary="I am on it.")
    candidate = NotificationCandidate(
        candidate_id="notif_1",
        task_id="task_1",
        candidate_type=NotificationCandidateType.COMPLETED,
        priority=NotificationPriority.P1,
        summary_short="Task completed.",
        created_at="2026-04-06T00:00:00+00:00",
        delivery_status=NotificationDeliveryStatus.PENDING,
        merge_key="completed_digest",
    )
    interruption = Interruption(
        interruption_id="int_1",
        task_id="task_1",
        interruption_type=InterruptionType.SPEECH_ONLY,
        conversational_effect=ConversationEffect.STOP_OUTPUT,
    )
    lease = AssignmentLease(
        task_id="task_1",
        claimed_by="worker_1",
        claim_expires_at="2026-04-06T00:00:00Z",
    )

    assert summary.needs_user_input is False
    assert candidate.priority == NotificationPriority.P1
    assert candidate.candidate_type == NotificationCandidateType.COMPLETED
    assert interruption.interruption_type == InterruptionType.SPEECH_ONLY
    assert lease.claimed_by == "worker_1"


def test_outbound_turn_request_defaults():
    request = OutboundTurnRequest(
        request_id="out-turn-1",
        persona_id="forge",
        executor_id="codex",
        executor_node_id="node-forge",
        target_thread_id="thread-1",
        client_request_id="client-1",
        input_modality="text",
        text="continue",
    )

    assert request.status == "pending"
    assert request.create_new_thread is False
    assert request.executor_thread_id is None
    assert request.executor_turn_id is None


def test_start_codex_turn_command_validates_thread_intent():
    StartCodexTurnCommand(
        request_id="req-new",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        create_new_thread=True,
        instruction=_codex_turn_instruction(),
    )
    StartCodexTurnCommand(
        request_id="req-thread",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        instruction=_codex_turn_instruction(),
    )
    StartCodexTurnCommand(
        request_id="req-resume",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        latest_resume_handle=AgentResumeHandle(
            executor_id="codex",
            session_handle="codex-thread-1",
        ),
        instruction=_codex_turn_instruction(),
    )

    with pytest.raises(ValidationError):
        StartCodexTurnCommand(
            request_id="req-new-with-thread",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            create_new_thread=True,
            thread_id="codex-thread-1",
            instruction=_codex_turn_instruction(),
        )
    with pytest.raises(ValidationError):
        StartCodexTurnCommand(
            request_id="req-new-with-resume",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            create_new_thread=True,
            latest_resume_handle=AgentResumeHandle(
                executor_id="codex",
                session_handle="codex-thread-1",
            ),
            instruction=_codex_turn_instruction(),
        )
    with pytest.raises(ValidationError):
        StartCodexTurnCommand(
            request_id="req-ambiguous-existing",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            thread_id="codex-thread-1",
            latest_resume_handle=AgentResumeHandle(
                executor_id="codex",
                session_handle="codex-thread-2",
            ),
            instruction=_codex_turn_instruction(),
        )
    with pytest.raises(ValidationError):
        StartCodexTurnCommand(
            request_id="req-missing-existing",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            instruction=_codex_turn_instruction(),
        )
