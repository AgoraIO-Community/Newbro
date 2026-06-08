# Skill Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-bro Codex skill picker to the active-session composer (desktop + mobile) that discovers installed skills and activates the chosen skill for a turn.

**Architecture:** Skills are discovered once at executor start via the Codex app-server `skills/list`, cached on the executor, and shipped to the backend through the existing `register_node` capability payload. The chosen skill rides a turn through the same metadata carriers as `plan_mode`, and the Codex adapter activates it with a `{type:"skill"}` turn input item + `$name` marker. The web picker reads the per-bro catalog from the session snapshot.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Pytest; React + Vite + TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-06-08-skill-picker-design.md`
**Fixture:** `docs/protocol/fixtures/codex-skills-list-sample.json`

**Conventions in this repo (read before starting):**
- Run backend tests with `.venv/bin/python -m pytest`.
- Run web tests from `clients/web` with `npm run test -- <file>` (Vitest). Avoid the flaky full `src/__tests__/App.test.tsx`; run targeted files.
- `plan_mode` is the exact pattern this feature mirrors — when unsure, grep `plan_mode` and follow it.

---

## File Structure

**Backend — new/modified:**
- `src/newbro/executors/core/capabilities.py` — add `ExecutorSkill` + `skills` field to `ExecutorCapabilities`.
- `src/newbro/protocol/executor_node.py` — add `ExecutorSkill` import + `skills` to wire model `ExecutorNodeExecutor`; add optional `ExecutorSkillRef` carried in instruction/command metadata (as plain dict).
- `src/newbro/executors/adapters/codex/skills.py` *(new)* — `parse_skills_list(result)` mapping `skills/list` → `list[ExecutorSkill]`.
- `src/newbro/executors/adapters/codex/client.py` — `skills_list()` method; `turn_start(skill=...)` activation.
- `src/newbro/executors/adapters/codex/executor.py` — load-once skill cache in `refresh_capabilities`; read `skill` from metadata at the 3 turn sites; `_turn_start_for_request(skill=...)`.
- `src/newbro/executors/node/service.py` — copy `skills` in `_descriptor`.
- `src/newbro/runtime/models.py` — add `skills` to `BroExecutorCapabilitySummary`.
- `src/newbro/runtime/session.py` — project `skills` into `BroExecutorCapabilitySummary`; thread `skill` through `submit_executor_text_instruction`.
- `src/newbro/runtime/direct_executor.py` — thread `skill`; validate-before-write vanished-skill contract.
- `src/newbro/runtime/direct_turn_starter.py` — write `skill` into `outbound_metadata`.
- `src/newbro/api/routes/executor_text.py` — accept `skill` in the request, pass through.

**Web — new/modified:**
- `clients/web/src/types.ts` — `ExecutorSkill` type; add `skills` to `BroExecutorCapabilitySummary`.
- `clients/web/src/lib/session-client.ts` — `submitExecutorTextInstruction({ skill })`.
- `clients/web/src/components/newbro/SkillPicker.tsx` *(new)* — shared catalog hook + desktop popover + mobile sheet, ported from the prototype.
- `clients/web/src/ArtboardShell.tsx` — wire the picker into `DesktopComposerBar` + mobile composer; render the skill pill.

---

## Phase A — Shared models

### Task 1: `ExecutorSkill` model + executor capabilities field

**Files:**
- Modify: `src/newbro/executors/core/capabilities.py`
- Test: `tests/unit/executors/test_executor_skill_model.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/test_executor_skill_model.py
from newbro.executors.core.capabilities import ExecutorCapabilities, ExecutorSkill


def test_executor_skill_defaults():
    skill = ExecutorSkill(name="doc", display_name="Word Docs", description="Edit docx", path="/x/SKILL.md")
    assert skill.enabled is True
    assert skill.hint is None


def test_capabilities_default_skills_empty():
    caps = ExecutorCapabilities(executor_type="codex")
    assert caps.skills == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_executor_skill_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'ExecutorSkill'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/newbro/executors/core/capabilities.py
from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutorSkill(BaseModel):
    name: str
    display_name: str
    description: str = ""
    hint: str | None = None
    path: str
    enabled: bool = True


class ExecutorCapabilities(BaseModel):
    executor_type: str
    supports_resume: bool = False
    supports_follow_up: bool = False
    supports_audio_instruction: bool = False
    supports_thread_list: bool = False
    supports_pause: bool = False
    supports_cancel: bool = True
    supports_setup: bool = False
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
    skills: list[ExecutorSkill] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/test_executor_skill_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/core/capabilities.py tests/unit/executors/test_executor_skill_model.py
git commit -m "feat: add ExecutorSkill model and capabilities.skills field"
```

---

### Task 2: Add `skills` to the wire model `ExecutorNodeExecutor`

**Files:**
- Modify: `src/newbro/protocol/executor_node.py:10-20`
- Test: `tests/unit/protocol/test_executor_node_skills.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/protocol/test_executor_node_skills.py
from newbro.protocol.executor_node import ExecutorNodeExecutor
from newbro.executors.core.capabilities import ExecutorSkill


def test_wire_executor_round_trips_skills():
    wire = ExecutorNodeExecutor(
        executor_type="codex",
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")],
    )
    dumped = wire.model_dump()
    restored = ExecutorNodeExecutor.model_validate(dumped)
    assert restored.skills[0].name == "doc"


def test_wire_executor_defaults_empty_skills():
    assert ExecutorNodeExecutor(executor_type="codex").skills == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/protocol/test_executor_node_skills.py -v`
Expected: FAIL (`skills` not a field / unexpected keyword)

- [ ] **Step 3: Write minimal implementation**

In `src/newbro/protocol/executor_node.py`, add the import near the top (after existing imports):

```python
from newbro.executors.core.capabilities import ExecutorSkill
```

Then add the field to `ExecutorNodeExecutor` (after `availability_reason`):

```python
class ExecutorNodeExecutor(BaseModel):
    executor_type: str
    supports_resume: bool = False
    supports_follow_up: bool = False
    supports_audio_instruction: bool = False
    supports_thread_list: bool = False
    supports_pause: bool = False
    supports_cancel: bool = True
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
    skills: list[ExecutorSkill] = Field(default_factory=list)
```

> If importing from `executors.core` into `protocol` creates a circular import, instead duplicate a minimal `ExecutorSkill` in `protocol/executor_node.py` and have `capabilities.ExecutorSkill` re-export it. Run the test in Step 4 — if it passes, the import is fine; keep it.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/protocol/test_executor_node_skills.py -v`
Expected: PASS

- [ ] **Step 5: Run the broader protocol/import smoke to catch cycles**

Run: `.venv/bin/python -c "import newbro.protocol; import newbro.executors.adapters.codex.executor"`
Expected: no output (no ImportError)

- [ ] **Step 6: Commit**

```bash
git add src/newbro/protocol/executor_node.py tests/unit/protocol/test_executor_node_skills.py
git commit -m "feat: carry skills on the ExecutorNodeExecutor wire model"
```

---

### Task 3: Add `skills` to `BroExecutorCapabilitySummary`

**Files:**
- Modify: `src/newbro/runtime/models.py:57-63`
- Test: `tests/unit/runtime/test_bro_capability_summary_skills.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/runtime/test_bro_capability_summary_skills.py
from newbro.runtime.models import BroExecutorCapabilitySummary
from newbro.executors.core.capabilities import ExecutorSkill


def test_summary_defaults_empty_skills():
    assert BroExecutorCapabilitySummary().skills == []


def test_summary_carries_skills():
    summary = BroExecutorCapabilitySummary(
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")]
    )
    assert summary.skills[0].display_name == "Word Docs"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_capability_summary_skills.py -v`
