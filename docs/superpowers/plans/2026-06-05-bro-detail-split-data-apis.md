# Bro Detail Split Data APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Bro Detail bootstrap, thread-list paging, timeline paging, and live subscription so `GET /sessions/{id}` no longer performs hidden Codex data loads.

**Architecture:** Add compact Bro/node bootstrap and subscribe response models in `runtime.models`, route them through `api/routes/sessions.py`, and move Bro Detail UI data loading to explicit page/subscription clients. Keep cached/live timeline projections for event reconciliation, but remove page metadata and remote Codex reads from session snapshots.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, React, Vite, TypeScript, Vitest.

---

## File Map

- `src/newbro/runtime/models.py` — add compact Bro/node bootstrap models, subscribe response model, and timeline page response `thread` field; reduce session snapshot fields.
- `src/newbro/runtime/session.py` — add `bro_list()`, rename subscribe/unsubscribe delegates, and make `snapshot()` local-only by default.
- `src/newbro/runtime/bro_detail_thread_projection.py` — add compact Bro projection helpers, change open/close to subscribe/unsubscribe, remove timeline hydration and import-sync fallback from subscribe, and return thread summaries from timeline pages.
- `src/newbro/api/routes/sessions.py` — add `GET /sessions/{id}/bros`, replace `/open` routes with `/subscribe`, and keep paged thread/timeline routes.
- `src/newbro/ui/src/types.ts` — add compact Bro/node and subscribe response types; update timeline page response shape; remove page metadata from session snapshot type.
- `src/newbro/ui/src/lib/session-client.ts` — add `listBros`, `subscribeBroThread`, `unsubscribeBroThread`; remove `openBroThread`/`closeBroThread`; keep page clients.
- `src/newbro/ui/src/NewbroShell.tsx` — load compact Bro/node rows separately, subscribe then load timeline page on thread selection, and keep page cursors in UI state.
- `src/newbro/ui/src/ArtboardShell.tsx` — consume shell state after the client rename if needed; keep view behavior.
- `tests/unit/runtime/test_bro_detail_thread_projection.py` — prove subscribe does not hydrate or import; timeline response includes thread.
- `tests/unit/runtime/test_session_runtime.py` — prove session snapshot does not sync imported Codex data and compact Bro list exists.
- `tests/integration/api/test_executor_text.py` — update route tests from `/open` to `/subscribe` and assert no hidden Codex page calls.
- `src/newbro/ui/src/lib/session-client.test.ts` — update client URL tests.
- `src/newbro/ui/src/__tests__/App.test.tsx` — update UI mocks and selection flow expectations.
- `docs/protocol/execution-session-and-run.md`, `docs/architecture/executors.md`, `docs/memories.md` — document the new explicit data APIs.

---

### Task 1: Add Compact Bro/Node And Subscribe Models

