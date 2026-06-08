from __future__ import annotations

import importlib

from newbro.executors.node.config import ExecutorNodeSettings, LoadedExecutorNodeConfig

executor_node_main = importlib.import_module("newbro.executors.node.__main__")


def test_main_returns_130_on_keyboard_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(
        executor_node_main,
        "load_executor_node_config",
        lambda: LoadedExecutorNodeConfig(
            node_settings=ExecutorNodeSettings(
                synapse_base_url="http://127.0.0.1:8000",
                node_id="node-1",
                token="token-1",
                enabled_executors=["codex"],
            ),
            executors={},
        ),
    )

    class FakeService:
        def __init__(self, *, settings, executors_config, audio_config=None):
            self.settings = settings
            self.executors_config = executors_config
            self.audio_config = audio_config

        def run_forever(self):
            return object()

    monkeypatch.setattr(executor_node_main, "ExecutorNodeService", FakeService)
    def _fake_run(awaitable):
        # Consume the coroutine so it isn't reported as "never awaited", then
        # simulate a Ctrl-C arriving while the node runs.
        awaitable.close()
        raise KeyboardInterrupt()

    monkeypatch.setattr(executor_node_main.asyncio, "run", _fake_run)

    assert (
        executor_node_main.main(["--base-url", "http://127.0.0.1:8000", "--node-id", "node-1", "--token", "token-1"])
        == 130
    )
    assert "[stop] executor node interrupted" in capsys.readouterr().out


def test_main_applies_enabled_executor_and_acpx_agent_overrides(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        executor_node_main,
        "load_executor_node_config",
        lambda: LoadedExecutorNodeConfig(
            node_settings=ExecutorNodeSettings(
                synapse_base_url="http://127.0.0.1:8000",
                node_id="node-1",
                token="token-1",
                enabled_executors=["codex"],
            ),
            executors={"acpx": {"command": "acpx", "agent": "codex"}},
            audio={"transcription": {"provider": "local_whisper", "model": "base"}},
        ),
    )

    class FakeService:
        def __init__(self, *, settings, executors_config, audio_config=None):
            captured["settings"] = settings
            captured["executors_config"] = executors_config
            captured["audio_config"] = audio_config

        async def run_forever(self):
            return None

        async def aclose(self):
            pass

    monkeypatch.setattr(executor_node_main, "ExecutorNodeService", FakeService)

    assert (
        executor_node_main.main(
            [
                "--base-url",
                "http://127.0.0.1:8000",
                "--node-id",
                "node-1",
                "--token",
                "token-1",
                "--enabled-executor",
                "acpx",
                "--acpx-agent",
                "openclaw",
                "--audio-language",
                "zh",
                "--whisper-model",
                "small",
            ]
        )
        == 0
    )
    assert captured["settings"].enabled_executors == ["acpx"]
    assert captured["executors_config"]["acpx"]["agent"] == "openclaw"
    assert captured["audio_config"]["transcription"]["language"] == "zh"
    assert captured["audio_config"]["transcription"]["model"] == "small"


def test_serve_runs_aclose_in_finally():
    import asyncio
    import contextlib

    closed = {"n": 0}

    class FakeService:
        async def run_forever(self):
            raise asyncio.CancelledError()

        async def aclose(self):
            closed["n"] += 1

    async def drive():
        with contextlib.suppress(asyncio.CancelledError):
            await executor_node_main._serve(FakeService())

    asyncio.run(drive())
    assert closed["n"] == 1
