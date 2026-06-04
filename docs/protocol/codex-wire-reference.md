# Codex Wire Reference (in/out JSON)

Real request/response payloads captured between the Newbro runtime and a connected
Codex executor node, for a single text turn (`"summary devx contents as a report"`)
in a resumed imported thread. Use this as ground truth when designing or debugging
timeline / turn-status / streaming behavior instead of reverse-engineering it.

- Captured: 2026-06-04, Codex CLI `0.135.0`, single executor node.
- Raw (trimmed) records: [`fixtures/codex-wire-sample.jsonl`](fixtures/codex-wire-sample.jsonl)
  (one JSON object per line: `{ts, dir, kind, payload}`).
- Long message bodies and the 15-turn history are trimmed in the fixture; field
  shapes are exact.

> **Important:** a Codex turn surfaces over **two independent channels** that the
> runtime reconciles into one `BroTimelineTurn`. Most timeline bugs come from how
> these two interleave. Read "Lifecycle & reconciliation" below.

---

## Channel A — turn-events (push, per request)

The executor pushes `CodexTurnEventMessage`s tied to the `request_id` of a dispatch.
Handled by `SessionRuntime.handle_codex_turn_event` (`runtime/session.py`).

Observed sequence for one turn (note the ~13s gap between the two):

1. **`event_type: "progress"`** — the dispatch ack, fires almost immediately.
2. **`event_type: "completed"`** — fires at the end, carrying the **full** answer
   in `message`.

Other `event_type`s the runtime maps: `plan`, `blocked`, `waiting_executor`
(→ `running`), `failed` / `cancelled` (→ `failed`). See
`_timeline_status_from_codex_event` / `_outbound_request_status_from_codex_event`.

### OUT — `start_codex_turn` (runtime → executor)

`StartCodexTurnCommand`, sent in `ExecutorNodeManager.start_codex_turn`
(`runtime/executor_node_manager.py`).

```json
{
  "type": "start_codex_turn",
  "request_id": "out-turn-bb7fd71a650f",
  "executor_type": "codex",
  "target_persona_id": "persona-atlas-b42b8ec1",
  "target_thread_id": "codex-import-8819846bc5136918",
  "thread_id": null,
  "create_new_thread": false,
  "workspace_id": null,
  "instruction": {
    "instruction_id": "txt-c4e667eb3ba3",
    "target_persona_id": "persona-atlas-b42b8ec1",
    "target_thread_id": "codex-import-8819846bc5136918",
    "text": "summary devx contents as a report",
    "source_audio_instruction_id": null,
    "metadata": {
      "source": "bro_detail_text",
      "target_thread_id": "codex-import-8819846bc5136918",
      "client_request_id": "text-1780559306958-g5lyfo",
      "plan_mode": false
    }
  },
  "latest_resume_handle": {
    "executor_id": "codex",
    "session_handle": "019e894a-5f04-7e82-a4b7-8226dc703db5",
    "turn_handle": null,
    "opaque": {
      "cwd": "/Users/USER/workspace",
      "path": "/Users/USER/.codex/sessions/2026/06/02/rollout-...-019e894a-....jsonl",
      "cliVersion": "0.135.0",
      "title": "hi",
      "listUpdatedAt": "2026-06-04T07:44:21+00:00"
    }
  },
  "metadata": { "...": "mirrors instruction.metadata + codex_thread_id + codex_import_cwd + latest_resume_handle" }
}
```

### IN — turn-event #1 `progress` (ack)

```json
{
  "type": "codex_turn_event",
  "request_id": "out-turn-bb7fd71a650f",
  "node_id": "node-a7760d2d",
  "executor_type": "codex",
  "target_persona_id": "persona-atlas-b42b8ec1",
  "target_thread_id": "codex-import-8819846bc5136918",
  "event_type": "progress",
  "message": "Direct instruction sent to Codex.",
  "executor_thread_id": "019e894a-5f04-7e82-a4b7-8226dc703db5",
  "executor_turn_id": "019e919a-e0f0-7863-baad-7d7f4aea0d9c",
  "ok": true,
  "error": null,
  "metadata": { "source": "codex", "client_request_id": "text-1780559306958-g5lyfo", "...": "..." }
}
```

### IN — turn-event #2 `completed` (final answer, ~13s later)

```json
{
  "type": "codex_turn_event",
  "request_id": "out-turn-bb7fd71a650f",
  "event_type": "completed",
  "message": "<assistant answer text omitted for privacy; ~1735 chars in the real payload>",
  "executor_thread_id": "019e894a-5f04-7e82-a4b7-8226dc703db5",
  "executor_turn_id": "019e919a-e0f0-7863-baad-7d7f4aea0d9c",
  "ok": true,
  "error": null,
  "metadata": { "...": "same shape as #1" }
}
```

