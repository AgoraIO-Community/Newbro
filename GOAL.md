<goal>
Implement authenticated UI logout and enforce a first-run Bro setup gate: a user cannot enter or use Bro Detail until the selected Bro has a user-owned executor node created and bound. The setup gate must live inline on the Bro Detail route, create a node, bind it to the Bro, and show the local `newbro executor run ...` command. Logout must be available from the sidebar account area and return the browser to the signup screen without stale session data.
</goal>

<context>
Read first:
- AGENTS.md project instructions in the repo root or conversation.
- docs/architecture/public-onboarding-and-ownership.md
- docs/guides/public-hosted-deployment.md
- docs/memories.md
- src/newbro/ui/src/NewbroShell.tsx
- src/newbro/ui/src/components/newbro/Sidebar.tsx
- src/newbro/ui/src/components/newbro/BroDetailPage.tsx
- src/newbro/ui/src/components/newbro/TopVoiceBar.tsx
- src/newbro/ui/src/components/newbro/NodesPage.tsx
- src/newbro/ui/src/lib/session-client.ts
- src/newbro/ui/src/__tests__/App.test.tsx
- src/newbro/api/routes/auth.py
- src/newbro/api/routes/personas.py
- src/newbro/api/routes/executor_nodes.py
- src/newbro/api/routes/sessions.py

Useful discovery commands:
- rg -n "logout|logoutPublicUser|newbro_session|auth/logout" src/newbro/ui/src src/newbro/api tests docs
- rg -n "executor_node_id|createExecutorNode|updatePersona|revealExecutorNodeConnectCommand|buildExecutorRunCommand" src/newbro/ui/src src/newbro/api tests
- rg -n "BroDetailShellPage|BroDetailPage|voice-session-start|TopVoiceBar|VoicePad|setVoiceTarget" src/newbro/ui/src
</context>

<constraints>
- Preserve Communication Brain, Execution Brain, Shared Blackboard, and transport boundaries.
- Treat protocol models as source of truth; do not add UI-only fake node state.
- Keep executor nodes user-owned and Bro bindings owner-scoped.
- Do not change the backend auth/logout route unless a bug is discovered; `POST /api/auth/logout` already exists.
- Do not introduce quotas, rate limits, billing, hard-coded transcript rules, or demo shortcuts.
- Do not expose node tokens except through the existing create/reveal credential flows.
- Do not require a Bro picker or global home path before setup; the user may still route directly to Bro Detail, but Bro Detail must show the setup wizard until bound.
- Do not allow voice Start, mic controls, drafting, or send-from-Bro-detail interactions before setup is complete.
- Existing waiting-executor task guidance may remain, but the new setup gate is required before normal Bro Detail usage.
- Keep UI consistent with existing Newbro visual patterns; avoid nested cards and avoid marketing/landing-page copy.
- Update stable docs and docs/memories.md for adopted behavior changes.
</constraints>

<done_when>
- `GOAL.md` remains a focused contract for this task and no stale RFC 0014 deployment scope remains in it.
- Sidebar desktop and mobile drawer replace the fake “Max Chen / Pro · Online” footer with the current authenticated user email when available, otherwise user id, plus a visible `Log out` button using an appropriate icon.
- Clicking `Log out` calls `logoutPublicUser()`, stops any active voice session before logout, clears shell/session UI state, removes `sid` from the URL, closes stale sockets if needed, and shows the signup screen.
- UI tests prove logout calls `logoutPublicUser`, removes the `sid` query param, returns to the signup panel, and does not leave stale Bros/nodes/session UI visible.
- Bro Detail routes are setup-gated when the active runtime Bro has no `executorNodeId`: the normal Bro Detail workspace, voice bar, voice Start, mic pad, draft controls, and task interaction UI are not shown as usable controls.
- The setup gate is inline on Bro Detail and clearly guides the user to create and bind a node for the current Bro.
- The setup action uses existing APIs: `createExecutorNode(sessionId, { name: "<Bro name> local node", enabled_executors: ["codex"] })`, then `updatePersona(sessionId, bro.id, { executor_node_id: issue.node.node_id })`, then `buildExecutorRunCommand(...)`.
- After setup succeeds, the UI shows a copyable local executor command and transitions to the normal Bro Detail experience only after the Bro binding is reflected locally or in the refreshed shell snapshot.
- If the Bro already has a bound node, Bro Detail behaves as before and does not show the setup gate.
- If setup fails, the gate shows a clear error and does not partially unlock Bro Detail.
- If the user is logged out or unauthenticated, setup APIs are not called and the signup screen remains the auth path.
- Stable docs describe that talking to a Bro requires creating and binding a local executor node first, and logout is available from the sidebar account area.
- docs/memories.md has a short factual note for the adopted logout and node-gated Bro Detail behavior.
- Focused frontend tests and frontend build pass.
- If backend behavior is touched, focused backend tests and full backend tests pass.
</done_when>

