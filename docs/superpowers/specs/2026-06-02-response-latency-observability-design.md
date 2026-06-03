# Response Latency Observability — Design

Status: design (approved for planning)
Date: 2026-06-02

## Summary

Users report slow assistant responses, but there is no way to see **which step**
of the pipeline is slow on a cloud-hosted server. This adds a **per-response
latency breakdown**: time each step of a turn on the backend, emit one structured
`turn.latency` event per response, and ship those events to a **configurable HTTP
destination** (vendor-neutral) for filtering and dashboards. A Cloudflare Worker
bridge (→ Workers Analytics Engine) is documented as one example target.

The codebase already has the foundation — a structured `DiagnosticEvent` stream
with timestamps and `request_id`/`task_id`/`run_id` correlation, a queryable
`observability.store`, a sinks abstraction (`observability/sinks/`), per-domain
emitters, and a `GET /sessions/{id}/diagnostics/timeline` endpoint. This feature
adds (1) explicit per-step *durations* for a turn and (2) an HTTP **exporter sink**
to send them off-box.

## Goal / Success Criteria

- For any response, an operator can see a breakdown like
  `total 4.7s — classify 180ms, dispatch 40ms, ttft 3.1s, stream 1.1s,
  publish 60ms`, localizing the slow step.
- The breakdown is emitted as one structured event that lands in stdout logs, the
  observability store (queryable), **and** an external HTTP destination.
- Capturing/exporting latency **never blocks or slows the actual response**.

## Non-Goals

- Node/codex-internal sub-step timing (queue wait vs model time). The executor is
  measured as a backend black box (TTFT + stream); finer node-reported timing is a
  follow-up. No node or protocol changes.
- Aggregate percentile dashboards inside the app — aggregation/visualization is the
  external tool's job (the exporter ships raw per-turn records).
- Exporting the full diagnostic event stream — the exporter ships only
  `turn.latency` events in V1 (configurable later).
- UI timing panel (possible follow-up).

## Context (current behavior)

- Response pipeline entry points (`src/newbro/runtime/session.py`):
  `submit_executor_text_instruction`, `submit_executor_audio_instruction`,
  `submit_message`.
- The runtime already emits domain events around the boundaries we need to time:
  `interaction_classified`, `live_draft_stage`/`updated`, dispatch / `start_codex_turn`,
  and `handle_codex_turn_event` (codex turn events correlated to a request via
  `find_session_by_outbound_turn_request(message.request_id)`).
- Observability: `DiagnosticEvent` (`observability/schema.py`) has `ts`, correlation
  ids, `event_name`, `details`; events flow through `observability.logger.emit_event`
  to a `store` and `sinks` (`stdout`, `pretty`). Some emitters already carry
  `elapsed_seconds` / `latency_ms`.
- Correlation: the UI sends a `client_request_id` with each instruction; it maps to
  the outbound turn request and through to the codex turn events. This is the stable
  per-turn key for the whole pipeline.

## Design

### 1. `LatencyTracker` — per-turn timing accumulator

`src/newbro/observability/latency.py` (new). A small, focused component:

```python
class LatencyTracker:
    def __init__(self, *, emit, now=time.monotonic, ttl_seconds=120.0): ...
    def mark(self, key: str, step: str, *, kind=None, model_name=None) -> None:
        """Record a monotonic timestamp for `step` under turn `key`."""
    def finish(self, key: str, *, outcome="completed") -> None:
        """Compute consecutive deltas → {step: ms} + total_ms, emit a
        turn.latency event, and evict the record."""
    def sweep(self) -> None:
        """Emit a partial record (outcome='incomplete') for turns whose last mark
        is older than ttl_seconds, then evict — so hangs still surface."""
```

- Keyed by `client_request_id`. Stores only an ordered list of `(step, monotonic_ts)`
  + small metadata (`kind`, `model_name`) — **no message content**.
- `finish` computes `steps[name_i] = ts_i - ts_{i-1}` between consecutive recorded
  marks and `total_ms = last - first`; missing steps are simply absent (robust to
  turns that skip drafting, etc.).
- Best-effort: every method is wrapped so a failure is logged and swallowed — it must
  never affect the response path.
