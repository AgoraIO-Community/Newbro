from __future__ import annotations

import pytest

from newbro.protocol import (
    AgentEvent,
    AgentEventDelivery,
    AgentEventImportance,
    AgoraVoiceEvent,
    AgoraVoiceEventType,
    DispatchPlan,
    DispatchGateOutcome,
    InteractionType,
    TaskMode,
)
from newbro.communication.interaction_classifier import (
    InteractionClassification,
    ScriptedInteractionClassifier,
)
from newbro.runtime.drafts import (
    DeterministicDraftRewriter,
    dispatch_gate,
    formulate_task_spec,
    lint_task_spec,
    agent_allowed_for_intent,
    utc_now_iso,
)
from newbro.runtime.session import create_session_runtime
from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.runtime.config import Settings
from newbro.runtime.executor_node_manager import ExecutorNodeManager


def _classifier_for(interaction_type: InteractionType, **kwargs) -> ScriptedInteractionClassifier:
    return ScriptedInteractionClassifier(
        {},
        default=InteractionClassification(
            interaction_type=interaction_type,
            confidence=1.0,
            reason="test",
            **kwargs,
        ),
    )


def test_formulate_task_spec_uses_target_context_and_safe_default_mode():
    spec = formulate_task_spec(
        "处理这个页面。",
        assigned_bro_id="persona-alpha",
    )

    assert spec.target_agent == "persona-alpha"
    assert spec.mode == TaskMode.READ_ONLY_FIRST
    assert spec.input_language == "zh-CN"
    assert spec.output_language == "zh-CN"
    assert spec.code_switched is False
    assert "Inspect first; ask before making changes" in spec.constraints
    assert "Respond to the user in Chinese" in spec.success_criteria


def test_dispatch_gate_requires_confirmation_before_safe_dispatch():
    spec = formulate_task_spec("Ask worker to analyze alpha module.", assigned_bro_id="hermes")
    plan = __import__("newbro.runtime.drafts", fromlist=["build_dispatch_plan"])
    from newbro.protocol import Draft, DraftSession, DraftSessionStatus

    draft_session = DraftSession(
        id="draft-1",
        assigned_bro_id="hermes",
        current_draft=Draft(text=spec.goal, task_spec=spec),
        status=DraftSessionStatus.READY,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    dispatch_plan = plan.build_dispatch_plan(
        runtime_session_id="session-1",
        draft_session=draft_session,
        draft=draft_session.current_draft,
    )

    assert dispatch_gate(dispatch_plan).outcome == DispatchGateOutcome.ASK_CONFIRMATION
    assert dispatch_gate(dispatch_plan.model_copy(update={"user_confirmed": True})).outcome == DispatchGateOutcome.DISPATCH


def test_dispatch_gate_covers_clarification_reject_and_risk_outcomes():
    spec = formulate_task_spec("Ask worker to analyze beta module.", assigned_bro_id="codex")
    base_plan = DispatchPlan(
        plan_id="plan-1",
        session_id="session-1",
        draft_session_id="draft-1",
        target_agent="codex",
        task_title=spec.title,
        task_goal=spec.goal,
        mode=spec.mode,
        task_spec=spec,
    )

    assert dispatch_gate(base_plan.model_copy(update={"confidence": 0.2})).outcome == DispatchGateOutcome.ASK_CLARIFICATION
    assert dispatch_gate(base_plan.model_copy(update={"missing_context": ["target"]})).outcome == DispatchGateOutcome.ASK_CLARIFICATION
    assert dispatch_gate(base_plan.model_copy(update={"target_agent": ""})).outcome == DispatchGateOutcome.REJECT
    assert dispatch_gate(base_plan.model_copy(update={"mode": TaskMode.MODIFY_ALLOWED, "risk_level": "medium"})).outcome == DispatchGateOutcome.ASK_CONFIRMATION


def test_task_linter_and_routing_table_are_deterministic():
    missing = formulate_task_spec("alpha")
    assert lint_task_spec(missing).valid is False

    valid = formulate_task_spec("Ask worker to analyze gamma module.", assigned_bro_id="hermes")
    assert lint_task_spec(valid).valid is True
    assert agent_allowed_for_intent("repo_investigation", "hermes") is True
    assert agent_allowed_for_intent("repo_investigation", "browser_agent") is False
    assert agent_allowed_for_intent("repo_investigation", "persona-rook") is True


@pytest.mark.anyio
async def test_runtime_message_stages_and_confirms_structured_task():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.DELEGATION),
    )

    decision = await session.handle_runtime_message(
        text="让 worker 处理 alpha 页面。",
        message_type="stt_final",
        language="zh-CN",
    )

    assert decision.should_speak is True
    assert decision.dispatch_plan_id
    assert "发送吗" in decision.response_text
    draft = session.draft_manager.active_session
    assert draft is not None
    assert draft.current_draft is not None
    assert draft.current_draft.task_spec is not None
    assert draft.current_draft.task_spec.mode == TaskMode.READ_ONLY_FIRST

    session.interaction_classifier = _classifier_for(InteractionType.CONFIRMATION)

    sent = await session.handle_runtime_message(text="confirm action", message_type="text")

    assert sent.should_speak is True
    assert sent.task_id
    task = await session.blackboard.get_task(sent.task_id)
    assert task is not None
    assert task.metadata["source_kind"] == "draft_session"
    assert task.metadata["mode"] == "read_only_first"
    assert task.metadata["task_spec"]["target_agent"] == "codex"
    assert task.goal != "confirm action"
    assert "raw_transcript" in task.metadata["task_spec"]


