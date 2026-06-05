# Bro Thread List Limit 15 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Bro Detail thread-list defaults and web page size from 25 to 15 while preserving explicit `limit` support for smaller clients.

**Architecture:** The existing cursor-page contract stays intact. The FastAPI route default, `SessionRuntime` default, and UI page-size constant all become 15; explicit `limit` values continue to flow through API -> runtime -> Codex executor-node request.

**Tech Stack:** Python 3.12/FastAPI/Pytest for backend; React/Vite/TypeScript/Vitest for frontend.

---

## Dirty Worktree Safety

This branch may already contain approved uncommitted changes in files touched by this plan. Before each commit step, run `git diff -- <files>` and confirm the diff contains only the task's page-size changes. If unrelated existing changes are present in the same file, do not use plain `git add <file>`; either stage only the relevant hunks with `git add -p` or skip the per-task commit and report the mixed diff before continuing.

---

## File Map

- Modify `src/newbro/api/routes/sessions.py`: change `GET /sessions/{session_id}/bro-threads` default `limit` from 25 to 15.
- Modify `src/newbro/runtime/session.py`: change `SessionRuntime.list_bro_thread_page` default `limit` from 25 to 15.
- Modify `src/newbro/ui/src/ArtboardShell.tsx`: change `THREAD_LIST_PAGE_SIZE` from 25 to 15.
- Modify `src/newbro/ui/src/NewbroShell.tsx`: change `listBroThreadsPage` calls from `limit: 25` to `limit: 15`.
- Modify `tests/unit/runtime/test_bro_detail_thread_projection.py`: update the default Codex `thread/list` limit assertion from 25 to 15.
- Create `tests/unit/api/test_session_route_defaults.py`: lock the API route default to 15.
- Modify `src/newbro/ui/src/__tests__/App.test.tsx`: lock UI bootstrap/load-more calls to 15.
- Modify `src/newbro/ui/src/lib/session-client.test.ts`: prove explicit small limits serialize into query params.
- Modify `docs/guides/frontend-workbench.md`: update stable UI docs from 25 to 15.
- Modify `docs/memories.md`: append a short factual note for the adopted default/page-size change.

---

### Task 1: Backend API And Runtime Defaults

**Files:**
- Modify: `src/newbro/api/routes/sessions.py`
- Modify: `src/newbro/runtime/session.py`
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py`
- Create: `tests/unit/api/test_session_route_defaults.py`

- [ ] **Step 1: Write failing API default test**

Create `tests/unit/api/test_session_route_defaults.py`:

```python
from __future__ import annotations

from inspect import signature

from newbro.api.routes.sessions import list_bro_thread_page


def test_bro_thread_page_route_default_limit_is_iot_friendly() -> None:
    params = signature(list_bro_thread_page).parameters

    assert params["limit"].default == 15
```

- [ ] **Step 2: Update failing runtime projection expectation**

In `tests/unit/runtime/test_bro_detail_thread_projection.py`, inside `test_imported_codex_threads_snapshot_uses_first_page_only`, change:

```python
assert kwargs["limit"] == 25
```

to:

```python
assert kwargs["limit"] == 15
```

- [ ] **Step 3: Run backend tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_session_route_defaults.py tests/unit/runtime/test_bro_detail_thread_projection.py -q
```

Expected: failure because the API route and runtime/projection defaults still use 25.

- [ ] **Step 4: Change backend defaults to 15**

In `src/newbro/api/routes/sessions.py`, update the route signature:

```python
@router.get("/sessions/{session_id}/bro-threads")
async def list_bro_thread_page(
    session_id: str,
    request: Request,
    target_persona_id: str,
    limit: int = 15,
    cursor: str | None = None,
):
```

In `src/newbro/runtime/session.py`, update the runtime method signature:

```python
async def list_bro_thread_page(
    self,
    *,
    target_persona_id: str,
    limit: int = 15,
    cursor: str | None = None,
):
```

In `src/newbro/runtime/bro_detail_thread_projection.py`, change the imported thread-list page constant if it is still 25:

```python
IMPORTED_CODEX_THREAD_PAGE_LIMIT = 15
```

- [ ] **Step 5: Run backend tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_session_route_defaults.py tests/unit/runtime/test_bro_detail_thread_projection.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 6: Commit backend default change**

First inspect the touched files:

```bash
git diff -- src/newbro/api/routes/sessions.py src/newbro/runtime/session.py src/newbro/runtime/bro_detail_thread_projection.py tests/unit/api/test_session_route_defaults.py tests/unit/runtime/test_bro_detail_thread_projection.py
```

If the diff contains only this task's default-limit changes, commit:

```bash
git add src/newbro/api/routes/sessions.py src/newbro/runtime/session.py src/newbro/runtime/bro_detail_thread_projection.py tests/unit/api/test_session_route_defaults.py tests/unit/runtime/test_bro_detail_thread_projection.py
git commit -m "Reduce bro thread API default limit"
```

If the diff includes unrelated pre-existing work, stage only the relevant hunks with `git add -p` or leave the task uncommitted and report the mixed diff.

---

