<goal>
Implement real end-to-end Codex-backed global thread sync and resume for Newbro Bro Detail. The desktop left rail and mobile drawer must show actual resumable Codex dialog threads, not task activity records. Newbro must use Codex app-server `thread/list` to import/list all global Codex threads returned by the local Codex app-server, including threads from cwd values unrelated to the current repo and threads not originally created by Newbro. The list must be sorted by recency descending using `updatedAt` then `createdAt`. Opening/selecting any imported or Newbro-created thread must fetch and hydrate that thread's `Task` records plus execution-run/timeline history, then let text and push-to-talk input continue the same Codex executor thread across browser refreshes through the running backend, connected executor node, and browser UI.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `docs/architecture/sessions-and-runs.md`
- `docs/architecture/execution-brain.md`
- `docs/architecture/executors.md`
- `docs/architecture/communication-brain.md`
- `docs/protocol/execution-session-and-run.md`
- `docs/protocol/task.md`
- `docs/guides/frontend-workbench.md`

Implementation files to inspect:
- `src/newbro/protocol/session.py`
- `src/newbro/protocol/task.py`
- `src/newbro/protocol/__init__.py`
- `src/newbro/runtime/models.py`
- `src/newbro/runtime/session.py`
- `src/newbro/execution/session_manager.py`
- `src/newbro/blackboard/interfaces.py`
- `src/newbro/blackboard/backends/memory.py`
- `src/newbro/executors/adapters/codex/client.py`
- `src/newbro/executors/adapters/codex/executor.py`
- `src/newbro/api/routes/executor_text.py`
- `src/newbro/api/routes/executor_audio.py`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/components/newbro/adapters.ts`
- `src/newbro/ui/src/components/newbro/types.ts`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`

Useful discovery commands:
- `rg -n "ExecutionSession|latest_resume_handle|continuity_key|thread_id|threadId|thread/read|thread/start|thread/fork" src/newbro tests docs`
- `rg -n "submit_executor_text_instruction|submit_executor_audio_instruction|executor-text|executor-audio|Communication Brain|conversation" src/newbro tests`
- `rg -n "THREADS WITH|Task activity|New thread|records|execution_sessions|selectedThread" src/newbro/ui/src`
- `rg -n "thread/list|thread/loaded/list|thread/read|thread/turns/list|thread/turns/items/list|thread_start|thread_fork" src/newbro/executors/adapters/codex src/newbro tests docs`

Verified Codex capability:
- Local `codex-cli 0.133.0` app-server exposes `thread/list`.
- A direct JSON-RPC probe returned global Codex threads, including threads not
  currently present in Newbro `bro_threads` and threads whose `cwd` is not the
  current repo.
- This goal should implement against `thread/list` directly. If a later installed Codex app-server lacks that method or returns an incompatible response, the goal is blocked; do not replace it with a Newbro-known-only fallback.
</context>

<constraints>
- Left rail entries are dialog threads, not task cards or renamed task activity.
- The sync path must call Codex app-server `thread/list` through the connected Codex adapter and import all global Codex threads from that response.
- Imported global Codex threads must be sorted by recency descending using `updatedAt` first and `createdAt` as fallback.
- Do not filter imported thread visibility by cwd/current workspace. Cwd is resume metadata only.
- Codex app-server `thread/list` is required. If it is absent or incompatible, stop and mark the goal blocked; do not implement a Newbro-known-only fallback.
- A user-visible thread may be imported from Codex or created by Newbro, but it must be backed by a real Codex `thread_id`.
- Newbro-created threads remain backed by `ExecutionSession.latest_resume_handle`.
- Raw Codex thread ids must not be normal user-facing labels; expose them only in diagnostics, logs, debug metadata, or import/sync proof artifacts.
- Do not store thread truth only in localStorage or browser-only state.
- Opening/selecting a thread must trigger backend thread hydration for that thread's `Task` records, execution runs, progress, and assistant-output timeline. The UI must not rely only on already-loaded task cards when a thread is opened.
- Browser refresh continuity is required. Backend-restart persistence is not required unless the existing blackboard/session persistence already supports it without broadening scope.
- Direct text and composer push-to-talk must bypass Communication Brain, Draft Brain, Agora, and connector voice paths.
- Rendering is unified: switching between open-channel mode and push-to-talk changes the input route, not the task/progress/assistant timeline model.
- Do not create a new thread for every direct send into the same selected thread.
- `New thread` must be explicit and must not create an empty Codex thread before first send.
- Keep `Task`, `ExecutionSession`, `ExecutionRun`, and the new thread projection conceptually separate.
- Keep protocol models typed; do not pass ad hoc untyped thread blobs through the runtime.
- Preserve existing PTT text and PTT audio behavior except for selecting the target thread.
- Preserve unrelated user changes in the dirty worktree.
- Update stable docs and `docs/memories.md` because this changes adopted runtime behavior.
</constraints>

