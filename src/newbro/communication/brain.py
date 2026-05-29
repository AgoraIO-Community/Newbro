from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from newbro.communication.history import ConversationEntry
from newbro.blackboard import BlackboardStore
from newbro.observability.emitters.communication import CommunicationDiagnosticEmitter
from newbro.observability.reason_codes import COMMUNICATION_MODEL_FAILURE
from newbro.protocol import MutationType, NotificationCandidate, Task, TaskMutation, TaskStatus
from newbro.executors.core import ExecutorCapabilities

from .context import CommunicationContextBuilder
from .history import InMemoryConversationHistory
from .model import (
    CommunicationModelResult,
    CommunicationModel,
    LlmTraceCallback,
    TextDeltaCallback,
    ToolCallCallback,
    ToolCallError,
    ToolCallRecord,
)
from .policies import ToolUsagePolicy, render_reply
from .prompts.runtime_context import build_notification_rendering_context
from .tools import ToolRegistry, build_default_tool_registry
from .tools.base import ToolInputError
from .types import CommunicationTurnResult, ToolInvocationRecord


ACTIVE_TASK_STATUSES = {
    TaskStatus.CREATED,
    TaskStatus.QUEUED,
    TaskStatus.WAITING_EXECUTOR,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_USER_INPUT,
    TaskStatus.PAUSED,
}
TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
}


@dataclass(slots=True)
class BundleSlot:
    task_id: str
    field_name: str
    cue: str
    group: str | None
    value: str


SLOT_PHRASE_RE = re.compile(
    r"\b(?P<cue>from|to|in|at)\s+(?P<value>[A-Za-z][A-Za-z\s-]+?)(?=\s+(?:for|from|to|instead|today|tomorrow)\b|[.,!?]|$)",
    re.IGNORECASE,
)

CORRECTION_OLD_NEW_RE = re.compile(
    r"^(?:change|replace|switch)\s+(?:(?P<cue>from|to|in|at)\s+)?(?P<old>[A-Za-z][A-Za-z\s-]+?)\s+(?:to|with|for)\s+(?P<new>[A-Za-z][A-Za-z\s-]+)$",
    re.IGNORECASE,
)

CORRECTION_SHOULD_BE_RE = re.compile(
    r"^(?:(?:it|that|this|destination|origin)\s+)?should\s+be\s+(?P<new>[A-Za-z][A-Za-z\s-]+?)(?:\s+(?P<cue>from|to|in|at))?$",
    re.IGNORECASE,
)

CORRECTION_DIRECT_CUE_RE = re.compile(
    r"^(?P<cue>from|to|in|at)\s+(?P<new>[A-Za-z][A-Za-z\s-]+)$",
    re.IGNORECASE,
)

CONTINUE_PHRASES = {
    "continue",
    "go on",
    "keep going",
    "resume",
    "继续",
    "继续吧",
    "继续执行",
}

STOP_PHRASES = {
    "stop",
    "stop it",
    "forget it",
    "never mind",
    "cancel that",
    "取消",
    "停止",
    "别做了",
}


