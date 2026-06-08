# Thread-detail message render — test protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect the fragile thread-detail message rendering by extracting `TimelineTurnView`'s render decision into a pure, unit-tested `buildTurnRenderModel()` and adding backend gap tests — without changing any runtime behavior.

**Architecture:** A behavior-preserving 1:1 extraction moves the inline decision block (`clients/web/src/ArtboardShell.tsx:1126-1170`) into `clients/web/src/lib/turnRenderModel.ts`. A new `turnRenderModel.test.ts` pins a 7-case matrix (including the two refresh cases). Three backend tests close gaps in `tests/unit/runtime/test_bro_detail_thread_projection.py`. The AGENTS.md Golden Rule #3 owner list is updated, and its mandated guard tests are the regression gate.

**Tech Stack:** TypeScript, React, Vitest (web at `clients/web`); Python, Pytest (backend).

**Branch:** `test/thread-detail-render-protection` (already created and checked out).

---

## File Structure

- Create: `clients/web/src/lib/timelineMessage.ts` — single home for `timelineMessageText` (shared by component + new model).
- Create: `clients/web/src/lib/turnRenderModel.ts` — pure `buildTurnRenderModel()`; the extracted render decision.
- Create: `clients/web/src/lib/turnRenderModel.test.ts` — 7-case render-decision matrix.
- Modify: `clients/web/src/ArtboardShell.tsx` — import `timelineMessageText`; delegate `TimelineTurnView` to `buildTurnRenderModel`.
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py` — 3 backend gap tests.
- Modify: `AGENTS.md` — add `buildTurnRenderModel` to the Golden Rule #3 owner list.

---

## Task 1: Extract `timelineMessageText` into a shared module (no behavior change)

**Files:**
- Create: `clients/web/src/lib/timelineMessage.ts`
- Modify: `clients/web/src/ArtboardShell.tsx` (remove local def at lines 1003-1006; add import)
- Test: existing suites (regression gate)

- [ ] **Step 1: Create the shared module**

Create `clients/web/src/lib/timelineMessage.ts`:

```ts
import type { BroTimelineMessage } from "../types";

/** The display text of a timeline message: trimmed transcript for audio, trimmed text otherwise. */
export function timelineMessageText(message: BroTimelineMessage | null): string {
  if (!message) return "";
  return (message.kind === "audio" ? message.transcript : message.text)?.trim() ?? "";
}
```

- [ ] **Step 2: Remove the local definition in ArtboardShell**

In `clients/web/src/ArtboardShell.tsx`, delete these exact lines (1003-1006):

```ts
function timelineMessageText(message: BroTimelineMessage | null): string {
  if (!message) return "";
  return (message.kind === "audio" ? message.transcript : message.text)?.trim() ?? "";
}
```

- [ ] **Step 3: Add the import**

In `clients/web/src/ArtboardShell.tsx`, add after the existing `import { timelineRowKey } from "./lib/timelineRowKey";` line (line 28):

```ts
import { timelineMessageText } from "./lib/timelineMessage";
```

- [ ] **Step 4: Verify build/typecheck passes (the 3 call sites still resolve)**

Run: `cd clients/web && npm run build`
Expected: PASS (no TS errors; `timelineMessageText` resolves at the 3 call sites: lines ~1066, ~1085, ~1141).

- [ ] **Step 5: Commit**

```bash
cd /Users/zhangqianze/Documents/Newbro
git add clients/web/src/lib/timelineMessage.ts clients/web/src/ArtboardShell.tsx
git commit -m "refactor(ui): extract timelineMessageText into shared lib (no behavior change)"
```

---

## Task 2: Write the failing render-model matrix (TDD red)

**Files:**
- Create: `clients/web/src/lib/turnRenderModel.test.ts`
- Test: `clients/web/src/lib/turnRenderModel.test.ts`

- [ ] **Step 1: Write the test file**

Create `clients/web/src/lib/turnRenderModel.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildTurnRenderModel } from "./turnRenderModel";
import type {
  BroTimelineMessage,
  BroTimelineTurn,
  ExecutionDetailEntry,
  ExecutionRun,
  NativeReasoningStep,
} from "../types";

const NATIVE_KEY = "codex::native-1::turn-1";

