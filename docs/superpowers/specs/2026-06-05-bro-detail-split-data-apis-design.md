# Bro Detail Split Data APIs — Design

## Goal

Reduce Bro Detail bootstrap and selection payloads so small clients do not pay
for unrelated session, Codex thread, or Codex turn data. The session endpoint
must stop performing hidden remote Codex work. Thread lists, turn lists, and live
thread subscription should be separate explicit APIs.

## Current Problem

The current branch already pages Codex `thread/list` and `thread/turns/list`,
but `GET /api/sessions/{session_id}` still acts as a broad bootstrap payload and
may sync the first imported Codex thread page. `POST
/api/sessions/{session_id}/bro-threads/{thread_id}/open` also mixes three
operations: resolving/selecting a thread, subscribing to live Codex events, and
hydrating an initial timeline page.

That coupling is unfriendly to small clients and makes API behavior hard to
predict. A client that only wants the Bro list or session readiness should not
trigger Codex `thread/list`. A client that only wants to subscribe to live events
should not trigger Codex `thread/turns/list`.

## Non-Goals

- Redesign the Codex event projection or multi-message turn contract.
- Remove cached/live timeline projections yet. They remain needed for live
  selected-thread reconciliation.
- Add task history pagination in this change.
- Preserve `/open` compatibility. Internal callers will move to `/subscribe`;
  external callers on this in-flight branch should update.

## API Contract

### Compact Bro Bootstrap

Add:

```http
GET /api/sessions/{session_id}/bros
```

This returns persona/Bro rows merged with only the executor-node fields the UI
needs to render readiness and setup state.

Response fields:

```json
{
  "bros": [
    {
      "persona_id": "forge",
      "name": "Forge",
      "executor_node": {
        "node_id": "node-forge",
        "name": "Mac Studio",
        "connection_status": "connected",
        "enabled_executors": ["codex"],
        "codex": {
          "version": "0.135.0",
          "minimum_version": "0.135.0",
          "availability_reason": null,
          "supports_thread_list": true,
          "supports_audio_instruction": true
        }
      }
    }
  ]
}
```

Node management fields and credentials stay under the existing executor-node
management APIs. The compact response should include only fields required by the
home page and Bro Detail shell.

### Reduced Session Snapshot

`GET /api/sessions/{session_id}` becomes local runtime state only. It must not:

- include full `personas`
- include full `executor_nodes`
- include imported Codex thread-list pages
- include `bro_thread_pages` or `bro_timeline_pages`
- trigger Codex `thread/list`
- trigger Codex `thread/turns/list`

If legacy surfaces still need task/run state, they can keep reading it from the
session snapshot for now. Bro Detail should stop relying on task/run state for
normal Codex thread rendering. Future work can split task/run data into a
dedicated recent/history endpoint.

### Thread List Pages

Keep:

```http
GET /api/sessions/{session_id}/bro-threads?target_persona_id=...&limit=25&cursor=...
```

This is the only Bro Detail API that fetches Codex `thread/list`. It returns
thread summaries and cursor metadata. The backend stores the public thread id to
resume-handle mapping for returned imported threads so later subscribe/timeline
calls can resolve the native Codex thread id without exposing it to the UI.

### Turn List Pages

Keep:

```http
GET /api/sessions/{session_id}/bro-threads/{thread_id}/timeline?target_persona_id=...&limit=15&cursor=...
```

This is the only Bro Detail API that fetches Codex `thread/turns/list`. It
returns:

- timeline turns for the requested page
- cursor metadata for the next/previous page
- the selected thread summary needed by the UI after selecting a thread

Response fields:

```json
{
  "thread": {
    "thread_id": "codex-import-d964cf9d0fbe5f81",
    "persona_id": "forge",
    "title": "Imported Codex thread",
    "status": "completed",
    "workspace_id": "/workspace",
    "workspace_name": "workspace",
    "timeline_status": "loaded",
    "timeline_error": null
  },
  "turns": [],
  "page": {
    "next_cursor": "older",
    "previous_cursor": null,
    "has_more": true,
    "status": "loaded",
    "error": null
  }
}
```

Thread summary for the selected/current thread should come from this response
after the user selects a thread, not from session snapshot side effects.

### Subscribe Endpoint

Replace `/open` with:

