# Newbro Bro Detail Canonical Timeline Spec

## Goal

Refactor Bro Detail so the timeline is rendered from one backend-owned,
multi-executor protocol projection: canonical timeline turns.

The current UI merges several independent shapes by timestamp:

- local optimistic text turns
- local optimistic audio turns
- Newbro task/run/summary records
- native executor thread messages
- general conversation messages

That design is error-prone because multiple sources can represent the same
logical user/executor turn. The refactor must make the turn the stable unit of
display and reconciliation.

## Product Decisions

- The canonical timeline object is a backend protocol object included in
  `SessionSnapshot`.
- The canonical timeline object is a read model/projection. It must not become
  another durable source of truth that competes with Newbro `Task`,
  `ExecutionRun`, `TaskSummary`, local optimistic turns, or native executor
  history. Runtime state owns reconciliation; the UI renders the projection plus
  timeline-shaped optimistic placeholders only.
- Do not preserve `bro_thread_messages` for Bro Detail compatibility. Replace
  Bro Detail rendering with canonical timeline turns.
- The core protocol must be multi-executor. Use generic fields such as
  `executor_id`, `executor_thread_id`, and `executor_turn_id`; keep Codex names
  only inside adapter metadata when needed.
- Executor adapters are responsible for mapping native thread/turn identifiers
  into the generic `executor_*` fields. If an executor cannot supply native turn
  identity, the system may still render Newbro-owned direct turns by
  `client_request_id`, but it must not pretend to safely reconcile unrelated
  native live events.
- Native executor history remains separate from Newbro `Task`, `ExecutionRun`,
  and `TaskSummary` records.
- Local text and audio sends may still render optimistically, but the optimistic
  item must use the same timeline-turn shape and be replaced by the canonical
  backend turn via `client_request_id`.
- Audio transcript is a property of the audio user message. It must not become a
  second user text message.
- The visual style should remain the existing Bro Detail user bubble and task
  response card UI. This is a data/model refactor, not a visual redesign.

## Required Protocol Shape

Add a canonical timeline turn model similar to:

```text
BroTimelineTurn
  turn_id: string
  thread_id: string
  persona_id: string
  executor_id: string
  owner: "newbro" | "executor"
  client_request_id?: string
  executor_thread_id?: string
  executor_turn_id?: string
  input_modality: "text" | "audio" | "unknown"
  user?: BroTimelineMessage
  assistant?: BroTimelineMessage
  task?: BroTimelineTask
  status: "pending" | "running" | "completed" | "failed" | "cancelled"
  created_at?: string
  updated_at?: string
  metadata: Record<string, unknown>
```

```text
BroTimelineMessage
  message_id: string
  role: "user" | "assistant"
  kind: "text" | "audio"
  text?: string
  transcript?: string
  audio_id?: string
  duration_ms?: number
  status: string
  created_at?: string
  updated_at?: string
  metadata: Record<string, unknown>
```

```text
BroTimelineTask
  task_id: string
  run_id?: string
  title: string
  status: string
  status_label: string
  progress: number
  description?: string
  summary?: string
  created_at?: string
  updated_at?: string
  metadata: Record<string, unknown>
```

Exact naming can vary if it follows existing project conventions, but the core
contract must represent one timeline row per logical turn and must not expose a
Codex-only primary model.

`BroThread` should keep per-thread timeline load state, such as
`timeline_status` and `timeline_error`, so imported history read failures can be
shown without failing thread open. Naming may follow existing project
conventions, but empty states must remain hidden while a selected thread's
timeline is loading.

## Required Behavior

### Imported Native History

- Opening an imported/native executor thread loads native history into
  executor-owned `BroTimelineTurn` records.
- Imported native history must not create Newbro `Task`, `ExecutionRun`, or
  `TaskSummary` records.
- User-side imported messages render with the existing user bubble.
- Assistant-side imported messages render with the existing task response card
  visual.
- Imported/native assistant card titles should come from the associated user
  input/query for that turn when available. The UI should not add redundant
  generic assistant-response headings.
- For response turns with multiple assistant/agent items, display only the last
  assistant/agent message for that turn.
- Imported history reads are allowed on explicit thread open. Ordinary send
  paths and snapshot publishes must not refresh native history or block on
  executor history reads.
- If imported/native history read fails, opening the thread still succeeds and
  the selected thread exposes a failed timeline load state and error.

### Newbro Direct Text Sends

- A local text send creates an optimistic `BroTimelineTurn` with the
  `client_request_id` generated by the UI.
- The backend-created canonical Newbro-owned turn replaces the optimistic turn
  by `client_request_id`.
- The user text appears once.
- The task/run/progress/final assistant output appears once in the same turn.
- Native executor events for the same turn update that canonical turn only when
  correlated by `executor_id`, `executor_thread_id`, and `executor_turn_id`.
- If native events for a Newbro-owned direct turn arrive before the runtime has
  attached the native `executor_turn_id` to the Newbro turn, the runtime must
  either buffer/merge them when correlation becomes available or project them as
  executor-owned and later merge them. It must not drop valid events or use
  thread-level filtering as a substitute for correlation.
- A mixed imported thread can show old executor-owned turns and newer
  Newbro-owned direct turns without hiding unrelated native history.

### Newbro Direct Audio Sends

- A local push-to-talk send creates an optimistic `BroTimelineTurn` with
  `input_modality = "audio"` and a user message of `kind = "audio"`.
- The voice bubble, duration, upload/transcription status, and transcript all
  belong to that one audio user message.
- The transcript must not render as a second text user message.
- The backend-created canonical Newbro-owned turn replaces the optimistic audio
  turn by `client_request_id`.
