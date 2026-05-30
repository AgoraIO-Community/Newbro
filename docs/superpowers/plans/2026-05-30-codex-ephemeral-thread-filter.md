# Filter Codex Ephemeral Threads From Bro Detail Imports — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip Codex threads flagged `ephemeral=True` when `_sync_imported_codex_threads()` imports `thread/list` results, so the Bro Detail new-thread workspace picker, the workspace validator, and the imported thread list stop surfacing Codex scratch/internal workspaces.

**Architecture:** A single guard inside the per-thread loop in `_sync_imported_codex_threads()` drops items whose `CodexThreadListItem.diagnostics["ephemeral"]` is exactly `True`. A per-node `runtime.codex_thread_sync` observability event records `imported_count` and `skipped_ephemeral_count` so the filter is debuggable from the diagnostics timeline. No protocol-model or frontend change; the picker, validator, and Bro Detail thread list inherit the change automatically because they all derive from `self._imported_codex_threads`.

**Tech Stack:** Python 3.12, FastAPI, pytest with `monkeypatch`, the existing `httpx.AsyncClient` integration harness in `tests/integration/api/test_executor_text.py`.

**Spec:** `docs/superpowers/specs/2026-05-30-codex-ephemeral-thread-filter-design.md`

---

## File Structure

- **Modify:** `src/newbro/runtime/session.py` — add `_is_ephemeral_codex_thread()` module helper near `_sync_imported_codex_threads()`; add ephemeral guard and per-node `emit_event` inside the sync loop.
- **Modify:** `tests/integration/api/test_executor_text.py` — add one new integration test that monkeypatches `request_codex_threads` with a mix of ephemeral and non-ephemeral items and asserts only the non-ephemeral one is imported.

That's it — one production file, one test file. The Bro Detail picker, `_known_codex_workspaces_for_persona()`, and the workspace validator all read from `self._imported_codex_threads`, so they pick up the change with no additional edits.

---

## Task 1: Add failing integration test for ephemeral skip

**Files:**
- Modify: `tests/integration/api/test_executor_text.py` (append a new test function near the existing `test_executor_text_instruction_targets_imported_codex_thread` at line 580)

- [ ] **Step 1.1: Add the new failing test**

Append this function to `tests/integration/api/test_executor_text.py`. It follows the exact harness the file already uses (see the existing test at line 580 and its `fake_request_codex_threads` pattern at line 636 for shape reference). The test creates a node-bound persona, returns one ephemeral and one normal `CodexThreadListItem` from `request_codex_threads`, fetches the session snapshot, and asserts only the normal thread becomes a `BroThread`.

```python
@pytest.mark.asyncio
async def test_sync_imported_codex_threads_skips_ephemeral_entries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    app = create_app()
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    websocket = FakeWebSocket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _redeem(client, app, code="invite-ephemeral-skip")
        session_id = (await client.post("/api/sessions")).json()["session_id"]
        runtime_session = app.state.runtime_container.get_session(session_id)
        manager = app.state.runtime_container.executor_node_manager
        manager._connections_by_node["node-forge"] = NodeConnectionState(
            websocket=websocket,
            node_id="node-forge",
            connected_at="2026-05-30T00:00:00+00:00",
            executors={
                "codex": ExecutorNodeExecutor(
                    executor_type="codex",
                    supports_resume=True,
                    supports_follow_up=True,
                    supports_audio_instruction=True,
                    supports_thread_list=True,
                )
            },
        )
        await runtime_session.blackboard.put_persona(
            Persona(
                persona_id="forge",
                name="Forge",
                avatar="bro",
                base_prompt="",
                executor_node_id="node-forge",
                bro_detail_session_id="detail-forge",
                status="idle",
            )
        )

        async def fake_request_codex_threads(*, node_id: str, workspace_id=None, timeout_seconds: float = 8.0):
            assert node_id == "node-forge"
            return [
                CodexThreadListItem(
                    thread_id="codex-real",
                    session_id="codex-real",
                    preview="Real project work",
                    status="notLoaded",
                    cwd="/Users/zhangqianze/Documents/Synopse",
                    created_at=1779850000,
                    updated_at=1779850100,
                    cli_version="0.133.0",
                    source="vscode",
                    diagnostics={"ephemeral": False},
                ),
                CodexThreadListItem(
                    thread_id="codex-scratch",
                    session_id="codex-scratch",
                    preview="Scratch turn",
                    status="notLoaded",
                    cwd="/Users/zhangqianze/.codex/scratch/abc",
                    created_at=1779850200,
                    updated_at=1779850300,
                    cli_version="0.133.0",
                    source="cli",
                    diagnostics={"ephemeral": True},
                ),
            ]

        monkeypatch.setattr(manager, "request_codex_threads", fake_request_codex_threads)

        snapshot = (await client.get(f"/api/sessions/{session_id}")).json()
        imported = [
            thread
            for thread in snapshot["bro_threads"]
            if thread.get("diagnostics", {}).get("imported_from_codex_thread_list") is True
        ]
        assert len(imported) == 1, imported
        assert imported[0]["workspace_id"] == "/Users/zhangqianze/Documents/Synopse"
        assert imported[0]["diagnostics"].get("ephemeral") is False

        workspaces = await runtime_session._known_codex_workspaces_for_persona(
            await runtime_session.blackboard.get_persona("forge")
        )
        assert "/Users/zhangqianze/Documents/Synopse" in workspaces
        assert "/Users/zhangqianze/.codex/scratch/abc" not in workspaces
```

