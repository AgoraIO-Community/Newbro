# Bro Detail Thread Projection Extraction

## Goal

Deepen the **Bro Detail Thread Projection** module so `SessionRuntime` no longer owns imported Codex thread catalogs, selected-thread subscriptions, Codex thread event merging, outbound turn projection, or Bro Detail timeline state.

## Constraints

- Source code is the current contract; stable docs may be outdated.
- Keep `SessionRuntime` compatibility methods for existing routes and websocket handlers.
- Keep `Direct Executor Interaction` focused on text/audio instruction dispatch.
- Do not add fallback behavior. Missing or ambiguous thread state should keep raising explicit errors.
- Protocol models remain the source of truth.

## Target shape

- Add `newbro.runtime.bro_detail_thread_projection.BroDetailThreadProjection`.
- The new module owns imported thread maps, resume handles, selected Codex subscriptions, timeline turns, timeline loading state, live deltas, and Codex goals.
- `SessionRuntime.snapshot()` asks the projection module for `bro_threads` and `bro_timeline_turns`.
- `SessionRuntime.open_bro_thread`, `close_bro_thread`, `handle_codex_thread_event`, and `handle_codex_turn_event` become delegates.
- `DirectExecutorInteraction` receives imported thread maps from the projection module, not from `SessionRuntime` fields.

## Test plan

1. Add a focused unit test for the new module interface.
2. Move or mirror selected thread event tests from `test_session_runtime.py`.
3. Keep integration tests for text/audio direct executor paths and executor node control.
4. Run focused projection/runtime tests.
5. Run full pytest.

## Steps

1. Create the new projection module with a minimal interface and failing test.
2. Move projection-owned state from `SessionRuntime` into the projection module.
3. Move imported Codex thread sync and Bro thread snapshot projection.
4. Move open/close selected Codex thread subscription behavior.
5. Move Codex thread event and Codex turn event projection behavior.
6. Update `DirectExecutorInteraction` wiring to use projection-owned maps.
7. Remove dead `SessionRuntime` helpers only after tests are green.
