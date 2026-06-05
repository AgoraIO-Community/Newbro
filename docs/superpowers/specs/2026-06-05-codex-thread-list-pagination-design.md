# Paged Codex Data Contracts Design

## Context

Bro Detail imports native Codex threads through the detached executor node's Codex app-server `thread/list` capability. The current Newbro runtime can end up importing and publishing a very large `bro_threads` array in `SessionSnapshot`. The desktop UI locally pages the rail after receiving that full array, but small clients such as IoT devices still pay for the whole payload.

The same rule applies to other Codex-backed APIs. When Codex app-server exposes `limit`, `cursor`, `nextCursor`, or `backwardsCursor`, Newbro should keep that pagination boundary in its own API and expose it to the UI. Newbro should not collapse a paged upstream contract into an unbounded snapshot field.

Newbro now requires a modern Codex app-server contract instead of supporting old compatibility shapes indefinitely.

## Decision

Newbro requires `codex-cli >= 0.135.0` for Codex executor nodes.

Codex executor nodes below this version are not supported. Setup/probe and node registration should report the detected version and mark Codex unavailable or degraded with a clear reason when the version is below `0.135.0`.

## General Paging Rule

For any upstream/local API used by Newbro that supports `limit`, `cursor`, or equivalent paging:

- Newbro request models should accept `limit` and an opaque cursor where the caller needs more than the default page.
- Newbro response models should return the items plus cursor metadata such as `next_cursor` and, when useful, `previous_cursor`.
- UI clients should load more by calling the explicit page endpoint, not by relying on an oversized `SessionSnapshot`.
- Snapshot fields may include a bounded first page or active page for continuity, but they must not be the only way to retrieve older data.
- If the upstream cursor is native to Codex, Newbro may wrap it in its own opaque cursor to preserve room for node id, persona id, workspace filters, sort direction, or future local cache metadata.

## Thread List Contract

Newbro treats Codex `thread/list` pagination as required. The executor adapter should request native thread pages with:

```json
{
  "limit": 100,
  "cursor": "<opaque cursor or null>",
  "sortKey": "updated_at",
  "sortDirection": "desc"
}
```

The adapter follows `nextCursor` only as needed. It should not use the old legacy request shape for unsupported pagination. If a `>= 0.135.0` Codex app-server rejects this contract, Newbro should surface the failure as an observable sync error instead of projecting an empty success state.

## Newbro Payload Contract

Codex pagination reduces executor-node I/O, but it is not enough by itself. Newbro must also stop broadcasting every imported Codex thread in every `SessionSnapshot`.

`SessionSnapshot.bro_threads` should include:

- Newbro-owned task/direct threads needed for the current session.
- Selected/open imported Codex threads needed to preserve the active Bro Detail view.
- A bounded first page of imported Codex thread metadata for the default thread rail.

Older imported Codex threads should be fetched through an explicit Newbro-side page request. That request returns compact `BroThread` metadata plus pagination state. It must not hydrate thread history.

Opening a thread remains the hydration boundary. Selecting an imported thread resolves the cached resume handle, subscribes to selected-thread events, and loads that one native history through `thread/read` or the existing selected-thread history path.

## Selected Thread History Contract

Codex `thread/turns/list` also supports pagination. Newbro should use it as a paged selected-thread history source rather than treating thread open as permission to load unbounded history.

The executor adapter should request turn pages with:

```json
{
  "threadId": "<native Codex thread id>",
  "limit": 100,
  "cursor": "<opaque cursor or null>",
  "sortDirection": "desc",
  "itemsView": "full"
}
```

Newbro should reverse the returned page only for display order when needed, while preserving the native page cursors. `SessionSnapshot.bro_timeline_turns` should include the active/selected thread's bounded current history page plus live turns. Older selected-thread turns should be fetched through a Newbro page endpoint that returns `BroTimelineTurn` records and cursor metadata.

`thread/read` remains useful for compact thread metadata, status, and goal setup, but it should not be used with `includeTurns=true` for large-history hydration when `thread/turns/list` can serve the page.

## Failure Behavior

When a Codex paged read fails:

- Keep the last known cached page if one exists.
- Mark the relevant list or timeline page status as failed/degraded with the error detail.
- Do not replace the page with an empty successful page.
- Do not block ordinary text, push-to-talk, or snapshot publishes on a global `thread/list` or selected-history page refresh.

This follows the project rule to represent contract failures directly instead of hiding them with fallback behavior.

## Adjacent Payload Risks

Other APIs and snapshot fields should be audited with the same rule: lists used by small clients need explicit bounds or page requests.

Already bounded, intentionally scoped, or already page-shaped:

- `recent_execution_details` is bounded in `SessionRuntime.snapshot`.
- diagnostics timeline has `after_sequence` and `limit`.
- conversation history is returned with explicit limits.
- selected Codex thread history is already separated from `thread/list`, but needs cursor propagation to Newbro/UI.

Likely follow-up candidates:

- `SessionSnapshot.agent_events` currently lists all agent events and may need a recent limit or separate page endpoint.
- `SessionSnapshot.tasks`, `execution_runs`, and `execution_sessions` are acceptable for the prototype but will need paging or session-scoped filtering once long-running usage grows.
- `bro_timeline_turns` should stay selected-thread scoped and bounded for executor-owned history; it should not become a global imported-history dump.
- workspace-file and diagnostics APIs should continue returning small metadata first and stream or page large content.

These follow-ups are separate from the Codex-backed paging change unless implementation discovers that one of them is already inflating IoT payloads.

## Testing

Add focused tests for:

- Codex probe/setup and executor-node registration rejecting or degrading versions below `0.135.0`.
- `thread/list` requests using `limit`, `cursor`, `sortKey: "updated_at"`, and `sortDirection: "desc"`.
- Newbro snapshots exposing only bounded imported Codex thread metadata.
- Fetching additional Newbro-side thread pages without hydrating thread history.
- Opening a selected imported thread still resolving the resume handle and hydrating only that thread.
- `thread/turns/list` requests using `limit`, `cursor`, `sortDirection: "desc"`, and `itemsView: "full"`.
- Fetching additional selected-thread timeline pages without refreshing the global thread list.
- Thread-list failure preserving cached data while surfacing failed sync status.

## Documentation

Update stable docs under `docs/protocol/` and `docs/architecture/` when implementation lands:

- Record the `codex-cli >= 0.135.0` requirement.
- Document the Newbro-side imported-thread page endpoint and snapshot bounds.
- Document the Newbro-side selected-thread timeline page endpoint and snapshot bounds.
- Keep `thread/read` as the per-thread hydration contract.