Verify that `CodexThreadListItem`, `NodeConnectionState`, `ExecutorNodeExecutor`, `Persona`, `FakeWebSocket`, `PublicAuthStore`, `create_app`, `AsyncClient`, `ASGITransport`, and `_redeem` are already imported at the top of `tests/integration/api/test_executor_text.py` from the existing tests in this file — they are used by `test_executor_text_instruction_targets_imported_codex_thread` and earlier tests. Do not add new imports unless one is genuinely missing.

- [ ] **Step 1.2: Run the new test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py::test_sync_imported_codex_threads_skips_ephemeral_entries -v
```

Expected: FAIL. The assertion `len(imported) == 1` will report `2` because `_sync_imported_codex_threads()` currently imports both threads — the ephemeral guard does not exist yet.

---

## Task 2: Implement ephemeral filter in `_sync_imported_codex_threads()`

**Files:**
- Modify: `src/newbro/runtime/session.py:1679-1781` (`_sync_imported_codex_threads`) and the module-level helpers area just above it.

- [ ] **Step 2.1: Add `_is_ephemeral_codex_thread()` helper**

Find a suitable spot in `src/newbro/runtime/session.py` immediately *above* the `_sync_imported_codex_threads()` method's enclosing class (i.e. in the module-level helpers band near the existing `_workspace_from_resume_handle`, `_task_workspace_id`, `_codex_thread_status`, etc.). Add:

```python
def _is_ephemeral_codex_thread(codex_thread: "CodexThreadListItem") -> bool:
    """Return True only when Codex explicitly flagged the thread as ephemeral.

    Codex puts the flag at `diagnostics["ephemeral"]` (see
    `executors/node/service.py:1124`). We treat the strict boolean `True` as
    ephemeral and pass through every other value — including `False`, `None`,
    a missing key, or a non-boolean — as non-ephemeral.
    """
    return codex_thread.diagnostics.get("ephemeral") is True
```

If `CodexThreadListItem` is not already imported in `session.py`, add it to the existing import block from `newbro.protocol.executor_node`. Confirm by grepping the file first — it may already be imported.

- [ ] **Step 2.2: Skip ephemeral threads inside the sync loop**

In `_sync_imported_codex_threads()` (around line 1726 in `src/newbro/runtime/session.py`), the current shape is:

```python
            for node_id, node_personas in personas_by_node.items():
                try:
                    codex_threads = await self.executor_node_manager.request_codex_threads(node_id=node_id)
                except Exception as exc:
                    LOGGER.warning("Failed to import Codex threads from node %s: %s", node_id, exc)
                    continue
                for codex_thread in codex_threads:
                    if codex_thread.thread_id in existing_codex_thread_ids:
                        continue
                    for persona in node_personas:
                        ...
```

Change it to track per-node counts and guard ephemeral threads *before* the persona inner loop:

```python
            for node_id, node_personas in personas_by_node.items():
                try:
                    codex_threads = await self.executor_node_manager.request_codex_threads(node_id=node_id)
                except Exception as exc:
                    LOGGER.warning("Failed to import Codex threads from node %s: %s", node_id, exc)
                    continue
                skipped_ephemeral_count = 0
                imported_thread_count = 0
                for codex_thread in codex_threads:
                    if codex_thread.thread_id in existing_codex_thread_ids:
                        continue
                    if _is_ephemeral_codex_thread(codex_thread):
                        skipped_ephemeral_count += 1
                        continue
                    imported_thread_count += 1
                    for persona in node_personas:
                        ...
                self.observability.logger.emit_event(
                    level="INFO",
                    event_name="runtime.codex_thread_sync",
                    component="runtime.bro_threads",
                    summary="Codex thread import sync",
                    conversation_id=self.session_id,
                    details={
                        "executor_node_id": node_id,
                        "total_thread_count": len(codex_threads),
                        "imported_thread_count": imported_thread_count,
                        "skipped_ephemeral_count": skipped_ephemeral_count,
                    },
                )
