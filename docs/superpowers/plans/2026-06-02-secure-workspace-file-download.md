# Secure Workspace-File Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user click a file path the assistant wrote in a message and download that file from the executor node, gated so only in-message, in-workspace files are ever released.

**Architecture:** Two layered authorization gates — Gate 1 (backend, authoritative): the requested `path` must be an exact path-token in the referenced turn's stored assistant text; Gate 2 (node): the path must `realpath()` inside the workspace the node itself bound to that thread. Bytes stream from the node to the backend as base64 chunks over the existing `/executors/control` WebSocket (correlated by `request_id`, using a per-request `asyncio.Queue`), and the backend streams them to the browser as an `attachment`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Pytest (backend/node); React, Vite, TypeScript, react-markdown, Vitest (UI).

**Spec:** `docs/superpowers/specs/2026-06-02-secure-workspace-file-download-design.md`

---

## File Structure

**Create:**
- `src/newbro/api/workspace_path_tokens.py` — Gate-1 path-token grammar (Python). One responsibility: extract absolute-path tokens from message text.
- `tests/api/test_workspace_path_tokens.py`
- `src/newbro/executors/node/workspace_files.py` — Gate-2 containment + chunked read (pure, node-side). One responsibility: resolve a path safely inside a workspace and stream it.
- `tests/executors/node/test_workspace_files.py`
- `src/newbro/api/routes/workspace_files.py` — the turn-scoped download route (Gate 1 + streaming + error mapping).
- `tests/api/routes/test_workspace_files_route.py`
- `src/newbro/ui/src/lib/workspace-paths.ts` — path-token grammar (TS, mirrors the Python one).
- `src/newbro/ui/src/lib/workspace-paths.test.ts`
- `src/newbro/ui/src/components/ui/workspace-file-link.tsx` — the Download control + remark plugin.
- `src/newbro/ui/src/components/ui/workspace-file-link.test.tsx`

**Modify:**
- `src/newbro/protocol/executor_node.py` — 4 new message models.
- `src/newbro/protocol/__init__.py` — export them.
- `src/newbro/executors/node/service.py` — thread→workspace registry, `read_workspace_file` handler, dispatch.
- `src/newbro/runtime/executor_node_manager.py` — streaming correlation (`read_workspace_file` + publish handlers + exceptions).
- `src/newbro/api/ws/executors.py` — dispatch the 3 node→backend messages to the manager.
- `src/newbro/api/app.py` — register the new router.
- `src/newbro/ui/src/components/ui/markdown-text.tsx` — accept `downloadContext`, wire the remark plugin + `a` override.
- `src/newbro/ui/src/ArtboardShell.tsx` — pass `downloadContext` at the assistant-message render.

---

## Task 1: Path-token grammar (Python, Gate 1)

**Files:**
- Create: `src/newbro/api/workspace_path_tokens.py`
- Test: `tests/api/test_workspace_path_tokens.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_workspace_path_tokens.py
from newbro.api.workspace_path_tokens import extract_path_tokens


def test_extracts_absolute_path_with_trailing_sentence_punctuation():
    assert extract_path_tokens("saved to /work/out/report.pdf.") == {"/work/out/report.pdf"}


def test_strips_backticks_and_quotes_and_parens():
    assert extract_path_tokens("see `/work/a.txt`") == {"/work/a.txt"}
    assert extract_path_tokens('see "/work/a.txt"') == {"/work/a.txt"}
    assert extract_path_tokens("(see /work/a.txt)") == {"/work/a.txt"}


def test_ignores_relative_paths_and_prose():
    assert extract_path_tokens("out/report.pdf and hello world") == set()


def test_dedupes_and_keeps_distinct_tokens():
    assert extract_path_tokens("/a /a /b") == {"/a", "/b"}


def test_passwd_and_passwd_txt_are_distinct_tokens():
    tokens = extract_path_tokens("/etc/passwd.txt")
    assert "/etc/passwd" not in tokens
    assert tokens == {"/etc/passwd.txt"}


def test_handles_none_and_empty():
    assert extract_path_tokens(None) == set()
    assert extract_path_tokens("") == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_workspace_path_tokens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.api.workspace_path_tokens'`

- [ ] **Step 3: Write the implementation**

```python
# src/newbro/api/workspace_path_tokens.py
from __future__ import annotations

# Wrapping markdown/quote characters stripped from a token's leading edge.
_LEADING = "(<\"'`["
# Sentence punctuation / wrappers stripped from a token's trailing edge.
_TRAILING = ".,;:!?)]}>\"'`"


def extract_path_tokens(text: str | None) -> set[str]:
    """Absolute-path tokens present in ``text`` per the shared grammar.

    A token is a maximal whitespace-delimited run with wrapping
    markdown/quote/punctuation stripped from each edge, that is an absolute
    POSIX path (starts with ``/`` and contains no NUL). Relative paths and
    paths containing spaces are intentionally not detected (V1).
    """
    if not text:
        return set()
    tokens: set[str] = set()
    for raw in text.split():
        token = raw.lstrip(_LEADING).rstrip(_TRAILING)
        if not token or "\x00" in token:
            continue
        if not token.startswith("/"):
            continue
        tokens.add(token)
    return tokens
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_workspace_path_tokens.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/api/workspace_path_tokens.py tests/api/test_workspace_path_tokens.py
git commit -m "feat(api): workspace path-token grammar for download gate 1"
```

---

## Task 2: Protocol messages

**Files:**
- Modify: `src/newbro/protocol/executor_node.py`
- Modify: `src/newbro/protocol/__init__.py`
- Test: `tests/protocol/test_workspace_file_messages.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/protocol/test_workspace_file_messages.py
from newbro.protocol import (
    ReadWorkspaceFileCommand,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
)


def test_read_command_round_trip():
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="t1", path="/work/a.txt")
    assert cmd.type == "read_workspace_file"
    assert ReadWorkspaceFileCommand.model_validate(cmd.model_dump(mode="json")) == cmd


def test_chunk_eof_error_round_trip():
    chunk = WorkspaceFileChunk(request_id="r1", seq=0, data="QUJD")
    eof = WorkspaceFileEof(request_id="r1", total_bytes=3, sha256="abc")
    err = WorkspaceFileError(request_id="r1", code="denied", message="nope")
    assert chunk.type == "workspace_file_chunk"
    assert eof.type == "workspace_file_eof"
    assert err.type == "workspace_file_error"
    assert WorkspaceFileChunk.model_validate(chunk.model_dump(mode="json")) == chunk
    assert WorkspaceFileEof.model_validate(eof.model_dump(mode="json")) == eof
    assert WorkspaceFileError.model_validate(err.model_dump(mode="json")) == err


