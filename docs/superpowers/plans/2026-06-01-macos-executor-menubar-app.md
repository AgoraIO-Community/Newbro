# macOS Menu-Bar Executor App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a macOS menu-bar app that supervises multiple concurrent Newbro executor-node profiles, each its own `newbro executor run` subprocess, with live status and credential editing.

**Architecture:** A thin Python `rumps` status-bar app under `src/newbro/executors/ui/`. It stores node profiles in `~/.newbro/menubar.json`, spawns one `python -m newbro.executors.node …` subprocess per active profile via the existing `command_specs.executor_node_command` builder, and maps the node's stderr status lines to a per-profile state. No node/protocol logic is reimplemented; the app is a supervisor + config editor. The node owns its own reconnection, so the UI adds no process-restart loop.

**Tech Stack:** Python 3.12, `rumps` (macOS status bar, optional `macos-ui` extra), `py2app` (bundling), pytest, stdlib `subprocess`/`threading`/`plistlib`/`shlex`.

---

## File Structure

**New files (all under `src/newbro/executors/ui/`):**
- `__init__.py` — package marker.
- `profiles.py` — `Profile` dataclass, `ProfileStore` (load/save `menubar.json`), `parse_connect_command`, `conflicting_profile_ids`, `MENUBAR_CONFIG_FILE`.
- `status.py` — `NodeStatus` enum, `StatusModel` (line/exit → state), `aggregate_status`.
- `process.py` — `NodeProcessController` (subprocess + reader thread + SIGTERM/SIGKILL stop).
- `supervisor.py` — `ProfileSupervisor` (per-profile controller+status map, start/stop/restart, aggregate, stop-all).
- `login_item.py` — `LoginItem` + `render_login_item_plist` (LaunchAgent plist).
- `app.py` — `MenuBarApp` (rumps shell) + `run_menu_bar_app()`. Thin; manually verified.

**New test files (under `tests/unit/executors/ui/`):**
- `__init__.py`, `test_profiles.py`, `test_status.py`, `test_process.py`, `test_supervisor.py`, `test_login_item.py`.

**Modified files:**
- `src/newbro/cli/parser.py` — add `executor ui` subcommand.
- `src/newbro/cli/dispatch.py` — route `executor ui`.
- `src/newbro/cli/commands/executor_ui.py` (new) — lazy-import launcher with a clear missing-extra message.
- `pyproject.toml` — add `macos-ui` / `macos-ui-build` optional extras.
- `packaging/menubar/setup.py` (new) — `py2app` build script.
- `docs/architecture/executors.md`, `docs/memories.md` — record the adopted UI.

---

### Task 1: Profile model and ProfileStore

**Files:**
- Create: `src/newbro/executors/ui/__init__.py`
- Create: `src/newbro/executors/ui/profiles.py`
- Create: `tests/unit/executors/ui/__init__.py`
- Test: `tests/unit/executors/ui/test_profiles.py`

- [ ] **Step 1: Create empty package markers**

Create `src/newbro/executors/ui/__init__.py` with a single line:

```python
"""macOS menu-bar app for supervising executor node profiles."""
```

Create `tests/unit/executors/ui/__init__.py` as an empty file (no content).

- [ ] **Step 2: Write the failing test for load/save round-trip**

Create `tests/unit/executors/ui/test_profiles.py`:

```python
from __future__ import annotations

from newbro.executors.ui.profiles import Profile, ProfileStore


def test_save_then_load_round_trips_profiles(tmp_path):
    path = tmp_path / "menubar.json"
    store = ProfileStore(path=path)
    profiles = [
        Profile(
            id="p1",
            label="Prod",
            base_url="https://synopse.example.com",
            node_id="node-1a2b",
            token="tok-1",
            enabled_executors=["codex"],
            auto_activate=True,
        ),
        Profile(id="p2", label="Staging", base_url="http://127.0.0.1:8000", node_id="node-9z", token="tok-2"),
    ]

    store.save(profiles)
    loaded = store.load()

    assert loaded == profiles
    assert loaded[1].enabled_executors == []
    assert loaded[1].auto_activate is False


def test_load_missing_file_returns_empty_list(tmp_path):
    store = ProfileStore(path=tmp_path / "does-not-exist.json")
    assert store.load() == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_profiles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.executors.ui.profiles'`

- [ ] **Step 4: Write minimal implementation**

Create `src/newbro/executors/ui/profiles.py`:

```python
from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path

from newbro.config_home import NEWBRO_HOME_DIR

MENUBAR_CONFIG_FILE = NEWBRO_HOME_DIR / "menubar.json"

_SCHEMA_VERSION = 1


@dataclass(slots=True)
class Profile:
    id: str
    label: str
    base_url: str
    node_id: str
    token: str
    enabled_executors: list[str] = field(default_factory=list)
    auto_activate: bool = False


class ProfileStore:
    def __init__(self, *, path: Path = MENUBAR_CONFIG_FILE) -> None:
        self._path = path

    def load(self) -> list[Profile]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        entries = raw.get("profiles", []) if isinstance(raw, dict) else []
        return [
            Profile(
                id=str(entry["id"]),
                label=str(entry.get("label", "")),
                base_url=str(entry.get("base_url", "")),
                node_id=str(entry.get("node_id", "")),
                token=str(entry.get("token", "")),
                enabled_executors=list(entry.get("enabled_executors", []) or []),
                auto_activate=bool(entry.get("auto_activate", False)),
            )
            for entry in entries
        ]

    def save(self, profiles: list[Profile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _SCHEMA_VERSION, "profiles": [asdict(p) for p in profiles]}
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_profiles.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add src/newbro/executors/ui/__init__.py src/newbro/executors/ui/profiles.py tests/unit/executors/ui/__init__.py tests/unit/executors/ui/test_profiles.py
git commit -m "feat(executor-ui): add Profile model and ProfileStore"
```

