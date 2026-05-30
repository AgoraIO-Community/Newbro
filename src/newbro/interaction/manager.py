from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.blackboard.store import BlackboardWriteEvent, BlackboardWriteKind
from newbro.protocol import (
    AttentionItem,
    AttentionItemKind,
    AttentionItemStatus,
    AttentionPriority,
    CodexTurnEventMessage,
    ExecutionRun,
    InteractionRequest,
    InteractionRequestKind,
    InteractionRequestStatus,
    OutboundTurnRequest,
    RunStatus,
    Task,
    TaskSummary,
)

from .sanitization import (
    build_interaction_request_opaque,
    sanitize_blocked_event_for_client,
)


@dataclass(slots=True)
class InteractionResolution:
    request: InteractionRequest
    follow_up_instruction: str
    answer_text: str | None = None
    answers: dict[str, list[str]] | None = None


class InteractionManager:
    def __init__(self, store: BlackboardStore) -> None:
        self._store = store

    async def handle_blackboard_write(self, event: BlackboardWriteEvent) -> bool:
        if event.kind == BlackboardWriteKind.RUN and event.entity_id:
            run = await self._store.get_run(event.entity_id)
            if run is None or run.status != RunStatus.BLOCKED:
                return False
            task = await self._store.get_task(run.task_id)
            if task is None:
                return False
            summary = await self._store.get_summary(task.task_id)
            existing = await self._store.list_interaction_requests()
            if any(
                request.run_id == run.run_id
                and request.status == InteractionRequestStatus.PENDING
                for request in existing
            ):
                return False
            request = _build_request_from_run(task=task, run=run, summary=summary)
            await self._store.put_interaction_request(request)
            await self._store.put_attention_item(_build_attention_from_request(task=task, request=request))
            return True

        if event.kind == BlackboardWriteKind.SUMMARY and event.entity_id:
            task = await self._store.get_task(event.entity_id)
            summary = await self._store.get_summary(event.entity_id)
            if task is None or summary is None or not summary.needs_user_input:
                return False
            existing = await self._store.list_interaction_requests()
            if any(
                request.task_id == task.task_id
                and request.status == InteractionRequestStatus.PENDING
                for request in existing
            ):
                return False
            request = _build_request_from_summary(task=task, summary=summary)
            await self._store.put_interaction_request(request)
            await self._store.put_attention_item(_build_attention_from_request(task=task, request=request))
            return True

        return False

    async def resolve_request(
        self,
        request_id: str,
        *,
        action: str,
        answer_text: str | None = None,
        option_id: str | None = None,
        answers: dict[str, list[str]] | None = None,
        reason: str | None = None,
    ) -> InteractionResolution:
        request = await self._store.get_interaction_request(request_id)
        if request is None:
            raise KeyError(f"Unknown interaction request: {request_id}")
        if request.status != InteractionRequestStatus.PENDING:
            raise ValueError("Interaction request is no longer pending.")
        if action not in request.available_actions:
            allowed = ", ".join(request.available_actions) or "none"
            raise ValueError(f"Action '{action}' is not allowed. Allowed: {allowed}.")
        if request.kind == InteractionRequestKind.PLAN_PROPOSAL:
            answers = _normalize_proposal_answers(request=request, answers=answers)
            answer_text = _plan_proposal_answer_text(
                request=request,
                action=action,
                answer_text=answer_text,
                option_id=option_id,
                answers=answers,
            )
        if action == "answer" and not (answer_text and answer_text.strip()):
            raise ValueError("answer_text is required for answer actions.")

        resolved_status = _resolved_status_for_action(action)
        resolved_at = _now_iso()
        updated_request = request.model_copy(
            update={
                "status": resolved_status,
                "resolved_at": resolved_at,
                "details": {
                    **request.details,
                    **({"selected_option_id": option_id} if option_id else {}),
                    **({"selected_answers": answers} if answers else {}),
                    **({"resolution_reason": reason} if reason else {}),
                },
            }
        )
        await self._store.put_interaction_request(updated_request)
        await self._mark_attention_for_request(
            request_id=request.request_id,
            status=AttentionItemStatus.ACTED,
        )
        return InteractionResolution(
            request=updated_request,
            follow_up_instruction=_build_follow_up_instruction(
                request=updated_request,
                action=action,
                answer_text=answer_text,
            ),
            answer_text=answer_text,
            answers=answers,
        )

    async def add_task_signal_attention(
        self,
        *,
        task: Task,
        kind: AttentionItemKind,
        body: str,
    ) -> AttentionItem:
        item = AttentionItem(
            attention_id=f"attention-{uuid4().hex[:8]}",
            source="task_signal",
            kind=kind,
            priority=AttentionPriority.P2,
            title=_task_signal_title(task, kind),
            body=body,
            task_id=task.task_id,
            dedupe_key=f"{kind.value}:{task.task_id}:{task.task_revision}",
            created_at=_now_iso(),
        )
        await self._store.put_attention_item(item)
        return item

    async def handle_outbound_codex_blocked(
        self,
        *,
        outbound_request: OutboundTurnRequest,
        message: CodexTurnEventMessage,
    ) -> InteractionRequest | None:
        if message.event_type.lower() != "blocked":
            return None
        metadata = message.metadata or {}
        if not metadata.get("interaction_kind"):
            return None
        prompt = metadata.get("prompt") or message.message
        if not isinstance(prompt, str) or not prompt.strip():
            return None
        existing = await self._store.list_interaction_requests()
        if any(
            request.outbound_turn_request_id == outbound_request.request_id
            and request.status == InteractionRequestStatus.PENDING
            for request in existing
        ):
            return None
        request = _build_request_from_outbound_blocked(
            outbound_request=outbound_request,
            message=message,
        )
        await self._store.put_interaction_request(request)
        await self._store.put_attention_item(
            _build_attention_from_outbound_request(
                outbound_request=outbound_request,
                request=request,
            )
        )
        return request

    async def cancel_requests_for_task(self, task_id: str) -> None:
        requests = await self._store.list_interaction_requests()
        for request in requests:
            if request.task_id != task_id or request.status != InteractionRequestStatus.PENDING:
                continue
            await self._store.put_interaction_request(
                request.model_copy(
                    update={
                        "status": InteractionRequestStatus.CANCELLED,
                        "resolved_at": _now_iso(),
                    }
                )
            )
            await self._mark_attention_for_request(
                request_id=request.request_id,
                status=AttentionItemStatus.DISMISSED,
            )

    async def _mark_attention_for_request(
        self,
        *,
        request_id: str,
        status: AttentionItemStatus,
    ) -> None:
        items = await self._store.list_attention_items()
        for item in items:
            if item.request_id != request_id or item.status == status:
                continue
            await self._store.put_attention_item(item.model_copy(update={"status": status}))


