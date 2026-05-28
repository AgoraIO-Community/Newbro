from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import math
from typing import Any, Protocol

from newbro.protocol import ExecutorAudioInstruction

WHISPER_SAMPLE_RATE = 16000


@dataclass(slots=True)
class AudioTranscriptionResult:
    text: str
    language: str | None = None
    duration_seconds: float | None = None
    metadata: dict[str, object] | None = None


class AudioTranscriber(Protocol):
    @property
    def available(self) -> bool:
        ...

    async def transcribe(self, audio: ExecutorAudioInstruction) -> AudioTranscriptionResult:
        ...


class DisabledAudioTranscriber:
    @property
    def available(self) -> bool:
        return False

    async def transcribe(self, audio: ExecutorAudioInstruction) -> AudioTranscriptionResult:
        raise RuntimeError("Local Whisper transcription is not available on this executor node.")


class LocalWhisperTranscriber:
    def __init__(
        self,
        *,
        model: str = "base",
        language: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: str | None = None,
    ) -> None:
        self._model_name = model or "base"
        self._language = None if language in (None, "", "auto") else language
        self._device = device or "cpu"
        self._compute_type = compute_type or "int8"
        self._download_root = download_root
        self._model: Any | None = None
        self._import_error: Exception | None = None
        try:
            import faster_whisper  # noqa: F401
            import numpy  # noqa: F401
        except Exception as exc:
            self._import_error = exc

    @property
    def available(self) -> bool:
        return self._import_error is None

    async def transcribe(self, audio: ExecutorAudioInstruction) -> AudioTranscriptionResult:
        if self._import_error is not None:
            raise RuntimeError(
                "Local Whisper transcription requires faster-whisper and numpy. "
                "Install Newbro audio dependencies on the executor node."
            ) from self._import_error

        import anyio
        import numpy as np

        raw = _decode_pcm16_content(audio)
        if not raw:
            raise RuntimeError("Audio content is empty.")
        if len(raw) % 2 != 0:
            raw = raw[:-1]
        pcm = np.frombuffer(raw, dtype=np.int16)
        if audio.num_channels > 1:
            usable = (pcm.size // audio.num_channels) * audio.num_channels
            pcm = pcm[:usable].reshape(-1, audio.num_channels).mean(axis=1).astype(np.int16)
        signal_stats = _pcm_signal_stats(pcm, sample_rate=audio.sample_rate)
        if signal_stats["duration_seconds"] < 0.25:
            raise RuntimeError("Audio recording is too short to transcribe.")
        samples = pcm.astype(np.float32) / 32768.0
        samples = _resample_audio(samples, source_sample_rate=audio.sample_rate, target_sample_rate=WHISPER_SAMPLE_RATE)

        def _run() -> AudioTranscriptionResult:
            model = self._ensure_model()
            segments, info = model.transcribe(
                samples,
                language=self._language,
                beam_size=5,
                condition_on_previous_text=False,
                hallucination_silence_threshold=1.0,
                no_repeat_ngram_size=3,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 500,
                    "speech_pad_ms": 200,
                },
            )
            segment_list = list(segments)
            accepted_segments = [
                segment
                for segment in segment_list
                if segment.text.strip()
                and not (
                    getattr(segment, "no_speech_prob", 0.0) >= 0.8
                    and getattr(segment, "avg_logprob", 0.0) < -0.5
                )
            ]
            text = " ".join(segment.text.strip() for segment in accepted_segments).strip()
            if not text:
                raise RuntimeError("No clear speech was detected in the recording.")
            return AudioTranscriptionResult(
                text=text,
                language=getattr(info, "language", None),
                duration_seconds=getattr(info, "duration", None),
                metadata={
                    "whisper_model": self._model_name,
                    "language_probability": getattr(info, "language_probability", None),
                    "audio_peak": signal_stats["peak"],
                    "audio_rms": signal_stats["rms"],
                    "audio_rms_norm": signal_stats["rms_norm"],
                    "whisper_segment_count": len(segment_list),
                    "whisper_accepted_segment_count": len(accepted_segments),
                },
            )

        return await anyio.to_thread.run_sync(_run)

    def _ensure_model(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            kwargs: dict[str, object] = {
                "device": self._device,
                "compute_type": self._compute_type,
            }
            if self._download_root:
                kwargs["download_root"] = self._download_root
            self._model = WhisperModel(self._model_name, **kwargs)
        return self._model


def build_audio_transcriber(config: dict[str, Any] | None) -> AudioTranscriber:
    raw = config or {}
    transcription = raw.get("transcription") if isinstance(raw, dict) else None
    if transcription is None:
        transcription = {}
    if not isinstance(transcription, dict):
        return DisabledAudioTranscriber()
    provider = str(transcription.get("provider", "local_whisper"))
    if provider in {"", "none", "disabled"}:
        return DisabledAudioTranscriber()
    if provider != "local_whisper":
        return DisabledAudioTranscriber()
    return LocalWhisperTranscriber(
        model=str(transcription.get("model", "base")),
        language=_optional_string(transcription.get("language")),
        device=str(transcription.get("device", "cpu")),
        compute_type=str(transcription.get("compute_type", "int8")),
        download_root=_optional_string(transcription.get("download_root")),
    )


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _decode_pcm16_content(audio: ExecutorAudioInstruction) -> bytes:
    try:
        return base64.b64decode(audio.pcm16_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("Audio content payload is invalid.") from exc


def _pcm_signal_stats(pcm: Any, *, sample_rate: int) -> dict[str, float]:
    sample_count = int(getattr(pcm, "size", 0) or 0)
    if sample_count <= 0:
        return {"duration_seconds": 0.0, "peak": 0.0, "rms": 0.0, "rms_norm": 0.0}
    peak = float(max(abs(int(value)) for value in pcm))
    rms = math.sqrt(sum(float(value) * float(value) for value in pcm) / sample_count)
    return {
        "duration_seconds": sample_count / max(sample_rate, 1),
        "peak": peak,
        "rms": rms,
        "rms_norm": rms / 32768.0,
    }


def _resample_audio(samples: Any, *, source_sample_rate: int, target_sample_rate: int) -> Any:
    if source_sample_rate == target_sample_rate:
        return samples
    import numpy as np

    sample_count = int(getattr(samples, "size", 0) or 0)
    if sample_count <= 1:
        return samples
    target_count = max(1, round(sample_count * target_sample_rate / max(source_sample_rate, 1)))
    source_positions = np.linspace(0, sample_count - 1, num=sample_count, dtype=np.float64)
    target_positions = np.linspace(0, sample_count - 1, num=target_count, dtype=np.float64)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)
