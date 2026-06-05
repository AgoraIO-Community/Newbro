# Codex Thread List Pagination Design

## Context

Bro Detail imports native Codex threads through the detached executor node's Codex app-server `thread/list` capability. The current Newbro runtime can end up importing and publishing a very large `bro_threads` array in `SessionSnapshot`. The desktop UI locally pages the rail after receiving that full array, but small clients such as IoT devices still pay for the whole payload.

Newbro now requires a modern Codex app-server contract instead of supporting old compatibility shapes indefinitely.

## Decision

Newbro requires `codex-cli >= 0.135.0` for Codex executor nodes.

Codex executor nodes below this version are not supported. Setup/probe and node registration should report the detected version and mark Codex unavailable or degraded with a clear reason when the version is below `0.135.0`.

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

## Failure Behavior

When Codex thread-list refresh fails:

- Keep the last known cached thread page if one exists.
- Mark thread-list sync status as failed/degraded with the error detail.
- Do not replace the list with an empty successful page.
- Do not block ordinary text, push-to-talk, or snapshot publishes on a global `thread/list` refresh.

This follows the project rule to represent contract failures directly instead of hiding them with fallback behavior.

## Adjacent Payload Risks

Other APIs and snapshot fields should be audited with the same rule: lists used by small clients need explicit bounds or page requests.

Already bounded or intentionally scoped:

- `recent_execution_details` is bounded in `SessionRuntime.snapshot`.
- diagnostics timeline has `after_sequence` and `limit`.
- conversation history is returned with explicit limits.
- selected Codex thread history is hydrated only when opening a thread.

Likely follow-up candidates:

- `SessionSnapshot.agent_events` currently lists all agent events and may need a recent limit or separate page endpoint.
- `SessionSnapshot.tasks`, `execution_runs`, and `execution_sessions` are acceptable for the prototype but will need paging or session-scoped filtering once long-running usage grows.
- `bro_timeline_turns` should stay selected-thread scoped for executor-owned history; it should not become a global imported-history dump.
- workspace-file and diagnostics APIs should continue returning small metadata first and stream or page large content.

These follow-ups are separate from the Codex thread-list change unless implementation discovers that one of them is already inflating IoT payloads.

## Testing

Add focused tests for:

- Codex probe/setup and executor-node registration rejecting or degrading versions below `0.135.0`.
- `thread/list` requests using `limit`, `cursor`, `sortKey: "updated_at"`, and `sortDirection: "desc"`.
- Newbro snapshots exposing only bounded imported Codex thread metadata.
- Fetching additional Newbro-side thread pages without hydrating thread history.
- Opening a selected imported thread still resolving the resume handle and hydrating only that thread.
- Thread-list failure preserving cached data while surfacing failed sync status.

## Documentation

Update stable docs under `docs/protocol/` and `docs/architecture/` when implementation lands:

- Record the `codex-cli >= 0.135.0` requirement.
- Document the Newbro-side imported-thread page endpoint and snapshot bounds.
- Keep `thread/read` as the per-thread hydration contract.
