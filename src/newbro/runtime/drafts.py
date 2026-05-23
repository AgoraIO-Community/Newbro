from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from newbro.protocol import (
    DispatchGateOutcome,
    DispatchGateResult,
    DispatchPlan,
    AsrTurn,
    Draft,
    DraftSession,
    DraftSessionStatus,
    DraftSnapshot,
    RuntimeSessionState,
    TaskMode,
    TaskSpec,
)

DEFAULT_BRO_ID = "codex"
SAFE_TASK_MODES = {TaskMode.READ_ONLY_FIRST, TaskMode.PROPOSAL_ONLY}
ROUTING_TABLE: dict[str, list[str]] = {
    "repo_investigation": ["hermes", "codex", "mock"],
    "code_modification": ["codex", "hermes"],
    "web_research": ["browser_agent", "hermes"],
    "status_query": ["communication_brain"],
    "draft_correction": ["communication_brain"],
    "task_control": ["task_manager"],
}
DRAFT_CLEANER_SYSTEM_PROMPT = """You are the Draft Cleaner for newbro.

The user is speaking across multiple ASR turns to prepare a task for a coding bro.
Your job is to produce a clean, faithful draft of what the user wants to send.

Do not turn the user's words into a full product spec.
Do not invent details the user did not express.
Only preserve what the user actually expressed.
You may lightly clean ASR errors, remove filler words, and merge corrections.
If the latest turn contradicts earlier turns, prefer the latest turn.
If the user explicitly rejects a previous idea, remove that idea from the draft.
Keep the draft concise and sendable."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class DraftRewriteInput:
    previous_draft: Draft | None
    asr_turns: list[AsrTurn]
    new_turn: AsrTurn
    assigned_bro_id: str


@dataclass(frozen=True, slots=True)
class TaskLintResult:
    valid: bool
    problems: tuple[str, ...] = ()
    clarifying_question: str | None = None


TextDeltaCallback = Callable[[str], Awaitable[None] | None]


class DraftRewriter:
    async def rewrite(
        self,
        payload: DraftRewriteInput,
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> Draft:
        raise NotImplementedError


class DraftRewriteError(RuntimeError):
    pass


class DraftRewriteUnavailable(DraftRewriteError):
    pass


class DraftRewriteInvalidOutput(DraftRewriteError):
    pass


class DraftRewriteUpstreamError(DraftRewriteError):
    pass


class UnavailableDraftRewriter(DraftRewriter):
    async def rewrite(
        self,
        payload: DraftRewriteInput,
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> Draft:
        raise DraftRewriteUnavailable("Draft generation requires a configured LLM provider.")


class OpenAIDraftRewriter(DraftRewriter):
    def __init__(self, provider: Any, *, model: str) -> None:
        self._provider = provider
        self._model = model

    async def rewrite(
        self,
        payload: DraftRewriteInput,
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> Draft:
        try:
            request = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": DRAFT_CLEANER_SYSTEM_PROMPT},
                    {"role": "user", "content": _draft_rewrite_user_message(payload)},
                ],
            }
            if on_text_delta is None:
                response = await self._provider.create_completion(**request)
                content = _completion_text(response)
            else:
                stream = await self._provider.create_completion(**request, stream=True)
                content = await _completion_stream_text(stream, on_text_delta)
        except DraftRewriteError:
            raise
        except Exception as exc:
            raise DraftRewriteUpstreamError("Draft cleaner request failed.") from exc
        return _draft_from_plain_text(
            content,
            previous=payload.previous_draft,
            locale=_draft_locale(_turn_text(payload.new_turn)),
        )


class DeterministicDraftRewriter(DraftRewriter):
    async def rewrite(
        self,
        payload: DraftRewriteInput,
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> Draft:
        text = _turn_text(payload.new_turn)
        previous = payload.previous_draft
        locale = _draft_locale(text)
        draft_text = _clean_goal(text, locale)
        if not draft_text.strip():
            draft_text = "执行前先澄清要完成的任务。" if locale == "zh" else "Clarify the requested task before execution."
        return Draft(
            text=draft_text,
            last_update_summary=_last_update_summary(previous, draft_text, locale),
            task_spec=formulate_task_spec(draft_text, assigned_bro_id=payload.assigned_bro_id),
        )


@dataclass(slots=True)
class DraftSessionManager:
    rewriter: DraftRewriter = field(default_factory=UnavailableDraftRewriter)
    _active_session: DraftSession | None = None

    @property
    def active_session(self) -> DraftSession | None:
        return self._active_session

    async def append_asr_turn(
        self,
        *,
        raw_text: str,
        normalized_text: str | None = None,
        confidence: float | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        assigned_bro_id: str | None = None,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> DraftSession:
        text = raw_text.strip()
        if not text:
            raise ValueError("ASR turn text must not be empty.")
        now = utc_now_iso()
        session = self._active_session
        if session is None or session.status in {DraftSessionStatus.SENT, DraftSessionStatus.CLEARED}:
            session = DraftSession(
                id=f"draft-{uuid4().hex[:8]}",
                assigned_bro_id=assigned_bro_id or DEFAULT_BRO_ID,
                status=DraftSessionStatus.EMPTY,
                created_at=now,
                updated_at=now,
            )
        elif assigned_bro_id:
            session.assigned_bro_id = assigned_bro_id

        turn = AsrTurn(
            id=f"asr-{uuid4().hex[:8]}",
            raw_text=text,
            normalized_text=normalized_text.strip() if normalized_text and normalized_text.strip() else None,
            confidence=confidence,
            started_at=started_at or now,
            ended_at=ended_at or now,
        )
        next_turns = [*session.asr_turns, turn]
        rewrite_input = DraftRewriteInput(
            previous_draft=session.current_draft,
            asr_turns=next_turns,
            new_turn=turn,
            assigned_bro_id=session.assigned_bro_id,
        )
        if on_text_delta is None:
            draft = await self.rewriter.rewrite(rewrite_input)
        else:
            draft = await self.rewriter.rewrite(rewrite_input, on_text_delta=on_text_delta)
        session.asr_turns.append(turn)
        return self._apply_draft_revision(
            session,
            draft=draft,
            source_asr_turn_ids=[item.id for item in session.asr_turns],
            source_boundary="asr_turn",
            transcript_timestamp_ms=None,
        )

    async def update_live_draft(
        self,
        *,
        raw_text: str,
        normalized_text: str | None = None,
        confidence: float | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        assigned_bro_id: str | None = None,
        source_boundary: str = "stt.partial",
        transcript_timestamp_ms: int | None = None,
        classification: dict[str, object] | None = None,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> DraftSession:
        text = raw_text.strip()
        if not text:
            raise ValueError("Live transcript text must not be empty.")
        now = utc_now_iso()
        session = self._active_session
        if session is None or session.status in {DraftSessionStatus.SENT, DraftSessionStatus.CLEARED}:
            session = DraftSession(
                id=f"draft-{uuid4().hex[:8]}",
                assigned_bro_id=assigned_bro_id or DEFAULT_BRO_ID,
                status=DraftSessionStatus.EMPTY,
                created_at=now,
                updated_at=now,
            )
        elif assigned_bro_id:
            session.assigned_bro_id = assigned_bro_id

        if (
            transcript_timestamp_ms is not None
            and session.live_transcript_timestamp_ms is not None
            and transcript_timestamp_ms < session.live_transcript_timestamp_ms
        ):
            return session

        turn = AsrTurn(
            id=f"live-{uuid4().hex[:8]}",
            raw_text=text,
            normalized_text=normalized_text.strip() if normalized_text and normalized_text.strip() else None,
            confidence=confidence,
            started_at=started_at or now,
            ended_at=ended_at or now,
        )
        rewrite_input = DraftRewriteInput(
            previous_draft=session.current_draft,
            asr_turns=[*session.asr_turns, turn],
            new_turn=turn,
            assigned_bro_id=session.assigned_bro_id,
        )
        if on_text_delta is None:
            draft = await self.rewriter.rewrite(rewrite_input)
        else:
            draft = await self.rewriter.rewrite(rewrite_input, on_text_delta=on_text_delta)
        session.live_classification = classification
        return self._apply_draft_revision(
            session,
            draft=draft,
            source_asr_turn_ids=[item.id for item in session.asr_turns],
            source_boundary=source_boundary,
            transcript_timestamp_ms=transcript_timestamp_ms,
        )

    def mark_live_checkpoint(
        self,
        *,
        source_boundary: str,
        transcript_timestamp_ms: int | None = None,
        classification: dict[str, object] | None = None,
    ) -> DraftSession | None:
        session = self._active_session
        if session is None or session.current_draft is None or session.current_revision_id is None:
            return session
        session.live_classification = classification if classification is not None else session.live_classification
        session.live_source_boundary = source_boundary
        if transcript_timestamp_ms is not None:
            session.live_transcript_timestamp_ms = transcript_timestamp_ms
        session.updated_at = utc_now_iso()
        session.snapshots.append(
            DraftSnapshot(
                id=f"draft-snap-{uuid4().hex[:8]}",
                draft=session.current_draft.model_copy(deep=True),
                source_asr_turn_ids=[item.id for item in session.asr_turns],
                created_at=session.updated_at,
                draft_revision_id=session.current_revision_id,
                draft_revision_number=session.current_revision_number,
                source_boundary=source_boundary,
                transcript_timestamp_ms=transcript_timestamp_ms,
            )
        )
        self._active_session = session
        return session

    def _apply_draft_revision(
        self,
        session: DraftSession,
        *,
        draft: Draft,
        source_asr_turn_ids: list[str],
        source_boundary: str,
        transcript_timestamp_ms: int | None,
    ) -> DraftSession:
        session.status = DraftSessionStatus.DRAFTING
        revision_number = session.current_revision_number + 1
        revision_id = f"draft-rev-{uuid4().hex[:8]}"
        created_at = utc_now_iso()
        draft.revision_id = revision_id
        draft.revision_number = revision_number
        draft.updated_at = created_at
        snapshot = DraftSnapshot(
            id=f"draft-snap-{uuid4().hex[:8]}",
            draft=draft,
            source_asr_turn_ids=source_asr_turn_ids,
            created_at=created_at,
            draft_revision_id=revision_id,
            draft_revision_number=revision_number,
            source_boundary=source_boundary,
            transcript_timestamp_ms=transcript_timestamp_ms,
        )
        session.current_draft = draft
        session.current_revision_id = revision_id
        session.current_revision_number = revision_number
        session.current_dispatch_plan = build_dispatch_plan(
            session_id=session.id,
            runtime_session_id="",
            draft_session=session,
            draft=draft,
        )
        session.runtime_state = RuntimeSessionState.WAITING_FOR_CONFIRMATION
        session.snapshots.append(snapshot)
        session.status = DraftSessionStatus.READY
        session.live_source_boundary = source_boundary
        if transcript_timestamp_ms is not None:
            session.live_transcript_timestamp_ms = transcript_timestamp_ms
        session.updated_at = snapshot.created_at
        self._active_session = session
        return session

    def clear(self) -> DraftSession | None:
        session = self._active_session
        if session is None:
            return None
        session.status = DraftSessionStatus.CLEARED
        session.runtime_state = RuntimeSessionState.IDLE
        session.updated_at = utc_now_iso()
        self._active_session = None
        return session

    def mark_sent(
        self,
        draft_session_id: str | None = None,
        *,
        draft_revision_id: str | None = None,
    ) -> DraftSession:
        session = self._active_session
        if session is None or session.current_draft is None or not session.snapshots:
            raise ValueError("No draft is ready to send.")
        if draft_session_id is not None and session.id != draft_session_id:
            raise ValueError("Draft session does not match the active draft.")
        if draft_revision_id is not None and session.current_revision_id != draft_revision_id:
            raise ValueError("Draft revision does not match the active draft.")
        session.status = DraftSessionStatus.SENT
        session.runtime_state = RuntimeSessionState.TASK_RUNNING
        session.updated_at = utc_now_iso()
        self._active_session = None
        return session


def formulate_task_spec(text: str, *, assigned_bro_id: str = DEFAULT_BRO_ID) -> TaskSpec:
    cleaned = " ".join(text.strip().split())
    language = _language_tag(cleaned)
    target_agent = assigned_bro_id or DEFAULT_BRO_ID
    mode = TaskMode.READ_ONLY_FIRST
    title = _title(cleaned, language)
    return TaskSpec(
        title=title,
        goal=cleaned,
        target_agent=target_agent,
        mode=mode,
        expected_output="Concise status or result summary",
        constraints=["Inspect first; ask before making changes"],
        success_criteria=_success_criteria(cleaned, language),
        stop_conditions=[
            "Need credentials",
            "Need permission to modify code",
            "Need unavailable repository or prototype context",
        ],
        input_language=language,
        output_language=language,
        raw_transcript=cleaned,
        code_switched=_is_code_switched(cleaned),
    )


def build_dispatch_plan(
    *,
    session_id: str | None = None,
    runtime_session_id: str,
    draft_session: DraftSession,
    draft: Draft,
    user_confirmed: bool = False,
) -> DispatchPlan:
    task_spec = draft.task_spec or formulate_task_spec(
        draft.text,
        assigned_bro_id=draft_session.assigned_bro_id,
    )
    missing_context = list(dict.fromkeys([*draft.missing_context, *_missing_context(task_spec)]))
    return DispatchPlan(
        plan_id=f"plan-{uuid4().hex[:8]}",
        session_id=runtime_session_id or session_id or "",
        draft_session_id=draft_session.id,
        draft_revision_id=draft_session.current_revision_id,
        draft_revision_number=draft_session.current_revision_number,
        intent=_intent(task_spec),
        target_agent=task_spec.target_agent,
        task_title=task_spec.title,
        task_goal=task_spec.goal,
        required_context=["target"] if missing_context else [],
        missing_context=missing_context,
        mode=task_spec.mode,
        risk_level=_risk_level(task_spec),
        confidence=0.91 if task_spec.goal else 0.0,
        requires_user_confirmation=True,
        user_confirmed=user_confirmed,
        output_language=task_spec.output_language,
        task_spec=task_spec,
    )


def dispatch_gate(plan: DispatchPlan) -> DispatchGateResult:
    lint = lint_task_spec(plan.task_spec)
    if not lint.valid:
        return DispatchGateResult(
            outcome=DispatchGateOutcome.ASK_CLARIFICATION,
            reason="task_lint_failed",
            question=lint.clarifying_question,
            plan_id=plan.plan_id,
        )
    if plan.confidence < 0.85:
        return DispatchGateResult(
            outcome=DispatchGateOutcome.ASK_CLARIFICATION,
            reason="low_confidence",
            question=_question(plan.output_language, "What should I send?"),
            plan_id=plan.plan_id,
        )
    if plan.missing_context:
        return DispatchGateResult(
            outcome=DispatchGateOutcome.ASK_CLARIFICATION,
            reason="missing_context",
            question=_question(plan.output_language, "Which repo or prototype should I inspect?"),
            plan_id=plan.plan_id,
        )
    if not plan.target_agent or plan.target_agent in {"unknown", "none"}:
        return DispatchGateResult(
            outcome=DispatchGateOutcome.REJECT,
            reason="agent_mismatch",
            question=_question(plan.output_language, "That worker is not available."),
            plan_id=plan.plan_id,
        )
    if not agent_allowed_for_intent(plan.intent, plan.target_agent):
        return DispatchGateResult(
            outcome=DispatchGateOutcome.REJECT,
            reason="agent_mismatch",
            question=_question(plan.output_language, "That worker is not available."),
            plan_id=plan.plan_id,
        )
    if plan.mode not in SAFE_TASK_MODES and not plan.user_confirmed:
        return DispatchGateResult(
            outcome=DispatchGateOutcome.ASK_CONFIRMATION,
            reason="unsafe_mode_needs_confirmation",
            question=_question(plan.output_language, "This may modify code. Send?"),
            plan_id=plan.plan_id,
        )
    if plan.risk_level in {"medium", "high"} and not plan.user_confirmed:
        return DispatchGateResult(
            outcome=DispatchGateOutcome.ASK_CONFIRMATION,
            reason="risk_needs_confirmation",
            question=_question(plan.output_language, "This needs approval. Send?"),
            plan_id=plan.plan_id,
        )
    if not plan.user_confirmed:
        return DispatchGateResult(
            outcome=DispatchGateOutcome.ASK_CONFIRMATION,
            reason="needs_confirmation",
            question=_question(plan.output_language, f"Drafted for {plan.target_agent}. Send?"),
            plan_id=plan.plan_id,
        )
    return DispatchGateResult(outcome=DispatchGateOutcome.DISPATCH, reason="ok", plan_id=plan.plan_id)


def lint_task_spec(task_spec: TaskSpec) -> TaskLintResult:
    problems: list[str] = []
    if not task_spec.goal.strip():
        problems.append("clear_goal")
    if not task_spec.target_agent.strip():
        problems.append("clear_target")
    if not task_spec.expected_output.strip():
        problems.append("expected_output")
    if task_spec.mode not in TaskMode:
        problems.append("mode")
    if _missing_context(task_spec):
        problems.append("missing_context")
    if problems:
        return TaskLintResult(
            valid=False,
            problems=tuple(problems),
            clarifying_question=_question(task_spec.output_language, "Which repo or prototype should I inspect?")
            if "missing_context" in problems
            else _question(task_spec.output_language, "What should I send?"),
        )
    return TaskLintResult(valid=True)


def agent_allowed_for_intent(intent: str, target_agent: str) -> bool:
    if target_agent.startswith("persona-"):
        return True
    allowed = ROUTING_TABLE.get(intent)
    if allowed is None:
        return True
    return target_agent in allowed


def _turn_text(turn: AsrTurn) -> str:
    return (turn.normalized_text or turn.raw_text).strip()


def _draft_rewrite_user_message(payload: DraftRewriteInput) -> str:
    previous = payload.previous_draft.text if payload.previous_draft else "(none)"
    turns = "\n".join(
        f"{index}. [{turn.id}] {_turn_text(turn)}"
        for index, turn in enumerate(payload.asr_turns, start=1)
    )
    return (
        "Return only the clean sendable task text.\n"
        "Do not return JSON, code fences, labels, commentary, or revision history.\n"
        "Write the exact text the user should send to the assigned coding bro.\n\n"
        f"Assigned bro id:\n{payload.assigned_bro_id}\n\n"
        f"Previous draft:\n{previous}\n\n"
        f"Ordered ASR turns:\n{turns}\n\n"
        f"Latest turn:\n{_turn_text(payload.new_turn)}"
    )


def _completion_text(completion: Any) -> str:
    choices = _get_value(completion, "choices") or []
    if not choices:
        raise DraftRewriteInvalidOutput("Draft cleaner returned no choices.")
    message = _get_value(choices[0], "message")
    content = _get_value(message, "content")
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    raise DraftRewriteInvalidOutput("Draft cleaner returned empty content.")


async def _completion_stream_text(stream: Any, on_text_delta: TextDeltaCallback) -> str:
    chunks: list[str] = []
    uses_context_manager = hasattr(stream, "__aenter__") and hasattr(stream, "__aexit__")
    try:
        if uses_context_manager:
            async with stream as entered:
                async for chunk in entered:
                    await _append_stream_chunk(chunk, chunks, on_text_delta)
        else:
            async for chunk in stream:
                await _append_stream_chunk(chunk, chunks, on_text_delta)
    finally:
        close = getattr(stream, "aclose", None)
        if not uses_context_manager and callable(close):
            maybe_awaitable = close()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

    text = "".join(chunks).strip()
    if text:
        return text
    raise DraftRewriteInvalidOutput("Draft cleaner returned empty content.")


async def _append_stream_chunk(
    chunk: Any,
    chunks: list[str],
    on_text_delta: TextDeltaCallback,
) -> None:
    delta = _completion_chunk_text(chunk)
    if not delta:
        return
    chunks.append(delta)
    maybe_awaitable = on_text_delta(delta)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


def _completion_chunk_text(chunk: Any) -> str:
    choices = _get_value(chunk, "choices") or []
    if not choices:
        return ""
    delta = _get_value(choices[0], "delta")
    content = _get_value(delta, "content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            text = _get_value(part, "text")
            if isinstance(text, str):
                text_parts.append(text)
                continue
            text_value = _get_value(text, "value")
            if isinstance(text_value, str):
                text_parts.append(text_value)
        return "".join(text_parts)
    return str(content)


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _draft_from_plain_text(text: str, *, previous: Draft | None, locale: str) -> Draft:
    draft_text = text.strip()
    if not draft_text:
        raise DraftRewriteInvalidOutput("Draft cleaner returned empty content.")
    return Draft(
        text=draft_text,
        last_update_summary=_last_update_summary(previous, draft_text, locale),
        task_spec=formulate_task_spec(draft_text),
    )


def _language_tag(text: str) -> str:
    return "zh-CN" if any("\u4e00" <= character <= "\u9fff" for character in text) else "en-US"


def _is_code_switched(text: str) -> bool:
    has_cjk = any("\u4e00" <= character <= "\u9fff" for character in text)
    has_ascii_word = any(character.isascii() and character.isalpha() for character in text)
    return has_cjk and has_ascii_word


def _success_criteria(text: str, language: str) -> list[str]:
    criteria = ["Produce a concise result that matches the requested output"]
    if language == "zh-CN":
        criteria.append("Respond to the user in Chinese")
    return criteria


def _title(text: str, language: str) -> str:
    compact = text.strip().rstrip(".。")
    return _title_from_goal(compact)


def _missing_context(task_spec: TaskSpec) -> list[str]:
    if len(task_spec.goal.strip()) < 8:
        return ["target"]
    return []


def _intent(task_spec: TaskSpec) -> str:
    return "repo_investigation"


def _risk_level(task_spec: TaskSpec) -> str:
    if task_spec.mode in {TaskMode.MODIFY_ALLOWED, TaskMode.SUBMIT_ALLOWED}:
        return "medium"
    return "low"


def _question(language: str, english: str) -> str:
    if language != "zh-CN":
        return english
    mapping = {
        "What should I send?": "要发送什么任务？",
        "Which repo or prototype should I inspect?": "要检查哪个 repo 或 prototype？",
        "That worker is not available.": "这个 worker 现在不可用。",
        "This may modify code. Send?": "这个任务可能会变更文件。发送吗？",
        "This needs approval. Send?": "这个任务需要确认。发送吗？",
    }
    if english.startswith("Drafted for "):
        return english.replace("Drafted for", "已草拟给").replace(". Send?", "。发送吗？")
    return mapping.get(english, english)


def _draft_locale(text: str) -> str:
    return "zh" if any("\u4e00" <= character <= "\u9fff" for character in text) else "en"


def _clean_goal(text: str, locale: str = "en") -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    if not cleaned.endswith(('.', '。', '!', '！', '?', '？')):
        cleaned += "。" if locale == "zh" else "."
    if locale == "zh":
        return cleaned
    return cleaned[0].upper() + cleaned[1:]


def _title_from_goal(goal: str) -> str:
    title = goal.strip().rstrip(".。")
    if len(title) > 72:
        title = title[:69].rstrip() + "..."
    return title or "Draft task"


def _last_update_summary(
    previous: Draft | None,
    text: str,
    locale: str = "en",
) -> str:
    if previous is None:
        return ""
    if previous.text != text:
        if locale == "zh":
            return "已根据最新语音重写草稿。"
        return "Rewrote the draft based on the latest voice turn."
    if locale == "zh":
        return "已根据最新语音刷新草稿。"
    return "Refreshed the draft from the latest voice turn."
