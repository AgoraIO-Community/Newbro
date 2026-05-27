from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest

from newbro.executors.core import ExecutorCapabilities
from newbro.executors.node.config import ExecutorNodeSettings
from newbro.executors.node.service import ExecutorNodeLifecycleReporter, ExecutorNodeService
import newbro.executors.node.service as service_module
from newbro.executors.adapters.codex.session import CodexExecutorSession
from newbro.executors.node.audio import AudioTranscriptionResult
from newbro.protocol import (
    DispatchAudioInstructionCommand,
    DispatchTextInstructionCommand,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    SupplyInteractionResponseCommand,
)


class FakeExecutor:
    def get_capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(
            executor_type="codex",
            supports_resume=True,
            supports_follow_up=True,
            supports_audio_instruction=False,
            supports_pause=True,
            supports_cancel=True,
        )

    async def handle_text_instruction(self, run, session, instruction):
        from newbro.executors.core import ExecutorEvent, ExecutorEventType

        yield ExecutorEvent(
            run_id=run.run_id,
            session_id=session.session_id,
            event_type=ExecutorEventType.PROGRESS,
            message="text sent",
            metadata={
                "instruction_id": instruction.instruction_id,
                "source_audio_instruction_id": instruction.source_audio_instruction_id or "",
                "text": instruction.text,
            },
        )


class FakeAudioTranscriber:
    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, audio):
        return AudioTranscriptionResult(
            text="Please continue from the audio.",
            language="en",
            duration_seconds=1.0,
            metadata={"whisper_model": "fake"},
        )


class FakeWebSocket:
    def __init__(self, incoming: list[object]):
        self._incoming = list(incoming)
        self.sent: list[dict[str, object]] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        if not self._incoming:
            raise asyncio.CancelledError()
        next_item = self._incoming.pop(0)
        if isinstance(next_item, BaseException):
            raise next_item
        return json.dumps(next_item)


class FakeConnection:
    def __init__(self, websocket: FakeWebSocket):
        self._websocket = websocket

    async def __aenter__(self) -> FakeWebSocket:
        return self._websocket

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def build_service(monkeypatch: pytest.MonkeyPatch, *, reporter: ExecutorNodeLifecycleReporter) -> ExecutorNodeService:
    monkeypatch.setattr(
        ExecutorNodeService,
        "_build_executors",
        lambda self, _executors_config: {"codex": FakeExecutor()},
    )
    return ExecutorNodeService(
        settings=ExecutorNodeSettings(
            synapse_base_url="http://127.0.0.1:8000",
            node_id="node-1",
            token="token-1",
            enabled_executors=["codex"],
        ),
        executors_config={},
        audio_transcriber=FakeAudioTranscriber(),
        reporter=reporter,
    )


