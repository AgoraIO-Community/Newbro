import pytest

from newbro.executors.node.service import ExecutorNodeService


@pytest.mark.anyio
async def test_aclose_calls_executor_aclose_when_present():
    closed = []

    class FakeCodex:
        async def aclose(self):
            closed.append("codex")

    class FakeAcpx:
        pass  # no aclose → must be skipped cleanly

    # Build a bare service instance without running __init__ side effects.
    service = ExecutorNodeService.__new__(ExecutorNodeService)
    service._executors = {"codex": FakeCodex(), "acpx": FakeAcpx()}

    await service.aclose()
    assert closed == ["codex"]
