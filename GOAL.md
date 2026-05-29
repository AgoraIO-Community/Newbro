<goal>
Refactor Bro Detail to render one backend-owned canonical timeline turn projection from `SessionSnapshot`. Replace the current timestamp merge of local text turns, local audio turns, Newbro task/run records, native executor messages, and chat messages with `BroTimelineTurn[]` or equivalent protocol models. The resulting timeline must be multi-executor, must avoid fake tasks for imported native history, and must render each logical text/audio/executor response turn exactly once.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/guides/frontend-workbench.md`
- `docs/architecture/executors.md`

Implementation files to inspect:
- `src/newbro/protocol/session.py`
- `src/newbro/protocol/__init__.py`
- `src/newbro/runtime/models.py`
- `src/newbro/runtime/session.py`
- `src/newbro/executors/adapters/codex/executor.py`
- `src/newbro/executors/node/service.py`
- `src/newbro/ui/src/types.ts`
- `src/newbro/ui/src/NewbroShell.tsx`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/components/newbro/adapters.ts`
- `src/newbro/ui/src/components/newbro/types.ts`

Tests to inspect:
- `src/newbro/ui/src/__tests__/App.test.tsx`
- `tests/unit/runtime/test_session_runtime.py`
- `tests/integration/api/test_executor_text.py`
- `tests/integration/api/test_executor_audio.py`

Useful discovery commands:
- `rg -n "BroThreadMessage|bro_thread_messages|buildTimelineEntries|TextTurn|AudioTurn|BroTaskRecord|SessionSnapshot" src/newbro tests docs`
- `rg -n "turnId|client_request_id|target_thread_id|source_kind|latest_resume_handle|item/agentMessage/delta|item/completed" src/newbro tests`
</context>

<constraints>
- Protocol models are the source of truth. The canonical timeline turn must be a backend protocol object included in `SessionSnapshot`.
- Canonical timeline turns are a read model/projection. Do not create a new durable source of truth that competes with Newbro tasks/runs/summaries or native executor history.
- Do not preserve `bro_thread_messages` as the Bro Detail rendering contract. This refactor does not need backward compatibility for that UI path.
- Keep the core timeline protocol multi-executor. Use generic fields such as `executor_id`, `executor_thread_id`, and `executor_turn_id`; Codex-specific names may exist only in adapter metadata.
- Executor adapters must map native thread/turn identifiers into generic `executor_*` fields. If an executor cannot provide native turn identity, handle that explicitly; do not invent heuristic dedupe.
- Keep Communication Brain and Execution Brain boundaries intact. Timeline projection belongs to runtime/protocol/UI state, not communication classification.
- Do not create fake Newbro `Task`, `ExecutionRun`, or `TaskSummary` records from imported/native executor history.
- Do not solve duplication with thread-level hiding, suppression, or broad source filters.
- Do not solve duplication with text/timestamp similarity matching.
- Do not make the frontend responsible for native event ownership decisions.
- Do not render Bro Detail from independently merged local turns, task records, native messages, and chat messages.
- Ordinary send paths and snapshot publishes must not refresh native executor history or block on native history reads. Native history reads belong to explicit thread-open/import flows.
- Local text/audio may render optimistically only as timeline-turn-shaped objects and must be replaced by canonical backend turns via `client_request_id`.
- Audio transcript is part of the audio user message and must not render as a separate text user message.
- Keep the existing user bubble and task response card visual language; this is not a visual redesign.
- Do not add new non-Codex executor features beyond the generic timeline correlation contract needed for future adapters.
- Preserve unrelated user changes in the worktree, including dirty files not involved in this refactor.
- Update stable docs and `docs/memories.md` because this changes adopted protocol/runtime behavior.
</constraints>

<done_when>
- `SessionSnapshot` includes backend-owned canonical Bro Detail timeline turns.
- Canonical timeline turns are implemented as a read-model/projection, not as a new competing durable state store.
- The core timeline turn protocol includes one logical turn id, public thread id, persona id, executor id, owner, optional `client_request_id`, optional `executor_thread_id`, optional `executor_turn_id`, input modality, optional user message, optional assistant message, optional task/run state, status, timestamps, and metadata.
- The selected `BroThread` exposes per-thread timeline load state/error so imported history loading and failures are visible without failing open.
- Bro Detail rendering consumes canonical timeline turns only. It no longer builds the selected timeline by timestamp-merging local text turns, local audio turns, task records, native `BroThreadMessage` records, and chat messages.
- `bro_thread_messages` is removed from the Bro Detail rendering contract.
- Imported/native executor history renders user and assistant turns without creating Newbro `Task`, `ExecutionRun`, or `TaskSummary` records.
- Imported/native user turns use the existing user bubble visual.
- Imported/native assistant turns use the existing task response card visual.
- Imported/native assistant card titles come from the associated user input/query when available and do not add a redundant generic assistant-response heading.
- For native response turns with multiple assistant/agent items, only the latest assistant/agent content for that turn is displayed.
- Imported/native history read failures keep open-thread returning successfully while the thread reports failed timeline load state and an error.
- Sending one text message renders exactly one user-side turn and one assistant/task response, with no duplicate native message.
- Sending one audio message renders exactly one audio user-side turn; transcript appears inside that audio turn and not as a separate text message.
- A mixed imported thread can show old executor-owned turns and new Newbro-owned turns without hiding unrelated native history.
- Live executor assistant deltas/messages replace the latest assistant content for the same executor turn instead of adding another row.
- Optimistic local text/audio turns are replaced by canonical backend turns via `client_request_id`.
- Native events that arrive before a Newbro-owned turn has attached native `executor_turn_id` are not dropped and are not handled by thread-level filtering; they are buffered, projected, or later merged by explicit identity.
- Timeline ordering is deterministic, and within one turn the user side renders before assistant/task output.
- Late/stale open/history responses for a previously selected thread do not replace the currently selected thread timeline.
- The implementation does not rely on thread-level hiding/suppression or text/timestamp similarity matching to avoid duplicates.
- `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py` passes.
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py` passes.
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py` passes.
- `bun run test -- src/__tests__/App.test.tsx` passes from `src/newbro/ui`.
- `bun run build` passes from `src/newbro/ui`.
- Stable docs and `docs/memories.md` document the canonical timeline turn contract and source ownership behavior.
</done_when>

