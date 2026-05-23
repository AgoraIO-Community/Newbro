<goal>
Implement the Newbro V1 ConvoAI live interaction loop from the discussed design: run the Communication Brain interaction classifier on the latest transcript snapshot at an approximately 1 second cadence, maintain provisional live draft state, update the same active draft revision silently as the user speaks or corrects themselves, and make finality/session-close only a stabilization checkpoint rather than the source of truth for responsiveness.

The deliverable is a working, tested, documented runtime path where:
- live transcript snapshots can drive classifier updates without waiting for `/chat/completions` coalesced final turns
- delegation and draft-correction classifications update one active live draft instead of appending many durable ASR turns
- explicit send/confirmation freezes an exact draft revision and dispatches only that revision through the normal dispatch gate
- `should_speak` remains driven by structured classifier/runtime state, not transcript keyword rules
- the Bro detail page target remains authoritative, with no persona-pick flow in the voice path
</goal>

<context>
Read first:
- docs/rfcs/0013-newbro-v1.md sections 9.1, 11.2, 11.3, 14.2, 14.3, 18.2, 18.3, 19.2, and 21.2.
- docs/architecture/communication-brain.md
- docs/protocol/draft-to-execute.md
- docs/guides/agora-conversational-ai.md
- docs/roadmap/current-milestone.md
- docs/memories.md

Inspect these implementation areas before editing:
- src/newbro/protocol/draft.py
- src/newbro/runtime/drafts.py
- src/newbro/runtime/session.py
- src/newbro/runtime/bootstrap.py
- src/newbro/runtime/container.py
- src/newbro/communication/interaction_classifier.py
- src/newbro/connectors/voice/agora_convoai/module.py
- src/newbro/connectors/voice/agora_convoai/settings.py
- src/newbro/ui/src/App.tsx
- tests/unit/runtime/test_quiet_runtime.py
- tests/unit/runtime/test_drafts.py
- tests/unit/communication/
- tests/unit/connectors/voice/agora_convoai/
- tests/integration/api/test_quiet_runtime_api.py
- src/newbro/ui/src/__tests__/App.test.tsx

Useful discovery commands:
- rg "stt_partial|stt_final|append_asr_turn|DraftSession|DraftSnapshot|RuntimeDecision|should_speak|send_draft|confirm_active_dispatch|InteractionClassifier" src/newbro tests docs
- rg "proposal|review|看一下|改代码|hotel|flight|keyword|phrase" src/newbro/runtime src/newbro/connectors tests/unit/runtime tests/unit/connectors
- rg "chat_completion_turn_silence_seconds|ChatCompletionTurnCoalescer|/chat/completions|convoai" src/newbro/connectors src/newbro/ui tests docs
</context>

<constraints>
Architecture rules:
- Communication Brain owns user-intent understanding. Runtime owns deterministic state transitions and speech policy after structured interpretation exists.
- Keep Execution Brain separate. Do not route raw user transcript directly to executors.
- Keep connector transport thin. The connector transports Agora events and compatibility callbacks; it must not decide meaning, draft corrections, or quietness.
- Treat protocol models and stable docs as the source of truth. RFC 0013 guides the target behavior, but stable docs must be updated for adopted behavior.
- Runtime V1 may remain single-executor in behavior, but protocol/schema changes must stay multi-executor compatible.

Strict anti-cheat rules:
- Do not use hardcoded semantic transcript keyword/phrase lists to classify delegation, draft correction, status, confirmation, task control, destination changes, or send intent.
- Do not move the same semantic keyword rules into a new module with a cleaner name.
- Do not make `should_speak` depend directly on transcript words.
- Do not make `/chat/completions`, callback finality, or silence coalescing the primary source of truth for draft mutation.
- Do not ask "which Bro?" when a Bro-detail voice target exists.
- Do not bypass the dispatch gate. A classifier may propose intent and draft state; it must not be final authority for dispatch.
- Do not use real-time sleeps in tests when a fake clock, explicit tick method, or deterministic scheduler hook can prove the cadence.

Allowed deterministic rules:
- Typed event rules: transcript partial/update events are silent by default; lifecycle events are silent unless runtime state says otherwise.
- Protocol/state rules: blocked/completed/urgent/status/permission/confirmation events may speak according to structured policy.
- High-confidence non-semantic state checks are allowed, e.g. "there is an active live draft", "there is an active task", "this send references the current revision".
- A tiny protocol-token fast path is allowed only if it is explicit protocol syntax, not free-form semantic language parsing, and is documented/tested separately.

