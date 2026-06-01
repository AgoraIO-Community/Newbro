from __future__ import annotations

import asyncio
import base64
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
    EXECUTOR_CONTROL_MAX_MESSAGE_BYTES,
    ExecutorAudioInstruction,
    ExecutorTextInstruction,
    StartCodexTurnCommand,
    SubscribeCodexThreadCommand,
    SupplyInteractionResponseCommand,
    TranscribeAudioInstructionCommand,
    UnsubscribeCodexThreadCommand,
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

    async def list_threads(self, workspace_id):
        assert workspace_id == "ws-forge"
        return [
            {
                "id": "codex-native-thread-1",
                "sessionId": "codex-native-thread-1",
                "preview": "Task: Imported thread",
                "status": {"type": "notLoaded"},
                "cwd": "/tmp/workspace",
                "path": "/tmp/thread.jsonl",
                "createdAt": 1779850000,
                "updatedAt": 1779850100,
                "cliVersion": "0.133.0",
                "source": "vscode",
            }
        ]


class FakeStartTurnExecutor(FakeExecutor):
    async def start_turn_request(self, command):
        from newbro.executors.core import ExecutorEvent, ExecutorEventType

        assert command.request_id == "turn-req-1"
        assert command.target_persona_id == "forge"
        assert command.target_thread_id == "public-thread-1"
        assert command.thread_id == "codex-thread-1"
        assert command.instruction.text == "Continue directly."
        yield ExecutorEvent(
            run_id=command.request_id,
            session_id=command.request_id,
            event_type=ExecutorEventType.PROGRESS,
            message="Direct turn started.",
            metadata={
                "client_request_id": "client-1",
                "instruction_id": command.instruction.instruction_id,
                "executor_thread_id": "codex-thread-1",
                "executor_turn_id": "codex-turn-1",
            },
        )
        yield ExecutorEvent(
            run_id=command.request_id,
            session_id=command.request_id,
            event_type=ExecutorEventType.COMPLETED,
            message="Done.",
            metadata={
                "client_request_id": "client-1",
                "instruction_id": command.instruction.instruction_id,
                "executor_thread_id": "codex-thread-1",
                "executor_turn_id": "codex-turn-1",
            },
        )


class FakeFailingStartTurnExecutor(FakeExecutor):
    async def start_turn_request(self, command):
        if False:
            yield None
        raise RuntimeError("adapter exploded")


class FakeFailedEventStartTurnExecutor(FakeExecutor):
    async def start_turn_request(self, command):
        from newbro.executors.core import ExecutorEvent, ExecutorEventType

        yield ExecutorEvent(
            run_id=command.request_id,
            session_id=command.request_id,
            event_type=ExecutorEventType.FAILED,
            message="adapter returned failure",
            metadata={},
        )


class FakeAudioTranscriber:
    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, audio):
        assert base64.b64decode(audio.pcm16_b64, validate=True)
        assert not hasattr(audio, "artifact_path")
        return AudioTranscriptionResult(
            text="Please continue from the audio.",
            language="en",
            duration_seconds=1.0,
            metadata={"whisper_model": "fake"},
        )


class FakeCodexThreadClient:
    def __init__(self) -> None:
        self.events: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    async def next_event(self) -> dict[str, object]:
        return await self.events.get()

    async def close(self) -> None:
        return None


class FakeThreadSubscribingExecutor(FakeExecutor):
    def __init__(self) -> None:
        self.subscribed: list[tuple[str, str | None]] = []
        self.unsubscribed: list[str] = []
        self.client = FakeCodexThreadClient()

    async def subscribe_thread(self, thread_id: str, *, workspace_id: str | None = None) -> CodexExecutorSession:
        self.subscribed.append((thread_id, workspace_id))
        session = CodexExecutorSession(session_id="codex-sub-session-1", executor_type="codex")
        session.thread_id = thread_id
        session._client = self.client
        return session

    async def unsubscribe_thread(self, session: CodexExecutorSession) -> dict[str, object]:
        self.unsubscribed.append(session.thread_id or "")
        await session.close()
        return {"status": "unsubscribed"}


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