Expected: FAIL (unexpected keyword `skills`)

- [ ] **Step 3: Write minimal implementation**

In `src/newbro/runtime/models.py`, add the import (near other imports) and the field:

```python
from newbro.executors.core.capabilities import ExecutorSkill
```

```python
class BroExecutorCapabilitySummary(BaseModel):
    version: str | None = None
    minimum_version: str | None = None
    availability_reason: str | None = None
    supports_thread_list: bool = False
    supports_audio_instruction: bool = False
    skills: list[ExecutorSkill] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_capability_summary_skills.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newbro/runtime/models.py tests/unit/runtime/test_bro_capability_summary_skills.py
git commit -m "feat: carry skills on BroExecutorCapabilitySummary"
```

---

## Phase B — Discovery

### Task 4: `parse_skills_list` mapping against the captured fixture

**Files:**
- Create: `src/newbro/executors/adapters/codex/skills.py`
- Test: `tests/unit/executors/codex/test_parse_skills_list.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/codex/test_parse_skills_list.py
import json
from pathlib import Path

from newbro.executors.adapters.codex.skills import parse_skills_list

FIXTURE = Path("docs/protocol/fixtures/codex-skills-list-sample.json")


def _result():
    return json.loads(FIXTURE.read_text())


def test_parses_all_skills_flattened():
    skills = parse_skills_list(_result())
    names = {s.name for s in skills}
    assert {"agent-browser", "cc-design", "doc", "openai-docs", "skill-creator"} <= names


def test_display_name_prefers_interface_then_name():
    skills = {s.name: s for s in parse_skills_list(_result())}
    assert skills["doc"].display_name == "Word Docs"          # interface.displayName
    assert skills["agent-browser"].display_name == "agent-browser"  # falls back to name


def test_description_prefers_short_then_toplevel_then_truncated():
    skills = {s.name: s for s in parse_skills_list(_result())}
    assert skills["doc"].description == "Edit and review docx files"      # interface.shortDescription
    assert skills["skill-creator"].description == "Create or update a skill"  # top-level shortDescription
    assert len(skills["agent-browser"].description) <= 160                 # truncated long description


def test_hint_from_default_prompt():
    skills = {s.name: s for s in parse_skills_list(_result())}
    assert skills["cc-design"].hint and skills["cc-design"].hint.startswith("Use $cc-design")
    assert skills["agent-browser"].hint is None


def test_path_always_present():
    assert all(s.path for s in parse_skills_list(_result()))


def test_dedupe_by_name_and_path():
    result = _result()
    # duplicate the cwd group; deduped output must not double-count
    result["data"].append(dict(result["data"][0]))
    skills = parse_skills_list(result)
    assert len(skills) == len({(s.name, s.path) for s in skills})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_parse_skills_list.py -v`
Expected: FAIL (`ModuleNotFoundError: ...codex.skills`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/newbro/executors/adapters/codex/skills.py
from __future__ import annotations

from typing import Any

from newbro.executors.core.capabilities import ExecutorSkill

_DESCRIPTION_CAP = 160


def _coerce_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _project_skill(raw: dict[str, Any]) -> ExecutorSkill | None:
    name = _coerce_str(raw.get("name"))
    path = _coerce_str(raw.get("path"))
    if name is None or path is None:
        return None
    interface = raw.get("interface") if isinstance(raw.get("interface"), dict) else {}
    display_name = _coerce_str(interface.get("displayName")) or name
    short = _coerce_str(interface.get("shortDescription")) or _coerce_str(raw.get("shortDescription"))
    if short is not None:
        description = short
    else:
        long_desc = _coerce_str(raw.get("description")) or ""
        description = long_desc[:_DESCRIPTION_CAP]
    hint = _coerce_str(interface.get("defaultPrompt"))
    enabled = raw.get("enabled") is not False
    return ExecutorSkill(
        name=name,
        display_name=display_name,
        description=description,
        hint=hint,
        path=path,
        enabled=enabled,
    )


def parse_skills_list(result: dict[str, Any]) -> list[ExecutorSkill]:
    """Flatten a codex app-server `skills/list` result into deduped ExecutorSkills."""
    skills: list[ExecutorSkill] = []
    seen: set[tuple[str, str]] = set()
    for group in result.get("data", []) or []:
        if not isinstance(group, dict):
            continue
        for raw in group.get("skills", []) or []:
            if not isinstance(raw, dict):
                continue
            skill = _project_skill(raw)
            if skill is None:
                continue
            key = (skill.name, skill.path)
            if key in seen:
                continue
            seen.add(key)
            skills.append(skill)
    return skills
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_parse_skills_list.py -v`
Expected: PASS (all 6)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/codex/skills.py tests/unit/executors/codex/test_parse_skills_list.py
git commit -m "feat: parse codex skills/list into ExecutorSkill catalog"
```

---

### Task 5: `CodexAppServerClient.skills_list` JSON-RPC method

**Files:**
- Modify: `src/newbro/executors/adapters/codex/client.py` (add method after `collaboration_mode_list`, ~line 162)
- Test: `tests/unit/executors/codex/test_client_skills_list.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/codex/test_client_skills_list.py
import pytest

from newbro.executors.adapters.codex.client import CodexAppServerClient


class FakePeer:
    def __init__(self):
        self.calls = []

    async def request(self, method, params=None):
        self.calls.append((method, params))
        return {"data": []}


@pytest.mark.asyncio
async def test_skills_list_sends_cwds_and_force_reload():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    result = await client.skills_list(cwds=["/repo"], force_reload=True)
    assert peer.calls == [("skills/list", {"cwds": ["/repo"], "forceReload": True})]
    assert result == {"data": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_client_skills_list.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'skills_list'`)

- [ ] **Step 3: Write minimal implementation**

Add to `CodexAppServerClient` in `client.py` (after `collaboration_mode_list`):

```python
    async def skills_list(
        self,
        *,
        cwds: list[str],
        force_reload: bool = False,
    ) -> dict[str, object]:
        result = await self._peer.request(
            "skills/list",
            {"cwds": cwds, "forceReload": force_reload},
        )
        return _as_dict(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_client_skills_list.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/codex/client.py tests/unit/executors/codex/test_client_skills_list.py
git commit -m "feat: add codex client skills/list method"
```

---

### Task 6: Load skills once at executor start, cache on capabilities

