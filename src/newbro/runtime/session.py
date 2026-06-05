from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import replace
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from newbro.blackboard import InMemoryBlackboard
from newbro.communication import CommunicationBrain
from newbro.communication.persona_pool import (
    create_workspace,
    load_personas_from_file,
)
from newbro.communication.history import InMemoryConversationHistory
from newbro.communication.interaction_classifier import (
    InteractionClassification,
    InteractionClassifier,
    InteractionClassifierState,
    UnavailableInteractionClassifier,
)
from newbro.communication.model import CommunicationModel, LlmTraceRecord, ToolCallRecord
from newbro.communication.tools import build_default_tool_registry
from newbro.communication.types import CommunicationTurnResult
from newbro.executors.adapters.hosted import HostedExecutor
from newbro.executors.adapters.codex.session import CodexExecutorSession
from newbro.execution import ExecutionBrain
from newbro.executors.adapters.mock import MockExecutor
from newbro.executors.core import ExecutorRegistry, UnknownExecutorError
from newbro.interaction import InteractionManager, InteractionResolution
from newbro.interaction.sanitization import (
    sanitize_interaction_request_details,
    sanitize_interaction_request_opaque,
)
from newbro.notification import NotificationManager
from newbro.observability.bootstrap import SessionObservability, build_session_observability
from newbro.observability.context import bind_diagnostic_context
from newbro.observability.reason_codes import COMMUNICATION_MODEL_FAILURE
from newbro.protocol import (
    AgentEvent,
    AgentEventDelivery,
    AgentEventImportance,
    AgoraVoiceEvent,
    AgoraVoiceEventType,
    AgentResumeHandle,
    AttentionItemKind,
    BroThread,
    BroTimelineMessage,
    BroTimelinePlan,
    BroTimelineTask,
    BroTimelineTurn,
    CodexThreadEventMessage,
    CodexThreadListItem,
    CodexTurnEventMessage,
    DispatchGateOutcome,
    BindingStatus,
    ExecutionMode,
    ExecutionRun,
    ExecutionSession,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    InteractionType,
    InteractionRequest,
    InteractionRequestKind,
    MutationType,
    NativeReasoningStep,
    NotificationDeliveryStatus,
    OutboundTurnRequest,
    RunStatus,
    RuntimeDecision,
    RuntimeSessionState,
    UiUpdate,
    TaskCommand,
    TaskCommandType,
    TaskExecutionMode,
    TaskMutation,
    TaskMode,
    TaskStatus,
    TaskSummary,
    Task,
)

from .config import Settings
from .bro_detail_thread_projection import BroDetailThreadProjection
from .direct_executor import DirectExecutorInteraction
from .drafts import (
    DEFAULT_BRO_ID,
    DraftRewriter,
    DraftSessionManager,
    build_dispatch_plan,
    dispatch_gate,
)
from .executor_node_manager import ExecutorNodeManager
from .models import (
    ActionAcceptedStreamEvent,
    ActionRejectedStreamEvent,
    AssistantResponseCompletedStreamEvent,
    AssistantResponseDeltaStreamEvent,
    AssistantResponseFailedStreamEvent,
    AssistantResponseStartedStreamEvent,
    ConversationAppendedStreamEvent,
    ConversationHistoryEntryModel,
    ConversationSnapshot,
    DraftOutputCompletedStreamEvent,
    DraftOutputDeltaStreamEvent,
    DraftOutputFailedStreamEvent,
    DraftOutputStartedStreamEvent,
    SessionSnapshot,
    SessionStreamEventBase,
    SnapshotStreamEvent,
    UserMessageAppendedStreamEvent,
)

from .bro_detail_thread_helpers import (
    _NATIVE_REASONING_PROJECT_STEPS,
    _NATIVE_REASONING_PROJECT_TURNS,
    _NATIVE_REASONING_STORE_STEPS,
    _NATIVE_REASONING_STORE_TURNS,
    _NATIVE_REASONING_TEXT_LIMIT,
    _native_reasoning_key,
    _selected_plan_option_label,
    _title_from_draft_text,
)


FALLBACK_ASSISTANT_ERROR_MESSAGE = "Sorry, something went wrong while generating the reply."
LOGGER = logging.getLogger(__name__)
PLAN_APPROVAL_VISIBLE_TEXT = "Implement it"
MAX_TASK_INSTRUCTION_CHARS = 4000


def _task_instruction_from_draft(draft) -> str:
    task_spec = getattr(draft, "task_spec", None)
    if task_spec is None:
        return draft.text
    constraints = "\n".join(f"- {item}" for item in task_spec.constraints)
    success = "\n".join(f"- {item}" for item in task_spec.success_criteria)
    stop_conditions = "\n".join(f"- {item}" for item in task_spec.stop_conditions)
    parts = [
        f"Task: {task_spec.goal}",
        f"Mode: {task_spec.mode.value}",
        f"Expected output: {task_spec.expected_output}",
    ]
    if constraints:
        parts.append(f"Constraints:\n{constraints}")
    if success:
        parts.append(f"Success criteria:\n{success}")
    if stop_conditions:
        parts.append(f"Stop conditions:\n{stop_conditions}")
    return "\n\n".join(parts)


def _runtime_state(*, has_draft: bool, active_tasks: list[Task]) -> RuntimeSessionState:
    if has_draft:
        return RuntimeSessionState.WAITING_FOR_CONFIRMATION
    if not active_tasks:
        return RuntimeSessionState.IDLE
    return _state_for_task(active_tasks[-1])


def _state_for_task(task: Task | None) -> RuntimeSessionState:
    if task is None:
        return RuntimeSessionState.IDLE
    if task.status == TaskStatus.WAITING_USER_INPUT:
        return RuntimeSessionState.TASK_BLOCKED
    if task.status == TaskStatus.COMPLETED:
        return RuntimeSessionState.TASK_COMPLETE
    if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED}:
        return RuntimeSessionState.TASK_RUNNING
    return RuntimeSessionState.IDLE


def _should_speak_for_classification(classification: InteractionClassification) -> bool:
    if classification.requires_user_decision:
        return True
    return classification.importance == "urgent"


def _classification_response_text(classification: InteractionClassification) -> str:
    if not _should_speak_for_classification(classification):
        return ""
    if classification.interaction_type == InteractionType.UNCERTAIN:
        return "I need a clearer instruction."
    return ""


def _should_speak_for_draft_decision(
    *,
    interaction: InteractionType,
    classification: InteractionClassification,
    gate: DispatchGateResult,
) -> bool:
    if gate.outcome in {DispatchGateOutcome.ASK_CLARIFICATION, DispatchGateOutcome.REJECT}:
        return True
    if classification.requires_user_decision:
        return True
    return interaction == InteractionType.DELEGATION and gate.outcome == DispatchGateOutcome.ASK_CONFIRMATION


@dataclass(slots=True)
class PendingMessageRequest:
    request_id: str
    user_text: str
    completion: asyncio.Future[CommunicationTurnResult]
    target_persona_id: str | None = None


@dataclass(slots=True)
class LiveTranscriptWork:
    generation: int
    text: str
    language: str | None
    timestamp_ms: int | None
    assigned_bro_id: str | None
    source_boundary: Literal["stt.partial", "stt.final"]
    scheduled_at: float