Classifier and live-state rules:
- The live classifier must consume the latest transcript snapshot plus session state summary and return structured `InteractionClassification`.
- The production path must use the existing model-backed classifier when configured; scripted/fake classifiers are test-only.
- If no model-backed classifier is configured, the runtime must fail closed or return `UNCERTAIN`/clarification rather than silently falling back to semantic keyword rules.
- The classifier cadence should be configurable and default to approximately 1 second.
- Repeated live classifications for one utterance should refine/replace the active live draft revision, not append one durable ASR turn per classifier tick.
- Final/coalesced events may stabilize/checkpoint a live draft if they are newer; they must not overwrite newer live revisions or become required for UI usefulness.
- Live draft updates are quiet by default. Speak only for structured clarification, blocked, completion, permission/risk, status, urgent, or explicit confirmation cases.
- Send/confirmation must freeze a specific `draft_revision_id` and dispatch only if that revision is still current, or reject/retry safely if a newer revision exists.
</constraints>

<done_when>
- Protocol/runtime models include a draft revision identity and update timestamp, or an equivalent checkpoint field, exposed through draft snapshots and diagnostics.
- A live/provisional interaction state exists for transcript snapshots, including enough metadata to show classifier source, event boundary, and draft revision in diagnostics.
- `stt.partial` or latest-transcript update handling can run the interaction classifier on a configurable approximately 1 second cadence without waiting for final/coalesced callback delivery.
- Unit tests prove the 1 second cadence with a fake clock, explicit tick method, or deterministic scheduler hook; tests do not sleep for real time.
- `DELEGATION` and `DRAFT_CORRECTION` classifier outputs update the same active draft session/revision silently, replacing or refining draft content rather than appending a durable ASR turn for every partial fragment.
- Tests prove a long utterance/correction sequence such as "US ... actually UK ..." ends with one active live draft whose latest revision contains the corrected destination, without creating five durable ASR turns.
- Existing final/coalesced callback handling no longer appends each callback as an authoritative durable `AsrTurn`; it stabilizes/checkpoints the live draft or is ignored if older than the live revision.
- Voice/text send or confirmation freezes the current draft revision and dispatches exactly that revision through the existing dispatch gate.
- Tests prove stale revision send is rejected, retried, or otherwise prevented from dispatching an older draft after a newer revision exists.
- Tests prove Bro-detail target remains authoritative: no persona-pick question or global/home routing appears when `target_persona_id` or the session voice target exists.
- Tests prove `should_speak` is computed from typed event kind, structured classifier output, dispatch gate result, and runtime/blackboard state. Changing transcript words alone cannot force speech unless classifier output or runtime state changes.
- Tests prove live draft updates stay silent by default, while clarification, blocked, completed, permission/risk, status, urgent, and explicit confirmation decisions can speak because of structured state.
- Connector `/chat/completions` remains compatibility-only and delegates to the typed event/runtime decision path; it does not gain semantic text rules or become the source of truth.
- Stable docs are updated to describe the adopted live classifier cadence, provisional draft revisions, finality-as-checkpoint behavior, and send checkpoint semantics.
- `docs/memories.md` gets a short factual note for the adopted runtime behavior.
- Forbidden-shortcut audit is clean for implementation code:
  - rg "proposal|review|看一下|改代码|hotel|flight|keyword|phrase" src/newbro/runtime src/newbro/connectors tests/unit/runtime tests/unit/connectors
  - Any remaining hits are documentation, non-authoritative fixtures, prompts/tests explicitly verifying no hardcoded classification, or otherwise explained.
- Verification succeeds with:
  - .venv/bin/python -m pytest tests/unit/runtime/test_quiet_runtime.py tests/unit/runtime/test_drafts.py tests/unit/communication tests/unit/connectors/voice/agora_convoai tests/integration/api/test_quiet_runtime_api.py
  - .venv/bin/python -m pytest
  - cd src/newbro/ui && bun run test src/__tests__/App.test.tsx --reporter=dot
  - cd src/newbro/ui && bun run build
</done_when>