@pytest.mark.anyio
async def test_runtime_message_handles_partial_communication_correction_and_cancel():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.COMMUNICATION),
    )

    partial = await session.handle_runtime_message(text="partial text", message_type="stt_partial")
    assert partial.should_speak is False
    assert partial.ui_updates[0].type == "transcript.partial"

    communication = await session.handle_runtime_message(text="hello", message_type="text")
    assert communication.should_speak is False
    assert communication.interaction_type == "communication"

    session.interaction_classifier = _classifier_for(InteractionType.DELEGATION)
    staged = await session.handle_runtime_message(text="same transcript", message_type="text")
    assert staged.dispatch_plan_id
    first_draft_id = staged.draft_session_id

    session.interaction_classifier = _classifier_for(
        InteractionType.DRAFT_CORRECTION,
        task_mode=TaskMode.PROPOSAL_ONLY,
    )
    corrected = await session.handle_runtime_message(text="same transcript", message_type="text")
    assert corrected.should_speak is False
    assert corrected.draft_session_id == first_draft_id
    draft = session.draft_manager.active_session
    assert draft is not None
    assert draft.current_draft is not None
    assert draft.current_draft.task_spec is not None
    assert draft.current_draft.task_spec.mode == TaskMode.PROPOSAL_ONLY

    session.interaction_classifier = _classifier_for(
        InteractionType.DRAFT_CORRECTION,
        control_action="clear_draft",
    )
    cancelled = await session.handle_runtime_message(text="same transcript", message_type="text")
    assert cancelled.should_speak is False
    assert session.draft_manager.active_session is None


@pytest.mark.anyio
async def test_agora_voice_event_path_uses_typed_finality_and_runtime_decision():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.DELEGATION),
    )

    partial = await session.handle_agora_event(
        AgoraVoiceEvent(
            event_id="event-partial",
            session_id="session-1",
            type=AgoraVoiceEventType.STT_PARTIAL,
            text="partial text",
            target_persona_id="codex",
        )
    )

    assert partial.should_speak is False
    assert partial.ui_updates[0].type == "transcript.partial"
    assert session.draft_manager.active_session is None
    assert session.voice_target_persona_id == "codex"

    final = await session.handle_agora_event(
        AgoraVoiceEvent(
            event_id="event-final",
            session_id="session-1",
            type=AgoraVoiceEventType.STT_FINAL,
            text="same transcript",
            target_persona_id="codex",
        )
    )

    assert final.should_speak is True
    assert final.dispatch_plan_id
    assert session.draft_manager.active_session is not None
    classified_events = [
        event for event in session.observability.store.all()
        if event.event_name == "comm.interaction.classified"
    ]
    assert classified_events[-1].details["interaction_type"] == "delegation"


