# Native Codex Reasoning (live + settled) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface codex reasoning (the streaming `PROGRESS`/`PLAN` commentary) for native codex turns — live "is reasoning" stream while running, and a collapsed "Reasoned" pill once settled.

**Architecture:** Capture `PROGRESS`/`PLAN` text from `handle_codex_turn_event` into a session-held map keyed by executor turn identity `(executor_id, executor_thread_id, executor_turn_id)`; project a bounded copy onto `SessionSnapshot.recent_native_turn_reasoning`; in the frontend, join native turns (no `task_id`) by that identity and render with the existing streaming bubble + `DTAnswerBubble` pill.

**Tech Stack:** Python 3.12 / Pydantic / FastAPI / pytest (backend); React / TypeScript / Vitest (frontend).

Spec: `docs/superpowers/specs/2026-05-31-native-codex-reasoning-design.md`

---

## File structure

- Create: `src/newbro/protocol/native_reasoning.py` — `NativeReasoningStep` model.
- Modify: `src/newbro/protocol/__init__.py` — export `NativeReasoningStep`.
- Modify: `src/newbro/runtime/models.py` — add `recent_native_turn_reasoning` to `SessionSnapshot`.
- Modify: `src/newbro/runtime/session.py` — capture method, projection, store field, constants, key helper; wire into `handle_codex_turn_event` and `snapshot()`.
- Test: `tests/unit/runtime/test_session_runtime.py` — accumulation test.
- Modify: `src/newbro/ui/src/types.ts` — `NativeReasoningStep` type + snapshot field.
- Modify: `src/newbro/ui/src/NewbroShell.tsx` — thread `recentNativeTurnReasoning` through state/context.
- Modify: `src/newbro/ui/src/components/newbro/adapters.ts` — `buildReasoningStepsForNativeTurn`.
- Test: `src/newbro/ui/src/components/newbro/adapters.test.ts` — adapter unit tests.
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` — native-turn reasoning join in `TimelineTurnView`.
- Test: `src/newbro/ui/src/__tests__/App.test.tsx` — render native running (stream) + settled (pill).

Backend test command: `.venv/bin/python -m pytest <path>::<test> -v`
Frontend commands (run from `src/newbro/ui`): `npx vitest run <path> -t "<name>"` and `npx tsc --noEmit`.

---

## Task 1: `NativeReasoningStep` protocol model + snapshot field

**Files:**
- Create: `src/newbro/protocol/native_reasoning.py`
- Modify: `src/newbro/protocol/__init__.py`
- Modify: `src/newbro/runtime/models.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/unit/runtime/test_session_runtime.py`:

```python
def test_session_snapshot_has_native_reasoning_field_default_empty():
    from newbro.runtime.models import SessionSnapshot
    from newbro.protocol import NativeReasoningStep

    snap = SessionSnapshot(session_id="s1")
    assert snap.recent_native_turn_reasoning == {}

    step = NativeReasoningStep(
        item_id="item-1", text="thinking", kind="progress", created_at="2026-05-31T00:00:00+00:00"
    )
    snap2 = SessionSnapshot(session_id="s1", recent_native_turn_reasoning={"k": [step]})
    dumped = snap2.model_dump()
    assert dumped["recent_native_turn_reasoning"]["k"][0]["kind"] == "progress"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_session_snapshot_has_native_reasoning_field_default_empty -v`
Expected: FAIL with `ImportError` / `cannot import name 'NativeReasoningStep'`.

- [ ] **Step 3: Create the model file**

Create `src/newbro/protocol/native_reasoning.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class NativeReasoningStep(BaseModel):
    item_id: str
    text: str
    kind: Literal["progress", "plan"]
    created_at: str
```

- [ ] **Step 4: Export it from the protocol package**

In `src/newbro/protocol/__init__.py`, add the import next to the other `from .` imports (e.g. just after the `from .task_execution_detail import TaskExecutionDetailEntry` line):

```python
from .native_reasoning import NativeReasoningStep
```

And add `"NativeReasoningStep",` to the `__all__` list (next to `"TaskExecutionDetailEntry",`).

- [ ] **Step 5: Add the snapshot field**

In `src/newbro/runtime/models.py`, add `NativeReasoningStep` to the existing `from newbro.protocol import (...)` block (alphabetical-ish, near `NotificationCandidate`):

```python
    NativeReasoningStep,