def test_error_code_is_constrained():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WorkspaceFileError(request_id="r1", code="bogus", message="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/protocol/test_workspace_file_messages.py -v`
Expected: FAIL with `ImportError: cannot import name 'ReadWorkspaceFileCommand'`

- [ ] **Step 3: Add the models**

Append to `src/newbro/protocol/executor_node.py` (end of file):

```python
class ReadWorkspaceFileCommand(BaseModel):
    type: Literal["read_workspace_file"] = "read_workspace_file"
    request_id: str
    thread_id: str
    path: str


class WorkspaceFileChunk(BaseModel):
    type: Literal["workspace_file_chunk"] = "workspace_file_chunk"
    request_id: str
    seq: int
    data: str  # base64-encoded bytes


class WorkspaceFileEof(BaseModel):
    type: Literal["workspace_file_eof"] = "workspace_file_eof"
    request_id: str
    total_bytes: int
    sha256: str | None = None


class WorkspaceFileError(BaseModel):
    type: Literal["workspace_file_error"] = "workspace_file_error"
    request_id: str
    code: Literal["denied", "not_found", "too_large", "read_error"]
    message: str
```

- [ ] **Step 4: Export the models**

In `src/newbro/protocol/__init__.py`, add to the `from .executor_node import (` block (keep alphabetical-ish with the neighbours):

```python
    ReadWorkspaceFileCommand,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
```

And add the same four names as string entries to the `__all__` list.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/protocol/test_workspace_file_messages.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/newbro/protocol/executor_node.py src/newbro/protocol/__init__.py tests/protocol/test_workspace_file_messages.py
git commit -m "feat(protocol): workspace file read command + chunk/eof/error messages"
```

---

## Task 3: Node-side containment + chunked read (Gate 2 core)

**Files:**
- Create: `src/newbro/executors/node/workspace_files.py`
- Test: `tests/executors/node/test_workspace_files.py`

This is the security core — test the ALLOW/DENY matrix exhaustively.

- [ ] **Step 1: Write the failing test**

```python
# tests/executors/node/test_workspace_files.py
import os
import pytest

from newbro.executors.node.workspace_files import (
    WorkspaceFileAccessError,
    iter_file_bytes,
    resolve_within_workspace,
)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "report.pdf").write_bytes(b"hello")
    (root / "sub" / "out.csv").write_bytes(b"a,b")
    return root


def test_allows_file_in_workspace(workspace):
    real = resolve_within_workspace(str(workspace / "report.pdf"), str(workspace))
    assert real == (workspace / "report.pdf").resolve()


def test_allows_nested_file(workspace):
    real = resolve_within_workspace(str(workspace / "sub" / "out.csv"), str(workspace))
    assert real.name == "out.csv"


def test_denies_absolute_outside(workspace):
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace("/etc/hosts", str(workspace))
    assert exc.value.code == "denied"


def test_denies_parent_traversal(workspace):
    outside = workspace.parent / "secret.txt"
    outside.write_text("x")
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(workspace / ".." / "secret.txt"), str(workspace))
    assert exc.value.code == "denied"


def test_denies_symlink_pointing_outside(workspace):
    target = workspace.parent / "outside.txt"
    target.write_text("secret")
    link = workspace / "link.txt"
    link.symlink_to(target)
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(link), str(workspace))
    assert exc.value.code == "denied"


def test_denies_directory(workspace):
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(workspace / "sub"), str(workspace))
    assert exc.value.code == "denied"


def test_not_found(workspace):
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(workspace / "missing.txt"), str(workspace))
    assert exc.value.code == "not_found"


def test_too_large(workspace):
    real = resolve_within_workspace(str(workspace / "report.pdf"), str(workspace))
    with pytest.raises(WorkspaceFileAccessError) as exc:
        list(iter_file_bytes(real, max_bytes=2))
    assert exc.value.code == "too_large"


def test_iter_file_bytes_yields_whole_file(workspace):
    real = resolve_within_workspace(str(workspace / "report.pdf"), str(workspace))
    assert b"".join(iter_file_bytes(real, chunk_bytes=2)) == b"hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/executors/node/test_workspace_files.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.executors.node.workspace_files'`

- [ ] **Step 3: Write the implementation**

```python
# src/newbro/executors/node/workspace_files.py
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB
CHUNK_BYTES = 256 * 1024  # 256 KB


class WorkspaceFileAccessError(Exception):
    """Raised when a workspace file cannot be released. ``code`` is one of
    'denied' | 'not_found' | 'too_large' | 'read_error'."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_within_workspace(path: str, workspace_root: str) -> Path:
    """Resolve ``path`` and assert it is a regular file inside ``workspace_root``.

    Symlinks are resolved before the containment check, so a symlink inside the
    workspace that points outside is denied. ``..`` traversal and absolute
    escapes are denied.
    """
    root = Path(os.path.realpath(workspace_root))
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    real = Path(os.path.realpath(candidate))

    if real != root and root not in real.parents:
        raise WorkspaceFileAccessError("denied", "path resolves outside the workspace")
    if not real.exists():
        raise WorkspaceFileAccessError("not_found", "file does not exist")
    if not real.is_file():
        raise WorkspaceFileAccessError("denied", "path is not a regular file")
    return real


def iter_file_bytes(
    real: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    chunk_bytes: int = CHUNK_BYTES,
) -> Iterator[bytes]:
    """Yield ``real`` in ``chunk_bytes`` blocks, raising 'too_large' if it
    exceeds ``max_bytes``."""
    size = real.stat().st_size
    if size > max_bytes:
        raise WorkspaceFileAccessError("too_large", f"file exceeds {max_bytes} bytes")
    try:
        with real.open("rb") as handle:
            while True:
                block = handle.read(chunk_bytes)
                if not block:
                    break
                yield block
    except OSError as exc:  # pragma: no cover - surfaced as read_error
        raise WorkspaceFileAccessError("read_error", str(exc)) from exc
```

