<goal>
Implement selected-thread live updates and auto-scroll for Newbro Bro Detail. When a user selects or opens a Codex-backed Bro thread, Newbro must start or refresh a selected-thread Codex app-server loaded-thread subscription through the executor node, hydrate the opened thread, and keep desktop and mobile thread panes scrolled to the newest selected-thread output. Existing selected Codex threads must be loaded with `thread/resume`; newly created selected Codex threads must use `thread/start`; leaving or replacing the selected thread must call `thread/unsubscribe` for the previous Codex thread when possible. New selected-thread assistant/task output must arrive through Newbro's session stream state/events, not browser polling, and updates for non-selected threads must not move the current scroll position.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `docs/architecture/execution-brain.md`
- `docs/architecture/executors.md`
- `docs/architecture/blackboard.md`
- `docs/protocol/session-stream.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/guides/frontend-workbench.md`

Implementation files to inspect:
- `src/newbro/executors/adapters/codex/client.py`
- `src/newbro/executors/adapters/codex/executor.py`
- `src/newbro/executors/adapters/codex/jsonrpc.py`
- `src/newbro/executors/adapters/codex/session.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/protocol/executor_node.py`
- `src/newbro/api/ws/executors.py`
- `src/newbro/runtime/executor_node_manager.py`
- `src/newbro/runtime/session.py`
- `src/newbro/blackboard/interfaces.py`
- `src/newbro/blackboard/backends/memory.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`

Useful discovery commands:
- `rg -n "subscribe|subscription|thread/start|thread/resume|thread/unsubscribe|thread/list|thread/read|next_event|iter_events|thread/status/changed|turn/completed" src/newbro tests docs`
- `rg -n "openRuntimeBroThread|openBroThread|selectedThreadId|activeThreadId|dt-pane-scroll|nb-mobile-thread-body|ThreadPanel" src/newbro/ui/src`
- `rg -n "ListCodexThreadsCommand|ReadCodexThreadCommand|ExecutorNode|codex_threads|codex_thread" src/newbro tests`
- `rg -n "snapshot|SessionStreamEvent|publish_snapshot|blackboard.subscribe|subscribers" src/newbro/runtime src/newbro/api tests`

Current understanding to verify:
- The browser already consumes `WS /api/sessions/{session_id}/stream`.
- Selected/opened thread hydration currently uses `POST /api/sessions/{session_id}/bro-threads/{thread_id}/open`.
- Codex app-server events are already consumed while an active turn runs through `CodexAppServerClient.next_event()`.
- Official Codex app-server docs say `thread/read` reads stored thread data without resuming or subscribing to it. It is suitable for non-live history hydration but not selected-thread live updates.
- Official Codex app-server docs expose `thread/start` for fresh threads, `thread/resume` for continuing stored threads, loaded-thread status/events, `thread/loaded/list`, and `thread/unsubscribe` for removing the current connection's subscription to a loaded thread.
- Thread list/open hydration appears request-based through `thread/list` and `thread/read`; selected-thread live behavior should be implemented by loading/subscribing through `thread/start` for new Codex threads or `thread/resume` for existing Codex threads, then consuming app-server events from that connection.
</context>