@pytest.mark.anyio
async def test_agora_lifecycle_events_are_silent_ui_updates():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.COMMUNICATION),
    )

    decision = await session.handle_agora_event(
        AgoraVoiceEvent(
            event_id="event-started",
            session_id="session-1",
            type=AgoraVoiceEventType.SESSION_STARTED,
            metadata={"agora_runtime_session_id": "runtime-1"},
        )
    )

    assert decision.should_speak is False
    assert decision.response_text == ""
    assert decision.ui_updates[0].type == "agora.session.started"
    assert decision.ui_updates[0].payload["metadata"] == {"agora_runtime_session_id": "runtime-1"}


@pytest.mark.anyio
async def test_same_transcript_speaks_only_when_classifier_output_requires_it():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.COMMUNICATION),
    )

    silent = await session.handle_runtime_message(text="same transcript", message_type="stt_final")
    assert silent.should_speak is False

    session.interaction_classifier = _classifier_for(InteractionType.STATUS_QUERY)
    spoken = await session.handle_runtime_message(text="same transcript", message_type="stt_final")
    assert spoken.should_speak is True
    assert spoken.response_text == "No active task."


@pytest.mark.anyio
async def test_structured_task_control_speaks_from_runtime_state_not_text():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.TASK_CONTROL),
    )

    decision = await session.handle_runtime_message(text="same transcript", message_type="stt_final")

    assert decision.should_speak is True
    assert decision.response_text == "No active task to stop."


@pytest.mark.anyio
async def test_agent_event_delivery_is_silent_for_low_progress_and_spoken_for_blocked():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.DELEGATION),
    )
    await session.handle_runtime_message(text="same transcript", message_type="text")
    session.interaction_classifier = _classifier_for(InteractionType.CONFIRMATION)
    sent = await session.handle_runtime_message(text="same transcript", message_type="text")
    assert sent.task_id

    progress = await session.ingest_agent_event(
        AgentEvent(
            event_id="event-1",
            task_id=sent.task_id,
            agent_id="codex",
            type="agent.progress",
            message="Checked the repo layout.",
            importance=AgentEventImportance.LOW,
            delivery=AgentEventDelivery.SILENT_UI,
            created_at=utc_now_iso(),
        )
    )
    assert progress.should_speak is False

    blocked = await session.ingest_agent_event(
        AgentEvent(
            event_id="event-2",
            task_id=sent.task_id,
            agent_id="codex",
            type="agent.blocked",
            message="Codex needs the prototype URL.",
            importance=AgentEventImportance.HIGH,
            delivery=AgentEventDelivery.SHORT_VOICE,
            created_at=utc_now_iso(),
        )
    )
    assert blocked.should_speak is True
    assert blocked.response_text == "Codex needs the prototype URL."


@pytest.mark.anyio
async def test_targeted_convoai_style_message_does_not_ask_which_bro():
    def targeted_reply(context):
        assert context.target_persona_id == "persona-forge"
        return ScriptedPlan(reply_override="Forge can help draft that plan.")

    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({"__default__": targeted_reply}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
    )
    session.set_voice_target("persona-forge")

    _message_id, completion = await session.submit_message(
        "convoai-test",
        "I may need you to help me draft the plan",
        source="connector",
        target_persona_id=session.voice_target_persona_id,
        start_processing=False,
    )
    session.start_message_processing()
    result = await completion

    assert result.reply_text == "Forge can help draft that plan."
    assert "which bro" not in result.reply_text.lower()
    assert session.voice_target_persona_id == "persona-forge"