```

Then, in `class SessionSnapshot`, add this field immediately after the `recent_execution_details` line:

```python
    recent_native_turn_reasoning: dict[str, list[NativeReasoningStep]] = Field(default_factory=dict)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_session_snapshot_has_native_reasoning_field_default_empty -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/newbro/protocol/native_reasoning.py src/newbro/protocol/__init__.py src/newbro/runtime/models.py tests/unit/runtime/test_session_runtime.py
git commit -m "feat: add NativeReasoningStep model and snapshot field"
```

---

## Task 2: Capture + project native reasoning in the runtime session

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/unit/runtime/test_session_runtime.py`:

```python
@pytest.mark.anyio
async def test_codex_turn_event_accumulates_native_reasoning():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    request = OutboundTurnRequest(
        request_id="out-turn-1",
        persona_id="forge",
        executor_node_id="node-forge",
        target_thread_id="thread-1",
        client_request_id="client-text-1",
        text="do the thing",
        status="accepted",
        created_at="2026-05-30T08:00:00+00:00",
    )
    await session.blackboard.put_outbound_turn_request(request)

    async def emit(text, *, item_id, event_type="progress"):
        await session.handle_codex_turn_event(
            CodexTurnEventMessage(
                request_id="out-turn-1",
                node_id="node-forge",
                target_persona_id="forge",
                target_thread_id="thread-1",
                event_type=event_type,
                message=text,
                executor_thread_id="native-thread-1",
                executor_turn_id="turn-1",
                metadata={"codex_item_id": item_id},
            )
        )

    await emit("Looking at the file", item_id="item-1")
    await emit("Looking at the file tree now", item_id="item-1")  # same item grows -> in place
    await emit("Writing the SCQA section", item_id="item-2")       # new item -> append
    await emit("Final plan ready", item_id="item-3", event_type="plan")

    snapshot = await session.snapshot(sync_imported_codex_threads=False)
    key = "codex::native-thread-1::turn-1"
    steps = snapshot.recent_native_turn_reasoning[key]
    assert [s.text for s in steps] == [
        "Looking at the file tree now",
        "Writing the SCQA section",
        "Final plan ready",
    ]
    assert steps[0].item_id == "item-1"
    assert steps[-1].kind == "plan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_codex_turn_event_accumulates_native_reasoning -v`
Expected: FAIL with `KeyError: 'codex::native-thread-1::turn-1'` (or `AttributeError` on `recent_native_turn_reasoning` if the field is empty `{}`).

- [ ] **Step 3: Add the import, constants, and key helper**

In `src/newbro/runtime/session.py`, add `NativeReasoningStep` to the existing `from newbro.protocol import (...)` import block (near `CodexTurnEventMessage`):

```python
    NativeReasoningStep,
```

Add these module-level constants and helper near the other module-level helpers (e.g. just above `def _bro_timeline_turn_from_codex_turn_event(`):

```python
_NATIVE_REASONING_TEXT_LIMIT = 280
_NATIVE_REASONING_STORE_STEPS = 16
_NATIVE_REASONING_STORE_TURNS = 20
_NATIVE_REASONING_PROJECT_STEPS = 8
_NATIVE_REASONING_PROJECT_TURNS = 10


def _native_reasoning_key(
    executor_id: str,
    executor_thread_id: str | None,
    executor_turn_id: str | None,
) -> str | None:
    if not executor_thread_id or not executor_turn_id:
        return None
    return f"{executor_id}::{executor_thread_id}::{executor_turn_id}"
```

- [ ] **Step 4: Add the session store field**

In `src/newbro/runtime/session.py`, next to the existing dataclass field
`_bro_thread_executor_turns: dict[str, list[BroTimelineTurn]] = field(default_factory=dict, init=False, repr=False)`,
add:

