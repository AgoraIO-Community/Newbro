# Newbro Push-To-Talk Audio With Executor-Node Whisper Spec

## Goal

Make Bro Detail composer push-to-talk audio client-agnostic. Browser, mobile,
Agora gateway, and future clients may upload raw recorded audio to Newbro. The
selected Bro's bound executor node owns local Whisper transcription, then sends
the transcript as a normal text follow-up to the active executor session.

Codex is the first adapter to be changed to this design. Codex must no longer
depend on native realtime audio ingestion for PTT. Hermes and future adapters
can participate by supporting text follow-up; they do not need native raw audio
support.

## Product Decisions

- Clients send raw audio and do not run STT.
- Executor nodes transcribe with local Whisper by default when audio
  dependencies are installed.
- `newbro-cli` includes the local Whisper runtime dependencies so a downloaded
  CLI can run composer PTT audio without an extra audio extra install.
- Whisper language defaults to automatic detection; executor run commands can
  override language and model inline.
- UI renders the audio bubble immediately and adds the transcript under that
  bubble after executor-node Whisper succeeds.
- Agents receive transcript text follow-ups, not PCM.
- Codex PTT uses the normal text instruction path, not Codex realtime audio.
- Hermes support should use the same node-level Whisper path once a Hermes
  adapter exists.
- The composer PTT path still does not create/update a Draft and still does not
  require Send/Confirm.
- Agora live/free voice remains separate from composer PTT.

## Source Of Truth

- `AGENTS.md`
- `docs/architecture/communication-brain.md`
- `docs/architecture/executors.md`
- `docs/protocol/draft-to-execute.md`
- `docs/guides/frontend-workbench.md`
- `src/newbro/protocol/executor_node.py`
- `src/newbro/runtime/session.py`
- `src/newbro/runtime/executor_node_manager.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/executors/node/config.py`
- `src/newbro/executors/adapters/codex/`
- `src/newbro/api/routes/executor_audio.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`

## In Scope

- Executor-node local Whisper transcription service for uploaded PCM audio.
- Executor-node capability advertisement for audio instructions based on:
  - executor supports text follow-up
  - local audio transcriber is available
  - or future native audio support is explicitly implemented
- Typed protocol model for text instructions produced from audio.
- Codex adapter text-follow-up handler for transcribed audio.
- Remove Codex realtime-audio/API-key-auth gating from the PTT path.
- Config support for local Whisper model/language/device settings.
- CLI support for inline Whisper language/model overrides on executor-node
  runs.
- UI disabled copy that points to local Whisper on the executor node instead of
  Codex API-key realtime audio.
- UI audio transcript display under the original voice-note bubble after the
  node reports a successful transcription.
- Tests for node transcription dispatch and Codex text follow-up.
- Stable docs and `docs/memories.md` updates.

## Non-Goals

- Do not implement a Hermes adapter in this goal.
- Do not make clients depend on Whisper, ffmpeg, or provider-specific STT.
- Do not use Agora STT/ConvoAI/RTC/RTM for composer PTT.
- Do not create/update Drafts from composer PTT.
- Do not require Send/Confirm for composer PTT.
- Do not render the transcript as a separate user chat turn; it belongs under
  the original voice-note bubble.
- Do not keep the Codex realtime audio path as the primary PTT implementation.

## Architecture

```text
client/gateway raw audio
  -> Newbro upload API
  -> typed ExecutorAudioInstruction
  -> selected Bro's executor node
  -> local Whisper transcription
  -> typed ExecutorTextInstruction
  -> Codex/Hermes/future adapter text follow-up
```

The upload API remains transport-thin. It validates auth, selected Bro, bound
node, active execution session, MIME, duration, and size, then dispatches the
typed audio instruction to the node. It must not transcribe.

The executor node owns local audio semantics. `supports_audio_instruction=True`
means the node can accept raw audio and deliver a text instruction to the active
executor, either through local Whisper plus text follow-up or through explicit
future native audio support.

Codex owns only text follow-up. It receives `ExecutorTextInstruction` and starts
a normal Codex text turn in the existing thread.

The UI owns voice-note presentation. It creates the voice-note bubble before the
upload completes, then patches the transcript under that same bubble from the
executor run progress metadata once local Whisper finishes.

## Edge Cases

- Local Whisper dependencies missing: node advertises no audio instruction
  support; UI disables PTT before recording.
- Whisper returns empty transcript: node emits a failed run event and does not
  call the adapter.
- Node disconnects while recording/uploading: API rejects or dispatch fails.
- Active Codex run/session is missing: API rejects before artifact dispatch.
- Upload too large or too long: API rejects with existing limits.
- Unsupported MIME: API rejects before node dispatch.

## Verification

Required backend checks:

- `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py`
- `.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py`
- `.venv/bin/python -m pytest`

Required frontend checks:

- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Manual checks:

- Connected node with local Whisper available advertises audio support.
- Connected node without local Whisper disables composer PTT before recording.
- Desktop and mobile PTT work end to end: hold/release records audio, uploads
  exactly one instruction, the executor node transcribes it with local Whisper,
  Codex receives the transcript as a text follow-up, Codex visibly acts on it,
  and the UI renders the audio bubble followed by its transcript.
- `newbro executor run --audio-language ... --whisper-model ...` overrides the
  automatic language/default model settings for the executor node.
- Capture a browser screenshot and relevant log artifact as proof for the E2E
  PTT audio smoke.
- No composer PTT call uses Agora, Draft ASR, Draft Send, or Codex realtime
  audio.

## Done When

- `GOAL.md` describes the executor-node Whisper contract and measurable
  completion criteria.
- Protocol includes typed audio and text instruction models.
- Executor node transcribes `ExecutorAudioInstruction` with local Whisper and
  forwards `ExecutorTextInstruction` to adapters.
- Codex handles transcribed PTT as a text follow-up and no longer gates PTT on
  Codex realtime audio/API-key auth.
- UI disabled state references local Whisper executor-node readiness.
- UI shows the voice-note bubble first and its transcript underneath after
  Whisper transcription succeeds.
- Tests and stable docs are updated for the adopted design.
- The goal is not complete until a real end-to-end push-to-talk audio check
  works with local Whisper, a connected executor node, and an active Codex task.
