# Hermes TUI Gateway — JSON-RPC Wire Contract

Discovery spike against the live `hermes` CLI installed at
`/Users/zhangqianze/.local/bin/hermes`.

- `hermes --version` (exact stdout):
  ```
  Hermes Agent v0.12.0 (2026.4.30)
  Project: /Users/zhangqianze/.hermes/hermes-agent
  Python: 3.11.15
  OpenAI SDK: 2.33.0
  Up to date
  ```
- Installed source root: `/Users/zhangqianze/.hermes/hermes-agent`
- Gateway server: `tui_gateway/server.py`; STDIO entrypoint: `tui_gateway/entry.py`
- The TUI's own client (the reference implementation we mirror) is
  `ui-tui/src/gatewayClient.ts`.

All schema below was read from the installed source AND confirmed against a
real captured session (see `fixtures/hermes-gateway-sample.jsonl`).

---

## 1. Launch

There is **no `hermes gateway` / `hermes tui-gateway` subcommand** for this
server — `hermes gateway` is the *messaging* gateway (Telegram/Discord/
WhatsApp). The TUI gateway is launched by spawning the Python module directly,
exactly as `ui-tui/src/gatewayClient.ts` does:

```
spawn(python, ['-m', 'tui_gateway.entry'], { cwd, env, stdio: ['pipe','pipe','pipe'] })
```

- **Base command**: the Hermes project Python interpreter.
  On this machine that is `/Users/zhangqianze/.hermes/hermes-agent/venv/bin/python3`
  (the shebang of the `hermes` launcher). The TUI resolves it via `HERMES_PYTHON`
  / `resolvePython(root)`.
- **`HERMES_GATEWAY_LAUNCH_ARGS`** (args after the base python command):
  ```
  ["-m", "tui_gateway.entry"]
  ```
- **Required environment** (the entry/client set these; the gateway depends on them):
  - `HERMES_PYTHON_SRC_ROOT` = `/Users/zhangqianze/.hermes/hermes-agent`
    (also prepended to `sys.path` by `entry.py` so installed packages win).
  - `PYTHONPATH` must contain that same project root.
  - `TERMINAL_CWD` = the working directory the agent should operate in.
    **This is how the per-session working directory is set — NOT a JSON-RPC
    param.** `session.create` ignores any `cwd` in params and reports
    `os.getenv("TERMINAL_CWD", os.getcwd())` in its result. The adapter must
    set `TERMINAL_CWD` (and spawn `cwd`) at process start.
  - `HERMES_CWD` = same dir (used by the JS client as spawn `cwd`).
- **Process model**: one long-lived process reading newline-delimited JSON-RPC
  on **stdin**, writing JSON-RPC frames on **stdout**, and human/diagnostic logs
  on **stderr**. Closing stdin (EOF) shuts the gateway down cleanly
  (`[gateway-exit] stdin EOF`). `SIGINT` is ignored; `SIGTERM`/`SIGHUP` are
  logged then exit.
- On startup the gateway emits exactly one `gateway.ready` event before reading
  any input (see §3).

---

## 2. Framing

**Newline-delimited JSON-RPC 2.0.** One JSON object per line on stdout; requests
one JSON object per line on stdin. The client splits stdout on `\n` and
`JSON.parse`s each line.

Three frame kinds appear on stdout:

| Frame | Shape |
|-------|-------|
| Request result | `{"jsonrpc":"2.0","id":<id>,"result":{...}}` |
| Request error  | `{"jsonrpc":"2.0","id":<id>,"error":{"code":<int>,"message":<str>}}` |
| Event (server-initiated) | `{"jsonrpc":"2.0","method":"event","params":{"type":<str>,"session_id":<str>,"payload":{...}}}` |