- `sweep()` is called opportunistically (e.g., on each `mark`/`finish`, cheap) and/or
  on a periodic task.

### 2. Instrumentation points (backend only)

Call `tracker.mark(client_request_id, <step>)` at these existing boundaries:

| step (mark) | where |
|---|---|
| `received` | `submit_executor_text_instruction` / `submit_executor_audio_instruction` / `submit_message` entry |
| `transcribed` | after STT, audio path only |
| `classified` | after interaction classification (`interaction_classified`) |
| `decided` | after the runtime decision / draft is ready |
| `dispatched` | at `start_codex_turn` / dispatch to the node |
| `first_token` | first `handle_codex_turn_event` for this request |
| `completed` | terminal `handle_codex_turn_event` (completed/failed/cancelled) → then `finish` |
| `published` | after the snapshot is published to the client |

Derived steps (consecutive deltas): `transcribe, classify, decide, dispatch, ttft,
stream, publish`; `total_ms = published − received`. On a failed/cancelled terminal
event, `finish(..., outcome=<status>)` still emits what was captured.

The `LatencyTracker` is owned by the session (`SessionObservability` already hangs
off the session) so the marks share the session's `emit_event`.

### 3. `turn.latency` event

`finish`/`sweep` emit a normal `DiagnosticEvent`:

```
event_name = "turn.latency"
level = "INFO", component = "runtime", outcome = "completed" | <status> | "incomplete"
request_id = <client_request_id>, task_id/run_id/executor_session_id if known
model_name = <model>
details = { "total_ms": 4700, "kind": "text"|"audio",
            "steps": {"classify":180, "decide":20, "dispatch":40,
                      "ttft":3100, "stream":1100, "publish":60} }
summary = "turn latency 4700ms"
```

Because it goes through `emit_event`, it automatically reaches stdout (greppable),
the queryable store (so `GET …/diagnostics/timeline?event_prefix=turn.latency` and
filtering by `request_id` work), and the new exporter sink — no extra wiring per
destination.

### 4. `HttpExporterSink` — vendor-neutral exporter

`src/newbro/observability/sinks/http_exporter.py` (new), registered alongside
`stdout`/`pretty`.

- Subscribes to emitted events; keeps only those whose `event_name` matches the
  configured filter (default `turn.latency`).
- **Non-blocking:** `emit` does `queue.put_nowait(record)` onto a bounded
  `asyncio.Queue` (cap ~1000). On overflow, drop the oldest and increment a
  `dropped` counter (periodically logged). It never awaits network I/O on the
  caller's path.
- A background task batches and flushes: POST a JSON **array** of records to
  `latency_export_url` with `latency_export_headers`, flushing when the batch
  reaches the size limit (~50) or the flush interval (~5s) elapses, whichever first.
- Bounded retries with exponential backoff on transient failures; after the cap,
  drop the batch and log (never accumulate unboundedly). All exporter errors are
  swallowed — they must not affect responses.
- Disabled (`latency_export_enabled=false` or no URL) → a no-op sink.

Payload record (flat, tool-agnostic):
```json
{ "event": "turn.latency", "ts": "2026-06-02T19:00:00Z",
  "request_id": "r-abc", "kind": "text", "model_name": "...",
  "outcome": "completed", "total_ms": 4700,
  "steps": { "classify": 180, "dispatch": 40, "ttft": 3100, "stream": 1100, "publish": 60 } }
```
Works as-is for Axiom / Datadog / Honeycomb / an OTLP collector, or for the
Cloudflare Worker bridge (Appendix A).

### 5. Configuration (`Settings`)

- `latency_export_enabled: bool = False`
- `latency_export_url: str | None = None`
- `latency_export_headers: dict[str, str] = {}` (e.g. `{"Authorization": "Bearer …"}`)
- `latency_export_event_filter: str = "turn.latency"`
- `latency_export_batch_size: int = 50`, `latency_export_flush_seconds: float = 5.0`,
  `latency_export_queue_max: int = 1000`

Loaded the same way as existing runtime settings; the sink is wired in
`observability/bootstrap.py` only when enabled.

## Error Handling

