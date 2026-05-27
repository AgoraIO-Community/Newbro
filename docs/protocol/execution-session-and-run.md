# Execution Session and Run Protocol

Key objects:

- `ExecutorConfig`
- `AgentResumeHandle`
- `BroThread`
- `QueuedRunRequest`
- `ExecutionSession`
- `ExecutionRun`
- `SessionBinding`
- `TaskExecutionMode`
- `ExecutionState`

Responsibilities:

- `ExecutorConfig`
  - normalized executor identity and per-run override
- `AgentResumeHandle`
  - opaque executor-native continuity handle
- `BroThread`
  - user-facing Bro Detail dialog projection backed by Newbro execution session
    state and, for Codex, a stored `AgentResumeHandle`
- `QueuedRunRequest`
  - one queued follow-up request for an active lineage
- `ExecutionSession`
  - lineage for a task under one executor family
- `ExecutionRun`
  - one concrete run inside that lineage
- `SessionBinding`
  - current active lease/binding projection
- `TaskExecutionMode`
  - current task-level execution classification projection
- `ExecutionState`
  - current runtime snapshot

Relationship note:

- task identity is durable
- session identity is executor-side lineage
- run identity is disposable
- binding is phase-based rather than permanent

Core rule:

- task identity is durable
- run identity is disposable
- `ExecutionRun.latest_progress_message` is the normalized current
  user-facing progress text; adapters may derive it from executor-native
  streams such as ACPX output chunks or Codex commentary deltas

Detached-executor additions:

- `ExecutionSession.executor_node_id`
  - identifies which detached executor node currently owns the live real-executor lineage
- `ExecutionSession.continuity_key`
  - optionally groups multiple tasks into one reusable executor-side lineage when
    they belong to the same Bro detail generation
- `SessionBinding.executor_node_id`
  - records which node the current binding is associated with
- `TaskStatus = waiting_executor`
  - task is accepted and durable state exists, but Newbro is waiting for the
    detached executor node to become available
- `RunStatus = waiting_executor`
  - the current run has been created but is waiting on detached-host availability

Workspace rule:

- `session_affinity` is an opaque workspace id, not a control-plane filesystem
  path
- the detached executor node maps that id to a node-local working directory

Bro detail continuity:

- draft-created tasks assigned to the same Bro detail generation reuse the same
  executor session when executor family and `executor_node_id` also match
- direct Bro Detail text and push-to-talk inputs can target a selected
  `BroThread`; follow-up tasks created for that selection reuse the thread's
  execution-session continuity and Codex resume handle
- New direct Bro Detail inputs create a `BroThread` projection as soon as the
  queued task is durable, even before the scheduler creates the backing
  `ExecutionSession`, so the current thread is visible immediately after send
- Newbro imports global Codex threads through the detached executor node's
  Codex app-server `thread/list` capability. Imported threads become typed
  `BroThread` projections with Newbro-owned public ids and diagnostic raw
  Codex ids; once the user sends into an imported thread, the created task
  stores the imported Codex thread id and Codex-reported cwd as a resume handle
  seed so the first Newbro `ExecutionSession` starts the node-local app-server
  in the original cwd, calls Codex `thread/resume`, and continues that native
  Codex thread. Thread import should page through Codex `thread/list` using
  `nextCursor` where the app-server supports pagination, should ask for
  updated-time descending order where supported, and must sort the imported
  result locally by Codex `updatedAt`/`createdAt` so recent resumed dialogs are
  not hidden behind the first default page. If a newer request shape is not
  accepted by the installed Codex app-server, Newbro retries with older
  compatible request shapes instead of projecting an empty thread list.
- Opening a `BroThread` is an explicit hydration operation. Newbro resolves the
  public thread id to a Codex resume handle, asks the detached executor node to
  read initial history through non-subscribing Codex `thread/read`, then starts
  the selected-thread live layer by loading/subscribing to the native thread
  with Codex `thread/resume`. The executor node forwards
  selected-thread events back to Newbro, and Newbro refreshes the public
  `BroThread` projection from `thread/read` when relevant events arrive.
  Leaving or replacing the selected thread must call the node's selected-thread
  close path, which in turn calls Codex `thread/unsubscribe`; stale events from
  older subscription ids are ignored. Hydration projects each returned turn into
  typed task, summary, and run history for the selected thread. For each
  hydrated turn, the task `goal` / `latest_instruction` carries that turn's
  synced user-side text when Codex reported one, while summaries and runs carry
  executor output. Clients must filter by the selected thread's `task_ids`
  before applying timeline limits; they must not infer the selected timeline
  from task cards that happened to be loaded earlier. Imported Codex thread
  titles are stable thread-list display labels and must not be replaced by
  hydrated task titles after the thread is opened. Opening an imported thread
  for read-only hydration must also preserve the Codex `thread/list` updated
  time as the list sort key; only a real follow-up/direct send should make the
  thread look newly active.
- push-to-talk audio is transcribed by the executor node. When a matching active
  Codex run exists, the transcript is emitted as a run progress event and Newbro
  turns it into a queued direct Codex task in the selected `BroThread`; when the
  Bro is idle, Newbro requests executor-node transcription directly and creates
  the queued direct Codex task from that transcript without requiring an active
  run first
- `BroThread.thread_id` is Newbro-owned UI/API identity; raw executor-native
  thread ids stay diagnostic data, not primary UI labels
- rebinding a Bro to a different executor node rotates the Bro detail generation,
  so future tasks create a new execution session
- old tasks remain durable history; clients filter recent Bro detail tasks by
  the current generation id
