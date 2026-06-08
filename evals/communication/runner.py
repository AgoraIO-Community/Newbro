from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

from newbro.blackboard import InMemoryBlackboard
from newbro.communication import CommunicationBrain, InMemoryConversationHistory
from newbro.communication.models import OpenAICommunicationModel
from newbro.communication.tools import build_default_tool_registry
from newbro.executors.core import ExecutorCapabilities
from newbro.infrastructure.llm import OpenAIProvider
from newbro.runtime import Settings

from .scenarios import COMMUNICATION_EVAL_SCENARIOS, CommunicationEvalScenario


MECHANICAL_REPLY_MARKERS = [
    "successfully",
    "task created",
    "task updated",
    "command applied",
]


@dataclass(slots=True)
class CommunicationEvalResult:
    scenario: str
    reply_text: str
    tool_names: list[str]
    passed_expected_tools: bool
    passed_forbidden_tools: bool
    mechanical_reply: bool
    passed_mock_only_reply_rules: bool

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


async def run_communication_eval(settings: Settings) -> list[CommunicationEvalResult]:
    model = OpenAICommunicationModel(OpenAIProvider(settings))
    results: list[CommunicationEvalResult] = []
    for scenario in COMMUNICATION_EVAL_SCENARIOS:
        results.append(await _run_scenario(model, settings, scenario))
    return results


def format_results(results: list[CommunicationEvalResult]) -> str:
    return json.dumps([result.model_dump() for result in results], ensure_ascii=False, indent=2)


async def _run_scenario(
    model: OpenAICommunicationModel,
    settings: Settings,
    scenario: CommunicationEvalScenario,
) -> CommunicationEvalResult:
    store = InMemoryBlackboard()
    history = InMemoryConversationHistory()
    for task in scenario.initial_tasks:
        await store.put_task(task)
    for summary in scenario.initial_summaries:
        await store.put_summary(summary)

    brain = CommunicationBrain(
        store,
        model,
        history=history,
        tool_registry=build_default_tool_registry(
            store,
            executor_types=["mock", "codex"] if settings.codex_executor_enabled else ["mock"],
            default_executor_type="codex" if settings.codex_executor_enabled else "mock",
        ),
        executor_capabilities=(
            [
                ExecutorCapabilities(executor_type="mock", supports_follow_up=True),
                ExecutorCapabilities(executor_type="codex", supports_follow_up=True, supports_resume=True),
            ]
            if settings.codex_executor_enabled
            else [ExecutorCapabilities(executor_type="mock", supports_follow_up=True)]
        ),
        default_executor_type="codex" if settings.codex_executor_enabled else "mock",
    )

    result = await brain.handle_user_message(scenario.name, scenario.user_text)
    tool_names = [item.tool_name for item in result.tool_invocations]
    reply_lower = result.reply_text.lower()
    expected_tools = (
        scenario.expected_tools_when_real_executor
        if settings.codex_executor_enabled and scenario.expected_tools_when_real_executor
        else scenario.expected_tools
    )
    forbidden_tools = list(scenario.forbidden_tools)
    if not settings.codex_executor_enabled:
        forbidden_tools.extend(scenario.forbidden_tools_when_mock_only)
    return CommunicationEvalResult(
        scenario=scenario.name,
        reply_text=result.reply_text,
        tool_names=tool_names,
        passed_expected_tools=all(tool in tool_names for tool in expected_tools),
        passed_forbidden_tools=all(tool not in tool_names for tool in forbidden_tools),
        mechanical_reply=any(marker in reply_lower for marker in MECHANICAL_REPLY_MARKERS),
        passed_mock_only_reply_rules=(
            True
            if settings.codex_executor_enabled
            else all(
                marker not in reply_lower
                for marker in scenario.forbidden_reply_markers_when_mock_only
            )
        ),
    )
