<goal>
Implement Newbro push-to-talk audio as executor-node local Whisper transcription followed by normal text follow-up delivery. Clients and gateways upload raw audio only; the selected Bro's executor node transcribes with local Whisper and sends a typed text instruction to Codex or future text-follow-up adapters. Codex must no longer depend on native realtime audio ingestion or API-key realtime auth for composer PTT.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `docs/architecture/communication-brain.md`
- `docs/architecture/executors.md`
- `docs/protocol/draft-to-execute.md`
- `docs/guides/frontend-workbench.md`

Implementation files:
- `src/newbro/protocol/executor_node.py`
- `src/newbro/protocol/__init__.py`
- `src/newbro/runtime/session.py`
- `src/newbro/runtime/executor_node_manager.py`
- `src/newbro/api/routes/executor_audio.py`
- `src/newbro/executors/node/config.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/executors/node/audio.py`
- `src/newbro/executors/core/executor.py`
- `src/newbro/executors/adapters/codex/client.py`
- `src/newbro/executors/adapters/codex/executor.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`
- `pyproject.toml`

Useful discovery commands:
- `rg -n "supports_audio_instruction|ExecutorAudioInstruction|ExecutorTextInstruction|handle_audio_instruction|handle_text_instruction" src tests docs`
- `rg -n "realtime|appendAudio|API-key|Whisper|transcription" src tests docs SPEC.md GOAL.md`
- `rg -n "executor-audio-instructions|submit_executor_audio_instruction" src tests`
</context>

<constraints>
- Clients and gateways must not run STT for composer PTT.
- Composer PTT must not use Agora RTC, RTM, ConvoAI, Agora STT, connector prepare/activate, Draft ASR, or Draft Send.
- Composer PTT must not create/update Drafts and must not require Send/Confirm.
- The Newbro API upload route stays transport-thin and must not transcribe.
- Local Whisper transcription belongs to the detached executor node.
- `newbro-cli` must include local Whisper runtime dependencies in its default
  install so users can run executor-node PTT audio directly after downloading.
- Codex PTT must use a normal text follow-up instruction generated from transcription; do not use Codex realtime audio as the primary path.
- Whisper language defaults to auto-detect; executor-node inline args can
  override language and model for a run.
- The UI must show the audio bubble first, then add the transcript under that
  bubble after executor-node Whisper transcription succeeds.
- Hermes is not implemented in this goal, but the protocol must remain compatible with a future Hermes adapter that supports text follow-up.
- `supports_audio_instruction=True` means the connected node can accept raw audio and deliver a usable executor instruction, not necessarily that the downstream adapter natively accepts PCM.
- If local Whisper dependencies are missing, the node must advertise no audio support and the UI must block recording before microphone capture.
- Keep protocol models typed; avoid ad hoc untyped blobs.
- Preserve existing typed PTT text behavior.
- Preserve unrelated user changes, especially `AGENTS.md`.
- Update stable docs and `docs/memories.md` because this changes adopted runtime behavior.
</constraints>

<done_when>
- `SPEC.md` and `GOAL.md` describe the executor-node Whisper design with concrete verification criteria.
- `src/newbro/protocol/executor_node.py` defines typed audio and text instruction models.
- `src/newbro/executors/node/audio.py` provides local Whisper transcription for PCM audio artifacts, with a disabled/unavailable path when dependencies are missing.
- `src/newbro/executors/node/config.py` loads executor-node audio transcription config such as provider/model/language.
- `newbro executor run` and generated connect commands expose inline Whisper
  language/model overrides while keeping auto language as the default.
- `src/newbro/executors/node/service.py` advertises audio capability when local Whisper plus text follow-up is available, transcribes audio instructions on the node, and forwards typed text instructions to the active adapter.
- `src/newbro/executors/adapters/codex/executor.py` handles transcribed audio as a text follow-up to the existing Codex thread and no longer probes or requires Codex realtime audio support for PTT.
- `src/newbro/executors/adapters/codex/client.py` no longer exposes unused realtime-audio helpers for this PTT path.
- UI disabled copy in `src/newbro/ui/src/ArtboardShell.tsx` points to local Whisper executor-node readiness rather than Codex API-key realtime auth.
- UI renders the voice-note bubble immediately and patches the transcript below
  it from executor progress metadata after Whisper succeeds.
