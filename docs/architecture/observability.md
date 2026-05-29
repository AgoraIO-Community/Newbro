# Observability

Newbro uses a diagnosis-first observability model.

The goal is to answer, within a few minutes of an incident:

- what failed
- where it failed
- which conversation, request, task, run, or notification was involved
- what changed immediately before the failure
- which dependency or executor path was involved

Observability is a backend concern alongside, not inside, the product-facing session stream.

## Signals

Phase 1 uses two diagnostic signals:

- structured backend diagnostic events
- existing runtime state projections

The structured backend events are emitted as:

- readable colorized console logs on stdout when attached to a terminal
- JSON-line logs on stdout when redirected or piped
- an in-memory per-session diagnostic event store queryable through the API

Local development note:

- diagnostics timeline polling requests are suppressed from `uvicorn.access`
  by default so local access logs keep showing user/API traffic instead of the
  frontend inspector poll loop

The existing runtime surfaces remain:

- `SessionSnapshot` for durable task and execution state
- conversation history projections
- the diagnostics timeline API for tool/blackboard inspection and backend LLM diagnostics

These serve different purposes and should not be collapsed into one stream.

Console formatting defaults:

- `SYNAPSE_LOG_FORMAT=auto`
  - terminal: pretty single-line logs
  - pipe/file: JSON lines
- `SYNAPSE_LOG_COLOR=auto`
  - enable ANSI colors only for terminal output
- `SYNAPSE_QUIET_DIAGNOSTICS_ACCESS_LOGS=true`
  - suppress access-log noise from frontend diagnostics polling
- `SYNAPSE_LOG_LLM_DETAILS=false`
  - keep LLM diagnostics summary-only by default and enable verbose prompt/message payloads only when explicitly needed

Communication LLM note:

- `comm.llm.request_built` always includes the exact built `system_messages` for
  normal message turns so the effective Communication Brain system prompt can be
  audited without enabling full verbose LLM logging
- full built `messages` payloads still require `SYNAPSE_LOG_LLM_DETAILS=true`
- notification rendering may fall back to candidate summary text so important
  task updates are still visible, but model-rendering failures must emit
  `comm.reply.failed` before the fallback is used

Execution logging note:

- low-level Codex item chatter such as `reasoning`, `webSearch`, and generic
  command-execution lifecycle events should not be promoted into normal
  task-execution detail history
- repetitive progress-time `bb.run.updated` and `bb.task.updated` refreshes may
  still exist as debug diagnostics, but normal `INFO` output should stay focused
  on semantic progress, blocking, and terminal changes
- unexpected execution exceptions should be represented as failed run/task state
  and execution-detail metadata instead of disappearing in the reconcile loop

Connector logging note:

- connector notification watcher and TTS delivery failures should be logged
  rather than swallowed silently; a single failed notification delivery may keep
  the watcher alive only when the failure is observable
- connector activation cleanup failures should be logged while preserving the
  primary activation/finalization error

## Canonical Event Shape

Diagnostic events use one stable schema with:

- identity and correlation fields:
  - `conversation_id`
  - `request_id`
  - `task_id`
  - `run_id`
  - `execution_session_id`
  - `executor_session_id`
  - `notification_id`
  - `trace_id`
- runtime classification fields:
  - `event_name`
  - `level`
  - `component`
  - `outcome`
  - `reason_code`
- operator fields:
  - `summary`
  - `details`
- reproducibility fields:
  - `app_version`
  - `git_sha`
  - `model_name`
  - `settings_fingerprint`

Every warning or error must carry a `reason_code`.

## Event Families

Phase 1 prioritizes boundary and decision events:

- API / transport:
  - `api.session.created`
  - `api.message.accepted`
  - `api.command.accepted`
  - `ws.action.accepted`
  - `ws.action.rejected`
- communication:
  - `comm.message.received`
  - `comm.tool.called`
  - `comm.reply.generated`
  - `comm.reply.failed`
  - `comm.llm.request_built`
  - `comm.llm.response_completed`
- blackboard:
  - `bb.task.created`
  - `bb.task.updated`
  - `bb.mutation.appended`
  - `bb.command.appended`
  - `bb.execution_detail.appended`
  - `bb.run.updated`
  - `bb.summary.updated`
  - `bb.notification.candidate.created`
- execution:
  - `exec.task.claimed`
  - `exec.task.classified`
  - `exec.session.created`
  - `exec.session.reused`
  - `exec.run.started`
  - `exec.run.blocked`
  - `exec.run.completed`
  - `exec.run.failed`
  - `exec.executor.unavailable`
- notification:
  - `notify.candidate.created`
  - `notify.plan.adopted`
  - `notify.delivery.deferred`
  - `notify.batch.emitted`
  - `notify.llm.request_built`
  - `notify.llm.response_completed`

## Boundaries And Storage

Observability code lives in `newbro.observability` as a first-class package.

Instrumentation is added at the runtime edges:

- HTTP and websocket request acceptance/rejection
- communication-brain reply generation and tool calls
- blackboard write subscriptions
- execution claim, session, run, and classification decisions
- notification candidate creation, defer, and emission
- notification plan adoption and task-anchoring decisions for rendered proactive updates

Execution-mode note:

- `exec.task.classified` and `bb.execution_mode.updated` are transition-oriented signals and should emit when the semantic execution mode changes, not on every elapsed-time sample while the mode remains the same.

The in-memory diagnostic store is session-scoped and non-durable.
It exists to support fast incident drill-downs during development and testing.

## Redaction

Diagnostic logs are not allowed to become a raw payload dump.

Phase 1 rules:

- do not log secrets or credentials
- sanitize tool args and long text fields
- keep LLM diagnostics summary-level by default
- always allow message-turn `system_messages` audit logging on `comm.llm.request_built`
- require explicit opt-in for verbose prompt/message payload logging
- use the diagnostic timeline for tool/blackboard inspection and backend LLM diagnostics
- keep websocket transport focused on assistant interaction and durable state updates