**Gotcha:** in some interleavings the `completed` turn-event arrives **early with an
empty/`null` `message`** (a dispatch-level completion), and the real answer only shows
up via Channel B. The runtime now treats a content-less `completed` as still
`running` — see `_bro_timeline_turn_from_codex_turn_event` and the tests in
`tests/unit/runtime/test_session_runtime.py`.

---

## Channel B — thread history (pull, polled)

`ExecutorNodeManager.request_codex_thread(node_id, thread_id)` returns the full thread
snapshot; parsed by `_timeline_turns_from_codex_thread`. The runtime polls this
(`_sync_imported_codex_threads`, ≥5s apart) and on explicit thread open/refresh. While
a turn generates, **its `agentMessage` item text grows across successive snapshots** —
this is the "streaming" the UI renders, NOT a turn-event stream.

### IN — `request_codex_thread` snapshot (structure)

Top-level keys:

```
id, sessionId, forkedFromId, preview, ephemeral, modelProvider,
createdAt, updatedAt, status (e.g. {"type":"idle"}), path, cwd, cliVersion,
source, threadSource, agentNickname, agentRole, gitInfo, name, turns
```

Each entry in `turns[]`:

```json
{
  "id": "...",
  "status": "completed",          // "in_progress" while generating → "completed"/"failed"
  "error": null,
  "startedAt": 1780559052,         // unix seconds
  "completedAt": 1780559061,
  "durationMs": 8873,
  "itemsView": [ "...render-oriented view; ignored by the runtime..." ],
  "items": [
    { "type": "userMessage",  "id": "item-41", "text": "...", "phase": null },
    { "type": "agentMessage", "id": "item-42", "text": "<assistant answer text>", "phase": "final_answer", "memoryCitation": null }
  ]
}
```

Notes (from the captured **post-completion** snapshot):
- The runtime keys turn status off `turns[].status` (`in_progress`→`running`).
- `agentMessage.phase` was `"final_answer"` once complete; `userMessage.phase` is
  `null`. (A mid-generation snapshot may carry a different phase / a growing `text`.)
- The agentMessage item here had **no `status` field** post-completion; the parser
  reads `item.get("status")` and defaults to `"completed"`.

---

## Lifecycle & reconciliation (why timeline bugs happen here)

For one outbound turn the runtime ends up with up to two `BroTimelineTurn`s that share
`(executor_id, executor_thread_id, executor_turn_id)` and are merged by
`_merge_timeline_turn`:

- **Outbound turn** — `turn_id = "<thread>:outbound:<client_request_id>"`,
  `owner=executor`, `client_request_id` set. Built from Channel A.
- **Native turn** — `turn_id = "<thread>:codex:<executor_turn_id>"`,
  `client_request_id=null`, `source=native_history`. Built from Channel B.

The optimistic UI turn (`turn_id = "optimistic:<client_request_id>"`) is replaced by
the outbound turn; they share `client_request_id`, so the UI keys rows by
`client_request_id ?? turn_id` to avoid a remount (`lib/timelineRowKey.ts`).

**The trap:** Channel A can report `completed` *before* the answer content exists, and
the merge used to **latch** `completed` permanently. Result: the turn read as "done"
for several seconds while it was still producing (a blank gap), then streamed its
answer with no "working" indicator.

**Reliable interpretation of "is this turn still working":**
- A turn is **settled** only when it has a real assistant answer AND that answer is
  complete (terminal `turn.status` *and* the assistant message is not streaming).
- A `completed`/terminal status with **no assistant content yet** is premature →
  treat as `running`.
- An assistant message whose status is `running`/`in_progress`/`pending`/`streaming`
  means the turn is still **answering**, regardless of `turn.status`.

These rules are enforced in `_bro_timeline_turn_from_codex_turn_event` and
`_merge_timeline_turn`, and consumed by the UI's `deriveLiveTurnState` /
`LiveTurnBubble`. Tests: `tests/unit/runtime/test_session_runtime.py`
(`test_merge_*`, `test_codex_completed_event_*`).

## Re-capturing

Temporary wire-dump instrumentation is not committed. To refresh this reference, add a
small `_wire_dump(...)` append at the three boundaries (dispatch in
`start_codex_turn`; `handle_codex_turn_event`; the `request_codex_thread` result),
send one turn, then read `/tmp/codex-wire-dump.jsonl`.