**Files:**
- Modify: `src/newbro/runtime/models.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write failing model/session tests**

Add this test near other snapshot/Bro Detail tests in `tests/unit/runtime/test_session_runtime.py`:

```python
@pytest.mark.anyio
async def test_bro_list_returns_compact_persona_node_rows_without_full_node_data():
    session = build_session_runtime()
    manager = session.executor_node_manager
    issue = await manager.create_node(name="Mac Studio", enabled_executors=["codex"])
    await session.blackboard.upsert_persona(
        Persona(persona_id="forge", name="Forge", executor_node_id=issue.node.node_id)
    )

    rows = await session.bro_list()

    assert rows.bros[0].persona_id == "forge"
    assert rows.bros[0].name == "Forge"
    assert rows.bros[0].executor_node is not None
    assert rows.bros[0].executor_node.node_id == issue.node.node_id
    assert rows.bros[0].executor_node.name == "Mac Studio"
    assert rows.bros[0].executor_node.enabled_executors == ["codex"]
    dumped = rows.model_dump(mode="json")
    assert "token_hint" not in dumped["bros"][0]["executor_node"]
    assert "last_seen_at" not in dumped["bros"][0]["executor_node"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_bro_list_returns_compact_persona_node_rows_without_full_node_data -q
```

Expected: FAIL with `AttributeError: 'SessionRuntime' object has no attribute 'bro_list'` or missing model imports.

- [ ] **Step 3: Add runtime models**

In `src/newbro/runtime/models.py`, add these models after `BroTimelineTurnPageResponse` imports are available:

```python
class BroExecutorCapabilitySummary(BaseModel):
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
    supports_thread_list: bool = False
    supports_audio_instruction: bool = False


class BroExecutorNodeSummary(BaseModel):
    node_id: str
    name: str
    connection_status: Literal["connected", "disconnected"] = "disconnected"
    enabled_executors: list[str] = Field(default_factory=list)
    codex: BroExecutorCapabilitySummary | None = None


class BroSummary(BaseModel):
    persona_id: str
    name: str
    avatar: str = ""
    status: str = "idle"
    executor_node: BroExecutorNodeSummary | None = None


class BroListResponse(BaseModel):
    bros: list[BroSummary] = Field(default_factory=list)


class BroThreadSubscriptionResponse(BaseModel):
    thread_id: str
    persona_id: str
    subscribed: bool
    timeline_status: Literal["not_loaded", "loading", "loaded", "failed"] = "not_loaded"
    timeline_error: str | None = None
```

- [ ] **Step 4: Add `SessionRuntime.bro_list()`**

In `src/newbro/runtime/session.py`, import the new models and add:

```python
    async def bro_list(self):
        from newbro.runtime.models import (
            BroExecutorCapabilitySummary,
            BroExecutorNodeSummary,
            BroListResponse,
            BroSummary,
        )

        personas = await self.blackboard.list_personas()
        nodes = {node.node_id: node for node in await self.executor_node_manager.list_nodes()}
        bros: list[BroSummary] = []
        for persona in personas:
            node_summary = None
            if persona.executor_node_id:
                node = nodes.get(persona.executor_node_id)
                if node is not None:
                    codex_capability = next(
                        (
                            capability
                            for capability in node.connected_executor_capabilities
                            if capability.executor_type == "codex"
                        ),
                        None,
                    )
                    node_summary = BroExecutorNodeSummary(
                        node_id=node.node_id,
                        name=node.name,
                        connection_status=node.connection_status,
                        enabled_executors=list(node.enabled_executors),
                        codex=(
                            BroExecutorCapabilitySummary(
                                version=codex_capability.version,
                                minimum_version=codex_capability.minimum_version,
                                availability_reason=codex_capability.availability_reason,
                                supports_thread_list=codex_capability.supports_thread_list,
                                supports_audio_instruction=codex_capability.supports_audio_instruction,
                            )
                            if codex_capability is not None
                            else None
                        ),
                    )
            bros.append(
                BroSummary(
                    persona_id=persona.persona_id,
                    name=persona.name,
                    avatar=persona.avatar,
                    status=persona.status,
                    executor_node=node_summary,
                )
            )
        return BroListResponse(bros=bros)
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_bro_list_returns_compact_persona_node_rows_without_full_node_data -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/runtime/models.py src/newbro/runtime/session.py tests/unit/runtime/test_session_runtime.py
git commit -m "Add compact bro node bootstrap models"
```

---

### Task 2: Add Compact Bro API And Reduce Session Snapshot

**Files:**
- Modify: `src/newbro/api/routes/sessions.py`
- Modify: `src/newbro/runtime/models.py`
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/integration/api/test_executor_text.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write failing snapshot no-sync test**

Add to `tests/unit/runtime/test_session_runtime.py`:

```python
@pytest.mark.anyio
async def test_session_snapshot_does_not_sync_imported_codex_threads(monkeypatch: pytest.MonkeyPatch):
    session = build_session_runtime()
    projection = session._bro_detail_thread_projection()

    async def fail_if_synced(**_kwargs):
        raise AssertionError("session snapshot must not sync imported Codex threads")

    monkeypatch.setattr(projection, "sync_imported_codex_threads", fail_if_synced)

    snapshot = await session.snapshot()

    assert snapshot.session_id == session.session_id
    assert snapshot.bro_thread_pages == {}
    assert snapshot.bro_timeline_pages == {}
    assert snapshot.personas == []
    assert snapshot.executor_nodes == []
```

- [ ] **Step 2: Write failing `/bros` route test**

Add to `tests/integration/api/test_executor_text.py`:

```python
@pytest.mark.anyio
async def test_bro_list_api_returns_compact_bro_node_rows(client):
    session_response = await client.post("/api/sessions")
    session_id = session_response.json()["session_id"]

    create_response = await client.post(
        f"/api/sessions/{session_id}/executor-nodes",
        json={"name": "Mac Studio", "enabled_executors": ["codex"]},
    )
    node_id = create_response.json()["node"]["node_id"]

    await client.post(
        f"/api/sessions/{session_id}/personas",
        json={"name": "Forge", "executor_node_id": node_id},
    )

    response = await client.get(f"/api/sessions/{session_id}/bros")

    assert response.status_code == 200
    payload = response.json()
    assert payload["bros"][0]["name"] == "Forge"
    assert payload["bros"][0]["executor_node"]["node_id"] == node_id
    assert payload["bros"][0]["executor_node"]["enabled_executors"] == ["codex"]
    assert "token_hint" not in payload["bros"][0]["executor_node"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_session_snapshot_does_not_sync_imported_codex_threads tests/integration/api/test_executor_text.py::test_bro_list_api_returns_compact_bro_node_rows -q
```

Expected: first test FAILS because `snapshot()` still includes full personas/nodes or syncs; second test FAILS with 404 route not found.

- [ ] **Step 4: Reduce `SessionSnapshot` payload fields**

In `src/newbro/runtime/models.py`, keep the fields required by current websocket/runtime code, but remove Bro Detail page metadata and full persona/node bootstrap from API output by changing defaults and snapshot construction. Do not remove class attributes yet if many tests depend on them; instead make `SessionRuntime.snapshot()` populate these reduced fields:

```python
            bro_thread_pages={},
            bro_timeline_pages={},
            personas=[],
            executor_nodes=[],
```

Also change `snapshot_parts(...)` invocation in `SessionRuntime.snapshot()` to:

```python
            sync_imported_codex_threads=False,
```

- [ ] **Step 5: Add `/bros` route**

In `src/newbro/api/routes/sessions.py`, add before thread page routes:

```python
@router.get("/sessions/{session_id}/bros")
async def list_bros(session_id: str, request: Request):
    await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await session.bro_list()
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_session_snapshot_does_not_sync_imported_codex_threads tests/integration/api/test_executor_text.py::test_bro_list_api_returns_compact_bro_node_rows -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/api/routes/sessions.py src/newbro/runtime/models.py src/newbro/runtime/session.py tests/unit/runtime/test_session_runtime.py tests/integration/api/test_executor_text.py
git commit -m "Split compact bro bootstrap from session snapshot"
```

---

### Task 3: Replace Open Routes With Subscribe Routes

**Files:**
- Modify: `src/newbro/api/routes/sessions.py`
- Modify: `src/newbro/runtime/session.py`
- Modify: `src/newbro/runtime/bro_detail_thread_projection.py`
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`
- Test: `tests/integration/api/test_executor_text.py`

- [ ] **Step 1: Write failing projection test for subscribe without hydration**

Add to `tests/unit/runtime/test_bro_detail_thread_projection.py`:

```python
@pytest.mark.anyio
async def test_subscribe_bro_thread_does_not_load_timeline_or_sync_import(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()
    thread_id = "codex-import-1"
    projection.imported_codex_thread_resume_handles[thread_id] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )
    projection.imported_codex_threads[thread_id] = BroThread(
        thread_id=thread_id,
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        execution_session_id=None,
        status="completed",
        title="Imported thread",
        preview=None,
        progress=100,
        task_ids=[],
        active_task_id=None,
        latest_task_id=None,
        has_resume_handle=True,
        updated_at=None,
        diagnostics={"codex_thread_id": "native-thread-1"},
    )

    async def fail_sync(**_kwargs):
        raise AssertionError("subscribe must not sync thread list")

    async def fail_turns(**_kwargs):
        raise AssertionError("subscribe must not load timeline")

    monkeypatch.setattr(projection, "sync_imported_codex_threads", fail_sync)
    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fail_turns)

    response = await projection.subscribe_bro_thread(target_persona_id=persona.persona_id, thread_id=thread_id)

    assert response.thread_id == thread_id
    assert response.persona_id == persona.persona_id
    assert response.subscribed is True
```

- [ ] **Step 2: Write failing API route tests**

In `tests/integration/api/test_executor_text.py`, update existing `/open` tests to `/subscribe` and add:

```python
@pytest.mark.anyio
async def test_open_thread_route_is_removed(client):
    session_response = await client.post("/api/sessions")
    session_id = session_response.json()["session_id"]

    response = await client.post(
        f"/api/sessions/{session_id}/bro-threads/codex-import-missing/open",
        json={"target_persona_id": "forge"},
    )

    assert response.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_subscribe_bro_thread_does_not_load_timeline_or_sync_import tests/integration/api/test_executor_text.py::test_open_thread_route_is_removed -q
```

Expected: projection test FAILS because `subscribe_bro_thread` does not exist; route test FAILS because `/open` still exists.

- [ ] **Step 4: Rename runtime methods and remove hydration from subscribe**

In `src/newbro/runtime/bro_detail_thread_projection.py`:

- Rename `open_bro_thread` to `subscribe_bro_thread`.
- Rename `_open_bro_thread_locked` to `_subscribe_bro_thread_locked`.
- Rename `close_bro_thread` to `unsubscribe_bro_thread`.
- Rename `open_bro_thread_locks` field to `subscribe_bro_thread_locks`.
- In `subscribe_bro_thread`, remove the `codex_thread_open_needs_import_sync(...)` call and the call to `load_bro_thread_timeline(...)`.
- Return `BroThreadSubscriptionResponse`.

The subscribe return should be:

```python
return BroThreadSubscriptionResponse(
    thread_id=resolved_thread_id,
    persona_id=persona.persona_id,
    subscribed=True,
    timeline_status=self.timeline_status.get(resolved_thread_id, "not_loaded"),
    timeline_error=self.timeline_errors.get(resolved_thread_id),
)
```

For unknown imported mapping, raise:

```python
raise ValueError("Thread is not loaded; list thread page first.")
```

In `SessionRuntime`, rename delegates:

```python
    async def subscribe_bro_thread(self, *, target_persona_id: str, thread_id: str):
        return await self._bro_detail_thread_projection().subscribe_bro_thread(
            target_persona_id=target_persona_id,
            thread_id=thread_id,
        )

    async def unsubscribe_bro_thread(self, *, target_persona_id: str, thread_id: str | None = None):
        return await self._bro_detail_thread_projection().unsubscribe_bro_thread(
            target_persona_id=target_persona_id,
            thread_id=thread_id,
        )
```

- [ ] **Step 5: Replace API routes**

In `src/newbro/api/routes/sessions.py`, remove `/open` route functions and add:

```python
@router.post("/sessions/{session_id}/bro-threads/{thread_id}/subscribe")
async def subscribe_bro_thread(
    session_id: str,
    thread_id: str,
    body: OpenBroThreadRequest,
    request: Request,
):
    await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
        return await session.subscribe_bro_thread(
            target_persona_id=body.target_persona_id,
            thread_id=thread_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=_conflict_detail(exc, "Unable to subscribe to this thread.")) from exc


@router.delete("/sessions/{session_id}/bro-threads/{thread_id}/subscribe")
async def unsubscribe_bro_thread(
    session_id: str,
    thread_id: str,
    body: OpenBroThreadRequest,
    request: Request,
):
    await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
        return await session.unsubscribe_bro_thread(
            target_persona_id=body.target_persona_id,
            thread_id=thread_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=_conflict_detail(exc, "Unable to unsubscribe from this thread.")) from exc
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py tests/integration/api/test_executor_text.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/api/routes/sessions.py src/newbro/runtime/session.py src/newbro/runtime/bro_detail_thread_projection.py tests/unit/runtime/test_bro_detail_thread_projection.py tests/integration/api/test_executor_text.py
git commit -m "Replace bro thread open with subscribe"
```

---

### Task 4: Return Thread Summary From Timeline Page

**Files:**
- Modify: `src/newbro/runtime/models.py`
- Modify: `src/newbro/runtime/bro_detail_thread_projection.py`
- Modify: `src/newbro/ui/src/types.ts`
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`

- [ ] **Step 1: Write failing backend test**

Add to `tests/unit/runtime/test_bro_detail_thread_projection.py`:

```python
@pytest.mark.anyio
async def test_list_bro_timeline_page_returns_thread_summary(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
        opaque={"title": "Imported thread", "cwd": "/workspace"},
    )
    projection.imported_codex_threads["codex-import-1"] = BroThread(
        thread_id="codex-import-1",
        persona_id=persona.persona_id,
        persona_name=persona.name,
        executor_id="codex",
        executor_node_id="node-forge",
        workspace_id="/workspace",
        workspace_name="workspace",
        execution_session_id=None,
        status="completed",
        title="Imported thread",
        preview="Preview",
        progress=100,
        task_ids=[],
        active_task_id=None,
        latest_task_id=None,
        has_resume_handle=True,
        updated_at=None,
        diagnostics={"codex_thread_id": "native-thread-1"},
    )

    async def fake_request_codex_thread_turns(**_kwargs):
        return CodexThreadTurnPage(thread_id="native-thread-1", turns=[], goal=None)

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    page = await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
        cursor=None,
        limit=15,
    )

    assert page.thread.thread_id == "codex-import-1"
    assert page.thread.title == "Imported thread"
    assert page.thread.workspace_id == "/workspace"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_list_bro_timeline_page_returns_thread_summary -q
```

Expected: FAIL because `BroTimelineTurnPageResponse` has no `thread` field.

- [ ] **Step 3: Add `thread` to response model and projection**

In `src/newbro/runtime/models.py`, change:

```python
class BroTimelineTurnPageResponse(BaseModel):
    thread_id: str
    thread: BroThread
    turns: list[BroTimelineTurn] = Field(default_factory=list)
    page: CursorPageInfo = Field(default_factory=CursorPageInfo)
```

In `list_bro_timeline_page`, build:

```python
        thread = self.imported_codex_threads.get(public_thread_id)
        if thread is None:
            raise ValueError("Thread is not loaded; list thread page first.")
```

and return:

```python
        return BroTimelineTurnPageResponse(
            thread_id=public_thread_id,
            thread=self.with_timeline_state([thread])[0],
            turns=turns,
            page=info,
        )
```

- [ ] **Step 4: Update frontend type**

In `src/newbro/ui/src/types.ts`, change `BroTimelineTurnPageResponse` to:

```ts
export interface BroTimelineTurnPageResponse {
  thread_id: string;
  thread: BroThread;
  turns: BroTimelineTurn[];
  page: CursorPageInfo;
}
```

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/runtime/models.py src/newbro/runtime/bro_detail_thread_projection.py src/newbro/ui/src/types.ts tests/unit/runtime/test_bro_detail_thread_projection.py
git commit -m "Return thread summary with timeline pages"
```

---

### Task 5: Update Frontend Client And Shell Flow

**Files:**
- Modify: `src/newbro/ui/src/types.ts`
- Modify: `src/newbro/ui/src/lib/session-client.ts`
- Modify: `src/newbro/ui/src/lib/session-client.test.ts`
- Modify: `src/newbro/ui/src/NewbroShell.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Write failing client tests**

In `src/newbro/ui/src/lib/session-client.test.ts`, replace open/close tests with:

```ts
it("subscribes to a bro thread through the subscribe endpoint", async () => {
  const fetchMock = vi.fn(async () =>
    okJsonResponse({
      thread_id: "codex-import-1",
      persona_id: "forge",
      subscribed: true,
      timeline_status: "not_loaded",
      timeline_error: null,
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  const client = await import("./session-client");
  await client.subscribeBroThread("session-1", {
    targetPersonaId: "forge",
    threadId: "codex-import-1",
  });

  expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/bro-threads/codex-import-1/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_persona_id: "forge" }),
  });
});

