# Bro Thread List Limit 15 Design

## Context

Bro Detail thread lists are loaded through explicit cursor-page APIs:

- `GET /api/sessions/{session_id}/bro-threads?target_persona_id=...&limit=...&cursor=...`
- `GET /api/sessions/{session_id}/bro-threads/{thread_id}/timeline?target_persona_id=...&limit=...&cursor=...`

The thread-list API already accepts `limit` and `cursor`, and the runtime forwards `limit` to the Codex executor node `thread/list` request. The current Newbro default and web UI page size are still 25 threads. That is more than the desktop needs at first paint and too large as a default for smaller clients such as IoT devices.

## Goal

Reduce the default Bro thread-list page size from 25 to 15 while preserving caller-controlled pagination. IoT and other lightweight clients must be able to request smaller pages explicitly through `limit`.

## Non-Goals

- Do not change selected-thread timeline page size; it remains 15.
- Do not change Codex cursor semantics or cursor encoding.
- Do not reintroduce thread lists into `SessionSnapshot`.
- Do not change the `/bros` compact Bro/node response.

## API Contract

`GET /api/sessions/{session_id}/bro-threads` keeps the same query parameters:

- `target_persona_id`: required.
- `limit`: optional integer. When omitted, Newbro uses 15.
- `cursor`: optional opaque cursor from the previous response.

The endpoint returns the existing `BroThreadPageResponse` shape. The `page.next_cursor`, `page.previous_cursor`, and `page.has_more` fields remain response-local pagination metadata.

Explicit `limit` values continue to override the default. A client may request fewer than 15 rows, such as `limit=1` or `limit=5`, and Newbro forwards that value through the runtime to the executor-node Codex thread-list request.

## Frontend Behavior

The web UI uses a single Bro thread page size of 15 for:

- first Bro thread pages loaded during shell bootstrap;
- desktop Bro Detail rail initial render;
- mobile Bro Detail drawer initial render;
- desktop and mobile "Show more" increments;
- later `listBroThreadsPage` calls with `cursor`.

The existing local expansion behavior stays intact: URL-selected threads can still auto-expand the visible count enough to bring the selected row into view.

## Data Flow

1. The browser loads compact `/bros`.
2. For each Bro that supports Codex thread listing, the browser calls `GET /bro-threads` with `limit=15` and no cursor.
3. The API route passes `limit` and `cursor` to `SessionRuntime.list_bro_thread_page`.
4. The Bro Detail thread projection passes the same `limit` and `cursor` to `ExecutorNodeManager.request_codex_threads`.
5. The Codex executor-node request uses that limit in `thread/list`.
6. The browser stores returned threads and page metadata.
7. "Show more" calls the same API with the returned next cursor and `limit=15`.

## Error Handling

Existing error handling remains unchanged. A failed first page records failed page metadata for that Bro and does not block the shell. A failed later page sets the existing shell error message. Invalid or unsupported cursor behavior continues to be handled by the executor/runtime path.

## Testing

Tests should cover:

- API/runtime defaults changed from 25 to 15.
- UI bootstrap requests `limit: 15` for Bro thread pages.
- UI "Show more" requests `limit: 15`.
- Existing client helper tests still prove explicit `limit` serializes into the query string.
- Runtime/executor projection tests still prove caller-provided `limit` is forwarded.

## Documentation

Update stable frontend docs and memories so they say desktop/mobile thread pickers and the Bro-thread page API default to 15, not 25.
