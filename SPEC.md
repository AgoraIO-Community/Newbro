# Newbro Selected Thread Live Subscribe And Auto Scroll Spec

## Goal

When a user selects or opens a Bro Detail thread, Newbro should keep that
selected thread live by subscribing to Codex app-server changes through the
executor node and should keep the visible thread pane pinned to the latest
message when new selected-thread output arrives.

The feature covers both desktop Bro Detail and mobile Bro Detail. Opening a
thread should hydrate the existing history, scroll to the bottom, start the
selected-thread live update path, and scroll again when new selected-thread
assistant/task output arrives. Updates for non-selected threads must not move
the current scroll position.

This is a planning goal only until the compiled `GOAL.md` is explicitly run.

## Current Understanding

- The browser already subscribes to Newbro session snapshots through
  `WS /api/sessions/{session_id}/stream`.
- The UI currently opens a thread through
  `POST /api/sessions/{session_id}/bro-threads/{thread_id}/open`.
- The Codex adapter already consumes app-server events while a turn is active
  through `CodexAppServerClient.next_event()`.
- Official Codex app-server docs say `thread/read` reads stored thread data
  without resuming or subscribing to it. It is suitable for history hydration,
  but not for selected-thread live updates.
- Official Codex app-server docs expose `thread/start` for fresh threads,
  `thread/resume` for continuing a stored thread, loaded-thread status/events,
  `thread/loaded/list`, and `thread/unsubscribe` for removing the current
  connection's subscription to a loaded thread.
- Thread list and open hydration currently appear request-based through
  `thread/list` and `thread/read`; selected-thread live behavior should be
  implemented by loading/subscribing the selected thread through
  `thread/start` for new Codex threads or `thread/resume` for existing Codex
  threads, then consuming app-server events from that connection.

## Product Decisions

- The executor node, not the browser, owns Codex app-server subscription.
- The browser continues to consume Newbro session stream snapshots/events.
- Do not solve selected-thread freshness with browser polling.
- Use Codex app-server's loaded-thread subscription lifecycle:
  `thread/start` for a newly created selected Codex thread, `thread/resume` for
  an existing selected Codex thread, and `thread/unsubscribe` when leaving or
  replacing the selected thread.
- Do not use `thread/read` as the selected-thread live subscription mechanism;
  it is explicitly non-subscribing.
- If Newbro already has this loaded-thread app-server event path wired for
  selected-thread behavior, keep it and prove it with tests/logs.
- If the installed Codex app-server does not support `thread/resume` /
  `thread/unsubscribe` and loaded-thread events as documented, stop as blocked
  with capability evidence instead of shipping a polling-only substitute.
- Auto-scroll should force-scroll to the bottom when a thread is opened and
  when new selected-thread output arrives, even if the user had manually
  scrolled up.
- Auto-scroll must apply to both desktop and mobile Bro Detail.

## Source Of Truth

- `AGENTS.md`
- `docs/architecture/execution-brain.md`
- `docs/architecture/executors.md`
- `docs/architecture/blackboard.md`
- `docs/protocol/session-stream.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/guides/frontend-workbench.md`
- `src/newbro/executors/adapters/codex/client.py`
- `src/newbro/executors/adapters/codex/executor.py`
- `src/newbro/executors/adapters/codex/jsonrpc.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/api/ws/executors.py`
- `src/newbro/runtime/executor_node_manager.py`
- `src/newbro/runtime/session.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`

## In Scope

- Discovering and documenting the Codex app-server loaded-thread event
  mechanism used after `thread/start` / `thread/resume`.
- Executor-node support for starting, replacing, and stopping the selected
  Codex loaded-thread subscription, including `thread/unsubscribe` cleanup.
- Backend/runtime plumbing that maps selected thread changes into typed Newbro
  state updates and session stream snapshots/events.
- Desktop Bro Detail auto-scroll on thread open and selected-thread updates.
- Mobile Bro Detail auto-scroll on thread open and selected-thread updates.
- Focused tests for subscription command flow, selected-thread update handling,
  and auto-scroll behavior.
- Stable docs and `docs/memories.md` updates if adopted runtime behavior
  changes.

## Non-Goals

- Do not redesign thread sync, thread import, or resume semantics beyond what is
  required for selected-thread live updates.
- Do not replace Newbro's browser session websocket with a browser-to-Codex
  connection.
- Do not add frontend polling loops for selected-thread freshness.
- Do not auto-scroll for non-selected thread updates.
- Do not change Communication Brain, Draft Brain, Agora, or connector voice
  behavior.
- Do not change visual design except for stable refs or attributes required for
  scrolling/tests.

## Architecture

```text
User selects BroThread
  -> UI writes selected thread to URL
  -> UI calls Newbro open-thread API
  -> Newbro hydrates thread history
  -> Newbro asks bound executor node to load/subscribe selected Codex thread
  -> executor node uses thread/start for new or thread/resume for existing
  -> executor node streams loaded-thread Codex app-server changes
  -> executor node forwards typed selected-thread events to Newbro
  -> Newbro updates blackboard/session state
  -> browser receives session stream update
  -> selected desktop/mobile thread pane scrolls to bottom
```