it("unsubscribes from a bro thread through the subscribe endpoint", async () => {
  const fetchMock = vi.fn(async () =>
    okJsonResponse({
      thread_id: "codex-import-1",
      persona_id: "forge",
      subscribed: false,
      timeline_status: "loaded",
      timeline_error: null,
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  const client = await import("./session-client");
  await client.unsubscribeBroThread("session-1", {
    targetPersonaId: "forge",
    threadId: "codex-import-1",
  });

  expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/bro-threads/codex-import-1/subscribe", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_persona_id: "forge" }),
  });
});
```

Add a `listBros` URL test:

```ts
it("lists compact bros", async () => {
  const fetchMock = vi.fn(async () => okJsonResponse({ bros: [] }));
  vi.stubGlobal("fetch", fetchMock);

  const client = await import("./session-client");
  await client.listBros("session-1");

  expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/bros");
});
```

- [ ] **Step 2: Run client tests to verify they fail**

Run:

```bash
cd src/newbro/ui && bun run test -- src/lib/session-client.test.ts -t "subscribes|unsubscribes|compact bros"
```

Expected: FAIL because client functions do not exist or still call `/open`.

- [ ] **Step 3: Add frontend types and clients**

In `src/newbro/ui/src/types.ts`, add:

```ts
export interface BroExecutorCapabilitySummary {
  version: string | null;
  minimum_version: string | null;
  availability_reason: string | null;
  supports_thread_list: boolean;
  supports_audio_instruction: boolean;
}

export interface BroExecutorNodeSummary {
  node_id: string;
  name: string;
  connection_status: "connected" | "disconnected";
  enabled_executors: string[];
  codex: BroExecutorCapabilitySummary | null;
}

export interface BroSummary {
  persona_id: string;
  name: string;
  avatar: string;
  status: string;
  executor_node: BroExecutorNodeSummary | null;
}

export interface BroListResponse {
  bros: BroSummary[];
}

export interface BroThreadSubscriptionResponse {
  thread_id: string;
  persona_id: string;
  subscribed: boolean;
  timeline_status: "not_loaded" | "loading" | "loaded" | "failed";
  timeline_error: string | null;
}
```

In `src/newbro/ui/src/lib/session-client.ts`, add:

```ts
export async function listBros(sessionId: string): Promise<BroListResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bros`));
  return (await ensureOk(response)).json();
}

export async function subscribeBroThread(
  sessionId: string,
  payload: { targetPersonaId: string; threadId: string },
): Promise<BroThreadSubscriptionResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads/${encodeURIComponent(payload.threadId)}/subscribe`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_persona_id: payload.targetPersonaId }),
  });
  return (await ensureOk(response)).json();
}