Note: `iter_file_bytes` checks size *before* opening so `test_too_large` raises on the first `list(...)` pull.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/executors/node/test_workspace_files.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/node/workspace_files.py tests/executors/node/test_workspace_files.py
git commit -m "feat(node): workspace containment + chunked file read (download gate 2)"
```

---

## Task 4: Node service — thread→workspace registry + read handler

**Files:**
- Modify: `src/newbro/executors/node/service.py`
- Test: `tests/executors/node/test_service_read_workspace_file.py`

The node must know each thread's workspace from its *own* binding (never from the command). It learns the workspace when it subscribes a codex thread (which is exactly when the UI opens a thread to view its turns). We record `thread_id -> resolved workspace path` there, and the read handler looks it up.

- [ ] **Step 1: Read the existing subscribe handler to find the workspace + thread variables**

Run: `grep -n "_subscribe_codex_thread\|resolve_workspace\|command.workspace_id\|command.thread_id" src/newbro/executors/node/service.py`
You will wire the registry write inside `_subscribe_codex_thread`, using the same `resolve_workspace(command.workspace_id)` call already used to locate the workspace, keyed by `command.thread_id`.

- [ ] **Step 2: Write the failing test**

```python
# tests/executors/node/test_service_read_workspace_file.py
import base64
import json
import pytest

from newbro.executors.node.service import ExecutorNodeService
from newbro.protocol import ReadWorkspaceFileCommand


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, data):
        self.sent.append(json.loads(data))


def _make_service() -> ExecutorNodeService:
    # ExecutorNodeService construction mirrors existing node tests; if the
    # constructor needs config, reuse the helper used by the sibling node tests
    # in tests/executors/node/. Then ensure the thread->workspace registry exists.
    service = ExecutorNodeService.__new__(ExecutorNodeService)
    service._thread_workspaces = {}
    service._send_lock = __import__("asyncio").Lock()
    return service


@pytest.mark.asyncio
async def test_read_denies_when_no_workspace_binding():
    service = _make_service()
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="unknown", path="/x")
    await service._read_workspace_file(ws, cmd)
    assert ws.sent[-1]["type"] == "workspace_file_error"
    assert ws.sent[-1]["code"] == "denied"


@pytest.mark.asyncio
async def test_read_streams_chunks_then_eof(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello")
    service = _make_service()
    service._thread_workspaces["t1"] = str(root)
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="t1", path=str(root / "a.txt"))
    await service._read_workspace_file(ws, cmd)
    chunks = [m for m in ws.sent if m["type"] == "workspace_file_chunk"]
    eofs = [m for m in ws.sent if m["type"] == "workspace_file_eof"]
    assert b"".join(base64.b64decode(c["data"]) for c in chunks) == b"hello"
    assert eofs and eofs[-1]["total_bytes"] == 5


@pytest.mark.asyncio
async def test_read_denies_outside_workspace(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    service = _make_service()
    service._thread_workspaces["t1"] = str(root)
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="t1", path="/etc/hosts")
    await service._read_workspace_file(ws, cmd)
    assert ws.sent[-1]["type"] == "workspace_file_error"
    assert ws.sent[-1]["code"] == "denied"
```

If `ExecutorNodeService.__new__` + manual attribute setup does not match how sibling tests build the service, instead use the existing construction helper from the other files in `tests/executors/node/` and just set `service._thread_workspaces` before calling. The behavioural assertions stay the same.

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/executors/node/test_service_read_workspace_file.py -v`
Expected: FAIL with `AttributeError: 'ExecutorNodeService' object has no attribute '_read_workspace_file'`

- [ ] **Step 4: Add the registry, handler, and dispatch**

In `src/newbro/executors/node/service.py`:

(a) Add imports near the existing protocol/node imports:

```python
import base64
import hashlib

from newbro.executors.node.workspace_files import (
    WorkspaceFileAccessError,
    iter_file_bytes,
    resolve_within_workspace,
)
from newbro.protocol import (
    ReadWorkspaceFileCommand,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
)
```

(b) In `__init__`, alongside `self._live_sessions: dict[str, ExecutorSession] = {}`:

```python
        self._thread_workspaces: dict[str, str] = {}
```

(c) Inside `_subscribe_codex_thread`, right after the workspace path is resolved (the existing `resolve_workspace(command.workspace_id)` / `subscribe_thread(..., workspace_id=command.workspace_id)` lines), record the binding:

```python
        if command.workspace_id:
            self._thread_workspaces[command.thread_id] = str(resolve_workspace(command.workspace_id))
```

(d) Add the dispatch branch in `_handle_message`, mirroring `read_codex_thread`:

```python
        if message_type == "read_workspace_file":
            command = ReadWorkspaceFileCommand.model_validate(payload)
            self._schedule_background_command(self._read_workspace_file(websocket, command))
            return
```

(e) Add the handler method:

```python
    async def _read_workspace_file(
        self, websocket: Any, command: ReadWorkspaceFileCommand
    ) -> None:
        root = self._thread_workspaces.get(command.thread_id)
        if root is None:
            await self._send_json(
                websocket,
                WorkspaceFileError(
                    request_id=command.request_id,
                    code="denied",
                    message="no workspace binding for thread",
                ).model_dump(mode="json"),
            )
            return
        try:
            real = resolve_within_workspace(command.path, root)
        except WorkspaceFileAccessError as exc:
            await self._send_json(
                websocket,
                WorkspaceFileError(
                    request_id=command.request_id, code=exc.code, message=exc.message
                ).model_dump(mode="json"),
            )
            return

        digest = hashlib.sha256()
        seq = 0
        total = 0
        try:
            # iter_file_bytes does the size-cap check before the first yield, so a
            # too_large file errors before any chunk is sent.
            for block in iter_file_bytes(real):
                digest.update(block)
                total += len(block)
                await self._send_json(
                    websocket,
                    WorkspaceFileChunk(
                        request_id=command.request_id,
                        seq=seq,
                        data=base64.b64encode(block).decode("ascii"),
                    ).model_dump(mode="json"),
                )
                seq += 1
        except WorkspaceFileAccessError as exc:
            await self._send_json(
                websocket,
                WorkspaceFileError(
                    request_id=command.request_id, code=exc.code, message=exc.message
                ).model_dump(mode="json"),
            )
            return
        await self._send_json(
            websocket,
            WorkspaceFileEof(
                request_id=command.request_id,
                total_bytes=total,
                sha256=digest.hexdigest(),
            ).model_dump(mode="json"),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/executors/node/test_service_read_workspace_file.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/newbro/executors/node/service.py tests/executors/node/test_service_read_workspace_file.py
git commit -m "feat(node): thread->workspace registry + read_workspace_file streaming handler"
```

---

## Task 5: Node-manager streaming correlation

**Files:**
- Modify: `src/newbro/runtime/executor_node_manager.py`
- Test: `tests/runtime/test_executor_node_manager_workspace_file.py`

