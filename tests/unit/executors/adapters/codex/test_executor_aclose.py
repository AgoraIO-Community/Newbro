import pytest

from newbro.executors.adapters.codex.executor import CodexExecutor


@pytest.mark.anyio
async def test_aclose_closes_app_session(monkeypatch):
    executor = CodexExecutor(command="codex")
    calls = {"closed": 0}

    async def fake_close():
        calls["closed"] += 1

    monkeypatch.setattr(executor, "_close_app_session", fake_close)
    await executor.aclose()
    assert calls["closed"] == 1
