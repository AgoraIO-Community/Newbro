<goal>
Implement Bro Detail node-usability gating: a runtime Bro must have a user-owned executor node that has connected successfully at least once before normal Bro Detail can unlock. If the Bro has such a usable node but that node is not currently connected, Bro Detail remains visible but all talk/voice input is blocked with a clear warning. If node connectivity changes during an active voice session, keep the session UI/state but display the warning and prevent further talk actions until the node reconnects.
</goal>

<context>
Read first:
- AGENTS.md project instructions in the repo root or conversation.
- docs/architecture/public-onboarding-and-ownership.md
- docs/guides/public-hosted-deployment.md
- docs/architecture/executors.md
- docs/guides/frontend-workbench.md
- docs/memories.md
- src/newbro/ui/src/NewbroShell.tsx
- src/newbro/ui/src/components/newbro/BroDetailPage.tsx
- src/newbro/ui/src/components/newbro/TopVoiceBar.tsx
- src/newbro/ui/src/components/newbro/NodesPage.tsx
- src/newbro/ui/src/components/newbro/adapters.ts
- src/newbro/ui/src/components/newbro/types.ts
- src/newbro/ui/src/lib/session-client.ts
- src/newbro/ui/src/__tests__/App.test.tsx
- src/newbro/api/routes/executor_nodes.py
- src/newbro/executors/node/registry.py
- src/newbro/runtime/executor_node_manager.py
- src/newbro/api/ws/executors.py
- src/newbro/types or equivalent protocol/model files for `ExecutorNodeRecord`

Useful discovery commands:
- rg -n "last_connected_at|last_seen_at|connection_status|connected_executors|ExecutorNodeRecord" src/newbro tests docs
- rg -n "BroSetupGate|bro-setup-gate|executorNodeId|ShellVoiceBar|voice-session-start|setVoiceTarget|clearVoiceTarget" src/newbro/ui/src
- rg -n "createExecutorNode|updatePersona|revealExecutorNodeConnectCommand|buildExecutorRunCommand" src/newbro/ui/src src/newbro/api tests
- rg -n "executor_node_id|current_task_id|waiting_executor|usable|connected" src/newbro docs tests
</context>

<constraints>
- Preserve Communication Brain, Execution Brain, Shared Blackboard, and transport boundaries.
- Treat protocol models and live snapshots as the source of truth; do not add UI-only fake node usability.
- Do not hard-code demo shortcuts, transcript keywords, or local-only rules that pretend a node is usable.
- Do not unlock normal Bro Detail immediately after node creation or Bro binding. A node becomes usable only after persisted/runtime state proves it has connected successfully at least once.
- Prefer existing node fields for usability if they are semantically correct. `last_connected_at` is the preferred signal if it is persisted on successful executor connection. If the existing backend cannot distinguish "ever connected" from "currently seen", add a minimal protocol/backend field or persisted timestamp instead of overloading ambiguous UI state.
- Keep owner scoping intact. User A must not see, bind, reveal, or use User B's nodes or commands.
- Do not expose node tokens except through existing create/reveal credential flows.
- Do not tear down an already-running voice session solely because the node disconnects unless existing voice runtime code requires cleanup. The required behavior is warning plus blocking further talk/start actions.
- If the Bro has no usable node, normal Bro Detail workspace must not be visible or usable.
- If the Bro has a usable node that is currently disconnected, normal Bro Detail may be visible, but voice start, mic/talk input, and draft-from-voice actions must be blocked.
- Keep UI consistent with existing Newbro visual patterns; avoid nested cards and marketing copy.
- Update stable docs and docs/memories.md for adopted behavior changes.
</constraints>

<done_when>
- `GOAL.md` is a focused contract for node usability and availability gating, with no stale logout-only or deployment scope.
- The implementation defines a clear helper or equivalent derivation for Bro node state with at least these states: no bound node, bound node never connected, usable node currently disconnected/unavailable, usable node currently connected.
- The node usability signal is backed by protocol/backend snapshot data, preferably `last_connected_at`, and the implementation documents or tests why that signal means "connected successfully at least once".
- Bro Detail setup gate is shown when the runtime Bro has no bound node or the bound node has never connected successfully.
- After setup creates and binds a node, the setup gate continues to show the local executor command and does not unlock normal Bro Detail until a refreshed or streamed snapshot shows the bound node has connected successfully at least once.
- If the setup gate is waiting for first connection, the UI clearly says the user should run the local executor command and is waiting for the node connection.
- If the Bro has a usable node with `connection_status` not currently connected, normal Bro Detail is visible but voice start/talk controls are disabled or replaced by a blocked state.
- When a usable node is disconnected, the UI shows a persistent warning explaining that the local node is not connected and that the user should run or reconnect the executor command.
- The disconnected-usable-node warning provides a path to copy or reveal the local executor command when the existing credential APIs permit it.
- `setVoiceTarget` is not called for Bros with no usable node. If the node is usable but currently disconnected, voice target behavior is either intentionally preserved or skipped, and tests/documentation make the choice explicit.
- If a node changes from connected to disconnected while Bro Detail is open, the route remains on Bro Detail, existing draft/session UI state remains visible, a warning appears, and further talk/start actions are blocked.
- If a node changes from disconnected to connected while Bro Detail is open, the warning clears and talk/start actions become available again.
- Already-bound, usable, currently-connected Bros behave as before: normal Bro Detail appears and voice start works.
- Setup failure still shows a clear error and does not unlock Bro Detail.
- Stable docs describe the distinction between a created node, a usable node that has connected once, and a currently connected node.
- docs/memories.md contains a short factual note for the adopted usable-node and disconnected-node Bro Detail behavior.
- Focused frontend tests cover: never-connected bound node stays gated; create/bind does not unlock until first successful connection snapshot; usable disconnected node shows normal detail but blocks talk with warning; live connected-to-disconnected snapshot blocks talk without leaving detail; disconnected-to-connected snapshot re-enables talk.
- Existing frontend tests for logout, basic Bro Detail, and waiting-executor command behavior still pass or are updated to reflect the new usability semantics.
- Frontend build passes.
- If backend/protocol persistence is touched, focused backend tests prove successful executor connection marks the node as ever-connected and that this survives snapshot reload; full backend tests pass.
</done_when>

