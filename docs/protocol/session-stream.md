# Session Stream

The session websocket is the mixed live transport for a session:

- path: `WS /api/sessions/{session_id}/stream`
- direction: bidirectional

Client actions:

- `send_message`
  - fields:
    - `request_id`
    - `text`
- `send_command`
  - fields:
    - `request_id`
    - `command_type`
    - `task_id` or `reference`
    - optional `payload`
    - optional `reason`
- `submit_asr_turn`
  - fields:
    - `request_id`
    - `raw_text`
    - optional `normalized_text`
    - optional `confidence`
    - optional `started_at`
    - optional `ended_at`
    - optional `assigned_bro_id`

Server events:

- `snapshot`
  - carries the durable `SessionSnapshot`
  - this is the stable session-state projection, not the generic debugger dump
- `bro_list_invalidated`
  - signals that compact Bro/node rows may have changed
  - fields:
    - `reason`: `executor_node_connected`, `executor_node_disconnected`,
      `executor_node_changed`, or `persona_changed`
    - optional `node_id`
  - clients should refetch `GET /api/sessions/{session_id}/bros`; this event
    does not carry Bro/persona/node rows
- `action_accepted`
  - acknowledges a valid client action by `request_id`
- `action_rejected`
  - rejects a client action with stable `error_code` and `message`
- `assistant_response_started`
- `assistant_response_delta`
- `assistant_response_completed`
- `assistant_response_failed`
- `draft_output_started`
- `draft_output_delta`
- `draft_output_completed`
- `draft_output_failed`

Assistant stream rules:

- assistant events are correlated by the originating `request_id`
- assistant deltas are transient and are not persisted in conversation history
- only the final assistant reply is durable in `conversation_history`
- communication-model tool calls remain internal and are not exposed on the websocket

Draft stream rules:

- draft output events are emitted for websocket `submit_asr_turn`
- draft output events are correlated by the originating `request_id`
- `draft_output_delta` carries transient plain text chunks from the Draft Cleaner
- draft deltas are not persisted directly; the durable state remains the
  `DraftSession` inside the next `snapshot`
- `draft_output_completed` carries `draft_session_id` and the final plain
  `draft_text`
- `draft_output_failed` is followed by `action_rejected`

Projection rules:

- `snapshot` should only carry durable runtime state such as tasks, execution,
  summaries, bindings, and notification candidates
- conversation history should not be packed into `snapshot`; read it through a
  dedicated conversation projection
- debugger/audit payloads should not be packed into `snapshot`; read them
  through the diagnostics timeline API
- compact Bro/persona/node rows should not be packed into `snapshot`; read them
  through `GET /api/sessions/{session_id}/bros`, and use
  `bro_list_invalidated` as the live refresh signal
