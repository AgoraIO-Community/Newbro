from __future__ import annotations

from dataclasses import dataclass

from newbro.blackboard import BlackboardQueryService, BlackboardStore
from newbro.executors.core import ExecutorCapabilities
from newbro.protocol import InteractionRequest, Task, TaskExecutionDetailEntry, TaskStatus, TaskSummary

from .history import ConversationEntry, InMemoryConversationHistory

DEFAULT_HISTORY_LIMIT = 30
ACTIVE_CONTEXT_TASK_LIMIT = 5
RECENT_CONTEXT_TASK_LIMIT = 5
EXECUTION_DETAIL_TASK_LIMIT = 5
EXECUTION_DETAIL_ENTRY_LIMIT = 20


@dataclass(slots=True)
class CommunicationTaskBrief:
    task_id: str
    title: str
    goal: str
    status: str
    priority: int
    latest_instruction: str | None
    conversational_summary: str | None
    latest_user_visible_status: str | None
    note_count: int
    constraint_count: int
    persona_name: str | None = None
    persona_avatar: str | None = None


@dataclass(slots=True)
class ExecutorRuntimeSummary:
    has_real_executor: bool
    available_executor_types: list[str]
    default_executor_type: str | None
    executors: list[dict[str, object]]


@dataclass(slots=True)
class CommunicationContext:
    conversation_id: str
    recent_history: list[ConversationEntry]
    tasks: list[Task]
    summaries: dict[str, TaskSummary | None]
    task_execution_details: dict[str, list[TaskExecutionDetailEntry]]
    focused_task_ids: list[str]
    focused_tasks: list[CommunicationTaskBrief]
    active_tasks: list[CommunicationTaskBrief]
    recent_tasks: list[CommunicationTaskBrief]
    executor_runtime: ExecutorRuntimeSummary
    available_tools: list[str]
    personas: list[dict[str, object]] | None = None
    interaction_requests: list[dict[str, object]] | None = None
    target_persona_id: str | None = None


class CommunicationContextBuilder:
    def __init__(
        self,
        store: BlackboardStore,
        history: InMemoryConversationHistory,
        *,
        executor_capabilities: list[ExecutorCapabilities] | None = None,
        default_executor_type: str | None = None,
    ) -> None:
        self._store = store
        self._history = history
        self._queries = BlackboardQueryService(store)
        self._executor_capabilities = list(executor_capabilities or [])
        self._default_executor_type = default_executor_type

    async def build(
        self,
        conversation_id: str,
        *,
        available_tools: list[str],
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        target_persona_id: str | None = None,
    ) -> CommunicationContext:
        tasks = await self._store.list_tasks()
        summaries = {
            task.task_id: await self._store.get_summary(task.task_id)
            for task in tasks
        }
        task_execution_details = await self._store.list_recent_task_execution_details(
            task_limit=EXECUTION_DETAIL_TASK_LIMIT,
            entry_limit=EXECUTION_DETAIL_ENTRY_LIMIT,
        )
        focused_task_ids = self._history.latest_focused_task_ids(conversation_id)
        focused_tasks = [
            self._build_task_brief(task, summaries.get(task.task_id))
            for task_id in focused_task_ids
            for task in tasks
            if task.task_id == task_id
        ]
        active_tasks = [
            self._build_task_brief(task, summaries.get(task.task_id))
            for task in tasks
            if task.status
            in {
                TaskStatus.CREATED,
                TaskStatus.QUEUED,
                TaskStatus.WAITING_EXECUTOR,
                TaskStatus.RUNNING,
                TaskStatus.WAITING_USER_INPUT,
                TaskStatus.PAUSED,
            }
        ][:ACTIVE_CONTEXT_TASK_LIMIT]
        recent_tasks = [
            self._build_task_brief(task, summaries.get(task.task_id))
            for task in reversed(tasks[-RECENT_CONTEXT_TASK_LIMIT:])
        ]
        return CommunicationContext(
            conversation_id=conversation_id,
            recent_history=self._history.get_recent(conversation_id, limit=history_limit),
            tasks=tasks,
            summaries=summaries,
            task_execution_details=task_execution_details,
            focused_task_ids=focused_task_ids,
            focused_tasks=focused_tasks,
            active_tasks=active_tasks,
            recent_tasks=recent_tasks,
            executor_runtime=self._build_executor_runtime_summary(),
            available_tools=available_tools,
            personas=await self._build_persona_context(),
            interaction_requests=await self._build_interaction_request_context(),
            target_persona_id=target_persona_id,
        )

    def _build_task_brief(
        self,
        task: Task,
        summary: TaskSummary | None,
    ) -> CommunicationTaskBrief:
        notes = task.metadata.get("notes", [])
        constraints = task.metadata.get("constraints", [])
        return CommunicationTaskBrief(
            task_id=task.task_id,
            title=task.title,
            goal=task.goal,
            status=task.status.value,
            priority=task.priority,
            latest_instruction=task.latest_instruction,
            conversational_summary=summary.conversational_summary if summary is not None else None,
            latest_user_visible_status=(
                summary.latest_user_visible_status if summary is not None else None
            ),
            note_count=len(notes) if isinstance(notes, list) else 0,
            constraint_count=len(constraints) if isinstance(constraints, list) else 0,
            persona_name=task.metadata.get("persona_name") if isinstance(task.metadata.get("persona_name"), str) else None,
            persona_avatar=task.metadata.get("persona_avatar") if isinstance(task.metadata.get("persona_avatar"), str) else None,
        )

    def _build_executor_runtime_summary(self) -> ExecutorRuntimeSummary:
        available_executor_types = [
            capability.executor_type for capability in self._executor_capabilities
        ]
        return ExecutorRuntimeSummary(
            has_real_executor=any(
                capability.executor_type != "mock"
                for capability in self._executor_capabilities
            ),
            available_executor_types=available_executor_types,
            default_executor_type=self._default_executor_type,
            executors=[
                {
                    "executor_type": capability.executor_type,
                    "is_mock": capability.executor_type == "mock",
                    "supports_follow_up": capability.supports_follow_up,
                    "supports_resume": capability.supports_resume,
                    "supports_pause": capability.supports_pause,
                    "supports_cancel": capability.supports_cancel,
                    "supports_setup": capability.supports_setup,
                }
                for capability in self._executor_capabilities
            ],
        )
    async def _build_persona_context(self) -> list[dict[str, object]] | None:
        personas = await self._store.list_personas()
        if not personas:
            return None
        return [
            {
                "persona_id": p.persona_id,
                "name": p.name,
                "avatar": p.avatar,
                "status": p.status,
            }
            for p in personas
        ]

    async def _build_interaction_request_context(self) -> list[dict[str, object]] | None:
        requests = await self._store.list_interaction_requests()
        pending_requests = [request for request in requests if request.status.value == "pending"]
        if not pending_requests:
            return None
        return [
            _interaction_request_payload(request)
            for request in pending_requests
        ]


def _interaction_request_payload(request: InteractionRequest) -> dict[str, object]:
    return {
        "request_id": request.request_id,
        "task_id": request.task_id,
        "kind": request.kind.value,
        "status": request.status.value,
        "prompt": request.prompt,
        "available_actions": list(request.available_actions),
    }
