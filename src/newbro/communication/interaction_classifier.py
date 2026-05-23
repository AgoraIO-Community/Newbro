from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from newbro.infrastructure.llm import OpenAIProvider
from newbro.protocol import InteractionType, TaskMode


class InteractionClassification(BaseModel):
    interaction_type: InteractionType = InteractionType.UNCERTAIN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_user_decision: bool = False
    importance: str = "low"
    reason: str = ""
    control_action: str | None = None
    task_mode: TaskMode | None = None


@dataclass(frozen=True, slots=True)
class InteractionClassifierState:
    has_draft: bool
    active_task_count: int
    target_persona_id: str | None = None
    voice_target_persona_id: str | None = None
    language: str | None = None


class InteractionClassifier(Protocol):
    async def classify(
        self,
        *,
        text: str,
        state: InteractionClassifierState,
    ) -> InteractionClassification:
        ...


class UnavailableInteractionClassifier:
    async def classify(
        self,
        *,
        text: str,
        state: InteractionClassifierState,
    ) -> InteractionClassification:
        return InteractionClassification(
            interaction_type=InteractionType.UNCERTAIN,
            confidence=0.0,
            requires_user_decision=True,
            importance="low",
            reason="interaction_classifier_unavailable",
        )


class ScriptedInteractionClassifier:
    def __init__(
        self,
        scripted: dict[str, InteractionClassification | InteractionType],
        *,
        default: InteractionClassification | InteractionType | None = None,
    ) -> None:
        self._scripted = scripted
        self._default = default or InteractionClassification(
            interaction_type=InteractionType.UNCERTAIN,
            confidence=0.0,
            requires_user_decision=True,
            reason="scripted_classifier_default",
        )

    async def classify(
        self,
        *,
        text: str,
        state: InteractionClassifierState,
    ) -> InteractionClassification:
        return _coerce_classification(self._scripted.get(text, self._default))


class OpenAIInteractionClassifier:
    def __init__(self, provider: OpenAIProvider, *, model: str) -> None:
        self._provider = provider
        self._model = model

    async def classify(
        self,
        *,
        text: str,
        state: InteractionClassifierState,
    ) -> InteractionClassification:
        completion = await self._provider.create_completion(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You classify one user utterance for Newbro's communication runtime. "
                        "Return only JSON with keys: interaction_type, confidence, "
                        "requires_user_decision, importance, reason, control_action, task_mode. "
                        "Valid interaction_type values: communication, delegation, "
                        "draft_correction, task_control, status_query, confirmation, "
                        "clarification_response, uncertain. Valid importance values: "
                        "low, medium, high, urgent. Valid task_mode values when known: "
                        "read_only_first, proposal_only, modify_allowed, submit_allowed. "
                        "Use session state. Do not decide dispatch permission."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "utterance": text,
                            "state": {
                                "has_draft": state.has_draft,
                                "active_task_count": state.active_task_count,
                                "target_persona_id": state.target_persona_id,
                                "voice_target_persona_id": state.voice_target_persona_id,
                                "language": state.language,
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        return _parse_completion(completion)


def _coerce_classification(
    value: InteractionClassification | InteractionType,
) -> InteractionClassification:
    if isinstance(value, InteractionClassification):
        return value
    return InteractionClassification(
        interaction_type=value,
        confidence=1.0,
        reason="scripted_interaction_type",
    )


def _parse_completion(completion: Any) -> InteractionClassification:
    choices = _get_value(completion, "choices") or []
    if not choices:
        return _uncertain("classifier_empty_choices")
    message = _get_value(choices[0], "message")
    content = _get_value(message, "content")
    if not isinstance(content, str) or not content.strip():
        return _uncertain("classifier_empty_content")
    try:
        raw = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError:
        return _uncertain("classifier_invalid_json")
    if not isinstance(raw, dict):
        return _uncertain("classifier_non_object_json")
    try:
        return InteractionClassification.model_validate(raw)
    except ValidationError:
        return _uncertain("classifier_invalid_schema")


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _uncertain(reason: str) -> InteractionClassification:
    return InteractionClassification(
        interaction_type=InteractionType.UNCERTAIN,
        confidence=0.0,
        requires_user_decision=True,
        importance="low",
        reason=reason,
    )


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
