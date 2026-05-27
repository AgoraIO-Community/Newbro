# Newbro Real Codex Thread Sync And Resume Spec

## Goal

Make the Bro Detail left rail and mobile drawer show real Codex-backed dialog
threads, not task activity records. A user must be able to select a thread,
fetch that thread's `Task` records plus execution-run/timeline history, refresh
the page, and continue a text or push-to-talk dialog against the same Codex
executor thread.

The request is end-to-end behavior, not a partial backend projection or UI
mock. The goal is complete only when real text and push-to-talk sends can resume
the selected Codex thread through the running Newbro backend, connected executor
node, and browser UI.

This is a planning goal only until the compiled `GOAL.md` is explicitly run.

## Product Decisions

- Left rail entries are user-facing dialog threads, not tasks.
- The thread rail must use Codex app-server `thread/list` to import/list global
  Codex threads returned by the local Codex app-server, not only threads for
  the current cwd and not only threads Newbro created earlier. Imported threads
  become Newbro-visible thread records while still keeping Codex as the source
  for their underlying `thread_id`.
- Global imported threads must be sorted by recency descending, using
  `updatedAt` first and `createdAt` as the fallback. Cwd must not be used as a
  visibility filter.
- Local verification against `codex-cli 0.133.0` confirms `thread/list` exists
  and returns global thread metadata. This goal should implement that method
  directly; if the installed Codex app-server later lacks `thread/list`, stop
  as blocked with version/capability evidence instead of falling back.
- Newbro-owned threads remain backed by a real Codex `thread_id` through
  `ExecutionSession.latest_resume_handle`.
- Raw Codex ids stay hidden from normal UI and may appear only in diagnostics,
  logs, or debug metadata.
- Refresh preserves the selected thread in the URL, for example
  `?sid=...&thread=...`.
- Opening/selecting a thread must fetch and hydrate that thread's `Task`
  records, execution runs, progress, and assistant-output timeline from
  backend/Codex state. The selected-thread timeline must not depend only on task
  cards that happened to be loaded before the click.
- Sending text or push-to-talk audio into a selected completed thread resumes
  the same Codex thread by using the stored resume handle and creates the
  needed task/run history under that selected thread.
- `New thread` is explicit. It should select a pending fresh-thread target and
  create the real Codex thread on first send, avoiding empty Codex clutter.
- Three sends into the same selected thread should produce one left-rail thread
  with multiple task/progress entries in the main timeline, not three left-rail
  threads.
- Browser refresh continuity is in scope. Backend-restart persistence is not
  required unless the existing runtime persistence already provides it without
  broadening the implementation.

## Source Of Truth

- `AGENTS.md`
- `docs/architecture/sessions-and-runs.md`
- `docs/architecture/execution-brain.md`
- `docs/architecture/executors.md`
- `docs/architecture/communication-brain.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/protocol/task.md`
- `docs/guides/frontend-workbench.md`
- `src/newbro/protocol/session.py`
- `src/newbro/protocol/task.py`
- `src/newbro/runtime/models.py`
- `src/newbro/runtime/session.py`
- `src/newbro/execution/session_manager.py`
- `src/newbro/executors/adapters/codex/client.py`
- `src/newbro/executors/adapters/codex/executor.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/components/newbro/adapters.ts`
- `src/newbro/ui/src/components/newbro/types.ts`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`

## In Scope

- A typed runtime/API projection for real Codex-backed Bro threads.
- Thread projection derived from Newbro execution/session state and backed by
  Codex resume handles, not browser-local fake data.
- Codex thread hydration using `thread/read` when a connected Codex session can
  provide additional title/preview/status details and `Task` plus
  execution-run/timeline history.
- Codex app-server `thread/list` integration, including typed response parsing,
  global recency sorting, and import into the Newbro thread projection so the
  UI can show all Codex threads returned by the local app-server, including
  threads from other cwd values and threads not originally created by Newbro.
- Selected-thread routing for direct text and push-to-talk audio.
- Resume behavior for selected completed threads.
- Desktop left rail and mobile drawer rendering based on thread projection.
- URL persistence for selected thread across browser refresh.
- Backend/API support for opening a thread and returning the fetched `Task`,
  execution-run, progress, and assistant-output timeline for that thread.
- Unified main timeline rendering for task/progress/assistant output inside the
  selected thread.
- Focused backend and frontend tests for the exact regression.
- Stable docs and `docs/memories.md` updates for adopted runtime behavior.

## Non-Goals

- Do not reintroduce task records as fake threads.
- Do not store thread truth only in localStorage or browser-only state.
- Do not route direct text or composer push-to-talk through Communication Brain,
  Draft Brain, Agora, or connector voice paths.
- Do not create a new thread for every direct send into the same selected
  thread.
- Do not expose raw Codex thread ids as the primary user-facing label.
- Do not require backend-restart persistence unless it falls out of the existing
  blackboard/session persistence model.
- Do not implement general multi-executor thread sync beyond Codex-first typed
  contracts that stay compatible with future executors.
- Do not change visual design beyond what is required to make desktop and
  mobile show the correct real thread model.

## Architecture

```text
Bro Detail selected thread
  -> typed Newbro thread id
  -> ExecutionSession / latest_resume_handle
  -> Codex thread_id
  -> direct text or PTT transcript turn
  -> normalized task/run/progress events
  -> unified selected-thread timeline
