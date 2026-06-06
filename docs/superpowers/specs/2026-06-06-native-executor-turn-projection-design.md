# Native Executor Turn Projection Design

## Goal

Deepen Bro Detail native turn projection without changing original UI behavior.

`BroDetailThreadProjection` currently owns Bro thread state and Codex wire semantics. That makes the module shallow: callers and tests must understand selected Bro threads, Codex channel A/B events, `agentMessage` phases, live delta state, and settle-once rules in one place.

This design extracts Codex-specific turn reduction behind a native executor turn projection module while preserving the existing `BroTimelineTurn` output and frontend split behavior.

## Non-Goals

- Do not change `BroTimelineTurn`, websocket snapshot shape, or frontend rendering contracts.
- Do not change `splitLiveSteps` or `LiveTurnBubble`.
- Do not introduce a broad executor plugin seam before a second adapter needs it.
- Do not add fallback behavior for ambiguous or malformed stream frames.
- Do not relax the codex multi-message turn invariants in `docs/protocol/codex-turn-streaming.md`.

## Current Friction

Codex-specific wire handling lives directly on `BroDetailThreadProjection`:

- `handle_codex_turn_event`
- `handle_codex_thread_event`
- `apply_codex_thread_timeline_event`
- live item phase state
- live message and plan delta state
- `commentary` versus `final_answer` routing
- `item/started`, `item/agentMessage/delta`, `item/completed`, and `turn/completed`

`BroDetailThreadProjection` should own Bro Detail threads and timelines. Codex wire semantics should be local to a deeper native turn projection module.

## Architecture

Add a runtime module named around the general concept:

```text
src/newbro/runtime/native_turn_projection.py
```

The module contains a Codex-specific reducer as the first implementation:

```text
Native executor turn projection
  - shared BroTimelineTurn merge and settle rules
  - Codex native turn reducer
```

This is intentionally not a fully generic executor plugin interface yet. Codex is the only current native threaded executor adapter. The module name leaves room for future executor-like reducers, while the implementation only abstracts what exists.

## Ownership

`BroDetailThreadProjection` keeps:

- Bro thread list and projection assembly
- selected Bro thread subscription lifecycle
- imported thread state
- thread target resolution
- timeline storage and page state
- snapshot publication trigger

Native executor turn projection owns:

- Codex channel A `codex_turn_event` reduction
- Codex channel B `codex_thread_event` item and turn reduction
- `agentMessage` phase routing
- live item phase map
- live assistant message delta map
- live plan delta and emitted-plan tracking
- settle-once behavior for reduced `BroTimelineTurn` updates

`SessionRuntime.handle_codex_turn_event` and the executor websocket route may keep their existing names. They become thin transport entry points that delegate through `BroDetailThreadProjection` into the native turn projection module. This avoids route and websocket contract churn.

## Data Flow

Channel A:

1. `BroDetailThreadProjection.handle_codex_turn_event` loads and validates the `OutboundTurnRequest`.
2. It updates request status and attach-new-thread resume handle state as today.
3. It passes the updated request, `CodexTurnEventMessage`, and timestamp to the native turn projection module.
4. The module returns a `BroTimelineTurn` update and native reasoning-step intent if needed.
5. `BroDetailThreadProjection` upserts the returned turn and publishes the snapshot.

Channel B:

1. `BroDetailThreadProjection.handle_codex_thread_event` validates the selected subscription.
2. Thread-level subscription lifecycle remains in `BroDetailThreadProjection`.
3. Item and turn events are passed to the native turn projection module.
4. The module returns an upsert, settle, or no-op action over existing `BroTimelineTurn` state.
5. `BroDetailThreadProjection` applies the action and publishes the snapshot when changed.

## Behavior Contract

The output interface remains the existing `BroTimelineTurn`.

Preserve these invariants:

- commentary never settles the turn
- commentary never fills `turn.assistant`
- `final_answer` is the durable answer
- phase-less native assistant messages remain back-compatible answers
- final answers are not recorded as reasoning steps
- contentless premature completion keeps the turn live
- late streaming echoes never un-settle a truly settled turn
- failed and cancelled turns never resurrect

## Error Handling

Invalid, unknown, or partial Codex stream frames remain no-ops. The module should return no action rather than surfacing user-visible errors for non-actionable stream frames.

Terminal executor failures continue to be represented by existing `BroTimelineTurn` status behavior.

No new fallback behavior is introduced.

## Testing

Existing acceptance tests must stay green:

- `tests/unit/runtime/test_codex_multi_message_turn.py`
- `tests/unit/runtime/test_session_runtime.py` cases for selected Codex threads, commentary, turn completion, and `_merge_timeline_turn`
- `src/newbro/ui/src/lib/splitLiveSteps.test.ts`
- `src/newbro/ui/src/LiveTurnBubble.test.tsx`

Add focused module tests for the new native turn projection module:

- commentary item started/delta/completed returns live turn with no assistant
- final answer delta/completed returns assistant and settles
- phase-less assistant message remains an answer
- turn-level completion settles a commentary-only turn
- late streaming echo does not un-settle a completed answer
- failed turn does not resurrect

These tests should exercise the new module interface without constructing a full `SessionRuntime`.

## Migration Plan

1. Add the native turn projection module with behavior copied from the current implementation.
2. Move live phase and delta maps into the new module.
3. Delegate Codex item and turn event handling from `BroDetailThreadProjection`.
4. Keep old public route/session method names unchanged.
5. Move `_merge_timeline_turn` only if doing so reduces interface width without causing broad churn; otherwise keep it as a shared helper during the first extraction.
6. Run the current regression tests and the new focused module tests.

## Deferred Registry Decision

The first implementation should not create a formal multi-executor reducer registry. Add a registry only when a second native threaded executor exists. Until then, Codex-specific code can live inside the native turn projection module under explicit Codex names.
