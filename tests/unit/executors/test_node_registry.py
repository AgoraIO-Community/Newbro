import pytest

from newbro.executors.node.registry import ExecutorNodeRegistry, ExecutorNodeRegistryError


@pytest.mark.anyio
async def test_create_node_accepts_hermes(tmp_path):
    registry = ExecutorNodeRegistry(path=tmp_path / "nodes.yaml")
    issue = await registry.create_node(name="H", enabled_executors=["hermes"])
    assert issue.node.enabled_executors == ["hermes"]


@pytest.mark.anyio
async def test_create_node_rejects_unknown_family(tmp_path):
    registry = ExecutorNodeRegistry(path=tmp_path / "nodes.yaml")
    with pytest.raises(ExecutorNodeRegistryError, match="Unsupported executor family"):
        await registry.create_node(name="X", enabled_executors=["bogus"])
