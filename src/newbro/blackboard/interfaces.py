from __future__ import annotations

import asyncio
from typing import Protocol

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

from .store import BlackboardWriteEvent


class BlackboardStore(Protocol):
    """Shared fact-layer interface used by both communication and execution."""

    async def put_task(self, task: Task) -> None:
        """Store or replace the current task projection."""

    async def get_task(self, task_id: str) -> Task | None:
        """Fetch one task by id."""

    async def list_tasks(self) -> list[Task]:
        """List current task projections."""

    async def append_mutation(self, mutation: TaskMutation) -> None:
        """Append a task mutation generated primarily by Communication Brain."""

    async def list_mutations(self, task_id: str) -> list[TaskMutation]:
        """List task mutations for one task."""

    async def list_all_mutations(self) -> list[TaskMutation]:
        """List task mutations across the session in append order."""

    async def append_command(self, command: TaskCommand) -> None:
        """Append a task command generated primarily by Communication Brain."""

    async def list_commands(self, task_id: str) -> list[TaskCommand]:
        """List task commands for one task."""

    async def list_all_commands(self) -> list[TaskCommand]:
        """List task commands across the session in append order."""

    async def append_task_execution_detail(self, entry: TaskExecutionDetailEntry) -> None:
        """Append one execution-detail entry for a task."""

    async def list_task_execution_details(
        self,
        task_id: str,
        limit: int | None = None,
    ) -> list[TaskExecutionDetailEntry]:
        """List execution-detail entries for one task in append order."""

    async def list_recent_task_execution_details(
        self,
        task_limit: int = 5,
        entry_limit: int = 20,
    ) -> dict[str, list[TaskExecutionDetailEntry]]:
        """List bounded execution-detail entries for the most recently active tasks."""

    async def put_run(self, run: ExecutionRun) -> None:
        """Store or replace a run projection written primarily by Execution Brain."""

    async def get_run(self, run_id: str) -> ExecutionRun | None:
        """Fetch one execution run by id."""

    async def list_runs(self) -> list[ExecutionRun]:
        """List current execution runs."""

    async def put_session(self, session: ExecutionSession) -> None:
        """Store or replace an execution-session lineage projection."""

    async def get_session(self, execution_session_id: str) -> ExecutionSession | None:
        """Fetch one execution session by id."""

    async def list_sessions(self) -> list[ExecutionSession]:
        """List execution sessions."""

    async def put_binding(self, binding: SessionBinding) -> None:
        """Store or replace the current task/session binding projection."""

    async def get_binding(self, task_id: str) -> SessionBinding | None:
        """Fetch the current binding for one task."""

    async def list_bindings(self) -> list[SessionBinding]:
        """List current task/session bindings."""

    async def put_summary(self, summary: TaskSummary) -> None:
        """Store or replace the current task summary projection."""

    async def get_summary(self, task_id: str) -> TaskSummary | None:
        """Fetch the current summary for one task."""

    async def put_execution_mode(self, execution_mode: TaskExecutionMode) -> None:
        """Store or replace the current execution-mode projection for one task."""

    async def get_execution_mode(self, task_id: str) -> TaskExecutionMode | None:
        """Fetch the current execution-mode projection for one task."""

    async def list_execution_modes(self) -> list[TaskExecutionMode]:
        """List current execution-mode projections."""

    async def put_notification_candidate(self, candidate: NotificationCandidate) -> None:
        """Store or replace a notification candidate projection."""

    async def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None:
        """Fetch one notification candidate by id."""

    async def list_notification_candidates(self) -> list[NotificationCandidate]:
        """List notification candidates across the session."""

    async def put_persona(self, persona: Persona) -> None:
        """Store or replace a persona."""

    async def get_persona(self, persona_id: str) -> Persona | None:
        """Fetch one persona by id."""

    async def list_personas(self) -> list[Persona]:
        """List all personas."""

    async def delete_persona(self, persona_id: str) -> bool:
        """Delete a persona. Returns True if it existed."""

    async def put_interaction_request(self, request: InteractionRequest) -> None:
        """Store or replace an interaction request."""

    async def get_interaction_request(self, request_id: str) -> InteractionRequest | None:
        """Fetch one interaction request by id."""

    async def list_interaction_requests(self) -> list[InteractionRequest]:
        """List interaction requests across the session."""

    async def put_attention_item(self, item: AttentionItem) -> None:
        """Store or replace an attention item."""

    async def get_attention_item(self, attention_id: str) -> AttentionItem | None:
        """Fetch one attention item by id."""

    async def list_attention_items(self) -> list[AttentionItem]:
        """List attention items across the session."""

    async def put_agent_event(self, event: AgentEvent) -> None:
        """Store an execution-agent event normalized for communication policy."""

    async def get_agent_event(self, event_id: str) -> AgentEvent | None:
        """Fetch one normalized agent event."""

    async def list_agent_events(self, task_id: str | None = None) -> list[AgentEvent]:
        """List normalized agent events, optionally scoped to a task."""

    async def list_recent_writes(self, limit: int = 50) -> list[BlackboardWriteEvent]:
        """List recent blackboard write events for debugging."""

    def subscribe(self) -> asyncio.Queue[BlackboardWriteEvent]:
        """Subscribe to blackboard write events."""

    def unsubscribe(self, queue: asyncio.Queue[BlackboardWriteEvent]) -> None:
        """Unsubscribe from blackboard write events."""