<constraints>
- The executor node, not the browser, owns Codex app-server loaded-thread subscription.
- The browser continues to consume Newbro session stream snapshots/events.
- Do not add browser polling or frontend poll loops for selected-thread freshness.
- Use Codex app-server's loaded-thread lifecycle: `thread/start` for a newly created selected Codex thread, `thread/resume` for an existing selected Codex thread, and `thread/unsubscribe` when leaving or replacing the selected thread.
- Do not use `thread/read` as the selected-thread live subscription mechanism; it is explicitly non-subscribing.
- If the existing Codex app-server loaded-thread event path already provides selected-thread live updates without polling, document proof and use that path.
- If the installed Codex app-server lacks compatible `thread/start` / `thread/resume` / `thread/unsubscribe` loaded-thread behavior, stop and mark the goal blocked with version/capability evidence rather than shipping a polling-only substitute.
- Selecting a new thread must call `thread/unsubscribe` for the previous selected Codex thread when possible, replace/supersede the previous selected-thread subscription, and suppress stale events so they do not leak into the wrong thread.
- Auto-scroll is intentionally forceful: scroll to bottom on thread open and new selected-thread output even if the user manually scrolled up.
- Auto-scroll only applies to selected-thread open/output. Non-selected thread updates must not move desktop or mobile scroll.
- Keep Communication Brain, Draft Brain, Agora, and connector voice behavior unchanged.
- Keep transport thin: executor/node/backend translate typed events; UI renders selected-thread state and scrolls.
- Keep protocol models typed; avoid ad hoc untyped subscription blobs.
- Do not redesign thread import/sync/resume beyond what selected-thread live updates require.
- Preserve unrelated user changes in the worktree.
- Update stable docs and `docs/memories.md` only for adopted runtime behavior changes, not for test-only edits.
</constraints>

<done_when>
- `SPEC.md` and `GOAL.md` describe the selected-thread subscribe and auto-scroll contract with measurable verification criteria.
- Implementation verifies the installed Codex app-server supports the documented loaded-thread lifecycle for selected-thread updates.
- Executor node uses `thread/start` for new selected Codex threads, `thread/resume` for existing selected Codex threads, and loaded-thread events for selected/opened thread updates; if this lifecycle does not exist, the goal is blocked with evidence rather than completed with polling.
- Selecting/opening an existing Codex-backed thread starts or refreshes the selected-thread live update path through the executor node using `thread/resume`.
- Creating the first real Codex thread for a selected pending thread uses `thread/start` and treats the created thread as the selected loaded subscription.
- Switching selected threads or leaving Bro Detail calls `thread/unsubscribe` for the previous selected Codex thread, or records a benign `notSubscribed` / `notLoaded` cleanup result.
- Stale subscription events from a previously selected thread do not mutate or scroll the newly selected thread.
- New selected-thread assistant/task output reaches the browser through Newbro session stream state/events, not through browser polling.
- Desktop Bro Detail scrolls `.dt-pane-scroll` or the actual desktop message scroller to bottom when a thread is opened.
- Desktop Bro Detail scrolls to bottom when new output for the selected thread arrives.
- Mobile Bro Detail scrolls `.nb-mobile-thread-body` or the actual mobile message scroller to bottom when a thread is opened.
- Mobile Bro Detail scrolls to bottom when new output for the selected thread arrives.
- Non-selected thread updates do not scroll the current desktop or mobile thread pane.
- Focused backend tests cover Codex `thread/start` / `thread/resume` / `thread/unsubscribe` command flow, selected-thread subscription replacement, stale event suppression, and selected-thread update delivery into Newbro session state.
- Frontend tests cover desktop open-thread scroll, desktop selected-thread update scroll, mobile open-thread scroll, mobile selected-thread update scroll, and no scroll for non-selected updates.
- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx` passes.
- `cd src/newbro/ui && bun run build` passes.
- Focused backend tests for touched executor-node/runtime routes pass.
- Stable docs and `docs/memories.md` document the adopted selected-thread subscription behavior if runtime behavior changes.
</done_when>

<workflow>
1. Check `git status --short` and identify unrelated dirty files before editing.
2. Read `SPEC.md`, `AGENTS.md`, and the stable executor/session/frontend docs listed in context.
3. Inspect current Codex app-server client/event handling, executor-node command protocol, runtime selected-thread open flow, and desktop/mobile thread rendering.
4. Discover the installed Codex app-server loaded-thread event surface. Prefer direct code/API inspection and, if feasible, a local app-server probe. Record exact method/event names and response shapes for `thread/start`, `thread/resume`, loaded-thread notifications, and `thread/unsubscribe`. If the documented lifecycle is unavailable, stop and mark the goal blocked with evidence.
5. Design the minimal typed selected-thread subscription protocol between Newbro runtime and executor node. Include start/replace/stop semantics, target persona/thread ids, node id, Codex thread id/resume handle, unsubscribe result, and stale-event correlation.
6. Implement executor-node Codex loaded-thread subscription support or reuse an existing app-server event stream if it already provides selected-thread changes after `thread/start` / `thread/resume` without polling.
7. Implement backend/runtime plumbing so selected-thread subscription events update typed Newbro state and publish session stream snapshots/events for the browser.
8. Ensure selected-thread switching, leaving Bro Detail, node disconnects, and pending `New thread` call `thread/unsubscribe` for the old loaded Codex thread when possible and always supersede stale events locally.
9. Add desktop auto-scroll refs/effects around the actual message scroller. Scroll on opened-thread hydration and selected-thread output changes, but not on non-selected thread updates.
10. Add mobile auto-scroll refs/effects around the actual message scroller with the same selected-thread-only behavior.
11. Add focused backend tests for `thread/start` / `thread/resume` / `thread/unsubscribe` command flow, replacement, stale event suppression, and session-state delivery.
12. Add or update frontend tests for desktop/mobile auto-scroll on open and selected updates, plus non-selected update no-scroll behavior.
13. Update stable docs and `docs/memories.md` if runtime behavior changed.
14. Run focused tests first, then frontend build. If backend scope is touched broadly, run the relevant focused backend suites before finalizing.
15. Do a final diff review to ensure no polling shortcut, no Communication Brain changes, and no unrelated refactors slipped in.
</workflow>

<verification_loop>
Discovery/proof:
- Inspect or probe Codex app-server to identify the selected-thread loaded-thread event surface.
- Confirm `thread/read` remains non-subscribing and is not used for selected-thread live updates.
- Confirm selected existing threads use `thread/resume`, new selected Codex threads use `thread/start`, and leaving/replacing uses `thread/unsubscribe`.
- If the app-server lacks the documented loaded-thread lifecycle, stop as blocked and report Codex version plus capability evidence.

Focused backend tests to run based on touched files:
- `.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py`
- `.venv/bin/python -m pytest tests/unit/executors/node/test_service.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_nodes.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py`

Frontend:
- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run build`

