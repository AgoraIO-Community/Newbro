# Newbro Audio Content Transport Spec

## Goal

Fix Bro Detail push-to-talk audio when the Newbro backend is remote and the
Codex executor node runs on the user's local machine.

Newbro must stop treating backend-local audio files as executor-readable state.
Browser-recorded audio must be transmitted to the executor node as command
content over the existing authenticated executor-node websocket path. The
executor node should transcribe from the transferred content, not from a
filesystem path supplied by the backend.

The user-visible regression being fixed is:

```text
Audio artifact is not available for transcription.
```

That failure currently happens because the backend writes a temp PCM file on
the backend host and sends that host-local path to the local executor. The
local executor cannot read that file.

## Product Decisions

- The Codex executor node is local; the Newbro backend may be remote.
- Audio transfer must not require a shared filesystem between backend and
  executor node.
- Use the existing backend-to-executor websocket control channel to carry audio
  content for transcription.
- Do not send an `artifact_path` for browser-uploaded push-to-talk audio.
- Do not add a compatibility fallback to backend-local audio paths.
- Keep the existing browser upload endpoint and frontend recording UX.
- Keep local Whisper transcription on the executor node; do not move
  transcription to the backend.
- The fix must cover both idle Bro PTT and active-run PTT follow-up.
- Local simulated end-to-end verification is sufficient; no real VPS deployment
  is required for this goal.

## Source Of Truth

Read first:

- `AGENTS.md`
- `docs/architecture/executors.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/guides/frontend-workbench.md`
- `src/newbro/protocol/executor_node.py`
- `src/newbro/runtime/session.py`
- `src/newbro/runtime/executor_node_manager.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/executors/node/audio.py`
- `src/newbro/api/routes/executor_audio.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/lib/session-client.ts`

Useful discovery commands:

```bash
rg -n "ExecutorAudioInstruction|TranscribeAudioInstructionCommand|DispatchAudioInstructionCommand|audio_instruction|transcribe_audio_instruction|dispatch_audio_instruction" src/newbro tests
rg -n "Audio artifact is not available for transcription|Audio artifact is empty|too short|executor-audio-instructions" src/newbro tests
```

## Current Behavior

- Browser records PCM audio and POSTs it to
  `/api/sessions/{session_id}/executor-audio-instructions`.
- Backend validates the body and writes it to a backend-local temp file.
- Backend builds `ExecutorAudioInstruction` with a backend-local file path.
- For idle Bro PTT, backend sends `TranscribeAudioInstructionCommand` to the
  executor node and waits for an `AudioInstructionTranscribedMessage`.
- For active-run PTT, backend sends `DispatchAudioInstructionCommand` to the
  executor node.
- Executor node transcription reads the path from the command.
- If backend is remote and executor is local, that path does not exist locally,
  causing `Audio artifact is not available for transcription.`

## Required Behavior

- `ExecutorAudioInstruction` carries a JSON-safe audio content payload,
  recommended as base64-encoded PCM bytes, alongside typed metadata such as MIME
  type, sample rate, channel count, sample count, duration, and size.
- Browser-uploaded push-to-talk audio commands do not include or require
  `artifact_path`.
- Executor-node transcription decodes audio content from the command and
  transcribes those bytes.
- Idle Bro PTT (`transcribe_audio_instruction`) works without any
  executor-readable audio file path.
- Active-run PTT (`dispatch_audio_instruction`) works without any
  executor-readable audio file path.
- Valid uploaded audio must not surface `Audio artifact is not available for
  transcription.`
- Empty, malformed, too-short, unsupported, or oversized audio still fails with
  clear validation or transcription errors.

## In Scope

- Protocol update for executor audio instructions.
- Backend runtime update to include audio content in executor-node commands.
- Executor-node transcription update to consume transferred audio content.
- Tests proving command payloads contain audio content and no path.
- Tests for idle Bro PTT and active-run PTT.
- Docs and memory updates because this changes deployed runtime behavior.
- Local simulated end-to-end verification of browser upload through executor
  transcription.

## Non-Goals

- Do not redesign push-to-talk UI.
- Do not replace local Whisper with server-side transcription.
- Do not require the local executor node to expose an inbound HTTP server.
- Do not add browser-to-executor direct upload.
- Do not change Communication Brain, Draft Brain, Agora, or connector voice
  behavior.
- Do not introduce polling.
- Do not deploy to a VPS as part of verification.

## Edge Cases

- Audio content is missing from the executor command: fail with a clear invalid
  audio payload error.
- Audio content is present but empty: fail as empty audio.
- Audio content is malformed base64: fail with a clear invalid audio payload
  error.
- Audio payload size exceeds the already-enforced backend upload limit: reject
  at the HTTP route as today.
- Executor node disconnects during transcription: existing request timeout /
  disconnect behavior should remain.
- Whisper dependencies unavailable on the executor node: keep the existing
  unavailable-Whisper error.
- Multiple local executor nodes or future remote nodes: protocol must stay
  node-agnostic and multi-executor compatible.

## Verification

Backend/unit checks:

```bash
.venv/bin/python -m pytest tests/unit/executors/node/test_audio.py
.venv/bin/python -m pytest tests/unit/executors/node/test_service.py
.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py
```

Optional broader check:

```bash
.venv/bin/python -m pytest
```

Local simulated end-to-end check:

1. Start the backend and frontend locally, or use an integration harness that
   exercises the same API/runtime/executor-node command path.
2. Submit valid PCM audio through
   `/api/sessions/{session_id}/executor-audio-instructions`.
3. Confirm the serialized `TranscribeAudioInstructionCommand` contains audio
   content and no `artifact_path`.
4. Confirm the executor node decodes the command content and produces a
   transcript for idle Bro PTT.
5. While a Codex run is active, submit valid PCM audio again.
6. Confirm the serialized `DispatchAudioInstructionCommand` contains audio
   content and no `artifact_path`.
7. Confirm active-run audio follow-up transcribes and is delivered as text to
   the active Codex thread.
8. Confirm no UI or backend failure says `Audio artifact is not available for
   transcription.`

## Done When

- `ExecutorAudioInstruction` carries audio content, likely base64 PCM bytes or
  equivalent JSON-safe bytes, with typed metadata.
- Browser-uploaded push-to-talk commands do not include or require
  `artifact_path`.
- Backend still accepts browser audio upload at
  `/executor-audio-instructions`, but executor-node transcription no longer
  requires shared filesystem access.
- Local executor node can transcribe audio when the backend-local temp audio
  file is not readable by the executor.
- Both idle PTT transcription and active-run audio follow-up use the transferred
  audio content.
- The old failure `Audio artifact is not available for transcription.` is not
  shown when valid audio bytes were uploaded.
- Tests cover audio-content command payloads with no `artifact_path` for
  `transcribe_audio_instruction`.
- Tests cover audio-content command payloads with no `artifact_path` for
  `dispatch_audio_instruction`.
- Existing validation still rejects empty audio, too-short audio, unsupported
  MIME type, oversized body, malformed transferred payload, and unavailable
  Whisper.
- Required backend/unit checks listed above pass.
- Local simulated end-to-end verification is completed successfully or
  documented with the exact blocker and residual risk.
- Stable docs and `docs/memories.md` document that executor audio is
  transported over the executor-node command path and does not require a shared
  filesystem.
