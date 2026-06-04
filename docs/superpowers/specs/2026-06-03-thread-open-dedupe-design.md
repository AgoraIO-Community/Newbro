# Thread Open Dedupe Design

## Problem

After the Bro Detail Thread Projection refactor, selecting a Bro Detail thread can visibly fetch history for a long time, succeed, then immediately fetch history again. The likely failure mode is a duplicate open after a successful snapshot update, not just one slow Codex history read.

Thread opening currently mixes two operations:

- history load: Codex `thread/read`, `thread/goal/get`, and `thread/turns/list`
- selected-thread subscription: Codex `thread/resume` plus live event routing

These operations are allowed to happen during one open, but history load must be idempotent for a selected thread.

## Goals

- Selecting one Bro Detail thread starts at most one history load for `(session_id, persona_id, thread_id)` at a time.
- Opening a thread whose timeline is already `loaded` does not call Codex history read again.
- Retrying a thread whose timeline is `failed` is allowed to call Codex history read again.
- The UI does not issue duplicate HTTP open requests for the same `(bro_id, thread_id)` while one is already in flight.
- Selected-thread subscription remains correct when a loaded thread is opened again.

## Non-Goals

- Do not optimize Codex `thread/read`, `thread/goal/get`, or `thread/turns/list` latency in this change.
- Do not add fallback history behavior.
- Do not change the explicit selected/new-thread intent contract.

## Backend Design

`BroDetailThreadProjection` owns backend idempotency because it already owns `timeline_status`, `timeline_errors`, imported Codex thread state, and selected-thread subscription state.

Add an in-flight history load map keyed by public Bro Detail thread id. When `load_bro_thread_timeline` is requested:

- if the thread is `loaded`, return without calling `request_codex_thread`
- if the thread is `loading` and an in-flight task exists, await that task
- if the thread is `failed`, start a new load
- if no load exists, create one task, store it in the map, and remove it when complete

`open_bro_thread` should still ensure selected-thread subscription state after history load is skipped or completed. History idempotency must not suppress subscription replacement when selecting a different thread.

## Frontend Design

`NewbroShell` owns client-side open dedupe because desktop and mobile Bro Detail views can each create a `useThreadSelection` instance.

Add shell-level tracking for in-flight opens keyed by `bro_id:thread_id`. `openRuntimeBroThread` should:

- return early if the same key is already opening
- start a request when no request for that key is in flight
- clear the in-flight key when the request resolves or fails
- preserve the existing sequence guard so stale responses cannot overwrite a newer selected thread

`useThreadSelection` keeps local selection intent and URL updates. Its local `openedThreadRef` remains useful, but it is not the only duplicate guard.

## Error Handling

If backend history loading fails:

- set `timeline_status` to `failed`
- set `timeline_error` to the user-visible error string
- clear the in-flight load entry
- allow a later explicit open for the same thread to retry

If duplicate opens occur during a failing request, every caller must observe the same failed timeline state. The implementation must not create a second concurrent Codex history read.

## Testing

Backend:

- concurrent opens for one imported thread call `request_codex_thread` once
- opening a thread with `timeline_status=loaded` does not call `request_codex_thread`
- opening a thread with `timeline_status=failed` retries and can call `request_codex_thread`
- selected-thread subscription still runs or stays correct when history loading is skipped

Frontend:

- duplicate `openRuntimeBroThread` calls for the same `(bro_id, thread_id)` while in flight call `openBroThread` once
- a loading snapshot followed by a loaded snapshot does not schedule a second open for the same selected thread

## Verification

- Run focused backend projection/session tests.
- Run focused frontend tests for `useThreadSelection`, `NewbroShell`, and session client behavior.
- Run the full Python suite.
- Run the frontend test suite if available in the existing project scripts.
