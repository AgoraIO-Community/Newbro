# Hermes Second Executor — Implementation Plan (Python backend + CLI)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Hermes as a first-class executor family (peer to `codex`) that runs through Hermes's TUI Gateway JSON-RPC app-server over stdio, with full node wiring, registry validation, and CLI setup/probe/install support.

**Architecture:** A new `hermes/` adapter package owns a from-scratch newline-delimited JSON-RPC stdio client to a single long-lived `hermes` gateway process per node, multiplexed by session id. Hermes emits the generic `ExecutorEvent` stream (no Codex multi-message-turn coupling). A shared `SUPPORTED_EXECUTOR_FAMILIES` constant feeds the registry, both argparse parsers, and the interactive setup path so nothing drifts.

**Tech Stack:** Python 3.12, asyncio, Pydantic, pytest. Mirrors existing `codex/` and `acpx/` adapters.

**Scope:** Python backend + CLI only. The macOS menu-bar app changes (spec §6) are a separate follow-on plan (separate Swift toolchain).

**Spec:** `docs/superpowers/specs/2026-06-09-hermes-second-executor-design.md`

---

## File Structure

- Create `src/newbro/executors/families.py` — canonical `SUPPORTED_EXECUTOR_FAMILIES` tuple.
- Modify `src/newbro/runtime/config.py` — alias `SUPPORTED_DETACHED_EXECUTOR_TYPES` to the shared tuple.
- Modify `src/newbro/executors/node/registry.py` — validate family membership.
- Create `src/newbro/executors/adapters/hermes/{__init__,probe,jsonrpc,client,session,executor}.py` — the adapter.
- Modify `src/newbro/executors/adapters/__init__.py` — export Hermes types.
- Modify `src/newbro/executors/node/service.py` — `_build_executors` Hermes branch.
- Modify `src/newbro/executors/node/__main__.py` — node parser `--enabled-executor` choices.
- Modify `src/newbro/cli/parser.py`, `src/newbro/cli/dispatch.py` — top-level parser + routing.
- Modify `src/newbro/cli/prompts.py`, `src/newbro/cli/setup_resolvers.py` — interactive setup.
- Modify `src/newbro/cli/commands/executor_settings.py` — probe/use/install generalization.
- Create `docs/protocol/hermes-gateway.md`, `docs/protocol/fixtures/hermes-gateway-sample.jsonl` — wire contract + fixture.
- Update `docs/architecture/executors.md`, `docs/memories.md`.

Run the whole suite with `.venv/bin/python -m pytest`.

---

## Task 1: Discovery spike — pin the Hermes gateway wire format

**This task gates Tasks 5, 7, 8.** No production code; its deliverables are a recorded fixture and a wire-contract doc that the later tasks consume. Do this against a live `hermes` install.

**Files:**
- Create: `docs/protocol/fixtures/hermes-gateway-sample.jsonl`
- Create: `docs/protocol/hermes-gateway.md`

- [ ] **Step 1: Confirm the binary and version flag**

