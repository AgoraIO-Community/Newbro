from __future__ import annotations

import json

import pytest

from newbro.connectors.base import ActiveConnectorBinding
from newbro.connectors.voice.agora_convoai.module import (
    ChatCompletionTurnCoalescer,
    _build_completion_response,
    _compat_event_from_chat_completion,
    _has_explicit_event_type,
    _resolve_voice_target_persona_id,
    _stream_runtime_decision,
    _stream_silent_completion,
)
from newbro.connectors.voice.agora_convoai.models import ChatCompletionRequest
from newbro.protocol import AgoraVoiceEvent, AgoraVoiceEventType, RuntimeDecision


class _FakeTransport:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = events
        self.calls: list[dict[str, object]] = []

    async def stream_message(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str,
        target_persona_id: str | None = None,
    ):
        self.calls.append(
            {
                "session_id": session_id,
                "text": text,
                "request_id": request_id,
                "target_persona_id": target_persona_id,
            }
        )
        for event in self.events:
            yield event

    async def submit_agora_event(self, session_id: str, event: AgoraVoiceEvent) -> RuntimeDecision:
        self.calls.append({"session_id": session_id, "event": event})
        return RuntimeDecision(should_speak=True, response_text="Runtime reply")

    async def get_voice_target_persona_id(self, session_id: str) -> str | None:
        self.calls.append({"session_id": session_id, "action": "get_voice_target_persona_id"})
        return "persona-forge"


class _FakeSpeaker:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def speak(self, runtime_session_id: str, text: str) -> None:
        self.calls.append({"runtime_session_id": runtime_session_id, "text": text})


def _decode_sse_payload(payload: str) -> dict[str, object]:
    assert payload.startswith("data: ")
    return json.loads(payload.removeprefix("data: ").strip())


@pytest.mark.anyio
async def test_stream_runtime_decision_uses_runtime_should_speak_contract():
    chunks = [
        chunk
        async for chunk in _stream_runtime_decision(
            decision=RuntimeDecision(should_speak=True, response_text="Runtime reply"),
            model_name="newbro-bridge",
        )
    ]

    first = _decode_sse_payload(chunks[0])
    assert first["choices"][0]["delta"]["content"] == "Runtime reply"  # type: ignore[index]
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.anyio
async def test_stream_runtime_decision_is_silent_when_runtime_says_not_to_speak():
    chunks = [
        chunk
        async for chunk in _stream_runtime_decision(
            decision=RuntimeDecision(should_speak=False, response_text="Do not say this"),
            model_name="newbro-bridge",
        )
    ]

    first = _decode_sse_payload(chunks[0])
    assert first["choices"][0]["delta"]["content"] == ""  # type: ignore[index]


def test_chat_completion_compat_uses_custom_llm_callback_as_turn_boundary_without_metadata():
    event = _compat_event_from_chat_completion(
        payload=ChatCompletionRequest(
            messages=[{"role": "user", "content": "Can you hear me?"}],
        ),
        session_id="session-1",
        text="Can you hear me?",
        target_persona_id="persona-forge",
    )

    assert event is not None
    assert event.type == AgoraVoiceEventType.STT_FINAL
    assert event.target_persona_id == "persona-forge"
    assert event.metadata["turn_boundary_source"] == "agora_custom_llm_callback"
    assert not _has_explicit_event_type(ChatCompletionRequest(messages=[]))


def test_chat_completion_compat_uses_explicit_partial_event_metadata():
    event = _compat_event_from_chat_completion(
        payload=ChatCompletionRequest(
            messages=[{"role": "user", "content": "Can you hear me?"}],
            event_type="stt.partial",
        ),
        session_id="session-1",
        text="Can you hear me?",
        target_persona_id="persona-forge",
    )

    assert event is not None
    assert event.type == AgoraVoiceEventType.STT_PARTIAL
    assert event.target_persona_id == "persona-forge"
    assert event.metadata["compatibility_endpoint"] == "/chat/completions"


def test_chat_completion_compat_uses_explicit_event_metadata():
    event = _compat_event_from_chat_completion(
        payload=ChatCompletionRequest(
            messages=[{"role": "user", "content": "Ask Codex to inspect docs."}],
            event_type="stt.final",
            metadata={"source": "fake-sdk"},
        ),
        session_id="session-1",
        text="Ask Codex to inspect docs.",
        target_persona_id=None,
    )

    assert event is not None
    assert event.type == AgoraVoiceEventType.STT_FINAL
    assert event.metadata["source"] == "fake-sdk"
    assert _has_explicit_event_type(ChatCompletionRequest(messages=[], event_type="stt.final"))


@pytest.mark.anyio
async def test_chat_completion_turn_coalescer_flushes_only_latest_callback_and_speaks_decision():
    transport = _FakeTransport([])
    speaker = _FakeSpeaker()
    coalescer = ChatCompletionTurnCoalescer(
        transport=transport,  # type: ignore[arg-type]
        speaker=speaker,  # type: ignore[arg-type]
        delay_seconds=60,
    )
    binding = ActiveConnectorBinding(
        binding_id="binding-1",
        synapse_session_id="session-1",
        runtime_session_id="runtime-1",
        metadata={},
        task=None,  # type: ignore[arg-type]
    )

    first = _compat_event_from_chat_completion(
        payload=ChatCompletionRequest(messages=[{"role": "user", "content": "Plan"}]),
        session_id="session-1",
        text="Plan",
        target_persona_id="persona-forge",
    )
    second = _compat_event_from_chat_completion(
        payload=ChatCompletionRequest(messages=[{"role": "user", "content": "Plan the trip"}]),
        session_id="session-1",
        text="Plan the trip",
        target_persona_id="persona-forge",
    )
    assert first is not None
    assert second is not None

    coalescer.submit(binding=binding, event=first)
    coalescer.submit(binding=binding, event=second)
    decision = await coalescer.flush_now("binding-1")

    assert decision is not None
    submitted = [call for call in transport.calls if "event" in call]
    assert len(submitted) == 1
    assert submitted[0]["event"].text == "Plan the trip"  # type: ignore[index, union-attr]
    assert speaker.calls == [{"runtime_session_id": "runtime-1", "text": "Runtime reply"}]


@pytest.mark.anyio
async def test_resolve_voice_target_reads_bound_session_snapshot():
    transport = _FakeTransport([])

    target = await _resolve_voice_target_persona_id(
        transport=transport,  # type: ignore[arg-type]
        synapse_session_id="session-1",
    )

    assert target == "persona-forge"
    assert {"session_id": "session-1", "action": "get_voice_target_persona_id"} in transport.calls


@pytest.mark.anyio
async def test_silent_stream_completion_returns_compatible_empty_completion():
    chunks = [chunk async for chunk in _stream_silent_completion(model_name="newbro-bridge")]

    first = _decode_sse_payload(chunks[0])
    assert first["choices"][0]["delta"]["content"] == ""  # type: ignore[index]
    final = _decode_sse_payload(chunks[1])
    assert final["choices"][0]["finish_reason"] == "stop"  # type: ignore[index]
    assert chunks[-1] == "data: [DONE]\n\n"


def test_silent_non_stream_completion_is_compatible_empty_completion():
    payload = _build_completion_response(
        completion_id="chatcmpl-test",
        created=123,
        model_name="newbro-bridge",
        reply_text="",
    )

    assert payload["choices"][0]["message"]["content"] == ""  # type: ignore[index]
    assert payload["choices"][0]["finish_reason"] == "stop"  # type: ignore[index]
