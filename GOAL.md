<goal>
Replace the hardcoded quiet-runtime semantic classifier with a real Communication Brain / interaction-classifier boundary, so Agora ConvoAI `stt.final` turns derive `RuntimeDecision.should_speak` from structured model/classifier output plus deterministic speech policy, not from local transcript keyword rules.

The deliverable is a working, tested, documented runtime path where:
- typed Agora event finality still comes from `AgoraVoiceEvent`
- interaction meaning comes from a classifier interface owned by the communication layer
- the preferred classifier path can use the configured local custom LLM / OpenAI-compatible provider
- deterministic runtime code only applies speech policy to structured classifier/runtime events
- hardcoded task/semantic phrase rules such as `proposal`, `review`, `看一下`, `改代码`, etc. are removed from the authority path
</goal>

<context>
Read first:
- docs/rfcs/0013-newbro-v1.md sections 9, 11.2, 14.2, 14.8, 19.1, 19.2, and 23.3.
- docs/architecture/communication-brain.md
- docs/protocol/draft-to-execute.md
- docs/guides/agora-conversational-ai.md
- docs/memories.md

Inspect these implementation areas before editing:
- src/newbro/runtime/session.py
- src/newbro/runtime/drafts.py
- src/newbro/communication/brain.py
- src/newbro/communication/model.py
- src/newbro/communication/models/openai.py
- src/newbro/communication/models/scripted.py
- src/newbro/runtime/bootstrap.py
- src/newbro/runtime/container.py
- src/newbro/protocol/draft.py
- src/newbro/protocol/enums.py
- src/newbro/connectors/voice/agora_convoai/module.py
- src/newbro/connectors/voice/agora_convoai/session_service.py
- tests/unit/runtime/test_quiet_runtime.py
- tests/unit/communication/
- tests/unit/connectors/voice/agora_convoai/
- tests/integration/api/test_quiet_runtime_api.py

Useful discovery commands:
- rg "classify_interaction|InteractionType|should_speak|RuntimeDecision|handle_runtime_message|handle_agora_event" src/newbro tests docs
- rg "proposal|review|看一下|改代码|hermes|codex|status|stop|send|cancel|keyword|phrase" src/newbro/runtime src/newbro/connectors tests/unit/runtime tests/unit/connectors
- rg "OpenAICommunicationModel|ScriptedCommunicationModel|CommunicationModelResult|DraftRewriter|OpenAIDraftRewriter" src/newbro tests
</context>

<constraints>
Architecture rules:
- Communication Brain owns user-intent understanding. Runtime owns deterministic state transitions and speech policy after structured interpretation exists.
- Keep Execution Brain separate. Do not route raw user transcript directly to executors.
- Keep connector transport thin. The connector maps Agora events to runtime events and maps `RuntimeDecision` back to Agora/TTS; it must not decide meaning or quietness.
- Treat protocol models and stable docs as the source of truth. RFC 0013 guides the target behavior but stable docs must be updated for adopted behavior.
- Runtime V1 may remain single-executor in behavior, but protocol/schema changes must stay multi-executor compatible.

Strict anti-cheat rules:
- Do not use hardcoded semantic transcript keyword/phrase lists to classify delegation, status, correction, confirmation, or task control.
- Do not move the same keyword rules into a new module with a cleaner name.
- Do not make `should_speak` depend directly on transcript words.
- Do not use transcript length, punctuation, language-specific endings, or duplicate text to decide meaning, finality, or speakability.
- Do not make `/chat/completions` the primary ConvoAI path.
- Do not ask "which Bro?" when a Bro-detail voice target exists.
- Do not bypass the dispatch gate. A model/classifier may classify intent and draft task specs, but it must not be final authority for dispatch.

Allowed deterministic rules:
- Typed event rules: `stt.partial` is silent; lifecycle events are silent unless runtime state says otherwise; `stt.final` enters interaction interpretation.
- Protocol/state rules: blocked/completed/urgent/status/permission/confirmation events may speak according to RFC speech policy.
- High-confidence non-semantic state checks are allowed, e.g. "there is an active draft", "there is an active task", "event delivery is urgent".
- A very small command fast path is allowed only if it is explicitly protocol-token based and not semantic task-language parsing; if used, it must be documented and tested separately from free-form task meaning.

Model/classifier rules:
- Add a first-class interaction classifier interface, e.g. `InteractionClassifier.classify(text, state) -> InteractionClassification`.
- The classifier result must include at least `interaction_type`, `confidence`, `requires_user_decision`, `importance`, `reason`, and optionally draft/task spec hints.
- The production/default model-backed path must use the configured LLM provider when available. This may be the user's local custom LLM exposed through the OpenAI-compatible provider settings.
- If no model-backed classifier is configured, the runtime must fail closed or return `UNCERTAIN`/clarification rather than silently falling back to semantic keyword rules.
- Scripted/fake classifiers are allowed only in tests.
</constraints>