def _audio_instruction() -> ExecutorAudioInstruction:
    pcm16 = b"\x01\x00" * 24_000
    return ExecutorAudioInstruction(
        audio_instruction_id="aud-1",
        target_persona_id="forge",
        target_thread_id="bro-thread-1",
        pcm16_b64=base64.b64encode(pcm16).decode("ascii"),
        mime_type="audio/pcm",
        duration_ms=1000,
        sample_rate=24000,
        num_channels=1,
        samples_per_channel=24000,
        size_bytes=len(pcm16),
    )


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
        assert kwargs["max_size"] == EXECUTOR_CONTROL_MAX_MESSAGE_BYTES
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
        assert kwargs["max_size"] == EXECUTOR_CONTROL_MAX_MESSAGE_BYTES
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
async def test_supply_interaction_response_routes_outbound_turn_to_codex_executor(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    session = CodexExecutorSession(session_id="codex-outbound-session", executor_type="codex")
    captured: dict[str, object] = {}

    class FakeClient:
        async def respond_to_request(self, **kwargs) -> None:
            captured.update(kwargs)

    session._client = FakeClient()
    codex_executor = service._executors["codex"]
    codex_executor._active_runs = {"out-turn-1": session}

    command = SupplyInteractionResponseCommand(
        interaction_request_id="ireq-outbound",
        outbound_turn_request_id="out-turn-1",
        action="approve",
        native_response={
            "request_id": "req-out",
            "method": "item/tool/requestUserInput",
            "params": {"threadId": "thread-1"},
        },
    )

    await service._supply_interaction_response(command)

    assert captured["request_id"] == "req-out"
    assert captured["method"] == "item/tool/requestUserInput"
    assert captured["action"] == "approve"


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
        audio=_audio_instruction().model_copy(update={"metadata": {"client_request_id": "audio-client-1"}}),
    )
    try:
        await service._dispatch_audio_instruction(websocket, command)
    finally:
        background_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await background_task

    assert websocket.sent[0]["type"] == "run_event"
    assert websocket.sent[0]["event_type"] == "progress"
    assert websocket.sent[0]["message"] == "Audio instruction transcribed."
    assert websocket.sent[0]["metadata"]["source_audio_instruction_id"] == "aud-1"
    assert websocket.sent[0]["metadata"]["client_request_id"] == "audio-client-1"
    assert websocket.sent[0]["metadata"]["target_thread_id"] == "bro-thread-1"
    assert websocket.sent[0]["metadata"]["transcript_text"] == "Please continue from the audio."
    assert len(websocket.sent) == 1