Single-response requests use a `Future`; a download is one request → many chunks, so use a per-`request_id` `asyncio.Queue` and expose an async iterator.

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime/test_executor_node_manager_workspace_file.py
import asyncio
import base64
import pytest

from newbro.protocol import (
    RegisterNodeMessage,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
)
from newbro.runtime.executor_node_manager import (
    ExecutorNodeManager,
    WorkspaceFileDenied,
    WorkspaceFileUnavailable,
)


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, data):  # matches whatever _send_json calls
        self.sent.append(data)


async def _register(manager) -> str:
    ws = _FakeWS()
    await manager.register_connection(ws, RegisterNodeMessage(node_id="node-1", token="t"))
    return "node-1"


@pytest.mark.asyncio
async def test_streams_chunks_until_eof():
    manager = ExecutorNodeManager()
    node_id = await _register(manager)

    async def feed():
        await asyncio.sleep(0.01)
        # find the request_id the manager allocated
        request_id = next(iter(manager._workspace_file_streams))
        manager.publish_workspace_file_chunk(
            WorkspaceFileChunk(request_id=request_id, seq=0, data=base64.b64encode(b"he").decode())
        )
        manager.publish_workspace_file_chunk(
            WorkspaceFileChunk(request_id=request_id, seq=1, data=base64.b64encode(b"llo").decode())
        )
        manager.publish_workspace_file_eof(
            WorkspaceFileEof(request_id=request_id, total_bytes=5)
        )

    asyncio.create_task(feed())
    out = b""
    async for chunk in manager.read_workspace_file(node_id=node_id, thread_id="t1", path="/x"):
        out += chunk
    assert out == b"hello"


@pytest.mark.asyncio
async def test_error_raises_denied():
    manager = ExecutorNodeManager()
    node_id = await _register(manager)

    async def feed():
        await asyncio.sleep(0.01)
        request_id = next(iter(manager._workspace_file_streams))
        manager.publish_workspace_file_error(
            WorkspaceFileError(request_id=request_id, code="denied", message="nope")
        )

    asyncio.create_task(feed())
    with pytest.raises(WorkspaceFileDenied) as exc:
        async for _ in manager.read_workspace_file(node_id=node_id, thread_id="t1", path="/x"):
            pass
    assert exc.value.code == "denied"


@pytest.mark.asyncio
async def test_offline_node_raises_unavailable():
    manager = ExecutorNodeManager()
    with pytest.raises(WorkspaceFileUnavailable):
        async for _ in manager.read_workspace_file(node_id="ghost", thread_id="t1", path="/x"):
            pass
```

Note: match `_FakeWS` to however `_send_json` sends (e.g. `send_json`/`send_text`). Check with `grep -n "_send_json" src/newbro/runtime/executor_node_manager.py` and mirror the sibling manager tests' fake websocket.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime/test_executor_node_manager_workspace_file.py -v`
Expected: FAIL with `ImportError: cannot import name 'WorkspaceFileDenied'`

- [ ] **Step 3: Implement streaming correlation**

In `src/newbro/runtime/executor_node_manager.py`:

(a) Add imports / module constants near the top:

```python
import base64
from collections.abc import AsyncIterator

from newbro.protocol import (
    ReadWorkspaceFileCommand,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
)
```

(b) Add exception types near `ExecutorNodeAuthError`:

```python
class WorkspaceFileUnavailable(Exception):
    """The node is offline / unreachable / timed out."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkspaceFileDenied(Exception):
    """The node refused the file (denied / not_found / too_large / read_error)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

(c) In `__init__`, alongside the other request dicts:

```python
        self._workspace_file_streams: dict[
            str, asyncio.Queue[WorkspaceFileChunk | WorkspaceFileEof | WorkspaceFileError]
        ] = {}
```

(d) Add the streaming method and publish handlers:

```python
    async def read_workspace_file(
        self,
        *,
        node_id: str,
        thread_id: str,
        path: str,
        timeout: float = 30.0,
    ) -> AsyncIterator[bytes]:
        connection = self._connections_by_node.get(node_id)
        if connection is None:
            raise WorkspaceFileUnavailable("node_offline", "executor node not connected")
        request_id = f"workspace-file-{uuid4().hex[:12]}"
        queue: asyncio.Queue = asyncio.Queue()
        self._workspace_file_streams[request_id] = queue
        command = ReadWorkspaceFileCommand(
            request_id=request_id, thread_id=thread_id, path=path
        )
        try:
            await self._send_json(connection, command.model_dump(mode="json"))
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError as exc:
                    raise WorkspaceFileUnavailable("node_offline", "timed out") from exc
                if isinstance(message, WorkspaceFileChunk):
                    yield base64.b64decode(message.data)
                elif isinstance(message, WorkspaceFileEof):
                    return
                else:  # WorkspaceFileError
                    raise WorkspaceFileDenied(message.code, message.message)
        finally:
            self._workspace_file_streams.pop(request_id, None)

    def publish_workspace_file_chunk(self, message: WorkspaceFileChunk) -> AckMessage:
        return self._publish_workspace_file(message)

    def publish_workspace_file_eof(self, message: WorkspaceFileEof) -> AckMessage:
        return self._publish_workspace_file(message)

    def publish_workspace_file_error(self, message: WorkspaceFileError) -> AckMessage:
        return self._publish_workspace_file(message)

    def _publish_workspace_file(self, message) -> AckMessage:
        queue = self._workspace_file_streams.get(message.request_id)
        if queue is None:
            return AckMessage(message_type=message.type, ok=False, detail="unknown_request")
        queue.put_nowait(message)
        return AckMessage(message_type=message.type, detail="ok")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime/test_executor_node_manager_workspace_file.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/runtime/executor_node_manager.py tests/runtime/test_executor_node_manager_workspace_file.py
git commit -m "feat(runtime): stream workspace file chunks from node by request_id"
```

---

## Task 6: WebSocket dispatch for node→backend file messages

**Files:**
- Modify: `src/newbro/api/ws/executors.py`
- Test: `tests/api/ws/test_executors_workspace_file_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/ws/test_executors_workspace_file_dispatch.py
import pytest

from newbro.api.ws.executors import _handle_control_message
from newbro.protocol import WorkspaceFileChunk


class _Manager:
    def __init__(self):
        self.calls = []

    def publish_workspace_file_chunk(self, message):
        self.calls.append(message)
        from newbro.protocol import AckMessage

        return AckMessage(message_type=message.type, detail="ok")


class _Container:
    def __init__(self):
        self.executor_node_manager = _Manager()


