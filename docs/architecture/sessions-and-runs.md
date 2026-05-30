# Sessions and Runs

Newbro `v2` separates durable work items from execution lineage.

Core concepts:

- `Task`
  - durable logical work item
- `ExecutionSession`
  - executor-family-specific lineage for a task
- `ExecutionRun`
  - one concrete execution attempt within a session
- `SessionBinding`
  - current live binding and lease projection

Important relationship rule:

- `Task` and `ExecutionSession` are not conceptually the same object
- bindings are phase-based and lease-based, not permanent identity coupling

Default policy:

- one active task owns one active session
- one session runs one active task at a time in the first version
- multi-task concurrency is achieved primarily through multiple sessions
- task follow-ups reuse the current session when possible
- Bro Detail direct text and push-to-talk routes may select a user-facing
  `BroThread`. Active direct text follow-ups dispatch into the active run;
  no-active direct text and push-to-talk sends create an `OutboundTurnRequest`
  and ask the executor node to start a Codex turn without creating a task first.
  Idle push-to-talk transcribes through the executor node before that outbound
  turn starts.
- retries append new runs
- completed tasks can be reopened without creating duplicate tasks
- executor-family handoff creates a new execution session under the same task

This model is what lets Newbro preserve:

- stable user-facing task identity
- clear execution history
- future executor-native continuity when supported

Related docs:

- [../protocol/execution-session-and-run.md](../protocol/execution-session-and-run.md)
- [Executors](./executors.md)