<workflow>
1. Check `git status --short` and identify unrelated dirty files before editing.
2. Read `SPEC.md`, `AGENTS.md`, and the stable protocol/frontend/executor docs listed in context.
3. Inspect current runtime snapshot projection, Bro thread models, imported Codex history loading, selected-thread event handling, task/run projection, and frontend timeline rendering.
4. Design the exact protocol models. Prefer names such as `BroTimelineTurn`, `BroTimelineMessage`, and `BroTimelineTask`; keep fields generic and multi-executor.
5. Define the timeline projection ownership boundary: canonical turns are derived from Newbro state, native history cache, and live event state; they are not a separate competing durable store.
6. Update protocol exports and `SessionSnapshot` to include canonical timeline turns and per-thread timeline load state/error.
7. Replace runtime `bro_thread_messages` projection with canonical turn projection:
   - imported/native history creates executor-owned turns
   - Newbro task/run/summary state creates Newbro-owned turns
   - live executor events upsert by `executor_id + executor_thread_id + executor_turn_id`
   - assistant deltas/messages for the same turn replace assistant content
8. Ensure direct text sends attach or preserve `client_request_id` and any available executor/native turn id on the canonical turn.
9. Ensure direct audio sends project as one audio user message with transcript embedded in that same message.
10. Handle native events that arrive before native turn identity has been attached to the Newbro-owned turn by explicit pending/merge logic, not thread-level filtering.
11. Remove thread-level duplicate guards, broad source suppression, and text/timestamp similarity dedupe introduced to work around duplicate rendering.
12. Update frontend types and shell state to consume canonical timeline turns from snapshots.
13. Replace `buildTimelineEntries` and related Bro Detail rendering so desktop and mobile render only canonical timeline turns plus any timeline-shaped optimistic turn state.
14. Reconcile optimistic text/audio turns by `client_request_id`; once a canonical backend turn exists, remove or replace the optimistic item.
15. Update frontend tests for imported history, direct text, direct audio transcript placement, mixed imported/direct threads, latest assistant replacement, loading state, and stale open response handling.
16. Update backend tests for imported history without fake tasks, direct Newbro-created threads, history failures, live event upsert/replacement, and no duplicate direct-send timeline turns.
17. Update stable docs and append a short factual note to `docs/memories.md`.
18. Run focused backend tests, focused frontend tests, and build. Run broader tests if the change touches shared protocol/runtime behavior beyond the focused coverage.
19. Final diff review: verify no Codex-only core model, no fake native-history tasks, no thread-level hiding workaround, no text/timestamp dedupe, no duplicate local/remote render path, and no unrelated refactor.
</workflow>

<verification_loop>
Focused backend commands:
- `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py`

Focused frontend commands from `src/newbro/ui`:
- `bun run test -- src/__tests__/App.test.tsx`
- `bun run build`

Optional broad commands:
- `.venv/bin/python -m pytest`
- `bun run test` from `src/newbro/ui`

Manual or test-backed UI checks:
1. Imported native thread history renders user and assistant turns with existing visuals and creates no Newbro tasks/runs/summaries.
2. Sending one text message renders one user-side turn and one assistant/task response.
3. Sending one audio message renders one audio user-side turn with transcript embedded in the audio message.
4. A mixed imported thread shows executor-owned historic turns and Newbro-owned new turns together.
5. Live assistant deltas replace the same turn's assistant content.
6. Late open/history responses for another thread do not replace the current selected timeline.

If any check cannot run, document the exact blocker and the residual risk instead of treating the goal as complete.
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
- Summary of the canonical timeline protocol added to `SessionSnapshot`.
- Summary of how imported/native history, direct text, direct audio, and live executor events are reconciled into one turn model.
- Verification commands run and outcomes.
- Explicit note that Bro Detail no longer renders from independent timestamp-merged local turns, task records, and native messages.
- Any skipped checks or residual risks.
</output_contract>