<done_when>
- `SPEC.md` and `GOAL.md` describe the real Codex thread sync/resume contract and its verification criteria.
- Runtime exposes a typed Codex-backed Bro thread projection in snapshots or an equivalent typed API.
- The implementation calls Codex app-server `thread/list` from the Codex adapter, with tests or captured logs proving the method and response shape used.
- The implementation imports/lists all global Codex threads returned by `thread/list` and includes imported threads in the typed projection even when Newbro did not create them or their cwd differs from the current repo.
- The typed projection and desktop/mobile UI sort imported and Newbro-known threads by recency descending, using Codex `updatedAt` then `createdAt` for imported threads.
- If the current Codex app-server does not expose `thread/list` or returns an incompatible response, the goal is blocked and must not be completed with a Newbro-known-only hydration path.
- The thread projection is backed by Codex thread ids plus Newbro execution/session state where available, not from grouped UI task cards or browser-local fake data.
- Desktop Bro Detail left rail renders real thread records from the typed projection.
- Mobile Bro Detail drawer renders the same real thread records.
- Selecting/opening a thread fetches and hydrates that thread's `Task` records and execution-run/timeline state from backend/Codex state, then updates the main timeline and composer target.
- Imported Codex threads with existing Codex history show fetched historical `Task` records plus execution-run/timeline entries when opened before the user sends a new message.
- The selected thread is preserved across browser refresh via URL state such as `?sid=...&thread=...`.
- Direct text sends include the selected thread target and resume the selected Codex `thread_id` / `latest_resume_handle`.
- Push-to-talk audio sends, after executor-node transcription, include the selected thread target and resume the same Codex thread.
- Sending into a completed selected thread creates the needed new task/run history inside that selected thread while keeping one left-rail thread.
- Sending into an imported Codex thread that has no Newbro task history yet creates Newbro task/run history under that imported thread without changing the underlying Codex thread id, and uses the Codex-reported cwd for resume.
- Three sends into the same selected thread across browser refreshes show one left-rail thread and a unified main timeline containing the related task/progress/assistant output.
- Clicking `New thread` creates a pending fresh-thread target, and the real Codex thread is created only on first send.
- Focused tests prove thread projection, open-thread `Task` and execution-run/timeline hydration, selected-thread routing for text, selected-thread routing for PTT audio, refresh restore, desktop/mobile rendering, and no Communication Brain conversation leakage.
- Manual proof includes desktop and mobile screenshots plus relevant logs showing one real Codex thread continuing across multiple sends and refreshes.
- The goal is not complete if only protocol, runtime, or UI tests pass; a real desktop and mobile E2E check against a connected Codex executor must work.
- `.venv/bin/python -m pytest` passes.
- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx` passes.
- `cd src/newbro/ui && bun run test` passes.
- `cd src/newbro/ui && bun run build` passes.
- Stable docs and `docs/memories.md` document the adopted Codex thread projection and selected-thread routing behavior.
</done_when>

<workflow>
1. Check git status and identify unrelated dirty files before editing.
2. Read `SPEC.md`, `AGENTS.md`, and the stable session/execution/frontend docs.
3. Inspect runtime snapshot models, execution session storage, direct text/audio routes, Codex adapter thread methods, and current UI left-rail/mobile drawer code.
4. Diagnose current state from real snapshots/logs: active session snapshot, `execution_sessions`, task list, Codex resume handles, current URL state, and running frontend/backend reload state.
5. Implement a Codex adapter method for app-server `thread/list`. Record and validate the response shape in tests or docs. Import the full global response without cwd filtering and sort by recency descending. If `thread/list` is missing or incompatible in the installed Codex app-server, stop and mark the goal blocked with the version/capability mismatch documented; do not implement a reduced fallback.
6. Decide the minimal typed thread projection shape. It should include Newbro/import thread id, Bro/persona id when known, executor node id when known, execution session id when known, Codex resume/import status, display title, preview/status/progress, updated time, and enough metadata to route sends.
7. Add backend projection/API support, including an explicit open-thread hydration path that fetches the selected thread's `Task` records and execution-run/timeline history, and tests before changing UI rendering.
8. Add selected-thread routing to direct text and PTT audio request models/routes/runtime methods, keeping Communication Brain untouched.
9. Implement resume behavior for selected completed or imported threads through Codex thread ids, stored resume handles when present, and execution session continuity.
10. Update desktop and mobile UI to render real threads, fetch/open the selected thread's tasks when clicked or restored from the URL, preserve selected thread in the URL, and route composer sends to that selected thread.
11. Add or update frontend tests for imported thread rendering, open-thread task fetching/loading/error states, thread rendering, refresh restore, new-thread pending state, and routing payloads.
12. Update stable docs and `docs/memories.md`.
13. Run focused tests, then full backend/frontend verification.
14. Perform manual browser checks on desktop and mobile, capture screenshots/logs, and inspect that direct sends did not create Communication Brain conversation turns.
</workflow>

<verification_loop>
Focused backend tests:
- `.venv/bin/python -m pytest tests/unit/execution/test_session_manager.py`
- `.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_text.py`
- `.venv/bin/python -m pytest tests/integration/api/test_executor_audio.py`

Full backend:
- `.venv/bin/python -m pytest`

Frontend:
- `cd src/newbro/ui && bun run test --run src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Manual checks:
- Start backend/frontend and confirm code reload is active before judging behavior.
- Connect a Codex executor node and create or select one Bro.
- Confirm Codex app-server `thread/list` returns global threads in the installed Codex app-server. Create or identify at least one Codex thread not originally created by Newbro and at least one thread whose cwd differs from the current repo; verify both appear in the Newbro thread list.
- Verify the desktop and mobile thread lists are sorted by recency descending and are not capped to the first 6 entries.
- Open an imported Codex thread with existing history and verify the UI fetches and renders that thread's `Task` records plus execution-run/timeline history before any new send.
- On desktop, send three text messages into one selected thread, refreshing the browser between sends. Verify the left rail still shows one thread and the main timeline shows all related output.
- On mobile, verify the drawer shows the same real thread and can select/resume it.
- Send push-to-talk audio into the selected thread and confirm the transcribed instruction resumes the same Codex thread.
- Inspect runtime snapshot/logs to confirm the selected thread maps to a real Codex resume handle.
- Inspect runtime snapshot/logs to confirm imported threads map to real Codex thread ids, retain Codex-reported cwd for resume, and are not fabricated from UI task grouping.
- Inspect conversation state/logs to confirm direct text and PTT did not touch Communication Brain.
- Capture desktop and mobile screenshots plus relevant backend/frontend logs as proof.

If the Codex `thread/list` check cannot run because the installed Codex app-server lacks the method or returns an incompatible response, stop and report the goal as blocked. For other checks, document why, what was run instead, and the residual risk.
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
- Summary of the real Codex thread projection and selected-thread routing behavior.
- Summary of backend protocol/runtime, Codex adapter, desktop UI, mobile UI, test, and doc changes.
- Verification commands run and outcomes.
- Manual proof artifacts: desktop screenshot, mobile screenshot, and relevant logs showing global Codex threads sorted newest-first, at least one different-cwd thread visible, an opened thread's fetched `Task` records plus execution-run/timeline history, and one Codex thread resumed across multiple sends/refreshes.
- Explicit note that direct text and PTT bypass Communication Brain.
- Any skipped checks or residual risks. If Codex `thread/list` is unavailable or incompatible in the installed Codex app-server, the final output must say the goal is blocked, not complete.
</output_contract>