---

### Task 2: Connect-command parsing and duplicate-identity detection

**Files:**
- Modify: `src/newbro/executors/ui/profiles.py`
- Test: `tests/unit/executors/ui/test_profiles.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/executors/ui/test_profiles.py`:

```python
import pytest

from newbro.executors.ui.profiles import (
    ConnectCommandFields,
    conflicting_profile_ids,
    parse_connect_command,
)


def test_parse_connect_command_extracts_fields():
    text = (
        "newbro executor run --base-url https://synopse.example.com "
        "--node-id node-1a2b --token tok-xyz "
        "--enabled-executor codex --enabled-executor acpx"
    )
    fields = parse_connect_command(text)
    assert fields == ConnectCommandFields(
        base_url="https://synopse.example.com",
        node_id="node-1a2b",
        token="tok-xyz",
        enabled_executors=["codex", "acpx"],
    )


def test_parse_connect_command_requires_core_fields():
    with pytest.raises(ValueError):
        parse_connect_command("newbro executor run --base-url https://x --node-id n")


def test_conflicting_profile_ids_flags_same_node_and_url():
    profiles = [
        Profile(id="a", label="A", base_url="https://x", node_id="n1", token="t"),
        Profile(id="b", label="B", base_url="https://x", node_id="n1", token="t2"),
        Profile(id="c", label="C", base_url="https://x", node_id="n2", token="t3"),
    ]
    assert conflicting_profile_ids(profiles) == {"a", "b"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_profiles.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConnectCommandFields'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/newbro/executors/ui/profiles.py` (after the `Profile` dataclass):

```python
@dataclass(slots=True)
class ConnectCommandFields:
    base_url: str
    node_id: str
    token: str
    enabled_executors: list[str] = field(default_factory=list)


def parse_connect_command(text: str) -> ConnectCommandFields:
    tokens = shlex.split(text)
    base_url = node_id = token = ""
    enabled: list[str] = []
    index = 0
    while index < len(tokens):
        flag = tokens[index]
        if flag in {"--base-url", "--node-id", "--token", "--enabled-executor"} and index + 1 < len(tokens):
            value = tokens[index + 1]
            if flag == "--base-url":
                base_url = value
            elif flag == "--node-id":
                node_id = value
            elif flag == "--token":
                token = value
            else:
                enabled.append(value)
            index += 2
            continue
        index += 1
    missing = [name for name, value in (("--base-url", base_url), ("--node-id", node_id), ("--token", token)) if not value]
    if missing:
        raise ValueError(f"connect command is missing required fields: {', '.join(missing)}")
    return ConnectCommandFields(base_url=base_url, node_id=node_id, token=token, enabled_executors=enabled)


def conflicting_profile_ids(profiles: list[Profile]) -> set[str]:
    seen: dict[tuple[str, str], str] = {}
    conflicts: set[str] = set()
    for profile in profiles:
        key = (profile.base_url, profile.node_id)
        if key in seen:
            conflicts.add(seen[key])
            conflicts.add(profile.id)
        else:
            seen[key] = profile.id
    return conflicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_profiles.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/ui/profiles.py tests/unit/executors/ui/test_profiles.py
git commit -m "feat(executor-ui): parse connect commands and detect duplicate node identities"
```

---

### Task 3: StatusModel and aggregate status

**Files:**
- Create: `src/newbro/executors/ui/status.py`
- Test: `tests/unit/executors/ui/test_status.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/executors/ui/test_status.py`:

