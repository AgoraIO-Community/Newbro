import json
from pathlib import Path

import pytest

from newbro.executors.adapters.codex.executor import CodexExecutor

FIXTURE = json.loads(Path("docs/protocol/fixtures/codex-skills-list-sample.json").read_text())


@pytest.mark.anyio
async def test_refresh_capabilities_loads_and_caches_skills(monkeypatch):
    executor = CodexExecutor(command="codex")
    calls = {"n": 0}

    async def counting_load():
        calls["n"] += 1
        return FIXTURE

    import newbro.executors.adapters.codex.executor as ex_mod
    from newbro.executors.adapters.codex.probe import CodexProbeResult

    monkeypatch.setattr(
        ex_mod,
        "probe_codex_command",
        lambda command: CodexProbeResult(path="codex", version="0.137.0", ok=True),
    )
    monkeypatch.setattr(executor, "_load_skills", counting_load)

    caps = await executor.refresh_capabilities()
    assert any(s.name == "doc" for s in caps.skills)

    await executor.refresh_capabilities()
    assert calls["n"] == 1


@pytest.mark.anyio
async def test_skills_empty_when_load_fails(monkeypatch):
    executor = CodexExecutor(command="codex")

    import newbro.executors.adapters.codex.executor as ex_mod
    from newbro.executors.adapters.codex.probe import CodexProbeResult

    monkeypatch.setattr(
        ex_mod,
        "probe_codex_command",
        lambda command: CodexProbeResult(path="codex", version="0.137.0", ok=True),
    )

    async def boom():
        raise RuntimeError("app-server down")

    monkeypatch.setattr(executor, "_load_skills", boom)
    caps = await executor.refresh_capabilities()
    assert caps.skills == []
