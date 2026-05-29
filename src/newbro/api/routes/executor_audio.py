from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query, Request

from newbro.api.public_auth import require_session_owner

router = APIRouter()

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_AUDIO_DURATION_MS = 60_000
ALLOWED_AUDIO_MIME_TYPES = {"audio/pcm", "audio/x-pcm", "application/octet-stream"}


class ExecutorAudioInstructionResponse(BaseModel):
    audio_instruction_id: str
    target_persona_id: str
    target_thread_id: str | None = None
    status: str
    duration_ms: int
    size_bytes: int
    transcript_text: str | None = None


@router.post(
    "/sessions/{session_id}/executor-audio-instructions",
    response_model=ExecutorAudioInstructionResponse,
)
async def submit_executor_audio_instruction(
    session_id: str,
    request: Request,
    target_persona_id: str = Query(min_length=1),
    target_thread_id: str | None = Query(default=None, min_length=1),
    create_new_thread: bool = Query(default=False),
    client_request_id: str | None = Query(default=None, min_length=1),
    duration_ms: int = Query(gt=0, le=MAX_AUDIO_DURATION_MS),
    sample_rate: int = Query(ge=8000, le=96000),
    num_channels: int = Query(ge=1, le=2),
    samples_per_channel: int = Query(gt=0),
) -> ExecutorAudioInstructionResponse:
    await require_session_owner(request, session_id)
    mime_type = _normalize_content_type(request.headers.get("content-type"))
    if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio MIME type.")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Audio body is empty.")
    if len(body) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio body exceeds 25 MB.")
    expected_duration_ms = round((samples_per_channel / sample_rate) * 1000)
    if abs(expected_duration_ms - duration_ms) > 1500:
        raise HTTPException(status_code=400, detail="Audio duration metadata does not match sample count.")

    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        audio = await session.submit_executor_audio_instruction(
            target_persona_id=target_persona_id,
            target_thread_id=target_thread_id,
            create_new_thread=create_new_thread,
            client_request_id=client_request_id,
            pcm16=body,
            mime_type=mime_type,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ExecutorAudioInstructionResponse(
        audio_instruction_id=audio.audio_instruction_id,
        target_persona_id=audio.target_persona_id,
        target_thread_id=audio.target_thread_id,
        status="accepted",
        duration_ms=audio.duration_ms,
        size_bytes=audio.size_bytes,
        transcript_text=audio.metadata.get("transcript_text")
        if isinstance(audio.metadata.get("transcript_text"), str)
        else None,
    )


def _normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()
