<goal>
Fix Bro Detail push-to-talk audio for a remote Newbro backend and local Codex executor node. Browser-uploaded audio must be carried as command content over the existing authenticated executor-node websocket path. The executor node must transcribe from that content, not from a backend-local filesystem path. Valid uploaded audio must no longer fail with `Audio artifact is not available for transcription.` when the backend and executor do not share a filesystem.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `docs/architecture/executors.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/guides/frontend-workbench.md`

Implementation files to inspect:
- `src/newbro/protocol/executor_node.py`
- `src/newbro/runtime/session.py`
- `src/newbro/runtime/executor_node_manager.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/executors/node/audio.py`
- `src/newbro/api/routes/executor_audio.py`
- `src/newbro/api/ws/executors.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/lib/session-client.ts`

Tests to inspect:
- `tests/unit/executors/node/test_audio.py`
- `tests/unit/executors/node/test_service.py`
- `tests/integration/api/test_executor_audio.py`
- `tests/integration/api/test_executor_text.py`

Useful discovery commands:
- `rg -n "ExecutorAudioInstruction|TranscribeAudioInstructionCommand|DispatchAudioInstructionCommand|audio_instruction|transcribe_audio_instruction|dispatch_audio_instruction" src/newbro tests`
- `rg -n "Audio artifact is not available for transcription|Audio artifact is empty|too short|executor-audio-instructions" src/newbro tests`
</context>

<constraints>
- Backend and executor node must not need a shared filesystem.
- Use the existing backend-to-executor websocket control channel for audio transfer.
- Do not send `artifact_path` in browser-uploaded push-to-talk executor commands.
- Do not add a compatibility fallback to backend-local audio paths.
- Keep local Whisper transcription on the executor node; do not move transcription to the backend.
- Keep the browser upload endpoint and frontend recording UX.
- Cover both idle Bro PTT (`transcribe_audio_instruction`) and active-run PTT (`dispatch_audio_instruction`).
- Keep protocol models typed and multi-executor compatible.
- Preserve Communication Brain, Draft Brain, Agora, and connector voice behavior.
- Do not add browser polling, browser-to-executor direct upload, or an inbound HTTP server requirement on the local executor node.
- Local simulated end-to-end verification is sufficient; do not require a real VPS deployment for this goal.
- Preserve unrelated user changes in the worktree.
- Update stable docs and `docs/memories.md` because this is an adopted runtime behavior change.
</constraints>

<done_when>
- `ExecutorAudioInstruction` carries audio content in a JSON-safe form, recommended as base64 PCM bytes or an equivalent typed payload, with existing audio metadata.
- Backend still accepts browser audio upload at `/executor-audio-instructions`, validates it as before, and sends audio content to the executor node without relying on shared filesystem access.
- Browser-uploaded push-to-talk executor commands do not include or require `artifact_path`.
- Executor-node transcription decodes transferred audio content from the command.
- Local executor node can transcribe valid audio when the backend-local temp audio file is not readable by the executor.
- Idle Bro PTT transcription uses transferred audio content through `TranscribeAudioInstructionCommand`.
- Active-run PTT follow-up uses transferred audio content through `DispatchAudioInstructionCommand`.
- The UI/backend no longer shows `Audio artifact is not available for transcription.` for valid uploaded audio when backend and executor do not share a filesystem.
- Tests cover audio-content command payloads with no `artifact_path` for `transcribe_audio_instruction`.
- Tests cover audio-content command payloads with no `artifact_path` for `dispatch_audio_instruction`.
- Existing validation still rejects empty audio, too-short audio, unsupported MIME type, oversized body, malformed transferred payload, and unavailable Whisper.
- `.venv/bin/python -m pytest tests/unit/executors/node/test_audio.py` passes.
- `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py` passes.
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py` passes.
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py` passes.
- Local simulated end-to-end verification confirms browser-uploaded audio reaches executor transcription as command content and no `artifact_path` is sent.
- Stable docs and `docs/memories.md` document that executor audio is transported over the executor-node command path and does not require a shared filesystem.
</done_when>

<workflow>
1. Check `git status --short` and identify unrelated dirty files before editing.
2. Read `SPEC.md`, `AGENTS.md`, and the stable executor/session/frontend docs listed in context.
3. Inspect the current audio upload route, runtime audio instruction construction, executor-node manager command serialization, executor-node transcription service, and tests.
4. Update `ExecutorAudioInstruction` with a typed JSON-safe audio content payload field. Prefer a concise name such as `audio_b64` or `pcm16_b64`; keep existing metadata fields.
5. Remove `artifact_path` from the browser-uploaded audio executor command contract and related runtime construction.
6. Update backend runtime audio instruction creation so uploaded PCM bytes are included in the executor command payload.
7. Update executor-node audio transcription to decode and transcribe bytes from the transferred payload.
8. Ensure malformed transferred payloads fail clearly and do not surface an unrelated missing-file error.
9. Verify both executor-node paths use the same audio content source: `_transcribe_audio_instruction` for idle Bro PTT and `_dispatch_audio_instruction` for active-run PTT.
10. Add focused unit/integration tests proving idle and active-run command payloads include audio content and no `artifact_path`.
11. Add or update tests for malformed payload and existing validation behavior if coverage is missing.
12. Update stable docs and append a short factual note to `docs/memories.md`.
13. Run focused tests first. Run broader tests if the protocol or runtime changes have wider blast radius.
14. Perform a final diff review to confirm there is no shared-filesystem dependency, no path fallback, no Communication Brain change, no frontend polling, and no unrelated refactor.
</workflow>

<verification_loop>
Focused commands:
- `.venv/bin/python -m pytest tests/unit/executors/node/test_audio.py`
- `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py`

Optional broad command:
- `.venv/bin/python -m pytest`

Local simulated end-to-end verification:
1. Start the backend and frontend locally, or use an integration harness that exercises the same API/runtime/executor-node command path.
2. Submit valid PCM audio through `/api/sessions/{session_id}/executor-audio-instructions`.
3. Confirm the serialized `TranscribeAudioInstructionCommand` contains audio content and no `artifact_path`.
4. Confirm the executor node decodes the command content and produces a transcript for idle Bro PTT.
5. While a Codex run is active, submit valid PCM audio again.
6. Confirm the serialized `DispatchAudioInstructionCommand` contains audio content and no `artifact_path`.
7. Confirm active-run audio follow-up transcribes and is delivered as text to the active Codex thread.
8. Confirm no UI or backend failure says `Audio artifact is not available for transcription.`

If local simulated end-to-end verification cannot be run, document the exact missing environment, the automated tests that cover the same command path, and residual risk.
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
- Summary of the protocol/runtime change that carries audio content to the executor node.
- Summary of idle PTT and active-run PTT behavior after the fix.
- Verification commands run and outcomes.
- Local simulated end-to-end verification result.
- Explicit note that local Whisper remains on the executor node and no shared filesystem is required.
- Any skipped checks or residual risks.
</output_contract>