```python
from __future__ import annotations

from newbro.executors.ui.status import NodeStatus, StatusModel, aggregate_status


def feed(model: StatusModel, lines: list[str]) -> NodeStatus:
    model.on_start()
    for line in lines:
        model.on_line(line)
    return model.status


def test_status_transitions_through_connect_to_ready():
    model = StatusModel()
    status = feed(
        model,
        [
            "[start] executor node node_id=node-1 executors=codex newbro=https://x",
            "[connect] executor node attempt=1 url=wss://x/api/executors/control",
            "[ready] executor node node_id=node-1 executors=codex newbro=https://x",
        ],
    )
    assert status is NodeStatus.READY


def test_status_reflects_disconnect_and_retry():
    model = StatusModel()
    feed(model, ["[ready] executor node node_id=node-1 executors=codex newbro=https://x"])
    model.on_line("[warn] executor node disconnected=ConnectionClosed url=wss://x")
    assert model.status is NodeStatus.DISCONNECTED
    model.on_line("[retry] executor node retrying in 2.0s")
    assert model.status is NodeStatus.RETRYING


def test_connect_failed_warn_stays_connecting():
    model = StatusModel()
    model.on_start()
    model.on_line("[connect] executor node attempt=1 url=wss://x")
    model.on_line("[warn] executor node attempt=1 connect_failed=Timeout url=wss://x")
    assert model.status is NodeStatus.CONNECTING


def test_exit_expected_is_stopped_unexpected_is_error():
    model = StatusModel()
    model.on_start()
    assert model.on_exit(0, expected=True) is NodeStatus.STOPPED
    other = StatusModel()
    other.on_start()
    assert other.on_exit(1, expected=False) is NodeStatus.ERROR


def test_aggregate_prioritizes_error_then_connecting_then_ready():
    assert aggregate_status([NodeStatus.READY, NodeStatus.ERROR]) is NodeStatus.ERROR
    assert aggregate_status([NodeStatus.READY, NodeStatus.CONNECTING]) is NodeStatus.CONNECTING
    assert aggregate_status([NodeStatus.READY, NodeStatus.STOPPED]) is NodeStatus.READY
    assert aggregate_status([NodeStatus.STOPPED, NodeStatus.IDLE]) is NodeStatus.IDLE
    assert aggregate_status([]) is NodeStatus.IDLE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.executors.ui.status'`

- [ ] **Step 3: Write minimal implementation**

Create `src/newbro/executors/ui/status.py`:

```python
from __future__ import annotations

from enum import Enum


class NodeStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    CONNECTING = "connecting"
    READY = "ready"
    DISCONNECTED = "disconnected"
    RETRYING = "retrying"
    ERROR = "error"
    STOPPED = "stopped"


class StatusModel:
    def __init__(self) -> None:
        self.status = NodeStatus.IDLE

    def on_start(self) -> NodeStatus:
        self.status = NodeStatus.STARTING
        return self.status

    def on_line(self, line: str) -> NodeStatus:
        if line.startswith("[start]"):
            self.status = NodeStatus.STARTING
        elif line.startswith("[connect]"):
            self.status = NodeStatus.CONNECTING
        elif line.startswith("[ready]"):
            self.status = NodeStatus.READY
        elif line.startswith("[retry]"):
            self.status = NodeStatus.RETRYING
        elif line.startswith("[warn]") and "disconnected=" in line:
            self.status = NodeStatus.DISCONNECTED
        elif line.startswith("[warn]") and "connect_failed=" in line:
            self.status = NodeStatus.CONNECTING
        return self.status

    def on_exit(self, code: int, *, expected: bool) -> NodeStatus:
        self.status = NodeStatus.STOPPED if expected else NodeStatus.ERROR
        return self.status


_AGGREGATE_PRIORITY = (
    NodeStatus.ERROR,
    NodeStatus.DISCONNECTED,
    NodeStatus.RETRYING,
    NodeStatus.CONNECTING,
    NodeStatus.STARTING,
    NodeStatus.READY,
)


def aggregate_status(statuses: list[NodeStatus]) -> NodeStatus:
    present = set(statuses)
    for candidate in _AGGREGATE_PRIORITY:
        if candidate in present:
            return candidate
    return NodeStatus.IDLE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_status.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/ui/status.py tests/unit/executors/ui/test_status.py
git commit -m "feat(executor-ui): map node output lines to per-profile status"
```

---

### Task 4: NodeProcessController

**Files:**
- Create: `src/newbro/executors/ui/process.py`
- Test: `tests/unit/executors/ui/test_process.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/executors/ui/test_process.py`:

```python
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from newbro.executors.ui.process import NodeProcessController


def _controller(script: str, lines: list[str], exits: list[int]) -> NodeProcessController:
    return NodeProcessController(
        argv=[sys.executable, "-c", script],
        cwd=Path.cwd(),
        on_line=lines.append,
        on_exit=exits.append,
    )


def test_captures_lines_and_exit_code():
    lines: list[str] = []
    exits: list[int] = []
    script = "import sys; print('[start] hello'); print('[ready] go'); sys.exit(0)"
    controller = _controller(script, lines, exits)

    controller.start()
    deadline = time.time() + 10
    while not exits and time.time() < deadline:
        time.sleep(0.05)

    assert "[start] hello" in lines
    assert "[ready] go" in lines
    assert exits == [0]


def test_stop_terminates_a_long_running_process():
    lines: list[str] = []
    exits: list[int] = []
    script = "import time\nprint('[start] up', flush=True)\nwhile True: time.sleep(0.1)"
    controller = _controller(script, lines, exits)

    controller.start()
    deadline = time.time() + 10
    while not lines and time.time() < deadline:
        time.sleep(0.05)
    assert controller.is_running() is True

    controller.stop(timeout=5.0)
    assert controller.is_running() is False
    assert exits  # on_exit fired after stop
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_process.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.executors.ui.process'`

- [ ] **Step 3: Write minimal implementation**

Create `src/newbro/executors/ui/process.py`:

