# Paged Codex Data Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require `codex-cli >= 0.135.0` and preserve Codex `limit`/`cursor` paging through Newbro backend APIs and UI for imported thread lists and selected-thread history.

**Architecture:** Add typed page metadata to protocol/runtime models, propagate native Codex cursors through executor node commands, and expose explicit Newbro page endpoints instead of relying on large `SessionSnapshot` arrays. Snapshots keep bounded first/current pages for continuity; UI "show more" actions call page endpoints and append returned records.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Pytest, React, TypeScript, Vite/Vitest.

---

## File Structure

- Modify `src/newbro/protocol/executor_node.py`: add cursor fields to Codex list commands/responses and add a selected-thread turn page command/response.
- Modify `src/newbro/executors/adapters/codex/probe.py`: parse Codex CLI versions and expose `CODEX_MINIMUM_SUPPORTED_VERSION = (0, 135, 0)`.
- Modify `src/newbro/executors/core/capabilities.py` and `src/newbro/protocol/executor_node.py`: carry `version`, `minimum_version`, and `availability_reason` for Codex capabilities.
- Modify `src/newbro/executors/node/service.py`: reject/degrade old Codex versions in descriptors and forward page parameters to executor methods.
- Modify `src/newbro/runtime/executor_node_manager.py`: request and publish paged Codex thread and turn data.
- Modify `src/newbro/executors/adapters/codex/client.py` and `src/newbro/executors/adapters/codex/executor.py`: remove legacy thread-list fallback, return one native page per call, and support `thread/turns/list` cursor.
- Modify `src/newbro/runtime/models.py`: add page info and page response models.
- Modify `src/newbro/runtime/bro_detail_thread_projection.py`: cache/import bounded Codex thread pages, keep selected threads visible, and load selected timeline pages through cursor-aware turn reads.
- Modify `src/newbro/api/routes/sessions.py`: add page endpoints for Bro threads and selected timeline turns.
- Modify `src/newbro/ui/src/types.ts`: add page metadata and response types.
- Modify `src/newbro/ui/src/lib/session-client.ts` and `src/newbro/ui/src/lib/session-client.test.ts`: add `listBroThreadsPage` and `listBroTimelinePage` clients.
- Modify `src/newbro/ui/src/NewbroShell.tsx`: maintain thread/timeline page state and expose load-more functions.
- Modify `src/newbro/ui/src/ArtboardShell.tsx`: call backend page APIs for "Show more" and "Load older" behavior.
- Modify `src/newbro/ui/src/__tests__/App.test.tsx`: cover backend paging from the UI.
- Modify stable docs: `docs/protocol/execution-session-and-run.md`, `docs/architecture/executors.md`, and append a short note to `docs/memories.md`.

---

### Task 1: Add Protocol Page Models

**Files:**
- Modify: `src/newbro/protocol/executor_node.py`
- Modify: `src/newbro/runtime/models.py`
- Test: `tests/unit/runtime/test_executor_node_manager.py`

- [ ] **Step 1: Write failing protocol tests**

Add these tests to `tests/unit/runtime/test_executor_node_manager.py` near the existing Codex list/read tests:

```python
@pytest.mark.anyio
async def test_request_codex_threads_sends_cursor_page_command():
    issue, manager = await _registered_manager_with_issue()
    sent_event = asyncio.Event()

    class CapturingSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            sent_event.set()

    socket = CapturingSocket()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    task = asyncio.create_task(
        manager.request_codex_threads(
            node_id=issue.node.node_id,
            workspace_id="/tmp/work",
            limit=25,
            cursor="cursor-1",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    command = socket.sent[-1]
    assert command["type"] == "list_codex_threads"
    assert command["workspace_id"] == "/tmp/work"
    assert command["limit"] == 25
    assert command["cursor"] == "cursor-1"
    assert command["sort_key"] == "updated_at"
    assert command["sort_direction"] == "desc"

    manager.publish_codex_threads_listed(
        CodexThreadsListedMessage(
            request_id=str(command["request_id"]),
            node_id=issue.node.node_id,
            threads=[],
            next_cursor="cursor-2",
            previous_cursor=None,
        )
    )
    page = await task
    assert page.threads == []
    assert page.next_cursor == "cursor-2"
    assert page.previous_cursor is None


@pytest.mark.anyio
async def test_request_codex_thread_turns_sends_cursor_page_command():
    issue, manager = await _registered_manager_with_issue()
    sent_event = asyncio.Event()

    class CapturingSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            sent_event.set()

    socket = CapturingSocket()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    task = asyncio.create_task(
        manager.request_codex_thread_turns(
            node_id=issue.node.node_id,
            thread_id="codex-thread-1",
            limit=50,
            cursor="older",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    command = socket.sent[-1]
    assert command["type"] == "list_codex_thread_turns"
    assert command["thread_id"] == "codex-thread-1"
    assert command["limit"] == 50
    assert command["cursor"] == "older"
    assert command["sort_direction"] == "desc"
    assert command["items_view"] == "full"

    manager.publish_codex_thread_turns_listed(
        CodexThreadTurnsListedMessage(
            request_id=str(command["request_id"]),
            node_id=issue.node.node_id,
            thread_id="codex-thread-1",
            turns=[],
            next_cursor=None,
            previous_cursor="newer",
        )
    )
    page = await task
    assert page.turns == []
    assert page.next_cursor is None
    assert page.previous_cursor == "newer"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_executor_node_manager.py::test_request_codex_threads_sends_cursor_page_command tests/unit/runtime/test_executor_node_manager.py::test_request_codex_thread_turns_sends_cursor_page_command -q
```

Expected: fail because `request_codex_threads` does not accept `limit`/`cursor` and `request_codex_thread_turns` does not exist.

- [ ] **Step 3: Add protocol models**

In `src/newbro/protocol/executor_node.py`, update and add these models:

```python
class ListCodexThreadsCommand(BaseModel):
    type: Literal["list_codex_threads"] = "list_codex_threads"
    request_id: str
    executor_type: Literal["codex"] = "codex"
    workspace_id: str | None = None
    limit: int = 100
    cursor: str | None = None
    sort_key: Literal["created_at", "updated_at"] = "updated_at"
    sort_direction: Literal["asc", "desc"] = "desc"


class CodexThreadsListedMessage(BaseModel):
    type: Literal["codex_threads_listed"] = "codex_threads_listed"
    request_id: str
    node_id: str
    executor_type: Literal["codex"] = "codex"
    ok: bool = True
    error: str | None = None
    threads: list[CodexThreadListItem] = Field(default_factory=list)
    next_cursor: str | None = None
    previous_cursor: str | None = None


class ListCodexThreadTurnsCommand(BaseModel):
    type: Literal["list_codex_thread_turns"] = "list_codex_thread_turns"
    request_id: str
    executor_type: Literal["codex"] = "codex"
    thread_id: str
    limit: int = 100
    cursor: str | None = None
    sort_direction: Literal["asc", "desc"] = "desc"
    items_view: Literal["summary", "full"] = "full"


class CodexThreadTurnsListedMessage(BaseModel):
    type: Literal["codex_thread_turns_listed"] = "codex_thread_turns_listed"
    request_id: str
    node_id: str
    executor_type: Literal["codex"] = "codex"
    ok: bool = True
    error: str | None = None
    thread_id: str
    turns: list[dict[str, object]] = Field(default_factory=list)
    goal: str | None = None
    next_cursor: str | None = None
    previous_cursor: str | None = None
```

