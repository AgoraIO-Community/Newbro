# AGENTS.md

## Project
Newbro is a backend-first prototype for a communication-brain / execution-brain runtime.

Core concepts:
- Communication Brain
- Execution Brain
- Shared Blackboard
- Protocol-first runtime

## Stack
- Python 3.12
- FastAPI
- Pydantic
- Pytest
- React
- Vite
- TypeScript

## Run
```bash
./install.sh
./newbro setup
./newbro backend
```

## Test
```bash
.venv/bin/python -m pytest
```

## Guardrails
- Keep Communication Brain and Execution Brain separate.
- Keep transport thin.
- Treat protocol models as the source of truth.
- Runtime V1 is single-executor, but schemas must stay multi-executor compatible.

## Golden Rules
- **Fix root causes; do not hide problems with fallback behavior.** When a failure exposes ambiguity, missing protocol state, or an invalid ownership boundary, fix the contract or flow directly. Do not add fallback behavior by default. If fallback behavior seems necessary, stop and get explicit user approval before implementing it; approved fallbacks must be intentional product behavior, documented, observable, and tested.
- **Think at project level before patching.** Before fixing a bug, identify the affected protocol/runtime ownership boundary and sibling flows, such as text/audio, new/existing thread, UI/API/runtime/executor. Make one coherent design change across the affected paths instead of a narrow patch that only satisfies the immediate reproduction.

## Project Skills
When developing Newbro, apply these project skills before changing code:

- **Read the contract first.** Check stable docs under `docs/architecture/`, `docs/protocol/`, and `docs/guides/` before RFCs. RFCs are design background unless merged into stable docs.
- **Preserve brain boundaries.** Put utterance meaning, classification, and user-facing speech policy in the Communication Brain path. Keep execution scheduling, executor sessions, and task state in Execution Brain / blackboard paths.
- **Avoid fake semantic rules.** Do not patch behavior with transcript keyword heuristics that pretend to understand the user. Prefer structured model-backed classifier contracts, protocol fields, and tests that prove the contract.
- **Keep transport thin.** Agora ConvoAI, browser UI, and compatibility endpoints should translate typed events and return `RuntimeDecision`; they should not own business policy.
- **Diagnose from real state.** Before claiming a fix works, inspect the active session snapshot, diagnostics timeline, task list, draft session, dispatch plan, and running process/reload state.
- **Design quiet voice behavior explicitly.** Partial live updates should be UI-first and silent. Speech should be gated by `RuntimeDecision.should_speak`, with prompts only for meaningful confirmation, clarification, blocked/completed/urgent status, or explicit user status requests.
- **Test the failure mode.** Add focused tests for the exact regression, including classifier prompt contract, runtime decision output, UI state cleanup, and API behavior when those boundaries are involved.
- **Verify activation.** After changes, confirm tests pass and the running backend/frontend picked up the code before judging a manual run.
- **Update memory deliberately.** For adopted runtime behavior changes, update stable docs and add a short factual note to `docs/memories.md`; do not update memories for tiny refactors or test-only changes.

## Project Memory
Treat `docs/` as the project documentation and memory root.

- `docs/README.md` is the docs index.
- `docs/design.md` is the legacy v1 architecture overview.
- `docs/architecture/`, `docs/protocol/`, `docs/guides/`, and `docs/decisions/` contain the stable topic docs.
- `docs/roadmap/` contains the maintained implementation roadmap and verification strategy.
- `docs/rfcs/` contains proposal / RFC-style design docs and must not be treated as the current implementation contract unless their content is merged into the stable docs.
- `docs/memories.md` records short factual notes for adopted, meaningful design and architecture changes.

When architecture, protocols, or runtime behavior changes in an adopted and implementation-relevant way:
- update the stable docs under `docs/architecture/`, `docs/protocol/`, and related topic docs
- update any other stable docs that become the source of truth for that topic
- append a short note to `docs/memories.md`

When implementation priorities, phase boundaries, or verification strategy change meaningfully:
- update `docs/roadmap/`

When a change is still proposal-only:
- update the proposal / RFC docs
- do not append it to `docs/memories.md` yet
- do not present the proposal as current runtime behavior

If stable docs and proposal docs conflict, treat the stable docs as authoritative.

Do not update memory docs for tiny refactors, formatting-only changes, or test-only changes.
Keep memory notes short and factual.
Do not claim this is automated; it is a repo convention for agents working here.