```python
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable


class NodeProcessController:
    """Supervises one `newbro executor run` subprocess for a single profile.

    Emits raw output lines and the final exit code. Does not interpret meaning.
    """

    def __init__(
        self,
        *,
        argv: list[str],
        cwd: Path,
        on_line: Callable[[str], None],
        on_exit: Callable[[int], None],
    ) -> None:
        self._argv = list(argv)
        self._cwd = Path(cwd)
        self._on_line = on_line
        self._on_exit = on_exit
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._proc = subprocess.Popen(
            self._argv,
            cwd=str(self._cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self._on_line(line.rstrip("\n"))
        self._on_exit(proc.wait())

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self, *, timeout: float = 5.0) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self._reader is not None:
            self._reader.join(timeout=timeout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_process.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/ui/process.py tests/unit/executors/ui/test_process.py
git commit -m "feat(executor-ui): supervise node subprocess with line capture and stop"
```

---

### Task 5: ProfileSupervisor

**Files:**
- Create: `src/newbro/executors/ui/supervisor.py`
- Test: `tests/unit/executors/ui/test_supervisor.py`

This task injects a fake controller and the real `StatusModel`, so it tests start/stop/restart, concurrency bookkeeping, aggregate status, and stop-all without spawning processes.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/executors/ui/test_supervisor.py`:

```python
from __future__ import annotations

from pathlib import Path

from newbro.executors.ui.profiles import Profile
from newbro.executors.ui.status import NodeStatus, StatusModel
from newbro.executors.ui.supervisor import ProfileSupervisor


class FakeController:
    instances: list["FakeController"] = []

    def __init__(self, *, argv, cwd, on_line, on_exit):
        self.argv = argv
        self.cwd = cwd
        self.on_line = on_line
        self.on_exit = on_exit
        self.started = False
        self.stopped = False
        FakeController.instances.append(self)

    def start(self):
        self.started = True

    def is_running(self):
        return self.started and not self.stopped

    def stop(self, *, timeout: float = 5.0):
        self.stopped = True


def make_supervisor():
    FakeController.instances = []
    return ProfileSupervisor(
        controller_factory=lambda **kw: FakeController(**kw),
        status_factory=StatusModel,
        build_argv=lambda profile: ["run", profile.node_id],
        cwd=Path.cwd(),
    )


def profile(pid="p1", node="node-1"):
    return Profile(id=pid, label=pid, base_url="https://x", node_id=node, token="t", enabled_executors=["codex"])


def test_start_spawns_controller_and_reports_starting():
    sup = make_supervisor()
    sup.start(profile())
    assert sup.active_ids() == {"p1"}
    assert sup.status_of("p1") is NodeStatus.STARTING
    assert FakeController.instances[0].argv == ["run", "node-1"]


def test_lines_drive_status_and_ready_aggregates():
    sup = make_supervisor()
    sup.start(profile())
    controller = FakeController.instances[0]
    controller.on_line("[ready] executor node node_id=node-1 executors=codex newbro=https://x")
    assert sup.status_of("p1") is NodeStatus.READY
    assert sup.aggregate_status() is NodeStatus.READY


def test_user_stop_marks_stopped_and_drops_profile():
    sup = make_supervisor()
    sup.start(profile())
    controller = FakeController.instances[0]
    sup.stop("p1")
    controller.on_exit(0)  # exit callback fires after terminate
    assert controller.stopped is True
    assert sup.active_ids() == set()


def test_unexpected_exit_marks_error_and_keeps_record():
    sup = make_supervisor()
    sup.start(profile())
    controller = FakeController.instances[0]
    controller.on_exit(1)
    assert sup.status_of("p1") is NodeStatus.ERROR
    assert sup.active_ids() == {"p1"}


def test_stop_all_stops_every_controller():
    sup = make_supervisor()
    sup.start(profile("p1", "node-1"))
    sup.start(profile("p2", "node-2"))
    sup.stop_all()
    assert all(c.stopped for c in FakeController.instances)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_supervisor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.executors.ui.supervisor'`

- [ ] **Step 3: Write minimal implementation**

Create `src/newbro/executors/ui/supervisor.py`:

```python
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from newbro.executors.ui.profiles import Profile
from newbro.executors.ui.status import NodeStatus, StatusModel, aggregate_status


@dataclass(slots=True)
class _Record:
    profile: Profile
    controller: Any
    status_model: StatusModel
    expected_stop: bool = False


class ProfileSupervisor:
    """Owns one controller + status model per active profile.

    The node subprocess owns its own reconnection, so the supervisor does not
    add a process-restart loop: an unexpected exit becomes ERROR and is left for
    the user to act on; a user-requested stop becomes STOPPED.
    """

    def __init__(
        self,
        *,
        controller_factory: Callable[..., Any],
        status_factory: Callable[[], StatusModel],
        build_argv: Callable[[Profile], list[str]],
        cwd: Path,
    ) -> None:
        self._controller_factory = controller_factory
        self._status_factory = status_factory
        self._build_argv = build_argv
        self._cwd = cwd
        self._records: dict[str, _Record] = {}
        self._lock = threading.RLock()

    def start(self, profile: Profile) -> None:
        with self._lock:
            if profile.id in self._records and self._records[profile.id].controller.is_running():
                return
            status_model = self._status_factory()
            status_model.on_start()
            record = _Record(profile=profile, controller=None, status_model=status_model)
            controller = self._controller_factory(
                argv=self._build_argv(profile),
                cwd=self._cwd,
                on_line=lambda line, pid=profile.id: self._on_line(pid, line),
                on_exit=lambda code, pid=profile.id: self._on_exit(pid, code),
            )
            record.controller = controller
            self._records[profile.id] = record
            controller.start()

    def stop(self, profile_id: str) -> None:
        with self._lock:
            record = self._records.get(profile_id)
            if record is None:
                return
            record.expected_stop = True
            controller = record.controller
        controller.stop()

    def restart(self, profile: Profile) -> None:
        self.stop(profile.id)
        self.start(profile)

    def _on_line(self, profile_id: str, line: str) -> None:
        with self._lock:
            record = self._records.get(profile_id)
            if record is not None:
                record.status_model.on_line(line)

    def _on_exit(self, profile_id: str, code: int) -> None:
        with self._lock:
            record = self._records.get(profile_id)
            if record is None:
                return
            if record.expected_stop:
                record.status_model.on_exit(code, expected=True)
                del self._records[profile_id]
            else:
                record.status_model.on_exit(code, expected=False)

    def status_of(self, profile_id: str) -> NodeStatus:
        with self._lock:
            record = self._records.get(profile_id)
            return record.status_model.status if record else NodeStatus.IDLE

    def aggregate_status(self) -> NodeStatus:
        with self._lock:
            return aggregate_status([record.status_model.status for record in self._records.values()])

    def active_ids(self) -> set[str]:
        with self._lock:
            return set(self._records)

    def stop_all(self) -> None:
        with self._lock:
            controllers = [(record_id, record.controller) for record_id, record in self._records.items()]
            for _, record in self._records.items():
                record.expected_stop = True
        for _, controller in controllers:
            controller.stop()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_supervisor.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/ui/supervisor.py tests/unit/executors/ui/test_supervisor.py
git commit -m "feat(executor-ui): supervise concurrent profiles with aggregate status"
```

---

### Task 6: LoginItem

**Files:**
- Create: `src/newbro/executors/ui/login_item.py`
- Test: `tests/unit/executors/ui/test_login_item.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/executors/ui/test_login_item.py`:

```python
from __future__ import annotations

import plistlib
from pathlib import Path

from newbro.executors.ui.login_item import (
    LOGIN_ITEM_LABEL,
    LoginItem,
    render_login_item_plist,
)


def test_render_plist_contains_label_and_app_path():
    text = render_login_item_plist(app_path=Path("/Applications/Newbro Executor.app"))
    parsed = plistlib.loads(text.encode("utf-8"))
    assert parsed["Label"] == LOGIN_ITEM_LABEL
    assert parsed["RunAtLoad"] is True
    assert "/Applications/Newbro Executor.app" in parsed["ProgramArguments"]


def test_install_then_remove(tmp_path):
    plist_path = tmp_path / f"{LOGIN_ITEM_LABEL}.plist"
    item = LoginItem(plist_path=plist_path, app_path=Path("/Applications/Newbro Executor.app"))

    assert item.is_installed() is False
    item.install()
    assert item.is_installed() is True
    assert plist_path.exists()

    item.remove()
    assert item.is_installed() is False
    assert not plist_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_login_item.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newbro.executors.ui.login_item'`

- [ ] **Step 3: Write minimal implementation**

Create `src/newbro/executors/ui/login_item.py`:

```python
from __future__ import annotations

import plistlib
from pathlib import Path

LOGIN_ITEM_LABEL = "com.newbro.executor-ui"

_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def login_item_plist_path() -> Path:
    return _LAUNCH_AGENTS_DIR / f"{LOGIN_ITEM_LABEL}.plist"


def render_login_item_plist(*, app_path: Path) -> str:
    payload = {
        "Label": LOGIN_ITEM_LABEL,
        "ProgramArguments": ["/usr/bin/open", str(app_path)],
        "RunAtLoad": True,
    }
    return plistlib.dumps(payload).decode("utf-8")


class LoginItem:
    def __init__(self, *, plist_path: Path | None = None, app_path: Path) -> None:
        self._plist_path = plist_path or login_item_plist_path()
        self._app_path = app_path

    def is_installed(self) -> bool:
        return self._plist_path.exists()

    def install(self) -> None:
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)
        self._plist_path.write_text(render_login_item_plist(app_path=self._app_path), encoding="utf-8")

    def remove(self) -> None:
        self._plist_path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui/test_login_item.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/ui/login_item.py tests/unit/executors/ui/test_login_item.py
git commit -m "feat(executor-ui): add login-item LaunchAgent install/remove"
```

---

### Task 7: rumps MenuBarApp shell and `newbro executor ui` command

The rumps app is a thin UI shell with no business logic, so it is verified manually (Step 6), not unit-tested. The CLI command lazy-imports it so installs without the `macos-ui` extra still load the CLI.

**Files:**
- Create: `src/newbro/executors/ui/app.py`
- Create: `src/newbro/cli/commands/executor_ui.py`
- Modify: `src/newbro/cli/parser.py:84-85`
- Modify: `src/newbro/cli/dispatch.py:74-79`

- [ ] **Step 1: Add the `ui` subparser**

In `src/newbro/cli/parser.py`, immediately after the existing line (currently line 85):