**Files:**
- Modify: `src/newbro/executors/adapters/codex/executor.py` (`refresh_capabilities`, ~line 85; add helper)
- Test: `tests/unit/executors/codex/test_executor_loads_skills.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/codex/test_executor_loads_skills.py
import json
from pathlib import Path

import pytest

from newbro.executors.adapters.codex.executor import CodexExecutor

FIXTURE = json.loads(Path("docs/protocol/fixtures/codex-skills-list-sample.json").read_text())


@pytest.mark.asyncio
async def test_refresh_capabilities_loads_and_caches_skills(monkeypatch):
    executor = CodexExecutor(command="codex")

    async def fake_load():
        return FIXTURE

    calls = {"n": 0}

    async def counting_load():
        calls["n"] += 1
        return FIXTURE

    # Probe must report a supported version so skills are loaded.
    from newbro.executors.adapters.codex import probe as probe_mod

    monkeypatch.setattr(
        probe_mod, "probe_codex_command",
        lambda command: probe_mod.CodexProbeResult(path="codex", version="0.137.0", ok=True),
    )
    monkeypatch.setattr(executor, "_load_skills", counting_load)

    caps = await executor.refresh_capabilities()
    assert any(s.name == "doc" for s in caps.skills)

    # Second refresh reuses the cache (load called once).
    await executor.refresh_capabilities()
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_skills_empty_when_load_fails(monkeypatch):
    executor = CodexExecutor(command="codex")
    from newbro.executors.adapters.codex import probe as probe_mod

    monkeypatch.setattr(
        probe_mod, "probe_codex_command",
        lambda command: probe_mod.CodexProbeResult(path="codex", version="0.137.0", ok=True),
    )

    async def boom():
        raise RuntimeError("app-server down")

    monkeypatch.setattr(executor, "_load_skills", boom)
    caps = await executor.refresh_capabilities()
    assert caps.skills == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_executor_loads_skills.py -v`
Expected: FAIL (`_load_skills` missing / skills not populated)

- [ ] **Step 3: Write minimal implementation**

In `executor.py`, add the import near the other codex-adapter imports:

```python
from .skills import parse_skills_list
```

Add a cache attribute in `__init__` (after `self._last_detected_version = None`):

```python
        self._skills_loaded = False
```

Extend `refresh_capabilities` (append before `return self._capabilities`):

```python
        if supported and not self._skills_loaded:
            try:
                result = await self._load_skills()
                self._capabilities.skills = parse_skills_list(result)
            except Exception:
                self._capabilities.skills = []
            self._skills_loaded = True
        return self._capabilities
```

Add the loader method on `CodexExecutor` (near `refresh_capabilities`):

```python
    async def _load_skills(self) -> dict[str, object]:
        session = await self._ensure_app_session()
        return await session.client.skills_list(cwds=[str(session.cwd)])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_executor_loads_skills.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/codex/executor.py tests/unit/executors/codex/test_executor_loads_skills.py
git commit -m "feat: load codex skills once at executor start"
```

---

### Task 7: Copy `skills` in the node descriptor

**Files:**
- Modify: `src/newbro/executors/node/service.py:1135-1151` (`_descriptor`)
- Test: `tests/unit/executors/node/test_descriptor_skills.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/node/test_descriptor_skills.py
import pytest

from newbro.executors.core.capabilities import ExecutorCapabilities, ExecutorSkill


class FakeExecutor:
    def __init__(self, caps):
        self._caps = caps

    def get_capabilities(self):
        return self._caps

    # no refresh_capabilities → _descriptor uses get_capabilities()


@pytest.mark.asyncio
async def test_descriptor_carries_skills(node_service):
    caps = ExecutorCapabilities(
        executor_type="codex",
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")],
    )
    descriptor = await node_service._descriptor("codex", FakeExecutor(caps))
    assert descriptor.skills[0].name == "doc"
```

