from __future__ import annotations

from newbro.communication.models import OpenAICommunicationModel, ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.communication.interaction_classifier import OpenAIInteractionClassifier
from newbro.infrastructure.llm import OpenAIProvider

from .config import Settings, load_settings
from .container import RuntimeContainer
from .drafts import OpenAIDraftRewriter


def build_runtime_container(
    *,
    settings: Settings | None = None,
    provider: OpenAIProvider | None = None,
) -> RuntimeContainer:
    settings = settings or load_settings()
    if settings.communication_backend != "scripted" and settings.openai_api_key:
        llm_provider = provider or OpenAIProvider(settings)
        model = OpenAICommunicationModel(llm_provider)
        return RuntimeContainer(
            communication_model=model,
            settings=settings,
            draft_rewriter=OpenAIDraftRewriter(llm_provider, model=settings.openai_model),
            interaction_classifier=OpenAIInteractionClassifier(
                llm_provider,
                model=settings.openai_model,
            ),
        )

    default_model = ScriptedCommunicationModel(
        {
            "__default__": ScriptedPlan(
                conversational_act="request_clarification",
                reply_override="I need a more specific instruction for that.",
            )
        }
    )
    return RuntimeContainer(communication_model=default_model, settings=settings)