export async function unsubscribeBroThread(
  sessionId: string,
  payload: { targetPersonaId: string; threadId: string },
): Promise<BroThreadSubscriptionResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads/${encodeURIComponent(payload.threadId)}/subscribe`), {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_persona_id: payload.targetPersonaId }),
  });
  return (await ensureOk(response)).json();
}
```

Remove `openBroThread` and `closeBroThread`.

- [ ] **Step 4: Update shell flow**

In `src/newbro/ui/src/NewbroShell.tsx`:

- import `listBros`, `subscribeBroThread`, `unsubscribeBroThread`
- add state for compact bro list if the existing adapter cannot be fed directly from snapshot
- call `listBros(sessionId)` in `loadShellSession` alongside `getSessionSnapshot` and `getConversationSnapshot`
- update `openRuntimeBroThread` to:

```ts
      const subscription = await subscribeBroThread(activeShellSessionId, { targetPersonaId, threadId });
      const page = await listBroTimelinePage(activeShellSessionId, {
        targetPersonaId,
        threadId,
        cursor: null,
        limit: 15,
      });
      if (!mountedRef.current || threadOpenLatestKeyRef.current !== openKey) {
        return;
      }
      startTransition(() => {
        setBroThreads((current) => upsertBroThreads(current, [page.thread]));
        setBroTimelineTurns((current) => mergeTimelineTurns(current, page.turns));
        setBroTimelinePages((current) => ({ ...current, [threadId]: page.page }));
      });
```