def _build_request_from_run(
    *,
    task: Task,
    run: ExecutionRun,
    summary: TaskSummary | None,
) -> InteractionRequest:
    prompt = (
        run.block_reason
        or (summary.conversational_summary if summary is not None else None)
        or f"{task.title} needs your input."
    )
    kind = _classify_prompt(prompt, run.metadata.get("blocked_event"))
    return InteractionRequest(
        request_id=f"ireq-{uuid4().hex[:8]}",
        task_id=task.task_id,
        execution_session_id=run.execution_session_id,
        run_id=run.run_id,
        executor_type=run.executor_type,
        kind=kind,
        prompt=prompt,
        details=_request_details(task=task, blocked_event=run.metadata.get("blocked_event")),
        available_actions=_actions_for_kind(kind),
        answer_schema={"type": "string"} if kind == InteractionRequestKind.QUESTION else None,
        opaque=build_interaction_request_opaque(blocked_event=run.metadata.get("blocked_event")),
        created_at=_now_iso(),
    )


def _build_request_from_outbound_blocked(
    *,
    outbound_request: OutboundTurnRequest,
    message: CodexTurnEventMessage,
) -> InteractionRequest:
    metadata = message.metadata or {}
    prompt = str(metadata.get("prompt") or message.message or "").strip()
    blocked_event: dict[str, object] = {
        "thread_id": metadata.get("thread_id") or message.executor_thread_id or "",
        "prompt": prompt,
        "interaction_kind": metadata.get("interaction_kind"),
        "blocked_method": metadata.get("blocked_method"),
        "native_response": metadata.get("native_response"),
        "proposal": metadata.get("proposal"),
    }
    kind = _classify_prompt(prompt, blocked_event)
    details: dict[str, object] = {
        "persona_id": outbound_request.persona_id,
        "target_thread_id": outbound_request.target_thread_id,
        "outbound_turn_request_id": outbound_request.request_id,
    }
    if outbound_request.client_request_id:
        details["client_request_id"] = outbound_request.client_request_id
    sanitized_blocked_event = sanitize_blocked_event_for_client(blocked_event)
    if sanitized_blocked_event is not None:
        details["blocked_event"] = sanitized_blocked_event
    proposal = _proposal_details_from_blocked_event(blocked_event)
    if proposal is not None:
        details["proposal"] = proposal
    has_native_response = isinstance(metadata.get("native_response"), dict)
    return InteractionRequest(
        request_id=f"ireq-{uuid4().hex[:8]}",
        task_id=None,
        outbound_turn_request_id=outbound_request.request_id,
        executor_type=outbound_request.executor_id,
        executor_node_id=outbound_request.executor_node_id,
        kind=kind,
        prompt=prompt,
        details=details,
        available_actions=_actions_for_kind(kind),
        answer_schema={"type": "string"} if kind == InteractionRequestKind.QUESTION else None,
        resume_strategy="native_response" if has_native_response else "follow_up_run",
        opaque=build_interaction_request_opaque(blocked_event=blocked_event),
        created_at=_now_iso(),
    )