```

The thread projection belongs to Newbro runtime/protocol state. Tasks remain
durable work items and execution sessions remain executor-side lineage; the
thread projection groups the user-visible dialog around Codex continuity
without collapsing these concepts.

The sync flow calls Codex app-server `thread/list` through the connected Codex
adapter. Newbro imports all Codex threads from that response, sorts them by
recency descending, and projects them into typed Newbro thread records. It may
hydrate individual details with `thread/read` where needed. If the local Codex
app-server does not expose `thread/list`, the goal is blocked; do not ship a
reduced Newbro-known-only sync path.

Opening a thread is a separate hydration operation. The backend must resolve
the selected Newbro thread to its Codex `thread_id` or resume handle, fetch the
thread's available `Task` records plus execution-run/timeline history from
Newbro state and Codex thread state, and return a typed selected-thread
timeline. The UI should show loading and recoverable error states for this open
operation instead of silently showing stale tasks from the previously selected
thread.

When the selected thread already has a Codex resume handle, new direct text and
PTT transcript sends must target that thread. If the selected thread has no
Codex thread yet, the first send creates it and stores the returned resume
handle before the UI treats it as a real thread.

The transport layer stays thin. APIs validate selected Bro, node/session
availability, and thread target, then dispatch typed direct executor
instructions. They do not classify user intent or call Communication Brain.

The UI consumes a runtime thread projection and selected-thread state. It must
not infer thread identity by grouping visible task cards.

## Edge Cases

- Selected thread id in URL is missing or stale: select the most recent
  valid thread for that Bro, or a pending fresh-thread target if no real thread
  exists.
- User clicks `New thread` and refreshes before sending: no empty Codex thread
  should be created; the UI can keep or clear the pending state.
- Selected Codex thread cannot be hydrated with `thread/read`: keep the Newbro
  projection and show a recoverable diagnostic, but do not fabricate a new
  thread.
- Selected Codex thread's `Task` records or execution-run/timeline history
  cannot be fetched on open: keep the selected thread intact, show a
  recoverable error/loading state, and do not display stale tasks from another
  thread.
- Codex app-server `thread/list` is missing or returns an unsupported shape:
  stop the goal as blocked and document the Codex version/capability mismatch;
  do not implement a fallback that hydrates only known Newbro-backed resume
  handles.
- Imported Codex thread has a cwd different from the current Newbro process cwd:
  still show it in global recency order. Preserve the Codex-reported cwd as
  resume metadata so sending into that thread starts Codex in the correct cwd.
- Imported Codex thread has no Newbro task history: show it as a selectable
  thread with Codex-derived title/preview/status, fetch any Codex-available
  history on open, and create Newbro task/run history only when the user sends
  into it.
- Connected node disappears before send: reject the direct instruction and keep
  the selected thread intact.
- User sends while another run in the selected thread is active: use the
  existing active-session follow-up path or queue behavior already supported by
  the runtime; do not create a duplicate thread.
- User switches between open-channel mode and push-to-talk mode: rendering stays
  unified, while only the input route changes.

## Verification

Required backend checks:

- `.venv/bin/python -m pytest tests/unit/execution/test_session_manager.py`
- `.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py`
- `.venv/bin/python -m pytest`

Required frontend checks:

- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Manual checks:

- Desktop Bro Detail left rail shows real Codex-backed threads, not task
  activity records.
- Codex `thread/list` returns global threads from multiple cwd values, and the
  left rail includes them sorted by recency descending without cwd filtering.
- Mobile Bro Detail drawer shows the same real thread model.
- Select a thread, refresh the browser, and confirm the same thread remains
  selected.
- Open an imported Codex thread with existing history and confirm Newbro fetches
  and renders that thread's `Task` records plus execution-run/timeline entries
  before any new send.
- Send three text messages into one selected thread across page refreshes and
  confirm the left rail still shows one thread while the main timeline shows
  all related task/progress/assistant output.
- Send push-to-talk audio into the selected thread and confirm it routes through
  the same direct executor path after transcription.
- Confirm direct text and PTT do not create Communication Brain conversation
  turns.
- Capture desktop and mobile browser screenshots plus relevant backend/frontend
  logs as proof.

## Done When

- `SPEC.md` and `GOAL.md` describe this real Codex thread sync/resume contract
  with measurable verification criteria.
- Runtime exposes a typed thread projection for Codex-backed Bro threads.
- The projection calls Codex app-server `thread/list` and imports/lists all
  global Codex threads returned by the connected Codex app-server.
- Imported global Codex threads are sorted by recency descending using
  `updatedAt` then `createdAt`, and cwd is not used to filter visibility.
- Imported threads appear in desktop and mobile thread lists even when they
  were not originally created by Newbro.
- If `thread/list` is missing or incompatible in the installed Codex app-server,
  the implementation is not accepted and the goal must be marked blocked with
  proof of the version/capability mismatch.
- Desktop and mobile render threads from that projection instead of task cards.
- Selected thread persists across browser refresh.
- Opening/selecting a thread fetches that thread's `Task` records plus
  execution-run/timeline history and renders it without showing stale tasks from
  another selected thread.
- Direct text and PTT audio route to the selected Codex thread and bypass
  Communication Brain.
- Sending into a completed selected thread resumes the same Codex thread with
  new task/run history instead of creating a new left-rail thread.
- `New thread` is explicit and does not create empty Codex threads before first
  send.
- Tests cover thread projection, open-thread `Task` and execution-run/timeline
  fetching, selected-thread routing, refresh restore, desktop/mobile rendering,
  and no Communication Brain leakage.
- Manual proof shows one selected Codex thread continuing across multiple sends
  and refreshes.
- The implementation is not considered complete if only tests pass; desktop and
  mobile manual E2E checks against a connected Codex executor must also pass.
