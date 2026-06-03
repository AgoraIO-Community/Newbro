# Newbro latency Worker bridge

Cloudflare Workers Analytics Engine can only be written from a Worker, so this tiny
Worker receives batched `turn.latency` records from the Newbro backend and writes a
data point per response.

## Deploy

```bash
cd cloudflare/latency-worker
npx wrangler deploy
npx wrangler secret put INGEST_TOKEN   # shared secret; must match the backend header
```

Then point the backend at the deployed Worker URL:

```bash
SYNAPSE_LATENCY_EXPORT_ENABLED=true
SYNAPSE_LATENCY_EXPORT_URL=https://newbro-latency.<your-subdomain>.workers.dev
SYNAPSE_LATENCY_EXPORT_HEADERS=Authorization=Bearer <INGEST_TOKEN>
```

## Data point schema

Each response becomes one Analytics Engine data point:

- `index1` = model name
- `blob1` = kind, `blob2` = outcome, `blob3` = request_id
- `double1` = total_ms, `double2` = executor_ready, `double3` = dispatch,
  `double4` = publish, `double5` = ttft, `double6` = stream

## Query (SQL API / Grafana)

```sql
SELECT blob1 AS kind,
       quantileWeighted(0.50)(double1) AS p50_total_ms,
       quantileWeighted(0.95)(double1) AS p95_total_ms,
       quantileWeighted(0.95)(double5) AS p95_ttft_ms
FROM newbro_turn_latency
WHERE timestamp > NOW() - INTERVAL '1' DAY
GROUP BY kind
```

Retention is ~90 days. A no-Worker alternative (Axiom etc.) accepts the same JSON
batch by direct POST if you prefer to skip the Worker — just set
`SYNAPSE_LATENCY_EXPORT_URL` to that ingest endpoint.