```http
POST /api/sessions/{session_id}/bro-threads/{thread_id}/subscribe
DELETE /api/sessions/{session_id}/bro-threads/{thread_id}/subscribe
```

`POST /subscribe`:

- validates session ownership, Bro/persona, bound executor node, and connected
  Codex capability
- resolves the public thread id to a cached resume handle from a prior thread
  list or Newbro-created thread
- starts or replaces the selected Codex thread subscription
- does not call Codex `thread/list`
- does not call Codex `thread/turns/list`
- returns a small subscribe response:

```json
{
  "thread_id": "codex-import-d964cf9d0fbe5f81",
  "persona_id": "forge",
  "subscribed": true,
  "timeline_status": "not_loaded",
  "timeline_error": null
}
```

If the public imported thread id is not cached, `POST /subscribe` fails with a
clear conflict such as "Thread is not loaded; list thread page first." This is
acceptable because normal UI selection only happens from returned thread-list
items.

`DELETE /subscribe` unsubscribes the selected Codex thread and returns the same
small response shape with `subscribed = false`.

Remove:

```http
POST /api/sessions/{session_id}/bro-threads/{thread_id}/open
DELETE /api/sessions/{session_id}/bro-threads/{thread_id}/open
```

## UI Flow

Home and Bro Detail bootstrap:

1. Load reduced session state.
2. Load compact Bro/node rows from `GET /bros`.
3. For a runtime Codex Bro detail page, call `GET /bro-threads` for the first
   visible thread page if the page is not already in UI state.

Thread selection:

1. User selects a thread returned by `GET /bro-threads`.
2. UI calls `POST /subscribe`.
3. UI calls `GET /timeline?limit=15&cursor=` for initial visible history.
4. UI stores cursor metadata from the timeline response locally.
5. "Load older" calls the same timeline endpoint with the response cursor.

Thread list paging:

1. UI stores cursor metadata from `GET /bro-threads` locally.
2. "Show more" calls `GET /bro-threads` with the next cursor.

## Runtime Ownership

`SessionRuntime.snapshot()` should not request remote Codex data by default.
`BroDetailThreadProjection` remains the owner of imported-thread cache,
resume-handle mapping, selected-thread subscription state, and live timeline
projection.

Rename runtime methods to match intent:

- `open_bro_thread` -> `subscribe_bro_thread`
- `close_bro_thread` -> `unsubscribe_bro_thread`
- `open_bro_thread_locks` -> `subscribe_bro_thread_locks`

The method body should drop timeline hydration and import-sync fallback. It
should only resolve already-known thread state and manage selected-thread event
subscription.

## Error Handling

- Unknown session: `404`
- Unknown or unowned Bro/thread/node: `404`
- Bro has no executor node: `409`
- Executor node disconnected or Codex unavailable: `409`
- Imported thread not cached for subscribe/timeline: `409` with explicit
  "list thread page first" wording
- Codex page request failure: `409` with the existing page failure detail

Do not add fallback behavior that silently calls thread-list or timeline APIs
from subscribe or snapshot.

## Testing

Backend tests should prove:

- `GET /sessions/{id}` does not call `request_codex_threads` or
  `request_codex_thread_turns`.
- `GET /bros` returns compact Bro/node rows and excludes credential/full node
  management data.
- `GET /bro-threads` is the only route that requests Codex thread pages.
- `GET /timeline` is the only route that requests Codex turn pages.
- `POST /subscribe` subscribes without requesting thread or turn pages.
- `POST /subscribe` fails clearly when the imported thread mapping is not
  cached.
- `/open` routes are removed.

Frontend tests should prove:

- Bro Detail loads compact Bro/node rows separately from session snapshot.
- Bro Detail first thread page comes from `listBroThreadsPage`.
- Selecting a thread calls `subscribeBroThread`, then `listBroTimelinePage`.
- "Load older" uses only timeline page cursors from page responses.
- No UI code calls `openBroThread` or `/open`.

Keep the Codex multi-message turn regression tests green because cached/live
timeline projections remain in use.

## Documentation Updates

Update stable docs under `docs/protocol/` and `docs/architecture/` to state:

- session snapshots do not perform remote Codex data loads
- Bro/node bootstrap, thread pages, turn pages, and subscribe are separate APIs
- `/open` is removed in favor of `/subscribe`

Append a short `docs/memories.md` note because this is an adopted runtime/API
contract change.
