# Live + settled reasoning for native codex turns

Date: 2026-05-31
Status: Design (approved for spec review)

## Problem

In the desktop bro detail view, assistant turns from a codex bro never show reasoning —
neither the live "<Bro> is reasoning" stream while the turn runs, nor the collapsed
"Reasoned" pill after it settles. The redesigned answer bubble (`DTAnswerBubble`) and the
streaming reasoning bubble are correct; they are simply never given any reasoning data for
these turns.

## Root cause (confirmed from a live session capture)

A codex bro driven through the bro-detail composer executes via the **native / outbound-turn
path**, not the runtime's tracked-run path:

- `submit_executor_text_instruction` requires a pre-existing active tracked codex execution
  (`_active_codex_execution_for_persona`, `runtime/session.py:3226`). A native-codex session
  has none (`sessions: 0, runs: 0`), so it always takes the outbound-turn branch
  (`runtime/session.py:2696`).
- The node runs the turn natively (`start_codex_turn` → `_stream_turn_events`) and emits
  events on the **codex-turn channel** (`_send_codex_turn_event`), which carry **no `run_id`**.
- Only the `dispatch_run` path streams run-scoped `RunEventMessage`s that the runtime records
  as `TaskExecutionDetailEntry` (`PROGRESS`/`PLAN`) into `recent_execution_details`
  (`execution/run_manager.py:70,93,164`). The native path never populates that store.
- The reasoning UI (`TimelineTurnView`) reads reasoning **only** from
  `execution_runs` + `recent_execution_details`, joined via `turn.task.task_id`. For native
  turns all three are absent (`task_id: null`), so there is nothing to render.

This is independent of plan mode: the outbound-vs-tracked branch is decided by
`run is None`, not by `plan_mode`. `plan_mode` only sets task metadata inside the tracked
branch, which native turns never reach.

Key enabling fact: the live native turn is **already projected**. `handle_codex_turn_event`
→ `_bro_timeline_turn_from_codex_turn_event` (`runtime/session.py:314`) builds an in-flight
`BroTimelineTurn` (status `running`) per incoming codex-turn event, and **each `PROGRESS`
event already carries the reasoning-step text in `message.message`** — it is currently
discarded (only the final message becomes the assistant text). We do not need to invent an
in-flight projection; we only need to capture and keep the reasoning steps.

## Goals

- Show the live "<Bro> is reasoning" stream while a native codex turn runs (steps appear in
  real time as snapshots arrive over WebSocket).
- Collapse those steps into the "Reasoned" pill on the settled `DTAnswerBubble` after the
  turn completes.
- Reuse the existing reasoning UI (streaming bubble + `DTAnswerBubble` pill) unchanged.
- Keep the added WebSocket payload bounded and comparable to the existing
  `recent_execution_details` field.

## Non-goals

- Routing native-codex composer turns through the tracked-run (`dispatch_run`) path. Rejected:
  it changes the execution model (resume handles, thread continuity, history dedup) for a
  display feature — too large a blast radius.
- Retroactively recovering reasoning for already-imported history turns (the existing
  `codex-import-…` turns). Their reasoning was never captured and is not in codex history.
- Moving the snapshot model from full-snapshot to delta/event WebSocket messages.

## Design

### 1. Capture (backend — `runtime/session.py`)

In `handle_codex_turn_event`, for each incoming event whose type is `PROGRESS` or `PLAN`,
append a reasoning step to an ordered list for that turn:

- **Key:** executor turn identity `(executor_id, executor_thread_id, executor_turn_id)` — the
  exact tuple `_timeline_identity` (`runtime/session.py`) already uses to merge the live
  outbound turn with the later synced `codex-import` history turn, so the steps survive the
  outbound→history transition. (Note: `executor_thread_id` is the codex-native thread id, not
  the public `thread_id`.)
- **Step shape:** `{ item_id: str, text: str, kind: "progress" | "plan", created_at: str }`.
- **Text:** `message.message`, truncated to 280 chars.
- **Accumulation keyed by `codex_item_id`** (present in the event metadata, spread into the
  codex-turn event): a single codex commentary item arrives as the *latest full text for that
  item* and grows across events (verified live: the same line streamed `len 206 → 234`, then a
  new line replaced it). So **update the step in place when `codex_item_id` matches the last
  step; append a new step when a new `item_id` appears.** This avoids both duplicate steps (one
  item growing) and lost steps (distinct items). Events without a `codex_item_id` fall back to
  append-on-text-change.
- **Storage:** a session-held in-memory map
  `dict[turn_key, list[NativeReasoningStep]]`, with the same lifetime/behavior as today's
  derived `recent_execution_details` (session lifetime; not durable across a full backend
  restart, which is acceptable since codex history does not store reasoning).

### 2. Project (snapshot — `runtime/models.py`, `SessionSnapshot`)

Add a new snapshot field:

```
recent_native_turn_reasoning: dict[str, list[NativeReasoningStep]]
```

keyed by a serialized turn key (e.g. `f"{executor_id}::{executor_thread_id}::{executor_turn_id}"`).

**Bounds (explicit requirements):**

- Window: most recent **10** turns, **8** steps each — identical to
  `list_recent_task_execution_details(task_limit=10, entry_limit=8)`.
