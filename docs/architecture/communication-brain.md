# Communication Brain

The Communication Brain owns:

- acknowledgement
- pre-send draft shaping for `newbro v0`
- clarification
- user-intent understanding inside the communication loop
- direct conversational replies
- task reference resolution
- task manipulation through tools
- reading stable task summaries and details

It does not own:

- executor scheduling
- session lifecycle
- raw execution log interpretation

Core communication policy:

- typed voice/ASR runtime input follows the v1 path: utterance -> structured Draft -> Dispatch Plan -> Dispatch Gate -> Task
- Bro Detail typed input in push-to-talk mode bypasses Communication Brain and Draft Brain; if the selected Bro is idle it stores an `OutboundTurnRequest` and starts a task-free Codex turn, and if the Bro is already running Codex it sends a typed executor-node text instruction to the active executor session; direct tasks, outbound turns, and direct follow-ups suppress Communication Brain notification candidates so executor output stays on the executor timeline surface
- Bro Detail composer mic input in push-to-talk mode bypasses Communication Brain and Draft Brain after local recording; clients upload raw audio, Newbro sends the audio content over the executor-node command channel, the selected Bro's executor node transcribes it with local Whisper, and Newbro turns the resulting text into direct Codex work, starting a task-free outbound Codex turn from idle or queueing the transcript behind the active Codex turn
- the dispatch gate is deterministic and is the final authority for starting execution
- the default execution mode for draft-created work is read-only/proposal-first; code modification and side effects require explicit confirmation
- free-form utterance meaning is produced by the Communication Brain interaction-classifier boundary, not by runtime transcript keyword checks
- live ConvoAI transcript snapshots may run the interaction classifier at the configured cadence, defaulting to about 1 second, so the current Draft can update before callback finality
- live partial classification should treat concrete task-shaped context as draft-worthy once the likely work product is clear enough to draft, even before the user finishes the final request phrase
- with an active Draft, short final acceptance turns classify as confirmation unless they add correction/new task content; destination, date, budget, target, recipient, constraint, requirement, or deliverable changes are Draft corrections, not confirmations
- ordinary research, planning, search, comparison, travel-help, review, and proposal requests default to read-only/proposal modes unless the user explicitly asks for side effects
- repeated live delegation/correction classifications refine the same active Draft revision stream instead of creating one durable ASR turn per partial transcript
- final or coalesced transcript callbacks stabilize/checkpoint the live Draft when newer, but they are not the responsiveness source of truth; matching finals reuse the existing live draft revision instead of re-running classifier and draft rewrite
- final voice turns speak one short send-confirmation prompt when a Draft first becomes ready, and one more prompt after a meaningful `draft_correction` creates a new revision; duplicate finals and non-correction refinements stay UI-first and silent
- confirmation turns with no active Draft are silent no-ops, and successful sends clear the active Draft before publishing the next session snapshot
- production runtime builds a model-backed interaction classifier from the configured OpenAI-compatible provider when available; without that classifier the quiet runtime fails closed to `uncertain`/clarification for final free-form turns
- the quiet runtime returns `RuntimeDecision` objects with `should_speak`, `response_text`, UI updates, state updates, and task/plan identifiers
- draft micro-updates and low-importance progress are UI/blackboard-first and silent by default
- spoken responses are reserved for confirmation, clarification, blocked state, completion, explicit status queries, permission/risk, and urgent events
- ConvoAI voice input is Bro-detail scoped; the active Bro detail page supplies the target persona, so the communication path must not ask which Bro should handle that utterance
- Agora ConvoAI transcript and lifecycle callbacks enter through typed runtime events, and only the resulting `RuntimeDecision.should_speak` controls whether the connector returns TTS content
- Send freezes the current Draft revision id and dispatches only when that revision is still current; stale revision sends are rejected before task creation
- in `newbro v0`, ASR turns update a mutable Draft and only Send creates an immutable Task contract
- tool success is an internal fact
- user-facing replies should express action commitment
- default replies should sound like a human accepting and starting work
- bounded user-visible message history is the authoritative conversation state for follow-up context
- OpenAI-backed communication should use a traditional OpenAI-compatible chat-completions loop and replay local user-visible history each turn
- in-flight assistant replies may stream over the session websocket as transient `assistant_response_*` events while only the final assistant reply is persisted
- communication-model tool calls stay internal to the runtime and are not exposed on the frontend websocket contract
- internal runtime vocabulary should stay hidden unless the user explicitly asks for it
- invalid tool arguments from the model should be returned through the tool loop for correction instead of crashing the message transport
- invalid executor ids should be rejected before task creation, and pre-existing bad tasks should fail cleanly rather than crashing execution
- ambiguous task references should not silently fall back to the latest task; the communication brain should resolve them explicitly or ask for clarification
- short deictic control turns, current-work questions, and follow-up corrections should rely on the LLM plus focused task/bundle context rather than large local heuristic parsers
- narrow "what are you working on" style replies should still be grounded in current blackboard task state rather than free-form conversational continuity
- focused task-bundle context should be exposed to the LLM so short follow-up corrections such as "it should be X", "actually X", "to X", "from X", and "X instead of Y" can be interpreted without hardcoding domain- or language-specific parsing into the runtime
- ambiguous follow-up corrections should ask a clarification when the corrected field is not clear enough to map safely
- explicit follow-up corrections that change a focused task bundle's core identity may replace that whole bundle instead of partially mutating only one task
- task-first routing is the default; only clear social, subjective, or Newbro-meta conversation should remain pure chat
- actionable requests should usually become tasks even when phrased as questions
- fact-checking, claim verification, current-world information, and other live external-fact requests should normally route toward `create_task` rather than unsupported pure-chat answers
- when a live verification request is missing a required operand such as location, ticker, date, or target claim, the communication brain should ask a short clarification before task creation
- capability-gated requests such as checking machine state, reading the workspace, or running commands are a high-value subset of those task requests
- if only the mock executor is available, ordinary task requests should be blocked by default unless they are explicitly mock-safe
- mock-only capability-limit replies should explain the missing real executor naturally and should not fall back to generic self-service advice unless the user explicitly asks for alternatives
- there is no standalone message interpreter in the primary `v2` design; interpretation is part of Communication Brain tool use
- recent execution progress should be grounded through bounded `TaskExecutionDetailEntry` context rather than only a single latest-progress field
- automatic execution-detail context should be limited to the 5 tasks with the most recent execution-detail activity and the last 20 entries per included task
- older tasks should be inspected on demand through `query_task_detail`
- executor-native low-level transport chatter should be filtered before it reaches execution-detail context so Communication Brain sees only user-meaningful task progress