Responses are correlated to requests by the top-level `id` (echoed verbatim from
the request; the client uses string ids). **All server-pushed events use the
single JSON-RPC method name `"event"`**; the *real* event name is the
discriminator `params.type` — there are NOT distinct JSON-RPC method names per
event. Parse error → `{"jsonrpc":"2.0","error":{"code":-32700,"message":"parse error"},"id":null}`.
Unknown method → error code `-32601`.

---

## 3. Events carry a session id — multiplexing IS viable

Every event params object has **`session_id` as a top-level key** (sibling of
`type` and `payload`), set by `_emit(event, sid, payload)` in `server.py`:

```python
def _emit(event, sid, payload=None):
    params = {"type": event, "session_id": sid}
    if payload is not None:
        params["payload"] = payload
    write_json({"jsonrpc":"2.0","method":"event","params":params})
```

Because `session.create` returns distinct session ids and every subsequent event
tags `params.session_id`, **a single gateway process can multiplex multiple
sessions** and the client can route events by `params.session_id`. One
gateway process per node (multiple sessions) is sufficient; per-session
processes are NOT required.

(The only events with an empty `session_id` are global ones like
`gateway.ready` and `skin.changed`, which are not session-scoped.)

---

## 4. Request params + result shapes

Session id key is **`session_id`** everywhere — in request params AND in the
`session.create` result.

### `session.create`
- **params**: `{"cols": <int, optional, default 80>}` — **no `cwd`**; cwd comes
  from the `TERMINAL_CWD` env var (see §1).
- **result**:
  ```json
  {"session_id":"09e3ff27","info":{"model":"gpt-5.5","tools":{},"skills":{},"cwd":"/tmp/...","lazy":true}}
  ```
  The session id is `result.session_id` (8-char hex). The agent is built lazily;
  a `session.info` event with the full tool/skill/usage catalog follows shortly.

### `prompt.submit`
- **params**: `{"session_id": <str>, "text": <str>}`
- **result**: `{"status":"streaming"}` (returned immediately; the turn streams
  via events). Busy session → error code `4009` `"session busy"`.
- The answer streams as `message.delta` events and ends with `message.complete`.

### `session.steer`
- **params**: `{"session_id": <str>, "text": <str>}` (inject text into the next
  tool result without interrupting the running turn).
- **result**: `{"status":"queued"|"rejected","text":<echoed text>}`. Empty text →
  error `4002`; agent without steer support → error `4010`.

### `session.interrupt`
- **params**: `{"session_id": <str>}`
- **result**: `{"status":"interrupted"}` (returned immediately).
- See §6 for how the cancellation actually surfaces to the client.

### Blocking-prompt responses (for completeness)
- `clarify.respond` params `{"request_id":<str>,"answer":<str>}` → `{"status":"ok"}`
- `approval.respond` params `{"session_id":<str>,"choice":"approve"|"deny","all":<bool>}`
  → `{"resolved":<...>}` (resolved by session, **no `request_id`**)
- `sudo.respond` `{"request_id","password"}`, `secret.respond` `{"request_id","value"}`

---

## 5. Event params (`params.type` → `params.payload`)

All carry `params.session_id`. Human-readable text / final answer / prompt keys
are called out.

| `type` | `payload` keys | text/answer key |
|--------|----------------|-----------------|
| `gateway.ready` | `{skin}` | — (global, `session_id` empty) |
| `session.info` | full catalog: `model`, `tools`, `skills`, `cwd`, `usage`, `mcp_servers`, … | — |
| `message.start` | *(no payload)* | — (turn begins) |
| `message.delta` | `{text, rendered?}` | **`text`** (incremental answer chunk) |
| `message.complete` | `{text, usage, status, reasoning?, warning?, rendered?}` | **`text`** (final answer). `status` ∈ `complete` \| `interrupted` \| `error` |
| `tool.start` | `{tool_id, name, context}` | `name` (tool), `context` (preview) |
| `tool.progress` | `{name, preview}` | `preview` |
| `tool.complete` | `{tool_id, name, duration_s?, summary?, todos?, inline_diff?}` | `summary` |
| `tool.generating` | `{name}` | — |
| `approval.request` | `{command, pattern_key, pattern_keys, description}` | `command` / `description` (NO `request_id`; respond via `approval.respond` keyed by `session_id`) |
| `clarify.request` | `{question, choices, request_id}` | **`question`** (+ `choices`); respond via `clarify.respond` with `request_id` |
| `reasoning.delta` / `reasoning.available` | `{text}` | `text` (model reasoning) |
| `thinking.delta` | `{text}` | `text` (cosmetic spinner text, often empty) |
| `status.update` | `{kind, text}` | `text` |
| `error` | `{message}` | **`message`** |

