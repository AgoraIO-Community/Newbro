from __future__ import annotations

from types import SimpleNamespace

import pytest

from newbro.communication.interaction_classifier import (
    InteractionClassification,
    InteractionClassifierState,
    OpenAIInteractionClassifier,
    ScriptedInteractionClassifier,
    UnavailableInteractionClassifier,
)
from newbro.protocol import InteractionType
from newbro.runtime.config import Settings
from newbro.infrastructure.llm import OpenAIProvider


def test_interaction_classification_serializes_required_policy_fields():
    classification = InteractionClassification(
        interaction_type=InteractionType.STATUS_QUERY,
        confidence=0.87,
        requires_user_decision=True,
        importance="medium",
        reason="needs_state_summary",
    )

    payload = classification.model_dump(mode="json")

    assert payload["interaction_type"] == "status_query"
    assert payload["confidence"] == 0.87
    assert payload["requires_user_decision"] is True
    assert payload["importance"] == "medium"
    assert payload["reason"] == "needs_state_summary"


@pytest.mark.anyio
async def test_unavailable_classifier_fails_closed_to_uncertain():
    classification = await UnavailableInteractionClassifier().classify(
        text="same transcript",
        state=InteractionClassifierState(has_draft=False, active_task_count=0),
    )

    assert classification.interaction_type == InteractionType.UNCERTAIN
    assert classification.requires_user_decision is True
    assert classification.confidence == 0.0


@pytest.mark.anyio
async def test_scripted_classifier_is_test_only_structured_boundary():
    classifier = ScriptedInteractionClassifier(
        {
            "same transcript": InteractionClassification(
                interaction_type=InteractionType.DELEGATION,
                confidence=1.0,
                reason="test",
            )
        }
    )

    classification = await classifier.classify(
        text="same transcript",
        state=InteractionClassifierState(has_draft=False, active_task_count=0),
    )

    assert classification.interaction_type == InteractionType.DELEGATION


@pytest.mark.anyio
async def test_openai_classifier_uses_provider_json_output():
    class _FakeClient:
        def __init__(self) -> None:
            self.last_request = None
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **kwargs):
            self.last_request = kwargs
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"interaction_type":"task_control","confidence":0.91,'
                                '"requires_user_decision":true,"importance":"high",'
                                '"reason":"model_output"}'
                            )
                        }
                    }
                ]
            }

    client = _FakeClient()
    classifier = OpenAIInteractionClassifier(
        OpenAIProvider(Settings(openai_api_key="test-key"), client=client),
        model="classifier-model",
    )

    classification = await classifier.classify(
        text="same transcript",
        state=InteractionClassifierState(has_draft=True, active_task_count=1),
    )

    assert classification.interaction_type == InteractionType.TASK_CONTROL
    assert classification.requires_user_decision is True
    assert client.last_request["model"] == "classifier-model"