> `node_service` fixture: if none exists, construct the service the way existing `tests/unit/executors/node/` tests do (copy their setup). If `_descriptor` only needs `self._audio_transcriber`, build a minimal instance per those tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_descriptor_skills.py -v`
Expected: FAIL (descriptor has empty `skills`)

- [ ] **Step 3: Write minimal implementation**

In `_descriptor` (`service.py`), add `skills=capabilities.skills,` to the `ExecutorNodeExecutor(...)` construction (after `availability_reason=...`):

```python
        return ExecutorNodeExecutor(
            executor_type=executor_type,
            supports_resume=capabilities.supports_resume,
            supports_follow_up=capabilities.supports_follow_up,
            supports_audio_instruction=capabilities.supports_audio_instruction
            or (capabilities.supports_follow_up and self._audio_transcriber.available),
            supports_thread_list=bool(
                executor_type == "codex"
                and hasattr(executor, "list_threads_page")
                and capabilities.availability_reason is None
            ),
            supports_pause=capabilities.supports_pause,
            supports_cancel=capabilities.supports_cancel,
            version=capabilities.version,
            minimum_version=capabilities.minimum_version,
            availability_reason=capabilities.availability_reason,
            skills=capabilities.skills,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/node/test_descriptor_skills.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/node/service.py tests/unit/executors/node/test_descriptor_skills.py
git commit -m "feat: copy skills through the node descriptor"
```

---

## Phase C — Snapshot projection

### Task 8: Project `skills` into `BroExecutorCapabilitySummary`

**Files:**
- Modify: `src/newbro/runtime/session.py:439-449` (`bro_list`) and the same projection in the snapshot builder if duplicated. Grep `BroExecutorCapabilitySummary(` to find all construction sites and update each.
- Test: `tests/unit/runtime/test_bro_list_skills.py` (create)

- [ ] **Step 1: Find every projection site**

Run: `grep -rn "BroExecutorCapabilitySummary(" src/newbro`
Expected: note each construction site; all must add `skills=`.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/runtime/test_bro_list_skills.py
from newbro.runtime.models import BroExecutorCapabilitySummary
from newbro.protocol.executor_node import ExecutorNodeExecutor
from newbro.executors.core.capabilities import ExecutorSkill
from newbro.runtime.session import _codex_summary_from_capability  # helper introduced in Step 4


def test_summary_projects_skills():
    cap = ExecutorNodeExecutor(
        executor_type="codex",
        skills=[ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")],
    )
    summary = _codex_summary_from_capability(cap)
    assert isinstance(summary, BroExecutorCapabilitySummary)
    assert summary.skills[0].name == "doc"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_list_skills.py -v`
Expected: FAIL (`ImportError: cannot import name '_codex_summary_from_capability'`)

- [ ] **Step 4: Write minimal implementation**

In `session.py`, extract a module-level helper and use it at every projection site. Add near the other module helpers:

```python
def _codex_summary_from_capability(capability) -> BroExecutorCapabilitySummary:
    return BroExecutorCapabilitySummary(
        version=capability.version,
        minimum_version=capability.minimum_version,
        availability_reason=capability.availability_reason,
        supports_thread_list=capability.supports_thread_list,
        supports_audio_instruction=capability.supports_audio_instruction,
        skills=capability.skills,
    )
```

Replace the inline `BroExecutorCapabilitySummary(...)` in `bro_list` (and any other site found in Step 1) with:

```python
                        codex=(
                            _codex_summary_from_capability(codex_capability)
                            if codex_capability is not None
                            else None
                        ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_list_skills.py -v`
Expected: PASS

- [ ] **Step 6: Run existing session/bro-list tests for regressions**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/newbro/runtime/session.py tests/unit/runtime/test_bro_list_skills.py
git commit -m "feat: project codex skills into BroExecutorCapabilitySummary"
```

---

## Phase D — Activation primitive

### Task 9: `turn_start(skill=...)` adds the skill input item + `$name` marker

**Files:**
- Modify: `src/newbro/executors/adapters/codex/client.py:164-201` (`turn_start`); add helper.
- Test: `tests/unit/executors/codex/test_turn_start_skill.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/codex/test_turn_start_skill.py
import pytest

from newbro.executors.adapters.codex.client import CodexAppServerClient


class FakePeer:
    def __init__(self):
        self.last = None

    async def request(self, method, params=None):
        self.last = (method, params)
        return {"turn": {"id": "t1"}}


@pytest.mark.asyncio
async def test_turn_start_with_skill_adds_item_and_marker():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    await client.turn_start(
        thread_id="th",
        prompt="find me flights",
        skill={"name": "flight-search", "path": "/s/flight/SKILL.md"},
    )
    _, params = peer.last
    items = params["input"]
    assert items[0]["type"] == "text"
    assert items[0]["text"].startswith("$flight-search ")
    assert {"type": "skill", "name": "flight-search", "path": "/s/flight/SKILL.md"} in items


@pytest.mark.asyncio
async def test_turn_start_without_skill_unchanged():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    await client.turn_start(thread_id="th", prompt="hello")
    _, params = peer.last
    assert len(params["input"]) == 1
    assert params["input"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_turn_start_marker_only_when_path_missing():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    await client.turn_start(thread_id="th", prompt="go", skill={"name": "deep-research", "path": None})
    _, params = peer.last
    assert params["input"][0]["text"].startswith("$deep-research ")
    assert all(i["type"] != "skill" for i in params["input"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_turn_start_skill.py -v`
Expected: FAIL (`turn_start() got an unexpected keyword argument 'skill'`)

- [ ] **Step 3: Write minimal implementation**

Add a helper near the bottom of `client.py` (next to `_as_dict`):

```python
def _apply_skill_marker(prompt: str, skill: dict[str, object] | None) -> str:
    if not skill:
        return prompt
    name = skill.get("name")
    if not isinstance(name, str) or not name:
        return prompt
    marker = f"${name}"
    if prompt.startswith(marker):
        return prompt
    return f"{marker} {prompt}"
```

Update `turn_start` signature and body:

```python
    async def turn_start(
        self,
        *,
        thread_id: str,
        prompt: str,
        collaboration_mode: Literal["plan", "default"] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        skill: dict[str, object] | None = None,
    ) -> dict[str, object]:
        input_items: list[dict[str, object]] = [
            {
                "type": "text",
                "text": _apply_skill_marker(prompt, skill),
                "textElements": [],
            }
        ]
        if skill and isinstance(skill.get("name"), str) and isinstance(skill.get("path"), str) and skill["path"]:
            input_items.append({"type": "skill", "name": skill["name"], "path": skill["path"]})
        params: dict[str, object] = {
            "threadId": thread_id,
            "input": input_items,
        }
        if collaboration_mode is not None:
            if not model and collaboration_mode != "default":
                raise ValueError("Codex collaborationMode requires a model.")
            if model:
                params["collaborationMode"] = {
                    "mode": collaboration_mode,
                    "settings": {
                        "model": model,
                        "reasoning_effort": reasoning_effort,
                        "developer_instructions": None,
                    },
                }
            else:
                params["collaborationMode"] = {"mode": collaboration_mode}
        result = await self._peer.request("turn/start", params)
        return _as_dict(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_turn_start_skill.py -v`
Expected: PASS (all 3)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/executors/adapters/codex/client.py tests/unit/executors/codex/test_turn_start_skill.py
git commit -m "feat: activate a skill in codex turn/start"
```

---

### Task 10: Read `skill` from metadata at the three executor turn sites

**Files:**
- Modify: `src/newbro/executors/adapters/codex/executor.py` — `run_task` (~362), `handle_text_instruction` (~417), `start_turn_request`/`_turn_start_for_request` (~480/920); add `_skill_from_metadata` helper.
- Test: `tests/unit/executors/codex/test_executor_skill_threading.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/executors/codex/test_executor_skill_threading.py
from newbro.executors.adapters.codex.executor import _skill_from_metadata


def test_skill_from_metadata_reads_name_and_path():
    meta = {"skill": {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}}
    assert _skill_from_metadata(meta) == {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}


def test_skill_from_metadata_none_when_absent_or_malformed():
    assert _skill_from_metadata({}) is None
    assert _skill_from_metadata({"skill": {"path": "/x"}}) is None  # no name
    assert _skill_from_metadata({"skill": "nope"}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_executor_skill_threading.py -v`
Expected: FAIL (`cannot import name '_skill_from_metadata'`)

- [ ] **Step 3: Write minimal implementation**

Add the helper at module level in `executor.py`:

```python
def _skill_from_metadata(metadata: dict[str, object]) -> dict[str, object] | None:
    skill = metadata.get("skill")
    if not isinstance(skill, dict):
        return None
    name = skill.get("name")
    if not isinstance(name, str) or not name:
        return None
    return skill
```

Thread it at each site:

`run_task` — pass `skill=` into `turn_start`:

```python
                turn = await session.client.turn_start(
                    thread_id=thread_id,
                    prompt=prompt,
                    skill=_skill_from_metadata(task.metadata),
                    **collaboration_kwargs,
                )
```

`handle_text_instruction` — pass `skill=`:

```python
            turn = await session.client.turn_start(
                thread_id=session.thread_id,
                prompt=(
                    "Direct user follow-up instruction:\n"
                    f"{text}\n\n"
                    "Act on this instruction in the existing execution thread."
                ),
                skill=_skill_from_metadata(instruction.metadata),
                **collaboration_kwargs,
            )
```

`start_turn_request` — compute skill and pass into `_turn_start_for_request`:

```python
                skill = _skill_from_metadata(command.metadata) or _skill_from_metadata(
                    command.instruction.metadata
                )
                turn = await _turn_start_for_request(
                    session,
                    thread_id=thread_id,
                    prompt=text,
                    plan_mode=plan_mode,
                    skill=skill,
                )
```

`_turn_start_for_request` — add `skill` param and forward to both `turn_start` calls:

```python
async def _turn_start_for_request(
    session: CodexExecutorSession,
    *,
    thread_id: str,
    prompt: str,
    plan_mode: bool,
    skill: dict[str, object] | None = None,
) -> dict[str, object]:
    if plan_mode:
        collaboration_kwargs = await _collaboration_kwargs_for_turn(session, plan_mode=True)
        return await session.client.turn_start(
            thread_id=thread_id,
            prompt=prompt,
            skill=skill,
            **collaboration_kwargs,
        )

    model = _session_collaboration_model(session, "default") or _session_codex_model(session)
    return await session.client.turn_start(
        thread_id=thread_id,
        prompt=prompt,
        collaboration_mode="default",
        model=model,
        reasoning_effort=(
            _session_collaboration_reasoning_effort(session, "default")
            or _session_codex_reasoning_effort(session)
        ),
        skill=skill,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/executors/codex/test_executor_skill_threading.py -v`
Expected: PASS

- [ ] **Step 5: Run codex executor regression tests**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_codex_multi_message_turn.py -q`
Expected: PASS (turn streaming contract intact)

- [ ] **Step 6: Commit**

```bash
git add src/newbro/executors/adapters/codex/executor.py tests/unit/executors/codex/test_executor_skill_threading.py
git commit -m "feat: thread chosen skill into codex turn sites"
```

---

## Phase E — Thread skill through the runtime + API

### Task 11: `direct_turn_starter` writes `skill` into outbound metadata

**Files:**
- Modify: `src/newbro/runtime/direct_turn_starter.py:43-99,151-191`
- Test: `tests/unit/runtime/test_direct_turn_starter_skill.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/runtime/test_direct_turn_starter_skill.py
from newbro.protocol import ExecutorTextInstruction
from newbro.runtime.direct_turn_starter import DirectTurnStarter


def _starter():
    return DirectTurnStarter(
        session_id="s", blackboard=None, executor_node_manager=None, publish_snapshot=None
    )


def test_outbound_metadata_includes_skill():
    instruction = ExecutorTextInstruction(instruction_id="i1", target_persona_id="p", text="hi")
    meta = _starter()._outbound_metadata(
        source="bro_detail_text",
        instruction=instruction,
        continuity_key="c",
        create_new_thread=True,
        workspace_id=None,
        client_request_id=None,
        execution_session=None,
        latest_resume_handle=None,
        plan_mode=False,
        skill={"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"},
        metadata=None,
    )
    assert meta["skill"] == {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}


def test_outbound_metadata_omits_skill_when_none():
    instruction = ExecutorTextInstruction(instruction_id="i1", target_persona_id="p", text="hi")
    meta = _starter()._outbound_metadata(
        source="bro_detail_text", instruction=instruction, continuity_key="c",
        create_new_thread=True, workspace_id=None, client_request_id=None,
        execution_session=None, latest_resume_handle=None, plan_mode=False,
        skill=None, metadata=None,
    )
    assert "skill" not in meta
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_direct_turn_starter_skill.py -v`
Expected: FAIL (`_outbound_metadata() got an unexpected keyword argument 'skill'`)

- [ ] **Step 3: Write minimal implementation**

Add `skill` param to `start_turn` (after `plan_mode: bool = False,`):

```python
        skill: dict[str, object] | None = None,
```

Pass it into the `_outbound_metadata(...)` call inside `start_turn` (add `skill=skill,` alongside `plan_mode=plan_mode,`).

Add `skill` param to `_outbound_metadata` signature (after `plan_mode: bool,`):

```python
        skill: dict[str, object] | None,
```

In `_outbound_metadata`, after the `plan_mode` block, before `if client_request_id is not None:`:

```python
        if skill:
            outbound_metadata["skill"] = skill
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_direct_turn_starter_skill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newbro/runtime/direct_turn_starter.py tests/unit/runtime/test_direct_turn_starter_skill.py
git commit -m "feat: carry chosen skill in outbound turn metadata"
```

---

### Task 12: `direct_executor.submit_text_instruction` threads + validates skill

**Files:**
- Modify: `src/newbro/runtime/direct_executor.py:149-302`
- Test: `tests/unit/runtime/test_direct_executor_skill.py` (create)

This task implements the **vanished-skill validate-before-write contract**: a chosen skill is written into instruction/task metadata only if it exists in the bro's current catalog; otherwise it is dropped and a `skill_dropped` marker is recorded.

- [ ] **Step 1: Write the failing test (pure helpers)**

```python
# tests/unit/runtime/test_direct_executor_skill.py
from newbro.executors.core.capabilities import ExecutorSkill
from newbro.runtime.direct_executor import _resolve_skill_against_catalog


def _catalog():
    return [ExecutorSkill(name="doc", display_name="Word Docs", path="/x/SKILL.md")]


def test_resolve_returns_ref_when_present():
    ref, dropped = _resolve_skill_against_catalog("doc", _catalog())
    assert ref == {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}
    assert dropped is None


def test_resolve_drops_when_absent():
    ref, dropped = _resolve_skill_against_catalog("flight-search", _catalog())
    assert ref is None
    assert dropped == {"name": "flight-search", "reason": "not_available"}


def test_resolve_none_when_no_skill_requested():
    assert _resolve_skill_against_catalog(None, _catalog()) == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_skill.py -v`
Expected: FAIL (`cannot import name '_resolve_skill_against_catalog'`)

- [ ] **Step 3: Write the helper**

Add at module level in `direct_executor.py`:

```python
def _resolve_skill_against_catalog(
    skill_name: str | None,
    catalog,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """Return (skill_ref, dropped_marker). Validate-before-write: only a skill that
    exists and is enabled in the bro's current catalog produces a ref; otherwise it
    is dropped with an observable marker (never silently 'ran')."""
    if not skill_name:
        return None, None
    for skill in catalog or []:
        if skill.name == skill_name and skill.enabled:
            return (
                {"name": skill.name, "path": skill.path, "display_name": skill.display_name},
                None,
            )
    return None, {"name": skill_name, "reason": "not_available"}
```

- [ ] **Step 4: Run helper test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_skill.py -v`
Expected: PASS

- [ ] **Step 5: Wire the helper into `submit_text_instruction`**

Add `skill_name: str | None = None` to the `submit_text_instruction` signature (after `plan_mode: bool = False,`).

After the persona/node readiness checks (right after the `runtime.executor_ready` metric, ~line 195), resolve against the node's catalog:

```python
        node_skills = self.executor_node_manager.codex_skills_for_node(persona.executor_node_id)
        skill_ref, skill_dropped = _resolve_skill_against_catalog(skill_name, node_skills)
```

In the `ExecutorTextInstruction(... metadata={...})` literal, add skill keys:

```python
            metadata={
                "source": "bro_detail_text",
                "target_thread_id": thread_target.public_thread_id,
                "client_request_id": client_request_id,
                "plan_mode": plan_mode,
                **({"skill": skill_ref} if skill_ref else {}),
                **({"skill_dropped": skill_dropped} if skill_dropped else {}),
            },
```

In the **no-active-run** branch, pass `skill=skill_ref` into the `start_turn(...)` call (alongside `plan_mode=plan_mode,`).

In the **active-run** branch, set it on the task metadata (after `task.metadata["plan_mode"] = plan_mode`):

```python
            if skill_ref:
                task.metadata["skill"] = skill_ref
            else:
                task.metadata.pop("skill", None)
            if skill_dropped:
                task.metadata["skill_dropped"] = skill_dropped
```

- [ ] **Step 6: Add the node-catalog accessor on the manager**

In `src/newbro/runtime/executor_node_manager.py`, add a method (near other node accessors):

```python
    def codex_skills_for_node(self, node_id: str | None):
        if not node_id:
            return []
        view = self._connection_views().get(node_id)
        if view is None:
            return []
        for capability in view.executor_capabilities:
            if capability.executor_type == "codex":
                return list(capability.skills)
        return []
```

> Confirm `ExecutorNodeConnectionView.executor_capabilities` is the right field name by reading the dataclass; adjust if the project exposes node capabilities differently. Add a focused test in `test_direct_executor_skill.py` using a fake manager that returns a catalog, asserting the dropped marker lands in instruction metadata when the skill is absent.

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_direct_executor_skill.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/newbro/runtime/direct_executor.py src/newbro/runtime/executor_node_manager.py tests/unit/runtime/test_direct_executor_skill.py
git commit -m "feat: validate-before-write skill threading in direct executor"
```

---

### Task 13: Thread `skill_name` through `session` + API

**Files:**
- Modify: `src/newbro/runtime/session.py:672-691` (`submit_executor_text_instruction`)
- Modify: `src/newbro/api/routes/executor_text.py:15-119`
- Test: `tests/unit/api/test_executor_text_skill.py` (create or extend existing executor-text API test)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/api/test_executor_text_skill.py
from newbro.api.routes.executor_text import ExecutorTextInstructionRequest


def test_request_accepts_skill_name():
    req = ExecutorTextInstructionRequest(target_persona_id="p", text="hi", skill_name="doc")
    assert req.skill_name == "doc"


def test_request_skill_name_optional():
    req = ExecutorTextInstructionRequest(target_persona_id="p", text="hi")
    assert req.skill_name is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_executor_text_skill.py -v`
Expected: FAIL (unexpected keyword `skill_name`)

- [ ] **Step 3: Write minimal implementation**

In `executor_text.py`, add the request field (after `plan_mode: bool = False`):

```python
    skill_name: str | None = Field(default=None, min_length=1, max_length=200)
```

Pass it to the session call inside `submit_executor_text_instruction` (add `skill_name=body.skill_name,` alongside `plan_mode=body.plan_mode,`).

In `session.py`, add `skill_name: str | None = None` to `submit_executor_text_instruction` (after `plan_mode`) and forward it to `_direct_executor().submit_text_instruction(..., skill_name=skill_name)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_executor_text_skill.py -v`
Expected: PASS

- [ ] **Step 5: Run existing executor-text API tests for regressions**

Run: `.venv/bin/python -m pytest tests/unit/api -k executor_text -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/newbro/api/routes/executor_text.py src/newbro/runtime/session.py tests/unit/api/test_executor_text_skill.py
git commit -m "feat: accept skill_name on the executor-text API"
```

---

## Phase F — Timeline pill

### Task 14: Mark the user message with the chosen skill in the timeline projection

**Files:**
- Modify: `src/newbro/runtime/bro_detail_thread_helpers.py` (near `_mark_timeline_message_plan_mode:510`) and the projection sites that call it (grep `_mark_timeline_message_plan_mode`).
- Test: `tests/unit/runtime/test_timeline_skill_pill.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/runtime/test_timeline_skill_pill.py
from newbro.runtime.models import BroTimelineMessage
from newbro.runtime.bro_detail_thread_helpers import _mark_timeline_message_skill


def test_marks_message_with_skill():
    msg = BroTimelineMessage(role="user", text="hi", metadata={})
    marked = _mark_timeline_message_skill(msg, {"name": "doc", "display_name": "Word Docs"})
    assert marked.metadata["skill"] == {"name": "doc", "display_name": "Word Docs"}


def test_none_message_passthrough():
    assert _mark_timeline_message_skill(None, {"name": "doc"}) is None


def test_no_skill_returns_message_unchanged():
    msg = BroTimelineMessage(role="user", text="hi", metadata={})
    assert _mark_timeline_message_skill(msg, None) is msg
```

> Check `BroTimelineMessage`'s required fields by reading `runtime/models.py`; adjust the constructor in the test to match (role/text/metadata at minimum).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_timeline_skill_pill.py -v`
Expected: FAIL (`cannot import name '_mark_timeline_message_skill'`)

- [ ] **Step 3: Write minimal implementation**

Add next to `_mark_timeline_message_plan_mode`:

```python
def _mark_timeline_message_skill(
    message: BroTimelineMessage | None,
    skill: dict[str, object] | None,
) -> BroTimelineMessage | None:
    if message is None or not skill:
        return message
    return message.model_copy(update={"metadata": {**message.metadata, "skill": skill}})
```

At each site where `_mark_timeline_message_plan_mode` is applied to a paired user message, also apply the skill mark, reading the skill from the same metadata source used for `plan_mode` (task/instruction/turn metadata `.get("skill")`). Example pattern at a projection site:

```python
            paired_user_message = _mark_timeline_message_plan_mode(paired_user_message)
            paired_user_message = _mark_timeline_message_skill(
                paired_user_message, metadata.get("skill") if isinstance(metadata.get("skill"), dict) else None
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_timeline_skill_pill.py -v`
Expected: PASS

- [ ] **Step 5: Run projection regression tests**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/newbro/runtime/bro_detail_thread_helpers.py tests/unit/runtime/test_timeline_skill_pill.py
git commit -m "feat: mark timeline user message with chosen skill"
```

---

## Phase G — Web UI

### Task 15: Web types — `ExecutorSkill` + summary `skills`

**Files:**
- Modify: `clients/web/src/types.ts:237-243`
- Test: none (type-only; covered by `tsc`)

- [ ] **Step 1: Add the type and field**

In `types.ts`, before `BroExecutorCapabilitySummary`:

```typescript
export interface ExecutorSkill {
  name: string;
  display_name: string;
  description: string;
  hint: string | null;
  path: string;
  enabled: boolean;
}
```

Add `skills` to the summary:

```typescript
export interface BroExecutorCapabilitySummary {
  version: string | null;
  minimum_version: string | null;
  availability_reason: string | null;
  supports_thread_list: boolean;
  supports_audio_instruction: boolean;
  skills: ExecutorSkill[];
}
```

- [ ] **Step 2: Typecheck**

Run: `cd clients/web && npx tsc --noEmit`
Expected: no errors (existing snapshot mocks may need `skills: []` — fix any that fail to compile by adding `skills: []`).

- [ ] **Step 3: Commit**

```bash
git add clients/web/src/types.ts
git commit -m "feat(web): add ExecutorSkill type and summary skills field"
```

---

### Task 16: Web client — send `skill_name`

**Files:**
- Modify: `clients/web/src/lib/session-client.ts:416-445`
- Test: `clients/web/src/lib/session-client.test.ts` (extend)

- [ ] **Step 1: Write the failing test**

Add to `session-client.test.ts` (follow the existing fetch-mock pattern in that file):

```typescript
it("sends skill_name when provided", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ instruction_id: "i", target_persona_id: "p", target_thread_id: "t", status: "accepted" }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await submitExecutorTextInstruction("s1", { targetPersonaId: "p", text: "hi", skillName: "doc" });
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body.skill_name).toBe("doc");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd clients/web && npm run test -- src/lib/session-client.test.ts`
Expected: FAIL (`skill_name` undefined in body)

- [ ] **Step 3: Write minimal implementation**

Add `skillName?: string | null;` to the payload type, and in the body:

```typescript
  const body: Record<string, unknown> = {
    target_persona_id: payload.targetPersonaId,
    target_thread_id: payload.targetThreadId ?? null,
    create_new_thread: payload.createNewThread ?? false,
    workspace_id: payload.workspaceId ?? null,
    plan_mode: payload.planMode ?? false,
    text: payload.text,
  };
  if (payload.skillName) {
    body.skill_name = payload.skillName;
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd clients/web && npm run test -- src/lib/session-client.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add clients/web/src/lib/session-client.ts clients/web/src/lib/session-client.test.ts
git commit -m "feat(web): send skill_name on executor text instruction"
```

---

### Task 17: `SkillPicker` component (catalog hook + desktop popover + mobile sheet)

**Files:**
- Create: `clients/web/src/components/newbro/SkillPicker.tsx`
- Test: `clients/web/src/components/newbro/SkillPicker.test.tsx` (create)

Port the prototype UI verbatim in structure, swapping the hardcoded data for the real catalog. Source components to port:
- Desktop popover: `prototypes/design/variants-desktop.jsx` `DTSkillMenu` (lines ~677-728) and the lead-cluster chip/pill (lines ~878-928).
- Mobile sheet: `prototypes/design/variants-mobile.jsx` `ThrSkillSheet` (lines ~448-500).

Keep the same classNames (`.dt-skill-*`, `.dt-cmp-skill*`, `.thr-skill-*`) so existing CSS in `clients/web/src/styles/variants-*.css` applies. Replace `SKILLS`/`THR_SKILLS` with the `skills: ExecutorSkill[]` prop; use `display_name` for the title, `description` for the subtitle, `SKILL_DEFAULT_ICON` for every row (icons deferred), and `hint` for the placeholder.

- [ ] **Step 1: Write the failing test**

```typescript
// clients/web/src/components/newbro/SkillPicker.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { filterSkills, DesktopSkillMenu } from "./SkillPicker";
import type { ExecutorSkill } from "../../types";

const SKILLS: ExecutorSkill[] = [
  { name: "doc", display_name: "Word Docs", description: "Edit docx", hint: null, path: "/a", enabled: true },
  { name: "flight-search", display_name: "Flight search", description: "Compare fares", hint: null, path: "/b", enabled: true },
];

describe("filterSkills", () => {
  it("filters by name and description, case-insensitive", () => {
    expect(filterSkills(SKILLS, "flight").map((s) => s.name)).toEqual(["flight-search"]);
    expect(filterSkills(SKILLS, "").length).toBe(2);
    expect(filterSkills(SKILLS, "fares").map((s) => s.name)).toEqual(["flight-search"]);
  });
});

describe("DesktopSkillMenu", () => {
  it("renders rows and fires onChoose", () => {
    const onChoose = vi.fn();
    render(<DesktopSkillMenu skills={SKILLS} query="" selected={null} broName="Atlas" onChoose={onChoose} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Word Docs"));
    expect(onChoose).toHaveBeenCalledWith(SKILLS[0]);
  });

  it("shows empty state when no match", () => {
    render(<DesktopSkillMenu skills={SKILLS} query="zzz" selected={null} broName="Atlas" onChoose={() => {}} onClose={() => {}} />);
    expect(screen.getByText(/No skill matches/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd clients/web && npm run test -- src/components/newbro/SkillPicker.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Write the component**

Create `SkillPicker.tsx` exporting `filterSkills`, `DesktopSkillMenu`, `MobileSkillSheet`, `SkillLeadCluster` (desktop chip/pill + popover wrapper), and a `SKILL_DEFAULT_ICON`. Port the prototype JSX, converting to TS with these prop types:

```typescript
import React from "react";
import type { ExecutorSkill } from "../../types";

export const SKILL_DEFAULT_ICON = (
  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3l1.9 4.7L19 9l-4.1 2.3L13 16l-1-4.5L7 9l4.1-1.3z" />
    <path d="M19 15l.7 1.8L21.5 18l-1.8.7L19 21l-.7-2.3L16.5 18l1.8-1.2z" />
  </svg>
);

export function filterSkills(skills: ExecutorSkill[], query: string): ExecutorSkill[] {
  const q = query.trim().toLowerCase();
  if (!q) return skills;
  return skills.filter((s) => `${s.display_name} ${s.name} ${s.description}`.toLowerCase().includes(q));
}

interface MenuProps {
  skills: ExecutorSkill[];
  query: string;
  selected: ExecutorSkill | null;
  broName: string;
  onChoose: (skill: ExecutorSkill) => void;
  onClose: () => void;
}

export function DesktopSkillMenu({ skills, query, selected, broName, onChoose }: MenuProps) {
  const list = filterSkills(skills, query);
  return (
    <div className="dt-skill-pop" role="menu" aria-label="Run with a skill">
      <div className="dt-skill-pop-head">
        <span className="dt-skill-pop-title">Run with a skill</span>
        <span className="dt-skill-pop-hint">
          {query ? <>filtering <span className="dt-skill-pop-q">/{query}</span></> : <>type <kbd className="dt-kbd">/</kbd> to filter</>}
        </span>
      </div>
      {list.length === 0 ? (
        <div className="dt-skill-empty">No skill matches “{query}”. Just send and {broName} figures it out.</div>
      ) : (
        <ul className="dt-skill-pop-list">
          {list.map((s) => {
            const on = selected?.name === s.name;
            return (
              <li key={s.name}>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={on}
                  disabled={!s.enabled}
                  className={`dt-skill-opt${on ? " dt-skill-opt-on" : ""}${s.enabled ? "" : " dt-skill-opt-disabled"}`}
                  onClick={() => s.enabled && onChoose(s)}
                >
                  <span className="dt-skill-opt-ic" aria-hidden="true">{SKILL_DEFAULT_ICON}</span>
                  <span className="dt-skill-opt-body">
                    <span className="dt-skill-opt-name">{s.display_name}</span>
                    <span className="dt-skill-opt-desc">{s.description}</span>
                  </span>
                  {on && (
                    <svg className="dt-skill-opt-check" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M4 12.5L10 18L20 6" />
                    </svg>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="dt-skill-pop-foot">
        <span>Skills shape how {broName} works the turn</span>
        <kbd className="dt-kbd">esc</kbd>
      </div>
    </div>
  );
}
```

Then add `MobileSkillSheet` (port `ThrSkillSheet`, same prop shape plus `open`/`onClose`, using `.thr-skill-*` classes and `filterSkills`) and `SkillLeadCluster` (port the desktop chip↔pill + popover wrapper from prototype lines 878-928, owning `skillOpen`/`query` state and the outside-click/Escape `useEffect`). Reuse `filterSkills` for the inline `/` behavior.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd clients/web && npm run test -- src/components/newbro/SkillPicker.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add clients/web/src/components/newbro/SkillPicker.tsx clients/web/src/components/newbro/SkillPicker.test.tsx
git commit -m "feat(web): SkillPicker component ported from prototype with real catalog"
```

---

### Task 18: Wire the picker into the desktop + mobile composers

**Files:**
- Modify: `clients/web/src/ArtboardShell.tsx` (`DesktopComposerBar` ~2984-3260; mobile composer ~2620-2930)
- Test: `clients/web/src/components/newbro/SkillPicker.integration.test.tsx` (create) — render the composer with a catalog, choose a skill, assert the send payload carries `skillName`.

- [ ] **Step 1: Write the failing test**

```typescript
// clients/web/src/components/newbro/SkillPicker.integration.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import * as client from "../../lib/session-client";
// import the composer (export DesktopComposerBar from ArtboardShell if not already exported)
import { DesktopComposerBar } from "../../ArtboardShell";

it("sends chosen skill_name with the message", async () => {
  const spy = vi.spyOn(client, "submitExecutorTextInstruction").mockResolvedValue({
    instruction_id: "i", target_persona_id: "p", target_thread_id: "t", status: "accepted",
  });
  // render with a bro whose executor_node.codex.skills includes "doc"; follow the
  // existing ArtboardShell test harness for required props/context.
  render(/* <DesktopComposerBar ...props with catalog /> */ null as never);
  fireEvent.click(screen.getByTitle(/Run this turn with a skill/i));
  fireEvent.click(screen.getByText("Word Docs"));
  // type + submit
  // ...
  await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ skillName: "doc" })));
});
```

> This integration test depends on the composer's existing test harness. If `DesktopComposerBar` is not exported, export it. If wiring a full render is impractical, instead assert at the unit boundary: extract a `buildSubmitPayload({ ..., skill })` pure function in `ArtboardShell.tsx`, unit-test that it includes `skillName: skill?.name`, and call it from `submitText`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd clients/web && npm run test -- src/components/newbro/SkillPicker.integration.test.tsx`
Expected: FAIL

- [ ] **Step 3: Wire the composer**

In `DesktopComposerBar`:
- Add state: `const [skill, setSkill] = useState<ExecutorSkill | null>(null);`
- Derive catalog: `const skills = bro.executor_node?.codex?.skills ?? [];`
- Render `<SkillLeadCluster skills={skills} selected={skill} onChoose={setSkill} onClear={() => setSkill(null)} broName={bro.name} disabled={disabled} />` beside the existing `planChip` (only when `skills.length > 0`).
- In `submitText`, pass `skillName: skill?.name ?? null` into `submitExecutorTextInstruction(...)`, and `setSkill(null)` after a successful send (next to `setDraft("")`).
- Use `skill?.hint` for the input placeholder when a skill is selected (fallback `Running with ${skill.display_name}…`).
- Clear `skill` when `bro.id` changes (add to the existing per-bro reset `useEffect`, or add one).

Apply the equivalent wiring in the mobile composer using `MobileSkillSheet`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd clients/web && npm run test -- src/components/newbro/SkillPicker.integration.test.tsx`
Expected: PASS

- [ ] **Step 5: Typecheck + targeted suite**

Run: `cd clients/web && npx tsc --noEmit && npm run test -- src/components/newbro`
Expected: no type errors; tests PASS

- [ ] **Step 6: Commit**

```bash
git add clients/web/src/ArtboardShell.tsx clients/web/src/components/newbro/SkillPicker.integration.test.tsx
git commit -m "feat(web): wire skill picker into desktop and mobile composers"
```

---

### Task 19: Render the skill pill on the timeline bubble

**Files:**
- Modify: `clients/web/src/ArtboardShell.tsx` (user bubble renderer ~970-1010; `BroTimelineTurn` mapper ~1060-1075)
- Test: extend `clients/web/src/components/newbro/SkillPicker.test.tsx` or add `clients/web/src/lib/turnRenderModel.test.ts` coverage if the pill flows through that model.

- [ ] **Step 1: Write the failing test**

```typescript
// add to clients/web/src/components/newbro/SkillPicker.test.tsx
import { skillFromMessageMetadata } from "../../ArtboardShell";

describe("skillFromMessageMetadata", () => {
  it("reads skill display_name from message metadata", () => {
    expect(skillFromMessageMetadata({ skill: { name: "doc", display_name: "Word Docs" } })).toEqual({ name: "doc", display_name: "Word Docs" });
  });
  it("returns null when absent", () => {
    expect(skillFromMessageMetadata({})).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd clients/web && npm run test -- src/components/newbro/SkillPicker.test.tsx`
Expected: FAIL (`skillFromMessageMetadata` not exported)

- [ ] **Step 3: Write minimal implementation**

In `ArtboardShell.tsx`, export the reader:

```typescript
export function skillFromMessageMetadata(metadata: Record<string, unknown> | undefined): { name: string; display_name: string } | null {
  const skill = metadata?.skill;
  if (skill && typeof skill === "object" && "name" in skill) {
    const s = skill as { name: string; display_name?: string };
    return { name: s.name, display_name: s.display_name ?? s.name };
  }
  return null;
}
```

In the user-bubble renderer, where `planMode` decoration is applied, also render a pill when a skill is present:

```tsx
{(() => {
  const sk = skillFromMessageMetadata(message.metadata);
  return sk ? <span className="dt-cmp-skillpill dt-bubble-skillpill"><span className="dt-cmp-skillpill-name">{sk.display_name}</span></span> : null;
})()}
```

Reuse existing skill-pill CSS classes. If `message.metadata` isn't already surfaced on the render model, thread it through the `BroTimelineTurn`→bubble mapper the same way `plan_mode` is (`timelinePlanMode`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd clients/web && npm run test -- src/components/newbro/SkillPicker.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add clients/web/src/ArtboardShell.tsx clients/web/src/components/newbro/SkillPicker.test.tsx
git commit -m "feat(web): render skill pill on the timeline bubble"
```

---

## Phase H — Docs + full verification

### Task 20: Protocol doc + memory note

**Files:**
- Create: `docs/protocol/skills.md`
- Modify: `docs/protocol/index.md` (add link), `docs/memories.md` (one-line note)

- [ ] **Step 1: Write the protocol doc**

Document, with the fixture as reference: discovery (`skills/list`, grouped-per-cwd shape, load-once-at-start, `register_node` carriage), the lean `ExecutorSkill` projection, activation (`{type:"skill"}` input item + `$name` marker), and the vanished-skill validate-before-write contract. Link the fixture `docs/protocol/fixtures/codex-skills-list-sample.json`.

- [ ] **Step 2: Add index link + memory note**

Append to `docs/protocol/index.md` a link to `skills.md`. Append to `docs/memories.md`:

```
- Skill picker: codex skills discovered once at executor start via skills/list, ride register_node; chosen skill rides turn metadata like plan_mode and activates via a {type:"skill"} input item + $name marker. See docs/protocol/skills.md.
```

- [ ] **Step 3: Commit**

```bash
git add docs/protocol/skills.md docs/protocol/index.md docs/memories.md
git commit -m "docs: document codex skill discovery and activation"
```

---

### Task 21: Full suite + manual smoke

- [ ] **Step 1: Run the backend suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS (no regressions). Investigate and fix any failure before continuing.

- [ ] **Step 2: Run targeted web suites**

Run: `cd clients/web && npx tsc --noEmit && npm run test -- src/components/newbro src/lib/session-client.test.ts`
Expected: type-clean; tests PASS. (Skip the flaky full `App.test.tsx`.)

- [ ] **Step 3: Manual smoke (per AGENTS.md "verify activation")**

```bash
./newbro setup && ./newbro backend   # in one shell
# start the web client per docs/guides/local-dev.md, connect a codex executor,
# open a bro's active session, click Skill, pick one, send a message.
```

Confirm: picker lists real installed skills; sending shows the skill pill on the user bubble; the turn runs. Disable/uninstall a skill, reconnect the executor, confirm it disappears from the picker.

- [ ] **Step 4: Commit any fixes from verification**

```bash
git add -A && git commit -m "fix: address issues found during skill picker verification"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §1 lean model → Tasks 1, 15 (`ExecutorSkill`/projection fields, `hint`, `description` truncation in Task 4).
- §1 three models + descriptor copy → Tasks 1, 2, 3, 7.
- §2 discovery (grouped/flatten/dedupe, load-once cache, register_node) → Tasks 4, 5, 6, 7.
- §3 activation (skill item + `$name`, marker-only fallback) → Task 9; threading through all 3 turn sites → Task 10; API→runtime chain → Tasks 11, 12, 13.
- §3/§5 vanished-skill validate-before-write → Task 12 (`_resolve_skill_against_catalog`, `skill_dropped` marker).
- §4 UI (catalog from snapshot, generic glyph, defaultPrompt hint, chip hidden when empty, disabled greyed, clear on bro switch) → Tasks 15-19.
- Timeline pill → Task 14 (backend mark) + Task 19 (render).
- Snapshot projection → Task 8.
- Docs + memory → Task 20. Verification → Task 21.

**Placeholder scan:** UI port tasks (17, 18, 19) reference exact prototype line ranges and show the new/changed code; the integration test (18) documents a fallback (`buildSubmitPayload`) when full render is impractical — both are concrete, not "TODO".

**Type consistency:** `ExecutorSkill` fields identical across Python (Task 1) and TS (Task 15). Skill metadata ref shape `{name, path, display_name}` consistent across Tasks 9, 10, 11, 12, 14, 19. `skill_name` (API/wire) vs `skillName` (web payload) vs `skill` (metadata ref) used consistently per layer.
