# Interaction Request and Attention

`InteractionRequest` and `AttentionItem` are the runtime objects Newbro uses
to turn executor-side blockage into actionable user-facing UI.

They complement, but do not replace:

- `Task`
- `ExecutionSession`
- `ExecutionRun`
- `TaskSummary`
- `NotificationCandidate`

## Why These Objects Exist

Before this model, blocked execution could surface only as:

- `task.status = waiting_user_input`
- `summary.needs_user_input = true`
- optional blocked notification text

That was enough to tell the user something was wrong, but not enough to let the
UI render explicit action affordances such as:

- `Allow`
- `Deny`
- `Answer`
- `Confirm`
- `Cancel`

`InteractionRequest` is the durable "what is being asked?" object.

`AttentionItem` is the presentation-facing "what should the user notice and
click?" object.

## InteractionRequest

`InteractionRequest` is created when the runtime needs a structured user
response.

Current kinds:

- `permission`
- `question`
- `confirmation`
- `plan_proposal`

Current statuses:

- `pending`
- `approved`
- `denied`
- `answered`
- `resolved`
- `cancelled`
- `expired`

Current fields include:

- `request_id`
- `task_id`
- `execution_session_id`
- `run_id`
- `executor_type`
- `kind`
- `status`
- `prompt`
- `details`
- `available_actions`
- `answer_schema`

For Bro Detail requests, `details` may include client-safe placement hints such
as `persona_id`, `target_thread_id`, `client_request_id`, and `source_kind`.
Clients use these only to place the request in the right Bro/thread surface;
resolution still targets `request_id`.
- `resume_strategy`
- `opaque`
- `created_at`
- `resolved_at`

### Current V1 Semantics

- `permission`
  - actions: `approve`, `deny`
- `question`
  - actions: `answer`
- `confirmation`
  - actions: `confirm`, `cancel`
- `plan_proposal`
  - actions: `approve`, `deny`
  - `approve` means run the selected proposal option
  - `deny` means keep planning/refine, not cancel the task

`opaque` is currently used to carry executor-native continuation data when
available.

For Codex approval and request-user-input flows, `opaque.native_response`
contains:

- request id
- method
- params

That allows Newbro to respond to the live Codex callback directly instead of
always converting the interaction into a follow-up run.

## AttentionItem

`AttentionItem` is the UI-facing object.

Current kinds:

- `permission_request`
- `question_request`
- `confirmation_request`
- `plan_proposal_request`
- `task_paused`
- `task_resumed`
- `task_blocked`
- `task_completed`

Current statuses:

- `active`
- `acted`
- `dismissed`
- `expired`

Typical fields:

- `attention_id`
- `source`
- `kind`
- `priority`
- `status`
- `title`
- `body`
- `task_id`
- `request_id`
- `actions`
- `dedupe_key`
- `metadata`
- `created_at`

In the current implementation, `AttentionItem` is rendered in the workbench
through the `AttentionPanel` component. It is not yet a floating "island"
surface.

## Current Creation Rules

### From Blocked Run

When an executor emits `ExecutorEventType.BLOCKED`:

1. `RunManager` stores:
   - `run.status = blocked`
   - `task.status = waiting_user_input`
   - `run.block_reason`
   - `run.metadata["blocked_event"]` when present
2. `SummaryManager` produces:
   - `latest_user_visible_status = "waiting_user_input"`
   - `needs_user_input = true`
3. `InteractionManager` creates:
   - one `InteractionRequest`
   - one `AttentionItem`
4. `NotificationManager` may also create an immediate blocked notification

This means a blocked task can legitimately have all of:

- a blocked run
- a waiting-user-input task state
- a summary
- a notification candidate
- an interaction request
- an attention item

Each serves a different responsibility.

### From Needs-Input Summary

If a summary has:

- `needs_user_input = true`

and no equivalent pending request exists yet, `InteractionManager` can also
create an `InteractionRequest` and `AttentionItem` from the summary alone.

## Current Resolution Rules

### HTTP

```text
POST /api/sessions/{session_id}/interaction-requests/{request_id}/resolve
```

### Websocket

```json
{
  "type": "resolve_interaction_request",
  "request_id": "...",
  "interaction_request_id": "...",
  "action": "approve|deny|answer|confirm|cancel",
  "answer_text": "..."
}
```

## Executor-Specific Continuation

### Codex

Codex now uses executor-native callback continuation for approval-like flows
when possible.

When Codex sends one of these live app-server requests:

- `item/commandExecution/requestApproval`
- `item/fileChange/requestApproval`
- `item/permissions/requestApproval`
- `execCommandApproval`
- `applyPatchApproval`
- `question/request_user_input`
- `item/tool/requestUserInput`

the adapter:

1. normalizes it into `ExecutorEventType.BLOCKED`
2. stores native callback metadata in `blocked_event.native_response`
3. pauses the event loop and waits for resolution

When the user resolves the request:

1. Newbro marks the `InteractionRequest` and `AttentionItem`
2. Newbro sends a native response back to Codex using the saved callback data
3. the same live Codex session continues the same turn

This is the preferred path for Codex approval and question flows.

For Bro Detail plan-mode turns, final Codex `item/completed` events with
`item.type = "plan"` become `InteractionRequest(kind="plan_proposal")` because
the app-server final plan item is the authoritative plan artifact. The
client-safe proposal summary/options live in `details.proposal`; approving that
proposal clears `task.metadata.plan_mode`, sets task metadata mode to
`modify_allowed`, and queues a follow-up execution turn using the approved
plan. Choosing `deny` keeps `plan_mode=true`, keeps mode `proposal_only`, and
queues a follow-up planning turn. The resolved proposal request records the
acknowledgement; active execution/refinement state belongs to the task/run
timeline or to a new pending `InteractionRequest`, not to the old proposal
card. These final-plan approval points are
non-native: the executor emits the blocked event and ends that executor run
instead of waiting for a native callback. Codex `requestUserInput` callbacks
with structured options also become plan proposals; in that native callback
path the executor payload stays in `opaque.native_response`, is sanitized
before it reaches clients, and can continue the same Codex turn.

### Generic Fallback

If no native response path is available, Newbro can still fall back to the
older V1 continuation model:

- synthesize a follow-up instruction
- queue the task again
- continue through the existing execution-session lineage

This fallback remains useful for executors that do not expose a native
interactive callback channel.

## Pause and Resume Relationship

`InteractionRequest` is not the same thing as `pause` / `resume`.

Current rules:

- `resume_task` is valid only for true paused tasks
- `waiting_user_input` tasks should be resolved through the pending
  `InteractionRequest`
- the communication brain should not treat blocked input requests as an ordinary
  resume case

## Current Limitations

- `AttentionItem` is not yet rendered as a compact island overlay
- `expired` lifecycle state is defined but not yet actively enforced
- Codex may still ask for multiple distinct approvals inside one turn when the
  model proposes multiple different commands
- the UI keeps historical acted requests/items in the snapshot rather than
  pruning them eagerly

## Related Docs

- [Task](./task.md)
- [Execution Session and Run](./execution-session-and-run.md)
- [Summary and Notification](./summary-notification.md)
- [Interruption](./interruption.md)
- [../rfcs/0009-interaction-requests-and-attention-items.md](../rfcs/0009-interaction-requests-and-attention-items.md)
