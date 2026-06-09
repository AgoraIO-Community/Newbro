# tests/unit/executors/test_node_build_executors.py
from newbro.executors.adapters.hermes import HermesExecutor
from newbro.executors.node.config import ExecutorNodeSettings
from newbro.executors.node.service import ExecutorNodeService


class _StubTranscriber:
    available = False


def test_build_executors_constructs_hermes_from_config():
    settings = ExecutorNodeSettings(node_id="n", token="t", enabled_executors=["hermes"])
    service = ExecutorNodeService(
        settings=settings,
        executors_config={"hermes": {"command": "hermes"}},
        audio_transcriber=_StubTranscriber(),  # avoid constructing a real Whisper transcriber
    )
    built = service._executors  # noqa: SLF001 - white-box check of construction
    assert isinstance(built["hermes"], HermesExecutor)
