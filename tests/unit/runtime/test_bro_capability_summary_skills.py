from newbro.runtime.models import BroExecutorCapabilitySummary
from newbro.executors.core.capabilities import ExecutorSkill


def test_summary_defaults_empty_skills():
    assert BroExecutorCapabilitySummary().skills == []


def test_summary_carries_skills():
    summary = BroExecutorCapabilitySummary(
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")]
    )
    assert summary.skills[0].display_name == "Word Docs"
