# Development Best Practices

This guide captures project skills for developing Newbro safely. These are
operational habits, not product requirements.

## Start From The Contract

- Read stable docs first: `docs/architecture/`, `docs/protocol/`, and
  `docs/guides/`.
- Use RFCs as design history unless their content has been merged into stable
  docs.
- If stable docs and RFCs conflict, follow the stable docs.
- When behavior changes in an adopted way, update the stable docs and add a
  short factual note to `docs/memories.md`.

## Keep Boundaries Sharp

- Communication Brain owns utterance meaning, interaction classification,
  conversational policy, and user-facing speech decisions.
- Execution Brain owns execution lifecycle, executor sessions, scheduling, and
  run state.
- Shared Blackboard is the source of durable task, draft, run, summary, and
  event facts.
- Transport layers should translate typed events and carry protocol objects.
  They should not decide product behavior.

## Avoid Fake Understanding

- Do not add hard-coded transcript keyword rules to make a demo look correct.
- Prefer structured classifier contracts and protocol fields over semantic
  runtime shortcuts.
- If model behavior is wrong, tighten the model-backed contract and test the
  prompt boundary.
- Deterministic runtime gates are appropriate for protocol facts such as draft
  revision, dispatch status, risk level, missing context, and stale send
  protection.

## Diagnose Before Changing

For voice/runtime issues, inspect the actual active state before implementing:

- Browser URL and session id.
- `GET /api/sessions/{session_id}` snapshot.
- `GET /api/sessions/{session_id}/diagnostics/timeline`.
- Current `draft_session`, `current_dispatch_plan`, `tasks`, and executor
  connection state.
- Whether backend/frontend reload picked up the code.

Do not declare success from code inspection alone when the user is testing a
live voice path.

## Quiet Voice Runtime Rules

- `stt.partial` may update live draft state on the classifier cadence, but it
  should stay silent by default.
- `stt.final` checkpoints stabilize the draft and may speak only when policy
  says a user-facing decision is useful.
- `RuntimeDecision.should_speak` is the sole TTS gate for Agora ConvoAI.
- A ready draft may ask once for send confirmation.
- A meaningful `draft_correction` may reopen one confirmation prompt for the
  corrected revision.
- Duplicate finals and non-correction refinements should not repeat "draft
  ready" prompts.
- Confirmation with no active draft is a silent no-op.

## Dispatch Safety

- Never dispatch raw user speech directly to an executor.
- Dispatch from a structured Draft through a Dispatch Plan and Dispatch Gate.
- Send only the current draft revision; stale revision sends must fail before
  task creation.
- After successful dispatch, clear the active draft and publish the cleared
  snapshot.
- Keep executor permission checkpoints with the executor. Do not voice
  transport-level or Codex-style internal risk wording as the user's send
  prompt.

## Testing Expectations

Match test scope to the changed boundary:

- Classifier contract changes need classifier prompt tests.
- Runtime speech/dispatch changes need quiet runtime tests.
- API behavior changes need integration API tests.
- UI stale-state or stream handling changes need frontend tests or build
  verification.
- End-to-end voice fixes should be checked against a real session timeline
  after implementation.

## Development Discipline

- Keep changes scoped to the failing behavior.
- Prefer existing repo patterns and protocol models over new abstractions.
- Do not claim a goal is complete until tests and live activation checks support
  it.
- When a manual run contradicts expectations, trust the logs and snapshot over
  assumptions.
