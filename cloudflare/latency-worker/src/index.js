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
          Number(e.total_ms ?? 0), Number(s.executor_ready ?? 0), Number(s.dispatch ?? 0),
          Number(s.publish ?? 0), Number(s.ttft ?? 0), Number(s.stream ?? 0),
        ],
      });
    }
    return new Response("ok");
  },
};