Use local helper functions rather than duplicating merge logic:

```ts
function upsertBroThreads(current: BroThread[], incoming: BroThread[]): BroThread[] {
  const byId = new Map(current.map((thread) => [thread.thread_id, thread]));
  for (const thread of incoming) byId.set(thread.thread_id, thread);
  return Array.from(byId.values());
}

function mergeTimelineTurns(current: BroTimelineTurn[], incoming: BroTimelineTurn[]): BroTimelineTurn[] {
  const seen = new Set(incoming.map((turn) => turn.turn_id));
  return [...incoming, ...current.filter((turn) => !seen.has(turn.turn_id))];
}
```

Update close path to call `unsubscribeBroThread` and locally clear selected status without expecting a full snapshot response.

- [ ] **Step 5: Update UI tests**

In `src/newbro/ui/src/__tests__/App.test.tsx`:

- replace mock functions `openBroThread`/`closeBroThread` with `subscribeBroThread`/`unsubscribeBroThread`
- add `listBros`
- update expectations to assert selection calls subscribe then timeline

Example assertion:

```ts
await waitFor(() => {
  expect(clientMock.subscribeBroThread).toHaveBeenCalledWith("session-existing", {
    targetPersonaId: "forge",
    threadId: "codex-import-history",
  });
});
expect(clientMock.listBroTimelinePage).toHaveBeenCalledWith("session-existing", {
  targetPersonaId: "forge",
  threadId: "codex-import-history",
  cursor: null,
  limit: 15,
});
```