Primary tool surface:

- `create_task`
- `update_task`
- `control_task`
- `add_task_note`
- `add_constraint`
- `list_tasks`
- `query_task_summary`
- `query_task_detail`

Architecture terminology note:

- `list_tasks` here means the task-retrieval and disambiguation tool used by Communication Brain
- it does not mean an unscoped "dump every task" storage API

Tool intent defaults:

- use `add_task_note` for extra user context, examples, preferences, or clarifications on an existing task
- use `add_constraint` for execution constraints such as deadlines, formatting rules, or do-not-send instructions
- use `update_task` only for core structured task fields such as title, goal, priority, executor preference, or latest instruction
- use `list_tasks` before a write or query when the target task is uncertain
- use `create_task.mock_safe = true` only for explicit simulation, demo, or record-only tasks
- when a cancelled task is explicitly resumed conversationally, it is acceptable to create a fresh replacement task rather than reviving the cancelled task in place
- when a follow-up correction changes the core identity of a focused task bundle, it is acceptable to cancel the old bundle and create a fresh corrected bundle

`control_task.command_type` must use the canonical protocol values from
[`TaskCommandType`](../protocol/mutation-and-command.md), for example `resume_task`
rather than `resume`.

Related docs:

- [../protocol/task.md](../protocol/task.md)
- [../protocol/task-execution-detail.md](../protocol/task-execution-detail.md)
- [../protocol/mutation-and-command.md](../protocol/mutation-and-command.md)
- [Notifications and Interruptions](./notifications-and-interruptions.md)
