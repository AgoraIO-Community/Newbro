from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from newbro.protocol import ExecutorAudioInstruction


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

        artifact = Path(audio.artifact_path)
        if not artifact.is_file():
            raise RuntimeError("Audio artifact is not available for transcription.")
        raw = artifact.read_bytes()
        if not raw:
            raise RuntimeError("Audio artifact is empty.")
        if len(raw) % 2 != 0:
            raw = raw[:-1]
        pcm = np.frombuffer(raw, dtype=np.int16)
        if audio.num_channels > 1:
            usable = (pcm.size // audio.num_channels) * audio.num_channels
            pcm = pcm[:usable].reshape(-1, audio.num_channels).mean(axis=1).astype(np.int16)
        samples = pcm.astype(np.float32) / 32768.0

        def _run() -> AudioTranscriptionResult:
            model = self._ensure_model()
            segments, info = model.transcribe(
                samples,
                language=self._language,
                beam_size=5,
            )
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
            return AudioTranscriptionResult(
                text=text,
                language=getattr(info, "language", None),
                duration_seconds=getattr(info, "duration", None),
                metadata={
                    "whisper_model": self._model_name,
                    "language_probability": getattr(info, "language_probability", None),
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