Update `src/newbro/protocol/__init__.py` exports to include `ListCodexThreadTurnsCommand` and `CodexThreadTurnsListedMessage`.

- [ ] **Step 4: Add runtime page result models**

In `src/newbro/runtime/models.py`, add:

```python
class CursorPageInfo(BaseModel):
    next_cursor: str | None = None
    previous_cursor: str | None = None
    has_more: bool = False
    status: Literal["not_loaded", "loading", "loaded", "failed"] = "not_loaded"
    error: str | None = None


class BroThreadPageResponse(BaseModel):
    persona_id: str
    threads: list[BroThread] = Field(default_factory=list)
    page: CursorPageInfo = Field(default_factory=CursorPageInfo)


class BroTimelineTurnPageResponse(BaseModel):
    thread_id: str
    turns: list[BroTimelineTurn] = Field(default_factory=list)
    page: CursorPageInfo = Field(default_factory=CursorPageInfo)
```

Add fields to `SessionSnapshot`:

```python
bro_thread_pages: dict[str, CursorPageInfo] = Field(default_factory=dict)
bro_timeline_pages: dict[str, CursorPageInfo] = Field(default_factory=dict)
```

- [ ] **Step 5: Update `ExecutorNodeManager` page request plumbing**

In `src/newbro/runtime/executor_node_manager.py`:

```python
@dataclass(frozen=True, slots=True)
class CodexThreadListPage:
    threads: list[CodexThreadListItem]
    next_cursor: str | None = None
    previous_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CodexThreadTurnPage:
    thread_id: str
    turns: list[dict[str, object]]
    goal: str | None = None
    next_cursor: str | None = None
    previous_cursor: str | None = None
```

Update `request_codex_threads` to accept `limit`, `cursor`, `sort_key`, and `sort_direction`, send them in `ListCodexThreadsCommand`, and return `CodexThreadListPage`.

Add `_codex_thread_turn_list_requests: dict[str, asyncio.Future[CodexThreadTurnsListedMessage]] = {}` in `__init__`.

Add:

```python
async def request_codex_thread_turns(
    self,
    *,
    node_id: str,
    thread_id: str,
    limit: int = 100,
    cursor: str | None = None,
    timeout_seconds: float = 8.0,
) -> CodexThreadTurnPage:
    connection = await self._connection_for_node(node_id)
    if connection is None or "codex" not in connection.executors:
        raise RuntimeError("Codex executor node is not connected.")
    request_id = f"codex-thread-turns-{uuid4().hex[:12]}"
    loop = asyncio.get_running_loop()
    future: asyncio.Future[CodexThreadTurnsListedMessage] = loop.create_future()
    self._codex_thread_turn_list_requests[request_id] = future
    command = ListCodexThreadTurnsCommand(
        request_id=request_id,
        thread_id=thread_id,
        limit=limit,
        cursor=cursor,
    )
    try:
        await self._send_json(connection, command.model_dump(mode="json"))
        response = await asyncio.wait_for(future, timeout=timeout_seconds)
    except TimeoutError as exc:
        self._codex_thread_turn_list_requests.pop(request_id, None)
        raise TimeoutError("Timed out listing Codex thread turns.") from exc
    except Exception:
        self._codex_thread_turn_list_requests.pop(request_id, None)
        raise
    if not response.ok:
        raise RuntimeError(response.error or "Codex thread/turns/list failed.")
    return CodexThreadTurnPage(
        thread_id=response.thread_id,
        turns=response.turns,
        goal=response.goal,
        next_cursor=response.next_cursor,
        previous_cursor=response.previous_cursor,
    )


def publish_codex_thread_turns_listed(self, message: CodexThreadTurnsListedMessage) -> AckMessage:
    future = self._codex_thread_turn_list_requests.pop(message.request_id, None)
    if future is None:
        return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
    if not future.done():
        future.set_result(message)
    return AckMessage(message_type=message.type, detail="queued")
```

- [ ] **Step 6: Run protocol tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_executor_node_manager.py::test_request_codex_threads_sends_cursor_page_command tests/unit/runtime/test_executor_node_manager.py::test_request_codex_thread_turns_sends_cursor_page_command -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/protocol/executor_node.py src/newbro/protocol/__init__.py src/newbro/runtime/models.py src/newbro/runtime/executor_node_manager.py tests/unit/runtime/test_executor_node_manager.py
git commit -m "Add paged codex protocol models"
```

---

### Task 2: Enforce Minimum Codex Version

**Files:**
- Modify: `src/newbro/executors/adapters/codex/probe.py`
- Modify: `src/newbro/executors/core/capabilities.py`
- Modify: `src/newbro/protocol/executor_node.py`
- Modify: `src/newbro/executors/node/service.py`
- Test: `tests/unit/cli/test_executor_probe.py`
- Test: `tests/unit/executors/node/test_service.py`
- Test: `tests/unit/runtime/test_executor_node_manager.py`

- [ ] **Step 1: Write failing probe tests**

Append to `tests/unit/cli/test_executor_probe.py`:

```python
def test_codex_probe_rejects_version_below_minimum():
    from newbro.executors.adapters.codex import probe as codex_probe

    assert codex_probe.codex_version_tuple("codex-cli 0.134.9") == (0, 134, 9)
    assert codex_probe.codex_version_supported("codex-cli 0.134.9") is False
    assert codex_probe.codex_version_supported("codex-cli 0.135.0") is True
    assert codex_probe.codex_version_supported("codex-cli 0.137.0") is True
```

- [ ] **Step 2: Run probe test to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_executor_probe.py::test_codex_probe_rejects_version_below_minimum -q
```

Expected: fail because version helpers do not exist.

- [ ] **Step 3: Add version helpers**

In `src/newbro/executors/adapters/codex/probe.py`, add:

```python
import re

CODEX_MINIMUM_SUPPORTED_VERSION = (0, 135, 0)
CODEX_MINIMUM_SUPPORTED_VERSION_TEXT = "0.135.0"


def codex_version_tuple(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def codex_version_supported(version: str | None) -> bool:
    parsed = codex_version_tuple(version)
    return parsed is not None and parsed >= CODEX_MINIMUM_SUPPORTED_VERSION


def unsupported_codex_version_error(version: str | None) -> str:
    display = version or "unknown"
    return f"Codex CLI {display} is below Newbro's minimum supported version {CODEX_MINIMUM_SUPPORTED_VERSION_TEXT}."
```

- [ ] **Step 4: Make CLI probe mark old versions unavailable**

Update `probe_codex_command` so a successful `codex --version` below `0.135.0` returns `ok=False`:

```python
    if completed.returncode != 0:
        return CodexProbeResult(
            path=path,
            version=first_line,
            ok=False,
            error=first_line or f"codex --version exited {completed.returncode}",
        )
    if not codex_version_supported(first_line):
        return CodexProbeResult(
            path=path,
            version=first_line,
            ok=False,
            error=unsupported_codex_version_error(first_line),
        )
    return CodexProbeResult(path=path, version=first_line, ok=True)
```

- [ ] **Step 5: Write failing node descriptor test**

In `tests/unit/executors/node/test_service.py`, add:

```python
@pytest.mark.anyio
async def test_codex_descriptor_reports_unsupported_version(monkeypatch: pytest.MonkeyPatch):
    service = build_service(monkeypatch)
    executor = service._executors["codex"]
    executor._last_detected_version = "codex-cli 0.134.9"

    descriptor = await service._descriptor("codex", executor)

    assert descriptor.executor_type == "codex"
    assert descriptor.supports_thread_list is False
    assert descriptor.version == "codex-cli 0.134.9"
    assert descriptor.minimum_version == "0.135.0"
    assert descriptor.availability_reason == "unsupported_codex_version"
```

- [ ] **Step 6: Add capability metadata**

In `src/newbro/executors/core/capabilities.py`, add fields:

```python
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
```

In `src/newbro/protocol/executor_node.py`, add the same fields to `ExecutorNodeExecutor`:

```python
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
```

In `src/newbro/executors/adapters/codex/executor.py`, probe the configured CLI command directly before advertising app-server features. Do not infer the version from the app-server `initialize` response. Add `self._last_detected_version: str | None = None` in `__init__`, then update `refresh_capabilities`:

```python
from .probe import CODEX_MINIMUM_SUPPORTED_VERSION_TEXT, probe_codex_command

async def refresh_capabilities(self) -> ExecutorCapabilities:
    probe = probe_codex_command(self._command)
    self._last_detected_version = probe.version
    self._capabilities.version = probe.version
    self._capabilities.minimum_version = CODEX_MINIMUM_SUPPORTED_VERSION_TEXT
    self._capabilities.availability_reason = None if probe.ok else "unsupported_codex_version"
    supported = probe.ok
    self._capabilities.supports_resume = supported
    self._capabilities.supports_follow_up = supported
    self._capabilities.supports_thread_list = supported
    self._capabilities.supports_pause = supported
    self._capabilities.supports_cancel = supported
    return self._capabilities
```

In `src/newbro/executors/node/service.py`, forward these fields in `_descriptor`:

```python
            supports_thread_list=bool(
                executor_type == "codex"
                and hasattr(executor, "list_threads_page")
                and capabilities.availability_reason is None
            ),
            version=capabilities.version,
            minimum_version=capabilities.minimum_version,
            availability_reason=capabilities.availability_reason,
```

- [ ] **Step 7: Make runtime reject unsupported connected Codex**

In `src/newbro/runtime/executor_node_manager.py`, update `executor_supports_thread_list`:

```python
        return (
            executor is not None
            and executor.supports_thread_list
            and executor.availability_reason is None
        )
```

Add a test in `tests/unit/runtime/test_executor_node_manager.py`:

```python
@pytest.mark.anyio
async def test_unsupported_codex_node_does_not_support_thread_list():
    issue, manager = await _registered_manager_with_issue()
    await manager.register_connection(
        object(),
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[
                ExecutorNodeExecutor(
                    executor_type="codex",
                    supports_thread_list=True,
                    availability_reason="unsupported_codex_version",
                )
            ],
        ),
    )

    assert manager.executor_supports_thread_list("codex", node_id=issue.node.node_id) is False
```

- [ ] **Step 8: Run version tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_executor_probe.py::test_codex_probe_rejects_version_below_minimum tests/unit/executors/node/test_service.py::test_codex_descriptor_reports_unsupported_version tests/unit/runtime/test_executor_node_manager.py::test_unsupported_codex_node_does_not_support_thread_list -q
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add src/newbro/executors/adapters/codex/probe.py src/newbro/executors/adapters/codex/executor.py src/newbro/executors/core/capabilities.py src/newbro/protocol/executor_node.py src/newbro/executors/node/service.py src/newbro/runtime/executor_node_manager.py tests/unit/cli/test_executor_probe.py tests/unit/executors/node/test_service.py tests/unit/runtime/test_executor_node_manager.py
git commit -m "Require modern codex executor version"
```

---

### Task 3: Return Native Codex Pages From Executor Node

**Files:**
- Modify: `src/newbro/executors/adapters/codex/client.py`
- Modify: `src/newbro/executors/adapters/codex/executor.py`
- Modify: `src/newbro/executors/node/service.py`
- Modify: `src/newbro/api/ws/executors.py`
- Test: `tests/unit/executors/adapters/test_codex_executor.py`
- Test: `tests/unit/executors/node/test_service.py`

- [ ] **Step 1: Write failing adapter tests**

In `tests/unit/executors/adapters/test_codex_executor.py`, update the fake `thread/list` assertions in the existing paged fake to reject calls without sorted paging. Add this test near existing list tests:

```python
@pytest.mark.anyio
async def test_codex_list_threads_page_returns_single_native_page(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))

    page = await executor.list_threads_page(
        workspace_id="/tmp/imported-workspace",
        limit=100,
        cursor=None,
    )

    assert [item["id"] for item in page.items] == ["import-thread-1"]
    assert page.next_cursor == "page-2"
    assert page.previous_cursor is None
```

Add a turn page test:

```python
@pytest.mark.anyio
async def test_codex_list_thread_turns_page_sends_cursor(tmp_path):
    command = _write_thread_turns_list_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))

    page = await executor.list_thread_turns_page(
        thread_id="thread-open",
        limit=100,
        cursor="older-turns",
    )

    assert [turn["id"] for turn in page.turns] == ["turn-new", "turn-old"]
    assert page.next_cursor == "older-turns"
```

- [ ] **Step 2: Run adapter tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py::test_codex_list_threads_page_returns_single_native_page tests/unit/executors/adapters/test_codex_executor.py::test_codex_list_thread_turns_page_sends_cursor -q
```

Expected: fail because `list_threads_page` and `list_thread_turns_page` do not exist.

- [ ] **Step 3: Add cursor support to client**

In `src/newbro/executors/adapters/codex/client.py`, update `thread_turns_list`:

```python
    async def thread_turns_list(
        self,
        *,
        thread_id: str,
        cursor: str | None = None,
        limit: int | None = None,
        sort_direction: str | None = None,
        items_view: str | None = None,
    ) -> dict[str, object]:
        params: dict[str, object] = {"threadId": thread_id}
        if cursor is not None:
            params["cursor"] = cursor
```

Keep the existing `limit`, `sortDirection`, and `itemsView` lines after the cursor block.

- [ ] **Step 4: Add adapter page result dataclasses**

In `src/newbro/executors/adapters/codex/executor.py`, add:

```python
@dataclass(frozen=True, slots=True)
class CodexNativeThreadListPage:
    items: list[dict[str, object]]
    next_cursor: str | None = None
    previous_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CodexNativeThreadTurnPage:
    turns: list[dict[str, object]]
    goal: str | None = None
    next_cursor: str | None = None
    previous_cursor: str | None = None
```

Add `from dataclasses import dataclass` if it is not already imported.

- [ ] **Step 5: Replace compatibility list flow with one-page method**

In `src/newbro/executors/adapters/codex/executor.py`, replace `list_threads` compatibility fallback with:

```python
    async def list_threads_page(
        self,
        workspace_id: str | None = None,
        *,
        limit: int = THREAD_LIST_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> CodexNativeThreadListPage:
        session = await self.create_session(workspace_id)
        response = await session.client.thread_list(
            cursor=cursor,
            limit=limit,
            sort_key="updated_at",
            sort_direction="desc",
        )
        data = response.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Codex thread/list returned an unsupported response shape.")
        return CodexNativeThreadListPage(
            items=[dict(item) for item in data if isinstance(item, dict)],
            next_cursor=response.get("nextCursor") if isinstance(response.get("nextCursor"), str) else None,
            previous_cursor=response.get("backwardsCursor") if isinstance(response.get("backwardsCursor"), str) else None,
        )
```