```

Do not touch the lines that build `public_thread_id`, `status`, `thread_title`, `thread_updated_at`, `resume_handle`, `diagnostics`, or that write into `imported_threads` / `imported_resume_handles`. The ephemeral guard must run *before* the `for persona in node_personas` block but *after* the `existing_codex_thread_ids` skip, so the existing dedup behavior is preserved and ephemeral threads are counted once per Codex thread instead of once per persona.

Verify by reading lines 1714-1781 of `src/newbro/runtime/session.py` after the edit that:

- the helper is called once per `codex_thread`,
- `imported_thread_count` is incremented only on threads we actually project,
- `emit_event` runs once per node (inside the outer `for node_id, node_personas`), not once per thread or once per persona,
- the existing return statement on the function still returns `list(imported_threads.values())`.

The `emit_event` signature matches the existing usage at `src/newbro/runtime/session.py:1564` — copy that call pattern (`level`, `event_name`, `component`, `summary`, `conversation_id`, `details`).

- [ ] **Step 2.3: Run the new test to verify it now passes**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py::test_sync_imported_codex_threads_skips_ephemeral_entries -v
```

Expected: PASS. The ephemeral thread is filtered out, `len(imported) == 1`, and the workspace set excludes `/Users/zhangqianze/.codex/scratch/abc`.

- [ ] **Step 2.4: Run adjacent tests to guard against regression**

Run the full `test_executor_text.py` module plus the runtime unit tests:

```bash
.venv/bin/python -m pytest tests/integration/api/test_executor_text.py tests/unit/runtime/test_session_runtime.py -v
```

Expected: all tests pass. Pay attention to `test_executor_text_instruction_targets_imported_codex_thread` at line 580 — it uses a single non-ephemeral fixture, so it must still pass unchanged.

---

## Task 3: Run the full test suite

- [ ] **Step 3.1: Run all Python tests**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass (or the same set that was already passing on the branch before this change). If any unrelated test fails, that's pre-existing; capture the names and check `git stash; pytest <test>` against base to confirm before assuming the change is at fault.

---

## Task 4: Commit

- [ ] **Step 4.1: Stage and commit on the existing branch**

The branch `filter-ephemeral-codex-threads` already exists with the spec committed. Stage the implementation and test changes and commit:

```bash
git add src/newbro/runtime/session.py tests/integration/api/test_executor_text.py
git commit -m "$(cat <<'EOF'
feat: skip Codex ephemeral threads when importing into Bro Detail

Codex returns ephemeral/scratch threads in thread/list with
diagnostics.ephemeral=True. We were importing all of them, which leaked
~/.codex/* cwds into the Bro Detail new-thread workspace picker and the
workspace validator. Filter on the ephemeral flag inside
_sync_imported_codex_threads(), and emit a runtime.codex_thread_sync
observability event per node with imported and skipped counts.

Spec: docs/superpowers/specs/2026-05-30-codex-ephemeral-thread-filter-design.md
EOF
)"
```

- [ ] **Step 4.2: Confirm the commit landed**

Run:

```bash
git status
git log --oneline -3
```

Expected: working tree clean, top commit is `feat: skip Codex ephemeral threads when importing into Bro Detail`, and the previous commit is the spec.

---

## Self-Review Notes (already addressed; recorded for the executor)

- **Spec coverage:** Filter semantics → Task 2.1 helper. Single change point → Task 2.2 inside `_sync_imported_codex_threads()`. Observability `skipped_ephemeral_count` → Task 2.2 `emit_event` block. Tests for ephemeral/non-ephemeral/None/missing → Task 1.1 covers `True`/`False`; the non-boolean and missing cases are covered by the helper's `is True` check on the strict-boolean rule (one explicit `False` and one normal thread without an `ephemeral` key in the spec are sufficient at the integration layer; defensive coverage stays in the helper docstring and isn't worth additional integration scaffolding).
- **No placeholders:** every code block is concrete; no TBD/TODO; all file paths and line numbers reference real call sites.
- **Type consistency:** `_is_ephemeral_codex_thread()` consumes `CodexThreadListItem` (defined in `src/newbro/protocol/executor_node.py:83`) and returns `bool`. `emit_event` matches the existing call at `src/newbro/runtime/session.py:1564`.
