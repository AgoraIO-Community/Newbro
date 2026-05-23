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
from newbro.protocol import InteractionType, TaskMode
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


@pytest.mark.anyio
async def test_openai_classifier_prompt_allows_early_draft_worthy_task_context():
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
                                '{"interaction_type":"delegation","confidence":0.83,'
                                '"requires_user_decision":false,"importance":"medium",'
                                '"reason":"concrete_task_context"}'
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
        text="I'm traveling next month and preparing tickets, flights, and hotels.",
        state=InteractionClassifierState(has_draft=False, active_task_count=0),
    )

    system_prompt = client.last_request["messages"][0]["content"]
    assert classification.interaction_type == InteractionType.DELEGATION
    assert "likely work product is clear enough to draft" in system_prompt
    assert "Do not wait for explicit words like please, help" in system_prompt
    assert "lacks enough concrete task material" in system_prompt


@pytest.mark.anyio
async def test_openai_classifier_prompt_treats_short_final_acceptance_as_confirmation():
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
                                '{"interaction_type":"confirmation","confidence":0.91,'
                                '"requires_user_decision":false,"importance":"low",'
                                '"reason":"draft_send_acceptance"}'
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
        text="ok",
        state=InteractionClassifierState(has_draft=True, active_task_count=0),
    )

    system_prompt = client.last_request["messages"][0]["content"]
    state_payload = client.last_request["messages"][1]["content"]
    assert classification.interaction_type == InteractionType.CONFIRMATION
    assert "When state.has_draft is true" in system_prompt
    assert "Confirmation must be short and must not contain task fields" in system_prompt
    assert "Do not classify a final short acceptance as communication" in system_prompt
    assert '"has_draft": true' in state_payload


@pytest.mark.anyio
async def test_openai_classifier_prompt_treats_active_draft_destination_change_as_correction():
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
                                '{"interaction_type":"draft_correction","confidence":0.93,'
                                '"requires_user_decision":false,"importance":"medium",'
                                '"reason":"destination_changed"}'
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
        text="Actually change the destination to the UK.",
        state=InteractionClassifierState(has_draft=True, active_task_count=0),
    )

    system_prompt = client.last_request["messages"][0]["content"]
    assert classification.interaction_type == InteractionType.DRAFT_CORRECTION
    assert "changes destination" in system_prompt
    assert "classify it as draft_correction, not confirmation" in system_prompt
    assert "actually make it California" in system_prompt


@pytest.mark.anyio
async def test_openai_classifier_prompt_defaults_research_help_away_from_modify_allowed():
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
                                '{"interaction_type":"delegation","confidence":0.89,'
                                '"requires_user_decision":true,"importance":"medium",'
                                '"reason":"travel_planning_help","task_mode":"read_only_first"}'
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
        text="I need help finding flights and hotels at affordable prices.",
        state=InteractionClassifierState(has_draft=False, active_task_count=0),
    )

    system_prompt = client.last_request["messages"][0]["content"]
    assert classification.interaction_type == InteractionType.DELEGATION
    assert classification.task_mode == TaskMode.READ_ONLY_FIRST
    assert "travel help" in system_prompt
    assert "Use modify_allowed only when the user explicitly asks" in system_prompt


@pytest.mark.anyio
async def test_openai_classifier_tolerates_empty_optional_enum_fields():
    class _FakeClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"interaction_type":"delegation","confidence":"0.88",'
                                '"requires_user_decision":true,"importance":"high",'
                                '"reason":"model_output","control_action":"none",'
                                '"task_mode":"none"}'
                            )
                        }
                    }
                ]
            }

    classifier = OpenAIInteractionClassifier(
        OpenAIProvider(Settings(openai_api_key="test-key"), client=_FakeClient()),
        model="classifier-model",
    )

    classification = await classifier.classify(
        text="Please help me plan the trip.",
        state=InteractionClassifierState(has_draft=False, active_task_count=0),
    )

    assert classification.interaction_type == InteractionType.DELEGATION
    assert classification.confidence == 0.88
    assert classification.control_action is None
    assert classification.task_mode is None