- [ ] **Step 6: Run frontend focused tests**

Run:

```bash
cd src/newbro/ui && bun run test -- src/lib/session-client.test.ts src/__tests__/App.test.tsx src/lib/splitLiveSteps.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/types.ts src/newbro/ui/src/lib/session-client.ts src/newbro/ui/src/lib/session-client.test.ts src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "Load bro detail data from split api clients"
```

---

### Task 6: Update Stable Docs And Memory

**Files:**
- Modify: `docs/protocol/execution-session-and-run.md`
- Modify: `docs/architecture/executors.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Update protocol doc**

In `docs/protocol/execution-session-and-run.md`, replace the current text that says `SessionSnapshot` includes bounded imported pages and selected history metadata with:

```markdown
`SessionSnapshot` is local runtime state and must not perform remote Codex
`thread/list` or `thread/turns/list` reads. Bro Detail clients load compact
Bro/node bootstrap data through `GET /sessions/{session_id}/bros`, imported
thread pages through `GET /sessions/{session_id}/bro-threads`, selected thread
history through `GET /sessions/{session_id}/bro-threads/{thread_id}/timeline`,
and selected-thread live event interest through `POST/DELETE
/sessions/{session_id}/bro-threads/{thread_id}/subscribe`.
```

- [ ] **Step 2: Update architecture doc**

In `docs/architecture/executors.md`, update the Codex adapter direction to state:

```markdown
The subscribe endpoint is live-event interest only. It does not hydrate native
history and does not search thread-list pages. Thread pages and timeline pages
are explicit paged API reads, and session snapshots do not trigger Codex app
server data reads.
```

- [ ] **Step 3: Append memory note**

Append under `## 2026-06-05` in `docs/memories.md`:

```markdown
- Split Bro Detail data loading so session snapshots no longer trigger remote Codex reads; compact Bro/node bootstrap, imported thread pages, selected timeline pages, and selected-thread subscribe/unsubscribe are separate APIs, with `/open` removed.
```

- [ ] **Step 4: Commit**

```bash
git add docs/protocol/execution-session-and-run.md docs/architecture/executors.md docs/memories.md
git commit -m "Document split bro detail data apis"
```

---

### Task 7: Final Verification

**Files:**
- No code edits unless tests fail.

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py tests/unit/runtime/test_session_runtime.py tests/integration/api/test_executor_text.py tests/unit/runtime/test_codex_multi_message_turn.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused tests**

Run:

```bash
cd src/newbro/ui && bun run test -- src/lib/session-client.test.ts src/__tests__/App.test.tsx src/lib/splitLiveSteps.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run full backend suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: PASS.

- [ ] **Step 4: Run full frontend suite**

Run:

```bash
cd src/newbro/ui && bun run test
```

Expected: PASS.

- [ ] **Step 5: Check removed `/open` references**

Run:

```bash
rg -n "openBroThread|closeBroThread|/open|open_bro_thread|close_bro_thread" src/newbro tests docs/protocol docs/architecture
```

Expected: no active code/test/stable-doc references to the removed Bro thread open API. Historical `docs/superpowers/` plan/spec files may still mention `/open`.

- [ ] **Step 6: Commit only if verification required fixes**

If verification required fixes, commit them:

```bash
git add -u
git commit -m "Fix split bro detail api regressions"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review Notes

- Spec coverage: Tasks cover compact Bro/node API, session snapshot reduction, explicit thread pages, explicit timeline pages with thread summary, subscribe-only replacement for `/open`, UI flow changes, docs, and memory.
- Placeholder scan: No `TBD`, `TODO`, "similar to", or undefined implementation placeholders are intentionally left.
- Type consistency: Backend response types are `BroListResponse`, `BroThreadSubscriptionResponse`, and `BroTimelineTurnPageResponse.thread`; frontend mirrors them as `BroListResponse`, `BroThreadSubscriptionResponse`, and `BroTimelineTurnPageResponse.thread`.