<workflow>
1. Check git status and preserve unrelated changes.
2. Re-read the context files and inspect existing tests around logout mocks, Bro Detail voice start, Bro node creation, and executor binding.
3. Add current-user state to the shell if not already exposed from bootstrap/signup responses. Use the existing authenticated user returned by bootstrap/auth APIs; do not create a new identity endpoint.
4. Implement logout in `useNewbroShellState`:
   - stop active voice if needed;
   - call `logoutPublicUser()`;
   - close or invalidate active session stream state;
   - clear shell snapshot data, messages, draft state, warnings/errors that would expose old data;
   - call `replaceSessionIdInUrl(null)`;
   - set auth-required state so the signup panel appears.
5. Update `ShellFrame` and `Sidebar` props so the sidebar receives current account display text, logout state, and an `onLogout` action.
6. Replace the fake sidebar account footer in both desktop and mobile drawer with current account info plus a `Log out` button.
7. Implement a Bro Detail setup gate for runtime Bros without `executorNodeId`.
   - The gate must be rendered by `BroDetailShellPage` or `BroDetailPage` before normal detail controls are usable.
   - Prefer reusing the existing `handlePrepareLocalNodeCommand` logic from `BroDetailPage`; refactor if needed so it is available to the setup gate without duplication.
   - The setup gate creates the node, binds the Bro, builds/copies the command, and then unlocks normal detail when binding state is present.
8. Ensure `ShellVoiceBar`, `VoicePad`, draft send/clear, and normal detail panels are not available before setup completion.
9. Add tests:
   - logout from sidebar;
   - mobile drawer logout if practical with existing test utilities;
   - unbound Bro Detail shows setup gate and hides/disables normal voice controls;
   - setup gate creates node, binds persona, shows command, and unlocks normal detail;
   - already-bound Bro Detail skips setup gate.
10. Update stable docs and docs/memories.md.
11. Run focused UI tests, then frontend build. Run backend tests only if backend files changed.
12. Review final diff for unrelated churn, stale fake account text, stale docs, and any hidden pre-setup voice controls.
</workflow>

<verification_loop>
Focused frontend checks:
- cd src/newbro/ui && bun run test src/__tests__/App.test.tsx
- cd src/newbro/ui && bun run build

Backend checks, only if backend files changed:
- .venv/bin/python -m pytest tests/integration/api/test_public_auth_onboarding.py
- .venv/bin/python -m pytest

Manual browser smoke check when feasible:
- Open hosted/local UI while authenticated.
- Confirm sidebar shows the signed-in email or user id and a Log out button.
- Click Log out and confirm the signup panel appears and `sid` is removed.
- Sign up/log in again and open a Bro with no bound node.
- Confirm Bro Detail shows only the setup wizard and no usable voice/draft controls.
- Click setup, confirm a node is created, the Bro is bound, and the local executor command is shown/copyable.
- Confirm the normal Bro Detail/voice UI appears only after setup.

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
- Do not widen scope beyond UI logout and node-gated Bro Detail setup.
- Keep final answer concise.
</execution_rules>

<output_contract>
Final output must include:
- Summary of logout UI behavior.
- Summary of Bro Detail setup-gate behavior.
- Key files changed, grouped by UI, docs, and tests.
- Verification commands run and outcomes.
- Any skipped checks or residual risks.
- A clear completion signal only when every `done_when` item is satisfied or explicitly documented.
</output_contract>