def _build_attention_from_outbound_request(
    *,
    outbound_request: OutboundTurnRequest,
    request: InteractionRequest,
) -> AttentionItem:
    item_kind = {
        InteractionRequestKind.PERMISSION: AttentionItemKind.PERMISSION_REQUEST,
        InteractionRequestKind.QUESTION: AttentionItemKind.QUESTION_REQUEST,
        InteractionRequestKind.CONFIRMATION: AttentionItemKind.CONFIRMATION_REQUEST,
        InteractionRequestKind.PLAN_PROPOSAL: AttentionItemKind.PLAN_PROPOSAL_REQUEST,
    }[request.kind]
    persona_label = outbound_request.persona_id or "Codex"
    titles = {
        InteractionRequestKind.PERMISSION: f"{persona_label} needs permission",
        InteractionRequestKind.CONFIRMATION: f"{persona_label} needs confirmation",
        InteractionRequestKind.PLAN_PROPOSAL: f"{persona_label} proposed a plan",
        InteractionRequestKind.QUESTION: f"{persona_label} needs your input",
    }
    return AttentionItem(
        attention_id=f"attention-{uuid4().hex[:8]}",
        source="interaction_request",
        kind=item_kind,
        priority=AttentionPriority.P0,
        title=titles[request.kind],
        body=request.prompt,
        request_id=request.request_id,
        actions=_attention_actions_for_request(request),
        dedupe_key=f"{item_kind.value}:outbound:{outbound_request.request_id}",
        created_at=_now_iso(),
    )


def _build_request_from_summary(
    *,
    task: Task,
    summary: TaskSummary,
) -> InteractionRequest:
    prompt = summary.conversational_summary or f"{task.title} needs your input."
    kind = _classify_prompt(prompt, None)
    return InteractionRequest(
        request_id=f"ireq-{uuid4().hex[:8]}",
        task_id=task.task_id,
        kind=kind,
        prompt=prompt,
        details=_request_details(task=task, blocked_event=None),
        available_actions=_actions_for_kind(kind),
        answer_schema={"type": "string"} if kind == InteractionRequestKind.QUESTION else None,
        created_at=_now_iso(),
    )


def _build_attention_from_request(*, task: Task, request: InteractionRequest) -> AttentionItem:
    item_kind = {
        InteractionRequestKind.PERMISSION: AttentionItemKind.PERMISSION_REQUEST,
        InteractionRequestKind.QUESTION: AttentionItemKind.QUESTION_REQUEST,
        InteractionRequestKind.CONFIRMATION: AttentionItemKind.CONFIRMATION_REQUEST,
        InteractionRequestKind.PLAN_PROPOSAL: AttentionItemKind.PLAN_PROPOSAL_REQUEST,
    }[request.kind]
    return AttentionItem(
        attention_id=f"attention-{uuid4().hex[:8]}",
        source="interaction_request",
        kind=item_kind,
        priority=AttentionPriority.P0,
        title=_request_title(task, request.kind),
        body=request.prompt,
        task_id=task.task_id,
        request_id=request.request_id,
        actions=_attention_actions_for_request(request),
        dedupe_key=f"{item_kind.value}:{task.task_id}:{request.run_id or request.request_id}",
        created_at=_now_iso(),
    )


def _request_details(*, task: Task, blocked_event: object) -> dict[str, object]:
    details: dict[str, object] = {}
    for source_key, detail_key in (
        ("persona_id", "persona_id"),
        ("assigned_bro_id", "persona_id"),
        ("target_thread_id", "target_thread_id"),
        ("bro_thread_id", "target_thread_id"),
        ("client_request_id", "client_request_id"),
        ("source_kind", "source_kind"),
    ):
        if detail_key in details:
            continue
        value = task.metadata.get(source_key)
        if isinstance(value, str) and value:
            details[detail_key] = value
    persona_name = task.metadata.get("persona_name")
    if isinstance(persona_name, str) and persona_name:
        details["persona_name"] = persona_name
    sanitized_blocked_event = sanitize_blocked_event_for_client(blocked_event)
    if sanitized_blocked_event is not None:
        details["blocked_event"] = sanitized_blocked_event
    proposal = _proposal_details_from_blocked_event(blocked_event)
    if proposal is not None:
        details["proposal"] = proposal
    return details


