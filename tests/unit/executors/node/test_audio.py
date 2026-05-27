from __future__ import annotations

import array
from types import SimpleNamespace

import pytest

from newbro.executors.node.audio import LocalWhisperTranscriber, WHISPER_SAMPLE_RATE
from newbro.protocol import ExecutorAudioInstruction


class FakeWhisperModel:
    def __init__(self, *, segments: list[object], captured: dict[str, object]) -> None:
        self._segments = segments
        self._captured = captured

    def transcribe(self, samples, **kwargs):
        self._captured.update(kwargs)
        self._captured["sample_count"] = len(samples)
        return self._segments, SimpleNamespace(language="en", duration=1.0, language_probability=0.99)


def _audio_instruction(path: str, *, sample_rate: int = 24000, sample_count: int = 24000) -> ExecutorAudioInstruction:
    return ExecutorAudioInstruction(
        audio_instruction_id="aud-test",
        target_persona_id="forge",
        target_thread_id="bro-thread-1",
        artifact_path=path,
        mime_type="audio/pcm",
        duration_ms=round((sample_count / sample_rate) * 1000),
        sample_rate=sample_rate,
        num_channels=1,
        samples_per_channel=sample_count,
        size_bytes=sample_count * 2,
    )


def _write_pcm(path, *, sample_count: int = 24000, value: int = 1200) -> None:
    values = array.array("h", (value if index % 2 == 0 else -value for index in range(sample_count)))
    path.write_bytes(values.tobytes())


@pytest.mark.anyio
async def test_local_whisper_transcriber_uses_vad_and_no_speech_controls(tmp_path):
    artifact = tmp_path / "audio.pcm"
    _write_pcm(artifact)
    captured: dict[str, object] = {}
    transcriber = LocalWhisperTranscriber()
    transcriber._import_error = None
    transcriber._model = FakeWhisperModel(
        segments=[
            SimpleNamespace(
                text=" Turn this into a task.",
                no_speech_prob=0.05,
                avg_logprob=-0.1,
            )
        ],
        captured=captured,
    )

    result = await transcriber.transcribe(_audio_instruction(str(artifact)))

    assert result.text == "Turn this into a task."
    assert captured["condition_on_previous_text"] is False
    assert captured["vad_filter"] is True
    assert captured["no_repeat_ngram_size"] == 3
    assert captured["hallucination_silence_threshold"] == 1.0
    assert captured["sample_count"] == WHISPER_SAMPLE_RATE
    assert result.metadata is not None
    assert result.metadata["whisper_segment_count"] == 1
    assert result.metadata["whisper_accepted_segment_count"] == 1
    assert result.metadata["audio_rms_norm"] > 0


@pytest.mark.anyio
async def test_local_whisper_transcriber_rejects_no_clear_speech_segments(tmp_path):
    artifact = tmp_path / "audio.pcm"
    _write_pcm(artifact)
    transcriber = LocalWhisperTranscriber()
    transcriber._import_error = None
    transcriber._model = FakeWhisperModel(
        segments=[
            SimpleNamespace(
                text=" unclear",
                no_speech_prob=0.95,
                avg_logprob=-0.8,
            )
        ],
        captured={},
    )

    with pytest.raises(RuntimeError, match="No clear speech"):
        await transcriber.transcribe(_audio_instruction(str(artifact)))


@pytest.mark.anyio
async def test_local_whisper_transcriber_resamples_browser_pcm_to_whisper_rate(tmp_path):
    artifact = tmp_path / "audio.pcm"
    _write_pcm(artifact, sample_count=48000)
    captured: dict[str, object] = {}
    transcriber = LocalWhisperTranscriber()
    transcriber._import_error = None
    transcriber._model = FakeWhisperModel(
        segments=[
            SimpleNamespace(
                text=" Hello, hello, can you hear me?",
                no_speech_prob=0.1,
                avg_logprob=-0.2,
            )
        ],
        captured=captured,
    )

    result = await transcriber.transcribe(_audio_instruction(str(artifact), sample_rate=48000, sample_count=48000))

    assert captured["sample_count"] == WHISPER_SAMPLE_RATE
    assert result.text == "Hello, hello, can you hear me?"


@pytest.mark.anyio
async def test_local_whisper_transcriber_rejects_too_short_recording(tmp_path):
    artifact = tmp_path / "audio.pcm"
    _write_pcm(artifact, sample_count=24)
    transcriber = LocalWhisperTranscriber()
    transcriber._import_error = None
    transcriber._model = FakeWhisperModel(segments=[], captured={})

    with pytest.raises(RuntimeError, match="too short"):
        await transcriber.transcribe(_audio_instruction(str(artifact), sample_count=24))
