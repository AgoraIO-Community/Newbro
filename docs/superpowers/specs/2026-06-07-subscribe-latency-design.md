# Reduce bro-thread subscribe latency

Date: 2026-06-07
Status: Approved design

## Problem

Opening a bro thread feels slow (~3s), **and frequently times out**: switching threads
issues a redundant DELETE+POST pair, the `/subscribe` POST blocks the UI longer than
necessary, and the client serializes work that could run in parallel. Because the awaited
node round-trip is capped at 2s (see below) while Codex `thread/resume` regularly takes
longer, the POST raises `TimeoutError` → HTTP 409 ("Timed out subscribing to this
thread.") and the thread open fails outright.

## Audit of the `/subscribe` path (POST)

Handler: `api/routes/sessions.py:207` → `session.subscribe_bro_thread`
(`runtime/session.py:500`) → `bro_detail_thread_projection.subscribe_bro_thread`
(`runtime/bro_detail_thread_projection.py:430`).

| Step | Cost |
| --- | --- |
| `require_session_owner_or_internal` (auth) | depends on auth impl; unmeasured |
| `blackboard.get_persona` | in-memory (memory backend) — fast |
| `resolve_bro_thread_target` → `find_codex_thread_session_for_persona` | iterates in-memory sessions/tasks — fast |
| stop previous subscription (different thread) | fire-and-forget (`wait=False`) — non-blocking |
| `executor_node_manager.subscribe_codex_thread` | websocket round-trip to the executor node — the one awaited remote op |
| ↳ node `_subscribe_codex_thread` → `create_session` | reuses a warm shared `app-server`; cold spawn + `initialize` + `get_account` only the first time |
| ↳ node `subscribe_thread` → **`thread_resume`** | JSON-RPC; Codex loads the thread rollout — expected heavy step |

The only genuinely heavy backend work is the node round-trip dominated by Codex
`thread/resume`. All runtime bookkeeping is in-memory.

### Key discrepancy

The awaited node round-trip is capped at
`SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS = 2.0`
(`runtime/bro_detail_thread_helpers.py:27`), yet the request is observed at ~3s and
succeeds (no timeout). Therefore a meaningful slice of the latency is **outside** the
resume: browser↔backend HTTP RTT, the auth check, backend↔node transport RTT, and/or
request serialization. This must be measured, not assumed.

### Redundant DELETE on switch

On thread switch the client fires an explicit DELETE in
`useThreadSelection.selectThread` (`ui/src/lib/useThreadSelection.ts:91`), but the
subsequent POST's `_subscribe_bro_thread_locked` already stops the previous subscription
server-side (`stop_selected_codex_thread_subscription(wait=False)`,
`bro_detail_thread_projection.py:512`). The explicit DELETE is therefore redundant per
switch.

## Goal

Make opening/switching a thread fast for both the visible history and the live
subscription, **and stop opens from timing out**, without blocking the UI on Codex
`thread/resume`. (User priority: live updates fast too, accepting that a cold thread's
live stream attaches ~resume-time later as long as nothing is blocked.)

## Approach A (chosen)

Three coherent changes across UI + runtime + node, plus instrumentation. Rejected
alternatives: B (warm LRU pool of resumed threads — only path to truly-instant live on
revisit, but depends on unverified Codex multi-resume capacity; deferred) and C
(predictive pre-subscribe — speculative; deferred).

### 1. Instrumentation first (confirm the split)

Add timing around: the API handler total, the auth check, and the
`subscribe_codex_thread` round-trip; and on the node, `create_session` vs
`thread_resume`. Emit through the existing metric/logging path used elsewhere in the
runtime/node. Purpose: attribute the ~3s between transport/overhead and Codex resume
before and after the behavior changes. This is diagnostic and stays in (low-noise,
debug-level where appropriate).

### 2. Node: ack subscribe before resume (non-blocking)

`executors/node/service.py:_subscribe_codex_thread` currently awaits `subscribe_thread`
(which does `create_session` + `thread_resume`) and only then registers the streaming
task and sends the `CodexThreadSubscribedMessage` ack.

Change it to:
- Register the subscription context and send the ack **immediately** (before resume), so
  the runtime future resolves and the HTTP POST returns in ms.
- Move `create_session` + `thread_resume` into the background streaming task; begin
  streaming events once resumed.

Edge cases:
- Unsubscribe arriving before resume completes must cancel the in-flight resume and clean
  up any partially created session/process (no leak). `_stop_codex_thread_subscription`
  cancels the background task; ensure cancellation mid-resume closes the session.
- Resume failure: since the synchronous `ok=False` path is gone, emit an async error
  event on the thread-event channel so the UI can mark the subscription failed.

### Timeout behavior (fixes "opens time out too easily")

Because the ack is now sent before resume, the awaited round-trip in
`subscribe_codex_thread` only confirms "the node received and registered the
subscription" — a fast operation. So:
- The ack round-trip keeps a short timeout (the existing 2s is fine; it no longer gates
  Codex resume), so a genuinely unreachable/dead node still fails fast rather than hanging
  the open.
- The background `create_session` + `thread_resume` runs under its own, more generous
  budget (the manager's existing 8s default, or a dedicated longer bound) and never
  surfaces as a hard open failure. If it exceeds that budget or errors, it emits the async
  error event from the edge-cases section above; the thread stays open with its history
  and the live subscription is marked failed/retryable.

Net: opening a thread no longer returns HTTP 409 "Timed out subscribing" when Codex
resume is slow — the open succeeds and live attaches when ready.

### 3. Client: drop the redundant switch-DELETE + parallel open

- In `ui/src/lib/useThreadSelection.ts`, stop calling `closeThread` on thread switch in
  `selectThread` and `selectWorkspace` (the POST replaces the subscription server-side).
  Keep the DELETE only on leaving the detail view (the unmount-cleanup effect). The old
  thread's cached timeline simply remains in client state — harmless and faster on
  switch-back.
- In `ui/src/NewbroShell.tsx` `openRuntimeBroThread` (lines ~668–674), load
  `listBroTimelinePage` concurrently with `subscribeBroThread` instead of serially, so
  the visible history renders without waiting on the subscription.

## Net effect

A thread switch goes from DELETE(~3s) + serial POST(~3s) + timeline → a single
non-blocking POST with timeline loading in parallel. Cold first-open live stream is still
bounded by Codex resume, but nothing blocks. Instrumentation tells us whether a follow-up
(transport tuning or the Approach B warm pool) is warranted.

## Testing

- **Node (pytest):** `_subscribe_codex_thread` sends the ack before `subscribe_thread`
  resolves (mock a slow `subscribe_thread`, assert ack ordering); unsubscribe during a
  pending resume cancels cleanly with no leaked session; resume failure emits an error
  event on the thread-event channel.
- **Runtime (pytest):** subscribe still returns a subscribed response; replacing a
  different thread still stops the previous subscription (fire-and-forget) — existing
  `selected_codex_thread` tests stay green.
- **Timeout (pytest):** a slow `thread_resume` (longer than the ack timeout) no longer
  raises `TimeoutError`/HTTP 409 from `subscribe_bro_thread`; the subscribe returns
  subscribed and resume continues in the background. A genuinely unresponsive node (no
  ack) still fails fast within the ack timeout.
- **Client (vitest):** opening a thread loads the timeline without awaiting subscribe;
  switching threads issues no DELETE (only POST); leaving the detail issues a DELETE.
- **Instrumentation:** timing spans/logs present on handler, round-trip, create_session,
  thread_resume.

## Out of scope (deferred)

- Approach B warm subscription pool (instant live on revisit) — pending instrumentation
  confirming resume dominates and verification that one Codex app-server can hold
  multiple concurrent resumed threads.
- Any change to Codex `thread/resume` itself (Codex-side).
- Mobile-specific subscribe changes.