- Per-step text truncated to **280** chars.
- The **active** (running) turn is always included with its full (capped at 8) tail; settled
  turns keep only their last 8 steps for the pill.

### 3. Join + render (frontend — `ArtboardShell.tsx`, `adapters.ts`)

- Add a builder `buildReasoningStepsForNativeTurn(turn, recentNativeTurnReasoning)` that, for a
  turn with `task_id == null`, looks up steps by `(executor_id, executor_thread_id,
  executor_turn_id)` and maps them to the existing `ReasoningStep[]` shape.
- In `TimelineTurnView`, when the turn is native (no task), source reasoning from this builder
  instead of `recentExecutionDetails[taskId]`. Tracked-run turns keep the existing path.
- Render reuses existing components with no visual change:
  - turn `status: "running"` → the live `dt-bubble-reason` streaming bubble (steps append as
    new snapshots arrive),
  - turn settled → steps collapse into `DTAnswerBubble`'s "Reasoned" pill.
- `NewbroShell` threads the new `recent_native_turn_reasoning` field through context the same
  way `recentExecutionDetails` is threaded today.

## Data flow

```
codex node (native turn)
  → _stream_turn_events emits PROGRESS/PLAN (message.message = reasoning step)
  → _send_codex_turn_event (codex-turn channel)
  → api/ws/executors.py: session.handle_codex_turn_event(message)
      → existing: build/refresh in-flight BroTimelineTurn (status running)
      → NEW: append step to native_turn_reasoning[(executor_id, executor_thread_id, executor_turn_id)]
  → publish_snapshot()  (already fires on these events)
      → snapshot.recent_native_turn_reasoning (bounded)
  → WS → NewbroShell → TimelineTurnView
      → native turn joins reasoning by executor identity
      → running: streaming bubble; settled: DTAnswerBubble pill
```

## Error handling / edge cases

- Missing `executor_thread_id` or `executor_turn_id` on an event → skip capture for that event
  (cannot form the identity key); do not fabricate a key.
- `FAILED`/`CANCELLED` turn → stop accumulating; whatever steps exist remain attached to the
  settled (failed) turn. No special failed-reasoning chrome (consistent with the earlier
  full-cleanup decision for the answer bubble).
- Turn ages out of the 10-turn window → its pill renders empty (no steps), which the existing
  `DTAnswerBubble` already handles (pill only shows when `steps.length > 0`).
- Backend restart → in-memory reasoning is lost; settled turns then show no pill. Acceptable
  and documented.
- **In-flight status comes from the WS path, not REST.** `handle_codex_turn_event` publishes
  with `sync_imported_codex_threads=False`, so the in-flight outbound turn keeps `status:
  running` for the UI. The REST `GET /sessions/{id}` re-syncs imported threads and merges in a
  completed history turn, which makes the turn read as `completed` mid-run — a REST-only
  artifact (it misled an earlier diagnostic poll). The frontend consumes WS snapshots, so the
  `running` → streaming, `completed` → pill transition is correct. The design must not rely on
  REST polling for in-flight state.

## Testing

Backend (`pytest`):
- Feed a sequence of `CodexTurnEventMessage`s into `handle_codex_turn_event`: same
  `codex_item_id` with growing text (asserts in-place update, one step), then a new
  `codex_item_id` (asserts a second step appended), a `PLAN` event, then `COMPLETED`. Assert
  `snapshot.recent_native_turn_reasoning` holds the ordered, truncated steps under the
  `(executor_id, executor_thread_id, executor_turn_id)` key, present while the turn is
  `running` and retained after `completed`.
- Assert the window/step bounds (10 turns × 8 steps, 280-char truncation).

Frontend (`vitest`):
- Native running turn with `recent_native_turn_reasoning` → renders the streaming reasoning
  bubble with the steps.
- Native completed turn → renders `DTAnswerBubble` with the "Reasoned" pill expanding to the
  steps.
- Native turn with no reasoning entry → no pill (unchanged behavior).

## Affected files (anticipated)

- `src/newbro/runtime/session.py` — capture in `handle_codex_turn_event`; expose store in
  `snapshot()`.
- `src/newbro/runtime/models.py` — `SessionSnapshot.recent_native_turn_reasoning`; step model.
- `src/newbro/ui/src/components/newbro/adapters.ts` — `buildReasoningStepsForNativeTurn`.
- `src/newbro/ui/src/ArtboardShell.tsx` — native-turn reasoning source in `TimelineTurnView`.
- `src/newbro/ui/src/NewbroShell.tsx` — thread the new snapshot field through context.
- Tests under `tests/unit/runtime/` (e.g. `test_session_runtime.py`) and
  `src/newbro/ui/src/__tests__/`.

## Cost note

The new field reuses the `recent_execution_details` window (≈10×8) and truncates steps, so it
adds roughly 10–15 KB to a snapshot — the same order as a field already shipped on every
snapshot. The snapshot is re-sent in full on each `publish_snapshot`; during a live turn the
growing step list is re-sent each time (≈O(steps²) cumulative per turn, tens of KB total),
which is acceptable and bounded by the window. A delta/event WebSocket model would remove the
re-send but is out of scope.