@pytest.mark.asyncio
async def test_chunk_routed_to_manager():
    container = _Container()
    payload = WorkspaceFileChunk(request_id="r1", seq=0, data="QQ==").model_dump(mode="json")
    ack = await _handle_control_message(container, websocket=None, payload=payload)
    assert ack.ok
    assert container.executor_node_manager.calls[0].request_id == "r1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/ws/test_executors_workspace_file_dispatch.py -v`
Expected: FAIL — ack is `unknown_message_type` (not ok), so `assert ack.ok` fails.

- [ ] **Step 3: Add dispatch branches**

In `src/newbro/api/ws/executors.py`, add `WorkspaceFileChunk, WorkspaceFileEof, WorkspaceFileError` to the `from newbro.protocol import (...)` block, then add these branches in `_handle_control_message` before the final `return AckMessage(... "unknown_message_type")`:

```python
    if message_type == "workspace_file_chunk":
        try:
            message = WorkspaceFileChunk.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="workspace_file_chunk", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_workspace_file_chunk(message)
    if message_type == "workspace_file_eof":
        try:
            message = WorkspaceFileEof.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="workspace_file_eof", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_workspace_file_eof(message)
    if message_type == "workspace_file_error":
        try:
            message = WorkspaceFileError.model_validate(payload)
        except ValidationError:
            return AckMessage(message_type="workspace_file_error", ok=False, detail="invalid_payload")
        return container.executor_node_manager.publish_workspace_file_error(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/ws/test_executors_workspace_file_dispatch.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/api/ws/executors.py tests/api/ws/test_executors_workspace_file_dispatch.py
git commit -m "feat(api): route node workspace-file chunk/eof/error to the node manager"
```

---

## Task 7: Backend download route (Gate 1 + streaming + error mapping)

**Files:**
- Create: `src/newbro/api/routes/workspace_files.py`
- Modify: `src/newbro/api/app.py`
- Test: `tests/api/routes/test_workspace_files_route.py`

- [ ] **Step 1: Confirm how the route gets a session and its turns**

Run: `grep -n "def get_session\|async def snapshot\|bro_timeline_turns\|bro_threads" src/newbro/runtime/session.py | head`
The route uses `container.get_session(session_id)` then `await session.snapshot()`, reading `.bro_timeline_turns` (each has `turn_id`, `thread_id`, `assistant.text`) and `.bro_threads` (each has `thread_id`, `executor_node_id`).

- [ ] **Step 2: Write the failing test**

```python
# tests/api/routes/test_workspace_files_route.py
import base64
import pytest
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import newbro.api.routes.workspace_files as wf
from newbro.api.paths import API_PREFIX


class _Session:
    async def snapshot(self):
        turn = SimpleNamespace(
            turn_id="turn-1",
            thread_id="t1",
            assistant=SimpleNamespace(text="saved to /work/report.pdf"),
        )
        thread = SimpleNamespace(thread_id="t1", executor_node_id="node-1")
        return SimpleNamespace(bro_timeline_turns=[turn], bro_threads=[thread])


class _Manager:
    async def read_workspace_file(self, *, node_id, thread_id, path):
        for block in (b"hel", b"lo"):
            yield block
    node_id = "node-1"


class _Container:
    def get_session(self, session_id):
        if session_id != "s1":
            raise KeyError(session_id)
        return _Session()
    executor_node_manager = _Manager()


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.state.runtime_container = _Container()
    # bypass auth in the unit test
    async def _ok(request, session_id):
        return SimpleNamespace(user_id="u1")
    monkeypatch.setattr(wf, "require_session_owner", _ok)
    app.include_router(wf.router, prefix=API_PREFIX)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_downloads_in_message_in_workspace_file(client):
    async with client as c:
        resp = await c.get(f"{API_PREFIX}/sessions/s1/bro-threads/t1/turns/turn-1/file", params={"path": "/work/report.pdf"})
    assert resp.status_code == 200
    assert resp.content == b"hello"
    assert "attachment" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_path_not_in_turn_is_forbidden(client):
    async with client as c:
        resp = await c.get(f"{API_PREFIX}/sessions/s1/bro-threads/t1/turns/turn-1/file", params={"path": "/etc/passwd"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unknown_turn_is_404(client):
    async with client as c:
        resp = await c.get(f"{API_PREFIX}/sessions/s1/bro-threads/t1/turns/nope/file", params={"path": "/work/report.pdf"})
    assert resp.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/routes/test_workspace_files_route.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.api.routes.workspace_files'`

- [ ] **Step 4: Write the route**

```python
# src/newbro/api/routes/workspace_files.py
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from newbro.api.public_auth import require_session_owner
from newbro.api.workspace_path_tokens import extract_path_tokens
from newbro.runtime.executor_node_manager import (
    WorkspaceFileDenied,
    WorkspaceFileUnavailable,
)

router = APIRouter()

_CODE_TO_STATUS = {"denied": 403, "not_found": 404, "too_large": 413, "read_error": 502}


def _safe_filename(path: str) -> str:
    name = os.path.basename(path) or "download"
    return name.replace('"', "").replace("\n", "").replace("\r", "")


@router.get("/sessions/{session_id}/bro-threads/{thread_id}/turns/{turn_id}/file")
async def download_workspace_file(
    session_id: str,
    thread_id: str,
    turn_id: str,
    request: Request,
    path: str = Query(...),
) -> StreamingResponse:
    await require_session_owner(request, session_id)
    container = request.app.state.runtime_container

    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown_session") from exc

    snapshot = await session.snapshot()
    turn = next(
        (t for t in snapshot.bro_timeline_turns if t.turn_id == turn_id and t.thread_id == thread_id),
        None,
    )
    if turn is None:
        raise HTTPException(status_code=404, detail="unknown_turn")

    assistant_text = turn.assistant.text if turn.assistant else None
    if path not in extract_path_tokens(assistant_text):
        # Gate 1: the path must be a token the assistant wrote in this turn.
        raise HTTPException(status_code=403, detail="path_not_in_turn")

    thread = next((th for th in snapshot.bro_threads if th.thread_id == thread_id), None)
    node_id = getattr(thread, "executor_node_id", None) if thread else None
    if node_id is None:
        node_id = container.executor_node_manager.node_id
    if node_id is None:
        raise HTTPException(status_code=504, detail="node_offline")

    agen = container.executor_node_manager.read_workspace_file(
        node_id=node_id, thread_id=thread_id, path=path
    )
    # Pull the first item so Gate-2 failures map to an HTTP status *before* the
    # response body (and its 200 + headers) is committed.
    try:
        first = await agen.__anext__()
    except StopAsyncIteration:
        first = b""  # empty file: node sent eof with no chunks
    except WorkspaceFileDenied as exc:
        await agen.aclose()
        raise HTTPException(status_code=_CODE_TO_STATUS.get(exc.code, 502), detail=exc.code) from exc
    except WorkspaceFileUnavailable as exc:
        await agen.aclose()
        raise HTTPException(status_code=504, detail=exc.code) from exc

    async def body():
        yield first
        async for chunk in agen:
            yield chunk

    return StreamingResponse(
        body(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_safe_filename(path)}"'},
    )
```

