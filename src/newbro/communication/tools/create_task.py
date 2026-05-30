from __future__ import annotations

from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.communication.persona_pool import create_workspace
from newbro.protocol import ExecutionMode, MutationType, Task, TaskExecutionMode, TaskMutation

from .base import ToolInputError


class CreateTaskTool:
    name = "create_task"

    def __init__(
        self,
        store: BlackboardStore,
        *,
        valid_executor_types: list[str],
        default_executor_type: str,
    ) -> None:
        self._store = store
        self._valid_executor_types = list(valid_executor_types)
        self._default_executor_type = default_executor_type

    @property
    def valid_executor_types(self) -> list[str]:
        return list(self._valid_executor_types)

    async def __call__(
        self,
        *,
        title: str,
        goal: str,
        persona_name: str | None = None,
        continue_from_task_id: str | None = None,
        preferred_executor: str | None = None,
        requires_confirmation: bool = False,
        mock_safe: bool = False,
    ) -> Task:
        resolved_executor = preferred_executor or self._default_executor_type
        if resolved_executor not in self._valid_executor_types:
            allowed = ", ".join(self._valid_executor_types)
            raise ToolInputError(
                f"Invalid create_task preferred_executor '{resolved_executor}'. Use one of: {allowed}.",
                code="invalid_executor_type",
            )
        if resolved_executor == "mock" and not mock_safe:
            raise ToolInputError(
                "A real executor is required but only the mock executor is available.",
                code="real_executor_required",
            )

        # Resolve persona
        metadata: dict[str, object] = {"mock_safe": True} if mock_safe else {}
        persona = None
        if persona_name:
            personas = await self._store.list_personas()
            for p in personas:
                if p.name.lower() == persona_name.lower():
                    persona = p
                    break
            if persona is None:
                available = ", ".join(p.name for p in personas) or "none"
                raise ToolInputError(
                    f"Persona '{persona_name}' not found. Available: {available}.",
                    code="persona_not_found",
                )
            if persona.status == "busy":
                raise ToolInputError(
                    f"{persona.name} is busy with another task right now.",
                    code="persona_busy",
                )

        task_id = f"task-{uuid4().hex[:8]}"

        # Resolve workspace: continue from prior task or create new
        session_affinity: str | None = None
        if continue_from_task_id:
            prior_task = await self._store.get_task(continue_from_task_id)
            if prior_task is not None and prior_task.session_affinity:
                session_affinity = prior_task.session_affinity
                metadata["continue_from_task_id"] = continue_from_task_id
        if session_affinity is None:
            session_affinity = (
                f"ws-{persona.bro_detail_session_id}"
                if persona is not None
                else create_workspace(task_id)
            )

        if persona is not None:
            metadata["persona_id"] = persona.persona_id
            metadata["persona_name"] = persona.name
            metadata["persona_avatar"] = persona.avatar
            metadata["bro_detail_session_id"] = persona.bro_detail_session_id
            if persona.executor_node_id:
                metadata["executor_node_id"] = persona.executor_node_id
            await self._store.put_persona(
                persona.model_copy(update={"status": "busy"})
            )

        task = Task(
            task_id=task_id,
            root_task_id=task_id,
            title=title,
            goal=goal,
            preferred_executor=resolved_executor,
            requires_confirmation=requires_confirmation,
            session_affinity=session_affinity,
            metadata=metadata,
        )
        await self._store.put_task(task)
        await self._store.put_execution_mode(
            TaskExecutionMode(task_id=task_id, mode=ExecutionMode.UNDECIDED)
        )
        await self._store.append_mutation(
            TaskMutation(
                mutation_id=f"mut-{uuid4().hex[:8]}",
                task_id=task_id,
                mutation_type=MutationType.CREATE,
                patch={
                    "title": title,
                    "goal": goal,
                    "preferred_executor": resolved_executor,
                    "persona_name": persona.name if persona else None,
                    "continue_from_task_id": continue_from_task_id,
                },
                created_by="communication_brain",
            )
        )
        saved = await self._store.get_task(task_id)
        return saved or task