```python
    _native_turn_reasoning: dict[str, list[NativeReasoningStep]] = field(default_factory=dict, init=False, repr=False)
```

- [ ] **Step 5: Add the capture + projection methods**

In `src/newbro/runtime/session.py`, add these two methods to the session class, immediately after `_upsert_bro_thread_executor_turn`:

```python
    def _record_native_turn_reasoning(
        self,
        request: OutboundTurnRequest,
        message: CodexTurnEventMessage,
        timestamp: str,
    ) -> None:
        event_type = message.event_type.lower()
        if event_type not in {"progress", "plan"}:
            return
        text = (message.message or "").strip()
        if not text:
            return
        executor_thread_id = message.executor_thread_id or request.executor_thread_id
        executor_turn_id = message.executor_turn_id or request.executor_turn_id
        key = _native_reasoning_key(request.executor_id, executor_thread_id, executor_turn_id)
        if key is None:
            return
        raw_item_id = message.metadata.get("codex_item_id")
        item_id = raw_item_id if isinstance(raw_item_id, str) else ""
        step = NativeReasoningStep(
            item_id=item_id,
            text=text[:_NATIVE_REASONING_TEXT_LIMIT],
            kind="plan" if event_type == "plan" else "progress",
            created_at=timestamp,
        )
        steps = list(self._native_turn_reasoning.get(key, []))
        if steps and item_id and steps[-1].item_id == item_id:
            steps[-1] = step
        elif steps and steps[-1].text == step.text:
            return
        else:
            steps.append(step)
        steps = steps[-_NATIVE_REASONING_STORE_STEPS:]
        self._native_turn_reasoning.pop(key, None)
        self._native_turn_reasoning[key] = steps
        while len(self._native_turn_reasoning) > _NATIVE_REASONING_STORE_TURNS:
            oldest = next(iter(self._native_turn_reasoning))
            self._native_turn_reasoning.pop(oldest, None)

    def _recent_native_turn_reasoning(self) -> dict[str, list[NativeReasoningStep]]:
        if not self._native_turn_reasoning:
            return {}
        keys = list(self._native_turn_reasoning.keys())[-_NATIVE_REASONING_PROJECT_TURNS:]
        return {
            key: self._native_turn_reasoning[key][-_NATIVE_REASONING_PROJECT_STEPS:]
            for key in keys
        }
```

- [ ] **Step 6: Wire capture into `handle_codex_turn_event`**

In `src/newbro/runtime/session.py`, inside `handle_codex_turn_event`, immediately after the existing `self._upsert_bro_thread_executor_turn(...)` call (which is followed by `await self.interaction_manager.handle_outbound_codex_blocked(...)`), add:

```python
        self._record_native_turn_reasoning(updated_request, message, timestamp)
```

- [ ] **Step 7: Wire projection into `snapshot()`**

In `src/newbro/runtime/session.py`, in the `return SessionSnapshot(` block inside `snapshot()`, add this argument immediately after the existing `recent_execution_details=recent_execution_details,` line:

```python
            recent_native_turn_reasoning=self._recent_native_turn_reasoning(),
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_codex_turn_event_accumulates_native_reasoning -v`
Expected: PASS

- [ ] **Step 9: Run the surrounding suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add src/newbro/runtime/session.py tests/unit/runtime/test_session_runtime.py
git commit -m "feat: capture and project native codex turn reasoning"
```

---

## Task 3: Frontend types + NewbroShell context wiring

**Files:**
- Modify: `src/newbro/ui/src/types.ts`
- Modify: `src/newbro/ui/src/NewbroShell.tsx`

- [ ] **Step 1: Add the TS type + snapshot field**

In `src/newbro/ui/src/types.ts`, add this interface immediately after the `ExecutionDetailEntry` interface:

```typescript
export interface NativeReasoningStep {
  item_id: string;
  text: string;
  kind: "progress" | "plan";
  created_at: string;
}
```

Then, in `interface SessionSnapshot`, add this field immediately after the `recent_execution_details: Record<string, ExecutionDetailEntry[]>;` line:

```typescript
  recent_native_turn_reasoning: Record<string, NativeReasoningStep[]>;