The executor node should own the Codex app-server lifecycle because it already
owns local Codex app-server access, cwd, auth, and executor capabilities.
Newbro runtime should own selected-thread state and publish durable typed
updates over the existing session stream. The browser should not infer updates
from raw Codex payloads and should not poll Codex or Newbro for new messages.

Selecting a new thread replaces the prior selected-thread subscription for that
Bro/session. Leaving Bro Detail, selecting `New thread`, disconnecting the node,
or switching to a different Bro must call `thread/unsubscribe` for the previous
loaded Codex thread when there is a live app-server connection and thread id.
If the app-server reports `notSubscribed` or `notLoaded`, treat cleanup as
complete but record enough diagnostic state for debugging. Stale events must
still be suppressed by selected-thread correlation.

Auto-scroll belongs in the UI. The scroll target should be the actual scrollable
thread pane, not the whole page. It should run after thread hydration/open and
after selected-thread records, visible text turns, visible audio turns, or
selected-thread conversation/task output changes.

## Edge Cases

- Selected thread has no Codex backing yet: do not start a Codex subscription
  until first send creates the real thread through `thread/start`; still scroll
  the empty/pending thread view appropriately.
- User quickly switches threads: stale subscription events for the old thread
  must not mutate or scroll the newly selected thread.
- Node disconnects while subscribed: stop the subscription, keep selected thread
  intact, and surface the existing offline state.
- Codex app-server `thread/resume` or `thread/start` fails: keep hydrated
  thread history visible and show/log a recoverable diagnostic; do not silently
  fall back to polling.
- Codex app-server `thread/unsubscribe` fails while leaving a thread: suppress
  stale events locally and surface/log the cleanup failure so it can be retried
  or diagnosed.
- Thread open returns old history and then live updates arrive: append or merge
  without duplicating turns, and scroll only after the selected thread changes.
- User manually scrolls up: approved behavior is to force-scroll to bottom on
  selected-thread open and new selected-thread output.
- Mobile drawer opens/closes: drawer scroll state must not prevent the thread
  body from scrolling to bottom after selection.

## Verification

Required discovery/proof:

- Inspect the installed Codex app-server methods/events and document the
  selected-thread loaded-thread surface used: `thread/start`, `thread/resume`,
  loaded-thread notifications, and `thread/unsubscribe`.
- If the documented loaded-thread lifecycle is unavailable in the installed
  Codex app-server, stop as blocked with the Codex version and app-server
  capability evidence.

Required backend checks:

- `.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py`
- `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_nodes.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py`

Required frontend checks:

- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run build`

Manual checks:

- Start backend/frontend and connect a Codex executor node.
- Open desktop Bro Detail, select an existing thread, and confirm the
  backend/executor calls `thread/resume` and starts consuming loaded-thread
  Codex events.
- Leave or switch away from that thread and confirm the backend/executor calls
  `thread/unsubscribe` for the previous Codex thread id.
- Confirm opening the thread scrolls the desktop thread pane to the bottom.
- Produce a new selected-thread response and confirm desktop scrolls to bottom.
- Produce or simulate an update for a non-selected thread and confirm desktop
  does not scroll.
- Repeat open/update/non-selected checks on mobile Bro Detail.

## Done When

- `SPEC.md` and `GOAL.md` describe this selected-thread subscribe and
  auto-scroll contract with measurable verification criteria.
- Implementation verifies the installed Codex app-server supports the
  documented loaded-thread lifecycle for selected-thread updates.
- Executor node uses `thread/start` for new selected Codex threads,
  `thread/resume` for existing selected Codex threads, and loaded-thread events
  for selected/opened thread updates; if this lifecycle does not exist, the goal
  is blocked with evidence rather than completed with polling.
- Selecting/opening a real Codex-backed thread starts or refreshes the
  selected-thread live update path through the executor node using
  `thread/resume`.
- Switching selected threads or leaving Bro Detail calls `thread/unsubscribe`
  for the previous selected Codex thread, or records a benign `notSubscribed` /
  `notLoaded` cleanup result.
- New selected-thread assistant/task output reaches the browser through Newbro
  session stream state/events, not through browser polling.
- Desktop Bro Detail scrolls its message pane to bottom when a thread is
  opened.
- Desktop Bro Detail scrolls to bottom when new output for the selected thread
  arrives.
- Mobile Bro Detail scrolls its message pane to bottom when a thread is opened.
- Mobile Bro Detail scrolls to bottom when new output for the selected thread
  arrives.
- Non-selected thread updates do not scroll the current desktop or mobile
  thread pane.
- Tests cover selected-thread `thread/start` / `thread/resume` /
  `thread/unsubscribe` command flow, stale subscription suppression,
  selected-thread update delivery, and desktop/mobile auto-scroll.
- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx` passes.
- `cd src/newbro/ui && bun run build` passes.
- Focused backend tests for the executor subscription/update path pass.
- Stable docs and `docs/memories.md` are updated if runtime behavior changes.