The tracker and exporter are strictly best-effort: any exception in marking,
computing, or exporting is caught and logged at most once, and the response path is
unaffected. Unfinished turns become `outcome=incomplete` via `sweep` so a hang is
visible rather than silently missing.

## Testing

- **`LatencyTracker`** (unit): marks → expected `{step: ms}` + total with a fake
  clock; missing intermediate steps are omitted; `finish` emits exactly one event
  and evicts; `sweep` emits `incomplete` past TTL; a raising `emit` is swallowed.
- **`HttpExporterSink`** (unit): non-`turn.latency` events ignored; `emit` never
  blocks; batches flush on size and on interval (fake clock); overflow drops oldest
  + counts; transient POST failure retried then dropped; URL+headers from config;
  disabled = no-op; payload JSON shape matches the contract.
- **Pipeline** (focused): driving a simulated turn through the marks yields one
  `turn.latency` event with the expected step keys and `total_ms` ≈ sum of steps.

## Files

- Create: `src/newbro/observability/latency.py` (+ test).
- Create: `src/newbro/observability/sinks/http_exporter.py` (+ test).
- Modify: `src/newbro/observability/bootstrap.py` (wire tracker + exporter sink when
  enabled); `src/newbro/runtime/config.py` (settings); `src/newbro/runtime/session.py`
  (add the `mark`/`finish` calls at the boundaries in §2).
- Create: `cloudflare/latency-worker/` — the example Worker bridge (Appendix A):
  `wrangler.toml`, `src/index.js`, `README.md`.
- Docs: a short `docs/guides/response-latency.md` (enabling export, the event shape,
  querying).

## Appendix A — Cloudflare Worker bridge (example target)

Only a Worker can write to Analytics Engine, so the backend POSTs batches to a small
Worker that calls `writeDataPoint`.

`cloudflare/latency-worker/wrangler.toml`:
```toml
name = "newbro-latency"
main = "src/index.js"
compatibility_date = "2026-01-01"

[[analytics_engine_datasets]]
binding = "LATENCY"
dataset = "newbro_turn_latency"
```

`cloudflare/latency-worker/src/index.js`:
```js
export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("method", { status: 405 });
    if (req.headers.get("authorization") !== `Bearer ${env.INGEST_TOKEN}`)
      return new Response("unauthorized", { status: 401 });
    let events;
    try { events = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
    if (!Array.isArray(events)) events = [events];
    for (const e of events) {
      const s = e.steps ?? {};
      env.LATENCY.writeDataPoint({
        indexes: [String(e.model_name ?? "unknown")],
        blobs: [String(e.kind ?? ""), String(e.outcome ?? ""), String(e.request_id ?? "")],
        doubles: [
          Number(e.total_ms ?? 0), Number(s.classify ?? 0), Number(s.decide ?? 0),
          Number(s.dispatch ?? 0), Number(s.ttft ?? 0), Number(s.stream ?? 0),
          Number(s.publish ?? 0),
        ],
      });
    }
    return new Response("ok");
  },
};
```

Deploy: `cd cloudflare/latency-worker && npx wrangler deploy`; set the shared secret
with `npx wrangler secret put INGEST_TOKEN`. Then on the backend set
`latency_export_url = <worker-url>` and
`latency_export_headers = {"Authorization": "Bearer <same token>"}`.

Query (SQL API) / Grafana:
```sql
SELECT blob1 AS kind,
       quantileWeighted(0.50)(double1) AS p50_total_ms,
       quantileWeighted(0.95)(double1) AS p95_total_ms,
       quantileWeighted(0.95)(double5) AS p95_ttft_ms
FROM newbro_turn_latency
WHERE timestamp > NOW() - INTERVAL '1' DAY
GROUP BY kind
```
(`double1..7` map to total, classify, decide, dispatch, ttft, stream, publish in the
order written above.) Retention ≈ 90 days.

**Cost (verify on Cloudflare's current pricing — figures ≈ early 2026):** billed on
data points written + read queries. One data point per response: at 10k
responses/day (~300k/month) you are comfortably within the free tier; paid Workers
($5/mo) includes ~10M data points/month. Effectively free at typical volume.
A no-Worker alternative (Axiom et al.) accepts the same JSON batch by direct POST if
you prefer to skip the Worker.