- Task/run/progress/final assistant output appears once in the same turn.

### Live Executor Events

- Live native events are normalized into timeline turns before the UI sees them.
- The frontend must not dedupe remote/native events by comparing text, timestamp,
  or thread-level task presence. Reconciliation belongs to runtime identity
  fields.
- Reconciliation order should be:
  1. canonical `turn_id`
  2. `client_request_id`
  3. `executor_id + executor_thread_id + executor_turn_id`
- If a native event matches an existing Newbro-owned turn, it updates that turn
  instead of creating an executor-owned duplicate.
- If a native event has no Newbro-owned match, it creates or updates an
  executor-owned turn.
- Assistant deltas/messages for the same response turn replace the latest
  assistant content in that turn instead of adding another timeline row.
- Timeline ordering must be deterministic, using timestamps where available and
  stable ids as a tie-breaker. Within one turn, the user side always renders
  before assistant/task output.

## In Scope

- Protocol model changes under `src/newbro/protocol/` and `SessionSnapshot`.
- Runtime projection changes in `src/newbro/runtime/session.py`.
- Generic executor timeline correlation fields and Codex adapter mapping into
  those fields.
- Bro Detail frontend data flow and rendering changes in
  `src/newbro/ui/src/`.
- Backend and frontend tests for imported history, direct text, direct audio,
  mixed threads, and stale/late responses.
- Stable docs and `docs/memories.md` updates because this changes adopted
  protocol/runtime behavior.

## Non-Goals

- Do not add a Codex-only timeline protocol.
- Do not introduce text/timestamp similarity dedupe heuristics.
- Do not make the frontend responsible for native event ownership decisions.
- Do not create fake Newbro tasks/runs/summaries for imported native history.
- Do not use thread-level hiding/suppression filters to solve duplication.
- Do not render Bro Detail from independently merged local turns, task cards,
  and native messages.
- Do not redesign the visual system.
- Do not implement new non-Codex executor capabilities beyond the generic
  protocol shape needed for future adapters.
- Do not change Communication Brain behavior.

## Source Of Truth

Read first:

- `AGENTS.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/guides/frontend-workbench.md`
- `docs/architecture/executors.md`
- `src/newbro/protocol/session.py`
- `src/newbro/runtime/models.py`
- `src/newbro/runtime/session.py`
- `src/newbro/executors/adapters/codex/executor.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/ui/src/types.ts`
- `src/newbro/ui/src/NewbroShell.tsx`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/components/newbro/adapters.ts`
- `src/newbro/ui/src/components/newbro/types.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`
- `tests/integration/api/test_executor_text.py`
- `tests/integration/api/test_executor_audio.py`
- `tests/unit/runtime/test_session_runtime.py`

Useful discovery commands:

```bash
rg -n "BroThreadMessage|bro_thread_messages|buildTimelineEntries|TextTurn|AudioTurn|BroTaskRecord|SessionSnapshot" src/newbro tests docs
rg -n "turnId|client_request_id|target_thread_id|source_kind|latest_resume_handle|item/agentMessage/delta|item/completed" src/newbro tests
```

## Verification

Focused backend checks:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py
.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py
```

Focused frontend checks:

```bash
bun run test -- src/__tests__/App.test.tsx
bun run build
```

Optional broad checks:

```bash
.venv/bin/python -m pytest
bun run test
```

Manual or test-backed UI checks:

1. Imported native thread history renders user and assistant turns using the
   existing user bubble and task response card visuals.
2. Sending one text message renders one user-side turn and one assistant/task
   response, with no duplicate native message.
3. Sending one audio message renders one audio user-side turn; transcript
   appears inside that audio turn and not as a second text message.
4. A mixed imported thread shows old executor-owned turns and new Newbro-owned
   turns without hiding unrelated native history.
5. Live assistant deltas replace the assistant content for the same executor
   turn.
6. Selecting a different thread while an open/history response is late does not
   replace the currently selected timeline.

## Done When

- `SessionSnapshot` includes backend-owned canonical Bro Detail timeline turns.
- Canonical timeline turns are a read-model/projection, not a new competing
  durable source of truth.
- Bro Detail rendering uses canonical timeline turns, not a timestamp merge of
  local text turns, local audio turns, task records, native messages, and chat
  messages.
- The core timeline protocol uses generic multi-executor correlation fields
  (`executor_id`, `executor_thread_id`, `executor_turn_id`) instead of Codex-only
  primary fields.
- Executor adapters map native identity into generic `executor_*` fields, and
  executors without native turn identity are handled explicitly rather than by
  heuristic dedupe.
- Per-thread timeline load state shows imported history loading/failure without
  failing thread open.
- `bro_thread_messages` is no longer the Bro Detail rendering contract.
- Imported/native executor history renders without creating Newbro `Task`,
  `ExecutionRun`, or `TaskSummary` records.
- Sending one text message renders exactly one user-side turn and one
  assistant/task response.
- Sending one audio message renders exactly one audio user-side turn; transcript
  appears inside that audio turn and not as a separate text message.
- A mixed imported thread can show old executor-owned turns and new
  Newbro-owned turns without hiding valid native history.
- Live assistant deltas/messages replace the latest assistant content for the
  same executor turn.
- Optimistic local text/audio turns are replaced by canonical backend turns via
  `client_request_id`.
- No thread-level suppression/hiding or text/timestamp similarity matching is
  required to avoid duplicates.
- Focused backend and frontend tests listed above pass.
- Stable docs and `docs/memories.md` document the canonical timeline turn
  contract and source ownership behavior.