```python
    executor_subparsers.add_parser("setup", help="Interactively configure the detached executor node.")
```

add:

```python
    executor_subparsers.add_parser(
        "ui",
        help="Launch the macOS menu-bar executor app (requires the 'macos-ui' extra).",
    )
```

- [ ] **Step 2: Route the `ui` command in dispatch**

In `src/newbro/cli/dispatch.py`, replace the `cmd_executor` function (lines 74-79) with:

```python
def cmd_executor(args: Any, app: Any) -> int:
    if args.executor_command == "setup":
        return setup_command.run_executor_setup(args, cli_factories.setup_context(app), cli_factories.setup_callbacks(app))
    if args.executor_command == "run":
        return run_command.run_executor(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))
    if args.executor_command == "ui":
        from newbro.cli.commands import executor_ui as executor_ui_command

        return executor_ui_command.run_executor_ui()
    raise app.CliError(f"Unknown executor command: {args.executor_command}")
```

- [ ] **Step 3: Create the launcher command with a clear missing-extra message**

Create `src/newbro/cli/commands/executor_ui.py`:

```python
from __future__ import annotations

import sys


def run_executor_ui() -> int:
    try:
        from newbro.executors.ui.app import run_menu_bar_app
    except ImportError as exc:
        print(
            "The macOS menu-bar executor app requires the 'macos-ui' extra.\n"
            "Install it with: pip install 'newbro-cli[macos-ui]'",
            file=sys.stderr,
        )
        print(f"(import error: {exc})", file=sys.stderr)
        return 1
    return run_menu_bar_app()
```

- [ ] **Step 4: Create the rumps app shell**

Create `src/newbro/executors/ui/app.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import rumps

from newbro.cli.command_specs import executor_node_command
from newbro.executors.ui.login_item import LoginItem, login_item_plist_path
from newbro.executors.ui.process import NodeProcessController
from newbro.executors.ui.profiles import (
    Profile,
    ProfileStore,
    conflicting_profile_ids,
    parse_connect_command,
)
from newbro.executors.ui.status import NodeStatus
from newbro.executors.ui.supervisor import ProfileSupervisor

_STATUS_GLYPH = {
    NodeStatus.READY: "●",        # ●
    NodeStatus.CONNECTING: "◌",   # ◌
    NodeStatus.STARTING: "◌",
    NodeStatus.RETRYING: "◌",
    NodeStatus.DISCONNECTED: "⚠",  # ⚠
    NodeStatus.ERROR: "✕",        # ✕
    NodeStatus.STOPPED: "○",      # ○
    NodeStatus.IDLE: "○",
}


def _build_argv(profile: Profile) -> list[str]:
    return executor_node_command(
        Path(sys.executable),
        base_url=profile.base_url,
        node_id=profile.node_id,
        token=profile.token,
        enabled_executors=profile.enabled_executors or None,
    )


class MenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Newbro Executor", quit_button=None)
        self._store = ProfileStore()
        self._supervisor = ProfileSupervisor(
            controller_factory=lambda **kw: NodeProcessController(**kw),
            status_factory=__import__("newbro.executors.ui.status", fromlist=["StatusModel"]).StatusModel,
            build_argv=_build_argv,
            cwd=Path.home(),
        )
        self._login_item = LoginItem(app_path=_app_bundle_path())
        self._profiles = self._store.load()
        self._refresh_timer = rumps.Timer(self._tick, 1.0)
        self._refresh_timer.start()
        self._autostart()
        self._rebuild_menu()

    def _autostart(self) -> None:
        for profile in self._profiles:
            if profile.auto_activate and _is_complete(profile):
                self._supervisor.start(profile)

    def _tick(self, _timer: rumps.Timer) -> None:
        self.title = _STATUS_GLYPH[self._supervisor.aggregate_status()]
        self._rebuild_menu()

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        conflicts = conflicting_profile_ids(self._profiles)
        for profile in self._profiles:
            status = self._supervisor.status_of(profile.id)
            label = f"{profile.label} · {_STATUS_GLYPH[status]} {status.value}"
            if profile.id in conflicts:
                label += "  (duplicate node id)"
            item = rumps.MenuItem(label)
            running = profile.id in self._supervisor.active_ids() and status not in (
                NodeStatus.STOPPED,
                NodeStatus.ERROR,
            )
            if running:
                item.add(rumps.MenuItem("Stop", callback=self._make_stop(profile)))
                item.add(rumps.MenuItem("Restart", callback=self._make_restart(profile)))
            else:
                item.add(rumps.MenuItem("Start", callback=self._make_start(profile)))
            self.menu.add(item)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Paste connect command…", callback=self._paste_connect_command))
        login = rumps.MenuItem("Launch at login", callback=self._toggle_login_item)
        login.state = 1 if login_item_plist_path().exists() else 0
        self.menu.add(login)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit", callback=self._quit))

    def _make_start(self, profile: Profile):
        def _cb(_sender):
            if not _is_complete(profile):
                rumps.alert(
                    "Executor setup needed",
                    "Run `newbro executor setup` in a terminal to configure executor commands, then return here.",
                )
                return
            self._supervisor.start(profile)
        return _cb

    def _make_stop(self, profile: Profile):
        return lambda _sender: self._supervisor.stop(profile.id)

    def _make_restart(self, profile: Profile):
        return lambda _sender: self._supervisor.restart(profile)

    def _paste_connect_command(self, _sender) -> None:
        response = rumps.Window(
            "Paste the connect command from the Newbro web UI:",
            "Add / update profile",
            ok="Save",
            cancel="Cancel",
        ).run()
        if not response.clicked:
            return
        try:
            fields = parse_connect_command(response.text)
        except ValueError as exc:
            rumps.alert("Invalid connect command", str(exc))
            return
        existing = next((p for p in self._profiles if p.node_id == fields.node_id and p.base_url == fields.base_url), None)
        if existing is not None:
            existing.token = fields.token
            existing.enabled_executors = fields.enabled_executors
        else:
            self._profiles.append(
                Profile(
                    id=f"profile-{uuid4().hex[:8]}",
                    label=fields.base_url,
                    base_url=fields.base_url,
                    node_id=fields.node_id,
                    token=fields.token,
                    enabled_executors=fields.enabled_executors,
                )
            )
        self._store.save(self._profiles)
        self._rebuild_menu()

    def _toggle_login_item(self, sender) -> None:
        if login_item_plist_path().exists():
            self._login_item.remove()
            sender.state = 0
        else:
            self._login_item.install()
            sender.state = 1

    def _quit(self, _sender) -> None:
        self._supervisor.stop_all()
        rumps.quit_application()


def _is_complete(profile: Profile) -> bool:
    return bool(profile.base_url and profile.node_id and profile.token and profile.enabled_executors)


def _app_bundle_path() -> Path:
    return Path("/Applications/Newbro Executor.app")


def run_menu_bar_app() -> int:
    MenuBarApp().run()
    return 0
```

