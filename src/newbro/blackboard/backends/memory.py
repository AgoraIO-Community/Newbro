from __future__ import annotations

import asyncio
from collections import defaultdict

from newbro.observability.context import get_diagnostic_context
from newbro.protocol import (
    AttentionItem,
    AgentEvent,
    ExecutionRun,
    ExecutionSession,
    InteractionRequest,
    NotificationCandidate,
    Persona,
    SessionBinding,
    Task,
    TaskCommand,
    TaskExecutionDetailEntry,
    TaskExecutionMode,
    TaskMutation,
    TaskSummary,
)

from ..interfaces import BlackboardStore
from ..revisions import bump_task_revision
from ..store import BlackboardWriteEvent, BlackboardWriteKind
from ..subscriptions import SubscriptionManager


class InMemoryBlackboard(BlackboardStore):
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._task_snapshots: dict[str, Task] = {}
        self._mutations_by_task: dict[str, list[TaskMutation]] = defaultdict(list)
        self._commands_by_task: dict[str, list[TaskCommand]] = defaultdict(list)
        self._mutations: list[TaskMutation] = []
        self._commands: list[TaskCommand] = []
        self._task_execution_details_by_task: dict[str, list[TaskExecutionDetailEntry]] = defaultdict(list)
        self._task_execution_details: list[TaskExecutionDetailEntry] = []
        self._sessions: dict[str, ExecutionSession] = {}
        self._runs: dict[str, ExecutionRun] = {}
        self._run_snapshots: dict[str, ExecutionRun] = {}
        self._bindings_by_task: dict[str, SessionBinding] = {}
        self._summaries_by_task: dict[str, TaskSummary] = {}
        self._execution_modes_by_task: dict[str, TaskExecutionMode] = {}
        self._notification_candidates: dict[str, NotificationCandidate] = {}
        self._notification_candidate_order: list[str] = []
        self._personas: dict[str, Persona] = {}
        self._interaction_requests: dict[str, InteractionRequest] = {}
        self._interaction_request_order: list[str] = []
        self._attention_items: dict[str, AttentionItem] = {}
        self._attention_item_order: list[str] = []
        self._agent_events: dict[str, AgentEvent] = {}
        self._agent_event_order: list[str] = []
        self._recent_writes: list[BlackboardWriteEvent] = []
        self._subscriptions = SubscriptionManager()
        # Writes are serialized under this lock; read accessors intentionally stay
        # await-free and return best-effort snapshots of the current in-memory state.
        self._lock = asyncio.Lock()

    async def put_task(self, task: Task) -> None:
        previous = self._task_snapshots.get(task.task_id)
        async with self._lock:
            self._tasks[task.task_id] = task
            self._task_snapshots[task.task_id] = task.model_copy(deep=True)
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.TASK,
                entity_id=task.task_id,
                task_id=task.task_id,
                payload=_task_write_payload(previous, task),
            )
        )

    async def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def list_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    async def append_mutation(self, mutation: TaskMutation) -> None:
        async with self._lock:
            if mutation.task_id is not None:
                self._mutations_by_task[mutation.task_id].append(mutation)
                task = self._tasks.get(mutation.task_id)
                if task is not None:
                    bump_task_revision(task)
            else:
                self._mutations_by_task[""].append(mutation)
            self._mutations.append(mutation)
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.MUTATION,
                entity_id=mutation.mutation_id,
                task_id=mutation.task_id,
                payload={
                    "mutation_id": mutation.mutation_id,
                    "mutation_type": mutation.mutation_type.value,
                    "created_by": mutation.created_by,
                    "urgency": mutation.urgency,
                    "effective_scope": mutation.effective_scope,
                    "requires_replan": mutation.requires_replan,
                    "patch": mutation.patch,
                },
            )
        )

    async def list_mutations(self, task_id: str) -> list[TaskMutation]:
        return list(self._mutations_by_task.get(task_id, []))

    async def list_all_mutations(self) -> list[TaskMutation]:
        return list(self._mutations)

    async def append_command(self, command: TaskCommand) -> None:
        async with self._lock:
            self._commands_by_task[command.task_id].append(command)
            self._commands.append(command)
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.COMMAND,
                entity_id=command.command_id,
                task_id=command.task_id,
                payload={
                    "command_id": command.command_id,
                    "command_type": command.command_type.value,
                    "created_by": command.created_by,
                    "reason": command.reason,
                    "payload": command.payload,
                },
            )
        )

    async def list_commands(self, task_id: str) -> list[TaskCommand]:
        return list(self._commands_by_task.get(task_id, []))

    async def list_all_commands(self) -> list[TaskCommand]:
        return list(self._commands)

    async def append_task_execution_detail(self, entry: TaskExecutionDetailEntry) -> None:
        async with self._lock:
            self._task_execution_details_by_task[entry.task_id].append(entry)
            self._task_execution_details.append(entry)
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.EXECUTION_DETAIL,
                entity_id=entry.detail_id,
                task_id=entry.task_id,
                payload={
                    "run_id": entry.run_id,
                    "execution_session_id": entry.execution_session_id,
                    "event_type": entry.event_type,
                    "text": entry.text,
                    "created_at": entry.created_at,
                },
            )
        )

    async def list_task_execution_details(
        self,
        task_id: str,
        limit: int | None = None,
    ) -> list[TaskExecutionDetailEntry]:
        entries = list(self._task_execution_details_by_task.get(task_id, []))
        if limit is None:
            return entries
        if limit <= 0:
            return []
        return entries[-limit:]

    async def list_recent_task_execution_details(
        self,
        task_limit: int = 5,
        entry_limit: int = 20,
    ) -> dict[str, list[TaskExecutionDetailEntry]]:
        if task_limit <= 0 or entry_limit <= 0:
            return {}
        ordered_task_ids: list[str] = []
        seen_task_ids: set[str] = set()
        for entry in reversed(self._task_execution_details):
            if entry.task_id in seen_task_ids:
                continue
            seen_task_ids.add(entry.task_id)
            ordered_task_ids.append(entry.task_id)
            if len(ordered_task_ids) >= task_limit:
                break
        return {
            task_id: self._task_execution_details_by_task.get(task_id, [])[-entry_limit:]
            for task_id in ordered_task_ids
        }

    async def put_run(self, run: ExecutionRun) -> None:
        previous = self._run_snapshots.get(run.run_id)
        async with self._lock:
            self._runs[run.run_id] = run
            self._run_snapshots[run.run_id] = run.model_copy(deep=True)
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.RUN,
                entity_id=run.run_id,
                task_id=run.task_id,
                payload=_run_write_payload(previous, run),
            )
        )

    async def get_run(self, run_id: str) -> ExecutionRun | None:
        return self._runs.get(run_id)

    async def list_runs(self) -> list[ExecutionRun]:
        return list(self._runs.values())

    async def put_session(self, session: ExecutionSession) -> None:
        async with self._lock:
            self._sessions[session.execution_session_id] = session
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.SESSION,
                entity_id=session.execution_session_id,
                task_id=session.task_id,
            )
        )

    async def get_session(self, execution_session_id: str) -> ExecutionSession | None:
        return self._sessions.get(execution_session_id)

    async def list_sessions(self) -> list[ExecutionSession]:
        return list(self._sessions.values())

    async def put_binding(self, binding: SessionBinding) -> None:
        async with self._lock:
            self._bindings_by_task[binding.task_id] = binding
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.BINDING,
                entity_id=binding.session_id,
                task_id=binding.task_id,
            )
        )

    async def get_binding(self, task_id: str) -> SessionBinding | None:
        return self._bindings_by_task.get(task_id)

    async def list_bindings(self) -> list[SessionBinding]:
        return list(self._bindings_by_task.values())

    async def put_summary(self, summary: TaskSummary) -> None:
        async with self._lock:
            self._summaries_by_task[summary.task_id] = summary
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.SUMMARY,
                entity_id=summary.task_id,
                task_id=summary.task_id,
            )
        )

    async def get_summary(self, task_id: str) -> TaskSummary | None:
        return self._summaries_by_task.get(task_id)

    async def put_execution_mode(self, execution_mode: TaskExecutionMode) -> None:
        async with self._lock:
            self._execution_modes_by_task[execution_mode.task_id] = execution_mode
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.EXECUTION_MODE,
                entity_id=execution_mode.task_id,
                task_id=execution_mode.task_id,
                payload={"mode": execution_mode.mode.value},
            )
        )

    async def get_execution_mode(self, task_id: str) -> TaskExecutionMode | None:
        return self._execution_modes_by_task.get(task_id)

    async def list_execution_modes(self) -> list[TaskExecutionMode]:
        return list(self._execution_modes_by_task.values())

    async def put_notification_candidate(self, candidate: NotificationCandidate) -> None:
        async with self._lock:
            if candidate.candidate_id not in self._notification_candidates:
                self._notification_candidate_order.append(candidate.candidate_id)
            self._notification_candidates[candidate.candidate_id] = candidate
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.NOTIFICATION,
                entity_id=candidate.candidate_id,
                task_id=candidate.task_id,
                payload={
                    "candidate_type": candidate.candidate_type.value,
                    "delivery_status": candidate.delivery_status.value,
                },
            )
        )

    async def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None:
        return self._notification_candidates.get(candidate_id)

    async def list_notification_candidates(self) -> list[NotificationCandidate]:
        return [
            self._notification_candidates[candidate_id]
            for candidate_id in self._notification_candidate_order
            if candidate_id in self._notification_candidates
        ]

    async def put_persona(self, persona: Persona) -> None:
        async with self._lock:
            self._personas[persona.persona_id] = persona
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.PERSONA,
                entity_id=persona.persona_id,
            )
        )

    async def get_persona(self, persona_id: str) -> Persona | None:
        return self._personas.get(persona_id)

    async def list_personas(self) -> list[Persona]:
        return list(self._personas.values())

    async def delete_persona(self, persona_id: str) -> bool:
        async with self._lock:
            removed = self._personas.pop(persona_id, None)
        if removed is not None:
            await self._publish(
                BlackboardWriteEvent(
                    kind=BlackboardWriteKind.PERSONA,
                    entity_id=persona_id,
                )
            )
            return True
        return False

    async def put_interaction_request(self, request: InteractionRequest) -> None:
        async with self._lock:
            if request.request_id not in self._interaction_requests:
                self._interaction_request_order.append(request.request_id)
            self._interaction_requests[request.request_id] = request
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.INTERACTION_REQUEST,
                entity_id=request.request_id,
                task_id=request.task_id,
                payload={
                    "kind": request.kind.value,
                    "status": request.status.value,
                },
            )
        )

    async def get_interaction_request(self, request_id: str) -> InteractionRequest | None:
        return self._interaction_requests.get(request_id)

    async def list_interaction_requests(self) -> list[InteractionRequest]:
        return [
            self._interaction_requests[request_id]
            for request_id in self._interaction_request_order
            if request_id in self._interaction_requests
        ]

    async def put_attention_item(self, item: AttentionItem) -> None:
        async with self._lock:
            if item.attention_id not in self._attention_items:
                self._attention_item_order.append(item.attention_id)
            self._attention_items[item.attention_id] = item
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.ATTENTION,
                entity_id=item.attention_id,
                task_id=item.task_id,
                payload={
                    "kind": item.kind.value,
                    "status": item.status.value,
                },
            )
        )

    async def get_attention_item(self, attention_id: str) -> AttentionItem | None:
        return self._attention_items.get(attention_id)

    async def list_attention_items(self) -> list[AttentionItem]:
        return [
            self._attention_items[attention_id]
            for attention_id in self._attention_item_order
            if attention_id in self._attention_items
        ]

    async def put_agent_event(self, event: AgentEvent) -> None:
        async with self._lock:
            if event.event_id not in self._agent_events:
                self._agent_event_order.append(event.event_id)
            self._agent_events[event.event_id] = event
        await self._publish(
            BlackboardWriteEvent(
                kind=BlackboardWriteKind.AGENT_EVENT,
                entity_id=event.event_id,
                task_id=event.task_id,
                payload={
                    "agent_id": event.agent_id,
                    "type": event.type,
                    "importance": event.importance.value,
                    "delivery": event.delivery.value,
                },
            )
        )

    async def get_agent_event(self, event_id: str) -> AgentEvent | None:
        return self._agent_events.get(event_id)

    async def list_agent_events(self, task_id: str | None = None) -> list[AgentEvent]:
        events = [
            self._agent_events[event_id]
            for event_id in self._agent_event_order
            if event_id in self._agent_events
        ]
        if task_id is None:
            return events
        return [event for event in events if event.task_id == task_id]

    async def list_recent_writes(self, limit: int = 50) -> list[BlackboardWriteEvent]:
        return list(self._recent_writes[-limit:])

    def subscribe(self) -> asyncio.Queue[BlackboardWriteEvent]:
        return self._subscriptions.subscribe()

    def unsubscribe(self, queue: asyncio.Queue[BlackboardWriteEvent]) -> None:
        self._subscriptions.unsubscribe(queue)

    async def _publish(self, event: BlackboardWriteEvent) -> None:
        if event.request_id is None:
            event.request_id = get_diagnostic_context().request_id
        self._recent_writes.append(event)
        await self._subscriptions.publish(event)


