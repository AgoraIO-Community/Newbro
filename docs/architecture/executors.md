# Executors

Newbro should expose a clean separation between:

- executor core abstractions
- concrete executor adapters

Stable core concepts:

- `Executor`
- `ExecutorSession`
- `ExecutorEvent`
- `ExecutorResult`
- `ExecutorCapabilities`
- `Executor Node`

Important capability directions:

- `supports_resume`
- `supports_follow_up`
- `supports_setup`

Current deployment direction:

- `mock` remains an in-process adapter
- real executors such as `codex` and `acpx` run inside the detached executor
  node
- the main Newbro API process registers hosted executor proxies rather than
  launching real executor subprocesses directly
- the control plane does not ask the operator to choose detached executor
  families; executor nodes declare their enabled families through
  `executor_node.enabled_executors` and live node registration

Executor-node note:

- the detached node owns live executor-native session continuity
- Newbro keeps durable execution lineage and user-facing control semantics
- executor-native continuity still remains optional across executor families
- Newbro persists an operator-managed executor-node registry, including
  node id, enabled executor families, and issued enrollment credentials
- detached nodes authenticate to Newbro with `node_id` and `token` on
  `WS /api/executors/control`
- the executor node's Newbro URL is a client-side runtime input passed to
  `newbro executor run --base-url ...`, not server-owned node metadata
- local executor-family/tool config no longer uses an `executor_node.enabled`
  toggle; `newbro executor run` may trigger the same local setup flow when
  executor commands or enabled families are missing
- each Bro may be bound to one executor node; a Bro is considered usable for
  Bro Detail only after the bound node has connected successfully at least once
  and is considered live only while that usable node is currently connected
  back to Newbro
- detached executor nodes connect to the main Newbro service origin through
  `WS /api/executors/control`
- foreground `newbro executor run` output should make connect, ready,
  disconnect, and retry state explicit, and should only report ready after the
  control-channel registration handshake succeeds
- Bro Detail audio instructions are node-local audio work: clients upload raw
  audio, Newbro dispatches a typed `ExecutorAudioInstruction`, and the detached
  node transcribes with local Whisper before invoking an adapter text follow-up
  path. `supports_audio_instruction` means the connected node can accept raw
  audio and produce a usable executor instruction. Whisper language defaults to
  automatic detection; foreground executor runs can override language and model
  with inline CLI arguments.
- Codex executor nodes also advertise `supports_thread_list` when they can call
  Codex app-server `thread/list`. Newbro uses that node-local capability to
  import real global Codex threads into Bro Detail without exposing raw
  native thread ids as normal UI labels.

Adapter direction:

- Codex is one real adapter family
- Codex app-server `thread/list` is the source for imported Codex dialog
  threads; `thread/read` is the required per-thread hydration path when a user
  opens/selects a thread, and `thread/resume` is required before `turn/start`
  when an imported or persisted native thread id is not yet loaded.
  `thread/start`/`thread/fork` remain run creation paths.
- Codex `agentMessage` commentary deltas are normalized into progress
  `ExecutorEvent`s so execution runs expose live user-facing progress through
  `latest_progress_message` snapshots without leaking Codex-native event
  shapes to clients
- OpenClaw or other executor families should fit behind the same normalized executor contract

This is why:

- `AgentResumeHandle` must stay optional
- runtime continuity and executor-native continuity must remain distinct concepts
- `session_affinity` should be treated as an opaque workspace id that the
  detached node resolves into a node-local directory

Related docs:

- [../protocol/execution-session-and-run.md](../protocol/execution-session-and-run.md)
- [Sessions and Runs](./api/sessions-and-runs.md)