function nativeTurn(over: Partial<BroTimelineTurn> = {}): BroTimelineTurn {
  return {
    turn_id: "codex-import-1:codex:turn-1",
    thread_id: "codex-import-1",
    persona_id: "forge",
    executor_id: "codex",
    owner: "executor",
    client_request_id: null,
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
    ...over,
  } as unknown as BroTimelineTurn;
}

function assistant(text: string, itemId = "a1"): BroTimelineMessage {
  return {
    message_id: "m1",
    role: "assistant",
    kind: "text",
    text,
    created_at: "t3",
    status: "running",
    metadata: { codex_item_id: itemId },
  } as unknown as BroTimelineMessage;
}

const commentary: NativeReasoningStep[] = [
  { item_id: "c1", text: "Reading", kind: "progress", created_at: "t1" },
  { item_id: "c2", text: "Editing", kind: "progress", created_at: "t2" },
];

const noDeps = { executionRuns: [], recentExecutionDetails: {}, recentNativeTurnReasoning: {} };

describe("buildTurnRenderModel", () => {
  it("case 1 — refresh-reconstructed in-flight commentary renders as reasoning, never the answer, never shimmer", () => {
    const model = buildTurnRenderModel(nativeTurn({ status: "running", assistant: null }), null, {
      ...noDeps,
      recentNativeTurnReasoning: { [NATIVE_KEY]: commentary },
    });
    expect(model.liveState).toEqual({ kind: "live", sub: "reasoning" });
    expect(model.activeCommentary).toBe("Editing");
    expect(model.stepsForBubble.map((s) => s.id)).toEqual(["c1"]);
    expect(model.answerText).toBe("");
    expect(model.settledHasNothing).toBe(false);
  });

  it("case 2 — in-flight with a streaming answer: answering, no commentary line, all steps compact", () => {
    const model = buildTurnRenderModel(
      nativeTurn({ status: "running", assistant: assistant("Partial answer") }),
      null,
      { ...noDeps, recentNativeTurnReasoning: { [NATIVE_KEY]: commentary } },
    );
    expect(model.liveState).toEqual({ kind: "live", sub: "answering" });
    expect(model.activeCommentary).toBeNull();
    expect(model.answerText).toBe("Partial answer");
    expect(model.stepsForBubble.map((s) => s.id)).toEqual(["c1", "c2"]);
  });

  it("case 3 — refresh after completion: settled answer with commentary as collapsed steps", () => {
    const settledSteps: NativeReasoningStep[] = [
      { item_id: "c1", text: "Working", kind: "progress", created_at: "t1" },
      { item_id: "a1", text: "Final answer", kind: "progress", created_at: "t2" },
    ];
    const model = buildTurnRenderModel(
      nativeTurn({ status: "completed", assistant: assistant("Final answer", "a1") }),
      null,
      { ...noDeps, recentNativeTurnReasoning: { [NATIVE_KEY]: settledSteps } },
    );
    expect(model.liveState).toEqual({ kind: "settled" });
    expect(model.answerText).toBe("Final answer");
    expect(model.stepsForBubble.map((s) => s.id)).toEqual(["c1"]);
    expect(model.settledHasNothing).toBe(false);
  });

  it("case 4 — settled with nothing renders nothing", () => {
    const model = buildTurnRenderModel(nativeTurn({ status: "completed", assistant: null }), null, noDeps);
    expect(model.liveState).toEqual({ kind: "settled" });
    expect(model.settledHasNothing).toBe(true);
  });

  it("case 5 — in-flight with no reasoning yet is connecting (the pre-seed shimmer state)", () => {
    const model = buildTurnRenderModel(nativeTurn({ status: "running", assistant: null }), null, noDeps);
    expect(model.liveState).toEqual({ kind: "live", sub: "connecting" });
    expect(model.activeCommentary).toBeNull();
    expect(model.stepsForBubble).toEqual([]);
    expect(model.settledHasNothing).toBe(false);
  });

  it("case 6 — a task-based turn draws reasoning from execution-run details, not native", () => {
    const run: ExecutionRun = {
      run_id: "r1",
      task_id: "task-1",
      execution_session_id: "es1",
      executor_type: "codex",
      status: "running",
      claimed_by: null,
      run_revision: 0,
      latest_progress_message: null,
      output_summary: null,
      block_reason: null,
      failure_reason: null,
      metadata: {},
    };
    const detail: ExecutionDetailEntry = {
      detail_id: "d1",
      task_id: "task-1",
      run_id: "r1",
      execution_session_id: "es1",
      event_type: "PROGRESS",
      text: "Compiling",
      created_at: "t1",
    };
    const turn = nativeTurn({ status: "running", task: { task_id: "task-1" } as unknown as BroTimelineTurn["task"] });
    const model = buildTurnRenderModel(turn, null, {
      executionRuns: [run],
      recentExecutionDetails: { "task-1": [detail] },
      recentNativeTurnReasoning: { [NATIVE_KEY]: commentary },
    });
    expect(model.liveState).toEqual({ kind: "live", sub: "reasoning" });
    expect(model.activeCommentary).toBe("Compiling");
    expect(model.stepsForBubble).toEqual([]);
  });

  it("case 7 — canStop is true while live with a task, false once settled", () => {
    const live = buildTurnRenderModel(
      nativeTurn({ status: "running", task: { task_id: "task-1" } as unknown as BroTimelineTurn["task"] }),
      null,
      { ...noDeps, recentNativeTurnReasoning: { [NATIVE_KEY]: commentary } },
    );
    expect(live.canStop).toBe(true);
    expect(live.stopTaskId).toBe("task-1");

    const settled = buildTurnRenderModel(
      nativeTurn({ status: "completed", task: { task_id: "task-1" } as unknown as BroTimelineTurn["task"] }),
      null,
      noDeps,
    );
    expect(settled.canStop).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd clients/web && npx vitest run src/lib/turnRenderModel.test.ts`
Expected: FAIL — `Failed to resolve import "./turnRenderModel"` (module does not exist yet).

- [ ] **Step 3: Commit the failing test**

```bash
cd /Users/zhangqianze/Documents/Newbro
git add clients/web/src/lib/turnRenderModel.test.ts
git commit -m "test(ui): add failing render-model matrix for thread-detail turns"
```

---

## Task 2.5: Note on case 5 (shimmer documentation)

Case 5 documents the pre-seed "connecting" state on purpose: it is the exact input that produced the shimmer regression, and case 1 shows that once reasoning is seeded the same turn renders as `reasoning`. Together they pin "seeding is what prevents the shimmer." No code in this task — it is a reading note for the implementer so case 5 is not mistaken for a bug.

---

## Task 3: Create `buildTurnRenderModel` (TDD green — verbatim extraction)

**Files:**
- Create: `clients/web/src/lib/turnRenderModel.ts`
- Test: `clients/web/src/lib/turnRenderModel.test.ts`

- [ ] **Step 1: Write the module (1:1 with ArtboardShell:1126-1170)**

Create `clients/web/src/lib/turnRenderModel.ts`:

```ts
import {
  buildReasoningStepsForNativeTurn,
  buildReasoningStepsForTurn,
  type ReasoningStep,
} from "../components/newbro/adapters";
import { deriveLiveTurnState, type LiveTurnState } from "./reasoningPhase";
import { splitLiveSteps } from "./splitLiveSteps";
import { timelineMessageText } from "./timelineMessage";
import type { BroTimelineTurn, ExecutionDetailEntry, ExecutionRun, NativeReasoningStep } from "../types";
import type { BroTaskRecord } from "../components/newbro/types";

export interface TurnRenderDeps {
  executionRuns: ExecutionRun[];
  recentExecutionDetails: Record<string, ExecutionDetailEntry[]>;
  recentNativeTurnReasoning: Record<string, NativeReasoningStep[]>;
}

export interface TurnRenderModel {
  liveState: LiveTurnState;
  activeCommentary: string | null;
  stepsForBubble: ReasoningStep[];
  dedupedSettledSteps: ReasoningStep[];
  answerText: string;
  settledHasNothing: boolean;
  canStop: boolean;
  stopTaskId: string | null;
}

/**
 * Decide how a single timeline turn renders. Pure: every input is passed in, so it
 * is unit-testable without React/shell context. This is the extracted decision that
 * was inline in TimelineTurnView; it owns the codex multi-message turn split on the
 * UI side (see AGENTS.md Golden Rule #3 and lib/splitLiveSteps).
 */
export function buildTurnRenderModel(
  turn: BroTimelineTurn,
  record: BroTaskRecord | null,
  deps: TurnRenderDeps,
): TurnRenderModel {
  const taskId = turn.task?.task_id ?? null;
  const activeRun = taskId
    ? (deps.executionRuns.find((r) => r.task_id === taskId && (r.status === "running" || r.status === "created" || r.status === "waiting_executor")) ?? null)
    : null;
  // For settled turns, find any run for this task (including completed runs).
  const anyRun = activeRun ?? (taskId ? (deps.executionRuns.find((r) => r.task_id === taskId) ?? null) : null);
  const details = taskId ? (deps.recentExecutionDetails[taskId] ?? null) : null;
  const nativeReasoningSteps = buildReasoningStepsForNativeTurn(turn, deps.recentNativeTurnReasoning);
  const nativeInFlight = nativeReasoningSteps.length > 0 && (turn.status === "running" || turn.status === "pending");
  const nativeSettled = nativeReasoningSteps.length > 0 && !nativeInFlight;
  const reasoningSteps = nativeInFlight ? nativeReasoningSteps : buildReasoningStepsForTurn(activeRun, details);
  const settledReasoningSteps = nativeSettled
    ? nativeReasoningSteps
    : activeRun
      ? []
      : buildReasoningStepsForTurn(anyRun, details);
  const answerText = timelineMessageText(turn.assistant) || record?.summary?.trim() || record?.description?.trim() || "";
  const rawAnswerItemId = turn.assistant?.metadata?.codex_item_id;
  const answerItemId = typeof rawAnswerItemId === "string" ? rawAnswerItemId : null;

  const liveState = deriveLiveTurnState({
    status: turn.status,
    stepCount: reasoningSteps.length,
    hasAnswer: answerText !== "",
  });
  // Codex multi-message turn split: while reasoning the latest step is the prominent
  // streaming commentary line and the rest are compact steps; on answering/settled
  // commentary collapses into the (deduped) step list and the final answer is the
  // answer. See lib/splitLiveSteps for the contract.
  const { activeCommentary, stepsForBubble, dedupedSettledSteps } = splitLiveSteps({
    liveState,
    reasoningSteps,
    settledReasoningSteps,
    answerItemId,
  });
  const stopTaskId = turn.task?.task_id ?? null;
  const canStop = liveState.kind !== "settled" && stopTaskId !== null;
  const settledHasNothing =
    liveState.kind === "settled" && answerText === "" && dedupedSettledSteps.length === 0;

  return {
    liveState,
    activeCommentary,
    stepsForBubble,
    dedupedSettledSteps,
    answerText,
    settledHasNothing,
    canStop,
    stopTaskId,
  };
}
```

- [ ] **Step 2: Run the matrix to verify it passes**

Run: `cd clients/web && npx vitest run src/lib/turnRenderModel.test.ts`
Expected: PASS (7 passed).

- [ ] **Step 3: Commit**

```bash
cd /Users/zhangqianze/Documents/Newbro
git add clients/web/src/lib/turnRenderModel.ts
git commit -m "feat(ui): add pure buildTurnRenderModel for thread-detail turn rendering"
```

---

## Task 4: Delegate `TimelineTurnView` to `buildTurnRenderModel` (behavior-preserving)

**Files:**
- Modify: `clients/web/src/ArtboardShell.tsx:1126-1170` (replace inline block) and import
- Test: existing UI suites + build (regression gate)

- [ ] **Step 1: Add the import**

In `clients/web/src/ArtboardShell.tsx`, add after the `import { timelineMessageText } from "./lib/timelineMessage";` line:

```ts
import { buildTurnRenderModel } from "./lib/turnRenderModel";
```

- [ ] **Step 2: Replace the inline decision block**

In `TimelineTurnView`, replace the block from `// Reasoning bubble — rendered for...` (line 1125) through the `settledHasNothing` declaration (line 1170) — i.e. everything between `const proposalRequests = ...` and the `return (` — with:

```ts
  const { liveState, activeCommentary, stepsForBubble, answerText, settledHasNothing, canStop, stopTaskId } =
    buildTurnRenderModel(turn, record, {
      executionRuns: shell.executionRuns,
      recentExecutionDetails: shell.recentExecutionDetails,
      recentNativeTurnReasoning: shell.recentNativeTurnReasoning,
    });
  const onStop = () => { if (stopTaskId) shell.cancelTask(stopTaskId); };

  const downloadContext =
    sessionId && turn.thread_id && turn.turn_id && workspaceRoot
      ? { sessionId, threadId: turn.thread_id, turnId: turn.turn_id, workspaceRoot }
      : undefined;
```

The `return (...)` JSX below stays exactly as-is (it already references `liveState`, `stepsForBubble`, `activeCommentary`, `answerText`, `settledHasNothing`, `canStop`, `onStop`, `downloadContext`).

- [ ] **Step 3: Confirm no now-unused imports remain**

`deriveLiveTurnState`, `splitLiveSteps`, `buildReasoningStepsForNativeTurn`, `buildReasoningStepsForTurn` may no longer be used directly in `ArtboardShell.tsx`. Check:

Run: `cd clients/web && grep -nE "deriveLiveTurnState|splitLiveSteps|buildReasoningStepsForNativeTurn|buildReasoningStepsForTurn" src/ArtboardShell.tsx`
Expected: only the `import` lines appear (no call sites). If an import is now unused, remove just that symbol from its import statement to keep the build clean (note: `buildBroCardModels`, `buildBroThreadRecords`, `ReasoningStep` in the same import line may still be used — keep those).

- [ ] **Step 4: Run the full web build/typecheck**

Run: `cd clients/web && npm run build`
Expected: PASS (no unused-symbol or type errors).

- [ ] **Step 5: Run the AGENTS.md-mandated UI guard + related suites (must stay green, unchanged)**

Run: `cd clients/web && npx vitest run src/lib/splitLiveSteps.test.ts src/lib/reasoningPhase.test.ts src/LiveTurnBubble.test.tsx src/components/newbro/adapters.test.ts src/lib/turnRenderModel.test.ts`
Expected: PASS (all suites green; none edited).

- [ ] **Step 6: Commit**

```bash
cd /Users/zhangqianze/Documents/Newbro
git add clients/web/src/ArtboardShell.tsx
git commit -m "refactor(ui): TimelineTurnView delegates to buildTurnRenderModel (no behavior change)"
```

---

## Task 5: Backend — lifecycle on the seed path (commentary stays reasoning while final answer settles)

**Files:**
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py` (append test)
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`

- [ ] **Step 1: Write the test (append at end of file)**

```python
@pytest.mark.anyio
async def test_seeded_in_flight_turn_settles_final_answer_keeping_commentary_reasoning(
    monkeypatch: pytest.MonkeyPatch,
):
    # Load an in-flight commentary turn (seeds native reasoning, assistant empty),
    # then a final_answer arrives over the subscription: the answer settles into the
    # assistant slot while the commentary remains a reasoning step (not duplicated).
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    projection = session._bro_detail_thread_projection()
    _register_imported_codex_thread(projection, persona)

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "Reading", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)

    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )

    projection.selected_codex_thread_subscriptions["forge"] = SelectedCodexThreadSubscription(
        subscription_id="sub-1",
        persona_id="forge",
        public_thread_id="codex-import-1",
        thread_continuity_key="codex-import-1",
        node_id="node-forge",
        codex_thread_id="native-thread-1",
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle="native-thread-1"),
    )

    await projection.handle_codex_thread_event(
        CodexThreadEventMessage.model_validate(
            {
                "subscription_id": "sub-1",
                "node_id": "node-forge",
                "session_id": session.session_id,
                "target_persona_id": "forge",
                "target_thread_id": "codex-import-1",
                "thread_id": "native-thread-1",
                "method": "item/completed",
                "params": {
                    "turnId": "turn-live",
                    "item": {
                        "type": "agentMessage",
                        "id": "a1",
                        "text": "Done",
                        "phase": "final_answer",
                        "status": "completed",
                    },
                },
            }
        )
    )

    turns = projection.bro_thread_executor_turns.get("codex-import-1") or []
    turn = next(t for t in turns if t.executor_turn_id == "turn-live")
    assert turn.assistant is not None and turn.assistant.text == "Done"

    recent = session._recent_native_turn_reasoning()
    assert recent.get("codex::native-thread-1::turn-live") is not None
    assert [s.text for s in recent["codex::native-thread-1::turn-live"]] == ["Reading"]
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_seeded_in_flight_turn_settles_final_answer_keeping_commentary_reasoning -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/runtime/test_bro_detail_thread_projection.py
git commit -m "test(runtime): lock final-answer settle keeps seeded commentary as reasoning"
```

---

## Task 6: Backend — publish-on-seed delivery

**Files:**
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py` (append test)
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`

- [ ] **Step 1: Write the test (append at end of file)**

```python
@pytest.mark.anyio
async def test_list_bro_timeline_page_publishes_only_when_it_seeds_reasoning(
    monkeypatch: pytest.MonkeyPatch,
):
    # list_bro_timeline_page must publish a snapshot when it seeds in-flight commentary
    # (so a refreshed client receives it promptly) and must NOT publish when there is
    # nothing to seed.
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)

    publish_calls: list[str] = []

    async def counting_publish() -> object:
        publish_calls.append("published")
        return None

    seeded_calls: list[tuple[str, str, str]] = []

    def record_history(executor_id, executor_thread_id, executor_turn_id, steps):
        seeded_calls.append((executor_id, executor_thread_id, executor_turn_id))

    projection = BroDetailThreadProjection(
        session_id=session.session_id,
        blackboard=session.blackboard,
        executor_node_manager=session.executor_node_manager,
        interaction_manager=session.interaction_manager,
        observability=session.observability,
        publish_snapshot=counting_publish,
        record_history_native_reasoning=record_history,
    )
    _register_imported_codex_thread(projection, persona)

    async def in_flight_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "Reading", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", in_flight_turns)
    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )
    assert seeded_calls == [("codex", "native-thread-1", "turn-live")]
    assert len(publish_calls) == 1

    async def completed_only_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-done",
                    "status": "completed",
                    "items": [
                        {"type": "agentMessage", "id": "a1", "text": "Done", "phase": "final_answer"},
                    ],
                    "startedAt": 1780650000,
                    "completedAt": 1780650010,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", completed_only_turns)
    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )
    # No new seed -> no new publish.
    assert len(publish_calls) == 1
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_list_bro_timeline_page_publishes_only_when_it_seeds_reasoning -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/runtime/test_bro_detail_thread_projection.py
git commit -m "test(runtime): list_bro_timeline_page publishes only when it seeds reasoning"
```

---

## Task 7: Backend — live store is authoritative (history seeding never clobbers it)

**Files:**
- Modify: `tests/unit/runtime/test_bro_detail_thread_projection.py` (append test)
- Test: `tests/unit/runtime/test_bro_detail_thread_projection.py`

- [ ] **Step 1: Write the test (append at end of file)**

```python
@pytest.mark.anyio
async def test_history_seeding_does_not_clobber_live_native_reasoning(
    monkeypatch: pytest.MonkeyPatch,
):
    # If the live native-reasoning store already holds a turn (in-session dispatch),
    # loading history must NOT overwrite it with the (possibly staler) history items.
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    persona = Persona(
        persona_id="forge",
        name="Forge",
        avatar="bro",
        base_prompt="",
        executor_node_id="node-forge",
        bro_detail_session_id="detail-forge",
        status="idle",
    )
    await session.blackboard.put_persona(persona)
    projection = session._bro_detail_thread_projection()
    _register_imported_codex_thread(projection, persona)

    key = "codex::native-thread-1::turn-live"
    session._native_turn_reasoning[key] = [
        NativeReasoningStep(item_id="live", text="LIVE step", kind="progress", created_at="t9"),
    ]

    async def fake_request_codex_thread_turns(**kwargs):
        return CodexThreadTurnPage(
            thread_id="native-thread-1",
            turns=[
                {
                    "id": "turn-live",
                    "status": "inProgress",
                    "items": [
                        {"type": "agentMessage", "id": "c1", "text": "HISTORY step", "phase": "commentary"},
                    ],
                    "startedAt": 1780650000,
                }
            ],
            next_cursor=None,
            previous_cursor=None,
        )

    monkeypatch.setattr(session.executor_node_manager, "request_codex_thread_turns", fake_request_codex_thread_turns)
    await projection.list_bro_timeline_page(
        persona=persona, public_thread_id="codex-import-1", node_id="node-forge"
    )

    assert [s.text for s in session._native_turn_reasoning[key]] == ["LIVE step"]
```

This requires `NativeReasoningStep` to be importable in the test module.

- [ ] **Step 2: Add the import if missing**

Run: `grep -n "NativeReasoningStep" tests/unit/runtime/test_bro_detail_thread_projection.py`
If there is no import, add `NativeReasoningStep` to the `from newbro.protocol import (...)` block at the top of the file (alongside `CodexThreadEventMessage`).

- [ ] **Step 3: Run it**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_bro_detail_thread_projection.py::test_history_seeding_does_not_clobber_live_native_reasoning -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/runtime/test_bro_detail_thread_projection.py
git commit -m "test(runtime): history seeding never clobbers the live native-reasoning store"
```

---

## Task 8: Update the AGENTS.md contract owner list

**Files:**
- Modify: `AGENTS.md` (Golden Rule #3, owner sentence)

- [ ] **Step 1: Edit the owner list**

In `AGENTS.md`, in the Golden Rule #3 paragraph, find:

```
and `splitLiveSteps` + `LiveTurnBubble` (`clients/web/src/`).
```

Replace with:

```
and `splitLiveSteps` + `buildTurnRenderModel` + `LiveTurnBubble` (`clients/web/src/`).
```

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): add buildTurnRenderModel to codex turn contract owners"
```

---

## Task 9: Full regression gate (AGENTS.md guard set + fixture) and final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the AGENTS.md-mandated backend guards + new backend tests**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_codex_multi_message_turn.py tests/unit/runtime/test_session_runtime.py tests/unit/runtime/test_bro_detail_thread_projection.py -q`
Expected: PASS (real-wire replay, commentary/`_merge_timeline_turn`/`selected_codex_thread` tests, and the new projection tests all green).

- [ ] **Step 2: Run the AGENTS.md-mandated UI guard + new UI matrix + web build**

Run: `cd clients/web && npx vitest run src/lib/splitLiveSteps.test.ts src/lib/reasoningPhase.test.ts src/LiveTurnBubble.test.tsx src/components/newbro/adapters.test.ts src/lib/turnRenderModel.test.ts && npm run build`
Expected: PASS (all suites green; build/typecheck clean).

- [ ] **Step 3: Re-verify the fixture is still the source for the wire replay**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_codex_multi_message_turn.py::test_real_wire_replay_commentary_never_settles_or_fills_answer -v`
Expected: PASS (replays `docs/protocol/fixtures/codex-multi-message-turn-sample.jsonl`).

- [ ] **Step 4: Confirm no `docs/memories.md` change was made**

Run: `git status --short docs/memories.md`
Expected: no output (per AGENTS.md, test-only + behavior-preserving refactor → no memory entry).

- [ ] **Step 5: Push the branch**

```bash
git push origin test/thread-detail-render-protection
```

---

## Self-Review

**Spec coverage:**
- Behavior-preserving extraction → Tasks 1, 3, 4. ✓
- 7-case UI matrix (incl. refresh-reconstructed in-flight + refresh-after-completion) → Task 2 (cases 1 & 3 are the refresh cases). ✓
- Backend gap tests: lifecycle on seed path → Task 5; publish-on-seed → Task 6; live-authoritative guard → Task 7. ✓
- AGENTS.md guard set as regression gate → Tasks 4 & 9. ✓
- AGENTS.md owner-list update → Task 8. ✓
- No `docs/memories.md` change → Task 9 Step 4. ✓
- NewbroShell reconciliation-ordering gap is deferred to #70 (spec §4) — intentionally no task here. ✓

**Placeholder scan:** No TBD/TODO; every code step contains full code and exact commands. ✓

**Type consistency:** `buildTurnRenderModel(turn, record, deps)` and the `TurnRenderModel`/`TurnRenderDeps` shapes are identical across Task 2 (test), Task 3 (impl), Task 4 (call site). `record_history_native_reasoning` signature in Task 6 matches the existing `(executor_id, executor_thread_id, executor_turn_id, steps)` callback. ✓
