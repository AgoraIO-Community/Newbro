from newbro.runtime.models import BroExecutorCapabilitySummary
from newbro.protocol.executor_node import ExecutorNodeExecutor, ExecutorSkill
from newbro.runtime.session import _codex_summary_from_capability


def test_summary_projects_skills():
    cap = ExecutorNodeExecutor(
        executor_type="codex",
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")],
    )
    summary = _codex_summary_from_capability(cap)
    assert isinstance(summary, BroExecutorCapabilitySummary)
    assert summary.skills[0].name == "doc"
    # existing fields still projected
    assert summary.supports_thread_list == cap.supports_thread_list
