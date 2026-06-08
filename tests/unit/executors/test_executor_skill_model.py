from newbro.executors.core.capabilities import ExecutorCapabilities, ExecutorSkill


def test_executor_skill_defaults():
    skill = ExecutorSkill(name="doc", display_name="Word Docs", description="Edit docx", path="/x/SKILL.md")
    assert skill.enabled is True
    assert skill.hint is None


def test_capabilities_default_skills_empty():
    caps = ExecutorCapabilities(executor_type="codex")
    assert caps.skills == []