- [ ] **Step 5: Register the router**

In `src/newbro/api/app.py`, mirror the existing `app.include_router(health_router, prefix=API_PREFIX)` lines:

```python
from newbro.api.routes.workspace_files import router as workspace_files_router
...
    app.include_router(workspace_files_router, prefix=API_PREFIX)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/routes/test_workspace_files_route.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add src/newbro/api/routes/workspace_files.py src/newbro/api/app.py tests/api/routes/test_workspace_files_route.py
git commit -m "feat(api): turn-scoped workspace file download endpoint (gate 1 + stream)"
```

---

## Task 8: UI path-token grammar (mirror of Task 1)

**Files:**
- Create: `src/newbro/ui/src/lib/workspace-paths.ts`
- Test: `src/newbro/ui/src/lib/workspace-paths.test.ts`

Run UI commands from `src/newbro/ui`.

- [ ] **Step 1: Write the failing test**

```ts
// src/newbro/ui/src/lib/workspace-paths.test.ts
import { describe, it, expect } from "vitest";
import { extractPathTokens, isUnderWorkspace, basename } from "./workspace-paths";

describe("extractPathTokens", () => {
  it("extracts an absolute path with trailing punctuation", () => {
    expect(extractPathTokens("saved to /work/out/report.pdf.")).toEqual(["/work/out/report.pdf"]);
  });
  it("strips backticks, quotes, and parens", () => {
    expect(extractPathTokens("see `/work/a.txt`")).toEqual(["/work/a.txt"]);
    expect(extractPathTokens('see "/work/a.txt"')).toEqual(["/work/a.txt"]);
    expect(extractPathTokens("(see /work/a.txt)")).toEqual(["/work/a.txt"]);
  });
  it("ignores relative paths and prose", () => {
    expect(extractPathTokens("out/report.pdf and hello world")).toEqual([]);
  });
  it("dedupes", () => {
    expect(extractPathTokens("/a /a /b")).toEqual(["/a", "/b"]);
  });
  it("keeps passwd and passwd.txt distinct", () => {
    expect(extractPathTokens("/etc/passwd.txt")).toEqual(["/etc/passwd.txt"]);
  });
});

describe("isUnderWorkspace", () => {
  it("matches inside the root, rejects outside", () => {
    expect(isUnderWorkspace("/work/a.txt", "/work")).toBe(true);
    expect(isUnderWorkspace("/work", "/work")).toBe(true);
    expect(isUnderWorkspace("/works/a.txt", "/work")).toBe(false);
    expect(isUnderWorkspace("/etc/passwd", "/work")).toBe(false);
  });
});

describe("basename", () => {
  it("returns the last segment", () => {
    expect(basename("/work/out/report.pdf")).toBe("report.pdf");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/workspace-paths.test.ts`
Expected: FAIL — cannot find module `./workspace-paths`.

- [ ] **Step 3: Write the implementation**

```ts
// src/newbro/ui/src/lib/workspace-paths.ts
const LEADING = /^[(<"'`[]+/;
const TRAILING = /[.,;:!?)\]}>"'`]+$/;

/** Absolute-path tokens in `text`, mirroring the backend grammar. */
export function extractPathTokens(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/\s+/)) {
    const token = raw.replace(LEADING, "").replace(TRAILING, "");
    if (!token || token.includes("\0") || !token.startsWith("/")) continue;
    if (!seen.has(token)) {
      seen.add(token);
      out.push(token);
    }
  }
  return out;
}

export function isUnderWorkspace(path: string, root: string): boolean {
  const r = root.replace(/\/+$/, "");
  return path === r || path.startsWith(`${r}/`);
}

export function basename(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/workspace-paths.test.ts`
Expected: PASS (3 files? no — 1 file, 7 tests passed)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/lib/workspace-paths.ts src/newbro/ui/src/lib/workspace-paths.test.ts
git commit -m "feat(ui): workspace path-token grammar (mirror of backend gate 1)"
```

---

## Task 9: UI Download control + remark plugin

**Files:**
- Create: `src/newbro/ui/src/components/ui/workspace-file-link.tsx`
- Test: `src/newbro/ui/src/components/ui/workspace-file-link.test.tsx`

The remark plugin rewrites in-workspace absolute-path text into `link` nodes with a `newbro-download:` scheme; the `a` override (Task 10) renders `WorkspaceFileLink` for that scheme. Clicking fetches with credentials and triggers a browser download, surfacing inline error state.

- [ ] **Step 1: Write the failing test**

```tsx
// src/newbro/ui/src/components/ui/workspace-file-link.test.tsx
import { describe, it, expect } from "vitest";
import { remark } from "remark";
import { remarkWorkspacePaths, DOWNLOAD_SCHEME } from "./workspace-file-link";

function transform(md: string, workspaceRoot: string): string {
  const tree = remark().use(remarkWorkspacePaths, { workspaceRoot }).parse(md);
  remark().use(remarkWorkspacePaths, { workspaceRoot }).runSync(tree);
  return JSON.stringify(tree);
}

describe("remarkWorkspacePaths", () => {
  it("wraps an in-workspace path in a download link node", () => {
    const json = transform("saved to /work/report.pdf here", "/work");
    expect(json).toContain(`${DOWNLOAD_SCHEME}/work/report.pdf`);
  });
  it("leaves out-of-workspace paths untouched", () => {
    const json = transform("see /etc/passwd now", "/work");
    expect(json).not.toContain(DOWNLOAD_SCHEME);
  });
});
```

If `remark` is not already a dependency, add it as a devDependency for the test only (it is the canonical way to exercise a remark plugin). Check first: `grep -n '"remark"' package.json`. `remark-gfm` is already present, so the remark ecosystem is available; if `remark` itself is missing run `npm i -D remark`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/ui/workspace-file-link.test.tsx`
Expected: FAIL — cannot find module `./workspace-file-link`.

- [ ] **Step 3: Write the plugin + control**

```tsx
// src/newbro/ui/src/components/ui/workspace-file-link.tsx
import { useState } from "react";
import { extractPathTokens, isUnderWorkspace, basename } from "../../lib/workspace-paths";

export const DOWNLOAD_SCHEME = "newbro-download:";

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

/** Remark plugin: split text nodes on in-workspace absolute paths and turn
 *  each into a link node with the newbro-download: scheme. */
export function remarkWorkspacePaths({ workspaceRoot }: { workspaceRoot: string }) {
  return (tree: MdNode) => {
    walk(tree, workspaceRoot);
  };
}

function walk(node: MdNode, root: string): void {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value) {
      next.push(...splitText(child.value, root));
    } else {
      if (child.type !== "link") walk(child, root); // don't descend into existing links
      next.push(child);
    }
  }
  node.children = next;
}

