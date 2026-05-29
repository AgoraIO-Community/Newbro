# Execution Brain

The Execution Brain owns:

- runnable-task discovery
- execution of immutable `newbro v0` tasks after Send
- task claim and lease management
- agent session lifecycle
- executor dispatch
- execution-state updates
- summary refresh
- execution classification decisions
- interruption resolution on the execution side
- best-effort live run pause/cancel handling for explicit task-control commands
- detached executor-node availability and redispatch when the host reconnects

It should be driven by:

- blackboard notifications
- periodic reconciliation

Request handlers should schedule execution work and return promptly.
Long-running executor activity should continue in the background while websocket
subscribers receive updated session snapshots as blackboard state changes.

For real executors, the live executor session no longer lives inside the main
Newbro API process. Execution Brain dispatches runs to the detached executor
host and keeps durable state in Newbro while the host owns live Codex or ACPX
runtime continuity.

It should not depend on Communication Brain internals.
It should not generate final user-facing dialogue.
It should not rewrite `newbro v0` draft-created task intent after Send.

Default execution model:

- `1 task = 1 active agent session`
- tasks are durable
- execution sessions are lineage
- execution runs are disposable historical attempts
- `SessionBinding` is the current active lease/binding projection, not a permanent 1:1 identity map

Stable execution projection:

- `ExecutionMode = undecided / lightweight / managed`
- classification is owned by Execution Brain and published as blackboard state
- the first version uses elapsed-time thresholds and upgrade-only transitions

Important subsystems:

- scheduler
- assignment and claim
- session manager
- run manager
- summary manager
- reconcile loop

Execution-side interruption rule:

- explicit cancel/pause commands should update task, run, session, and binding projections promptly, even if the executor reports a late stale terminal event afterward

Execution failure visibility rule:

- unexpected executor or reconcile exceptions must become explicit failed
  task/run state with execution-detail metadata; the reconcile loop must not
  discard exceptions as if no work happened
- executor-provided resume handles are part of the executor/session contract; if
  a real executor returns an invalid resume handle, the run should fail visibly
  instead of silently dropping continuity state

Detached-host availability rule:

- if a real executor node is unavailable, the task should move into
  `waiting_executor` state rather than failing immediately
- reconnect should requeue matching waiting tasks and let normal execution
  scheduling dispatch them again

Related docs:

- [Blackboard](./blackboard.md)
- [Sessions and Runs](./api/sessions-and-runs.md)
- [Executors](./executors.md)