- [ ] **Step 5: Verify the CLI loads without the extra installed**

Run: `.venv/bin/python -m newbro executor ui`
Expected (when `rumps` is NOT installed): prints the "requires the 'macos-ui' extra" message and exits non-zero — **not** a traceback. (If `rumps` is already installed, the app launches instead; quit it with the menu's Quit.)

- [ ] **Step 6: Manual verification (once `macos-ui` extra is installed — see Task 8)**

After Task 8 installs `rumps`, run `.venv/bin/python -m newbro executor ui` and confirm:
- A menu-bar glyph appears (no Dock icon).
- "Paste connect command…" accepts a `newbro executor run --base-url … --node-id … --token …` string and adds a profile that appears in the menu.
- Start launches the node; status moves to ● ready once connected; Stop returns it to ○.
- "Launch at login" toggles `~/Library/LaunchAgents/com.newbro.executor-ui.plist`.
- Quit stops all node subprocesses (verify with `pgrep -f newbro.executors.node` returning nothing).

- [ ] **Step 7: Commit**

```bash
git add src/newbro/executors/ui/app.py src/newbro/cli/commands/executor_ui.py src/newbro/cli/parser.py src/newbro/cli/dispatch.py
git commit -m "feat(executor-ui): add rumps menu-bar app and 'newbro executor ui' command"
```

---

### Task 8: Optional `macos-ui` extra and py2app packaging

**Files:**
- Modify: `pyproject.toml:25-35`
- Create: `packaging/menubar/setup.py`
- Create: `packaging/menubar/README.md`

- [ ] **Step 1: Add optional extras to pyproject**

In `pyproject.toml`, in the `[project.optional-dependencies]` table (after the `release` entry, around line 35), add:

```toml
macos-ui = [
  "rumps>=0.4,<1",
]
macos-ui-build = [
  "rumps>=0.4,<1",
  "py2app>=0.28,<1",
]
```

- [ ] **Step 2: Verify the extra installs and the app launches**

Run: `.venv/bin/python -m pip install -e '.[macos-ui]'`
Then run: `.venv/bin/python -m newbro executor ui`
Expected: the menu-bar app launches (a glyph appears top-right). Quit it via the menu's Quit.

- [ ] **Step 3: Create the py2app build script**

Create `packaging/menubar/setup.py`:

```python
"""py2app build script for the Newbro Executor menu-bar app.

Build from the repo root with the macos-ui-build extra installed:

    python packaging/menubar/setup.py py2app

Produces `dist/Newbro Executor.app`.
"""
from __future__ import annotations

from pathlib import Path

from setuptools import setup

_ENTRY = Path(__file__).parent / "main.py"

setup(
    app=[str(_ENTRY)],
    name="Newbro Executor",
    options={
        "py2app": {
            "argv_emulation": False,
            "plist": {
                "CFBundleIdentifier": "com.newbro.executor-ui",
                "CFBundleName": "Newbro Executor",
                "LSUIElement": True,  # menu-bar only: no Dock icon
            },
            "packages": ["newbro", "rumps"],
        }
    },
    setup_requires=["py2app>=0.28,<1"],
)
```

- [ ] **Step 4: Create the bundle entry point**

Create `packaging/menubar/main.py`:

```python
from newbro.executors.ui.app import run_menu_bar_app

if __name__ == "__main__":
    run_menu_bar_app()
```

- [ ] **Step 5: Create packaging README**

Create `packaging/menubar/README.md`:

```markdown
# Newbro Executor menu-bar app (macOS)

Build a double-clickable `.app`:

```bash
python -m pip install -e '.[macos-ui-build]'
python packaging/menubar/setup.py py2app
open "dist/Newbro Executor.app"
```

The app is menu-bar only (`LSUIElement`), supervises executor node profiles
stored in `~/.newbro/menubar.json`, and spawns one `python -m
newbro.executors.node` subprocess per active profile.

Deeper executor runtime config (codex/acpx binary paths, Whisper/audio) is
machine-level and is configured separately with `newbro executor setup`.
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml packaging/menubar/setup.py packaging/menubar/main.py packaging/menubar/README.md
git commit -m "build(executor-ui): add macos-ui extra and py2app packaging"
```

---

### Task 9: Documentation and memory note

**Files:**
- Modify: `docs/architecture/executors.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Add an executor-node UI note to the architecture doc**

In `docs/architecture/executors.md`, in the "Executor-node note" bullet list (after the bullet describing `newbro executor run --base-url ...`), add:

```markdown
- a macOS menu-bar app (`newbro executor ui`, packaged via the `macos-ui`
  extra) supervises multiple executor-node profiles stored in
  `~/.newbro/menubar.json`. Each profile carries its own base URL, node id,
  token, and enabled executor families, and runs as an independent
  `newbro executor run` subprocess; several profiles can run concurrently. The
  app only edits connection profiles — deeper executor runtime config stays
  owned by `newbro executor setup`.
```

- [ ] **Step 2: Append a memory note**

In `docs/memories.md`, append a short factual line under the most recent section:

```markdown
- A macOS menu-bar app (`newbro executor ui`, `macos-ui` extra) supervises
  multiple concurrent executor-node profiles from `~/.newbro/menubar.json`,
  spawning one `newbro executor run` subprocess per active profile. It is a
  supervisor + connection-profile editor only; `newbro executor setup` still
  owns executor binary/audio config.
```

- [ ] **Step 3: Run the full unit suite for the new package**

Run: `.venv/bin/python -m pytest tests/unit/executors/ui -v`
Expected: PASS (all tests across profiles, status, process, supervisor, login_item)

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/executors.md docs/memories.md
git commit -m "docs(executor-ui): document the macOS menu-bar executor app"
```

---

## Self-Review

**Spec coverage:**
- Multiple profiles, each an executor instance (base_url/node_id/token/enabled_executors) → Task 1 (`Profile`), Task 7 (per-profile menu).
- Several profiles concurrent, one subprocess each → Task 5 (`ProfileSupervisor`), Task 4 (`NodeProcessController`), Task 7 (`_build_argv` via `executor_node_command`).
- Run/stop/restart + live status → Tasks 3, 4, 5, 7.
- Edit credentials / paste connect command → Task 2 (`parse_connect_command`), Task 7 (paste flow + save).
- Menu-bar only, auto-connect on launch, login item → Task 6 (`LoginItem`), Task 7 (`LSUIElement` via Task 8 plist, `_autostart`, login toggle).
- Subprocess via `newbro executor run` contract → Task 7 reuses `command_specs.executor_node_command`.
- No-TTY: no interactive setup from the app; clear guidance message → Task 7 (`_make_start` alert).
- Deep runtime config stays in `newbro executor setup` → not written by the app (Task 1 store writes only `menubar.json`); documented Task 9.
- Duplicate node_id warning → Task 2 (`conflicting_profile_ids`), Task 7 (menu label).
- macOS-only deps as optional extra → Task 8.
- `newbro executor ui` dev command → Task 7.
- py2app `.app` bundle → Task 8.
- Tests for StatusModel / NodeProcessController / ProfileSupervisor / ProfileStore / LoginItem → Tasks 1–6.

**Deviations from spec (intentional refinements):**
- No process-restart backoff loop: the node subprocess already owns reconnection (emits `[retry]`/`[warn]` while staying alive), so the UI surfaces `error` on fatal exit instead of looping. Captured in `ProfileSupervisor` docstring and Task 5.
- Completeness check is a lightweight per-profile field check (`_is_complete`) plus terminal guidance, rather than constructing the heavy `executor_runtime_config_complete` setup-callback graph from the UI. This keeps the UI decoupled from the setup callback infrastructure while still preventing a broken launch.
- Aggregate icon prioritizes the most concerning state (error > connecting > ready > idle) rather than "any ready wins," so an in-progress profile is not hidden behind a ready one.

**Placeholder scan:** none — every step contains concrete code or exact commands.

**Type consistency:** `Profile`, `ProfileStore(path=…)`, `ConnectCommandFields`, `parse_connect_command`, `conflicting_profile_ids`, `NodeStatus`, `StatusModel.on_start/on_line/on_exit(expected=…)`, `aggregate_status`, `NodeProcessController(argv=,cwd=,on_line=,on_exit=)`, `ProfileSupervisor(controller_factory=,status_factory=,build_argv=,cwd=)` and its `start/stop/restart/status_of/aggregate_status/active_ids/stop_all`, `LoginItem(plist_path=,app_path=)`, `executor_node_command(Path, base_url=…, node_id=…, token=…, enabled_executors=…)` are used consistently across tasks and match the existing `command_specs` signature.