Manual checks:
- Start backend/frontend and confirm active code reload before judging behavior.
- Connect a Codex executor node and open desktop Bro Detail.
- Select a real Codex-backed thread and confirm logs/state show `thread/resume` and selected-thread loaded-event consumption.
- Switch away or leave Bro Detail and confirm logs/state show `thread/unsubscribe` for the previous selected Codex thread id.
- Confirm desktop thread pane scrolls to the bottom after open-thread hydration.
- Produce a new response for the selected thread and confirm desktop scrolls to bottom.
- Produce or simulate an update for a non-selected thread and confirm desktop scroll does not move.
- Repeat selected-thread open, selected-thread update, and non-selected update checks on mobile Bro Detail.
- Inspect logs/snapshots to confirm browser updates arrive through Newbro session stream state/events and not through browser polling.
- Inspect logs/snapshots to confirm direct text/PTT behavior still bypasses Communication Brain.

If a verification command cannot run, document the command, why it could not run, what was run instead, and residual risk.
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
- Do not widen scope.
- Keep the final answer concise.
- Follow repo guardrails from `AGENTS.md`: preserve Communication Brain and Execution Brain separation, keep transport thin, treat protocol models as source of truth, diagnose from real state, test the failure mode, verify activation, and update memory deliberately.
</execution_rules>

<output_contract>
Final output must include:
- Summary of the Codex selected-thread loaded-thread mechanism used, including where `thread/start`, `thread/resume`, and `thread/unsubscribe` are called, or a clear blocked report if no compatible mechanism exists.
- Summary of executor-node/backend/runtime changes.
- Summary of desktop and mobile auto-scroll changes.
- Verification commands run and outcomes.
- Manual proof notes for selected-thread open, selected-thread update scroll, non-selected update no-scroll, and session-stream delivery.
- Explicit note that direct text and PTT still bypass Communication Brain.
- Any skipped checks or residual risks.
</output_contract>