@pytest.mark.anyio
async def test_run_forever_reports_retry_then_ready(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    websocket = FakeWebSocket(
        [
            {"type": "ack", "message_type": "register_node", "ok": True, "detail": "registered"},
            asyncio.CancelledError(),
        ]
    )
    attempts: list[object] = [
        OSError("connection refused"),
        FakeConnection(websocket),
    ]
    delays: list[float] = []

    def fake_connect(url: str, **kwargs) -> FakeConnection:
        assert url == "ws://127.0.0.1:8000/api/executors/control"
        assert kwargs["proxy"] is None
        attempt = attempts.pop(0)
        if isinstance(attempt, Exception):
            raise attempt
        return attempt

    async def fake_sleep(delay_seconds: float) -> None:
        delays.append(delay_seconds)

    monkeypatch.setattr(service_module.websockets, "connect", fake_connect)
    monkeypatch.setattr(service_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await service.run_forever()

    output = stream.getvalue()
    assert "[start] executor node node_id=node-1 executors=codex newbro=http://127.0.0.1:8000" in output
    assert "[connect] executor node attempt=1 url=ws://127.0.0.1:8000/api/executors/control" in output
    assert (
        "[warn] executor node attempt=1 connect_failed=OSError: connection refused "
        "url=ws://127.0.0.1:8000/api/executors/control"
    ) in output
    assert "[retry] executor node retrying in 1.0s" in output
    assert "[connect] executor node attempt=2 url=ws://127.0.0.1:8000/api/executors/control" in output
    assert "[ready] executor node node_id=node-1 executors=codex newbro=http://127.0.0.1:8000" in output
    assert output.index("[connect] executor node attempt=2") < output.index("[ready] executor node")
    assert delays == [1.0]
    assert websocket.sent[0]["type"] == "register_node"
    assert websocket.sent[0]["token"] == "token-1"


@pytest.mark.anyio
async def test_run_forever_reports_disconnect_after_ready(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    websocket = FakeWebSocket(
        [
            {"type": "ack", "message_type": "register_node", "ok": True, "detail": "registered"},
            RuntimeError("connection lost"),
        ]
    )
    delays: list[float] = []

    def fake_connect(url: str, **kwargs) -> FakeConnection:
        assert url == "ws://127.0.0.1:8000/api/executors/control"
        assert kwargs["proxy"] is None
        return FakeConnection(websocket)

    async def fake_sleep(delay_seconds: float) -> None:
        delays.append(delay_seconds)
        raise asyncio.CancelledError()

    monkeypatch.setattr(service_module.websockets, "connect", fake_connect)
    monkeypatch.setattr(service_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await service.run_forever()

    output = stream.getvalue()
    assert "[ready] executor node node_id=node-1 executors=codex newbro=http://127.0.0.1:8000" in output
    assert (
        "[warn] executor node disconnected=RuntimeError: connection lost "
        "url=ws://127.0.0.1:8000/api/executors/control"
    ) in output
    assert "[retry] executor node retrying in 1.0s" in output
    assert delays == [1.0]


@pytest.mark.anyio
async def test_supply_interaction_response_logs_failures(monkeypatch: pytest.MonkeyPatch, caplog):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    session = CodexExecutorSession(session_id="codex-session-1", executor_type="codex")

    class FakeClient:
        async def respond_to_request(self, **kwargs) -> None:
            raise RuntimeError("boom")

    session._client = FakeClient()
    service._live_sessions["exec-1"] = session

    command = SupplyInteractionResponseCommand(
        interaction_request_id="ireq-1",
        execution_session_id="exec-1",
        action="approve",
        native_response={
            "request_id": "req-1",
            "method": "item/permissions/requestApproval",
            "params": {"prompt": "Need approval."},
        },
    )

    with caplog.at_level(logging.WARNING):
        await service._supply_interaction_response(command)

    assert "Failed to forward interaction response to executor node session" in caplog.text
    assert "exec-1" in caplog.text
    assert "ireq-1" in caplog.text


@pytest.mark.anyio
async def test_dispatch_audio_instruction_forwards_to_active_executor(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    websocket = FakeWebSocket([])
    session = CodexExecutorSession(session_id="codex-session-1", executor_type="codex")
    background_task = asyncio.create_task(asyncio.sleep(60))
    service._live_sessions["exec-1"] = session
    service._active_runs["run-1"] = service_module.LocalRunContext(
        executor=service._executors["codex"],
        execution_session_id="exec-1",
        background_task=background_task,
    )
    command = DispatchAudioInstructionCommand(
        run_id="run-1",
        execution_session_id="exec-1",
        executor_type="codex",
        task_id="task-1",
        audio=ExecutorAudioInstruction(
            audio_instruction_id="aud-1",
            target_persona_id="forge",
            artifact_path="/tmp/audio.pcm",
            mime_type="audio/pcm",
            duration_ms=1000,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=24000,
            size_bytes=48000,
        ),
    )
    try:
        await service._dispatch_audio_instruction(websocket, command)
    finally:
        background_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await background_task

    assert websocket.sent[-1]["type"] == "run_event"
    assert websocket.sent[-1]["event_type"] == "progress"
    assert websocket.sent[-1]["metadata"]["source_audio_instruction_id"] == "aud-1"
    assert websocket.sent[-1]["metadata"]["text"] == "Please continue from the audio."


@pytest.mark.anyio
async def test_dispatch_text_instruction_forwards_to_active_executor(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    websocket = FakeWebSocket([])
    session = CodexExecutorSession(session_id="codex-session-1", executor_type="codex")
    background_task = asyncio.create_task(asyncio.sleep(60))
    service._live_sessions["exec-1"] = session
    service._active_runs["run-1"] = service_module.LocalRunContext(
        executor=service._executors["codex"],
        execution_session_id="exec-1",
        background_task=background_task,
    )
    command = DispatchTextInstructionCommand(
        run_id="run-1",
        execution_session_id="exec-1",
        executor_type="codex",
        task_id="task-1",
        instruction=ExecutorTextInstruction(
            instruction_id="txt-1",
            target_persona_id="forge",
            text="Continue directly.",
            metadata={"source": "bro_detail_text"},
        ),
    )
    try:
        await service._dispatch_text_instruction(websocket, command)
    finally:
        background_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await background_task

    assert websocket.sent[-1]["type"] == "run_event"
    assert websocket.sent[-1]["event_type"] == "progress"
    assert websocket.sent[-1]["metadata"]["instruction_id"] == "txt-1"
    assert websocket.sent[-1]["metadata"]["text"] == "Continue directly."