<done_when>
- `src/newbro/runtime/drafts.py` no longer contains a semantic `classify_interaction(text, ...)` function with task/status/control keyword lists, and `SessionRuntime.handle_runtime_message` / `handle_agora_event` do not call such a function.
- A typed protocol or communication-layer model exists for interaction classification results with fields for `interaction_type`, `confidence`, `requires_user_decision`, `importance`, and `reason`; unit tests validate serialization or dataclass behavior as appropriate.
- Runtime session construction accepts an interaction classifier dependency, and production bootstrap wires a model-backed classifier when an LLM provider is configured.
- When no model-backed classifier is available, `stt.final` free-form utterances do not get classified through hardcoded semantic keywords. They either return a safe `UNCERTAIN`/clarification decision or use an explicitly configured test/scripted classifier.
- `should_speak` is computed from typed event kind, structured classifier output, dispatch gate result, and blackboard/runtime state. Tests prove changing transcript words alone cannot force speech unless the classifier output or runtime state changes.
- Tests prove a `DELEGATION` classifier output stages/updates a draft and dispatch plan, while a `DRAFT_CORRECTION` output silently updates an existing draft unless clarification/confirmation is required.
- Tests prove `STATUS_QUERY`, `TASK_CONTROL`, `CONFIRMATION`, blocked, completed, permission/risk, and urgent events can speak because of structured event/classifier/runtime state, not because of transcript word matching.
- Tests prove `COMMUNICATION` and low-importance progress stay silent by default.
- Tests prove Bro-detail target remains authoritative: classifier/routing does not ask "which Bro?" when `target_persona_id` or the session voice target is present.
- Connector `/chat/completions` remains compatibility-only and delegates to the typed event/runtime decision path; it does not gain new semantic text rules.
- Forbidden-shortcut audit is clean for implementation code:
  - rg "proposal|review|看一下|改代码|hotel|flight|still thinking|let me finish|MEANINGFUL|INCOMPLETE|keyword|phrase" src/newbro/runtime src/newbro/connectors tests/unit/runtime tests/unit/connectors
  - Any remaining hits are either documentation, fixture text that is not used for classification, or model prompts/tests explicitly verifying the absence of hardcoded classification.
- Stable docs are updated to describe the adopted classifier boundary, model-backed interpretation, and deterministic speech policy. `docs/memories.md` gets a short factual note.
- Verification succeeds with:
  - .venv/bin/python -m pytest tests/unit/runtime/test_quiet_runtime.py tests/unit/communication tests/unit/connectors/voice/agora_convoai tests/integration/api/test_quiet_runtime_api.py
  - .venv/bin/python -m pytest
  - cd src/newbro/ui && bun run test src/__tests__/App.test.tsx --reporter=dot
  - cd src/newbro/ui && bun run build
</done_when>

<workflow>
1. Check git status and preserve unrelated user changes.
2. Re-read RFC 0013 sections 11.2, 14.2, 14.8, and 19.2. Treat "rules + local classifier + hosted fallback" as classifier architecture, not permission to hardcode free-form task semantics in runtime.
3. Inspect current `classify_interaction`, `handle_runtime_message`, `handle_agora_event`, draft rewriting, and Communication Brain model/provider wiring.
4. Design the smallest classifier boundary that fits existing code:
   - classifier input: transcript text plus session state summary
   - classifier output: structured interaction classification
   - production adapter: model-backed via configured provider
   - tests: scripted classifier
5. Implement the protocol/model types and dependency injection.
6. Replace direct calls to `classify_interaction` in runtime with the classifier boundary.
7. Update speech policy so it consumes classifier/runtime event fields and never raw transcript words.
8. Update draft/delegation handling so model-backed classification can stage drafts without hardcoded task words.
9. Update tests: remove tests that only pass because of text keyword matching; add tests where the same transcript yields different `should_speak` only when classifier output changes.
10. Keep the typed Agora event path and `/chat/completions` compatibility behavior intact.
11. Update stable docs and memory notes for adopted behavior.
12. Run focused tests, then full backend/frontend checks. Fix failures in scope.
13. Run forbidden-shortcut audit and manually inspect hits before claiming completion.
</workflow>

<verification_loop>
Focused backend checks:
- .venv/bin/python -m pytest tests/unit/runtime/test_quiet_runtime.py
- .venv/bin/python -m pytest tests/unit/communication
- .venv/bin/python -m pytest tests/unit/connectors/voice/agora_convoai
- .venv/bin/python -m pytest tests/integration/api/test_quiet_runtime_api.py

Forbidden-shortcut audit:
- rg "proposal|review|看一下|改代码|hotel|flight|still thinking|let me finish|MEANINGFUL|INCOMPLETE|keyword|phrase" src/newbro/runtime src/newbro/connectors tests/unit/runtime tests/unit/connectors
- Inspect every hit. Implementation-code hits that influence classification or `should_speak` are blockers.

Full backend check:
- .venv/bin/python -m pytest

Frontend checks:
- cd src/newbro/ui && bun run test src/__tests__/App.test.tsx --reporter=dot
- cd src/newbro/ui && bun run build

Manual live check after restart:
- Start backend, connector, tunnel, and UI.
- Open a Bro detail page and start ConvoAI.
- Confirm logs show typed event handling, classifier output, and `RuntimeDecision` outcomes.
- Confirm partial/progressive transcripts do not persist as durable turns.
- Confirm final utterances do not get classified by runtime keyword matching.
- Confirm spoken response happens only when classifier/runtime state produces a speakable decision.

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
- Do not widen scope.
- Do not implement semantic transcript heuristics to make tests look green.
- Do not rename a shortcut into a new abstraction and call it architecture.
- Keep final answer concise.
- Use existing repo patterns and structured APIs.
- Update stable docs and `docs/memories.md` only for adopted implementation-relevant behavior.
</execution_rules>

<output_contract>
Final output must include:
- A concise explanation of how `should_speak` is now determined.
- Whether the classifier is model-backed, scripted test-only, or failing closed in the current config.
- Key files changed, grouped by protocol/communication/runtime/connector/docs/tests.
- Verification commands run and outcomes.
- Forbidden-shortcut audit result.
- Any skipped checks, blockers, or residual risks.
- A clear completion signal only when every `done_when` item is satisfied or explicitly documented as out of scope.
</output_contract>