@dataclass(slots=True)
class SessionRuntime:
    session_id: str
    blackboard: InMemoryBlackboard
    history: InMemoryConversationHistory
    registry: ExecutorRegistry
    communication_brain: CommunicationBrain
    execution_brain: ExecutionBrain
    notification_manager: NotificationManager
    interaction_manager: InteractionManager
    observability: SessionObservability
    executor_node_manager: ExecutorNodeManager
    interaction_classifier: InteractionClassifier = field(default_factory=UnavailableInteractionClassifier)
    live_interaction_classifier_interval_seconds: float = 1.0
    default_executor_type: str = "mock"
    draft_manager: DraftSessionManager = field(default_factory=DraftSessionManager)
    subscribers: list[asyncio.Queue[SessionStreamEventBase]] = field(default_factory=list)
    _message_queue: asyncio.Queue[PendingMessageRequest] = field(default_factory=asyncio.Queue)
    _execution_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _communication_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _notification_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _snapshot_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _diagnostic_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _blackboard_queue: asyncio.Queue | None = field(default=None, init=False, repr=False)
    _notification_blackboard_queue: asyncio.Queue | None = field(default=None, init=False, repr=False)
    _diagnostic_blackboard_queue: asyncio.Queue | None = field(default=None, init=False, repr=False)
    _notification_wakeup: asyncio.Event = field(default_factory=asyncio.Event)
    _next_sequence: int = field(default=1, init=False, repr=False)
    _active_assistant_turns: int = field(default=0, init=False, repr=False)
    _diagnostic_seen_entities: set[tuple[str, str | None]] = field(default_factory=set, init=False, repr=False)
    _voice_target_persona_id: str | None = field(default=None, init=False, repr=False)
    _last_live_classifier_ms: int | None = field(default=None, init=False, repr=False)
    _latest_live_transcript: str = field(default="", init=False, repr=False)
    _live_generation: int = field(default=0, init=False, repr=False)
    _latest_published_live_text: str = field(default="", init=False, repr=False)
    _live_partial_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _live_partial_work: LiveTranscriptWork | None = field(default=None, init=False, repr=False)
    _last_spoken_confirmation_draft_session_id: str | None = field(default=None, init=False, repr=False)
    _last_spoken_confirmation_revision_id: str | None = field(default=None, init=False, repr=False)
    _native_turn_reasoning: dict[str, list[NativeReasoningStep]] = field(default_factory=dict, init=False, repr=False)
    direct_executor: DirectExecutorInteraction | None = field(default=None, init=False, repr=False)
    bro_detail_thread_projection: BroDetailThreadProjection | None = field(default=None, init=False, repr=False)

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
        self.observability.logger.emit_event(
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

    def _direct_executor(self) -> DirectExecutorInteraction:
        if self.direct_executor is None:
            projection = self._bro_detail_thread_projection()
            self.direct_executor = DirectExecutorInteraction(
                session_id=self.session_id,
                blackboard=self.blackboard,
                executor_node_manager=self.executor_node_manager,
                bro_detail_thread_projection=projection,
                publish_snapshot=lambda: self.publish_snapshot(sync_imported_codex_threads=False),
                observability=self.observability,
            )
        return self.direct_executor

    def _bro_detail_thread_projection(self) -> BroDetailThreadProjection:
        if self.bro_detail_thread_projection is None:
            self.bro_detail_thread_projection = BroDetailThreadProjection(
                session_id=self.session_id,
                blackboard=self.blackboard,
                executor_node_manager=self.executor_node_manager,
                interaction_manager=self.interaction_manager,
                observability=self.observability,
                publish_snapshot=lambda: self.publish_snapshot(sync_imported_codex_threads=False),
                record_native_turn_reasoning=self._record_native_turn_reasoning,
            )
        return self.bro_detail_thread_projection

    async def snapshot(self, *, sync_imported_codex_threads: bool = True) -> SessionSnapshot:
        tasks = await self.blackboard.list_tasks()
        sessions = await self.blackboard.list_sessions()
        runs = await self.blackboard.list_runs()
        execution_modes = await self.blackboard.list_execution_modes()
        notification_candidates = await self.blackboard.list_notification_candidates()
        outbound_turn_requests = await self.blackboard.list_outbound_turn_requests()
        bindings = await self.blackboard.list_bindings()
        interaction_requests = await self.blackboard.list_interaction_requests()
        sanitized_interaction_requests = [
            request.model_copy(
                update={
                    "opaque": sanitize_interaction_request_opaque(request.opaque),
                    "details": sanitize_interaction_request_details(request.details),
                }
            )
            for request in interaction_requests
        ]
        attention_items = await self.blackboard.list_attention_items()
        recent_execution_details = await self.blackboard.list_recent_task_execution_details(
            task_limit=10,
            entry_limit=8,
        )
        summaries = [
            summary
            for summary in [await self.blackboard.get_summary(task.task_id) for task in tasks]
            if summary is not None
        ]
        personas = await self.blackboard.list_personas()
        bro_detail_projection = await self._bro_detail_thread_projection().snapshot_parts(
            tasks=tasks,
            sessions=sessions,
            runs=runs,
            summaries=summaries,
            personas=personas,
            sync_imported_codex_threads=sync_imported_codex_threads,
        )
        bro_detail_threads = self._bro_detail_thread_projection()
        return SessionSnapshot(
            session_id=self.session_id,
            voice_target_persona_id=self._voice_target_persona_id,
            tasks=tasks,
            execution_sessions=sessions,
            execution_runs=runs,
            execution_modes=execution_modes,
            bindings=bindings,
            summaries=summaries,
            notification_candidates=notification_candidates,
            outbound_turn_requests=outbound_turn_requests,
            bro_threads=bro_detail_projection.bro_threads,
            bro_timeline_turns=bro_detail_projection.bro_timeline_turns,
            bro_thread_pages=dict(bro_detail_threads.imported_codex_thread_page_info),
            bro_timeline_pages=dict(bro_detail_threads.bro_thread_timeline_page_info),
            personas=personas,
            interaction_requests=sanitized_interaction_requests,
            attention_items=attention_items,
            agent_events=await self.blackboard.list_agent_events(),
            executor_capabilities=self._executor_capabilities_snapshot(),
            executor_nodes=await self.executor_node_manager.list_nodes(),
            recent_execution_details=recent_execution_details,
            recent_native_turn_reasoning=self._recent_native_turn_reasoning(),
            draft_session=self.draft_manager.active_session,
        )

    async def list_bro_thread_page(
        self,
        *,
        target_persona_id: str,
        limit: int = 25,
        cursor: str | None = None,
    ):
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        return await self._bro_detail_thread_projection().list_bro_thread_page(
            persona=persona,
            sessions=await self.blackboard.list_sessions(),
            limit=limit,
            cursor=cursor,
        )

    async def list_bro_timeline_page(
        self,
        *,
        target_persona_id: str,
        thread_id: str,
        limit: int = 100,
        cursor: str | None = None,
    ):
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        node_id = persona.executor_node_id
        if not node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        return await self._bro_detail_thread_projection().list_bro_timeline_page(
            persona=persona,
            public_thread_id=thread_id,
            node_id=node_id,
            limit=limit,
            cursor=cursor,
        )

    async def open_bro_thread(
        self,
        *,
        target_persona_id: str,
        thread_id: str,
    ) -> SessionSnapshot:
        return await self._bro_detail_thread_projection().open_bro_thread(
            target_persona_id=target_persona_id,
            thread_id=thread_id,
        )

    async def close_bro_thread(
        self,
        *,
        target_persona_id: str,
        thread_id: str | None = None,
    ) -> SessionSnapshot:
        return await self._bro_detail_thread_projection().close_bro_thread(
            target_persona_id=target_persona_id,
            thread_id=thread_id,
        )

    async def handle_codex_thread_event(self, message: CodexThreadEventMessage) -> None:
        await self._bro_detail_thread_projection().handle_codex_thread_event(message)

    async def handle_codex_turn_event(self, message: CodexTurnEventMessage) -> None:
        await self._bro_detail_thread_projection().handle_codex_turn_event(message)

    def _record_native_turn_reasoning(
        self,
        request: OutboundTurnRequest,
        message: CodexTurnEventMessage,
        timestamp: str,
    ) -> None:
        event_type = message.event_type.lower()
        if event_type not in {"progress", "plan"}:
            return
        # The final answer is rendered as the settled answer bubble, not a
        # reasoning step; only commentary / intermediate narration is a step.
        if message.metadata.get("phase") == "final_answer":
            return
        text = (message.message or "").strip()
        if not text:
            return
        executor_thread_id = message.executor_thread_id or request.executor_thread_id
        executor_turn_id = message.executor_turn_id or request.executor_turn_id
        key = _native_reasoning_key(request.executor_id, executor_thread_id, executor_turn_id)
        if key is None:
            return
        raw_item_id = message.metadata.get("codex_item_id")
        item_id = raw_item_id if isinstance(raw_item_id, str) else ""
        if not item_id:
            return  # id-less events (e.g. the dispatch marker) are not real steps
        step = NativeReasoningStep(
            item_id=item_id,
            text=text[:_NATIVE_REASONING_TEXT_LIMIT],
            kind="plan" if event_type == "plan" else "progress",
            created_at=timestamp,
        )
        steps = list(self._native_turn_reasoning.get(key, []))
        if steps and steps[-1].item_id == item_id:
            steps[-1] = step  # same codex item streaming -> grow in place
        else:
            steps.append(step)
        steps = steps[-_NATIVE_REASONING_STORE_STEPS:]
        self._native_turn_reasoning.pop(key, None)
        self._native_turn_reasoning[key] = steps
        while len(self._native_turn_reasoning) > _NATIVE_REASONING_STORE_TURNS:
            oldest = next(iter(self._native_turn_reasoning))
            self._native_turn_reasoning.pop(oldest, None)

    def _record_interaction_answer_turn(
        self,
        request: InteractionRequest,
        *,
        user_visible_text: str | None,
        client_request_id: str | None,
    ) -> None:
        text = (user_visible_text or "").strip()
        if not text:
            return
        details = request.details or {}
        thread_id = details.get("target_thread_id")
        persona_id = details.get("persona_id")
        if not isinstance(thread_id, str) or not thread_id:
            return
        if not isinstance(persona_id, str) or not persona_id:
            return
        timestamp = datetime.now(tz=UTC).isoformat()
        stable_key = client_request_id or request.request_id
        turn = BroTimelineTurn(
            turn_id=f"{thread_id}:answer:{stable_key}",
            thread_id=thread_id,
            persona_id=persona_id,
            executor_id=request.executor_type or "codex",
            owner="executor",
            client_request_id=client_request_id,
            input_modality="text",
            user=BroTimelineMessage(
                message_id=f"{thread_id}:{stable_key}:user",
                role="user",
                kind="text",
                text=text,
                created_at=timestamp,
                updated_at=timestamp,
                status="completed",
                metadata={"source": "native_interaction_answer"},
            ),
            status="completed",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"source": "native_interaction_answer", "request_id": request.request_id},
        )
        self._bro_detail_thread_projection().upsert_bro_thread_executor_turn(turn)

    def _recent_native_turn_reasoning(self) -> dict[str, list[NativeReasoningStep]]:
        if not self._native_turn_reasoning:
            return {}
        keys = list(self._native_turn_reasoning.keys())[-_NATIVE_REASONING_PROJECT_TURNS:]
        return {
            key: self._native_turn_reasoning[key][-_NATIVE_REASONING_PROJECT_STEPS:]
            for key in keys
        }

    @property
    def voice_target_persona_id(self) -> str | None:
        return self._voice_target_persona_id

    def set_voice_target(self, persona_id: str | None) -> None:
        self._voice_target_persona_id = persona_id

    async def submit_executor_text_instruction(
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
        return await self._direct_executor().submit_text_instruction(
            target_persona_id=target_persona_id,
            text=text,
            target_thread_id=target_thread_id,
            create_new_thread=create_new_thread,
            workspace_id=workspace_id,
            client_request_id=client_request_id,
            plan_mode=plan_mode,
        )

    async def handle_executor_audio_transcript_event(self, run_id: str, metadata: dict[str, object]) -> None:
        await self._direct_executor().handle_audio_transcript_event(run_id, metadata)

    async def submit_executor_audio_instruction(
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
        return await self._direct_executor().submit_audio_instruction(
            target_persona_id=target_persona_id,
            target_thread_id=target_thread_id,
            create_new_thread=create_new_thread,
            workspace_id=workspace_id,
            client_request_id=client_request_id,
            pcm16=pcm16,
            mime_type=mime_type,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
        )

    async def _active_codex_execution_for_persona(
        self,
        persona_id: str,
        *,
        target_thread_id: str | None = None,
    ) -> tuple[ExecutionSession | None, ExecutionRun | None]:
        return await self._direct_executor()._active_codex_execution_for_persona(
            persona_id,
            target_thread_id=target_thread_id,
        )

    async def conversation_snapshot(self) -> ConversationSnapshot:
        history = [
            ConversationHistoryEntryModel(
                role=entry.role,
                text=entry.text,
                message_id=entry.message_id,
                created_at=entry.created_at,
            )
            for entry in self.history.get_recent(self.session_id, limit=50)
        ]
        return ConversationSnapshot(
            session_id=self.session_id,
            conversation_history=history,
        )

    def diagnostic_timeline(
        self,
        *,
        after_sequence: int | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        execution_session_id: str | None = None,
        notification_id: str | None = None,
        request_id: str | None = None,
        event_prefix: str | None = None,
        min_level: str | None = None,
        limit: int = 200,
    ):
        return self.observability.store.query(
            after_sequence=after_sequence,
            task_id=task_id,
            run_id=run_id,
            execution_session_id=execution_session_id,
            notification_id=notification_id,
            request_id=request_id,
            event_prefix=event_prefix,
            min_level=min_level,
            limit=limit,
        )

    def subscribe(self) -> asyncio.Queue[SessionStreamEventBase]:
        queue: asyncio.Queue[SessionStreamEventBase] = asyncio.Queue()
        self.subscribers.append(queue)
        self._ensure_snapshot_pump()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[SessionStreamEventBase]) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)
        if not self.subscribers and self._snapshot_task is not None:
            self._snapshot_task.cancel()

    async def publish_snapshot(self, *, sync_imported_codex_threads: bool = False) -> SessionSnapshot:
        snapshot = await self.snapshot(sync_imported_codex_threads=sync_imported_codex_threads)
        await self._broadcast_event(self._snapshot_event(snapshot))
        return snapshot

    async def initial_snapshot_event(self) -> SnapshotStreamEvent:
        return self._snapshot_event(await self.snapshot(sync_imported_codex_threads=False))

    async def publish_private_event(
        self,
        queue: asyncio.Queue[SessionStreamEventBase],
        event: SessionStreamEventBase,
    ) -> None:
        await queue.put(event)

    async def submit_message(
        self,
        request_id: str,
        user_text: str,
        *,
        source: Literal["user", "connector"] = "user",
        target_persona_id: str | None = None,
        start_processing: bool = True,
    ) -> tuple[str, asyncio.Future[CommunicationTurnResult]]:
        user_entry = self.communication_brain.append_user_message(self.session_id, user_text)
        await self._broadcast_user_message_append(
            message_id=user_entry.message_id,
            text=user_text,
            source=source,
        )
        completion = asyncio.get_running_loop().create_future()
        await self._message_queue.put(
            PendingMessageRequest(
                request_id=request_id,
                user_text=user_text,
                completion=completion,
                target_persona_id=target_persona_id,
            )
        )
        self._wake_notification_pump()
        if start_processing:
            self._ensure_communication_pump()
        return user_entry.message_id, completion

    def start_message_processing(self) -> None:
        self._ensure_communication_pump()

    def start_notification_processing(self) -> None:
        self._ensure_notification_pump()

    def action_accepted_event(
        self,
        request_id: str,
        *,
        action_type: str,
    ) -> ActionAcceptedStreamEvent:
        return ActionAcceptedStreamEvent(
            sequence=self._next_event_sequence(),
            request_id=request_id,
            action_type=action_type,
        )

    def action_rejected_event(
        self,
        request_id: str,
        *,
        action_type: str,
        error_code: str,
        message: str,
    ) -> ActionRejectedStreamEvent:
        return ActionRejectedStreamEvent(
            sequence=self._next_event_sequence(),
            request_id=request_id,
            action_type=action_type,
            error_code=error_code,
            message=message,
        )

    def schedule_execution(self) -> None:
        # Keep one runtime execution loop active; it drains newly queued work
        # after the current executor run releases.
        if self._execution_task is not None and not self._execution_task.done():
            return
        self._execution_task = asyncio.create_task(self._run_execution_loop())

    async def append_asr_turn_to_draft(
        self,
        *,
        raw_text: str,
        normalized_text: str | None = None,
        confidence: float | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        assigned_bro_id: str | None = None,
        on_text_delta=None,
    ):
        return await self.draft_manager.append_asr_turn(
            raw_text=raw_text,
            normalized_text=normalized_text,
            confidence=confidence,
            started_at=started_at,
            ended_at=ended_at,
            assigned_bro_id=assigned_bro_id,
            on_text_delta=on_text_delta,
        )

    async def update_live_transcript_draft(
        self,
        *,
        raw_text: str,
        normalized_text: str | None = None,
        confidence: float | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        assigned_bro_id: str | None = None,
        source_boundary: str,
        transcript_timestamp_ms: int | None = None,
        classification: InteractionClassification | None = None,
        on_text_delta=None,
    ):
        return await self.draft_manager.update_live_draft(
            raw_text=raw_text,
            normalized_text=normalized_text,
            confidence=confidence,
            started_at=started_at,
            ended_at=ended_at,
            assigned_bro_id=assigned_bro_id,
            source_boundary=source_boundary,
            transcript_timestamp_ms=transcript_timestamp_ms,
            classification=classification.model_dump(mode="json") if classification is not None else None,
            on_text_delta=on_text_delta,
        )

    def _live_classifier_due(self, *, text: str, timestamp_ms: int | None) -> bool:
        normalized = " ".join(text.strip().split())
        if not normalized:
            return False
        if normalized == self._latest_live_transcript and self._last_live_classifier_ms is not None:
            return False
        if self._last_live_classifier_ms is None:
            return True
        if timestamp_ms is None:
            return True
        interval_ms = max(0, int(self.live_interaction_classifier_interval_seconds * 1000))
        return timestamp_ms - self._last_live_classifier_ms >= interval_ms

    def _mark_live_classifier_ran(self, *, text: str, timestamp_ms: int | None) -> None:
        self._latest_live_transcript = " ".join(text.strip().split())
        if timestamp_ms is not None:
            self._last_live_classifier_ms = timestamp_ms

    def _live_text_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def _emit_live_stage(
        self,
        *,
        work: LiveTranscriptWork,
        stage: str,
        started_at: float | None = None,
        outcome: str | None = None,
        stale: bool = False,
    ) -> None:
        self.observability.communication.live_draft_stage(
            conversation_id=self.session_id,
            stage=stage,
            source_boundary=work.source_boundary,
            generation=work.generation,
            transcript_timestamp_ms=work.timestamp_ms,
            text_length=len(work.text),
            text_hash=self._live_text_hash(work.text),
            latency_ms=int((time.perf_counter() - started_at) * 1000) if started_at is not None else None,
            outcome=outcome,
            stale=stale,
        )

    def _next_live_work(
        self,
        *,
        text: str,
        language: str | None,
        timestamp_ms: int | None,
        assigned_bro_id: str | None,
        source_boundary: Literal["stt.partial", "stt.final"],
    ) -> LiveTranscriptWork:
        self._live_generation += 1
        return LiveTranscriptWork(
            generation=self._live_generation,
            text=text,
            language=language,
            timestamp_ms=timestamp_ms,
            assigned_bro_id=assigned_bro_id,
            source_boundary=source_boundary,
            scheduled_at=time.perf_counter(),
        )

    def _live_draft_request_id(self, work: LiveTranscriptWork) -> str:
        return f"live-draft-{work.generation}"

    def _should_speak_for_live_draft_decision(
        self,
        *,
        work: LiveTranscriptWork,
        interaction: InteractionType,
        classification: InteractionClassification,
        gate: DispatchGateResult,
        draft_session_id: str | None,
        draft_revision_id: str | None,
    ) -> bool:
        should_speak = _should_speak_for_draft_decision(
            interaction=interaction,
            classification=classification,
            gate=gate,
        )
        if (
            not should_speak
            and interaction == InteractionType.DRAFT_CORRECTION
            and gate.outcome == DispatchGateOutcome.ASK_CONFIRMATION
        ):
            should_speak = True
        if not should_speak:
            return False
        if gate.outcome != DispatchGateOutcome.ASK_CONFIRMATION:
            return True
        if work.source_boundary == "stt.partial":
            return False
        if draft_session_id is not None:
            if self._last_spoken_confirmation_draft_session_id != draft_session_id:
                self._last_spoken_confirmation_draft_session_id = draft_session_id
                self._last_spoken_confirmation_revision_id = draft_revision_id
                return True
            if (
                interaction == InteractionType.DRAFT_CORRECTION
                and draft_revision_id is not None
                and self._last_spoken_confirmation_revision_id != draft_revision_id
            ):
                self._last_spoken_confirmation_revision_id = draft_revision_id
                return True
            if self._last_spoken_confirmation_draft_session_id == draft_session_id:
                return False
        if draft_revision_id is None:
            return True
        return True

    async def _broadcast_live_draft_started(self, work: LiveTranscriptWork) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputStartedStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
            )
        )

    async def _broadcast_live_draft_delta(self, work: LiveTranscriptWork, delta: str) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputDeltaStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
                delta=delta,
            )
        )

    async def _broadcast_live_draft_completed(self, work: LiveTranscriptWork, *, draft_session_id: str, draft_text: str) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputCompletedStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
                draft_session_id=draft_session_id,
                draft_text=draft_text,
            )
        )

    async def _broadcast_live_draft_failed(self, work: LiveTranscriptWork, message: str) -> None:
        if not self.subscribers:
            return
        await self._broadcast_event(
            DraftOutputFailedStreamEvent(
                sequence=self._next_event_sequence(),
                request_id=self._live_draft_request_id(work),
                message=message,
            )
        )

    def _cancel_live_partial_task(self) -> None:
        if self._live_partial_task is not None and not self._live_partial_task.done():
            if self._live_partial_work is not None:
                self._emit_live_stage(work=self._live_partial_work, stage="cancelled", stale=True)
            self._live_partial_task.cancel()

    def _schedule_live_partial_work(
        self,
        *,
        text: str,
        language: str | None,
        timestamp_ms: int | None,
        assigned_bro_id: str | None,
    ) -> LiveTranscriptWork:
        work = self._next_live_work(
            text=text,
            language=language,
            timestamp_ms=timestamp_ms,
            assigned_bro_id=assigned_bro_id,
            source_boundary="stt.partial",
        )
        self._mark_live_classifier_ran(text=text, timestamp_ms=timestamp_ms)
        self._cancel_live_partial_task()
        self._emit_live_stage(work=work, stage="scheduled")
        self._live_partial_work = work
        self._live_partial_task = asyncio.create_task(self._run_live_partial_work(work))
        return work

    async def _run_live_partial_work(self, work: LiveTranscriptWork) -> None:
        try:
            await self._process_live_transcript_work(work)
        except asyncio.CancelledError:
            self._emit_live_stage(work=work, stage="cancelled", stale=True)
            raise
        except Exception as exc:
            LOGGER.exception("Live partial draft update failed for %s", self.session_id)
            self.observability.communication.reply_failed(
                conversation_id=self.session_id,
                request_id=None,
                reason_code=COMMUNICATION_MODEL_FAILURE,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        finally:
            if asyncio.current_task() is self._live_partial_task:
                self._live_partial_task = None
                self._live_partial_work = None

    async def _process_live_transcript_work(self, work: LiveTranscriptWork) -> RuntimeDecision:
        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        has_draft = self.draft_manager.active_session is not None
        started_at = time.perf_counter()
        self._emit_live_stage(work=work, stage="classifier_started", started_at=work.scheduled_at)
        classification = await self.interaction_classifier.classify(
            text=work.text,
            state=InteractionClassifierState(
                has_draft=has_draft,
                active_task_count=len(active_tasks),
                target_persona_id=work.assigned_bro_id,
                voice_target_persona_id=self._voice_target_persona_id,
                language=work.language,
            ),
        )
        stale = work.generation != self._live_generation
        self._emit_live_stage(
            work=work,
            stage="classifier_completed",
            started_at=started_at,
            outcome=classification.interaction_type.value,
            stale=stale,
        )
        self.observability.communication.interaction_classified(
            conversation_id=self.session_id,
            interaction_type=classification.interaction_type.value,
            confidence=classification.confidence,
            requires_user_decision=classification.requires_user_decision,
            importance=classification.importance,
            reason=classification.reason,
            control_action=classification.control_action,
            task_mode=classification.task_mode.value if classification.task_mode is not None else None,
        )
        if stale:
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=classification.interaction_type,
                session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
            )

        interaction = classification.interaction_type
        if work.source_boundary == "stt.partial" and interaction not in {InteractionType.DELEGATION, InteractionType.DRAFT_CORRECTION}:
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=interaction,
                session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                ui_updates=[
                    UiUpdate(
                        type="transcript.partial",
                        payload={
                            "text": work.text,
                            "classifier_ran": True,
                            "interaction_type": interaction.value,
                            **({"language": work.language} if work.language else {}),
                        },
                    )
                ],
            )
        if interaction == InteractionType.CONFIRMATION:
            return await self.confirm_active_dispatch()
        if classification.control_action == "clear_draft":
            cleared = self.clear_draft()
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=interaction,
                session_state=RuntimeSessionState.IDLE,
                ui_updates=[UiUpdate(type="draft.cleared", payload={"draft_session_id": cleared.id if cleared else ""})],
            )
        if interaction == InteractionType.STATUS_QUERY:
            return await self.runtime_status_decision()
        if interaction == InteractionType.TASK_CONTROL:
            return await self.stop_active_task_decision(reason=work.text)
        if interaction in {InteractionType.DELEGATION, InteractionType.DRAFT_CORRECTION}:
            normalized = " ".join(work.text.strip().split())
            if work.source_boundary == "stt.partial" and normalized == self._latest_published_live_text:
                return RuntimeDecision(
                    should_speak=False,
                    response_text="",
                    interaction_type=interaction,
                    session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                )
            rewrite_started = time.perf_counter()
            self._emit_live_stage(work=work, stage="draft_rewrite_started", started_at=rewrite_started, outcome=interaction.value)
            await self._broadcast_live_draft_started(work)
            try:
                draft_session = await self.update_live_transcript_draft(
                    raw_text=work.text,
                    normalized_text=work.text,
                    assigned_bro_id=work.assigned_bro_id,
                    source_boundary=work.source_boundary,
                    transcript_timestamp_ms=work.timestamp_ms,
                    classification=classification,
                    on_text_delta=(
                        (lambda delta: self._broadcast_live_draft_delta(work, delta))
                        if self.subscribers
                        else None
                    ),
                )
            except Exception as exc:
                await self._broadcast_live_draft_failed(work, str(exc))
                raise
            self._latest_published_live_text = normalized
            draft = draft_session.current_draft
            if draft is None:
                raise ValueError("Draft manager did not produce a draft.")
            if classification.task_mode is not None and draft.task_spec is not None:
                draft.task_spec.mode = classification.task_mode
            plan = build_dispatch_plan(
                runtime_session_id=self.session_id,
                draft_session=draft_session,
                draft=draft,
            )
            draft_session.current_dispatch_plan = plan
            draft.missing_context = list(plan.missing_context)
            self._emit_live_stage(work=work, stage="draft_rewrite_completed", started_at=rewrite_started, outcome=interaction.value)
            await self._broadcast_live_draft_completed(
                work,
                draft_session_id=draft_session.id,
                draft_text=draft.text,
            )
            self.observability.communication.live_draft_updated(
                conversation_id=self.session_id,
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
                draft_revision_number=draft_session.current_revision_number,
                source_boundary=draft_session.live_source_boundary,
                transcript_timestamp_ms=draft_session.live_transcript_timestamp_ms,
                interaction_type=interaction.value,
            )
            gate = dispatch_gate(plan)
            await self.publish_snapshot()
            should_speak = self._should_speak_for_live_draft_decision(
                work=work,
                interaction=interaction,
                classification=classification,
                gate=gate,
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
            )
            return RuntimeDecision(
                should_speak=should_speak,
                response_text=(gate.question or "") if should_speak else "",
                interaction_type=interaction,
                session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
                ui_updates=[
                    *(
                        [
                            UiUpdate(
                                type="transcript.partial",
                                payload={
                                    "text": work.text,
                                    "classifier_ran": True,
                                    "interaction_type": interaction.value,
                                    **({"language": work.language} if work.language else {}),
                                },
                            )
                        ]
                        if work.source_boundary == "stt.partial"
                        else []
                    ),
                    UiUpdate(type="draft_card.updated", payload={"draft_session_id": draft_session.id, "draft_revision_id": draft_session.current_revision_id}),
                    UiUpdate(type="dispatch_plan.updated", payload={"plan_id": plan.plan_id, "draft_revision_id": draft_session.current_revision_id}),
                ],
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            dispatch_plan_id=plan.plan_id,
        )
        return RuntimeDecision(
            should_speak=_should_speak_for_classification(classification),
            response_text=_classification_response_text(classification),
            interaction_type=interaction,
            session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
        )

    async def _reuse_matching_live_draft_for_final(self, work: LiveTranscriptWork) -> RuntimeDecision | None:
        if work.source_boundary != "stt.final":
            return None
        normalized = " ".join(work.text.strip().split())
        if not normalized or normalized != self._latest_published_live_text:
            return None
        draft_session = self.draft_manager.active_session
        if draft_session is None or draft_session.current_draft is None or draft_session.current_revision_id is None:
            return None

        classification = (
            InteractionClassification.model_validate(draft_session.live_classification)
            if draft_session.live_classification is not None
            else None
        )
        draft_session = self.draft_manager.mark_live_checkpoint(
            source_boundary="stt.final",
            transcript_timestamp_ms=work.timestamp_ms,
            classification=draft_session.live_classification,
        )
        if draft_session is None or draft_session.current_draft is None:
            return None
        plan = draft_session.current_dispatch_plan or build_dispatch_plan(
            runtime_session_id=self.session_id,
            draft_session=draft_session,
            draft=draft_session.current_draft,
        )
        draft_session.current_dispatch_plan = plan
        self._emit_live_stage(
            work=work,
            stage="final_checkpoint_reused",
            started_at=work.scheduled_at,
            outcome=(classification.interaction_type.value if classification is not None else InteractionType.DELEGATION.value),
        )
        self.observability.communication.live_draft_updated(
            conversation_id=self.session_id,
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            draft_revision_number=draft_session.current_revision_number,
            source_boundary=draft_session.live_source_boundary,
            transcript_timestamp_ms=draft_session.live_transcript_timestamp_ms,
            interaction_type=(classification.interaction_type.value if classification is not None else InteractionType.DELEGATION.value),
        )
        await self.publish_snapshot()
        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        gate = dispatch_gate(plan)
        effective_classification = classification or InteractionClassification(
            interaction_type=InteractionType.DELEGATION,
            confidence=1.0,
            reason="final_checkpoint_reused",
        )
        interaction = effective_classification.interaction_type
        should_speak = self._should_speak_for_live_draft_decision(
            work=work,
            interaction=interaction,
            classification=effective_classification,
            gate=gate,
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
        )
        return RuntimeDecision(
            should_speak=should_speak,
            response_text=(gate.question or "") if should_speak else "",
            interaction_type=interaction,
            session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
            ui_updates=[
                UiUpdate(type="draft_card.updated", payload={"draft_session_id": draft_session.id, "draft_revision_id": draft_session.current_revision_id}),
                UiUpdate(type="dispatch_plan.updated", payload={"plan_id": plan.plan_id, "draft_revision_id": draft_session.current_revision_id}),
            ],
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            dispatch_plan_id=plan.plan_id,
        )

    async def handle_runtime_message(
        self,
        *,
        text: str,
        message_type: str = "text",
        language: str | None = None,
        timestamp_ms: int | None = None,
        assigned_bro_id: str | None = None,
    ) -> RuntimeDecision:
        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        has_draft = self.draft_manager.active_session is not None
        if message_type == "stt_partial":
            if not self._live_classifier_due(text=text, timestamp_ms=timestamp_ms):
                return RuntimeDecision(
                    should_speak=False,
                    response_text="",
                    interaction_type=InteractionType.COMMUNICATION,
                    session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                    ui_updates=[UiUpdate(type="transcript.partial", payload={"text": text, **({"language": language} if language else {})})],
                )
            work = self._schedule_live_partial_work(
                text=text,
                language=language,
                timestamp_ms=timestamp_ms,
                assigned_bro_id=assigned_bro_id,
            )
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=InteractionType.COMMUNICATION,
                session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
                ui_updates=[
                    UiUpdate(
                        type="transcript.partial",
                        payload={
                            "text": text,
                            "classifier_scheduled": True,
                            "generation": work.generation,
                            **({"language": language} if language else {}),
                        },
                    )
                ],
            )
        if message_type == "stt_final":
            self._cancel_live_partial_task()
            work = self._next_live_work(
                text=text,
                language=language,
                timestamp_ms=timestamp_ms,
                assigned_bro_id=assigned_bro_id,
                source_boundary="stt.final",
            )
            self._emit_live_stage(work=work, stage="scheduled")
            reused = await self._reuse_matching_live_draft_for_final(work)
            if reused is not None:
                return reused
            return await self._process_live_transcript_work(work)
        classification = await self.interaction_classifier.classify(
            text=text,
            state=InteractionClassifierState(
                has_draft=has_draft,
                active_task_count=len(active_tasks),
                target_persona_id=assigned_bro_id,
                voice_target_persona_id=self._voice_target_persona_id,
                language=language,
            ),
        )
        self.observability.communication.interaction_classified(
            conversation_id=self.session_id,
            interaction_type=classification.interaction_type.value,
            confidence=classification.confidence,
            requires_user_decision=classification.requires_user_decision,
            importance=classification.importance,
            reason=classification.reason,
            control_action=classification.control_action,
            task_mode=classification.task_mode.value if classification.task_mode is not None else None,
        )
        interaction = classification.interaction_type
        if interaction == InteractionType.CONFIRMATION:
            return await self.confirm_active_dispatch()
        if classification.control_action == "clear_draft":
            cleared = self.clear_draft()
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=interaction,
                session_state=RuntimeSessionState.IDLE,
                ui_updates=[UiUpdate(type="draft.cleared", payload={"draft_session_id": cleared.id if cleared else ""})],
            )
        if interaction == InteractionType.STATUS_QUERY:
            return await self.runtime_status_decision()
        if interaction == InteractionType.TASK_CONTROL:
            return await self.stop_active_task_decision(reason=text)
        if interaction in {InteractionType.DELEGATION, InteractionType.DRAFT_CORRECTION}:
            draft_session = await self.append_asr_turn_to_draft(
                raw_text=text,
                normalized_text=text,
                assigned_bro_id=assigned_bro_id,
            )
            draft = draft_session.current_draft
            if draft is None:
                raise ValueError("Draft manager did not produce a draft.")
            if classification.task_mode is not None and draft.task_spec is not None:
                draft.task_spec.mode = classification.task_mode
            plan = build_dispatch_plan(
                runtime_session_id=self.session_id,
                draft_session=draft_session,
                draft=draft,
            )
            draft_session.current_dispatch_plan = plan
            draft.missing_context = list(plan.missing_context)
            self.observability.communication.live_draft_updated(
                conversation_id=self.session_id,
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
                draft_revision_number=draft_session.current_revision_number,
                source_boundary=draft_session.live_source_boundary,
                transcript_timestamp_ms=draft_session.live_transcript_timestamp_ms,
                interaction_type=interaction.value,
            )
            gate = dispatch_gate(plan)
            await self.publish_snapshot()
            should_speak = _should_speak_for_draft_decision(
                interaction=interaction,
                classification=classification,
                gate=gate,
            )
            return RuntimeDecision(
                should_speak=should_speak,
                response_text=(gate.question or "") if should_speak else "",
                interaction_type=interaction,
                session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
                ui_updates=[
                    UiUpdate(type="draft_card.updated", payload={"draft_session_id": draft_session.id, "draft_revision_id": draft_session.current_revision_id}),
                    UiUpdate(type="dispatch_plan.updated", payload={"plan_id": plan.plan_id, "draft_revision_id": draft_session.current_revision_id}),
                ],
                draft_session_id=draft_session.id,
                draft_revision_id=draft_session.current_revision_id,
                dispatch_plan_id=plan.plan_id,
            )
        return RuntimeDecision(
            should_speak=_should_speak_for_classification(classification),
            response_text=_classification_response_text(classification),
            interaction_type=interaction,
            session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
        )

    async def handle_agora_event(self, event: AgoraVoiceEvent) -> RuntimeDecision:
        if event.session_id != self.session_id:
            raise ValueError("Agora voice event session_id does not match runtime session.")

        target_persona_id = event.target_persona_id or self._voice_target_persona_id
        if event.target_persona_id:
            self.set_voice_target(event.target_persona_id)

        if event.type == AgoraVoiceEventType.STT_PARTIAL:
            return await self.handle_runtime_message(
                text=event.text,
                message_type="stt_partial",
                language=event.language,
                timestamp_ms=event.timestamp_ms,
                assigned_bro_id=target_persona_id,
            )
        if event.type == AgoraVoiceEventType.STT_FINAL:
            return await self.handle_runtime_message(
                text=event.text,
                message_type="stt_final",
                language=event.language,
                timestamp_ms=event.timestamp_ms,
                assigned_bro_id=target_persona_id,
            )

        active_tasks = [
            task for task in await self.blackboard.list_tasks()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_USER_INPUT, TaskStatus.PAUSED}
        ]
        has_draft = self.draft_manager.active_session is not None
        update_type = f"agora.{event.type.value}"
        payload: dict[str, object] = {
            "event_id": event.event_id,
            "session_id": event.session_id,
        }
        if event.timestamp_ms is not None:
            payload["timestamp_ms"] = event.timestamp_ms
        if event.target_persona_id:
            payload["target_persona_id"] = event.target_persona_id
        if event.metadata:
            payload["metadata"] = event.metadata
        return RuntimeDecision(
            should_speak=False,
            response_text="",
            interaction_type=InteractionType.COMMUNICATION,
            session_state=_runtime_state(has_draft=has_draft, active_tasks=active_tasks),
            ui_updates=[UiUpdate(type=update_type, payload=payload)],
        )

    def clear_draft(self):
        return self.draft_manager.clear()

    async def confirm_active_dispatch(
        self,
        *,
        plan_id: str | None = None,
        draft_revision_id: str | None = None,
    ) -> RuntimeDecision:
        draft_session = self.draft_manager.active_session
        if draft_session is None or draft_session.current_draft is None:
            return RuntimeDecision(
                should_speak=False,
                response_text="",
                interaction_type=InteractionType.CONFIRMATION,
                session_state=RuntimeSessionState.IDLE,
            )
        plan = draft_session.current_dispatch_plan
        if plan_id is not None and (plan is None or plan.plan_id != plan_id):
            raise ValueError("Dispatch plan does not match the active draft.")
        if draft_revision_id is not None and draft_session.current_revision_id != draft_revision_id:
            raise ValueError("Draft revision does not match the active draft.")
        if plan is None:
            plan = build_dispatch_plan(
                runtime_session_id=self.session_id,
                draft_session=draft_session,
                draft=draft_session.current_draft,
            )
        confirmed = plan.model_copy(update={"user_confirmed": True})
        gate = dispatch_gate(confirmed)
        if gate.outcome != DispatchGateOutcome.DISPATCH:
            draft_session.current_dispatch_plan = confirmed
            return RuntimeDecision(
                should_speak=True,
                response_text=gate.question or "Cannot send yet.",
                interaction_type=InteractionType.CONFIRMATION,
                session_state=RuntimeSessionState.WAITING_FOR_CONFIRMATION,
                dispatch_plan_id=confirmed.plan_id,
            )
        draft_session.current_dispatch_plan = confirmed
        task = await self.send_draft(
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
        )
        await self.publish_snapshot()
        self.schedule_execution()
        return RuntimeDecision(
            should_speak=True,
            response_text=f"Sent to {confirmed.target_agent}.",
            interaction_type=InteractionType.CONFIRMATION,
            session_state=RuntimeSessionState.TASK_RUNNING,
            ui_updates=[
                UiUpdate(type="draft.cleared", payload={"draft_session_id": confirmed.draft_session_id}),
                UiUpdate(type="task.started", payload={"task_id": task.task_id}),
            ],
            draft_session_id=draft_session.id,
            draft_revision_id=draft_session.current_revision_id,
            dispatch_plan_id=confirmed.plan_id,
            task_id=task.task_id,
        )

    async def runtime_status_decision(self, *, task_id: str | None = None) -> RuntimeDecision:
        task = await self._resolve_status_task(task_id)
        if task is None:
            return RuntimeDecision(
                should_speak=True,
                response_text="No active task.",
                interaction_type=InteractionType.STATUS_QUERY,
                session_state=RuntimeSessionState.IDLE,
            )
        summary = await self.blackboard.get_summary(task.task_id)
        events = await self.blackboard.list_agent_events(task.task_id)
        latest_event = events[-1] if events else None
        response = (
            (summary.conversational_summary if summary and summary.conversational_summary else None)
            or (latest_event.message if latest_event else None)
            or f"{task.title} is {task.status.value}."
        )
        return RuntimeDecision(
            should_speak=True,
            response_text=response,
            interaction_type=InteractionType.STATUS_QUERY,
            session_state=_state_for_task(task),
            ui_updates=[UiUpdate(type="task.status", payload={"task_id": task.task_id})],
            task_id=task.task_id,
        )

    async def _resolve_status_task(self, task_id: str | None = None) -> Task | None:
        if task_id is not None:
            return await self.blackboard.get_task(task_id)
        tasks = await self.blackboard.list_tasks()
        preferred_statuses = {
            TaskStatus.RUNNING,
            TaskStatus.QUEUED,
            TaskStatus.WAITING_USER_INPUT,
            TaskStatus.PAUSED,
        }
        for task in reversed(tasks):
            if task.status in preferred_statuses:
                return task
        return tasks[-1] if tasks else None

    async def stop_active_task_decision(self, *, task_id: str | None = None, reason: str | None = None) -> RuntimeDecision:
        task = await self._resolve_status_task(task_id)
        if task is None:
            return RuntimeDecision(
                should_speak=True,
                response_text="No active task to stop.",
                interaction_type=InteractionType.TASK_CONTROL,
                session_state=RuntimeSessionState.IDLE,
            )
        command = TaskCommand(
            command_id=f"cmd-{uuid4().hex[:8]}",
            task_id=task.task_id,
            command_type=TaskCommandType.CANCEL_TASK,
            payload={},
            created_by="runtime",
            reason=reason,
        )
        await self.apply_command(command)
        await self.publish_snapshot()
        return RuntimeDecision(
            should_speak=True,
            response_text="Stopped.",
            interaction_type=InteractionType.TASK_CONTROL,
            session_state=RuntimeSessionState.IDLE,
            ui_updates=[UiUpdate(type="task.stopped", payload={"task_id": task.task_id})],
            task_id=task.task_id,
        )

    async def ingest_agent_event(self, event: AgentEvent) -> RuntimeDecision:
        await self.blackboard.put_agent_event(event)
        task = await self.blackboard.get_task(event.task_id)
        if task is not None:
            if event.type in {"agent.blocked", "task.blocked"}:
                task.status = TaskStatus.WAITING_USER_INPUT
                await self.blackboard.put_task(task)
            elif event.type in {"task.completed", "agent.completed"}:
                task.status = TaskStatus.COMPLETED
                await self.blackboard.put_task(task)
        should_speak = event.delivery in {AgentEventDelivery.SHORT_VOICE, AgentEventDelivery.VOICE_INTERRUPT} or event.importance == AgentEventImportance.URGENT
        if event.type in {"agent.blocked", "task.completed", "agent.completed"}:
            should_speak = True
        if event.type in {"agent.progress"} and event.importance == AgentEventImportance.LOW:
            should_speak = False
        if event.type in {"agent.blocked", "task.blocked"}:
            response = event.message
            state = RuntimeSessionState.TASK_BLOCKED
        elif event.type in {"task.completed", "agent.completed"}:
            response = event.message or "Task finished."
            state = RuntimeSessionState.TASK_COMPLETE
        else:
            response = event.message if should_speak else ""
            state = _state_for_task(task) if task is not None else RuntimeSessionState.IDLE
        await self.publish_snapshot()
        return RuntimeDecision(
            should_speak=should_speak,
            response_text=response,
            interaction_type=InteractionType.COMMUNICATION,
            session_state=state,
            ui_updates=[UiUpdate(type="agent_event.ingested", payload={"event_id": event.event_id, "task_id": event.task_id})],
            task_id=event.task_id,
        )

    async def send_draft(
        self,
        *,
        draft_session_id: str | None = None,
        draft_revision_id: str | None = None,
    ) -> Task:
        draft_session = self.draft_manager.active_session
        if draft_session is None or draft_session.current_draft is None or not draft_session.snapshots:
            raise ValueError("No draft is ready to send.")
        if draft_session_id is not None and draft_session.id != draft_session_id:
            raise ValueError("Draft session does not match the active draft.")
        if draft_revision_id is not None and draft_session.current_revision_id != draft_revision_id:
            raise ValueError("Draft revision does not match the active draft.")

        draft = draft_session.current_draft
        snapshot = draft_session.snapshots[-1]
        task_id = f"task-{uuid4().hex[:8]}"
        assigned_bro_id = draft_session.assigned_bro_id
        personas = await self.blackboard.list_personas()
        persona = await self.blackboard.get_persona(assigned_bro_id) if assigned_bro_id else None
        if persona is None and personas and assigned_bro_id and assigned_bro_id != DEFAULT_BRO_ID:
            raise ValueError(f"Bro '{assigned_bro_id}' is not available.")
        if persona is not None and persona.status == "busy":
            raise ValueError(f"{persona.name} is busy with another task right now.")

        available_executor_types = set(self.registry.list_executor_types())
        preferred_executor = await self._resolve_draft_preferred_executor(
            persona=persona,
            available_executor_types=available_executor_types,
        )
        session_affinity = (
            f"ws-{persona.bro_detail_session_id}"
            if persona is not None
            else create_workspace(task_id)
        )
        metadata = {
            "immutable": True,
            "source_kind": "draft_session",
            "draft_session_id": draft_session.id,
            "draft_snapshot_id": snapshot.id,
            "draft_revision_id": draft_session.current_revision_id,
            "draft_revision_number": draft_session.current_revision_number,
            "asr_turn_ids": [turn.id for turn in draft_session.asr_turns],
            "assigned_bro_id": assigned_bro_id,
            "draft_text": draft.text,
            "task_spec": draft.task_spec.model_dump(mode="json") if draft.task_spec is not None else {},
            "dispatch_plan": draft_session.current_dispatch_plan.model_dump(mode="json") if draft_session.current_dispatch_plan is not None else {},
            "mode": (draft.task_spec.mode.value if draft.task_spec is not None else TaskMode.READ_ONLY_FIRST.value),
            "expected_output": draft.task_spec.expected_output if draft.task_spec is not None else "",
            "constraints": draft.task_spec.constraints if draft.task_spec is not None else [],
            "success_criteria": draft.task_spec.success_criteria if draft.task_spec is not None else [],
            "stop_conditions": draft.task_spec.stop_conditions if draft.task_spec is not None else [],
            "mock_safe": preferred_executor == "mock",
        }
        if persona is not None:
            metadata["persona_id"] = persona.persona_id
            metadata["persona_name"] = persona.name
            metadata["persona_avatar"] = persona.avatar
            metadata["bro_detail_session_id"] = persona.bro_detail_session_id
            if persona.executor_node_id:
                metadata["executor_node_id"] = persona.executor_node_id
        task = Task(
            task_id=task_id,
            root_task_id=task_id,
            title=_title_from_draft_text(draft.text),
            goal=draft.task_spec.goal if draft.task_spec is not None else draft.text,
            status=TaskStatus.QUEUED,
            preferred_executor=preferred_executor,
            session_affinity=session_affinity,
            latest_instruction=_task_instruction_from_draft(draft),
            metadata=metadata,
        )
        if persona is not None:
            await self.blackboard.put_persona(
                persona.model_copy(update={"status": "busy"})
            )
        self.draft_manager.mark_sent(draft_session_id, draft_revision_id=draft_revision_id)
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
                    "preferred_executor": preferred_executor,
                    "persona_id": persona.persona_id if persona else None,
                    "persona_name": persona.name if persona else None,
                    "source_kind": "draft_session",
                    "draft_session_id": draft_session.id,
                    "draft_snapshot_id": snapshot.id,
                    "draft_revision_id": draft_session.current_revision_id,
                },
                created_by="draft_brain",
            )
        )
        saved = await self.blackboard.get_task(task_id)
        return saved or task

    async def _resolve_draft_preferred_executor(
        self,
        *,
        persona,
        available_executor_types: set[str],
    ) -> str | None:
        if persona is not None and persona.executor_node_id:
            for node in await self.executor_node_manager.list_nodes():
                if node.node_id != persona.executor_node_id:
                    continue
                for executor_type in node.enabled_executors:
                    if executor_type in available_executor_types:
                        return executor_type
                break
        preferred_executor = self.default_executor_type
        if preferred_executor not in available_executor_types:
            preferred_executor = "mock" if "mock" in available_executor_types else None
        return preferred_executor

    async def validate_task_command(self, task: Task, command_type: TaskCommandType) -> str | None:
        if command_type not in {TaskCommandType.PAUSE_TASK, TaskCommandType.PREEMPT_TASK}:
            if command_type == TaskCommandType.RESUME_TASK:
                if task.status == TaskStatus.WAITING_USER_INPUT:
                    return (
                        "This task is waiting for user input. Resolve the pending interaction request "
                        "instead of using resume."
                    )
                if task.status != TaskStatus.PAUSED:
                    return "Only paused tasks can be resumed."
            return None
        if task.status in {TaskStatus.CREATED, TaskStatus.QUEUED}:
            return None
        run, executor_type = await self._resolve_task_command_target(task)
        if run is None and executor_type is None:
            return "Task is not actively running."
        if executor_type is None:
            return "Task executor could not be determined."
        try:
            executor = self.registry.get(executor_type)
        except UnknownExecutorError:
            return f"Executor '{executor_type}' is not available."
        if not executor.get_capabilities().supports_pause:
            return f"Executor '{executor_type}' does not support pause."
        return None

    async def apply_command(self, command: TaskCommand) -> list[str]:
        task = await self.blackboard.get_task(command.task_id)
        if task is None:
            return []
        validation_error = await self.validate_task_command(task, command.command_type)
        if validation_error is not None:
            raise ValueError(validation_error)

        await self.blackboard.append_command(command)

        binding = await self.blackboard.get_binding(task.task_id)
        execution_session = None
        if binding is not None and binding.execution_session_id is not None:
            execution_session = await self.blackboard.get_session(binding.execution_session_id)
        run = await self._select_command_run(execution_session)

        if command.command_type in {TaskCommandType.PAUSE_TASK, TaskCommandType.PREEMPT_TASK}:
            await self._capture_pause_resume_handle(execution_session, run)
            task.status = TaskStatus.PAUSED
            await self._pause_live_run(run)
            if run is not None:
                run.status = RunStatus.PAUSED
                await self.blackboard.put_run(run)
            if binding is not None:
                await self.blackboard.put_binding(
                    binding.model_copy(
                        update={
                            "claimed_by": None,
                            "claim_expires_at": None,
                            "binding_status": BindingStatus.PAUSED,
                        }
                    )
                )
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Paused: {task.title}",
                    conversational_summary=f"I paused {task.title}.",
                    latest_user_visible_status="paused",
                    needs_user_input=False,
                )
            )
            await self.interaction_manager.add_task_signal_attention(
                task=task,
                kind=AttentionItemKind.TASK_PAUSED,
                body=f"{task.title} is paused.",
            )
        elif command.command_type == TaskCommandType.CANCEL_TASK:
            task.status = TaskStatus.CANCELLED
            await self._cancel_live_run(run)
            if run is not None:
                run.status = RunStatus.CANCELLED
                await self.blackboard.put_run(run)
            if execution_session is not None and execution_session.active_run_id == (
                run.run_id if run is not None else None
            ):
                execution_session.active_run_id = None
                await self.blackboard.put_session(execution_session)
            if binding is not None:
                await self.blackboard.put_binding(
                    binding.model_copy(
                        update={
                            "claimed_by": None,
                            "claim_expires_at": None,
                            "binding_status": BindingStatus.RELEASED,
                        }
                    )
                )
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Cancelled: {task.title}",
                    conversational_summary=f"I won't continue with {task.title}.",
                    latest_user_visible_status="cancelled",
                    needs_user_input=False,
                )
            )
            await self._suppress_pending_notifications(task.task_id)
            await self.interaction_manager.cancel_requests_for_task(task.task_id)
        elif command.command_type in {TaskCommandType.RESUME_TASK, TaskCommandType.RETRY_TASK}:
            task.status = TaskStatus.QUEUED
            if execution_session is not None and run is not None and execution_session.active_run_id == run.run_id:
                execution_session.active_run_id = None
                await self.blackboard.put_session(execution_session)
            if binding is not None:
                await self.blackboard.put_binding(
                    binding.model_copy(
                        update={
                            "claimed_by": None,
                            "claim_expires_at": None,
                            "binding_status": BindingStatus.RELEASED,
                        }
                    )
                )
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Queued: {task.title}",
                    conversational_summary=f"I queued {task.title} again.",
                    latest_user_visible_status="queued",
                    needs_user_input=False,
                )
            )
            if command.command_type == TaskCommandType.RESUME_TASK:
                await self.interaction_manager.add_task_signal_attention(
                    task=task,
                    kind=AttentionItemKind.TASK_RESUMED,
                    body=f"{task.title} is queued to continue.",
                )

        await self.blackboard.put_task(task)
        return [task.task_id]

    async def resolve_interaction_request(
        self,
        request_id: str,
        *,
        action: str,
        answer_text: str | None = None,
        option_id: str | None = None,
        answers: dict[str, list[str]] | None = None,
        reason: str | None = None,
        client_request_id: str | None = None,
        user_visible_text: str | None = None,
    ) -> list[str]:
        resolution = await self.interaction_manager.resolve_request(
            request_id,
            action=action,
            answer_text=answer_text,
            option_id=option_id,
            answers=answers,
            reason=reason,
        )
        native_resolved = await self._respond_to_native_interaction_request(
            resolution.request,
            action=action,
            answer_text=resolution.answer_text,
            answers=resolution.answers,
        )
        if native_resolved:
            await self.blackboard.put_interaction_request(
                resolution.request.model_copy(update={"resume_strategy": "native_response"})
            )
            self._record_interaction_answer_turn(
                resolution.request,
                user_visible_text=user_visible_text,
                client_request_id=client_request_id,
            )
            if resolution.request.task_id is None:
                await self.publish_snapshot(sync_imported_codex_threads=False)
                return []
            return [resolution.request.task_id]
        if resolution.request.outbound_turn_request_id is not None:
            await self._spawn_outbound_follow_up_from_interaction(
                resolution=resolution,
                action=action,
                client_request_id=client_request_id,
                user_visible_text=user_visible_text,
            )
            await self.publish_snapshot(sync_imported_codex_threads=False)
            return []
        if resolution.request.task_id is None:
            raise ValueError(
                "Interaction request without a task cannot resume via a follow-up run.",
            )
        task = await self.blackboard.get_task(resolution.request.task_id)
        if task is None:
            raise KeyError(f"Task '{resolution.request.task_id}' not found.")

        await self._detach_follow_up_live_session(resolution.request)
        if resolution.request.kind == InteractionRequestKind.PLAN_PROPOSAL:
            if action == "approve":
                task.metadata.pop("plan_mode", None)
                task.metadata["mode"] = TaskMode.MODIFY_ALLOWED.value
                visible_text = (
                    (user_visible_text or "").strip()
                    or _selected_plan_option_label(resolution.request)
                    or PLAN_APPROVAL_VISIBLE_TEXT
                )
                if client_request_id:
                    task.metadata["client_request_id"] = client_request_id
                task.metadata["user_visible_text"] = visible_text
                task.metadata["source_kind"] = "bro_detail_plan_approval"
            elif action == "deny":
                task.metadata["plan_mode"] = True
                task.metadata["mode"] = TaskMode.PROPOSAL_ONLY.value
        task.latest_instruction = self._merge_follow_up_instruction(
            task.latest_instruction,
            resolution.follow_up_instruction,
        )
        task.status = TaskStatus.QUEUED

        binding = await self.blackboard.get_binding(task.task_id)
        execution_session = None
        if binding is not None and binding.execution_session_id is not None:
            execution_session = await self.blackboard.get_session(binding.execution_session_id)
        if execution_session is not None and resolution.request.run_id is not None:
            if execution_session.active_run_id == resolution.request.run_id:
                execution_session.active_run_id = None
                await self.blackboard.put_session(execution_session)
        if binding is not None:
            await self.blackboard.put_binding(
                binding.model_copy(
                    update={
                        "claimed_by": None,
                        "claim_expires_at": None,
                        "binding_status": BindingStatus.RELEASED,
                    }
                )
            )
        await self.blackboard.put_summary(
            TaskSummary(
                task_id=task.task_id,
                operational_summary=f"Queued: {task.title}",
                conversational_summary=f"I queued {task.title} again.",
                latest_user_visible_status="queued",
                needs_user_input=False,
            )
        )
        await self.blackboard.put_task(task)
        return [task.task_id]

    async def requeue_waiting_executor_tasks(self) -> list[str]:
        changed_task_ids: list[str] = []
        for task in await self.blackboard.list_tasks():
            preferred_executor = task.preferred_executor
            if task.status != TaskStatus.WAITING_EXECUTOR:
                continue
            if not isinstance(preferred_executor, str):
                continue
            executor_node_id = task.metadata.get("executor_node_id")
            if executor_node_id is not None and not isinstance(executor_node_id, str):
                executor_node_id = None
            availability = self.executor_node_manager.executor_availability(
                preferred_executor,
                node_id=executor_node_id,
            )
            if not availability["connected"]:
                continue
            task.status = TaskStatus.QUEUED
            await self.blackboard.put_task(task)
            await self.blackboard.put_summary(
                TaskSummary(
                    task_id=task.task_id,
                    operational_summary=f"Queued: {task.title}",
                    conversational_summary=f"I queued {task.title} again.",
                    latest_user_visible_status="queued",
                    needs_user_input=False,
                )
            )
            changed_task_ids.append(task.task_id)
        return changed_task_ids

    async def _select_command_run(
        self,
        execution_session: ExecutionSession | None,
    ) -> ExecutionRun | None:
        if execution_session is None:
            return None
        candidate_run_ids = []
        if execution_session.active_run_id:
            candidate_run_ids.append(execution_session.active_run_id)
        if execution_session.latest_run_id and execution_session.latest_run_id not in candidate_run_ids:
            candidate_run_ids.append(execution_session.latest_run_id)
        for run_id in candidate_run_ids:
            run = await self.blackboard.get_run(run_id)
            if run is not None and run.status in {
                RunStatus.CREATED,
                RunStatus.ASSIGNED,
                RunStatus.RUNNING,
                RunStatus.BLOCKED,
                RunStatus.PAUSED,
            }:
                return run
        return None

    async def _cancel_live_run(self, run) -> None:
        if run is None:
            return
        try:
            executor = self.registry.get(run.executor_type)
        except UnknownExecutorError:
            return
        if not executor.get_capabilities().supports_cancel:
            return
        try:
            await executor.cancel_run(run.run_id)
        except Exception:
            return

    async def _pause_live_run(self, run) -> None:
        if run is None:
            return
        try:
            executor = self.registry.get(run.executor_type)
        except UnknownExecutorError:
            return
        if not executor.get_capabilities().supports_pause:
            return
        try:
            await executor.pause_run(run.run_id)
        except Exception:
            return

    async def _capture_pause_resume_handle(
        self,
        execution_session: ExecutionSession | None,
        run: ExecutionRun | None,
    ) -> None:
        if execution_session is None or run is None:
            return
        try:
            executor = self.registry.get(run.executor_type)
        except UnknownExecutorError:
            return
        if not executor.get_capabilities().supports_resume:
            return
        live_session = self.execution_brain.get_live_session(execution_session.execution_session_id)
        if live_session is None:
            return
        resume_handle = None
        if isinstance(live_session, CodexExecutorSession) and live_session.thread_id:
            resume_handle = AgentResumeHandle(
                executor_id="codex",
                session_handle=live_session.thread_id,
            )
        serialized_resume_handle = live_session.metadata.get("latest_resume_handle")
        if resume_handle is None and isinstance(serialized_resume_handle, dict):
            try:
                resume_handle = AgentResumeHandle.model_validate(serialized_resume_handle)
            except Exception:
                resume_handle = None
        elif resume_handle is None and hasattr(executor, "build_resume_handle"):
            try:
                resume_handle = executor.build_resume_handle(live_session)
            except Exception:
                resume_handle = None
        if resume_handle is None:
            return
        execution_session.latest_resume_handle = resume_handle
        await self.blackboard.put_session(execution_session)

    async def _respond_to_native_interaction_request(
        self,
        request: InteractionRequest,
        *,
        action: str,
        answer_text: str | None,
        answers: dict[str, list[str]] | None = None,
    ) -> bool:
        execution_session_id = request.execution_session_id
        executor_node_id: str | None = None
        if isinstance(execution_session_id, str) and execution_session_id:
            execution_session = await self.blackboard.get_session(execution_session_id)
            if execution_session is not None and isinstance(execution_session.executor_node_id, str):
                executor_node_id = execution_session.executor_node_id
        if await self.executor_node_manager.supply_interaction_response(
            request,
            action=action,
            answer_text=answer_text,
            answers=answers,
            node_id=executor_node_id,
        ):
            return True
        native_response = request.opaque.get("native_response")
        if not isinstance(native_response, dict):
            return False
        method = native_response.get("method")
        params = native_response.get("params")
        request_id = native_response.get("request_id")
        if not isinstance(method, str) or not isinstance(params, dict):
            return False
        if not isinstance(execution_session_id, str) or not execution_session_id:
            return False
        live_session = self.execution_brain.get_live_session(execution_session_id)
        if not isinstance(live_session, CodexExecutorSession):
            return False
        if request_id is None:
            return False
        try:
            await live_session.client.respond_to_request(
                request_id=request_id,
                method=method,
                params=params,
                action=action,
                answer_text=answer_text,
                answers=answers,
            )
        except Exception:
            LOGGER.warning(
                "Failed to send native interaction response for %s in session %s.",
                request.request_id,
                execution_session_id,
                exc_info=True,
            )
            return False
        live_session.mark_blocked_resolved()
        return True

    async def _spawn_outbound_follow_up_from_interaction(
        self,
        *,
        resolution: InteractionResolution,
        action: str,
        client_request_id: str | None,
        user_visible_text: str | None,
    ) -> None:
        if resolution.request.outbound_turn_request_id is None:
            raise ValueError("Resolution is not tied to an outbound turn request.")
        outbound = await self.blackboard.get_outbound_turn_request(
            resolution.request.outbound_turn_request_id,
        )
        if outbound is None:
            raise KeyError(
                f"OutboundTurnRequest '{resolution.request.outbound_turn_request_id}' not found.",
            )
        is_plan_proposal = resolution.request.kind == InteractionRequestKind.PLAN_PROPOSAL
        follow_up_plan_mode = is_plan_proposal and action != "approve"
        if is_plan_proposal and action == "approve":
            follow_up_text = (
                (user_visible_text or "").strip()
                or _selected_plan_option_label(resolution.request)
                or PLAN_APPROVAL_VISIBLE_TEXT
            )
        else:
            follow_up_text = resolution.follow_up_instruction
        await self.submit_executor_text_instruction(
            target_persona_id=outbound.persona_id,
            text=follow_up_text,
            target_thread_id=outbound.target_thread_id,
            create_new_thread=False,
            client_request_id=client_request_id,
            plan_mode=follow_up_plan_mode,
        )

    async def _detach_follow_up_live_session(self, request: InteractionRequest) -> None:
        execution_session_id = request.execution_session_id
        if not isinstance(execution_session_id, str) or not execution_session_id:
            return
        live_session = self.execution_brain.get_live_session(execution_session_id)
        if not isinstance(live_session, CodexExecutorSession):
            return
        execution_session = await self.blackboard.get_session(execution_session_id)
        run = (
            await self.blackboard.get_run(request.run_id)
            if isinstance(request.run_id, str) and request.run_id
            else None
        )
        await self._capture_pause_resume_handle(execution_session, run)
        try:
            await live_session.close()
        except Exception:
            LOGGER.warning(
                "Failed to close blocked Codex session %s while preparing follow-up run.",
                execution_session_id,
                exc_info=True,
            )
        finally:
            self.execution_brain.drop_live_session(execution_session_id)

    async def _suppress_pending_notifications(self, task_id: str) -> None:
        candidates = await self.blackboard.list_notification_candidates()
        for candidate in candidates:
            if (
                candidate.task_id == task_id
                and candidate.delivery_status == NotificationDeliveryStatus.PENDING
            ):
                await self.blackboard.put_notification_candidate(
                    candidate.model_copy(
                        update={"delivery_status": NotificationDeliveryStatus.SUPPRESSED}
                    )
                )

    async def _resolve_task_command_target(
        self,
        task: Task,
    ) -> tuple[ExecutionRun | None, str | None]:
        execution_session = None
        for session in await self.blackboard.list_sessions():
            if session.task_id == task.task_id:
                execution_session = session
                break
        run = None
        if execution_session is not None:
            candidate_run_ids = []
            if execution_session.active_run_id:
                candidate_run_ids.append(execution_session.active_run_id)
            if (
                execution_session.latest_run_id
                and execution_session.latest_run_id not in candidate_run_ids
            ):
                candidate_run_ids.append(execution_session.latest_run_id)
            for run_id in candidate_run_ids:
                run = await self.blackboard.get_run(run_id)
                if run is not None and run.status in {
                    RunStatus.CREATED,
                    RunStatus.ASSIGNED,
                    RunStatus.RUNNING,
                    RunStatus.BLOCKED,
                    RunStatus.PAUSED,
                }:
                    return run, run.executor_type
        executor_type = task.preferred_executor
        return run, executor_type

    def _executor_capabilities_snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "executor_type": capability.executor_type,
                "supports_pause": capability.supports_pause,
                "supports_cancel": capability.supports_cancel,
                "supports_resume": capability.supports_resume,
                "supports_follow_up": capability.supports_follow_up,
                "supports_audio_instruction": capability.supports_audio_instruction,
                "supports_thread_list": capability.supports_thread_list,
                **self.executor_node_manager.executor_availability(capability.executor_type),
            }
            for capability in self.registry.list_capabilities()
        ]

    def _merge_follow_up_instruction(
        self,
        existing: str | None,
        follow_up: str,
    ) -> str:
        if existing and existing.strip():
            merged = f"{existing.strip()}\n\nFollow-up:\n{follow_up}"
        else:
            merged = follow_up
        if len(merged) <= MAX_TASK_INSTRUCTION_CHARS:
            return merged
        marker = "[Earlier instructions truncated]\n\n"
        suffix = f"\n\nFollow-up:\n{follow_up}"
        available = MAX_TASK_INSTRUCTION_CHARS - len(marker) - len(suffix)
        if available <= 0:
            return merged[-MAX_TASK_INSTRUCTION_CHARS:]
        preserved_existing = (existing or "").strip()[-available:].lstrip()
        return f"{marker}{preserved_existing}{suffix}"

    async def _run_execution_loop(self) -> None:
        with bind_diagnostic_context(conversation_id=self.session_id):
            while await self._has_runnable_tasks():
                await self.execution_brain.tick()

    async def _has_runnable_tasks(self) -> bool:
        tasks = await self.blackboard.list_tasks()
        return any(task.status in {TaskStatus.CREATED, TaskStatus.QUEUED} for task in tasks)

    def _ensure_communication_pump(self) -> None:
        if self._communication_task is not None and not self._communication_task.done():
            return
        self._communication_task = asyncio.create_task(self._communication_loop())

    def _ensure_snapshot_pump(self) -> None:
        if self._snapshot_task is not None and not self._snapshot_task.done():
            return
        self._blackboard_queue = self.blackboard.subscribe()
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())

    def _ensure_notification_pump(self) -> None:
        if self._notification_task is not None and not self._notification_task.done():
            return
        self._notification_blackboard_queue = self.blackboard.subscribe()
        self._notification_task = asyncio.create_task(self._notification_loop())

    def _ensure_diagnostic_pump(self) -> None:
        if self._diagnostic_task is not None and not self._diagnostic_task.done():
            return
        self._diagnostic_blackboard_queue = self.blackboard.subscribe()
        self._diagnostic_task = asyncio.create_task(self._diagnostic_loop())

    def _wake_notification_pump(self) -> None:
        self._ensure_notification_pump()
        self._notification_wakeup.set()

    async def _communication_loop(self) -> None:
        try:
            while True:
                request = await self._message_queue.get()
                try:
                    await self._handle_message_request(request)
                finally:
                    self._message_queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            if asyncio.current_task() is self._communication_task:
                self._communication_task = None

    async def _handle_message_request(self, request: PendingMessageRequest) -> None:
        self._active_assistant_turns += 1
        self._wake_notification_pump()
        try:
            with bind_diagnostic_context(
                conversation_id=self.session_id,
                request_id=request.request_id,
            ):
                try:
                    await self._broadcast_event(
                        AssistantResponseStartedStreamEvent(
                            sequence=self._next_event_sequence(),
                            request_id=request.request_id,
                        )
                    )
                    if self.subscribers:
                        result = await self.communication_brain.generate_reply(
                            self.session_id,
                            request.user_text,
                            target_persona_id=request.target_persona_id,
                            on_text_delta=lambda delta: self._broadcast_event(
                                AssistantResponseDeltaStreamEvent(
                                    sequence=self._next_event_sequence(),
                                    request_id=request.request_id,
                                    delta=delta,
                                )
                            ),
                            on_trace=lambda trace: self._record_llm_trace(
                                replace(trace, request_id=request.request_id)
                            ),
                            on_tool_call=lambda record: self._record_tool_call(
                                record.with_request_id(request.request_id)
                            ),
                        )
                    else:
                        result = await self.communication_brain.generate_reply(
                            self.session_id,
                            request.user_text,
                            target_persona_id=request.target_persona_id,
                            on_trace=self._record_llm_trace,
                            on_tool_call=self._record_tool_call,
                        )
                except Exception as exc:
                    self.observability.communication.reply_failed(
                        conversation_id=self.session_id,
                        request_id=request.request_id,
                        reason_code=COMMUNICATION_MODEL_FAILURE,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                    assistant_entry = self.history.append_assistant(
                        self.session_id,
                        FALLBACK_ASSISTANT_ERROR_MESSAGE,
                    )
                    result = CommunicationTurnResult(
                        message_id=assistant_entry.message_id,
                        reply_text=FALLBACK_ASSISTANT_ERROR_MESSAGE,
                        conversational_act="model_reply",
                    )
                    await self._broadcast_event(
                        ConversationAppendedStreamEvent(
                            sequence=self._next_event_sequence(),
                            message_id=assistant_entry.message_id,
                            role="assistant",
                            text=FALLBACK_ASSISTANT_ERROR_MESSAGE,
                            source="system_fallback",
                            created_at=assistant_entry.created_at,
                        )
                    )
                    await self._broadcast_event(
                        AssistantResponseFailedStreamEvent(
                            sequence=self._next_event_sequence(),
                            request_id=request.request_id,
                            message=FALLBACK_ASSISTANT_ERROR_MESSAGE,
                        )
                    )
                else:
                    await self._broadcast_event(
                        AssistantResponseCompletedStreamEvent(
                            sequence=self._next_event_sequence(),
                            request_id=request.request_id,
                            message_id=result.message_id,
                            reply_text=result.reply_text,
                            conversational_act=result.conversational_act,
                            affected_task_ids=result.affected_task_ids,
                            created_at=self._conversation_message_created_at(result.message_id),
                        )
                    )
                await self.publish_snapshot()
                self.schedule_execution()
                if not request.completion.done():
                    request.completion.set_result(result)
        finally:
            self._active_assistant_turns = max(0, self._active_assistant_turns - 1)
            self._wake_notification_pump()

    async def _snapshot_loop(self) -> None:
        queue = self._blackboard_queue
        if queue is None:
            return
        try:
            while True:
                await queue.get()
                while True:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                await self.publish_snapshot()
        except asyncio.CancelledError:
            raise
        finally:
            self.blackboard.unsubscribe(queue)
            if self._blackboard_queue is queue:
                self._blackboard_queue = None
            if asyncio.current_task() is self._snapshot_task:
                self._snapshot_task = None

    async def _notification_loop(self) -> None:
        queue = self._notification_blackboard_queue
        if queue is None:
            return
        try:
            while True:
                with bind_diagnostic_context(conversation_id=self.session_id):
                    result = await self.notification_manager.process_pending(
                        assistant_busy=self._active_assistant_turns > 0,
                        has_pending_user_messages=not self._message_queue.empty(),
                    )
                queue_task = asyncio.create_task(queue.get())
                wake_task = asyncio.create_task(self._notification_wakeup.wait())
                task_kinds: dict[asyncio.Task, str] = {
                    queue_task: "queue",
                    wake_task: "wake",
                }
                if result.next_due_seconds is not None:
                    timer_task = asyncio.create_task(asyncio.sleep(result.next_due_seconds))
                    task_kinds[timer_task] = "timer"

                done, pending = await asyncio.wait(
                    task_kinds.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                blackboard_events = []
                for task in done:
                    kind = task_kinds[task]
                    if kind == "wake":
                        self._notification_wakeup.clear()
                    elif kind == "queue":
                        blackboard_events.append(task.result())
                while True:
                    try:
                        blackboard_events.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                for event in blackboard_events:
                    with bind_diagnostic_context(conversation_id=self.session_id):
                        await self.interaction_manager.handle_blackboard_write(event)
                        await self.notification_manager.handle_blackboard_write(event)
        except asyncio.CancelledError:
            raise
        finally:
            self.blackboard.unsubscribe(queue)
            if self._notification_blackboard_queue is queue:
                self._notification_blackboard_queue = None
            if asyncio.current_task() is self._notification_task:
                self._notification_task = None

    async def _diagnostic_loop(self) -> None:
        queue = self._diagnostic_blackboard_queue
        if queue is None:
            return
        try:
            while True:
                event = await queue.get()
                with bind_diagnostic_context(conversation_id=self.session_id):
                    key = (event.kind.value, event.entity_id)
                    created = key not in self._diagnostic_seen_entities
                    self._diagnostic_seen_entities.add(key)
                    self.observability.blackboard.record_write(
                        event=event,
                        created=created,
                    )
        except asyncio.CancelledError:
            raise
        finally:
            self.blackboard.unsubscribe(queue)
            if self._diagnostic_blackboard_queue is queue:
                self._diagnostic_blackboard_queue = None
            if asyncio.current_task() is self._diagnostic_task:
                self._diagnostic_task = None

    async def _broadcast_event(self, event: SessionStreamEventBase) -> None:
        for queue in list(self.subscribers):
            await queue.put(event)

    async def _record_llm_trace(self, trace: LlmTraceRecord) -> None:
        self.observability.communication.llm_trace(trace)

    async def _record_tool_call(self, record: ToolCallRecord) -> None:
        self.observability.communication.tool_called(
            **{
                "request_id": record.request_id,
                "tool_name": record.tool_name,
                "status": record.status,
                "args": record.args,
                "result_summary": record.result_summary,
                "result_pre" + "view": getattr(record, "result_pre" + "view"),
                "affected_task_ids": record.affected_task_ids,
                "error_code": record.error.code if record.error is not None else None,
                "error_message": record.error.message if record.error is not None else None,
            },
        )

    async def _broadcast_conversation_append(
        self,
        *,
        message_id: str,
        text: str,
        source: str,
    ) -> None:
        await self._broadcast_event(
            ConversationAppendedStreamEvent(
                sequence=self._next_event_sequence(),
                message_id=message_id,
                role="assistant",
                text=text,
                source="notification" if source == "notification" else "system_fallback",
                created_at=self._conversation_message_created_at(message_id),
            )
        )

    def _conversation_message_created_at(self, message_id: str) -> str:
        for entry in reversed(self.history.get_recent(self.session_id, limit=200)):
            if entry.message_id == message_id:
                return entry.created_at
        return datetime.now(tz=UTC).isoformat()

    async def _broadcast_user_message_append(
        self,
        *,
        message_id: str,
        text: str,
        source: Literal["user", "connector"],
    ) -> None:
        await self._broadcast_event(
            UserMessageAppendedStreamEvent(
                sequence=self._next_event_sequence(),
                message_id=message_id,
                text=text,
                source=source,
                created_at=self._conversation_message_created_at(message_id),
            )
        )

    def _snapshot_event(self, snapshot: SessionSnapshot) -> SnapshotStreamEvent:
        return SnapshotStreamEvent(
            sequence=self._next_event_sequence(),
            snapshot=snapshot,
        )

    def _next_event_sequence(self) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        return sequence


def create_session_runtime(
    session_id: str,
    *,
    model: CommunicationModel,
    settings: Settings,
    executor_node_manager: ExecutorNodeManager | None = None,
    draft_rewriter: DraftRewriter | None = None,
    interaction_classifier: InteractionClassifier | None = None,
) -> SessionRuntime:
    executor_node_manager = executor_node_manager or ExecutorNodeManager(
        detached_executor_types=settings.detached_executor_types,
    )
    blackboard = InMemoryBlackboard()
    history = InMemoryConversationHistory()
    registry = ExecutorRegistry()
    observability = build_session_observability(settings)
    registry.register(MockExecutor())
    if settings.detached_executor_enabled:
        for executor_type in settings.detached_executor_types:
            if executor_type == "codex":
                registry.register(
                    HostedExecutor(
                        executor_type="codex",
                        manager=executor_node_manager,
                        supports_resume=True,
                        supports_follow_up=True,
                        supports_thread_list=True,
                        supports_pause=True,
                    )
                )
            elif executor_type == "acpx":
                registry.register(
                    HostedExecutor(
                        executor_type="acpx",
                        manager=executor_node_manager,
                        supports_resume=True,
                        supports_follow_up=True,
                        supports_thread_list=False,
                        supports_pause=True,
                    )
                )
    elif settings.acpx_executor_enabled:
        registry.register(
            HostedExecutor(
                executor_type="acpx",
                manager=executor_node_manager,
                supports_resume=True,
                supports_follow_up=True,
                supports_thread_list=False,
                supports_pause=True,
            )
        )
    if settings.codex_executor_enabled:
        registry.register(
            HostedExecutor(
                executor_type="codex",
                manager=executor_node_manager,
                supports_resume=True,
                supports_follow_up=True,
                supports_thread_list=True,
                supports_pause=True,
            )
        )
    default_executor_type = (
        settings.detached_executor_types[0]
        if settings.detached_executor_enabled and settings.detached_executor_types
        else "mock"
    )
    # Load user-defined personas from ~/.newbro/personas.yaml into the blackboard.
    tool_registry = build_default_tool_registry(
        blackboard,
        executor_types=registry.list_executor_types(),
        default_executor_type=default_executor_type,
        apply_interaction_request=None,
    )
    communication_brain = CommunicationBrain(
        blackboard,
        model,
        history=history,
        tool_registry=tool_registry,
        executor_capabilities=registry.list_capabilities(),
        default_executor_type=default_executor_type,
        observability=observability.communication,
    )
    execution_brain = ExecutionBrain(
        blackboard,
        registry,
        worker_id=f"worker-{session_id}",
        default_executor_type=default_executor_type,
        observability=observability.execution,
    )
    notification_manager = NotificationManager(
        blackboard,
        communication_brain,
        conversation_id=session_id,
        observability=observability.notification,
    )
    interaction_manager = InteractionManager(blackboard)
    runtime = SessionRuntime(
        session_id=session_id,
        blackboard=blackboard,
        history=history,
        registry=registry,
        communication_brain=communication_brain,
        execution_brain=execution_brain,
        notification_manager=notification_manager,
        interaction_manager=interaction_manager,
        observability=observability,
        executor_node_manager=executor_node_manager,
        interaction_classifier=interaction_classifier or UnavailableInteractionClassifier(),
        live_interaction_classifier_interval_seconds=settings.live_interaction_classifier_interval_seconds,
        default_executor_type=default_executor_type,
        draft_manager=(
            DraftSessionManager(rewriter=draft_rewriter)
            if draft_rewriter is not None
            else DraftSessionManager()
        ),
    )
    control_task_handler = tool_registry.get("control_task").handler
    if hasattr(control_task_handler, "set_apply_callback"):
        control_task_handler.set_apply_callback(runtime.apply_command)
    interaction_request_handler = tool_registry.get("resolve_interaction_request").handler
    if hasattr(interaction_request_handler, "set_apply_callback"):
        interaction_request_handler.set_apply_callback(runtime.resolve_interaction_request)
    communication_brain.set_trace_callback(runtime._record_llm_trace)
    notification_manager.set_conversation_event_callback(runtime._broadcast_conversation_append)
    runtime.start_notification_processing()
    runtime._ensure_diagnostic_pump()
    # Load personas from persistent config into the blackboard.
    for persona in load_personas_from_file():
        blackboard._personas[persona.persona_id] = persona
    return runtime