Keep a temporary compatibility wrapper for internal callers until runtime is migrated:

```python
    async def list_threads(self, workspace_id: str | None = None) -> list[dict[str, object]]:
        page = await self.list_threads_page(workspace_id, limit=THREAD_LIST_PAGE_LIMIT, cursor=None)
        return _sort_codex_threads(page.items)
```

- [ ] **Step 6: Add turn page method**

In `src/newbro/executors/adapters/codex/executor.py`, add:

```python
    async def list_thread_turns_page(
        self,
        *,
        thread_id: str,
        limit: int = THREAD_READ_TURNS_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> CodexNativeThreadTurnPage:
        session = await self.create_session(None)
        goal_response = await session.client.thread_goal_get(thread_id=thread_id)
        turns_response = await session.client.thread_turns_list(
            thread_id=thread_id,
            cursor=cursor,
            limit=limit,
            sort_direction="desc",
            items_view="full",
        )
        turns_data = turns_response.get("data")
        if not isinstance(turns_data, list):
            raise RuntimeError("Codex thread/turns/list returned an unsupported response shape.")
        return CodexNativeThreadTurnPage(
            turns=[dict(item) for item in turns_data if isinstance(item, dict)],
            goal=_extract_codex_goal(goal_response),
            next_cursor=turns_response.get("nextCursor") if isinstance(turns_response.get("nextCursor"), str) else None,
            previous_cursor=turns_response.get("backwardsCursor") if isinstance(turns_response.get("backwardsCursor"), str) else None,
        )
```

Update `read_thread` to call `thread_read(include_turns=False)` and `list_thread_turns_page(cursor=None)` for the initial bounded page.

- [ ] **Step 7: Update node service handlers**

In `src/newbro/executors/node/service.py`, update `_list_codex_threads` to call `list_threads_page` and include cursors:

```python
            raw_page = await list_threads_page(
                command.workspace_id,
                limit=command.limit,
                cursor=command.cursor,
            )
            threads = [_codex_thread_list_item(item) for item in raw_page.items]
```

Send:

```python
                CodexThreadsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    threads=threads,
                    next_cursor=raw_page.next_cursor,
                    previous_cursor=raw_page.previous_cursor,
                ).model_dump(mode="json"),
```

Add `_list_codex_thread_turns`:

```python
    async def _list_codex_thread_turns(self, websocket: Any, command: ListCodexThreadTurnsCommand) -> None:
        executor = self._executors.get(command.executor_type)
        list_turns = getattr(executor, "list_thread_turns_page", None)
        if list_turns is None:
            await self._send_json(
                websocket,
                CodexThreadTurnsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    thread_id=command.thread_id,
                    ok=False,
                    error="Codex executor does not support thread/turns/list.",
                ).model_dump(mode="json"),
            )
            return
        try:
            raw_page = await list_turns(
                thread_id=command.thread_id,
                limit=command.limit,
                cursor=command.cursor,
            )
            await self._send_json(
                websocket,
                CodexThreadTurnsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    thread_id=command.thread_id,
                    turns=raw_page.turns,
                    goal=raw_page.goal,
                    next_cursor=raw_page.next_cursor,
                    previous_cursor=raw_page.previous_cursor,
                ).model_dump(mode="json"),
            )
        except Exception as exc:
            await self._send_json(
                websocket,
                CodexThreadTurnsListedMessage(
                    request_id=command.request_id,
                    node_id=self._settings.node_id,
                    thread_id=command.thread_id,
                    ok=False,
                    error=str(exc),
                ).model_dump(mode="json"),
            )
```

In `_handle_message`, dispatch `list_codex_thread_turns` to this handler.

In `src/newbro/api/ws/executors.py`, handle inbound `codex_thread_turns_listed` by validating `CodexThreadTurnsListedMessage` and calling `publish_codex_thread_turns_listed`.

- [ ] **Step 8: Update node service tests**

In `tests/unit/executors/node/test_service.py`, update `test_list_codex_threads_returns_normalized_thread_list` expected payload to include:

```python
"next_cursor": None,
"previous_cursor": None,
```

Add:

```python
@pytest.mark.anyio
async def test_list_codex_thread_turns_returns_page(monkeypatch: pytest.MonkeyPatch):
    service = build_service(monkeypatch)
    websocket = FakeWebSocket([])

    await service._list_codex_thread_turns(
        websocket,
        service_module.ListCodexThreadTurnsCommand(
            request_id="req-turns-1",
            thread_id="codex-native-thread-1",
            cursor=None,
            limit=100,
        ),
    )

    assert websocket.sent[0]["type"] == "codex_thread_turns_listed"
    assert websocket.sent[0]["request_id"] == "req-turns-1"
    assert websocket.sent[0]["thread_id"] == "codex-native-thread-1"
    assert websocket.sent[0]["ok"] is True
    assert "turns" in websocket.sent[0]
    assert "next_cursor" in websocket.sent[0]
```

