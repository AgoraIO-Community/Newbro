from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from newbro.blackboard import BlackboardStore

from .add_constraint import AddConstraintTool
from .add_task_note import AddTaskNoteTool
from .control_task import ControlTaskTool
from .create_task import CreateTaskTool
from .list_tasks import ListTasksTool
from .query_task_detail import QueryTaskDetailTool
from .query_task_summary import QueryTaskSummaryTool
from .resolve_interaction_request import ResolveInteractionRequestTool
from .update_task import UpdateTaskTool


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, object]
    handler: Any

    async def invoke(self, **kwargs: Any) -> Any:
        return await self.handler(**kwargs)

    async def __call__(self, **kwargs: Any) -> Any:
        return await self.invoke(**kwargs)


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, ToolSpec]

    def get(self, name: str) -> ToolSpec:
        return self.tools[name]

    @property
    def names(self) -> list[str]:
        return sorted(self.tools.keys())

    @property
    def openai_tools(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_schema,
                },
            }
            for spec in self.tools.values()
        ]


def build_default_tool_registry(
    store: BlackboardStore,
    *,
    executor_types: list[str] | None = None,
    default_executor_type: str = "mock",
    apply_task_command=None,
    apply_interaction_request=None,
) -> ToolRegistry:
    resolved_executor_types = sorted(set(executor_types or ["mock"]))
    create_task = CreateTaskTool(
        store,
        valid_executor_types=resolved_executor_types,
        default_executor_type=default_executor_type,
    )
    add_constraint = AddConstraintTool(store)
    add_task_note = AddTaskNoteTool(store)
    control_task = ControlTaskTool(store, apply_callback=apply_task_command)
    resolve_interaction_request = ResolveInteractionRequestTool(
        store,
        apply_callback=apply_interaction_request,
    )
    list_tasks = ListTasksTool(store)
    query_task_detail = QueryTaskDetailTool(store)
    query_task_summary = QueryTaskSummaryTool(store)
    update_task = UpdateTaskTool(store, valid_executor_types=resolved_executor_types)
    return ToolRegistry(
        tools={
            "add_constraint": ToolSpec(
                name="add_constraint",
                description="Add an execution-relevant constraint to an existing task. Prefer passing task_id over reference when the task is visible in context.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "constraint": {"type": "string"},
                        "category": {"type": ["string", "null"]},
                        "task_id": {"type": ["string", "null"]},
                        "reference": {"type": ["string", "null"]},
                    },
                    "required": ["constraint"],
                    "additionalProperties": False,
                },
                handler=add_constraint,
            ),
            "add_task_note": ToolSpec(
                name="add_task_note",
                description="Attach an extra user note or contextual hint to an existing task. Prefer passing task_id over reference when the task is visible in context.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "note": {"type": "string"},
                        "task_id": {"type": ["string", "null"]},
                        "reference": {"type": ["string", "null"]},
                    },
                    "required": ["note"],
                    "additionalProperties": False,
                },
                handler=add_task_note,
            ),
            "control_task": ToolSpec(
                name="control_task",
                description="Pause, cancel, retry, resume, or preempt a task.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "command_type": {
                            "type": "string",
                            "enum": control_task.allowed_command_types,
                        },
                        "task_id": {"type": ["string", "null"]},
                        "reference": {"type": ["string", "null"]},
                        "payload": {"type": "object"},
                        "reason": {"type": ["string", "null"]},
                    },
                    "required": ["command_type"],
                    "additionalProperties": False,
                },
                handler=control_task,
            ),
            "create_task": ToolSpec(
                name="create_task",
                description="Create a new task on the blackboard. Must specify persona_name to assign a worker.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "goal": {"type": "string"},
                        "persona_name": {"type": ["string", "null"], "description": "Name of the persona to assign this task to."},
                        "continue_from_task_id": {"type": ["string", "null"], "description": "Task ID to continue from. Reuses that task's workspace so the executor can see prior files."},
                        "preferred_executor": {
                            "anyOf": [
                                {"type": "string", "enum": create_task.valid_executor_types},
                                {"type": "null"},
                            ]
                        },
                        "requires_confirmation": {"type": "boolean"},
                        "mock_safe": {"type": "boolean"},
                    },
                    "required": ["title", "goal"],
                    "additionalProperties": False,
                },
                handler=create_task,
            ),
            "resolve_interaction_request": ToolSpec(
                name="resolve_interaction_request",
                description="Resolve a pending interaction request such as allow, deny, answer, confirm, or cancel.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": ["approve", "deny", "answer", "confirm", "cancel"],
                        },
                        "answer_text": {"type": ["string", "null"]},
                        "option_id": {"type": ["string", "null"]},
                        "answers": {
                            "type": ["object", "null"],
                            "additionalProperties": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "reason": {"type": ["string", "null"]},
                    },
                    "required": ["request_id", "action"],
                    "additionalProperties": False,
                },
                handler=resolve_interaction_request,
            ),
            "list_tasks": ToolSpec(
                name="list_tasks",
                description="List the most relevant tasks for a user reference such as 'that one' or 'the email task'.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "reference": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                    "required": ["reference"],
                    "additionalProperties": False,
                },
                handler=list_tasks,
            ),
            "query_task_detail": ToolSpec(
                name="query_task_detail",
                description="Inspect one task together with related execution detail.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": ["string", "null"]},
                        "reference": {"type": ["string", "null"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
                handler=query_task_detail,
            ),
            "query_task_summary": ToolSpec(
                name="query_task_summary",
                description="Read the user-facing and operational summary for a task.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": ["string", "null"]},
                        "reference": {"type": ["string", "null"]},
                    },
                    "additionalProperties": False,
                },
                handler=query_task_summary,
            ),
            "update_task": ToolSpec(
                name="update_task",
                description="Update core structured task fields such as goal, title, instruction, priority, or executor preference. Prefer passing task_id over reference when the task is visible in context.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": ["string", "null"]},
                        "reference": {"type": ["string", "null"]},
                        "patch": {
                            "type": "object",
                            "properties": {
                                "goal": {"type": "string"},
                                "interruptible": {"type": "boolean"},
                                "latest_instruction": {"type": "string"},
                                "preferred_executor": {
                                    "anyOf": [
                                        {"type": "string", "enum": resolved_executor_types},
                                        {"type": "null"},
                                    ]
                                },
                                "priority": {"type": "integer"},
                                "requires_confirmation": {"type": "boolean"},
                                "session_affinity": {"type": ["string", "null"]},
                                "title": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "required": ["patch"],
                    "additionalProperties": False,
                },
                handler=update_task,
            ),
        }
    )