### Task 2: Frontend Thread Page Size And Client Limit Test

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/NewbroShell.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`
- Modify: `src/newbro/ui/src/lib/session-client.test.ts`

- [ ] **Step 1: Update UI tests first**

In `src/newbro/ui/src/__tests__/App.test.tsx`, in `loads additional runtime thread pages from the backend`, change the fixture from 25 to 15:

```ts
snapshot.bro_threads = Array.from({ length: 15 }, (_, index) => threadFixture(index)) as any;
```

Change the assertions in that test to:

```ts
expect(await screen.findByText("Paged thread 01")).toBeInTheDocument();
expect(screen.getByText("Paged thread 15")).toBeInTheDocument();
expect(screen.queryByText("Paged thread 16")).not.toBeInTheDocument();
```

Change the second mocked page to return thread 16:

```ts
.mockResolvedValueOnce({
  persona_id: "forge",
  threads: [threadFixture(15)],
  page: { next_cursor: null, previous_cursor: "page-1", has_more: false, status: "loaded", error: null },
});
```

Change the post-click assertions:

```ts
expect(await screen.findByText("Paged thread 16")).toBeInTheDocument();
expect(clientMock.listBroThreadsPage).toHaveBeenCalledWith("session-existing", {
  targetPersonaId: "forge",
  cursor: "page-2",
  limit: 15,
});
```

In the existing bootstrap/request assertions that currently expect `limit: 25`, change them to `limit: 15`. The important assertion shape is:

```ts
expect(clientMock.listBroThreadsPage).toHaveBeenCalledWith("session-existing", {
  targetPersonaId: "forge",
  cursor: null,
  limit: 15,
});
```

In `src/newbro/ui/src/lib/session-client.test.ts`, change `lists a bro thread page with cursor params` to prove a small explicit limit is serialized:

```ts
await client.listBroThreadsPage("session-1", {
  targetPersonaId: "forge",
  cursor: "cursor-1",
  limit: 5,
});

expect(fetchMock).toHaveBeenCalledWith(
  "/api/sessions/session-1/bro-threads?target_persona_id=forge&limit=5&cursor=cursor-1",
);
```

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```bash
cd src/newbro/ui
bun run test src/__tests__/App.test.tsx src/lib/session-client.test.ts
```

Expected: failures because production code still requests/render-pages 25.

- [ ] **Step 3: Change frontend page size and request limits**

In `src/newbro/ui/src/ArtboardShell.tsx`, change:

```ts
const THREAD_LIST_PAGE_SIZE = 15;
```

In `src/newbro/ui/src/NewbroShell.tsx`, change both Bro-thread list calls to use `limit: 15`:

```ts
return await listBroThreadsPage(sessionId, {
  targetPersonaId: bro.persona_id,
  cursor: null,
  limit: 15,
});
```

and:

```ts
const page = await listBroThreadsPage(activeShellSessionId, {
  targetPersonaId,
  cursor: pageInfo.next_cursor,
  limit: 15,
});
```

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run:

```bash
cd src/newbro/ui
bun run test src/__tests__/App.test.tsx src/lib/session-client.test.ts
```

Expected: selected frontend tests pass.

- [ ] **Step 5: Commit frontend page-size change**

First inspect the touched files:

```bash
git diff -- src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/__tests__/App.test.tsx src/newbro/ui/src/lib/session-client.test.ts
```

If the diff contains only this task's page-size/test changes, commit:

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/__tests__/App.test.tsx src/newbro/ui/src/lib/session-client.test.ts
git commit -m "Reduce bro thread UI page size"
```

If the diff includes unrelated pre-existing work, stage only the relevant hunks with `git add -p` or leave the task uncommitted and report the mixed diff.

---

### Task 3: Stable Documentation And Memory

**Files:**
- Modify: `docs/guides/frontend-workbench.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Update stable frontend wording**

In `docs/guides/frontend-workbench.md`, replace:

```markdown
Desktop and mobile thread pickers render long thread lists in pages of 25 and
```

with:

```markdown
Desktop and mobile thread pickers render long thread lists in pages of 15 and
```

- [ ] **Step 2: Add memory note**

Append this factual note under `## 2026-06-05` in `docs/memories.md`:

```markdown
- Reduced Bro Detail thread-list defaults and web page size from 25 to 15 while preserving explicit `limit` and cursor support for smaller clients.
```

- [ ] **Step 3: Check docs diff**

Run:

```bash
git diff -- docs/guides/frontend-workbench.md docs/memories.md
```

Expected: only the thread-list page-size wording and the memory note changed.

- [ ] **Step 4: Commit docs**

First inspect the touched files:

```bash
git diff -- docs/guides/frontend-workbench.md docs/memories.md
```

If the diff contains only this task's documentation changes, commit:

```bash
git add docs/guides/frontend-workbench.md docs/memories.md
git commit -m "Document bro thread list page size"
```

If the diff includes unrelated pre-existing work, stage only the relevant hunks with `git add -p` or leave the task uncommitted and report the mixed diff.

---

### Task 4: Full Verification

**Files:**
- No new edits unless verification exposes a real defect.

- [ ] **Step 1: Run targeted backend suite**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_session_route_defaults.py tests/unit/runtime/test_bro_detail_thread_projection.py tests/integration/api/test_executor_text.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 2: Run targeted frontend suite**

Run:

```bash
cd src/newbro/ui
bun run test src/__tests__/App.test.tsx src/lib/session-client.test.ts
```

Expected: all selected frontend tests pass.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd src/newbro/ui
bun run build
```

Expected: Vite build and `tsc --noEmit` pass. Existing vendor chunk-size and Agora RTM eval warnings are acceptable if unchanged.

- [ ] **Step 4: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Confirm final diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only files from this plan and the already-existing approved branch changes are modified. Do not revert unrelated existing changes.