```

- [ ] **Step 2: Thread it through NewbroShell state**

In `src/newbro/ui/src/NewbroShell.tsx`:

a) Add `NativeReasoningStep` to the import from `./types` that already brings in `ExecutionDetailEntry`.

b) Immediately after the existing
`const [recentExecutionDetails, setRecentExecutionDetails] = useState<Record<string, ExecutionDetailEntry[]>>({});`
add:

```typescript
  const [recentNativeTurnReasoning, setRecentNativeTurnReasoning] = useState<Record<string, NativeReasoningStep[]>>({});
```

c) In `applySnapshot`, immediately after the existing
`setRecentExecutionDetails(snapshot.recent_execution_details ?? {});`
add:

```typescript
    setRecentNativeTurnReasoning(snapshot.recent_native_turn_reasoning ?? {});
```

d) In the object returned by the hook (the context value that already lists `recentExecutionDetails,`), add immediately after it:

```typescript
    recentNativeTurnReasoning,
```

- [ ] **Step 3: Typecheck**

Run (from `src/newbro/ui`): `npx tsc --noEmit`
Expected: no output (clean). It compiles even though nothing consumes the new field yet.

- [ ] **Step 4: Commit**

```bash
git add src/newbro/ui/src/types.ts src/newbro/ui/src/NewbroShell.tsx
git commit -m "feat(ui): thread recentNativeTurnReasoning through shell context"
```

---

## Task 4: Frontend adapter `buildReasoningStepsForNativeTurn`

**Files:**
- Modify: `src/newbro/ui/src/components/newbro/adapters.ts`
- Test: `src/newbro/ui/src/components/newbro/adapters.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `src/newbro/ui/src/components/newbro/adapters.test.ts`. First ensure these are imported at the top of the file (extend existing imports):

```typescript
import { buildReasoningStepsForNativeTurn } from "./adapters";
import type { BroTimelineTurn, NativeReasoningStep } from "../../types";
```

Then add:

```typescript
describe("buildReasoningStepsForNativeTurn", () => {
  const baseTurn = {
    turn_id: "thread-1:outbound:c1",
    thread_id: "thread-1",
    persona_id: "forge",
    executor_id: "codex",
    owner: "executor",
    client_request_id: "c1",
    executor_thread_id: "native-1",
    executor_turn_id: "turn-1",
    input_modality: "text",
    user: null,
    assistant: null,
    task: null,
    status: "running",
    created_at: null,
    updated_at: null,
    metadata: {},
  } as unknown as BroTimelineTurn;

  const steps: NativeReasoningStep[] = [
    { item_id: "i1", text: "step one", kind: "progress", created_at: "t1" },
    { item_id: "i2", text: "step two", kind: "progress", created_at: "t2" },
  ];
  const map = { "codex::native-1::turn-1": steps };

  it("marks the last step active while the turn is running", () => {
    const result = buildReasoningStepsForNativeTurn(baseTurn, map);
    expect(result.map((s) => s.label)).toEqual(["step one", "step two"]);
    expect(result[0].status).toBe("done");
    expect(result[1].status).toBe("active");
  });

  it("marks all steps done once the turn is completed", () => {
    const completed = { ...baseTurn, status: "completed" } as BroTimelineTurn;
    const result = buildReasoningStepsForNativeTurn(completed, map);
    expect(result.every((s) => s.status === "done")).toBe(true);
  });

  it("returns nothing for tracked-run turns or missing identity", () => {
    const tracked = { ...baseTurn, task: { task_id: "t1" } } as unknown as BroTimelineTurn;
    expect(buildReasoningStepsForNativeTurn(tracked, map)).toEqual([]);
    const noIds = { ...baseTurn, executor_turn_id: null } as BroTimelineTurn;
    expect(buildReasoningStepsForNativeTurn(noIds, map)).toEqual([]);
    expect(buildReasoningStepsForNativeTurn(baseTurn, {})).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `src/newbro/ui`): `npx vitest run src/components/newbro/adapters.test.ts -t "buildReasoningStepsForNativeTurn"`
Expected: FAIL — `buildReasoningStepsForNativeTurn is not a function` / import error.

- [ ] **Step 3: Implement the adapter**

In `src/newbro/ui/src/components/newbro/adapters.ts`, the first import line is:

```typescript
import type { BroThread, BroTimelinePlan, ExecutionDetailEntry, ExecutionRun, Task, TaskStatus, TaskSummary } from "../../types";
```

`buildReasoningStepsForNativeTurn` needs `BroTimelineTurn` and `NativeReasoningStep`, which are **not** imported yet — add both:

```typescript
import type { BroThread, BroTimelinePlan, BroTimelineTurn, ExecutionDetailEntry, ExecutionRun, NativeReasoningStep, Task, TaskStatus, TaskSummary } from "../../types";
```

Then add this exported function just after `buildReasoningStepsForTurn`:

```typescript
export function buildReasoningStepsForNativeTurn(
  turn: BroTimelineTurn,
  recentNativeTurnReasoning: Record<string, NativeReasoningStep[]>,
): ReasoningStep[] {
  if (turn.task) return [];
  if (!turn.executor_thread_id || !turn.executor_turn_id) return [];
  const key = `${turn.executor_id}::${turn.executor_thread_id}::${turn.executor_turn_id}`;
  const steps = recentNativeTurnReasoning[key];
  if (!steps || steps.length === 0) return [];
  const inFlight = turn.status === "running" || turn.status === "pending";
  const lastIndex = steps.length - 1;
  return steps.map((step, index) => ({
    id: step.item_id || `${key}:${index}`,
    label: step.text,
    status: inFlight && index === lastIndex ? "active" : "done",
    created_at: step.created_at,
  }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `src/newbro/ui`): `npx vitest run src/components/newbro/adapters.test.ts -t "buildReasoningStepsForNativeTurn"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/components/newbro/adapters.ts src/newbro/ui/src/components/newbro/adapters.test.ts
git commit -m "feat(ui): add buildReasoningStepsForNativeTurn adapter"
```

---

## Task 5: Join native reasoning in `TimelineTurnView` (live stream + settled pill)

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `src/newbro/ui/src/__tests__/App.test.tsx` inside the main `describe("Newbro artboard shell", ...)` block (near the other timeline tests). This builds a settled native turn plus a reasoning map and asserts the "Reasoned" pill renders.

```typescript
  it("shows the Reasoned pill for a settled native codex turn", async () => {
    const snapshot = forgeSnapshot("session-existing");
    snapshot.bro_timeline_turns = [
      timelineTurn({
        thread_id: "codex-import-history",
        executor_turn_id: "turn-r1",
        executor_thread_id: "native-r1",
        userText: "Make the report",
        assistantText: "Done — report written.",
      }),
    ] as any;
    (snapshot as any).recent_native_turn_reasoning = {
      "codex::native-r1::turn-r1": [
        { item_id: "i1", text: "Reading the spec", kind: "progress", created_at: "t1" },
        { item_id: "i2", text: "Writing the section", kind: "progress", created_at: "t2" },
      ],
    };
    const importedThread = {
      thread_id: "codex-import-history",
      persona_id: "forge",
      persona_name: "Forge",
      executor_id: "codex",
      executor_node_id: "node-forge",
      execution_session_id: null,
      status: "completed",
      title: "Imported Codex thread",
      preview: "Remote history",
      progress: 100,
      task_ids: [],
      active_task_id: null,
      latest_task_id: null,
      has_resume_handle: true,
      updated_at: "2026-05-26T22:00:00+00:00",
      timeline_status: "loaded",
      timeline_error: null,
      diagnostics: { codex_thread_id: "codex-native-history" },
    };
    snapshot.bro_threads = [importedThread] as any;
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValue(snapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=codex-import-history");

    render(<RouterProvider router={getRouter()} />);

    const reasoned = await screen.findByRole("button", { name: /Reasoned/i });
    expect(reasoned).toBeInTheDocument();
    fireEvent.click(reasoned);
    expect(screen.getByText("Reading the spec")).toBeInTheDocument();
    expect(screen.getByText("Writing the section")).toBeInTheDocument();
  });
```

Note: if the `timelineTurn` helper does not already accept an `executor_thread_id` override, it does — it spreads `...overrides` and reads `overrides.executor_thread_id`. Confirm by reading the helper near the top of the test file; pass `executor_thread_id` as shown.

- [ ] **Step 2: Run test to verify it fails**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "Reasoned pill for a settled native codex turn"`
Expected: FAIL — no `Reasoned` button found (native steps are not joined yet).

- [ ] **Step 3: Join native reasoning in `TimelineTurnView`**

In `src/newbro/ui/src/ArtboardShell.tsx`:

a) Add `buildReasoningStepsForNativeTurn` to the existing import from `./components/newbro/adapters` (the line importing `buildReasoningStepsForTurn`, `type ReasoningStep`).

b) In `TimelineTurnView`, locate this existing block:

```typescript
  const reasoningSteps = buildReasoningStepsForTurn(activeRun, details);
  const settledReasoningSteps = activeRun ? [] : buildReasoningStepsForTurn(anyRun, details);
  const isTurnSettled = activeRun === null;
  const answerText = timelineMessageText(turn.assistant) || record?.summary?.trim() || record?.description?.trim() || "";
```

Replace it with:

```typescript
  const nativeReasoningSteps = buildReasoningStepsForNativeTurn(turn, shell.recentNativeTurnReasoning);
  const nativeInFlight = nativeReasoningSteps.length > 0 && (turn.status === "running" || turn.status === "pending");
  const nativeSettled = nativeReasoningSteps.length > 0 && !nativeInFlight;
  const reasoningSteps = nativeInFlight ? nativeReasoningSteps : buildReasoningStepsForTurn(activeRun, details);
  const settledReasoningSteps = nativeSettled
    ? nativeReasoningSteps
    : activeRun
      ? []
      : buildReasoningStepsForTurn(anyRun, details);
  const isTurnSettled = activeRun === null && !nativeInFlight;
  const answerText = timelineMessageText(turn.assistant) || record?.summary?.trim() || record?.description?.trim() || "";
```

This keeps tracked-run turns unchanged (`nativeReasoningSteps` is empty when `turn.task` is set), shows the live streaming bubble for a running native turn, and feeds the settled steps into `DTAnswerBubble` for a completed native turn.

- [ ] **Step 4: Run the new test to verify it passes**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "Reasoned pill for a settled native codex turn"`
Expected: PASS

- [ ] **Step 5: Run the full frontend suite + typecheck**

Run (from `src/newbro/ui`): `npx vitest run` then `npx tsc --noEmit`
Expected: all tests pass; tsc clean.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): show reasoning for native codex turns (stream + Reasoned pill)"
```

---

## Final verification

- [ ] Backend: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q` → all pass.
- [ ] Frontend (from `src/newbro/ui`): `npx vitest run` → all pass; `npx tsc --noEmit` → clean.
- [ ] Manual (optional, `newbro dev`): send a live message to a codex bro; the assistant bubble shows the live "is reasoning" stream while running and a "Reasoned" pill after it settles.

## Notes / gotchas

- The reasoning key string must match exactly on both sides: `f"{executor_id}::{executor_thread_id}::{executor_turn_id}"` (backend) and `` `${turn.executor_id}::${turn.executor_thread_id}::${turn.executor_turn_id}` `` (frontend). `executor_id` is `"codex"` for these turns.
- In-flight `running` status is only correct on the **WebSocket** snapshot path (`publish_snapshot(sync_imported_codex_threads=False)`), which the UI consumes. The REST `GET /sessions/{id}` re-syncs imported threads and can show the turn as `completed` mid-run — do not use REST polling to judge in-flight behavior.
- A native running turn shows nothing until its first `PROGRESS` step arrives (no steps yet → not treated as in-flight). This is a brief, acceptable gap and matches "no reasoning until the model produces some".
- Payload stays bounded: projection caps at 10 turns × 8 steps, each step text truncated to 280 chars; the store caps at 20 turns × 16 steps.
