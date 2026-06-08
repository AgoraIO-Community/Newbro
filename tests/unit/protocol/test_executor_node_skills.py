from newbro.protocol.executor_node import ExecutorNodeExecutor
from newbro.executors.core.capabilities import ExecutorSkill


def test_wire_executor_round_trips_skills():
    wire = ExecutorNodeExecutor(
        executor_type="codex",
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")],
    )
    dumped = wire.model_dump()
    restored = ExecutorNodeExecutor.model_validate(dumped)
    assert restored.skills[0].name == "doc"


def test_wire_executor_defaults_empty_skills():
    assert ExecutorNodeExecutor(executor_type="codex").skills == []