function splitText(value: string, root: string): MdNode[] {
  const tokens = extractPathTokens(value).filter((t) => isUnderWorkspace(t, root));
  if (tokens.length === 0) return [{ type: "text", value }];
  const out: MdNode[] = [];
  let rest = value;
  // Process longest tokens first so a token that is a prefix of another wins on
  // an equal-position tie.
  const ordered = [...tokens].sort((a, b) => b.length - a.length);
  // Repeatedly find the earliest token occurrence, emitting text + link nodes.
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let bestIdx = -1;
    let bestTok = "";
    for (const tok of ordered) {
      const i = rest.indexOf(tok);
      if (i !== -1 && (bestIdx === -1 || i < bestIdx)) {
        bestIdx = i;
        bestTok = tok;
      }
    }
    if (bestIdx === -1) {
      if (rest) out.push({ type: "text", value: rest });
      break;
    }
    if (bestIdx > 0) out.push({ type: "text", value: rest.slice(0, bestIdx) });
    out.push({
      type: "link",
      url: `${DOWNLOAD_SCHEME}${bestTok}`,
      children: [{ type: "text", value: bestTok }],
    });
    rest = rest.slice(bestIdx + bestTok.length);
  }
  return out;
}

/** The clickable Download control rendered for newbro-download: links. */
export function WorkspaceFileLink({
  path,
  downloadUrl,
}: {
  path: string;
  downloadUrl: (path: string) => string;
}) {
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const name = basename(path);

  async function onClick(event: React.MouseEvent) {
    event.preventDefault();
    if (state === "loading") return;
    setState("loading");
    try {
      const response = await fetch(downloadUrl(path), { credentials: "include" });
      if (!response.ok) {
        setState("error");
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <a
      href={downloadUrl(path)}
      onClick={onClick}
      className="break-words text-primary underline decoration-primary/35 underline-offset-2"
      data-testid="workspace-file-download"
    >
      ↓ {name}
      {state === "loading" ? " …" : ""}
      {state === "error" ? " (download failed)" : ""}
    </a>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/ui/workspace-file-link.test.tsx`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/components/ui/workspace-file-link.tsx src/newbro/ui/src/components/ui/workspace-file-link.test.tsx
git commit -m "feat(ui): remark plugin + download control for in-workspace file paths"
```

---

## Task 10: Wire the control into MarkdownText + assistant renders

**Files:**
- Modify: `src/newbro/ui/src/components/ui/markdown-text.tsx`
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/components/ui/markdown-text.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/newbro/ui/src/components/ui/markdown-text.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarkdownText } from "./markdown-text";

describe("MarkdownText download control", () => {
  const ctx = {
    sessionId: "s1",
    threadId: "t1",
    turnId: "turn-1",
    workspaceRoot: "/work",
  };

  it("renders a download control for an in-workspace path", () => {
    render(<MarkdownText downloadContext={ctx}>{"saved to /work/report.pdf"}</MarkdownText>);
    const link = screen.getByTestId("workspace-file-download");
    expect(link).toHaveTextContent("report.pdf");
    expect(link.getAttribute("href")).toContain("/sessions/s1/bro-threads/t1/turns/turn-1/file");
    expect(link.getAttribute("href")).toContain("path=%2Fwork%2Freport.pdf");
  });

  it("leaves out-of-workspace paths as plain text", () => {
    render(<MarkdownText downloadContext={ctx}>{"see /etc/passwd"}</MarkdownText>);
    expect(screen.queryByTestId("workspace-file-download")).toBeNull();
  });

  it("renders plain text when no downloadContext is provided", () => {
    render(<MarkdownText>{"saved to /work/report.pdf"}</MarkdownText>);
    expect(screen.queryByTestId("workspace-file-download")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/ui/markdown-text.test.tsx`
Expected: FAIL — `MarkdownText` does not accept `downloadContext`; no control rendered.

- [ ] **Step 3: Extend MarkdownText**

Replace `src/newbro/ui/src/components/ui/markdown-text.tsx` with the version below (adds an optional `downloadContext`; when present, registers the remark plugin and an `a` override that renders `WorkspaceFileLink` for `newbro-download:` links). The existing `markdownComponents` object is kept; only the `a` renderer becomes context-aware and the plugin list becomes dynamic.

```tsx
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "../../lib/utils";
import { API_PREFIX } from "../../lib/session-client";
import { buildHttpUrl } from "../../lib/session-client";
import {
  DOWNLOAD_SCHEME,
  WorkspaceFileLink,
  remarkWorkspacePaths,
} from "./workspace-file-link";

export interface MarkdownDownloadContext {
  sessionId: string;
  threadId: string;
  turnId: string;
  workspaceRoot: string;
}

function baseComponents(downloadUrl: ((path: string) => string) | null): Components {
  return {
    a({ node, href, children, ...props }) {
      if (downloadUrl && typeof href === "string" && href.startsWith(DOWNLOAD_SCHEME)) {
        const path = href.slice(DOWNLOAD_SCHEME.length);
        return <WorkspaceFileLink path={path} downloadUrl={downloadUrl} />;
      }
      return (
        <a
          {...props}
          href={href}
          className={cn(
            "break-words text-primary underline decoration-primary/35 underline-offset-2",
            (props as { className?: string }).className,
          )}
          rel="noreferrer"
          target="_blank"
        >
          {children}
        </a>
      );
    },
    code: ({ node, ...props }) => (
      <code
        {...props}
        className={cn(
          "rounded bg-muted/75 px-1 py-0.5 font-mono text-[0.92em] text-foreground break-words",
          props.className,
        )}
      />
    ),
    pre: ({ node, ...props }) => (
      <pre
        {...props}
        className={cn(
          "my-2 max-w-full overflow-x-auto rounded-md bg-muted/75 p-2 font-mono text-[11px] leading-5 text-foreground",
          props.className,
        )}
      />
    ),
    p: ({ node, ...props }) => <p {...props} className={cn("my-2 break-words", props.className)} />,
    ul: ({ node, ...props }) => (
      <ul {...props} className={cn("my-2 list-disc space-y-1 pl-5", props.className)} />
    ),
    ol: ({ node, ...props }) => (
      <ol {...props} className={cn("my-2 list-decimal space-y-1 pl-5", props.className)} />
    ),
    li: ({ node, ...props }) => <li {...props} className={cn("pl-0.5", props.className)} />,
    blockquote: ({ node, ...props }) => (
      <blockquote
        {...props}
        className={cn("my-2 border-l-2 border-border pl-3 text-muted-foreground", props.className)}
      />
    ),
    table: ({ node, ...props }) => (
      <table
        {...props}
        className={cn("my-2 block max-w-full overflow-x-auto border-collapse text-left text-[0.95em]", props.className)}
      />
    ),
    th: ({ node, ...props }) => (
      <th {...props} className={cn("border border-border px-2 py-1 font-medium", props.className)} />
    ),
    td: ({ node, ...props }) => (
      <td {...props} className={cn("border border-border px-2 py-1 align-top", props.className)} />
    ),
  };
}

export function MarkdownText({
  children,
  className,
  downloadContext,
}: {
  children: string;
  className?: string;
  downloadContext?: MarkdownDownloadContext;
}) {
  const downloadUrl = downloadContext
    ? (path: string) =>
        buildHttpUrl(
          `${API_PREFIX}/sessions/${downloadContext.sessionId}/bro-threads/${encodeURIComponent(
            downloadContext.threadId,
          )}/turns/${encodeURIComponent(downloadContext.turnId)}/file?path=${encodeURIComponent(path)}`,
        )
    : null;

  const remarkPlugins = downloadContext
    ? [remarkGfm, [remarkWorkspacePaths, { workspaceRoot: downloadContext.workspaceRoot }] as const]
    : [remarkGfm];

  return (
    <div className={cn("min-w-0 max-w-full overflow-hidden [&>:first-child]:mt-0 [&>:last-child]:mb-0", className)}>
      <ReactMarkdown
        disallowedElements={["img"]}
        remarkPlugins={remarkPlugins}
        components={baseComponents(downloadUrl)}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
```

Note: this requires `buildHttpUrl` and `API_PREFIX` to be exported from `src/newbro/ui/src/lib/session-client.ts`. `buildHttpUrl` is currently a module-private `function buildHttpUrl(...)` — add `export` to it. `API_PREFIX` is already imported there from `./api-paths` (confirm with `grep -n "API_PREFIX" src/newbro/ui/src/lib/session-client.ts`); re-export it: `export { API_PREFIX } from "./api-paths";` or add `API_PREFIX` to an existing export. Make the smallest change that exposes both.

- [ ] **Step 4: Run the MarkdownText test**

Run: `npx vitest run src/components/ui/markdown-text.test.tsx`
Expected: PASS (3 passed)

- [ ] **Step 5: Pass downloadContext at the assistant render in ArtboardShell**

Find the assistant-message render that has a timeline turn in scope (the turn's `assistant.text` rendered via `MarkdownText`). Run:
`grep -n "MarkdownText" src/newbro/ui/src/ArtboardShell.tsx` and identify the call that renders an assistant turn's text (the one whose surrounding data is a `BroTimelineTurn` with `turn_id`, `thread_id`, and a thread carrying `workspace_id`). At that call site, pass:

```tsx
<MarkdownText
  downloadContext={
    sessionId && turn.thread_id && turn.turn_id && threadWorkspaceRoot
      ? {
          sessionId,
          threadId: turn.thread_id,
          turnId: turn.turn_id,
          workspaceRoot: threadWorkspaceRoot,
        }
      : undefined
  }
>
  {assistantText}
</MarkdownText>
```

where `sessionId` is the active session id already available in the shell, and `threadWorkspaceRoot` is the selected thread's `workspace_id` (the absolute workspace path; threads expose `workspace_id`). Only assistant turns get `downloadContext`; user-message and task-narration renders stay as-is (plain `MarkdownText`).

If the assistant text is rendered inside `MobileThreadSurface` / a turn component without `sessionId` or the thread `workspace_id` in scope, thread those two values down as props from the component that has them (the same place `selectedThread`/`bro` are known). Keep the prop name `downloadContext` end-to-end.

- [ ] **Step 6: Run the full UI test suite for regressions**

Run: `npx vitest run src/components/ui/markdown-text.test.tsx src/components/ui/workspace-file-link.test.tsx src/lib/workspace-paths.test.ts`
Expected: PASS. Then `npx tsc --noEmit` → clean.
(Note: the broader `App.test.tsx` suite has known pre-existing async flakiness unrelated to this work; rely on `tsc` + these targeted tests.)

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/components/ui/markdown-text.tsx src/newbro/ui/src/components/ui/markdown-text.test.tsx src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/lib/session-client.ts
git commit -m "feat(ui): render workspace download controls in assistant messages"
```

---

## Final verification (after all tasks)

- [ ] Backend/node: `.venv/bin/python -m pytest tests/api/test_workspace_path_tokens.py tests/protocol/test_workspace_file_messages.py tests/executors/node/test_workspace_files.py tests/executors/node/test_service_read_workspace_file.py tests/runtime/test_executor_node_manager_workspace_file.py tests/api/ws/test_executors_workspace_file_dispatch.py tests/api/routes/test_workspace_files_route.py -v` → all pass.
- [ ] UI: `cd src/newbro/ui && npx tsc --noEmit` clean; the three new test files pass.
- [ ] Manual smoke (optional): open a thread whose assistant wrote an absolute in-workspace path; confirm a "↓ <name>" control appears, downloads the file, and that hand-editing the URL to a path not in the turn → 403, and to an out-of-workspace path → 403.

---

## Notes / known limitations (from the spec)

- Downloads only work for threads the node has **bound a workspace to** (i.e. opened/subscribed this process lifetime). After a node restart, re-opening the thread re-establishes the binding. A request for an unbound thread returns `denied` — secure by default.
- V1 detects **absolute** paths only; relative paths and paths containing spaces are not linkified.
- Dotfiles/secrets that live **inside** the workspace are downloadable when the assistant writes their absolute path (boundary == assistant's read scope).
