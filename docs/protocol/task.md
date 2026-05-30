# Task Protocol

`Task` is the durable user-visible work item.

It is the unified logical work unit for Newbro, rather than one of two separate task systems.

Typical fields:

- `task_id`
- `root_task_id`
- `parent_task_id`
- `title`
- `goal`
- `status`
- `priority`
- `requires_confirmation`
- `interruptible`
- `depends_on_task_ids`
- `session_affinity`
- `task_revision`
- `latest_instruction`

Ownership:

- Communication Brain manipulates task intent through tools
- Execution Brain reads task state and updates execution-related projections

`newbro v0` draft-created tasks are immutable execution contracts after Send.
They store their draft source and frozen contract fields in `metadata`, including
`immutable`, `source_kind`, `draft_session_id`, `draft_snapshot_id`,
`asr_turn_ids`, and `draft_text`.

When a draft is sent to a configured runtime Bro, the task also records
`persona_id`, `persona_name`, `bro_detail_session_id`, and, when present,
`executor_node_id`. The assigned Bro may be marked `busy` as a display cache;
task ownership and execution routing are derived from task metadata,
execution-session state, and the task's executor type.

`bro_detail_session_id` identifies the Bro detail generation that created the
task. Tasks from the same generation use the same `session_affinity` and may
reuse one executor session. Rebinding the Bro to a different executor node
rotates this id for future tasks without deleting existing task history.

Relationship note:

- `Task` is not the same thing as `ExecutionSession`
- execution lineage and live binding are represented separately through execution-session, run, and binding objects

`Task` should not be the main home for:

- raw executor logs
- session internals
- low-level execution history