Notes confirmed from the live capture:
- `message.delta` payload observed: `{"text":"pong"}`.
- `message.complete` (success) payload: `{"text":"pong","usage":{...},"status":"complete"}`.
- `message.complete` (interrupted) payload:
  `{"text":"Operation interrupted: ...","usage":{...},"status":"interrupted"}`.

---

## 6. Cancellation: there is NO dedicated interrupt-ack EVENT

`session.interrupt` is acknowledged **synchronously** by its JSON-RPC *result*
`{"status":"interrupted"}`. When a turn was actually running, the agent's
abort then surfaces as a **`message.complete` event whose
`payload.status == "interrupted"`** (text e.g. `"Operation interrupted: waiting
for model response (1.2s elapsed)."`). There is no separate
`session.interrupted` / `interrupt.ack` event name.

**`_HERMES_CANCELLED_EVENT` therefore is not a unique event name.** The CANCELLED
signal must be detected as:

> event `type == "message.complete"` **AND** `payload.status == "interrupted"`.

(If detection by the request result alone is preferred, the `session.interrupt`
result `{"status":"interrupted"}` is the synchronous ack.)

---

## 7. Event → ExecutorEventType mapping

| Gateway signal | ExecutorEventType |
|----------------|-------------------|
| `message.delta` | PROGRESS |
| `reasoning.delta` / `reasoning.available` / `thinking.delta` / `status.update` | PROGRESS |
| `tool.start` / `tool.progress` / `tool.complete` / `tool.generating` | PROGRESS |
| `message.complete` with `payload.status == "complete"` | COMPLETED |
| `message.complete` with `payload.status == "interrupted"` | CANCELLED (terminal) |
| `message.complete` with `payload.status == "error"` | FAILED |
| `approval.request` | BLOCKED (terminal — needs `approval.respond`) |
| `clarify.request` | BLOCKED (terminal — needs `clarify.respond`) |
| `error` event | FAILED |

Note: `message.complete` is the single terminal event for a turn; its
`payload.status` field selects COMPLETED / CANCELLED / FAILED. The interrupt-ack
is the `message.complete`+`interrupted` combination, not a standalone event.

---

## 8. Authentication

This machine is authenticated via **OpenAI Codex OAuth** (model `gpt-5.5`,
`hermes auth` shows "OpenAI Codex ✓ logged in"), so a real turn completed
("pong"). No API keys are configured; the adapter relies on whatever auth the
installed Hermes already has — the gateway does not take credentials over
JSON-RPC.

---

## 9. Fixture

`fixtures/hermes-gateway-sample.jsonl` contains every line **received from the
gateway**, verbatim, across two real sessions:

1. Session 1 (`09e3ff27`): `session.create` → `prompt.submit` ("Reply with the
   single word: pong…") → streamed through `message.complete` (status
   `complete`, text `pong`), then `session.steer` (queued) and `session.interrupt`
   (interrupted, no turn running).
2. Session 2 (`bed7f4a1`): `session.create` → a longer `prompt.submit`
   interrupted mid-turn → `session.interrupt` result, then a
   `message.complete` event with `payload.status == "interrupted"` — the
   cancellation evidence for §6.