Run: `hermes --version`
Record the exact stdout (used by Task 4's probe parsing).

- [ ] **Step 2: Determine the gateway launch invocation and transport**

From the Hermes docs, the TUI gateway is `tui_gateway/server.py` over stdio or WebSocket. Establish the exact CLI invocation that starts it on **stdio** (stdout = JSON-RPC, stderr = logs). Try, in order, and record which works:

```bash
hermes gateway run            # foreground gateway
hermes tui-gateway --stdio    # if exposed
python -m tui_gateway.server  # module form
```

Record the working command as `HERMES_GATEWAY_LAUNCH_ARGS` (the argv after the base command) at the top of `docs/protocol/hermes-gateway.md`.

- [ ] **Step 3: Capture a real session lifecycle**

Drive the gateway by hand (write JSON-RPC lines to its stdin, read stdout). Capture one full exchange:

```
-> {"jsonrpc":"2.0","id":1,"method":"session.create","params":{"cwd":"/tmp/hermes-probe"}}
<- {"jsonrpc":"2.0","id":1,"result":{...}}            # capture the session-id key name
-> {"jsonrpc":"2.0","id":2,"method":"prompt.submit","params":{...}}
<- {"jsonrpc":"2.0","method":"message.delta","params":{...}}
<- {"jsonrpc":"2.0","method":"tool.start","params":{...}}
<- {"jsonrpc":"2.0","method":"message.complete","params":{...}}
```

Then capture an interrupt exchange (`session.interrupt`) and a steer exchange (`session.steer`). Save every received line verbatim to `docs/protocol/fixtures/hermes-gateway-sample.jsonl` (one JSON object per line).

- [ ] **Step 4: Write the wire-contract doc**

In `docs/protocol/hermes-gateway.md` record, with exact key names from Step 3:
- the launch argv (`HERMES_GATEWAY_LAUNCH_ARGS`)
- whether the framing is newline-delimited JSON-RPC 2.0 (expected) or other
- request params + result shape for `session.create`, `prompt.submit`, `session.steer`, `session.interrupt` (note the exact **session-id param/result key**)
- event params for `message.delta`, `message.complete`, `tool.start/progress/complete`, `approval.request`, `clarify.request` (note whether each event carries the session id, and under which key — multiplexing depends on this)
- the §3 event→`ExecutorEventType` mapping from the spec

**If events do NOT carry a session id:** record this; Task 6 must then use one gateway process per session instead of a multiplexed per-node process. Note the chosen model explicitly in the doc.

- [ ] **Step 5: Commit**

```bash
git add docs/protocol/hermes-gateway.md docs/protocol/fixtures/hermes-gateway-sample.jsonl
git commit -m "docs(hermes): record gateway wire contract and sample fixture"
```

---

## Task 2: Shared supported-families constant

**Files:**
- Create: `src/newbro/executors/families.py`
- Modify: `src/newbro/runtime/config.py:19`
- Test: `tests/unit/executors/test_families.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_families.py
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES
from newbro.runtime.config import SUPPORTED_DETACHED_EXECUTOR_TYPES


def test_hermes_is_a_supported_family():
    assert "hermes" in SUPPORTED_EXECUTOR_FAMILIES
    assert SUPPORTED_EXECUTOR_FAMILIES[:2] == ("codex", "acpx")


def test_runtime_constant_does_not_drift_from_shared_tuple():
    # The runtime constant must be the same object/value as the shared source
    # of truth, so settings (detached_executor_types) cannot fall out of sync.
    assert SUPPORTED_DETACHED_EXECUTOR_TYPES == SUPPORTED_EXECUTOR_FAMILIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_families.py -v`
Expected: FAIL — `ModuleNotFoundError: newbro.executors.families`.

- [ ] **Step 3: Create the constant**

```python
# src/newbro/executors/families.py
"""Canonical list of executor families Newbro can run as detached nodes.

Single source of truth: the node registry, both CLI argparse parsers, the
interactive setup path, and runtime settings all reference this tuple so they
cannot drift apart.
"""

from __future__ import annotations

SUPPORTED_EXECUTOR_FAMILIES: tuple[str, ...] = ("codex", "acpx", "hermes")
```

- [ ] **Step 4: Alias the runtime constant**

In `src/newbro/runtime/config.py`, replace the literal at line 19:

```python
# was: SUPPORTED_DETACHED_EXECUTOR_TYPES = ("codex", "acpx")
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES

SUPPORTED_DETACHED_EXECUTOR_TYPES = SUPPORTED_EXECUTOR_FAMILIES
```

Place the import with the other top-of-module imports; keep the assignment where the old literal was.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_families.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add src/newbro/executors/families.py src/newbro/runtime/config.py tests/unit/executors/test_families.py
git commit -m "feat(executors): add shared SUPPORTED_EXECUTOR_FAMILIES with hermes"
```

---

## Task 3: Registry validates family membership

**Files:**
- Modify: `src/newbro/executors/node/registry.py` (`create_node`, `update_node`)
- Test: `tests/unit/executors/test_node_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_node_registry.py
import pytest

from newbro.executors.node.registry import ExecutorNodeRegistry, ExecutorNodeRegistryError


@pytest.mark.asyncio
async def test_create_node_accepts_hermes(tmp_path):
    registry = ExecutorNodeRegistry(path=tmp_path / "nodes.yaml")
    issue = await registry.create_node(name="H", enabled_executors=["hermes"])
    assert issue.node.enabled_executors == ["hermes"]


@pytest.mark.asyncio
async def test_create_node_rejects_unknown_family(tmp_path):
    registry = ExecutorNodeRegistry(path=tmp_path / "nodes.yaml")
    with pytest.raises(ExecutorNodeRegistryError, match="Unsupported executor family"):
        await registry.create_node(name="X", enabled_executors=["bogus"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_node_registry.py -v`
Expected: FAIL — `test_create_node_rejects_unknown_family` does not raise (registry currently accepts any string).

- [ ] **Step 3: Add validation**

In `src/newbro/executors/node/registry.py`, add the import near the top:

```python
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES
```

Add a helper near `_normalize_executor_list`:

```python
def _validate_supported_families(families: list[str]) -> None:
    for family in families:
        if family not in SUPPORTED_EXECUTOR_FAMILIES:
            raise ExecutorNodeRegistryError(
                f"Unsupported executor family: {family}. "
                f"Supported: {', '.join(SUPPORTED_EXECUTOR_FAMILIES)}."
            )
```

In `create_node`, after the `len(normalized_executors) > 1` check, add:

```python
        _validate_supported_families(normalized_executors)
```

In `update_node`, inside the `if enabled_executors is not None:` block, after the `len > 1` check and before `updates["enabled_executors"] = normalized_executors`, add:

```python
                _validate_supported_families(normalized_executors)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_node_registry.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/node/registry.py tests/unit/executors/test_node_registry.py
git commit -m "feat(executors): validate node executor family membership"
```

---

## Task 4: Hermes binary probe

**Files:**
- Create: `src/newbro/executors/adapters/hermes/__init__.py`
- Create: `src/newbro/executors/adapters/hermes/probe.py`
- Test: `tests/unit/executors/test_hermes_probe.py`

V1 enforces no Hermes minimum version (no known floor): the probe reports `ok=True` when `hermes --version` exits 0, parsing a `X.Y.Z` version string when present.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_hermes_probe.py
from newbro.executors.adapters.hermes.probe import parse_hermes_version


def test_parse_version_extracts_semver():
    assert parse_hermes_version("hermes 1.4.2") == "1.4.2"


def test_parse_version_handles_missing():
    assert parse_hermes_version("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_probe.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the probe**

Create the package `__init__.py` **empty** for now (Task 6 adds the exports, once `executor`/`session` exist — importing them here before they exist would break collection of this task's test):

```python
# src/newbro/executors/adapters/hermes/__init__.py
```

```python
# src/newbro/executors/adapters/hermes/probe.py
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HermesProbeResult:
    path: str
    version: str | None
    ok: bool
    error: str | None = None


def parse_hermes_version(output: str | None) -> str | None:
    if not output:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
    return match.group(0) if match else None


def probe_hermes_command(command: str) -> HermesProbeResult:
    path = command if os.path.isabs(command) else (shutil.which(command) or command)
    try:
        completed = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except FileNotFoundError:
        return HermesProbeResult(path=path, version=None, ok=False, error="command not found")
    except subprocess.TimeoutExpired:
        return HermesProbeResult(path=path, version=None, ok=False, error="hermes --version timed out")
    except Exception as exc:  # noqa: BLE001 - surface any spawn failure as a probe error
        return HermesProbeResult(path=path, version=None, ok=False, error=str(exc))
    output = (completed.stdout or completed.stderr or "").strip()
    version = parse_hermes_version(output)
    if completed.returncode != 0:
        first_line = output.splitlines()[0].strip() if output else None
        return HermesProbeResult(
            path=path,
            version=version,
            ok=False,
            error=first_line or f"hermes --version exited {completed.returncode}",
        )
    return HermesProbeResult(path=path, version=version, ok=True)
```

Note: the package `__init__.py` stays empty until Task 6 populates the exports. The probe test imports `...hermes.probe` directly, so an empty `__init__.py` lets it collect cleanly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_probe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/hermes/__init__.py src/newbro/executors/adapters/hermes/probe.py tests/unit/executors/test_hermes_probe.py
git commit -m "feat(hermes): add hermes binary probe"
```

---

## Task 5: JSON-RPC stdio peer for the gateway

**Files:**
- Create: `src/newbro/executors/adapters/hermes/jsonrpc.py`
- Test: `tests/unit/executors/test_hermes_jsonrpc.py`

A from-scratch newline-delimited JSON-RPC 2.0 peer (confirm framing matches Task 1's fixture). Mirrors the Codex peer but is self-contained to avoid cross-adapter coupling.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_hermes_jsonrpc.py
import asyncio
import json

import pytest

from newbro.executors.adapters.hermes.jsonrpc import HermesJsonRpcPeer


async def _make_peer_over_pipe():
    # Loopback: peer writes to `to_peer`, reads responses we inject via `from_peer`.
    reader = asyncio.StreamReader()
    transport_writes: list[bytes] = []

    class _FakeWriter:
        def write(self, data: bytes) -> None:
            transport_writes.append(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    peer = HermesJsonRpcPeer(reader, _FakeWriter())
    return peer, reader, transport_writes


@pytest.mark.asyncio
async def test_request_resolves_on_matching_response():
    peer, reader, writes = await _make_peer_over_pipe()
    request = asyncio.ensure_future(peer.request("session.create", {"cwd": "/tmp"}))
    await asyncio.sleep(0)  # let the request serialize
    sent = json.loads(writes[0].decode())
    assert sent["method"] == "session.create"
    reader.feed_data(
        (json.dumps({"jsonrpc": "2.0", "id": sent["id"], "result": {"session_id": "s1"}}) + "\n").encode()
    )
    assert await request == {"session_id": "s1"}
    await peer.close()


@pytest.mark.asyncio
async def test_notifications_surface_as_events():
    peer, reader, _ = await _make_peer_over_pipe()
    reader.feed_data(
        (json.dumps({"jsonrpc": "2.0", "method": "message.delta", "params": {"text": "hi"}}) + "\n").encode()
    )
    event = await peer.next_event()
    assert event["method"] == "message.delta"
    await peer.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_jsonrpc.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the peer**

```python
# src/newbro/executors/adapters/hermes/jsonrpc.py
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator


class HermesJsonRpcPeer:
    """Newline-delimited JSON-RPC 2.0 peer over a stdio stream pair."""

    def __init__(self, reader: asyncio.StreamReader, writer: object) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[object]] = {}
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._read_loop())

    async def request(self, method: str, params: dict[str, object] | None = None) -> object:
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        return await future

    async def notify(self, method: str, params: dict[str, object] | None = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def next_event(self) -> dict[str, object]:
        return await self._events.get()

    async def iter_events(self) -> AsyncIterator[dict[str, object]]:
        while True:
            yield await self.next_event()

    async def close(self) -> None:
        self._reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader_task
        self._writer.close()
        await self._writer.wait_closed()

    async def _send(self, payload: dict[str, object]) -> None:
        self._writer.write(json.dumps(payload).encode("utf-8") + b"\n")
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                message = json.loads(stripped.decode("utf-8"))
                if isinstance(message, dict) and "id" in message and ("result" in message or "error" in message):
                    self._handle_response(message)
                    continue
                if isinstance(message, dict):
                    await self._events.put(message)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Hermes gateway connection closed."))
            self._pending.clear()

    def _handle_response(self, message: dict[str, object]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return
        error = message.get("error")
        if error is not None:
            future.set_exception(RuntimeError(str(error)))
            return
        future.set_result(message.get("result"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_jsonrpc.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/hermes/jsonrpc.py tests/unit/executors/test_hermes_jsonrpc.py
git commit -m "feat(hermes): add newline-delimited json-rpc stdio peer"
```

---

## Task 6: Session type, gateway client, and executor capabilities

**Files:**
- Create: `src/newbro/executors/adapters/hermes/session.py`
- Create: `src/newbro/executors/adapters/hermes/client.py`
- Create: `src/newbro/executors/adapters/hermes/executor.py`
- Modify: `src/newbro/executors/adapters/__init__.py`
- Test: `tests/unit/executors/test_hermes_executor.py`

The client manages gateway processes keyed by working directory (Task 1: `TERMINAL_CWD` is per-process) and routes events to per-session queues by `params.session_id`. The launch/env details and method/event shapes below are reconciled with Task 1's `docs/protocol/hermes-gateway.md`.

- [ ] **Step 1: Write the failing capabilities test**

```python
# tests/unit/executors/test_hermes_executor.py
from newbro.executors.adapters.hermes import HermesExecutor


def test_capabilities_are_core_run_loop_only():
    caps = HermesExecutor(command="hermes").get_capabilities()
    assert caps.executor_type == "hermes"
    assert caps.supports_follow_up is True
    assert caps.supports_cancel is True
    assert caps.supports_pause is False
    assert caps.supports_resume is False
    assert caps.supports_thread_list is False
    assert caps.supports_audio_instruction is False
    assert caps.skills == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_executor.py -v`
Expected: FAIL — `HermesExecutor` does not exist.

- [ ] **Step 3: Implement session, client, and executor skeleton**

```python
# src/newbro/executors/adapters/hermes/session.py
from __future__ import annotations

from pathlib import Path

from pydantic import PrivateAttr

from newbro.executors.core import ExecutorSession


class HermesExecutorSession(ExecutorSession):
    _cwd: Path | None = PrivateAttr(default=None)
    _gateway_session_id: str | None = PrivateAttr(default=None)

    def attach(self, *, cwd: Path, gateway_session_id: str) -> None:
        self._cwd = cwd
        self._gateway_session_id = gateway_session_id
        self.session_id = gateway_session_id
        self.metadata.update({"cwd": str(cwd), "gateway_session_id": gateway_session_id})

    @property
    def cwd(self) -> Path:
        if self._cwd is None:
            raise RuntimeError("Hermes cwd not attached.")
        return self._cwd

    @property
    def gateway_session_id(self) -> str:
        if self._gateway_session_id is None:
            raise RuntimeError("Hermes gateway session id not attached.")
        return self._gateway_session_id
```

Reconciled with Task 1's findings (`docs/protocol/hermes-gateway.md`):
- The gateway is **not** launched via the `hermes` binary. Spawn the Hermes project's venv python with `["-m", "tui_gateway.entry"]`, env `HERMES_PYTHON_SRC_ROOT`/`PYTHONPATH`/`TERMINAL_CWD`/`HERMES_CWD`, and process `cwd` = the workspace.
- The working directory is set via **`TERMINAL_CWD` at spawn**, not a `session.create` param (`session.create` params are `{"cols": 80}`; the session id is `result["session_id"]`). So gateway **processes are keyed by working directory**; multiple sessions multiplex on one process via `params.session_id`.
- The project root is parsed from `<command> --version` ("Project: …"), defaulting to `~/.hermes/hermes-agent`; the gateway python is `<root>/venv/bin/python3`.
- The client's public API stays **session-id-keyed** (so the executor and the Task 7/8 fake clients are unaffected). The event router pushes each event's `params` dict (carrying `type`/`session_id`/`payload`) onto the per-session queue, skipping global events whose `session_id` is empty.

```python
# src/newbro/executors/adapters/hermes/client.py
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .jsonrpc import HermesJsonRpcPeer

GATEWAY_MODULE_ARGS: list[str] = ["-m", "tui_gateway.entry"]
DEFAULT_PROJECT_ROOT = Path.home() / ".hermes" / "hermes-agent"


def resolve_gateway_launch(command: str, project_root: str | None) -> tuple[str, Path]:
    """Return (python_executable, project_root) for launching the gateway.

    project_root defaults to parsing the `Project:` line of `<command> --version`,
    falling back to ~/.hermes/hermes-agent. The gateway python is
    <project_root>/venv/bin/python3.
    """
    root: Path | None = Path(project_root) if project_root else None
    if root is None:
        try:
            completed = subprocess.run(
                [command, "--version"], check=False, capture_output=True, text=True, timeout=8
            )
            match = re.search(r"^Project:\s*(.+)$", completed.stdout or "", re.MULTILINE)
            if match:
                root = Path(match.group(1).strip())
        except Exception:  # noqa: BLE001 - fall back to the default root on any probe failure
            root = None
    if root is None:
        root = DEFAULT_PROJECT_ROOT
    return str(root / "venv" / "bin" / "python3"), root


@dataclass(slots=True)
class _GatewayProcess:
    process: asyncio.subprocess.Process
    peer: HermesJsonRpcPeer
    router_task: asyncio.Task[None] | None = None
    session_queues: dict[str, asyncio.Queue[dict[str, object]]] = field(default_factory=dict)


class HermesGatewayClient:
    """Gateway processes keyed by working directory (TERMINAL_CWD is per-process).

    Public API is session-id-keyed; a session id is internally mapped to the
    gateway process that owns it.
    """

    def __init__(self, *, command: str = "hermes", project_root: str | None = None) -> None:
        self._command = command
        self._project_root = project_root
        self._lock = asyncio.Lock()
        self._by_cwd: dict[str, _GatewayProcess] = {}
        self._gateway_by_session: dict[str, _GatewayProcess] = {}

    async def _ensure_process(self, cwd: Path) -> _GatewayProcess:
        key = str(cwd)
        async with self._lock:
            existing = self._by_cwd.get(key)
            if existing is not None and existing.process.returncode is None:
                return existing
            python_executable, root = resolve_gateway_launch(self._command, self._project_root)
            env = dict(os.environ)
            env["HERMES_PYTHON_SRC_ROOT"] = str(root)
            env["PYTHONPATH"] = os.pathsep.join(
                [str(root), env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
            env["TERMINAL_CWD"] = key
            env["HERMES_CWD"] = key
            process = await asyncio.create_subprocess_exec(
                python_executable,
                *GATEWAY_MODULE_ARGS,
                cwd=key,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert process.stdout is not None and process.stdin is not None
            gateway = _GatewayProcess(process=process, peer=HermesJsonRpcPeer(process.stdout, process.stdin))
            gateway.router_task = asyncio.create_task(self._route_events(gateway))
            self._by_cwd[key] = gateway
            return gateway

    def _gateway(self, session_id: str) -> _GatewayProcess:
        gateway = self._gateway_by_session.get(session_id)
        if gateway is None:
            raise RuntimeError(f"Unknown hermes session: {session_id}")
        return gateway

    async def create_session(self, cwd: Path) -> str:
        gateway = await self._ensure_process(cwd)
        result = await gateway.peer.request("session.create", {"cols": 80})
        if not isinstance(result, dict) or "session_id" not in result:
            raise RuntimeError(f"Hermes session.create returned unexpected result: {result!r}")
        session_id = str(result["session_id"])
        gateway.session_queues.setdefault(session_id, asyncio.Queue())
        self._gateway_by_session[session_id] = gateway
        return session_id

    async def submit_prompt(self, session_id: str, text: str) -> None:
        await self._gateway(session_id).peer.request(
            "prompt.submit", {"session_id": session_id, "text": text}
        )

    async def steer(self, session_id: str, text: str) -> None:
        result = await self._gateway(session_id).peer.request(
            "session.steer", {"session_id": session_id, "text": text}
        )
        if isinstance(result, dict) and result.get("status") == "rejected":
            raise RuntimeError("hermes session.steer rejected")

    async def interrupt(self, session_id: str) -> None:
        await self._gateway(session_id).peer.request("session.interrupt", {"session_id": session_id})

    async def events_for(self, session_id: str) -> asyncio.Queue[dict[str, object]]:
        return self._gateway(session_id).session_queues.setdefault(session_id, asyncio.Queue())

    async def _route_events(self, gateway: _GatewayProcess) -> None:
        async for event in gateway.peer.iter_events():
            params = event.get("params") if isinstance(event, dict) else None
            if not isinstance(params, dict):
                continue
            session_id = params.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue  # global event (gateway.ready, skin.changed) — not session-scoped
            queue = gateway.session_queues.setdefault(session_id, asyncio.Queue())
            await queue.put(params)

    async def aclose(self) -> None:
        for gateway in list(self._by_cwd.values()):
            if gateway.router_task is not None:
                gateway.router_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await gateway.router_task
            await gateway.peer.close()
            if gateway.process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    gateway.process.terminate()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(gateway.process.wait(), timeout=5.0)
        self._by_cwd.clear()
        self._gateway_by_session.clear()
```

```python
# src/newbro/executors/adapters/hermes/executor.py
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from newbro.executors.core import ExecutorCapabilities, ExecutorEvent, ExecutorEventType
from newbro.protocol import ExecutionRun, ExecutorTextInstruction, Task

from .client import HermesGatewayClient
from .probe import probe_hermes_command
from .session import HermesExecutorSession


class HermesExecutor:
    def __init__(
        self,
        *,
        command: str = "hermes",
        project_root: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._command = command
        self._timeout_seconds = timeout_seconds
        self._client = HermesGatewayClient(command=command, project_root=project_root)
        self._capabilities = ExecutorCapabilities(
            executor_type="hermes",
            supports_resume=False,
            supports_follow_up=True,
            supports_audio_instruction=False,
            supports_thread_list=False,
            supports_pause=False,
            supports_cancel=True,
            supports_setup=False,
        )
        self._sessions_by_run: dict[str, HermesExecutorSession] = {}

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def refresh_capabilities(self) -> ExecutorCapabilities:
        probe = await asyncio.to_thread(probe_hermes_command, self._command)
        self._capabilities.version = probe.version
        self._capabilities.minimum_version = None
        self._capabilities.availability_reason = None if probe.ok else (probe.error or "hermes_not_found")
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> HermesExecutorSession:
        cwd = Path(workspace_id or os.getcwd()).resolve()
        gateway_session_id = await self._client.create_session(cwd)
        session = HermesExecutorSession(
            session_id=gateway_session_id,
            executor_type="hermes",
            metadata={},
        )
        session.attach(cwd=cwd, gateway_session_id=gateway_session_id)
        return session

    async def cancel_run(self, run_id: str) -> None:
        session = self._sessions_by_run.get(run_id)
        if session is not None:
            await self._client.interrupt(session.gateway_session_id)

    async def pause_run(self, run_id: str) -> None:
        # supports_pause is False, so the runtime never calls this. Implemented
        # as an explicit unsupported no-op rather than aliasing cancel, to avoid
        # promising a resumable paused state we do not have.
        return None

    async def aclose(self) -> None:
        await self._client.aclose()

    def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: HermesExecutorSession,
    ) -> AsyncIterator[ExecutorEvent]:
        return self._drive_prompt(run, session, task.goal or task.title)

    def handle_text_instruction(
        self,
        run: ExecutionRun,
        session: HermesExecutorSession,
        instruction: ExecutorTextInstruction,
    ) -> AsyncIterator[ExecutorEvent]:
        return self._drive_prompt(run, session, instruction.text, follow_up=True)

    def handle_audio_instruction(self, run, session, audio):  # pragma: no cover - unsupported
        raise NotImplementedError("Hermes V1 does not support audio instructions.")

    async def _drive_prompt(
        self,
        run: ExecutionRun,
        session: HermesExecutorSession,
        text: str,
        *,
        follow_up: bool = False,
    ) -> AsyncIterator[ExecutorEvent]:
        # Implemented in Task 7.
        raise NotImplementedError
```

Now populate the package `__init__.py` (left empty in Task 4):

```python
# src/newbro/executors/adapters/hermes/__init__.py
from .executor import HermesExecutor
from .session import HermesExecutorSession

__all__ = ["HermesExecutor", "HermesExecutorSession"]
```

Append to `src/newbro/executors/adapters/__init__.py`:

```python
from .hermes import HermesExecutor, HermesExecutorSession
```

and add `"HermesExecutor"`, `"HermesExecutorSession"` to its `__all__`.

Field-name note (verified): `Task` has required `task_id`, `root_task_id`, `title`, `goal` (no `description`) — `run_task` uses `task.goal or task.title`. `ExecutorTextInstruction` (in `newbro/protocol/executor_node.py`) requires `instruction_id`, `target_persona_id`, `text`. The tests below construct these with all required fields.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_executor.py::test_capabilities_are_core_run_loop_only -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/hermes/ src/newbro/executors/adapters/__init__.py tests/unit/executors/test_hermes_executor.py
git commit -m "feat(hermes): add gateway client, session, and executor capabilities"
```

---

## Task 7: run_task event normalization against the fixture

**Files:**
- Modify: `src/newbro/executors/adapters/hermes/executor.py` (`_drive_prompt`)
- Test: `tests/unit/executors/test_hermes_run_task.py`

Drive a prompt and map gateway events to `ExecutorEvent`. Per Task 1's contract, the client's event router pushes each event's **`params` dict** (`{"type", "session_id", "payload"}`) onto the per-session queue; text lives in `payload.text`; `message.complete` is the single terminal event and its `payload.status` selects COMPLETED / CANCELLED / FAILED. The test uses a fake client that scripts those `params` dicts, so it is independent of a live binary.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_hermes_run_task.py
import asyncio
from pathlib import Path

import pytest

from newbro.executors.adapters.hermes.executor import HermesExecutor
from newbro.executors.adapters.hermes.session import HermesExecutorSession
from newbro.executors.core import ExecutorEventType
from newbro.protocol import ExecutionRun, Task


class _FakeClient:
    """Scripts a gateway event sequence (each item is an event `params` dict)."""

    def __init__(self, event_params: list[dict[str, object]]):
        self._queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        for params in event_params:
            self._queue.put_nowait(params)
        self.submitted: list[tuple[str, str]] = []
        self.interrupted: list[str] = []

    async def submit_prompt(self, session_id, text):
        self.submitted.append((session_id, text))

    async def steer(self, session_id, text):
        self.submitted.append((session_id, text))

    async def interrupt(self, session_id):
        self.interrupted.append(session_id)

    async def events_for(self, session_id):
        return self._queue


def _make(event_params):
    executor = HermesExecutor(command="hermes")
    executor._client = _FakeClient(event_params)  # type: ignore[assignment]
    session = HermesExecutorSession(session_id="sess-1", executor_type="hermes", metadata={})
    session.attach(cwd=Path("/tmp"), gateway_session_id="sess-1")
    run = ExecutionRun(run_id="run-1", execution_session_id="es-1", task_id="t-1", executor_type="hermes")
    task = Task(task_id="t-1", root_task_id="t-1", title="Do it", goal="Do the thing")
    return executor, session, run, task


@pytest.mark.asyncio
async def test_run_task_streams_progress_then_completed():
    event_params = [
        {"type": "message.delta", "session_id": "sess-1", "payload": {"text": "working"}},
        {"type": "tool.start", "session_id": "sess-1", "payload": {"name": "shell"}},
        {"type": "message.complete", "session_id": "sess-1", "payload": {"text": "done", "status": "complete"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    types = [event.event_type for event in seen]
    assert types[-1] == ExecutorEventType.COMPLETED
    assert ExecutorEventType.PROGRESS in types
    assert seen[-1].message == "done"
    assert executor._client.submitted == [("sess-1", "Do the thing")]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_message_complete_interrupted_maps_to_cancelled():
    event_params = [
        {"type": "message.complete", "session_id": "sess-1", "payload": {"text": "Operation interrupted", "status": "interrupted"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    assert seen[-1].event_type == ExecutorEventType.CANCELLED


@pytest.mark.asyncio
async def test_message_complete_error_maps_to_failed():
    event_params = [
        {"type": "message.complete", "session_id": "sess-1", "payload": {"text": "boom", "status": "error"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    assert seen[-1].event_type == ExecutorEventType.FAILED


@pytest.mark.asyncio
async def test_run_task_maps_blocked_approval_request_terminally():
    event_params = [
        {"type": "approval.request", "session_id": "sess-1", "payload": {"command": "rm -rf /", "description": "Run rm -rf?"}},
    ]
    executor, session, run, task = _make(event_params)
    seen = [event async for event in executor.run_task(run, task, session)]
    assert seen[-1].event_type == ExecutorEventType.BLOCKED
    assert "rm -rf" in (seen[-1].message or "")
    assert seen[-1].metadata.get("hermes_event") == "approval.request"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_run_task.py -v`
Expected: FAIL — `_drive_prompt` raises `NotImplementedError`.

- [ ] **Step 3: Implement `_drive_prompt`**

Replace the `_drive_prompt` body in `executor.py`:

Define these module-level constants near the top of `executor.py` (event types grouped per Task 1 §7):

```python
_PROGRESS_EVENTS = frozenset({
    "message.delta", "tool.start", "tool.progress", "tool.complete", "tool.generating",
    "reasoning.delta", "reasoning.available", "thinking.delta", "status.update",
})
_BLOCKING_EVENTS = frozenset({"approval.request", "clarify.request"})
```

Replace the `_drive_prompt` body in `executor.py`:

```python
    async def _drive_prompt(
        self,
        run: ExecutionRun,
        session: HermesExecutorSession,
        text: str,
        *,
        follow_up: bool = False,
    ) -> AsyncIterator[ExecutorEvent]:
        self._sessions_by_run[run.run_id] = session
        queue = await self._client.events_for(session.gateway_session_id)
        try:
            if follow_up:
                # Single follow-up contract: steer only, no prompt.submit fallback.
                await self._client.steer(session.gateway_session_id, text)
            else:
                await self._client.submit_prompt(session.gateway_session_id, text)
        except Exception as exc:  # noqa: BLE001 - surface steer/submit failure observably
            yield ExecutorEvent(
                run_id=run.run_id,
                session_id=session.session_id,
                event_type=ExecutorEventType.FAILED,
                message=f"hermes prompt failed: {exc}",
            )
            return

        # Each queue item is an event `params` dict: {"type", "session_id", "payload"}.
        while True:
            params = await queue.get()
            etype = params.get("type")
            payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
            text_value = payload.get("text")
            progress_text = text_value or payload.get("preview") or payload.get("summary")
            if etype in _PROGRESS_EVENTS:
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.PROGRESS,
                    message=progress_text if isinstance(progress_text, str) else None,
                    metadata={"hermes_event": etype},
                )
                continue
            if etype == "message.complete":
                status = payload.get("status")
                if status == "interrupted":
                    terminal = ExecutorEventType.CANCELLED
                elif status == "error":
                    terminal = ExecutorEventType.FAILED
                else:
                    terminal = ExecutorEventType.COMPLETED
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=terminal,
                    message=text_value if isinstance(text_value, str) else None,
                    metadata={"hermes_event": etype, "status": status},
                )
                return
            if etype in _BLOCKING_EVENTS:
                prompt = payload.get("question") or payload.get("command") or payload.get("description")
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.BLOCKED,
                    message=prompt if isinstance(prompt, str) else f"hermes requested {etype}",
                    metadata={"hermes_event": etype, "request": payload},
                )
                return
            if etype == "error":
                yield ExecutorEvent(
                    run_id=run.run_id,
                    session_id=session.session_id,
                    event_type=ExecutorEventType.FAILED,
                    message=payload.get("message") if isinstance(payload.get("message"), str) else None,
                    metadata={"hermes_event": etype},
                )
                return
```

This matches Task 1's contract: `message.complete` is the single terminal event whose `payload.status` selects COMPLETED / CANCELLED / FAILED (no standalone interrupt-ack event). Cross-check against `docs/protocol/fixtures/hermes-gateway-sample.jsonl`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_run_task.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/hermes/executor.py tests/unit/executors/test_hermes_run_task.py
git commit -m "feat(hermes): normalize gateway events into ExecutorEvent stream"
```

---

## Task 8: Follow-up steer (no fallback) and cancel

**Files:**
- Test: `tests/unit/executors/test_hermes_follow_up.py`

`_drive_prompt` already routes follow-ups through `steer`. This task locks the no-fallback contract and cancel behavior with dedicated tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_hermes_follow_up.py
import asyncio
from pathlib import Path

import pytest

from newbro.executors.adapters.hermes.executor import HermesExecutor
from newbro.executors.adapters.hermes.session import HermesExecutorSession
from newbro.executors.core import ExecutorEventType
from newbro.protocol import ExecutionRun, ExecutorTextInstruction


class _SteerFailsClient:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self.submitted: list = []

    async def events_for(self, session_id):
        return self._queue

    async def submit_prompt(self, session_id, text):
        self.submitted.append(("submit", text))

    async def steer(self, session_id, text):
        raise RuntimeError("session not steerable")

    async def interrupt(self, session_id):
        return None


def _session():
    session = HermesExecutorSession(session_id="s", executor_type="hermes", metadata={})
    session.attach(cwd=Path("/tmp"), gateway_session_id="s")
    return session


@pytest.mark.asyncio
async def test_unsteerable_follow_up_fails_without_submit_fallback():
    executor = HermesExecutor(command="hermes")
    executor._client = _SteerFailsClient()  # type: ignore[assignment]
    session = _session()
    run = ExecutionRun(run_id="r", execution_session_id="e", task_id="t", executor_type="hermes")
    instruction = ExecutorTextInstruction(
        instruction_id="i", target_persona_id="p", text="and now refactor"
    )
    seen = [e async for e in executor.handle_text_instruction(run, session, instruction)]
    assert seen[-1].event_type == ExecutorEventType.FAILED
    assert executor._client.submitted == []  # type: ignore[attr-defined]  # no prompt.submit fallback


@pytest.mark.asyncio
async def test_cancel_run_interrupts_the_session():
    executor = HermesExecutor(command="hermes")
    calls: list[str] = []

    class _C:
        async def interrupt(self, session_id):
            calls.append(session_id)

    executor._client = _C()  # type: ignore[assignment]
    session = _session()
    executor._sessions_by_run["r"] = session
    await executor.cancel_run("r")
    assert calls == ["s"]
```

(`ExecutorTextInstruction` requires `instruction_id`, `target_persona_id`, `text` — all provided above.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_follow_up.py -v`
Expected: PASS already if Task 7 is correct — if either test fails, fix `_drive_prompt`/`cancel_run` so the no-fallback and interrupt contracts hold.

- [ ] **Step 3: (only if a test failed) adjust implementation**

If `test_unsteerable_follow_up_fails_without_submit_fallback` fails, ensure the `except` branch in `_drive_prompt` yields `FAILED` and `return`s without ever calling `submit_prompt` on the follow-up path. No code change is expected beyond Task 7.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_hermes_follow_up.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/executors/test_hermes_follow_up.py
git commit -m "test(hermes): lock no-fallback follow-up and interrupt contracts"
```

---

## Task 9: Node service builds the Hermes executor

**Files:**
- Modify: `src/newbro/executors/node/service.py:1118-1137` (`_build_executors`)
- Test: `tests/unit/executors/test_node_build_executors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_node_build_executors.py
from newbro.executors.adapters.hermes import HermesExecutor
from newbro.executors.node.config import ExecutorNodeSettings
from newbro.executors.node.service import ExecutorNodeService


class _StubTranscriber:
    available = False


def test_build_executors_constructs_hermes_from_config():
    settings = ExecutorNodeSettings(node_id="n", token="t", enabled_executors=["hermes"])
    service = ExecutorNodeService(
        settings=settings,
        executors_config={"hermes": {"command": "hermes"}},
        audio_transcriber=_StubTranscriber(),  # avoid constructing a real Whisper transcriber
    )
    built = service._executors  # noqa: SLF001 - white-box check of construction
    assert isinstance(built["hermes"], HermesExecutor)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_node_build_executors.py -v`
Expected: FAIL — `built` has no `"hermes"` key (branch missing).

- [ ] **Step 3: Add the Hermes branch**

In `src/newbro/executors/node/service.py`, add the import near the other adapter imports:

```python
from newbro.executors.adapters.hermes import HermesExecutor, HermesExecutorSession
```

In `_build_executors`, after the `acpx` branch:

```python
            elif executor_type == "hermes":
                built[executor_type] = HermesExecutor(
                    command=str((config or {}).get("command", "hermes")),
                    project_root=str((config or {}).get("project_root"))
                    if (config or {}).get("project_root") not in (None, "")
                    else None,
                    timeout_seconds=float((config or {}).get("timeout_seconds"))
                    if (config or {}).get("timeout_seconds") not in (None, "")
                    else None,
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_node_build_executors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/node/service.py tests/unit/executors/test_node_build_executors.py
git commit -m "feat(hermes): build hermes executor in the node service"
```

---

## Task 10: Top-level CLI parser + dispatch

**Files:**
- Modify: `src/newbro/cli/parser.py:107,111,128` (executor probe/use/run choices + install-hermes)
- Modify: `src/newbro/cli/dispatch.py:78` (`cmd_executor`)
- Test: `tests/unit/cli/test_executor_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cli/test_executor_parser.py
from pathlib import Path

from newbro.cli.parser import build_parser


def _parser():
    return build_parser(cli_name="newbro", env_file=Path("/tmp/.env"), start_public_port=8000)


def test_probe_accepts_hermes():
    args = _parser().parse_args(["executor", "probe", "--executor", "hermes"])
    assert args.executor == "hermes"


def test_enabled_executor_accepts_hermes():
    args = _parser().parse_args(
        ["executor", "run", "--base-url", "u", "--node-id", "n", "--token", "t", "--enabled-executor", "hermes"]
    )
    assert args.enabled_executor == ["hermes"]


def test_install_hermes_subcommand_parses():
    args = _parser().parse_args(["executor", "install-hermes"])
    assert args.executor_command == "install-hermes"
```

(`build_parser` is keyword-only: `cli_name`, `env_file`, `start_public_port` — verified against `tests/unit/cli/test_version.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_parser.py -v`
Expected: FAIL — `hermes` not in choices / `install-hermes` unknown.

- [ ] **Step 3: Update the parser**

In `src/newbro/cli/parser.py`, add the import:

```python
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES
```

Change the two `--executor` arguments (probe and use) from `choices=["codex"]` to `choices=list(SUPPORTED_EXECUTOR_FAMILIES)`. Change `--enabled-executor` from `choices=["codex", "acpx"]` to `choices=list(SUPPORTED_EXECUTOR_FAMILIES)`. Add a subparser next to `install-codex`:

```python
    executor_subparsers.add_parser(
        "install-hermes",
        help="Install or repair the local Hermes CLI used by executor nodes.",
    )
```

- [ ] **Step 4: Route it in dispatch**

In `src/newbro/cli/dispatch.py`, in `cmd_executor`, after the `install-codex` route:

```python
    if args.executor_command == "install-hermes":
        return executor_settings_command.run_executor_install_hermes(args, app)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_parser.py -v`
Expected: PASS (all three).

- [ ] **Step 6: Commit**

```bash
git add src/newbro/cli/parser.py src/newbro/cli/dispatch.py tests/unit/cli/test_executor_parser.py
git commit -m "feat(cli): accept hermes in executor probe/use/run and add install-hermes"
```

---

## Task 11: Detached node's own parser accepts hermes

**Files:**
- Modify: `src/newbro/executors/node/__main__.py:18` (`build_parser` `--enabled-executor`)
- Test: `tests/unit/executors/test_node_main_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_node_main_parser.py
from newbro.executors.node.__main__ import build_parser


def test_node_parser_accepts_enabled_executor_hermes():
    parser = build_parser()
    args = parser.parse_args(["--base-url", "u", "--node-id", "n", "--token", "t", "--enabled-executor", "hermes"])
    assert args.enabled_executor == ["hermes"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_node_main_parser.py -v`
Expected: FAIL — `argument --enabled-executor: invalid choice: 'hermes'`.

- [ ] **Step 3: Update the node parser**

In `src/newbro/executors/node/__main__.py`, add the import:

```python
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES
```

Change `--enabled-executor` from `choices=["codex", "acpx"]` to `choices=list(SUPPORTED_EXECUTOR_FAMILIES)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_node_main_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/node/__main__.py tests/unit/executors/test_node_main_parser.py
git commit -m "fix(executors): accept hermes in the detached node parser"
```

---

## Task 12: Interactive setup writes the hermes executor block

**Files:**
- Modify: `src/newbro/cli/prompts.py:72` (`prompt_executor_selection`)
- Modify: `src/newbro/cli/setup_resolvers.py:181` (`resolve_executor_setup_values`)
- Test: `tests/unit/cli/test_setup_resolvers_hermes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cli/test_setup_resolvers_hermes.py
from newbro.cli.setup_resolvers import resolve_executor_setup_values


class _Callbacks:
    def connector_config_path(self):
        import pathlib, tempfile
        return pathlib.Path(tempfile.gettempdir()) / "hermes-setup-config.yaml"

    def prompt_executor_selection(self, default_selected=None):
        return ["hermes"]

    def existing_executor_enabled_types(self, raw):
        return []

    def existing_executors_config(self, raw):
        return {}

    def prompt_text_value(self, label, default_value="", required=False):
        return "hermes"

    def command_available(self, command):
        return True

    def detected_codex_command(self):
        return None


def test_setup_writes_hermes_command_block():
    result = resolve_executor_setup_values(
        existing_values={},
        environ={},
        existing_config_yaml={},
        callbacks=_Callbacks(),
    )
    assert "hermes" in result.config_text
    assert "command" in result.config_text
```

Inspect the real `SetupResolutionCallbacks` protocol and `ConnectorSetupResult` in `src/newbro/cli/setup_resolvers.py` and adjust the fake callbacks to satisfy the actual interface (the snippet covers the methods the Hermes branch needs).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_setup_resolvers_hermes.py -v`
Expected: FAIL — selection can't return `hermes` (not offered) and/or no `hermes` block is written.

- [ ] **Step 3: Offer hermes in the prompt**

In `src/newbro/cli/prompts.py`, in `prompt_executor_selection`, change:

```python
    executors = ["codex", "acpx"]
```

to:

```python
    from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES

    executors = list(SUPPORTED_EXECUTOR_FAMILIES)
```

- [ ] **Step 4: Write the hermes block in the resolver**

In `src/newbro/cli/setup_resolvers.py`, inside the `for executor_type in enabled_executors:` loop in `resolve_executor_setup_values`, add a branch parallel to the `codex` one:

```python
        elif executor_type == "hermes":
            command = callbacks.prompt_text_value(
                "Hermes command",
                default_value=str(existing_block.get("command") or "hermes"),
                required=True,
            )
            if not callbacks.command_available(command):
                print(f"[warn] command '{command}' is not currently available on PATH")
            executors_block["hermes"] = {"command": command}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_setup_resolvers_hermes.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/cli/prompts.py src/newbro/cli/setup_resolvers.py tests/unit/cli/test_setup_resolvers_hermes.py
git commit -m "feat(cli): support hermes in interactive executor setup"
```

---

## Task 13: executor_settings — probe/use/install-hermes

**Files:**
- Modify: `src/newbro/cli/commands/executor_settings.py`
- Test: `tests/unit/cli/test_executor_settings_hermes.py`

Generalize the Codex-only command module. `install_hermes_cli` resolves/validates the `hermes` binary and writes the config; the exact installer command (from Task 1) goes in `_install_hermes_runtime`. For V1, if `hermes` is already present, set it; otherwise raise a clear error pointing at Hermes's documented install/OAuth setup (no silent best-effort install of an unknown package).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cli/test_executor_settings_hermes.py
from newbro.cli.commands import executor_settings


def test_supported_executors_includes_hermes():
    assert "hermes" in executor_settings.SUPPORTED_EXECUTORS


def test_set_hermes_command_writes_block(tmp_path):
    config_path = tmp_path / "config.yaml"
    executor_settings.set_hermes_command(config_path=config_path, command="/usr/local/bin/hermes")
    text = config_path.read_text()
    assert "hermes" in text
    assert "/usr/local/bin/hermes" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_settings_hermes.py -v`
Expected: FAIL — `SUPPORTED_EXECUTORS` is `["codex"]`; `set_hermes_command` undefined.

- [ ] **Step 3: Generalize the module**

In `src/newbro/cli/commands/executor_settings.py`:

Replace the constant:

```python
from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES
from newbro.executors.adapters.hermes import probe as hermes_probe

SUPPORTED_EXECUTORS = list(SUPPORTED_EXECUTOR_FAMILIES)
```

Change `run_executor_probe` and `run_executor_use` to dispatch by family instead of rejecting non-codex. For probe:

```python
def run_executor_probe(args: Any, app: Any) -> int:
    if args.executor not in SUPPORTED_EXECUTORS:
        print(f"Unsupported executor: {args.executor}", file=sys.stderr)
        return 1
    config_path = app.ENV_LOCAL.with_name("config.yaml")
    if args.executor == "hermes":
        payload = hermes_probe_payload(config_path=config_path)
    else:
        payload = codex_probe_payload(config_path=config_path)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human_probe(payload)
    return 0
```

Add `set_hermes_command` (mirror `set_codex_command`, writing the `hermes` block):

```python
def set_hermes_command(*, config_path: Path, command: str) -> None:
    raw = config_files.load_existing_connector_yaml(config_path)
    runtime = config_files.existing_runtime_config(raw, removed_keys=set())
    connector_host = config_files.existing_connector_host_config(raw)
    connectors = config_files.existing_connectors_config(raw)
    executor_node = config_files.existing_executor_node_config(raw)
    enabled = list(executor_node.get("enabled_executors") or [])
    if "hermes" not in enabled:
        enabled.append("hermes")
    executor_node["enabled_executors"] = enabled
    executors = config_files.existing_executors_config(raw)
    hermes_config = dict(executors.get("hermes") or {})
    hermes_config["command"] = command
    executors["hermes"] = hermes_config
    rendered = config_files.render_connector_config(
        runtime=runtime,
        connector_host=connector_host,
        connectors=connectors,
        executor_node=executor_node,
        executors=executors,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(rendered, encoding="utf-8")


def hermes_probe_payload(*, config_path: Path) -> dict[str, object]:
    raw = config_files.load_existing_connector_yaml(config_path)
    executors = config_files.existing_executors_config(raw)
    configured_command = str((executors.get("hermes") or {}).get("command") or "hermes")
    result = hermes_probe.probe_hermes_command(configured_command)
    return {
        "supported_executors": list(SUPPORTED_EXECUTORS),
        "current": {
            "executor": "hermes",
            "command": configured_command,
            "resolved_path": result.path,
            "version": result.version,
            "ok": result.ok,
            "error": result.error,
        },
        "candidates": [],
    }


def install_hermes_cli(config_path: Path) -> str:
    result = hermes_probe.probe_hermes_command("hermes")
    if not result.ok:
        raise RuntimeError(
            "Hermes CLI is not available. Install it and run `hermes setup --portal` "
            "to authenticate, then re-run."
        )
    command = result.path
    set_hermes_command(config_path=config_path, command=command)
    return command


def run_executor_install_hermes(args: Any, app: Any) -> int:
    config_path = app.ENV_LOCAL.with_name("config.yaml")
    try:
        command = install_hermes_cli(config_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Hermes is ready: {command}")
    return 0
```

Also update `run_executor_use` to call `set_hermes_command` when `args.executor == "hermes"` (probe with `hermes_probe.probe_hermes_command` first; require an absolute path like the codex branch).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_executor_settings_hermes.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/cli/commands/executor_settings.py tests/unit/cli/test_executor_settings_hermes.py
git commit -m "feat(cli): hermes probe/use/install in executor settings"
```

---

## Task 14: Docs and full-suite verification

**Files:**
- Modify: `docs/architecture/executors.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Document Hermes as a real adapter family**

In `docs/architecture/executors.md`, under "Adapter direction", add a bullet:

```markdown
- Hermes is a real adapter family running through Hermes's TUI Gateway JSON-RPC
  app-server over stdio. V1 is core run loop only (create/prompt/steer/interrupt
  with streamed progress and a settled final answer); it advertises
  `supports_follow_up` and `supports_cancel`, with `supports_pause`,
  `supports_resume`, and `supports_thread_list` false. Gateway events normalize
  into the generic `ExecutorEvent` stream and do not use the Codex
  multi-message-turn contract. See `docs/protocol/hermes-gateway.md`.
```

- [ ] **Step 2: Append a memory note**

In `docs/memories.md`, append:

```markdown
- Hermes is supported as a second detached executor family (peer to Codex),
  driven over Hermes's TUI Gateway JSON-RPC stdio app-server. V1 is core run loop
  only; events map to the generic ExecutorEvent stream. Supported families are
  centralized in `newbro/executors/families.py::SUPPORTED_EXECUTOR_FAMILIES`,
  aliased by `runtime/config.py::SUPPORTED_DETACHED_EXECUTOR_TYPES`.
```

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS (no regressions). Also run `ruff check src/newbro` if configured.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/executors.md docs/memories.md
git commit -m "docs(hermes): record hermes executor family in architecture and memories"
```

---

## Out of scope (follow-on plans)

- **macOS menu-bar app** (spec §6): single-choice executor selector, per-family probe state (`probeByFamily`/`statusByFamily`), Hermes readiness diagnosis. Separate Swift plan.
- Hermes thread import, skills, audio, resume, and interactive approval/clarify response wiring (spec future scope).