def _classify_prompt(prompt: str, blocked_event: object) -> InteractionRequestKind:
    if isinstance(blocked_event, dict):
        explicit = blocked_event.get("interaction_kind")
        if explicit == "plan_proposal":
            return InteractionRequestKind.PLAN_PROPOSAL
        if explicit == "permission":
            return InteractionRequestKind.PERMISSION
        if explicit == "confirmation":
            return InteractionRequestKind.CONFIRMATION
        if explicit == "question":
            return InteractionRequestKind.QUESTION
    normalized = prompt.lower()
    if any(token in normalized for token in ["allow", "permission", "approve", "grant access"]):
        return InteractionRequestKind.PERMISSION
    if any(token in normalized for token in ["confirm", "confirmation", "are you sure"]):
        return InteractionRequestKind.CONFIRMATION
    return InteractionRequestKind.QUESTION


def _actions_for_kind(kind: InteractionRequestKind) -> list[str]:
    if kind == InteractionRequestKind.PERMISSION:
        return ["approve", "deny"]
    if kind == InteractionRequestKind.PLAN_PROPOSAL:
        return ["approve", "deny"]
    if kind == InteractionRequestKind.CONFIRMATION:
        return ["confirm", "cancel"]
    return ["answer"]


def _attention_actions_for_request(request: InteractionRequest) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    for action in request.available_actions:
        if request.kind == InteractionRequestKind.PLAN_PROPOSAL and action == "deny":
            label = "Keep planning"
        elif request.kind == InteractionRequestKind.PLAN_PROPOSAL and action == "approve":
            label = "Approve & run"
        else:
            label = {
                "approve": "Allow",
                "deny": "Deny",
                "answer": "Answer",
                "confirm": "Confirm",
                "cancel": "Cancel",
            }.get(action, action.replace("_", " ").title())
        actions.append({"action": action, "label": label})
    return actions


def _request_title(task: Task, kind: InteractionRequestKind) -> str:
    actor = task.metadata.get("persona_name")
    subject = str(actor) if isinstance(actor, str) and actor else task.title
    if kind == InteractionRequestKind.PERMISSION:
        return f"{subject} needs permission"
    if kind == InteractionRequestKind.CONFIRMATION:
        return f"{subject} needs confirmation"
    if kind == InteractionRequestKind.PLAN_PROPOSAL:
        return f"{subject} proposed a plan"
    return f"{subject} needs your input"


def _task_signal_title(task: Task, kind: AttentionItemKind) -> str:
    actor = task.metadata.get("persona_name")
    subject = str(actor) if isinstance(actor, str) and actor else task.title
    if kind == AttentionItemKind.TASK_PAUSED:
        return f"{subject} paused"
    if kind == AttentionItemKind.TASK_RESUMED:
        return f"{subject} resumed"
    return subject


def _resolved_status_for_action(action: str) -> InteractionRequestStatus:
    mapping = {
        "approve": InteractionRequestStatus.APPROVED,
        "deny": InteractionRequestStatus.DENIED,
        "answer": InteractionRequestStatus.ANSWERED,
        "confirm": InteractionRequestStatus.RESOLVED,
        "cancel": InteractionRequestStatus.CANCELLED,
    }
    return mapping[action]


def _build_follow_up_instruction(
    *,
    request: InteractionRequest,
    action: str,
    answer_text: str | None,
) -> str:
    if request.kind == InteractionRequestKind.PERMISSION:
        if action == "approve":
            return "The user approved the pending permission request. Continue from where you left off."
        return (
            "The user denied the pending permission request. Do not perform that action. "
            "Continue with an alternative if possible, otherwise ask for next steps."
        )
    if request.kind == InteractionRequestKind.CONFIRMATION:
        if action == "confirm":
            return "The user confirmed the pending action. Continue."
        return (
            "The user cancelled the pending action. Do not perform it. "
            "Continue only if there is another safe path."
        )
    if request.kind == InteractionRequestKind.PLAN_PROPOSAL:
        if action == "approve":
            return (
                f"The user approved this plan: {(answer_text or '').strip()}. "
                "Proceed with that plan."
            )
        return "The user asked you to keep planning. Refine the plan and ask again before acting."
    if answer_text is None:
        raise ValueError("answer_text is required for answer actions.")
    return f"The user answered the pending question: {answer_text.strip()}. Continue from where you left off."