- [ ] **Step 9: Run adapter/node tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/executors/adapters/test_codex_executor.py::test_codex_list_threads_page_returns_single_native_page tests/unit/executors/adapters/test_codex_executor.py::test_codex_list_thread_turns_page_sends_cursor tests/unit/executors/node/test_service.py::test_list_codex_threads_returns_normalized_thread_list tests/unit/executors/node/test_service.py::test_list_codex_thread_turns_returns_page -q
```

Expected: pass.

- [ ] **Step 10: Commit**

```bash
git add src/newbro/executors/adapters/codex/client.py src/newbro/executors/adapters/codex/executor.py src/newbro/executors/node/service.py src/newbro/api/ws/executors.py tests/unit/executors/adapters/test_codex_executor.py tests/unit/executors/node/test_service.py
git commit -m "Use native codex cursor pages"
```

---

### Task 4: Add Runtime Bro Thread Page Projection

**Files:**
- Modify: `src/newbro/runtime/bro_detail_thread_projection.py`
- Modify: `src/newbro/runtime/session.py`
- Modify: `src/newbro/api/routes/sessions.py`
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write failing projection tests**

Add to `tests/unit/runtime/test_bro_detail_thread_projection.py`:

```python
@pytest.mark.anyio
async def test_imported_codex_threads_snapshot_uses_first_page_only(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()
    session.executor_node_manager._connections_by_node["node-forge"] = NodeConnectionState(
        websocket=object(),
        node_id="node-forge",
        connected_at="2026-06-05T00:00:00+00:00",
        executors={"codex": ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)},
    )

    async def fake_request_codex_threads(**kwargs):
        assert kwargs["limit"] == 25
        assert kwargs["cursor"] is None
        return CodexThreadListPage(
            threads=[
                CodexThreadListItem(thread_id="native-1", preview="Task: One", updated_at=1780650000),
            ],
            next_cursor="next-page",
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_threads", fake_request_codex_threads)

    snapshot = await projection.snapshot_parts(
        tasks=[],
        sessions=[],
        runs=[],
        summaries=[],
        personas=[persona],
        sync_imported_codex_threads=True,
    )

    assert [thread.title for thread in snapshot.bro_threads] == ["One"]
    assert projection.imported_codex_thread_page_info[persona.persona_id].next_cursor == "next-page"
    assert projection.imported_codex_thread_page_info[persona.persona_id].has_more is True


@pytest.mark.anyio
async def test_list_bro_thread_page_appends_cached_imported_threads(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()

    async def fake_request_codex_threads(**kwargs):
        assert kwargs["cursor"] == "next-page"
        return CodexThreadListPage(
            threads=[CodexThreadListItem(thread_id="native-2", preview="Task: Two", updated_at=1780650100)],
            next_cursor=None,
            previous_cursor="first-page",
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_threads", fake_request_codex_threads)
    page = await projection.list_bro_thread_page(
        persona=persona,
        sessions=[],
        limit=25,
        cursor="next-page",
    )

    assert [thread.title for thread in page.threads] == ["Two"]
    assert page.page.next_cursor is None
    assert page.page.previous_cursor == "first-page"
```

- [ ] **Step 2: Run projection tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_imported_codex_threads_snapshot_uses_first_page_only tests/unit/runtime/test_bro_detail_thread_projection.py::test_list_bro_thread_page_appends_cached_imported_threads -q
```

Expected: fail because page info and `list_bro_thread_page` do not exist.

- [ ] **Step 3: Add projection page state**

In `src/newbro/runtime/bro_detail_thread_projection.py`, add constants near the top:

```python
IMPORTED_CODEX_THREAD_PAGE_LIMIT = 25
SELECTED_CODEX_TURN_PAGE_LIMIT = 100
```

Add fields to `BroDetailThreadProjection`:

```python
    imported_codex_thread_page_info: dict[str, CursorPageInfo] = field(default_factory=dict)
    imported_codex_thread_pages_by_persona: dict[str, list[str]] = field(default_factory=dict)
    bro_thread_timeline_page_info: dict[str, CursorPageInfo] = field(default_factory=dict)
```

Import `CursorPageInfo`, `BroThreadPageResponse`, and `BroTimelineTurnPageResponse` from `newbro.runtime.models` or move page models to a shared module if imports would cycle.

- [ ] **Step 4: Convert Codex list item projection into helper**

Extract the existing Codex-thread-to-`BroThread` logic inside `sync_imported_codex_threads` into:

```python
    def _project_imported_codex_thread(
        self,
        *,
        persona: Persona,
        node_id: str,
        codex_thread: CodexThreadListItem,
    ) -> tuple[BroThread, AgentResumeHandle]:
        public_thread_id = self.codex_thread_public_id_aliases.get(
            _codex_thread_alias_key(persona.persona_id, codex_thread.thread_id)
        ) or _imported_bro_thread_id(persona.persona_id, codex_thread.thread_id)
        status = _codex_thread_status(codex_thread.status)
        thread_title = _title_from_codex_thread(codex_thread)
        thread_updated_at = _iso_from_epoch_seconds(codex_thread.updated_at or codex_thread.created_at)
        resume_handle = AgentResumeHandle(
            executor_id="codex",
            session_handle=codex_thread.thread_id,
            opaque={
                "cwd": codex_thread.cwd or "",
                "path": codex_thread.path or "",
                "cliVersion": codex_thread.cli_version or "",
                "title": thread_title,
                "listUpdatedAt": thread_updated_at or "",
            },
        )
        diagnostics = {
            **codex_thread.diagnostics,
            "codex_thread_id": codex_thread.thread_id,
            "codex_session_id": codex_thread.session_id,
            "codex_cwd": codex_thread.cwd,
            "codex_path": codex_thread.path,
            "codex_cli_version": codex_thread.cli_version,
            "codex_thread_source": codex_thread.source,
            "imported_from_codex_thread_list": True,
        }
        thread = BroThread(
            thread_id=public_thread_id,
            persona_id=persona.persona_id,
            persona_name=persona.name,
            executor_id="codex",
            executor_node_id=node_id,
            workspace_id=codex_thread.cwd,
            workspace_name=_workspace_name(codex_thread.cwd),
            execution_session_id=None,
            status=status,  # type: ignore[arg-type]
            title=thread_title,
            preview=codex_thread.preview,
            progress=_thread_progress(status),
            task_ids=[],
            active_task_id=None,
            latest_task_id=None,
            has_resume_handle=True,
            updated_at=thread_updated_at,
            diagnostics=diagnostics,
        )
        return thread, resume_handle
```

- [ ] **Step 5: Update `sync_imported_codex_threads`**

Change the call to `request_codex_threads`:

```python
                    page = await self.executor_node_manager.request_codex_threads(
                        node_id=node_id,
                        limit=IMPORTED_CODEX_THREAD_PAGE_LIMIT,
                        cursor=None,
                    )
                    codex_threads = page.threads
```

For each persona, fill `imported_codex_thread_pages_by_persona[persona.persona_id]` with the public thread ids projected from that first page. Set:

```python
self.imported_codex_thread_page_info[persona.persona_id] = CursorPageInfo(
    next_cursor=page.next_cursor,
    previous_cursor=page.previous_cursor,
    has_more=bool(page.next_cursor),
    status="loaded",
    error=None,
)
```

On failure, keep cached `imported_codex_threads` and set `status="failed"` with the error for every persona on that node.

- [ ] **Step 6: Add explicit thread page method**

Add to `BroDetailThreadProjection`:

```python
    async def list_bro_thread_page(
        self,
        *,
        persona: Persona,
        sessions: list[ExecutionSession],
        limit: int = IMPORTED_CODEX_THREAD_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> BroThreadPageResponse:
        if not persona.executor_node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        page = await self.executor_node_manager.request_codex_threads(
            node_id=persona.executor_node_id,
            limit=limit,
            cursor=cursor,
        )
        existing_codex_thread_ids = {
            session.latest_resume_handle.session_handle
            for session in sessions
            if session.latest_resume_handle is not None
            and session.latest_resume_handle.executor_id == "codex"
            and isinstance(session.latest_resume_handle.session_handle, str)
        }
        threads: list[BroThread] = []
        for codex_thread in page.threads:
            if codex_thread.thread_id in existing_codex_thread_ids or _is_ephemeral_codex_thread(codex_thread):
                continue
            thread, resume_handle = self._project_imported_codex_thread(
                persona=persona,
                node_id=persona.executor_node_id,
                codex_thread=codex_thread,
            )
            self.imported_codex_threads[thread.thread_id] = thread
            self.imported_codex_thread_resume_handles[thread.thread_id] = resume_handle
            threads.append(thread)
        info = CursorPageInfo(
            next_cursor=page.next_cursor,
            previous_cursor=page.previous_cursor,
            has_more=bool(page.next_cursor),
            status="loaded",
            error=None,
        )
        self.imported_codex_thread_page_info[persona.persona_id] = info
        return BroThreadPageResponse(persona_id=persona.persona_id, threads=self.with_timeline_state(threads), page=info)
```

- [ ] **Step 7: Add session wrappers and routes**

In `src/newbro/runtime/session.py`, add:

```python
    async def list_bro_thread_page(
        self,
        *,
        target_persona_id: str,
        limit: int = 25,
        cursor: str | None = None,
    ) -> BroThreadPageResponse:
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        return await self.bro_detail_threads.list_bro_thread_page(
            persona=persona,
            sessions=await self.blackboard.list_sessions(),
            limit=limit,
            cursor=cursor,
        )
```

In `src/newbro/api/routes/sessions.py`, add:

```python
@router.get("/sessions/{session_id}/bro-threads")
async def list_bro_thread_page(
    session_id: str,
    request: Request,
    target_persona_id: str,
    limit: int = 25,
    cursor: str | None = None,
):
    await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
        return await session.list_bro_thread_page(
            target_persona_id=target_persona_id,
            limit=limit,
            cursor=cursor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=_conflict_detail(exc, "Thread page could not be listed.")) from exc
```

- [ ] **Step 8: Include page info in snapshots**

In `snapshot_parts`, return page info through `BroDetailThreadProjectionSnapshot` or have `SessionRuntime.snapshot` copy:

```python
bro_thread_pages=dict(self.bro_detail_threads.imported_codex_thread_page_info)
```

Use `SessionSnapshot.bro_thread_pages` when constructing the snapshot.

- [ ] **Step 9: Run runtime tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_imported_codex_threads_snapshot_uses_first_page_only tests/unit/runtime/test_bro_detail_thread_projection.py::test_list_bro_thread_page_appends_cached_imported_threads tests/unit/runtime/test_session_runtime.py -q
```

Expected: pass.

- [ ] **Step 10: Commit**

```bash
git add src/newbro/runtime/bro_detail_thread_projection.py src/newbro/runtime/session.py src/newbro/api/routes/sessions.py tests/unit/runtime/test_bro_detail_thread_projection.py tests/unit/runtime/test_session_runtime.py
git commit -m "Page imported bro thread projections"
```

---

### Task 5: Add Runtime Selected Timeline Page Projection

**Files:**
- Modify: `src/newbro/runtime/bro_detail_thread_projection.py`
- Modify: `src/newbro/runtime/session.py`
- Modify: `src/newbro/api/routes/sessions.py`
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`
- Test: `tests/unit/runtime/test_codex_multi_message_turn.py`

- [ ] **Step 1: Write failing timeline page test**

Add to `tests/unit/runtime/test_bro_detail_thread_projection.py`:

```python
@pytest.mark.anyio
async def test_list_bro_timeline_page_uses_codex_turn_cursor(monkeypatch: pytest.MonkeyPatch):
    session, persona, projection, _publish_calls = await _projection_harness()
    projection.imported_codex_thread_resume_handles["codex-import-1"] = AgentResumeHandle(
        executor_id="codex",
        session_handle="native-thread-1",
    )

    async def fake_request_codex_thread_turns(**kwargs):
        assert kwargs["node_id"] == "node-forge"
        assert kwargs["thread_id"] == "native-thread-1"
        assert kwargs["limit"] == 100
        assert kwargs["cursor"] == "older"
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-old",
                    "status": "completed",
                    "items": [
                        {"type": "agentMessage", "id": "agent-old", "text": "Old answer", "phase": "final_answer"}
                    ],
                    "startedAt": 1780650000,
                    "completedAt": 1780650010,
                }
            ],
            next_cursor=None,
            previous_cursor="newer",
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    page = await projection.list_bro_timeline_page(
        persona=persona,
        public_thread_id="codex-import-1",
        node_id="node-forge",
        cursor="older",
        limit=100,
    )

    assert page.thread_id == "codex-import-1"
    assert [turn.executor_turn_id for turn in page.turns] == ["turn-old"]
    assert page.page.next_cursor is None
    assert page.page.previous_cursor == "newer"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_list_bro_timeline_page_uses_codex_turn_cursor -q
```

Expected: fail because `list_bro_timeline_page` does not exist.

- [ ] **Step 3: Add timeline page method**

In `src/newbro/runtime/bro_detail_thread_projection.py`, add:

```python
    async def list_bro_timeline_page(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        node_id: str,
        cursor: str | None = None,
        limit: int = SELECTED_CODEX_TURN_PAGE_LIMIT,
    ) -> BroTimelineTurnPageResponse:
        resume_handle = self.imported_codex_thread_resume_handles.get(public_thread_id)
        if resume_handle is None or resume_handle.executor_id != "codex" or not isinstance(resume_handle.session_handle, str):
            raise ValueError("Selected Codex thread is not available.")
        page = await self.executor_node_manager.request_codex_thread_turns(
            node_id=node_id,
            thread_id=resume_handle.session_handle,
            limit=limit,
            cursor=cursor,
        )
        turns = list(
            _timeline_turns_from_codex_thread(
                thread={"id": page.thread_id, "goal": page.goal, "turns": list(reversed(page.turns))},
                public_thread_id=public_thread_id,
                executor_thread_id=page.thread_id,
                persona_id=persona.persona_id,
                executor_id="codex",
            )
        )
        for turn in turns:
            self.upsert_bro_thread_executor_turn(turn)
        info = CursorPageInfo(
            next_cursor=page.next_cursor,
            previous_cursor=page.previous_cursor,
            has_more=bool(page.next_cursor),
            status="loaded",
            error=None,
        )
        self.bro_thread_timeline_page_info[public_thread_id] = info
        return BroTimelineTurnPageResponse(thread_id=public_thread_id, turns=turns, page=info)
```

- [ ] **Step 4: Use turn pages for initial timeline load**

In `_load_bro_thread_timeline_once`, replace `request_codex_thread` history hydration with:

```python
            page = await self.executor_node_manager.request_codex_thread_turns(
                node_id=node_id,
                thread_id=native_thread_id,
                limit=SELECTED_CODEX_TURN_PAGE_LIMIT,
                cursor=None,
            )
```

Set `bro_thread_goals` from `page.goal`. Build turns from `page.turns` as in Step 3. Set `bro_thread_timeline_page_info[public_thread_id]` from `page.next_cursor` and `page.previous_cursor`.

Keep `request_codex_thread` available for metadata/status if an existing flow requires it, but do not use `includeTurns=true`.

- [ ] **Step 5: Add session wrapper and route**

In `src/newbro/runtime/session.py`, add:

```python
    async def list_bro_timeline_page(
        self,
        *,
        target_persona_id: str,
        thread_id: str,
        limit: int = 100,
        cursor: str | None = None,
    ) -> BroTimelineTurnPageResponse:
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        node_id = persona.executor_node_id
        if not node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        return await self.bro_detail_threads.list_bro_timeline_page(
            persona=persona,
            public_thread_id=thread_id,
            node_id=node_id,
            limit=limit,
            cursor=cursor,
        )
```

In `src/newbro/api/routes/sessions.py`, add:

```python
@router.get("/sessions/{session_id}/bro-threads/{thread_id}/timeline")
async def list_bro_timeline_page(
    session_id: str,
    thread_id: str,
    request: Request,
    target_persona_id: str,
    limit: int = 100,
    cursor: str | None = None,
):
    await require_session_owner_or_internal(request, session_id)
    container = request.app.state.runtime_container
    try:
        session = container.get_session(session_id)
        return await session.list_bro_timeline_page(
            target_persona_id=target_persona_id,
            thread_id=thread_id,
            limit=limit,
            cursor=cursor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=_conflict_detail(exc, "Timeline page could not be listed.")) from exc
```

- [ ] **Step 6: Include timeline page info in snapshots**

When constructing `SessionSnapshot`, set:

```python
bro_timeline_pages=dict(self.bro_detail_threads.bro_thread_timeline_page_info)
```

- [ ] **Step 7: Run selected-thread contract tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_list_bro_timeline_page_uses_codex_turn_cursor tests/unit/runtime/test_codex_multi_message_turn.py tests/unit/runtime/test_session_runtime.py -q
```

Expected: pass, including multi-message turn replay.

- [ ] **Step 8: Commit**

```bash
git add src/newbro/runtime/bro_detail_thread_projection.py src/newbro/runtime/session.py src/newbro/api/routes/sessions.py tests/unit/runtime/test_bro_detail_thread_projection.py tests/unit/runtime/test_codex_multi_message_turn.py
git commit -m "Page selected codex timeline history"
```

---

### Task 6: Wire UI Page Endpoints

**Files:**
- Modify: `src/newbro/ui/src/types.ts`
- Modify: `src/newbro/ui/src/lib/session-client.ts`
- Modify: `src/newbro/ui/src/lib/session-client.test.ts`
- Modify: `src/newbro/ui/src/NewbroShell.tsx`
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Write failing client tests**

Add to `src/newbro/ui/src/lib/session-client.test.ts`:

```ts
it("lists a bro thread page with cursor params", async () => {
  const fetchMock = vi.fn(async () =>
    okJsonResponse({
      persona_id: "forge",
      threads: [],
      page: { next_cursor: "next", previous_cursor: null, has_more: true, status: "loaded", error: null },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  const client = await import("./session-client");
  await client.listBroThreadsPage("session-1", {
    targetPersonaId: "forge",
    cursor: "cursor-1",
    limit: 25,
  });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/sessions/session-1/bro-threads?target_persona_id=forge&limit=25&cursor=cursor-1",
  );
});

it("lists a bro timeline page with cursor params", async () => {
  const fetchMock = vi.fn(async () =>
    okJsonResponse({
      thread_id: "thread-1",
      turns: [],
      page: { next_cursor: null, previous_cursor: "newer", has_more: false, status: "loaded", error: null },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  const client = await import("./session-client");
  await client.listBroTimelinePage("session-1", {
    targetPersonaId: "forge",
    threadId: "thread-1",
    cursor: "older",
    limit: 100,
  });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/sessions/session-1/bro-threads/thread-1/timeline?target_persona_id=forge&limit=100&cursor=older",
  );
});
```

- [ ] **Step 2: Run client tests to verify failure**

Run:

```bash
cd src/newbro/ui && bun test src/lib/session-client.test.ts -t "lists a bro"
```

Expected: fail because the client functions do not exist.

- [ ] **Step 3: Add TypeScript page types**

In `src/newbro/ui/src/types.ts`, add:

```ts
export interface CursorPageInfo {
  next_cursor: string | null;
  previous_cursor: string | null;
  has_more: boolean;
  status: "not_loaded" | "loading" | "loaded" | "failed";
  error: string | null;
}

export interface BroThreadPageResponse {
  persona_id: string;
  threads: BroThread[];
  page: CursorPageInfo;
}

export interface BroTimelineTurnPageResponse {
  thread_id: string;
  turns: BroTimelineTurn[];
  page: CursorPageInfo;
}
```

Add to `SessionSnapshot`:

```ts
  bro_thread_pages?: Record<string, CursorPageInfo>;
  bro_timeline_pages?: Record<string, CursorPageInfo>;
```

- [ ] **Step 4: Add session client functions**

In `src/newbro/ui/src/lib/session-client.ts`, import the new response types and add:

```ts
export async function listBroThreadsPage(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    limit?: number;
    cursor?: string | null;
  },
): Promise<BroThreadPageResponse> {
  const params = new URLSearchParams();
  params.set("target_persona_id", payload.targetPersonaId);
  params.set("limit", String(payload.limit ?? 25));
  if (payload.cursor) params.set("cursor", payload.cursor);
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads?${params.toString()}`));
  return (await ensureOk(response)).json();
}

export async function listBroTimelinePage(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    threadId: string;
    limit?: number;
    cursor?: string | null;
  },
): Promise<BroTimelineTurnPageResponse> {
  const params = new URLSearchParams();
  params.set("target_persona_id", payload.targetPersonaId);
  params.set("limit", String(payload.limit ?? 100));
  if (payload.cursor) params.set("cursor", payload.cursor);
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads/${encodeURIComponent(payload.threadId)}/timeline?${params.toString()}`),
  );
  return (await ensureOk(response)).json();
}
```

- [ ] **Step 5: Update shell state**

In `src/newbro/ui/src/NewbroShell.tsx`, add state:

```ts
const [broThreadPages, setBroThreadPages] = useState<Record<string, CursorPageInfo>>({});
const [broTimelinePages, setBroTimelinePages] = useState<Record<string, CursorPageInfo>>({});
```

In `applySnapshot`:

```ts
setBroThreadPages(snapshot.bro_thread_pages ?? {});
setBroTimelinePages(snapshot.bro_timeline_pages ?? {});
```

Add functions:

```ts
const loadMoreBroThreads = useEffectEvent(async (targetPersonaId: string) => {
  if (!activeShellSessionId) return;
  const pageInfo = broThreadPages[targetPersonaId];
  if (!pageInfo?.next_cursor) return;
  const page = await listBroThreadsPage(activeShellSessionId, {
    targetPersonaId,
    cursor: pageInfo.next_cursor,
    limit: 25,
  });
  setBroThreads((current) => {
    const seen = new Set(current.map((thread) => thread.thread_id));
    return [...current, ...page.threads.filter((thread) => !seen.has(thread.thread_id))];
  });
  setBroThreadPages((current) => ({ ...current, [targetPersonaId]: page.page }));
});

const loadMoreBroTimeline = useEffectEvent(async (targetPersonaId: string, threadId: string) => {
  if (!activeShellSessionId) return;
  const pageInfo = broTimelinePages[threadId];
  if (!pageInfo?.next_cursor) return;
  const page = await listBroTimelinePage(activeShellSessionId, {
    targetPersonaId,
    threadId,
    cursor: pageInfo.next_cursor,
    limit: 100,
  });
  setBroTimelineTurns((current) => {
    const seen = new Set(current.map((turn) => turn.turn_id));
    return [...page.turns.filter((turn) => !seen.has(turn.turn_id)), ...current];
  });
  setBroTimelinePages((current) => ({ ...current, [threadId]: page.page }));
});
```

Expose `broThreadPages`, `broTimelinePages`, `loadMoreBroThreads`, and `loadMoreBroTimeline` from the shell context.

- [ ] **Step 6: Update desktop rail behavior**

In `src/newbro/ui/src/ArtboardShell.tsx`, keep local slicing only for non-runtime/static data. For runtime Bro detail, use page info:

```tsx
const broThreadPage = bro?.source === "runtime" ? shell.broThreadPages[bro.id] : null;
const hasMoreRuntimeThreads = Boolean(broThreadPage?.has_more && broThreadPage.next_cursor);
```

Pass `hasMore={hasMoreRuntimeThreads || hiddenThreadCount > 0}` to `DesktopActivityRail`, and change `DesktopActivityRail` props to accept `hasMore` and `showMoreLabel`.

Use:

```tsx
onShowMore={() => {
  if (bro.source === "runtime" && hasMoreRuntimeThreads) {
    void shell.loadMoreBroThreads(bro.id);
    return;
  }
  setThreadVisibleCount((count) => count + THREAD_LIST_PAGE_SIZE);
}}
```

- [ ] **Step 7: Add selected timeline load-older control**

In `ThreadPanel` props, add:

```ts
onLoadOlderTimeline?: () => void;
hasOlderTimeline?: boolean;
```

Render above timeline turns:

```tsx
{hasOlderTimeline ? (
  <button type="button" className="dt-thread-more" onClick={onLoadOlderTimeline}>
    <Layers size={12} strokeWidth={2.2} aria-hidden="true" />
    <span>Load older</span>
  </button>
) : null}
```

Pass from `BroDetailRuntimePage`:

```tsx
hasOlderTimeline={Boolean(activeThreadId && shell.broTimelinePages[activeThreadId]?.has_more)}
onLoadOlderTimeline={() => {
  if (activeThreadId) void shell.loadMoreBroTimeline(bro.id, activeThreadId);
}}
```

- [ ] **Step 8: Update UI tests**

In `src/newbro/ui/src/__tests__/App.test.tsx`, add the new client functions to the `vi.mock("../lib/session-client", ...)` object before using `clientMock`:

```ts
listBroThreadsPage: vi.fn(),
listBroTimelinePage: vi.fn(),
```

Then replace the local-only rail paging test with backend paging:

```ts
it("loads additional runtime thread pages from the backend", async () => {
  const snapshot = forgeSnapshot("session-existing");
  snapshot.bro_threads = Array.from({ length: 25 }, (_, index) => threadFixture(index + 1)) as any;
  (snapshot as any).bro_thread_pages = {
    forge: { next_cursor: "page-2", previous_cursor: null, has_more: true, status: "loaded", error: null },
  };
  clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
  clientMock.listBroThreadsPage.mockResolvedValueOnce({
    persona_id: "forge",
    threads: [threadFixture(26)],
    page: { next_cursor: null, previous_cursor: "page-1", has_more: false, status: "loaded", error: null },
  });
  window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

  render(<RouterProvider router={getRouter()} />);

  expect(await screen.findByText("Paged thread 25")).toBeInTheDocument();
  expect(screen.queryByText("Paged thread 26")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Show 25 more|Show more/ }));
  expect(await screen.findByText("Paged thread 26")).toBeInTheDocument();
  expect(clientMock.listBroThreadsPage).toHaveBeenCalledWith("session-existing", {
    targetPersonaId: "forge",
    cursor: "page-2",
    limit: 25,
  });
});
```

Define `threadFixture` near the test as:

```ts
function threadFixture(index: number) {
  const number = String(index).padStart(2, "0");
  return {
    thread_id: `thread-${number}`,
    persona_id: "forge",
    persona_name: "Forge",
    executor_id: "codex",
    executor_node_id: "node-forge",
    execution_session_id: null,
    status: "completed",
    title: `Paged thread ${number}`,
    preview: `History ${number}`,
    progress: 100,
    task_ids: [],
    active_task_id: null,
    latest_task_id: null,
    has_resume_handle: true,
    updated_at: `2026-05-26T20:${number}:00+00:00`,
    timeline_status: "not_loaded",
    timeline_error: null,
    diagnostics: { codex_thread_id: `codex-${number}` },
  };
}
```

Add a timeline load test that mocks `listBroTimelinePage` and asserts older turns render above current turns.

- [ ] **Step 9: Run UI tests**

Run:

```bash
cd src/newbro/ui && bun test src/lib/session-client.test.ts src/__tests__/App.test.tsx -t "bro thread page|bro timeline page|loads additional runtime thread pages|Load older"
```

Expected: pass.

- [ ] **Step 10: Commit**

```bash
git add src/newbro/ui/src/types.ts src/newbro/ui/src/lib/session-client.ts src/newbro/ui/src/lib/session-client.test.ts src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "Load bro detail pages from ui"
```

---

### Task 7: Update Stable Docs and Memory

**Files:**
- Modify: `docs/protocol/execution-session-and-run.md`
- Modify: `docs/architecture/executors.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Update protocol docs**

In `docs/protocol/execution-session-and-run.md`, replace the existing compatibility wording around imported threads with:

```markdown
Thread import requires `codex-cli >= 0.135.0` and uses Codex app-server `thread/list`
with `limit`, `cursor`, `sortKey = updated_at`, and `sortDirection = desc`.
Newbro snapshots expose only a bounded imported-thread page plus selected/open
threads; older imported threads are fetched through the Newbro Bro-thread page
API. Newbro does not retry old `thread/list` request shapes for unsupported
pagination.
```

Add selected-history text:

```markdown
Selected imported-thread history uses Codex `thread/turns/list` with `limit`,
`cursor`, `sortDirection = desc`, and `itemsView = full`. `thread/read` remains
the compact thread metadata/status path. UI clients fetch older selected-thread
turns through the Newbro timeline page API instead of expecting the full native
thread history in `SessionSnapshot.bro_timeline_turns`.
```

- [ ] **Step 2: Update architecture docs**

In `docs/architecture/executors.md`, add:

```markdown
Codex executor nodes are supported only with `codex-cli >= 0.135.0`. The node
advertises degraded availability when the detected Codex version is older.
Newbro treats Codex list and turn-history pagination as part of the executor
contract and preserves cursor-shaped data through backend APIs to the UI.
```

- [ ] **Step 3: Append memory note**

Append to `docs/memories.md`:

```markdown
- 2026-06-05: Newbro requires `codex-cli >= 0.135.0` for Codex executor nodes and preserves Codex cursor pagination for imported thread lists and selected-thread turn history instead of broadcasting unbounded Codex data in session snapshots.
```

- [ ] **Step 4: Commit docs**

```bash
git add docs/protocol/execution-session-and-run.md docs/architecture/executors.md docs/memories.md
git commit -m "Document paged codex data contract"
```

---

### Task 8: Full Verification

**Files:**
- No file edits expected.

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py tests/unit/runtime/test_executor_node_manager.py tests/unit/runtime/test_session_runtime.py tests/unit/runtime/test_codex_multi_message_turn.py tests/unit/executors/adapters/test_codex_executor.py tests/unit/executors/node/test_service.py tests/unit/cli/test_executor_probe.py -q
```

Expected: pass.

- [ ] **Step 2: Run frontend focused tests**

Run:

```bash
cd src/newbro/ui && bun test src/lib/session-client.test.ts src/__tests__/App.test.tsx src/lib/splitLiveSteps.test.ts
```

Expected: pass.

- [ ] **Step 3: Run full backend test suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: pass.

- [ ] **Step 4: Run UI lint/test command if available**

Run:

```bash
cd src/newbro/ui && bun test
```

Expected: pass.

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: `git status --short` is empty after the task commits, or only contains intentional uncommitted verification artifacts that should be removed before handoff.

---

## Self-Review

- Spec coverage: The plan covers `codex-cli >= 0.135.0`, `thread/list` paging, Newbro-side imported-thread page endpoints, bounded snapshots, selected-thread `thread/turns/list` paging, UI load-more behavior, failure visibility, tests, stable docs, and memory updates.
- Placeholder scan: No `TBD`, `TODO`, "implement later", or unspecified "add tests" steps remain.
- Type consistency: Cursor fields use snake_case in Python/API models (`next_cursor`, `previous_cursor`) and TypeScript interfaces mirror API JSON. Native Codex fields are mapped at adapter/service boundaries from `nextCursor`/`backwardsCursor` to Newbro snake_case.