class CommunicationBrain:
    def __init__(
        self,
        store: BlackboardStore,
        model: CommunicationModel,
        *,
        history: InMemoryConversationHistory | None = None,
        tool_registry: ToolRegistry | None = None,
        executor_capabilities: list[ExecutorCapabilities] | None = None,
        default_executor_type: str | None = None,
        trace_callback: LlmTraceCallback | None = None,
        observability: CommunicationDiagnosticEmitter | None = None,
    ) -> None:
        self._store = store
        self._model = model
        self._history = history or InMemoryConversationHistory()
        self._tools = tool_registry or build_default_tool_registry(store)
        self._tool_usage_policy = ToolUsagePolicy(self._tools.names)
        self._context_builder = CommunicationContextBuilder(
            store,
            self._history,
            executor_capabilities=executor_capabilities,
            default_executor_type=default_executor_type,
        )
        self._trace_callback = trace_callback
        self._observability = observability

    def set_trace_callback(self, callback: LlmTraceCallback | None) -> None:
        self._trace_callback = callback

    async def handle_user_message(
        self,
        conversation_id: str,
        user_text: str,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> CommunicationTurnResult:
        self.append_user_message(conversation_id, user_text)
        return await self.generate_reply(
            conversation_id,
            user_text,
            on_text_delta=on_text_delta,
        )

    def append_user_message(self, conversation_id: str, user_text: str) -> ConversationEntry:
        return self._history.append_user(conversation_id, user_text)

    async def generate_reply(
        self,
        conversation_id: str,
        user_text: str,
        *,
        target_persona_id: str | None = None,
        on_text_delta: TextDeltaCallback | None = None,
        on_trace: LlmTraceCallback | None = None,
        on_tool_call: ToolCallCallback | None = None,
    ) -> CommunicationTurnResult:
        if self._observability is not None:
            self._observability.message_received(
                conversation_id=conversation_id,
                user_text=user_text,
            )
        context = await self._context_builder.build(
            conversation_id,
            available_tools=self._tool_usage_policy.available_tools,
            target_persona_id=target_persona_id,
        )
        local_result = await self._handle_local_intent(
            conversation_id,
            user_text,
            context=context,
            on_tool_call=on_tool_call,
        )
        if local_result is not None:
            return local_result
        respond_kwargs = {
            "user_text": user_text,
            "context": context,
            "tool_registry": self._tools,
        }
        if on_text_delta is not None:
            respond_kwargs["on_text_delta"] = on_text_delta
        if on_trace is not None:
            respond_kwargs["on_trace"] = on_trace
        elif self._trace_callback is not None:
            respond_kwargs["on_trace"] = self._trace_callback
        if on_tool_call is not None:
            respond_kwargs["on_tool_call"] = on_tool_call
        result = await self._model.respond(**respond_kwargs)
        result = self._ground_model_result(result)
        assistant_entry = self._append_assistant_entry(
            conversation_id,
            result.reply_text,
            affected_task_ids=result.affected_task_ids,
        )
        if self._observability is not None:
            self._observability.reply_generated(
                conversation_id=conversation_id,
                request_id=None,
                conversational_act=result.conversational_act or "model_reply",
                affected_task_ids=result.affected_task_ids,
                reply_text=result.reply_text,
            )
        return CommunicationTurnResult(
            message_id=assistant_entry.message_id,
            reply_text=result.reply_text,
            conversational_act=result.conversational_act or "model_reply",
            tool_invocations=result.tool_invocations,
            affected_task_ids=result.affected_task_ids,
        )

    async def emit_notification(
        self,
        conversation_id: str,
        *,
        candidates: list[NotificationCandidate],
        on_trace: LlmTraceCallback | None = None,
        on_tool_call: ToolCallCallback | None = None,
    ) -> CommunicationTurnResult:
        context = await self._context_builder.build(
            conversation_id,
            available_tools=self._tool_usage_policy.available_tools,
        )
        rendering_context = build_notification_rendering_context(context, candidates)
        key_task = rendering_context.get("key_task")
        relevant_tasks = rendering_context.get("relevant_tasks", [])
        try:
            reply_text = await self._model.render_notification(
                context=context,
                candidates=candidates,
                on_trace=on_trace or self._trace_callback,
                on_tool_call=on_tool_call,
            )
        except Exception as exc:
            if self._observability is not None:
                self._observability.reply_failed(
                    conversation_id=conversation_id,
                    request_id=None,
                    reason_code=COMMUNICATION_MODEL_FAILURE,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            if len(candidates) == 1:
                reply_text = candidates[0].summary_short
            else:
                reply_text = "; ".join(candidate.summary_short for candidate in candidates)
        affected_task_ids = sorted({candidate.task_id for candidate in candidates})
        assistant_entry = self._append_assistant_entry(
            conversation_id,
            reply_text,
            focused_task_id=(
                str(key_task.get("task_id")) if isinstance(key_task, dict) and key_task.get("task_id") else None
            ),
            affected_task_ids=affected_task_ids,
        )
        if self._observability is not None:
            self._observability.reply_generated(
                conversation_id=conversation_id,
                request_id=None,
                conversational_act="inform_progress",
                affected_task_ids=affected_task_ids,
                reply_text=reply_text,
            )
        return CommunicationTurnResult(
            message_id=assistant_entry.message_id,
            reply_text=reply_text,
            conversational_act="inform_progress",
            affected_task_ids=affected_task_ids,
            notification_key_task_id=(
                str(key_task.get("task_id")) if isinstance(key_task, dict) and key_task.get("task_id") else None
            ),
            notification_relevant_task_ids=[
                str(task.get("task_id"))
                for task in relevant_tasks
                if isinstance(task, dict) and task.get("task_id")
            ],
        )

    def _ground_model_result(self, result: CommunicationModelResult) -> CommunicationModelResult:
        if (
            result.conversational_act in {"acknowledge_and_start", "acknowledge_and_modify", "acknowledge_and_hold"}
            and not result.affected_task_ids
        ):
            return CommunicationModelResult(
                reply_text="Can you clarify which task you mean?",
                tool_invocations=result.tool_invocations,
                affected_task_ids=[],
                conversational_act="request_clarification",
            )
        if not result.tool_invocations:
            return result
        tool_names = {item.tool_name for item in result.tool_invocations}
        write_tools = {"create_task", "update_task", "add_task_note", "add_constraint", "control_task"}
        if result.reply_text.strip():
            return result
        tool_results = {
            f"{item.tool_name}:{index}": item.result
            for index, item in enumerate(result.tool_invocations)
        }
        return CommunicationModelResult(
            reply_text=render_reply(
                result.conversational_act or "model_reply",
                tool_results=tool_results,
            ),
            tool_invocations=result.tool_invocations,
            affected_task_ids=result.affected_task_ids,
            conversational_act=result.conversational_act,
        )

    async def _handle_local_intent(
        self,
        conversation_id: str,
        user_text: str,
        *,
        context,
        on_tool_call: ToolCallCallback | None,
    ) -> CommunicationTurnResult | None:
        normalized = _normalize_user_text(user_text)
        correction_intent = _parse_generic_correction(user_text)
        if correction_intent is not None:
            return await self._handle_correction_intent(
                conversation_id,
                context=context,
                on_tool_call=on_tool_call,
                correction_intent=correction_intent,
            )
        if normalized in CONTINUE_PHRASES:
            return await self._handle_continue_intent(
                conversation_id,
                context=context,
                on_tool_call=on_tool_call,
            )
        if normalized in STOP_PHRASES:
            return await self._handle_stop_intent(
                conversation_id,
                context=context,
                on_tool_call=on_tool_call,
            )
        if _is_current_work_question(normalized):
            return await self._handle_current_work_question(
                conversation_id,
                context=context,
            )
        return None

    async def _handle_correction_intent(
        self,
        conversation_id: str,
        *,
        context,
        on_tool_call: ToolCallCallback | None,
        correction_intent: dict[str, str],
    ) -> CommunicationTurnResult:
        bundle = self._resolve_focused_bundle(
            conversation_id,
            context.tasks,
            allowed_statuses=ACTIVE_TASK_STATUSES,
        )
        if not bundle:
            return self._finalize_local_turn(
                conversation_id,
                reply_text="Which task should I update?",
                conversational_act="request_clarification",
            )
        bundle_slots = _extract_bundle_slots(bundle)
        target_slots = _select_correction_slots(bundle_slots, correction_intent)
        if target_slots is None:
            return self._finalize_local_turn(
                conversation_id,
                reply_text=_build_correction_clarification(bundle_slots, correction_intent),
                conversational_act="request_clarification",
                affected_task_ids=[task.task_id for task in bundle],
                focused_task_id=bundle[0].task_id,
                focused_task_ids=[task.task_id for task in bundle],
            )

        replaced_tasks = await self._replace_bundle_for_correction(
            bundle,
            target_slots=target_slots,
            correction_intent=correction_intent,
            on_tool_call=on_tool_call,
        )
        old_task_ids = [task.task_id for task in bundle]
        new_tasks = replaced_tasks["new_tasks"]
        new_task_ids = [task.task_id for task in new_tasks]
        if not self._bundle_correction_is_valid(
            bundle,
            new_tasks,
            target_slots=target_slots,
            correction_intent=correction_intent,
        ):
            return self._finalize_local_turn(
                conversation_id,
                reply_text="I need one more clarification before I update that.",
                conversational_act="request_clarification",
                affected_task_ids=old_task_ids + new_task_ids,
                focused_task_id=new_tasks[0].task_id if new_tasks else bundle[0].task_id,
                focused_task_ids=new_task_ids or old_task_ids,
            )
        reply_text = _build_correction_acknowledgement(correction_intent)
        return self._finalize_local_turn(
            conversation_id,
            reply_text=reply_text,
            conversational_act="acknowledge_and_modify",
            tool_invocations=replaced_tasks["tool_invocations"],
            affected_task_ids=old_task_ids + new_task_ids,
            focused_task_id=new_tasks[0].task_id if new_tasks else bundle[0].task_id,
            focused_task_ids=new_task_ids,
        )

    async def _handle_stop_intent(
        self,
        conversation_id: str,
        *,
        context,
        on_tool_call: ToolCallCallback | None,
    ) -> CommunicationTurnResult:
        task = self._resolve_focused_task(
            conversation_id,
            context.tasks,
            allowed_statuses=ACTIVE_TASK_STATUSES,
        )
        if task is None:
            return self._finalize_local_turn(
                conversation_id,
                reply_text="Which task do you want me to stop?",
                conversational_act="request_clarification",
            )
        result = await self._invoke_tool(
            "control_task",
            {
                "task_id": task.task_id,
                "command_type": "cancel_task",
            },
            on_tool_call=on_tool_call,
        )
        tool_invocation = ToolInvocationRecord(
            tool_name="control_task",
            args={"task_id": task.task_id, "command_type": "cancel_task"},
            result=result,
        )
        resolved_task = _extract_task_from_tool_result(result) or task
        return self._finalize_local_turn(
            conversation_id,
            reply_text=f"Okay, I won't continue with {resolved_task.title}.",
            conversational_act="acknowledge_and_hold",
            tool_invocations=[tool_invocation],
            affected_task_ids=[resolved_task.task_id],
            focused_task_id=resolved_task.task_id,
        )

    async def _handle_continue_intent(
        self,
        conversation_id: str,
        *,
        context,
        on_tool_call: ToolCallCallback | None,
    ) -> CommunicationTurnResult:
        focused_task_id = self._history.latest_focused_task_id(conversation_id)
        if not focused_task_id:
            return self._finalize_local_turn(
                conversation_id,
                reply_text="Which task do you want me to continue?",
                conversational_act="request_clarification",
            )
        task = _task_by_id(context.tasks, focused_task_id)
        if task is None:
            return self._finalize_local_turn(
                conversation_id,
                reply_text="Which task do you want me to continue?",
                conversational_act="request_clarification",
            )
        if task.status == TaskStatus.WAITING_USER_INPUT:
            pending_request = _pending_interaction_request_for_task(context, task.task_id)
            if pending_request is not None:
                prompt = pending_request.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    reply_text = f"I still need your input before I can continue: {prompt.strip()}"
                else:
                    reply_text = f"I still need your input before I can continue with {task.title}."
            else:
                reply_text = f"I still need your input before I can continue with {task.title}."
            return self._finalize_local_turn(
                conversation_id,
                reply_text=reply_text,
                conversational_act="request_clarification",
                affected_task_ids=[task.task_id],
                focused_task_id=task.task_id,
            )
        if task.status == TaskStatus.CANCELLED:
            recreated = await self._recreate_task_from_cancelled(
                task,
                on_tool_call=on_tool_call,
            )
            tool_invocations = [record["tool_invocation"] for record in recreated]
            new_task = recreated[-1]["task"]
            return self._finalize_local_turn(
                conversation_id,
                reply_text=f"Okay, I'll start {new_task.title} again.",
                conversational_act="acknowledge_and_start",
                tool_invocations=tool_invocations,
                affected_task_ids=[new_task.task_id],
                focused_task_id=new_task.task_id,
            )
        if task.status == TaskStatus.PAUSED:
            result = await self._invoke_tool(
                "control_task",
                {
                    "task_id": task.task_id,
                    "command_type": "resume_task",
                },
                on_tool_call=on_tool_call,
            )
            tool_invocation = ToolInvocationRecord(
                tool_name="control_task",
                args={"task_id": task.task_id, "command_type": "resume_task"},
                result=result,
            )
            resolved_task = _extract_task_from_tool_result(result) or task
            return self._finalize_local_turn(
                conversation_id,
                reply_text=f"Okay, I'll continue with {resolved_task.title}.",
                conversational_act="acknowledge_and_start",
                tool_invocations=[tool_invocation],
                affected_task_ids=[resolved_task.task_id],
                focused_task_id=resolved_task.task_id,
            )
        if task.status in ACTIVE_TASK_STATUSES:
            return self._finalize_local_turn(
                conversation_id,
                reply_text=f"I'm already working on {task.title}.",
                conversational_act="inform_progress",
                affected_task_ids=[task.task_id],
                focused_task_id=task.task_id,
            )
        return self._finalize_local_turn(
            conversation_id,
            reply_text="Which task do you want me to continue?",
            conversational_act="request_clarification",
        )

    async def _handle_current_work_question(
        self,
        conversation_id: str,
        *,
        context,
    ) -> CommunicationTurnResult:
        active_tasks = [task for task in reversed(context.tasks) if task.status in ACTIVE_TASK_STATUSES]
        if not active_tasks:
            return self._finalize_local_turn(
                conversation_id,
                reply_text="I'm not actively working on anything right now.",
                conversational_act="inform_progress",
            )
        task = active_tasks[0]
        summary = context.summaries.get(task.task_id)
        if len(active_tasks) == 1:
            if summary is not None and summary.conversational_summary:
                reply_text = (
                    f"I'm working on {task.title} right now. {summary.conversational_summary}"
                )
            else:
                reply_text = f"I'm working on {task.title} right now."
        else:
            reply_text = (
                f"I'm working on {task.title} right now, plus {len(active_tasks) - 1} other task"
                f"{'' if len(active_tasks) == 2 else 's'}."
            )
        return self._finalize_local_turn(
            conversation_id,
            reply_text=reply_text,
            conversational_act="inform_progress",
            affected_task_ids=[task.task_id],
            focused_task_id=task.task_id,
        )

    async def _recreate_task_from_cancelled(
        self,
        task: Task,
        *,
        on_tool_call: ToolCallCallback | None,
    ) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        create_args = {
            "title": task.title,
            "goal": task.goal,
            "preferred_executor": task.preferred_executor,
            "requires_confirmation": task.requires_confirmation,
            "mock_safe": bool(task.metadata.get("mock_safe", False)) or task.preferred_executor == "mock",
        }
        created_result = await self._invoke_tool(
            "create_task",
            create_args,
            on_tool_call=on_tool_call,
        )
        created_task = _extract_task_from_tool_result(created_result)
        if created_task is None:
            raise RuntimeError("create_task did not return a task.")
        records.append(
            {
                "tool_invocation": ToolInvocationRecord(
                    tool_name="create_task",
                    args=create_args,
                    result=created_result,
                ),
                "task": created_task,
            }
        )
        patch: dict[str, object] = {}
        if task.priority != created_task.priority:
            patch["priority"] = task.priority
        if task.interruptible != created_task.interruptible:
            patch["interruptible"] = task.interruptible
        if task.latest_instruction is not None:
            patch["latest_instruction"] = task.latest_instruction
        if task.session_affinity != created_task.session_affinity:
            patch["session_affinity"] = task.session_affinity
        if patch:
            update_result = await self._invoke_tool(
                "update_task",
                {
                    "task_id": created_task.task_id,
                    "patch": patch,
                },
                on_tool_call=on_tool_call,
            )
            created_task = _extract_task_from_tool_result(update_result) or created_task
            records.append(
                {
                    "tool_invocation": ToolInvocationRecord(
                        tool_name="update_task",
                        args={"task_id": created_task.task_id, "patch": patch},
                        result=update_result,
                    ),
                    "task": created_task,
                }
            )
        for note in task.metadata.get("notes", []):
            if not isinstance(note, str) or not note.strip():
                continue
            note_args = {
                "task_id": created_task.task_id,
                "note": note,
            }
            note_result = await self._invoke_tool(
                "add_task_note",
                note_args,
                on_tool_call=on_tool_call,
            )
            created_task = _extract_task_from_tool_result(note_result) or created_task
            records.append(
                {
                    "tool_invocation": ToolInvocationRecord(
                        tool_name="add_task_note",
                        args=note_args,
                        result=note_result,
                    ),
                    "task": created_task,
                }
            )
        for item in task.metadata.get("constraints", []):
            if not isinstance(item, dict):
                continue
            constraint = item.get("constraint")
            if not isinstance(constraint, str) or not constraint.strip():
                continue
            constraint_args = {
                "task_id": created_task.task_id,
                "constraint": constraint,
                "category": str(item.get("category")) if item.get("category") is not None else None,
            }
            constraint_result = await self._invoke_tool(
                "add_constraint",
                constraint_args,
                on_tool_call=on_tool_call,
            )
            created_task = _extract_task_from_tool_result(constraint_result) or created_task
            records.append(
                {
                    "tool_invocation": ToolInvocationRecord(
                        tool_name="add_constraint",
                        args=constraint_args,
                        result=constraint_result,
                    ),
                    "task": created_task,
                }
            )
        created_task.metadata["recreated_from_task_id"] = task.task_id
        await self._store.put_task(created_task)
        await self._store.append_mutation(
            TaskMutation(
                mutation_id=f"mut-{uuid4().hex[:8]}",
                task_id=created_task.task_id,
                mutation_type=MutationType.UPDATE,
                patch={"recreated_from_task_id": task.task_id},
                created_by="communication_brain",
            )
            )
        return records

    async def _replace_bundle_for_correction(
        self,
        bundle: list[Task],
        *,
        target_slots: list[BundleSlot],
        correction_intent: dict[str, str],
        on_tool_call: ToolCallCallback | None,
    ) -> dict[str, object]:
        new_tasks: list[Task] = []
        tool_invocations: list[ToolInvocationRecord] = []
        slots_by_task: dict[str, list[BundleSlot]] = {}
        for slot in target_slots:
            slots_by_task.setdefault(slot.task_id, []).append(slot)
        for task in bundle:
            clone_result = await self._clone_task_with_correction(
                task,
                target_slots=slots_by_task.get(task.task_id, []),
                correction_intent=correction_intent,
                on_tool_call=on_tool_call,
            )
            new_tasks.append(clone_result["task"])
            tool_invocations.extend(clone_result["tool_invocations"])

        for old_task, new_task in zip(bundle, new_tasks, strict=False):
            old_task.metadata["replaced_by_task_id"] = new_task.task_id
            await self._store.put_task(old_task)
            await self._store.append_mutation(
                TaskMutation(
                    mutation_id=f"mut-{uuid4().hex[:8]}",
                    task_id=old_task.task_id,
                    mutation_type=MutationType.UPDATE,
                    patch={"replaced_by_task_id": new_task.task_id},
                    created_by="communication_brain",
                )
            )
            cancel_args = {
                "task_id": old_task.task_id,
                "command_type": "cancel_task",
            }
            cancel_result = await self._invoke_tool(
                "control_task",
                cancel_args,
                on_tool_call=on_tool_call,
            )
            tool_invocations.append(
                ToolInvocationRecord(
                    tool_name="control_task",
                    args=cancel_args,
                    result=cancel_result,
                )
            )

        return {
            "new_tasks": new_tasks,
            "tool_invocations": tool_invocations,
        }

    async def _clone_task_with_correction(
        self,
        task: Task,
        *,
        target_slots: list[BundleSlot],
        correction_intent: dict[str, str],
        on_tool_call: ToolCallCallback | None,
    ) -> dict[str, object]:
        tool_invocations: list[ToolInvocationRecord] = []
        create_args = {
            "title": _apply_correction_to_text(task.title, target_slots, correction_intent),
            "goal": _apply_correction_to_text(task.goal, target_slots, correction_intent),
            "preferred_executor": task.preferred_executor,
            "requires_confirmation": task.requires_confirmation,
            "mock_safe": bool(task.metadata.get("mock_safe", False)) or task.preferred_executor == "mock",
        }
        created_result = await self._invoke_tool(
            "create_task",
            create_args,
            on_tool_call=on_tool_call,
        )
        created_task = _extract_task_from_tool_result(created_result)
        if created_task is None:
            raise RuntimeError("create_task did not return a task.")
        tool_invocations.append(
            ToolInvocationRecord(
                tool_name="create_task",
                args=create_args,
                result=created_result,
            )
        )
        patch: dict[str, object] = {}
        if task.priority != created_task.priority:
            patch["priority"] = task.priority
        if task.interruptible != created_task.interruptible:
            patch["interruptible"] = task.interruptible
        if task.latest_instruction is not None:
            patch["latest_instruction"] = _apply_correction_to_text(
                task.latest_instruction,
                target_slots,
                correction_intent,
            )
        if task.session_affinity != created_task.session_affinity:
            patch["session_affinity"] = task.session_affinity
        if patch:
            update_result = await self._invoke_tool(
                "update_task",
                {
                    "task_id": created_task.task_id,
                    "patch": patch,
                },
                on_tool_call=on_tool_call,
            )
            created_task = _extract_task_from_tool_result(update_result) or created_task
            tool_invocations.append(
                ToolInvocationRecord(
                    tool_name="update_task",
                    args={"task_id": created_task.task_id, "patch": patch},
                    result=update_result,
                )
            )
        for note in task.metadata.get("notes", []):
            if not isinstance(note, str) or not note.strip():
                continue
            note_args = {
                "task_id": created_task.task_id,
                "note": _apply_correction_to_text(note, target_slots, correction_intent),
            }
            note_result = await self._invoke_tool(
                "add_task_note",
                note_args,
                on_tool_call=on_tool_call,
            )
            created_task = _extract_task_from_tool_result(note_result) or created_task
            tool_invocations.append(
                ToolInvocationRecord(
                    tool_name="add_task_note",
                    args=note_args,
                    result=note_result,
                )
            )
        for item in task.metadata.get("constraints", []):
            if not isinstance(item, dict):
                continue
            constraint = item.get("constraint")
            if not isinstance(constraint, str) or not constraint.strip():
                continue
            constraint_args = {
                "task_id": created_task.task_id,
                "constraint": _apply_correction_to_text(
                    constraint,
                    target_slots,
                    correction_intent,
                ),
                "category": str(item.get("category")) if item.get("category") is not None else None,
            }
            constraint_result = await self._invoke_tool(
                "add_constraint",
                constraint_args,
                on_tool_call=on_tool_call,
            )
            created_task = _extract_task_from_tool_result(constraint_result) or created_task
            tool_invocations.append(
                ToolInvocationRecord(
                    tool_name="add_constraint",
                    args=constraint_args,
                    result=constraint_result,
                )
            )
        created_task.metadata["replacement_for_task_id"] = task.task_id
        created_task.metadata["correction_new_value"] = correction_intent["new_value"]
        if correction_intent.get("old_value") is not None:
            created_task.metadata["correction_old_value"] = correction_intent["old_value"]
        if correction_intent.get("target_group") is not None:
            created_task.metadata["correction_target_group"] = correction_intent["target_group"]
        await self._store.put_task(created_task)
        await self._store.append_mutation(
            TaskMutation(
                mutation_id=f"mut-{uuid4().hex[:8]}",
                task_id=created_task.task_id,
                mutation_type=MutationType.UPDATE,
                patch={
                    "replacement_for_task_id": task.task_id,
                    "correction_new_value": correction_intent["new_value"],
                    **(
                        {"correction_old_value": correction_intent["old_value"]}
                        if correction_intent.get("old_value") is not None
                        else {}
                    ),
                    **(
                        {"correction_target_group": correction_intent["target_group"]}
                        if correction_intent.get("target_group") is not None
                        else {}
                    ),
                },
                created_by="communication_brain",
            )
        )
        return {
            "task": created_task,
            "tool_invocations": tool_invocations,
        }

    def _bundle_correction_is_valid(
        self,
        old_bundle: list[Task],
        new_bundle: list[Task],
        *,
        target_slots: list[BundleSlot],
        correction_intent: dict[str, str],
    ) -> bool:
        if len(old_bundle) != len(new_bundle):
            return False
        slots_by_task: dict[str, list[BundleSlot]] = {}
        for slot in target_slots:
            slots_by_task.setdefault(slot.task_id, []).append(slot)
        for task in old_bundle:
            if task.status != TaskStatus.CANCELLED:
                return False
        for old_task, new_task in zip(old_bundle, new_bundle, strict=False):
            for slot in slots_by_task.get(old_task.task_id, []):
                if not _task_has_cued_value(new_task, slot.cue, correction_intent["new_value"]):
                    return False
                if _task_has_cued_value(new_task, slot.cue, slot.value):
                    return False
        return True

    async def _invoke_tool(
        self,
        tool_name: str,
        args: dict[str, object],
        *,
        on_tool_call: ToolCallCallback | None,
    ) -> object:
        tool = self._tools.get(tool_name)
        try:
            result = await tool.invoke(**args)
        except ToolInputError as exc:
            if on_tool_call is not None:
                await _emit_tool_call(
                    on_tool_call,
                    ToolCallRecord(
                        tool_name=tool_name,
                        args=args,
                        status="failed",
                        error=ToolCallError(code=exc.code, message=str(exc)),
                    ),
                )
            raise
        except Exception as exc:
            if on_tool_call is not None:
                await _emit_tool_call(
                    on_tool_call,
                    ToolCallRecord(
                        tool_name=tool_name,
                        args=args,
                        status="failed",
                        error=ToolCallError(code="tool_error", message=str(exc) or "Tool call failed."),
                    ),
                )
            raise
        if on_tool_call is not None:
            task = _extract_task_from_tool_result(result)
            await _emit_tool_call(
                on_tool_call,
                ToolCallRecord(
                    tool_name=tool_name,
                    args=args,
                    status="succeeded",
                    affected_task_ids=[task.task_id] if task is not None else [],
                ),
            )
        return result

    def _resolve_focused_task(
        self,
        conversation_id: str,
        tasks: list[Task],
        *,
        allowed_statuses: set[TaskStatus],
    ) -> Task | None:
        bundle = self._resolve_focused_bundle(
            conversation_id,
            tasks,
            allowed_statuses=allowed_statuses,
        )
        return bundle[0] if bundle else None

    def _resolve_focused_bundle(
        self,
        conversation_id: str,
        tasks: list[Task],
        *,
        allowed_statuses: set[TaskStatus],
    ) -> list[Task]:
        focused_task_ids = self._history.latest_focused_task_ids(conversation_id)
        if not focused_task_ids:
            return []
        bundle: list[Task] = []
        for task_id in focused_task_ids:
            task = _task_by_id(tasks, task_id)
            if task is None or task.status not in allowed_statuses:
                return []
            bundle.append(task)
        return bundle

    def _append_assistant_entry(
        self,
        conversation_id: str,
        reply_text: str,
        *,
        focused_task_id: str | None = None,
        focused_task_ids: list[str] | None = None,
        affected_task_ids: list[str] | None = None,
    ) -> ConversationEntry:
        resolved_affected = list(affected_task_ids or [])
        resolved_focus_ids = list(focused_task_ids or resolved_affected)
        resolved_focus = focused_task_id or (resolved_focus_ids[0] if resolved_focus_ids else None)
        return self._history.append_assistant(
            conversation_id,
            reply_text,
            focused_task_id=resolved_focus,
            focused_task_ids=resolved_focus_ids,
            affected_task_ids=resolved_affected,
        )

    def _finalize_local_turn(
        self,
        conversation_id: str,
        *,
        reply_text: str,
        conversational_act: str,
        tool_invocations: list[ToolInvocationRecord] | None = None,
        affected_task_ids: list[str] | None = None,
        focused_task_id: str | None = None,
        focused_task_ids: list[str] | None = None,
    ) -> CommunicationTurnResult:
        assistant_entry = self._append_assistant_entry(
            conversation_id,
            reply_text,
            focused_task_id=focused_task_id,
            focused_task_ids=focused_task_ids,
            affected_task_ids=affected_task_ids,
        )
        resolved_affected = list(affected_task_ids or [])
        if self._observability is not None:
            self._observability.reply_generated(
                conversation_id=conversation_id,
                request_id=None,
                conversational_act=conversational_act,
                affected_task_ids=resolved_affected,
                reply_text=reply_text,
            )
        return CommunicationTurnResult(
            message_id=assistant_entry.message_id,
            reply_text=reply_text,
            conversational_act=conversational_act,
            tool_invocations=list(tool_invocations or []),
            affected_task_ids=resolved_affected,
        )


def _normalize_user_text(user_text: str) -> str:
    lowered = user_text.strip().lower()
    for ch in ("?", "!", ".", ","):
        lowered = lowered.replace(ch, " ")
    return " ".join(lowered.split())


def _parse_generic_correction(user_text: str) -> dict[str, str] | None:
    normalized = _normalize_user_text(user_text)
    replacement_match = CORRECTION_OLD_NEW_RE.match(normalized)
    if replacement_match is not None:
        return {
            "kind": "replacement",
            "new_value": _title_case_location(replacement_match.group("new")),
            "old_value": _title_case_location(replacement_match.group("old")),
            "target_group": _cue_to_group(
                replacement_match.group("cue") or replacement_match.group("old_cue")
            ),
        }
    should_be_match = CORRECTION_SHOULD_BE_RE.match(normalized)
    if should_be_match is not None:
        return {
            "kind": "correction",
            "new_value": _title_case_location(should_be_match.group("new")),
            "target_group": _cue_to_group(should_be_match.group("cue")),
        }
    cue_match = CORRECTION_DIRECT_CUE_RE.match(normalized)
    if cue_match is not None:
        return {
            "kind": "correction",
            "new_value": _title_case_location(cue_match.group("new")),
            "target_group": _cue_to_group(cue_match.group("cue")),
        }
    return None


def _is_current_work_question(normalized: str) -> bool:
    return (
        "what are you working on" in normalized
        or "what are you working with" in normalized
        or normalized == "what are you working"
    )


def _task_by_id(tasks: list[Task], task_id: str) -> Task | None:
    for task in tasks:
        if task.task_id == task_id:
            return task
    return None


def _pending_interaction_request_for_task(context, task_id: str) -> dict[str, object] | None:
    requests = context.interaction_requests or []
    for request in requests:
        if (
            isinstance(request, dict)
            and request.get("task_id") == task_id
            and request.get("status") == "pending"
        ):
            return request
    return None


def _extract_bundle_slots(tasks: list[Task]) -> list[BundleSlot]:
    slots: list[BundleSlot] = []
    for task in tasks:
        for field_name, text in (
            ("title", task.title),
            ("goal", task.goal),
            ("latest_instruction", task.latest_instruction or ""),
        ):
            for match in SLOT_PHRASE_RE.finditer(text):
                cue = match.group("cue").lower()
                value = _title_case_location(match.group("value"))
                slots.append(
                    BundleSlot(
                        task_id=task.task_id,
                        field_name=field_name,
                        cue=cue,
                        group=_cue_to_group(cue),
                        value=value,
                    )
                )
    return slots


def _select_correction_slots(
    slots: list[BundleSlot],
    correction_intent: dict[str, str],
) -> list[BundleSlot] | None:
    if not slots:
        return None
    target_group = correction_intent.get("target_group")
    old_value = correction_intent.get("old_value")
    if old_value is not None:
        matched = [slot for slot in slots if slot.value.lower() == old_value.lower()]
        if target_group is not None:
            matched = [slot for slot in matched if slot.group == target_group]
        if not matched:
            return None
        groups = {slot.group for slot in matched}
        if target_group is None and len(groups) > 1:
            return None
        return matched
    if target_group is not None:
        matched = [slot for slot in slots if slot.group == target_group]
        return matched or None
    if len(slots) == 1:
        return slots
    return None


def _build_correction_clarification(
    slots: list[BundleSlot],
    correction_intent: dict[str, str],
) -> str:
    new_value = correction_intent["new_value"]
    old_value = correction_intent.get("old_value")
    target_group = correction_intent.get("target_group")
    if old_value is not None:
        if target_group == "destination":
            return f"Do you mean the destination should be {new_value} instead of {old_value}?"
        if target_group == "origin":
            return f"Do you mean the origin should be {new_value} instead of {old_value}?"
        return f"Do you mean {new_value} instead of {old_value}?"
    if target_group == "destination":
        current = _infer_common_slot_value(slots, "destination")
        if current is not None:
            return f"Do you mean the destination should be {new_value} instead of {current}?"
        return f"Do you mean the destination should be {new_value} instead?"
    if target_group == "origin":
        current = _infer_common_slot_value(slots, "origin")
        if current is not None:
            return f"Do you mean the origin should be {new_value} instead of {current}?"
        return f"Do you mean the origin should be {new_value} instead?"
    destination = _infer_common_slot_value(slots, "destination")
    if destination is not None:
        return f"Do you mean the destination should be {new_value} instead of {destination}?"
    return f"Do you mean {new_value} instead?"


def _infer_common_slot_value(slots: list[BundleSlot], group: str) -> str | None:
    values = [slot.value for slot in slots if slot.group == group]
    if not values:
        return None
    first = values[0]
    return first if all(value == first for value in values) else None


def _apply_correction_to_text(
    value: str | None,
    target_slots: list[BundleSlot],
    correction_intent: dict[str, str],
) -> str:
    if value is None:
        return ""
    updated = value
    for slot in target_slots:
        pattern = re.compile(
            rf"\b{re.escape(slot.cue)}\s+{re.escape(slot.value)}(?=\s+(?:for|from|to|instead|today|tomorrow)\b|[.,!?]|$)",
            re.IGNORECASE,
        )
        updated = pattern.sub(f"{slot.cue} {correction_intent['new_value']}", updated)
    return updated


def _task_has_cued_value(task: Task, cue: str, value: str) -> bool:
    pattern = re.compile(
        rf"\b{re.escape(cue)}\s+{re.escape(value)}(?=\s+(?:for|from|to|instead|today|tomorrow)\b|[.,!?]|$)",
        re.IGNORECASE,
    )
    haystacks = [task.title, task.goal, task.latest_instruction or ""]
    haystacks.extend(
        note for note in task.metadata.get("notes", []) if isinstance(note, str)
    )
    haystacks.extend(
        item.get("constraint", "")
        for item in task.metadata.get("constraints", [])
        if isinstance(item, dict) and isinstance(item.get("constraint"), str)
    )
    return any(pattern.search(text) for text in haystacks if text)


def _build_correction_acknowledgement(correction_intent: dict[str, str]) -> str:
    old_value = correction_intent.get("old_value")
    new_value = correction_intent["new_value"]
    target_group = correction_intent.get("target_group")
    if old_value is not None:
        return f"Okay, I replaced {old_value} with {new_value} in those tasks."
    if target_group == "destination":
        return f"Okay, I updated the destination to {new_value}."
    if target_group == "origin":
        return f"Okay, I updated the origin to {new_value}."
    return f"Okay, I updated that to {new_value}."


def _cue_to_group(cue: str | None) -> str | None:
    if cue is None:
        return None
    normalized = cue.lower()
    if normalized == "from":
        return "origin"
    if normalized in {"to", "in", "at"}:
        return "destination"
    return None


def _title_case_location(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


def _extract_task_from_tool_result(result: object) -> Task | None:
    if isinstance(result, Task):
        return result
    if isinstance(result, dict):
        task = result.get("task")
        if isinstance(task, Task):
            return task
    return None


async def _emit_tool_call(
    callback: ToolCallCallback,
    record: ToolCallRecord,
) -> None:
    maybe_awaitable = callback(record)
    if hasattr(maybe_awaitable, "__await__"):
        await maybe_awaitable
