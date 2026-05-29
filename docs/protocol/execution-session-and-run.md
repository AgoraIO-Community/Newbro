# Execution Session and Run Protocol

Key objects:

- `ExecutorConfig`
- `AgentResumeHandle`
- `BroThread`
- `BroTimelineTurn`
- `BroTimelineMessage`
- `BroTimelineTask`
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
- `BroTimelineTurn`
  - canonical Bro Detail timeline read model in `SessionSnapshot`. One turn
    represents one logical user/executor exchange and carries generic
    multi-executor identity: public `thread_id`, `executor_id`, optional
    `client_request_id`, optional `executor_thread_id`, and optional
    `executor_turn_id`.
- `BroTimelineMessage`
  - user or assistant side of a canonical timeline turn. Audio transcript,
    duration, and audio id belong to the audio user message instead of creating
    a second text user message.
- `BroTimelineTask`
  - task/run state attached to a Newbro-owned timeline turn. Native executor
    history does not create this object unless Newbro actually created the
    task/run. It may expose `goal` and `plan`; `goal` is the Newbro task goal
    for Newbro-owned turns, and `plan` is normalized executor-visible plan
    state.
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
- executor-native plan state is separate from progress. Adapters emit
  `ExecutorEventType.PLAN` for documented planning surfaces, and
  `RunManager` stores the latest event under
  `ExecutionRun.metadata.latest_plan_event` without overwriting
  `latest_progress_message`.

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
- direct Bro Detail text and push-to-talk inputs must provide explicit thread
  intent: either a selected `target_thread_id` or `create_new_thread=true`, but
  never both. The backend does not infer active/latest thread ownership for
  direct sends. Follow-up tasks created for a selected `BroThread` reuse the
  thread's execution-session continuity and Codex resume handle
- direct Bro Detail text may set `plan_mode=true`. Newbro stores that flag on
  the direct instruction, task metadata, and Bro timeline user message metadata.
  The Codex adapter sends native app-server `collaborationMode.mode = "plan"`
  for that turn, resolving the required model settings from the resumed thread
  or `collaborationMode/list`. If plan collaboration settings cannot be
  resolved, the adapter fails the turn instead of running a normal execution.
  Ordinary direct text turns send `"default"` when model settings are known so
  plan mode does not stick to later work in the same native thread. Plan-mode
  tasks use `TaskMode.PROPOSAL_ONLY` until the user approves a proposal
  interaction.
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
- Opening a `BroThread` resolves the public thread id to a Codex resume handle,
  starts selected-thread event interest, and, for imported native Codex threads,
  loads native thread history into executor-owned `BroTimelineTurn` records for
  display in Bro Detail. For a known imported Codex thread, opening uses the
  cached `thread/list` projection and resume handle instead of refreshing the
  global Codex thread list on the open request path. Newbro must not project
  native Codex history into Newbro `Task`, `ExecutionRun`, or `TaskSummary`
  records just because a thread was selected. The detached executor node keeps
  one shared Codex app-server process for list/start/resume/history read and
  selected-thread event routing; selected-thread subscription records local
  event interest and must not spawn a separate app-server process. The executor
  node forwards selected-thread events back to Newbro. Ordinary text/PTT sends
  and session snapshot publishes must not block on Codex `thread/list`,
  `thread/read`, or `thread/turns/list`; imported-thread open may read history,
  but history-read failures are represented as per-thread `timeline_status =
  failed` and `timeline_error`, not as open-request conflicts. `SessionSnapshot`
  exposes `bro_timeline_turns` as the Bro Detail rendering contract.
  Newbro-owned turns are projected from typed `Task`, `ExecutionRun`, and
  `TaskSummary` state; executor-owned turns are projected from imported native
  history and selected-thread live events. The projection is a read model, not a
  durable store competing with either source. Reconciliation uses, in order,
  canonical `turn_id`, `client_request_id`, and
  `executor_id + executor_thread_id + executor_turn_id`; it does not use
  thread-level suppression or text/timestamp similarity. Native Codex history
  pairs a user-only turn with the next assistant-only turn when Codex represents
  one logical exchange as separate native records. For each native response
  turn, Newbro exposes only the latest assistant/agent message; later
  assistant/agent items or deltas for that same executor turn replace the
  displayed assistant side instead of adding another timeline entry. Codex
  goals and plans are projected only from the documented app-server goal/plan
  contract: `thread/goal/get` and `thread/goal/*` events for goals,
  `turn/plan/updated` for structured live plans, `item/plan/delta` for
  streaming plan text, and final `plan` items from `item/completed` as the
  authoritative item text. Newbro may coalesce `item/plan/delta` before writing
  plan detail records, but it must always project the final completed plan item.
  Codex `reasoning` items and reasoning deltas remain internal and must not
  become goal, plan, or progress text.
  Leaving or replacing the selected thread must call the node's selected-thread
  close path, which in turn calls Codex `thread/unsubscribe`; stale events from
  older subscription ids are ignored. Clients must render Bro Detail from the
  selected thread's canonical `bro_timeline_turns`, plus only timeline-shaped
  optimistic placeholders that are replaced by canonical turns through
  `client_request_id`; they must not infer the selected timeline by merging
  task cards, local text/audio echoes, conversation messages, and native
  messages by timestamp. Imported
  Codex thread titles are stable thread-list display labels. Opening an
  imported thread without sending a follow-up must also preserve the Codex
  `thread/list` updated time as the list sort key; only a real follow-up/direct
  send should make the thread look newly active.
- push-to-talk audio is transcribed by the executor node. Newbro carries the
  browser-uploaded PCM content and typed metadata in the executor-node command
  payload, so transcription does not depend on a shared filesystem path between
  the main backend and detached node. When a matching active Codex run exists,
  the transcript is emitted as a run progress event and Newbro turns it into a
  queued direct Codex task in the selected `BroThread`; when the Bro is idle,
  Newbro requests executor-node transcription directly and creates the queued
  direct Codex task from that transcript without requiring an active run first
- `BroThread.thread_id` is Newbro-owned UI/API identity; raw executor-native
  thread ids stay diagnostic data, not primary UI labels
- rebinding a Bro to a different executor node rotates the Bro detail generation,
  so future tasks create a new execution session
- old tasks remain durable history; clients filter recent Bro detail tasks by
  the current generation id
