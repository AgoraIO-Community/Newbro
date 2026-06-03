# Response latency observability

Each assistant response emits one `turn.latency` event with a per-step breakdown,
so you can see which step of the pipeline is slow.

## Where it shows up

- **stdout logs** — the event is logged as JSON (`"event_name":"turn.latency"`),
  greppable in your cloud log viewer.
- **Diagnostics timeline** — queryable via
  `GET /api/sessions/{session_id}/diagnostics/timeline?event_prefix=turn.latency`.
- **External export** — when enabled, batched and POSTed to a configurable HTTP
  destination (see below).

## Event shape

```json
{
  "event_name": "turn.latency",
  "request_id": "<client_request_id>",
  "outcome": "completed",
  "details": {
    "total_ms": 4700,
    "model_name": "...",
    "steps": { "executor_ready": 20, "dispatch": 10, "publish": 5, "ttft": 3100, "stream": 1100 }
  }
}
```

`ttft` (dispatch → first executor token) and `stream` (first token → completion) are
usually where the time goes.

## Enabling export

Set these environment variables on the backend:

| Env var | Meaning |
|---|---|
| `SYNAPSE_LATENCY_EXPORT_ENABLED` | `true` to enable export |
| `SYNAPSE_LATENCY_EXPORT_URL` | HTTP ingest URL (a Cloudflare Worker, Axiom, Datadog, …) |
| `SYNAPSE_LATENCY_EXPORT_HEADERS` | `Header=Value;Header2=Value2` (e.g. `Authorization=Bearer <token>`) |
| `SYNAPSE_LATENCY_EXPORT_BATCH_SIZE` | events per POST (default 50) |
| `SYNAPSE_LATENCY_EXPORT_FLUSH_SECONDS` | max seconds before a partial batch flushes (default 5) |
| `SYNAPSE_LATENCY_EXPORT_QUEUE_MAX` | in-memory queue cap; drops oldest on overflow (default 1000) |

Export is non-blocking and best-effort — it never slows or breaks a response, and if
disabled (the default) everything still lands in stdout logs and the timeline.

For Cloudflare Analytics Engine, deploy the Worker bridge in
[`cloudflare/latency-worker/`](../../cloudflare/latency-worker/README.md).