<workflow>
1. Check git status and preserve unrelated changes.
2. Read the context files and inspect current node model fields, especially `last_connected_at`, `last_seen_at`, and `connection_status`.
3. Determine whether existing backend state already persists "connected successfully at least once". Prefer `last_connected_at` if it is set only on successful executor connection and included in session snapshots.
4. If the existing protocol cannot reliably represent "ever connected", add the smallest backend/protocol change needed so snapshots expose that fact. Keep ownership and token boundaries unchanged.
5. Add or centralize a frontend node-state derivation helper:
   - no bound node;
   - bound node missing from snapshot;
   - bound node never connected;
   - usable node disconnected/unavailable;
   - usable node connected.
6. Replace the current Bro Detail gate condition from "has executorNodeId" to "has a usable bound node".
7. Update the setup gate:
   - create and bind node as before;
   - build/copy/show local executor command;
   - enter a waiting-for-first-connection state;
   - unlock only when refreshed or streamed shell state shows the bound node has connected at least once.
8. Add disconnected usable-node UI:
   - show normal Bro Detail;
   - show persistent warning;
   - provide command reveal/copy path if available;
   - block voice start and mic/talk actions.
9. Handle live snapshot transitions by deriving availability every render from shell state, not from one-time setup state.
10. Ensure active voice session UI is not forcibly discarded on node disconnect. Keep current session/draft state visible, but prevent further talk/start actions and show the warning.
11. Update or add tests for every `done_when` behavior. Update older fixtures that used `executor_node_id` alone to include the new first-connected signal when they intend an already-usable Bro.
12. Update stable docs and docs/memories.md.
13. Run focused frontend tests, then frontend build. If backend/protocol files changed, run focused backend tests and full backend tests.
14. Review final diff for unrelated churn, hidden pre-usability voice controls, ambiguous node-state naming, and stale docs.
</workflow>

<verification_loop>
Focused frontend checks:
- cd src/newbro/ui && bun run test src/__tests__/App.test.tsx
- cd src/newbro/ui && bun run build

Backend checks, only if backend/protocol files changed:
- .venv/bin/python -m pytest tests/integration/api/test_public_auth_onboarding.py
- .venv/bin/python -m pytest tests/unit tests/integration/api
- .venv/bin/python -m pytest

Manual browser smoke check when feasible:
- Open a Bro whose bound node has never connected and confirm only the setup/waiting gate appears.
- Create/bind a node and confirm the command remains visible while the UI waits for first connection.
- Start the local executor command and confirm Bro Detail unlocks after the node first connects.
- Stop the executor and confirm Bro Detail remains visible, warning appears, and talk/start is blocked.
- Restart the executor and confirm the warning clears and talk/start is available again.
- If a voice session is already open when the node disconnects, confirm the session UI/state remains visible while warning and input blocking appear.

Audits:
- rg -n "executorNodeId|last_connected_at|connection_status|voice-session-start|setVoiceTarget" src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/components/newbro src/newbro/ui/src/__tests__/App.test.tsx
- rg -n "created node|usable node|connected once|disconnected" docs/architecture docs/guides docs/memories.md

If a check cannot run, document why, what was run instead, and the remaining risk.
</verification_loop>

<execution_rules>
- Check git status before edits.
- Preserve unrelated user changes.
- Prefer `rg` over `grep` when available.
- Use `apply_patch` for manual file edits.
- Read context files before implementation.
- Batch independent file reads in parallel when available.
- Run focused tests before broad tests.
- Do not paper over failures.
- Do not widen scope beyond usable-node and node-availability Bro Detail gating.
- Keep final answer concise.
</execution_rules>

<output_contract>
Final output must include:
- Summary of the usable-node definition implemented.
- Summary of no-usable-node setup-gate behavior.
- Summary of usable-but-disconnected Bro Detail warning and talk-blocking behavior.
- Key files changed, grouped by UI, backend/protocol if any, docs, and tests.
- Verification commands run and outcomes.
- Any skipped checks or residual risks.
- A clear completion signal only when every `done_when` item is satisfied or explicitly documented.
</output_contract>