def _task_write_payload(previous: Task | None, current: Task) -> dict[str, object]:
    payload: dict[str, object] = {"status": current.status.value}
    if previous is None:
        payload["change_kind"] = "created"
        return payload
    if previous.status != current.status:
        payload["change_kind"] = "status_change"
        payload["previous_status"] = previous.status.value
        return payload

    changed_fields = [
        field
        for field in (
            "title",
            "goal",
            "priority",
            "interruptible",
            "requires_confirmation",
            "preferred_executor",
            "session_affinity",
            "latest_instruction",
            "metadata",
        )
        if getattr(previous, field) != getattr(current, field)
    ]
    if changed_fields:
        payload["change_kind"] = "fields_updated"
        payload["changed_fields"] = changed_fields[:5]
        return payload
    payload["change_kind"] = "refresh"
    return payload


def _run_write_payload(previous: ExecutionRun | None, current: ExecutionRun) -> dict[str, object]:
    payload: dict[str, object] = {"status": current.status.value}
    if previous is None:
        payload["change_kind"] = "created"
        if current.latest_progress_message:
            payload["latest_progress_message"] = current.latest_progress_message
        return payload
    if previous.status != current.status:
        payload["change_kind"] = "status_change"
        payload["previous_status"] = previous.status.value
        if current.latest_progress_message:
            payload["latest_progress_message"] = current.latest_progress_message
        return payload
    if previous.latest_progress_message != current.latest_progress_message:
        payload["change_kind"] = "progress_update"
        if current.latest_progress_message:
            payload["latest_progress_message"] = current.latest_progress_message
        return payload

    changed_fields = [
        field
        for field in (
            "output_summary",
            "block_reason",
            "failure_reason",
            "claimed_by",
            "run_revision",
            "metadata",
        )
        if getattr(previous, field) != getattr(current, field)
    ]
    if changed_fields:
        payload["change_kind"] = "fields_updated"
        payload["changed_fields"] = changed_fields[:5]
        return payload
    payload["change_kind"] = "refresh"
    return payload