@pytest.mark.anyio
async def test_transcribe_audio_instruction_returns_transcript_without_active_run(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    websocket = FakeWebSocket([])
    command = TranscribeAudioInstructionCommand(
        request_id="audio-req-1",
        executor_type="codex",
        audio=_audio_instruction(),
    )

    await service._transcribe_audio_instruction(websocket, command)

    assert websocket.sent == [
        {
            "type": "audio_instruction_transcribed",
            "request_id": "audio-req-1",
            "node_id": "node-1",
            "executor_type": "codex",
            "ok": True,
            "error": None,
            "transcript_text": "Please continue from the audio.",
            "language": "en",
            "duration_seconds": 1.0,
            "metadata": {
                "source": "executor_node_whisper",
                "source_audio_instruction_id": "aud-1",
                "target_thread_id": "bro-thread-1",
                "whisper_model": "fake",
            },
        }
    ]


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


@pytest.mark.anyio
async def test_node_service_starts_codex_turn_request(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    service._executors["codex"] = FakeStartTurnExecutor()
    websocket = FakeWebSocket([])
    command = StartCodexTurnCommand(
        request_id="turn-req-1",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        instruction=ExecutorTextInstruction(
            instruction_id="txt-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Continue directly.",
            metadata={"client_request_id": "client-1"},
        ),
    )

    await service._handle_message(websocket, command.model_dump(mode="json"))
    for _ in range(20):
        if len(websocket.sent) >= 2:
            break
        await asyncio.sleep(0)

    assert [event["type"] for event in websocket.sent] == ["codex_turn_event", "codex_turn_event"]
    assert websocket.sent[0]["request_id"] == "turn-req-1"
    assert websocket.sent[0]["event_type"] == "progress"
    assert websocket.sent[0]["executor_thread_id"] == "codex-thread-1"
    assert websocket.sent[0]["executor_turn_id"] == "codex-turn-1"
    assert websocket.sent[0]["metadata"]["client_request_id"] == "client-1"
    assert websocket.sent[0]["metadata"]["instruction_id"] == "txt-1"
    assert websocket.sent[-1]["event_type"] == "completed"


@pytest.mark.anyio
async def test_node_service_unsupported_codex_turn_failure_preserves_correlation_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    websocket = FakeWebSocket([])
    command = StartCodexTurnCommand(
        request_id="turn-req-unsupported",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        metadata={"command_meta": "kept"},
        instruction=ExecutorTextInstruction(
            instruction_id="txt-unsupported",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Continue directly.",
            source_audio_instruction_id="aud-unsupported",
            metadata={"client_request_id": "client-unsupported"},
        ),
    )

    await service._start_codex_turn(websocket, command)

    assert websocket.sent[0]["type"] == "codex_turn_event"
    assert websocket.sent[0]["ok"] is False
    metadata = websocket.sent[0]["metadata"]
    assert metadata["instruction_id"] == "txt-unsupported"
    assert metadata["client_request_id"] == "client-unsupported"
    assert metadata["source_audio_instruction_id"] == "aud-unsupported"
    assert metadata["target_persona_id"] == "forge"
    assert metadata["target_thread_id"] == "public-thread-1"
    assert metadata["command_meta"] == "kept"


@pytest.mark.anyio
async def test_node_service_codex_turn_exception_preserves_correlation_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    service._executors["codex"] = FakeFailingStartTurnExecutor()
    websocket = FakeWebSocket([])
    command = StartCodexTurnCommand(
        request_id="turn-req-failed",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        metadata={"command_meta": "kept"},
        instruction=ExecutorTextInstruction(
            instruction_id="txt-failed",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Continue directly.",
            source_audio_instruction_id="aud-failed",
            metadata={"client_request_id": "client-failed"},
        ),
    )

    await service._start_codex_turn(websocket, command)

    assert websocket.sent[0]["type"] == "codex_turn_event"
    assert websocket.sent[0]["ok"] is False
    assert websocket.sent[0]["error"] == "adapter exploded"
    metadata = websocket.sent[0]["metadata"]
    assert metadata["instruction_id"] == "txt-failed"
    assert metadata["client_request_id"] == "client-failed"
    assert metadata["source_audio_instruction_id"] == "aud-failed"
    assert metadata["target_persona_id"] == "forge"
    assert metadata["target_thread_id"] == "public-thread-1"
    assert metadata["command_meta"] == "kept"


@pytest.mark.anyio
async def test_node_service_codex_turn_adapter_failure_event_preserves_correlation_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    service._executors["codex"] = FakeFailedEventStartTurnExecutor()
    websocket = FakeWebSocket([])
    command = StartCodexTurnCommand(
        request_id="turn-req-event-failed",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        metadata={"command_meta": "kept"},
        instruction=ExecutorTextInstruction(
            instruction_id="txt-event-failed",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Continue directly.",
            source_audio_instruction_id="aud-event-failed",
            metadata={"client_request_id": "client-event-failed"},
        ),
    )

    await service._start_codex_turn(websocket, command)

    assert websocket.sent[0]["type"] == "codex_turn_event"
    assert websocket.sent[0]["ok"] is False
    assert websocket.sent[0]["error"] == "adapter returned failure"
    metadata = websocket.sent[0]["metadata"]
    assert metadata["instruction_id"] == "txt-event-failed"
    assert metadata["client_request_id"] == "client-event-failed"
    assert metadata["source_audio_instruction_id"] == "aud-event-failed"
    assert metadata["target_persona_id"] == "forge"
    assert metadata["target_thread_id"] == "public-thread-1"
    assert metadata["command_meta"] == "kept"


@pytest.mark.anyio
async def test_list_codex_threads_returns_normalized_thread_list(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    websocket = FakeWebSocket([])

    await service._list_codex_threads(
        websocket,
        service_module.ListCodexThreadsCommand(request_id="req-1", workspace_id="ws-forge"),
    )

    assert websocket.sent == [
        {
            "type": "codex_threads_listed",
            "request_id": "req-1",
            "node_id": "node-1",
            "executor_type": "codex",
            "ok": True,
            "error": None,
            "threads": [
                {
                    "thread_id": "codex-native-thread-1",
                    "session_id": "codex-native-thread-1",
                    "preview": "Task: Imported thread",
                    "title": None,
                    "cwd": "/tmp/workspace",
                    "path": "/tmp/thread.jsonl",
                    "status": "notLoaded",
                    "created_at": 1779850000,
                    "updated_at": 1779850100,
                    "cli_version": "0.133.0",
                    "source": "vscode",
                    "diagnostics": {
                        "forked_from_id": None,
                        "ephemeral": None,
                        "model_provider": None,
                        "thread_source": None,
                        "agent_nickname": None,
                        "agent_role": None,
                        "git_info": None,
                    },
                }
            ],
        }
    ]


@pytest.mark.anyio
async def test_subscribe_codex_thread_streams_events_and_unsubscribes(monkeypatch: pytest.MonkeyPatch):
    stream = io.StringIO()
    reporter = ExecutorNodeLifecycleReporter(stream=stream)
    service = build_service(monkeypatch, reporter=reporter)
    executor = FakeThreadSubscribingExecutor()
    service._executors["codex"] = executor
    websocket = FakeWebSocket([])
    command = SubscribeCodexThreadCommand(
        request_id="req-sub-1",
        subscription_id="sub-1",
        session_id="session-1",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        workspace_id="/tmp/workspace",
    )

    await service._subscribe_codex_thread(websocket, command)
    assert executor.subscribed == [("codex-thread-1", "/tmp/workspace")]
    assert websocket.sent[0]["type"] == "codex_thread_subscribed"
    assert websocket.sent[0]["metadata"] == {"source": "thread/resume"}

    await executor.client.events.put(
        {
            "method": "turn/completed",
            "params": {
                "thread": {"id": "codex-thread-1"},
                "turn": {"id": "turn-1"},
            },
        }
    )
    for _ in range(20):
        if len(websocket.sent) > 1:
            break
        await asyncio.sleep(0)
    assert websocket.sent[1]["type"] == "codex_thread_event"
    assert websocket.sent[1]["subscription_id"] == "sub-1"
    assert websocket.sent[1]["thread_id"] == "codex-thread-1"
    assert websocket.sent[1]["method"] == "turn/completed"

    await service._unsubscribe_codex_thread(
        websocket,
        UnsubscribeCodexThreadCommand(
            request_id="req-unsub-1",
            subscription_id="sub-1",
            thread_id="codex-thread-1",
        ),
    )
    assert executor.unsubscribed == ["codex-thread-1"]
    assert websocket.sent[-1]["type"] == "codex_thread_unsubscribed"
    assert websocket.sent[-1]["status"] == "unsubscribed"
    assert service._codex_thread_subscriptions == {}
