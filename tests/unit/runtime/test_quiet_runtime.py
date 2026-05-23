from __future__ import annotations

import asyncio

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


class CountingClassifier:
    def __init__(self, classification: InteractionClassification) -> None:
        self.classification = classification
        self.calls: list[str] = []

    async def classify(self, *, text: str, state):
        self.calls.append(text)
        return self.classification


class DelayedCountingClassifier(CountingClassifier):
    def __init__(self, classification: InteractionClassification, *, delay_seconds: float = 0.05) -> None:
        super().__init__(classification)
        self.delay_seconds = delay_seconds

    async def classify(self, *, text: str, state):
        self.calls.append(text)
        await asyncio.sleep(self.delay_seconds)
        return self.classification


class CountingDraftRewriter(DeterministicDraftRewriter):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def rewrite(self, payload, *, on_text_delta=None):
        self.calls.append(payload.new_turn.raw_text)
        return await super().rewrite(payload, on_text_delta=on_text_delta)


class StreamingDraftRewriter(DeterministicDraftRewriter):
    async def rewrite(self, payload, *, on_text_delta=None):
        if on_text_delta is not None:
            maybe_awaitable = on_text_delta("Preview ")
            if maybe_awaitable is not None:
                await maybe_awaitable
            maybe_awaitable = on_text_delta("draft")
            if maybe_awaitable is not None:
                await maybe_awaitable
        return await super().rewrite(payload, on_text_delta=None)


async def _drain_live_partial(session) -> None:
    await asyncio.sleep(0)
    task = session._live_partial_task
    if task is not None:
        await task


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

    assert decision.should_speak is False
    assert decision.dispatch_plan_id
    assert decision.response_text == ""
    draft = session.draft_manager.active_session
    assert draft is not None
    assert draft.current_draft is not None
    assert draft.current_draft.task_spec is not None
    assert draft.current_draft.task_spec.mode == TaskMode.READ_ONLY_FIRST
    assert draft.current_revision_id == decision.draft_revision_id
    assert len(draft.asr_turns) == 0

    session.interaction_classifier = _classifier_for(InteractionType.CONFIRMATION)

    sent = await session.handle_runtime_message(text="confirm action", message_type="text")

    assert sent.should_speak is True
    assert sent.task_id
    task = await session.blackboard.get_task(sent.task_id)
    assert task is not None
    assert task.metadata["source_kind"] == "draft_session"
    assert task.metadata["mode"] == "read_only_first"
    assert task.metadata["draft_revision_id"] == decision.draft_revision_id
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
async def test_live_classifier_cadence_refines_one_draft_without_durable_asr_turns():
    classifier = CountingClassifier(
        InteractionClassification(
            interaction_type=InteractionType.DELEGATION,
            confidence=0.95,
            requires_user_decision=True,
            reason="test_live_delegation",
        )
    )
    rewriter = CountingDraftRewriter()
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(live_interaction_classifier_interval_seconds=1.0),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=rewriter,
        interaction_classifier=classifier,
    )

    first = await session.handle_runtime_message(
        text="Plan a trip to the US",
        message_type="stt_partial",
        timestamp_ms=0,
    )
    await _drain_live_partial(session)
    skipped = await session.handle_runtime_message(
        text="Plan a trip to the US actually",
        message_type="stt_partial",
        timestamp_ms=500,
    )
    corrected = await session.handle_runtime_message(
        text="Plan a trip to the US actually make it UK",
        message_type="stt_partial",
        timestamp_ms=1000,
    )
    await _drain_live_partial(session)
    final = await session.handle_runtime_message(
        text="Plan a trip to the US actually make it UK",
        message_type="stt_final",
        timestamp_ms=1100,
    )

    assert [first.should_speak, skipped.should_speak, corrected.should_speak, final.should_speak] == [False, False, False, False]
    assert [first.response_text, skipped.response_text, corrected.response_text, final.response_text] == ["", "", "", ""]
    assert classifier.calls == [
        "Plan a trip to the US",
        "Plan a trip to the US actually make it UK",
    ]
    assert rewriter.calls == [
        "Plan a trip to the US",
        "Plan a trip to the US actually make it UK",
    ]
    draft = session.draft_manager.active_session
    assert draft is not None
    assert draft.current_draft is not None
    assert draft.current_draft.text == "Plan a trip to the US actually make it UK."
    assert len(draft.asr_turns) == 0
    assert len(draft.snapshots) == 3
    assert draft.current_revision_id == final.draft_revision_id
    assert draft.live_source_boundary == "stt.final"
    assert draft.live_classification is not None
    assert draft.live_classification["interaction_type"] == "delegation"
    live_events = [
        event for event in session.observability.store.all()
        if event.event_name == "comm.live_draft.updated"
    ]
    assert live_events[-1].details["draft_revision_id"] == final.draft_revision_id
    assert live_events[-1].details["source_boundary"] == "stt.final"
    assert live_events[-1].details["draft_revision_number"] == 2
    stages = [
        event for event in session.observability.store.all()
        if event.event_name == "comm.live_draft.stage"
    ]
    assert any(event.details["stage"] == "final_checkpoint_reused" for event in stages)


