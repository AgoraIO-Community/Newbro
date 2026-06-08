# Codex Turn Streaming (multi-message turns)

A single Codex turn can stream **several `agentMessage` items**, each tagged with a
`phase`. The runtime must distinguish intermediate narration from the durable answer,
otherwise the Bro Detail bubble flickers (settles, then snaps back to working) or
double-renders the streaming text. This contract was regressed repeatedly; the
invariants below are non-negotiable and locked by tests.

## Phases

- `phase: "commentary"` — intermediate working narration. Multiple per turn. Rendered
  as **reasoning steps**. Never settles the turn and never fills the answer slot.
- `phase: "final_answer"` — the durable assistant response. Exactly one per turn.
  Settles the turn and is the **answer**.
- Phase-absent `agentMessage` (history / older Codex / a lone native answer) is treated
  as an answer for back-compat.

## Two channels

A direct Bro Detail turn is reconciled from two event streams that merge into one
`BroTimelineTurn` by executor identity (`executor_thread_id` + `executor_turn_id`):

- **`codex_turn_event`** (channel A) — the outbound turn-request lifecycle: `progress`
  (carries the current item's partial text + `metadata.codex_item_id` + `metadata.phase`)
  and a terminal `completed` carrying the final answer.
- **`codex_thread_event`** (channel B) — the selected-thread subscription:
  `item/started` (carries `phase`), `item/agentMessage/delta` (no phase — routed by the
  phase recorded at `item/started`), `item/completed` (carries `phase`), and the
  turn-level `turn/completed`.

## Invariants (do not break)

1. **Settle once.** The turn settles only on `final_answer`, the outbound
   `codex_turn_event` `completed`, or `turn/completed`. Status goes `running … →
   completed` exactly once — no `completed → running` flip. A *contentless* premature
   `completed` keeps the turn live; a late streaming echo never un-settles a turn that
   already has a real answer.
2. **Commentary is never the answer.** `turn.assistant` stays `None` through commentary;
   only `final_answer` / phase-less native answers populate it.
3. **The answer is not a step.** `_record_native_turn_reasoning` skips `final_answer`;
   commentary `progress` events become reasoning steps.
4. **UI split.** While reasoning, the latest step renders as the prominent streaming
   commentary line (answer weight + caret) above the compact step list; it collapses
   into the step list when the next message starts. On answering/settled, commentary is
   the compact (collapsible) step list and the final answer is the answer bubble.

## Owning code

- `src/newbro/runtime/bro_detail_thread_helpers.py` — `_merge_timeline_turn` (settle /
  un-settle rules), `_record_native_turn_reasoning` text limit.
- `src/newbro/runtime/bro_detail_thread_projection.py` —
  `apply_codex_thread_timeline_event` (phase tracking via `item/started`, commentary →
  `_keep_selected_thread_turn_live`, `final_answer` → answer), `settle_selected_thread_turn`.
- `src/newbro/runtime/session.py` — `_record_native_turn_reasoning` (skips `final_answer`).
- `clients/web/src/lib/splitLiveSteps.ts` + `LiveTurnBubble.tsx` — the UI split.

## Tests & fixture

- `tests/unit/runtime/test_codex_multi_message_turn.py` — replays the real captured wire
  and asserts invariants 1–3.
- `tests/unit/runtime/test_session_runtime.py` — the `selected_codex_thread*`,
  `commentary*`, `turn_completed*`, and `_merge_timeline_turn` cases.
- `clients/web/src/lib/splitLiveSteps.test.ts` and `LiveTurnBubble.test.tsx` — invariant 4.
- Fixture: `docs/protocol/fixtures/codex-multi-message-turn-sample.jsonl` (masked real wire:
  paths → `/Users/USER`, content → `<masked:N>`, persona → `persona-A`; `phase` preserved).

See also [Codex wire reference](./codex-wire-reference.md).