<workflow>
1. Check git status and preserve unrelated user changes.
2. Re-read RFC 0013 and stable docs listed in `<context>`, especially the sections about quiet communication, draft-to-execute, blackboard state, and responsive interaction.
3. Inspect current partial/final transcript handling, classifier dependency injection, draft session mutation, send/confirmation flow, diagnostics, and connector fallback behavior.
4. Design the smallest live-state extension that fits existing code:
   - classifier input: latest transcript snapshot plus session/draft/task summary
   - classifier output: existing or minimally extended structured `InteractionClassification`
   - live state: provisional classification, active draft revision, timestamp, boundary/source metadata
   - send checkpoint: exact revision id plus deterministic current-revision validation
5. Add protocol/runtime fields for draft revision/checkpoint identity with serialization tests where applicable.
6. Add deterministic classifier cadence support, preferably as an explicit runtime tick/scheduler method that production code can call every configured interval and tests can drive without sleeps.
7. Change partial/latest transcript handling to update live interaction state and draft revisions through the classifier.
8. Change final/coalesced handling so it stabilizes/checkpoints or no-ops relative to newer live state; remove reliance on coalesced callback delivery for responsiveness.
9. Update `send_draft` / `confirm_active_dispatch` so they freeze and validate the current draft revision before dispatch.
10. Keep connector transport thin and keep `/chat/completions` as a compatibility adapter into typed runtime events.
11. Update diagnostics and API/UI state as needed so test runs can show classifier cadence, source/boundary, draft revision, and send checkpoint.
12. Update focused tests for live cadence, one-draft correction behavior, stale revision protection, quiet speech policy, Bro-detail target authority, and callback compatibility.
13. Update stable docs, roadmap if phase/verification scope changes, and `docs/memories.md`.
14. Run focused tests, forbidden-shortcut audit, full backend tests, and frontend checks. Fix failures in scope.
</workflow>

<verification_loop>
Focused backend checks:
- .venv/bin/python -m pytest tests/unit/runtime/test_quiet_runtime.py
- .venv/bin/python -m pytest tests/unit/runtime/test_drafts.py
- .venv/bin/python -m pytest tests/unit/communication
- .venv/bin/python -m pytest tests/unit/connectors/voice/agora_convoai
- .venv/bin/python -m pytest tests/integration/api/test_quiet_runtime_api.py

Forbidden-shortcut audit:
- rg "proposal|review|看一下|改代码|hotel|flight|keyword|phrase" src/newbro/runtime src/newbro/connectors tests/unit/runtime tests/unit/connectors
- Inspect every hit. Implementation-code hits that influence classification, draft correction, send intent, or `should_speak` are blockers.

Full backend check:
- .venv/bin/python -m pytest

Frontend checks:
- cd src/newbro/ui && bun run test src/__tests__/App.test.tsx --reporter=dot
- cd src/newbro/ui && bun run build

Manual live check after restart:
- Start backend, connector, tunnel if needed, and UI.
- Open a Bro detail page and start ConvoAI.
- Say a long delegation with a correction before stopping, e.g. ask for a plan/trip/task and correct one key field while still speaking.
- Confirm logs/diagnostics show live classifier ticks around the configured cadence and one active draft revision stream.
- Confirm final/coalesced callbacks do not create duplicate durable ASR turns.
- Confirm the visible/latest draft reflects the correction before waiting for a long silence coalescer.
- Confirm no audio is spoken for ordinary draft updates.
- Say or click send.
- Confirm dispatch uses the latest frozen revision and stale revisions are rejected or retried safely.

If any check fails, diagnose and fix in scope. Do not report completion with unexplained failures.
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
- Do not widen scope beyond the live classifier loop, live draft revisioning, send checkpointing, docs, and tests required for this change.
- Do not implement semantic transcript heuristics to make tests look green.
- Do not rename a shortcut into a new abstraction and call it architecture.
- Keep final/coalesced callback compatibility, but do not make it the authority path.
- Update stable docs and `docs/memories.md` only for adopted implementation-relevant behavior.
- Keep final answer concise.
</execution_rules>

<output_contract>
Final output must include:
- A concise explanation of how live classification now runs and how often.
- A concise explanation of how `should_speak` is now determined.
- A concise explanation of how draft revisions and send checkpoints prevent stale dispatch.
- Whether the classifier is model-backed, scripted test-only, or failing closed in the current config.
- Key files changed, grouped by protocol/communication/runtime/connector/UI/docs/tests.
- Verification commands run and outcomes.
- Forbidden-shortcut audit result.
- Any skipped checks, blockers, or residual risks.
- A clear completion signal only when every `done_when` item is satisfied or explicitly documented as out of scope.
</output_contract>