- Existing upload validation still rejects unsupported MIME, missing connected node, missing active Codex run, missing node audio support, duration > 60 seconds, and size > 25 MB.
- Focused tests prove executor-node audio dispatch transcribes then sends text, Codex sends text follow-up, and UI disabled state matches the new contract.
- A real end-to-end push-to-talk audio check works: with local Whisper dependencies installed, a connected executor node, and an active Codex task, holding and releasing the Bro Detail composer mic records audio, uploads exactly one instruction, transcribes it on the executor node, shows the transcript under the audio bubble, sends the transcript to Codex as a text follow-up, and Codex visibly acts on it.
- Browser screenshot and relevant log artifact are captured as proof for the E2E
  PTT audio check.
- `.venv/bin/python -m pytest` passes.
- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx` passes.
- `cd src/newbro/ui && bun run test` passes.
- `cd src/newbro/ui && bun run build` passes.
- Stable docs and `docs/memories.md` document that composer PTT now uses executor-node local Whisper transcription before text follow-up.
</done_when>

<workflow>
1. Check git status and preserve unrelated changes.
2. Read `SPEC.md`, `AGENTS.md`, and stable docs before implementation.
3. Inspect existing raw-audio PTT upload, executor-node dispatch, Codex adapter, and UI capability gating.
4. Add/adjust typed protocol models for audio input and text instruction output.
5. Add executor-node audio transcription support with local Whisper as the default provider and explicit unavailable behavior when dependencies are missing.
6. Change executor-node capability advertising so local Whisper plus text follow-up enables audio instructions.
7. Change executor-node dispatch so audio is transcribed before adapter delivery; emit failed run events on empty transcript or missing transcriber.
8. Change Codex to handle `ExecutorTextInstruction` and remove Codex realtime-audio dependency from PTT.
9. Update UI copy/tests for local Whisper readiness.
10. Update `SPEC.md`, `GOAL.md`, stable docs, and `docs/memories.md`.
11. Run focused tests, then full backend and frontend verification.
12. Review final diff for stale realtime-audio/API-key language, untyped shortcuts, and accidental Draft/Agora usage.
</workflow>

<verification_loop>
Focused backend tests:
- `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py`
- `.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py`
- `.venv/bin/python -m pytest tests/unit/executors/node/test_config_loader.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py`

Full backend:
- `.venv/bin/python -m pytest`

Frontend:
- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Manual checks:
- Start a node with local Whisper dependencies installed and confirm connected Codex advertises `supports_audio_instruction=true`.
- Start a node without local Whisper dependencies and confirm composer PTT is disabled before recording.
- Verify desktop and mobile PTT end to end: hold/release records audio, uploads exactly one instruction, node transcription succeeds, Codex receives the transcript as a text follow-up, and the UI shows the audio bubble followed by the transcript without using Draft Send.
- Confirm generated executor run commands support `--audio-language` and
  `--whisper-model`, with language omitted/defaulting to auto when not set.
- Inspect calls/logs to confirm composer PTT does not call Agora, Draft ASR, Draft Send, or Codex realtime audio.

If any check cannot run, document why, what was run instead, and the residual risk.
</verification_loop>

<execution_rules>
- Check git status before edits.
- Preserve unrelated user changes.
- Prefer `rg` over `grep` when available.
- Use `apply_patch` for manual file edits.
- Read context files before implementation.
- Batch independent file reads in parallel when available.
- Run focused tests before broad tests.
- Do not paper over failures.
- Do not widen scope.
- Keep the final answer concise.
- Follow repo guardrails from `AGENTS.md`: preserve Communication Brain and Execution Brain separation, keep transport thin, treat protocol models as source of truth, diagnose from real state, test the failure mode, verify activation, and update memory deliberately.
</execution_rules>

<output_contract>
Final output must include:
- Summary of the executor-node Whisper PTT behavior.
- Summary of protocol, executor-node, Codex, UI, test, and doc changes.
- Verification commands run and outcomes.
- Explicit end-to-end push-to-talk audio evidence, including a browser
  screenshot/log artifact, before marking the goal complete.
- Any skipped checks or residual risks, especially whether local Whisper dependencies were installed for a real manual smoke.
</output_contract>