def _proposal_details_from_blocked_event(blocked_event: object) -> dict[str, object] | None:
    if not isinstance(blocked_event, dict):
        return None
    proposal = blocked_event.get("proposal")
    if isinstance(proposal, dict):
        return proposal
    native_response = blocked_event.get("native_response")
    if not isinstance(native_response, dict):
        return None
    params = native_response.get("params")
    if not isinstance(params, dict):
        return None
    return _proposal_details_from_native_params(params)


def _proposal_details_from_native_params(params: dict[str, object]) -> dict[str, object] | None:
    questions = params.get("questions")
    if not isinstance(questions, list):
        return None
    normalized_questions: list[dict[str, object]] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_id = question.get("id")
        header = question.get("header")
        question_text = question.get("question") or question.get("prompt") or header
        options = question.get("options")
        normalized_options: list[dict[str, object]] = []
        if isinstance(options, list):
            for index, option in enumerate(options):
                if not isinstance(option, dict):
                    continue
                label = option.get("label")
                description = option.get("description")
                if not isinstance(label, str) or not label.strip():
                    continue
                option_id = option.get("id")
                normalized_options.append(
                    {
                        "id": str(option_id) if isinstance(option_id, str) and option_id else label.strip(),
                        "label": label.strip(),
                        "description": description.strip() if isinstance(description, str) else "",
                        "letter": chr(65 + index),
                    }
                )
        normalized_questions.append(
            {
                "question_id": str(question_id).strip()
                if isinstance(question_id, str) and question_id.strip()
                else f"question_{len(normalized_questions) + 1}",
                "header": header.strip()
                if isinstance(header, str) and header.strip()
                else (
                    question_text.strip()
                    if isinstance(question_text, str) and question_text.strip()
                    else f"Question {len(normalized_questions) + 1}"
                ),
                "summary": question_text.strip()
                if isinstance(question_text, str) and question_text.strip()
                else "Review the proposed plan.",
                "options": normalized_options,
            }
        )
    if not normalized_questions:
        return None
    first = normalized_questions[0]
    return {
        "questions": normalized_questions,
        "question_id": first["question_id"],
        "summary": first["summary"],
        "options": first["options"],
    }


def _plan_proposal_answer_text(
    *,
    request: InteractionRequest,
    action: str,
    answer_text: str | None,
    option_id: str | None,
    answers: dict[str, list[str]] | None = None,
) -> str:
    if answer_text and answer_text.strip():
        return answer_text.strip()
    if answers:
        summary = _proposal_answers_summary(request=request, answers=answers)
        if summary:
            return summary
    if action == "deny":
        return "Keep planning. Refine the proposal instead of acting yet."
    proposal = request.details.get("proposal")
    if isinstance(proposal, dict):
        options = proposal.get("options")
        if isinstance(options, list):
            for option in options:
                if not isinstance(option, dict):
                    continue
                candidate_id = option.get("id")
                if option_id and candidate_id != option_id:
                    continue
                label = option.get("label")
                if isinstance(label, str) and label.strip():
                    return label.strip()
    return "Approve and run the proposed plan."


def _normalize_proposal_answers(
    *,
    request: InteractionRequest,
    answers: dict[str, list[str]] | None,
) -> dict[str, list[str]] | None:
    proposal = request.details.get("proposal")
    if not isinstance(proposal, dict):
        return answers
    questions = proposal.get("questions")
    if not isinstance(questions, list) or len(questions) <= 1:
        return answers
    if answers is None:
        raise ValueError("answers are required for multi-question plan proposals.")
    normalized_answers: dict[str, list[str]] = {}
    missing: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_id = question.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            continue
        selected = answers.get(question_id)
        values = [value.strip() for value in selected or [] if isinstance(value, str) and value.strip()]
        if not values:
            missing.append(question_id)
            continue
        normalized_answers[question_id] = values
    if missing:
        raise ValueError(f"answers are required for proposal questions: {', '.join(missing)}.")
    return normalized_answers


def _proposal_answers_summary(
    *,
    request: InteractionRequest,
    answers: dict[str, list[str]],
) -> str:
    proposal = request.details.get("proposal")
    if not isinstance(proposal, dict):
        return ""
    questions = proposal.get("questions")
    if not isinstance(questions, list):
        return ""
    parts: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_id = question.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            continue
        label = question.get("header") or question.get("summary") or question_id
        values = answers.get(question_id) or []
        clean_values = [value.strip() for value in values if isinstance(value, str) and value.strip()]
        if clean_values:
            parts.append(f"{str(label).strip()}: {', '.join(clean_values)}")
    return "; ".join(parts)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
