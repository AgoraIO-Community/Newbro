from __future__ import annotations

import io

import pytest

from newbro.executors.core.capabilities import ExecutorCapabilities, ExecutorSkill
from newbro.executors.node.config import ExecutorNodeSettings
from newbro.executors.node.service import ExecutorNodeLifecycleReporter, ExecutorNodeService
from newbro.executors.node.audio import AudioTranscriptionResult


class FakeAudioTranscriber:
    @property
    def available(self) -> bool:
        return False

    async def transcribe(self, audio):
        raise NotImplementedError


class FakeBaseExecutor:
    def get_capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(executor_type="acpx")


class FakeExecutorWithSkills:
    def __init__(self, caps: ExecutorCapabilities) -> None:
        self._caps = caps

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._caps
    # intentionally no refresh_capabilities, so _descriptor uses get_capabilities()


@pytest.mark.anyio
async def test_descriptor_carries_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ExecutorNodeService,
        "_build_executors",
        lambda self, _executors_config: {"acpx": FakeBaseExecutor()},
    )
    service = ExecutorNodeService(
        settings=ExecutorNodeSettings(
            synapse_base_url="http://127.0.0.1:8000",
            node_id="node-1",
            token="token-1",
            enabled_executors=["acpx"],
        ),
        executors_config={},
        audio_transcriber=FakeAudioTranscriber(),
        reporter=ExecutorNodeLifecycleReporter(stream=io.StringIO()),
    )

    caps = ExecutorCapabilities(
        executor_type="acpx",
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")],
    )
    descriptor = await service._descriptor("acpx", FakeExecutorWithSkills(caps))
    assert descriptor.skills[0].name == "doc"
