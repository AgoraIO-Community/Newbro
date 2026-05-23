"""Communication Brain package scaffold."""

from .brain import CommunicationBrain, CommunicationTurnResult
from .history import InMemoryConversationHistory
from .interaction_classifier import (
    InteractionClassification,
    InteractionClassifier,
    InteractionClassifierState,
    OpenAIInteractionClassifier,
    ScriptedInteractionClassifier,
    UnavailableInteractionClassifier,
)

__all__ = [
    "CommunicationBrain",
    "CommunicationTurnResult",
    "InMemoryConversationHistory",
    "InteractionClassification",
    "InteractionClassifier",
    "InteractionClassifierState",
    "OpenAIInteractionClassifier",
    "ScriptedInteractionClassifier",
    "UnavailableInteractionClassifier",
]