@pytest.mark.anyio
async def test_live_draft_rewrite_streams_preview_to_subscribers():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(live_interaction_classifier_interval_seconds=1.0),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=StreamingDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.DELEGATION),
    )
    queue = session.subscribe()
    try:
        await session.handle_runtime_message(
            text="Plan a trip to the US with flights and hotels",
            message_type="stt_partial",
            timestamp_ms=0,
        )
        await _drain_live_partial(session)

        events = []
        while not queue.empty():
            events.append(await queue.get())
        draft_events = [event for event in events if event.type.startswith("draft_output_")]

        assert [event.type for event in draft_events[:4]] == [
            "draft_output_started",
            "draft_output_delta",
            "draft_output_delta",
            "draft_output_completed",
        ]
        assert all(event.request_id == "live-draft-1" for event in draft_events)
        assert [draft_events[1].delta, draft_events[2].delta] == ["Preview ", "draft"]
        assert draft_events[3].draft_text == "Plan a trip to the US with flights and hotels."
    finally:
        session.unsubscribe(queue)


@pytest.mark.anyio
async def test_live_partial_worker_discards_cancelled_stale_work():
    classifier = DelayedCountingClassifier(
        InteractionClassification(
            interaction_type=InteractionType.DELEGATION,
            confidence=0.95,
            requires_user_decision=True,
            reason="test_latest_wins",
        )
    )
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(live_interaction_classifier_interval_seconds=1.0),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=classifier,
    )

    first = await session.handle_runtime_message(
        text="Plan a trip",
        message_type="stt_partial",
        timestamp_ms=0,
    )
    second = await session.handle_runtime_message(
        text="Plan a trip to California with flights and hotels",
        message_type="stt_partial",
        timestamp_ms=1000,
    )
    await _drain_live_partial(session)

    assert [first.should_speak, second.should_speak] == [False, False]
    draft = session.draft_manager.active_session
    assert draft is not None
    assert draft.current_draft is not None
    assert draft.current_draft.text == "Plan a trip to California with flights and hotels."
    assert len(draft.snapshots) == 1
    assert draft.live_source_boundary == "stt.partial"
    cancelled = [
        event for event in session.observability.store.all()
        if event.event_name == "comm.live_draft.stage"
        and event.details["stage"] == "cancelled"
    ]
    assert cancelled


@pytest.mark.anyio
async def test_send_rejects_stale_draft_revision():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel({}),
        settings=Settings(),
        executor_node_manager=ExecutorNodeManager(detached_executor_types=[]),
        draft_rewriter=DeterministicDraftRewriter(),
        interaction_classifier=_classifier_for(InteractionType.DELEGATION),
    )

    first = await session.handle_runtime_message(
        text="Ask Codex to inspect alpha.",
        message_type="stt_final",
        timestamp_ms=0,
    )
    stale_revision = first.draft_revision_id
    second = await session.handle_runtime_message(
        text="Ask Codex to inspect beta.",
        message_type="stt_final",
        timestamp_ms=1000,
    )

    assert stale_revision is not None
    assert second.draft_revision_id != stale_revision
    with pytest.raises(ValueError, match="Draft revision"):
        await session.confirm_active_dispatch(draft_revision_id=stale_revision)

    sent = await session.confirm_active_dispatch(draft_revision_id=second.draft_revision_id)
    assert sent.task_id is not None
    task = await session.blackboard.get_task(sent.task_id)
    assert task is not None
    assert task.metadata["draft_revision_id"] == second.draft_revision_id


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
    await _drain_live_partial(session)
    assert session.draft_manager.active_session is not None
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

    assert final.should_speak is False
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
