# Thread-detail message rendering — test protection

## Problem

The thread-detail message area is the most fragile, most critical part of the app.
A chain of recent bugs (commentary rendering below the answer after refresh;
"connecting" shimmer on a fresh in-flight view; cross-profile invisibility) all
shared one trait: **the isolated units were green the whole time**. The bugs lived
in the *assembly seam* — where raw inputs are selected and combined into a render
decision — which is not directly tested.

### What is already well covered
- `clients/web/src/lib/splitLiveSteps.test.ts` — commentary/step split per state.
- `clients/web/src/lib/reasoningPhase.test.ts` — `deriveLiveTurnState` across statuses.
- `clients/web/src/LiveTurnBubble.test.tsx` — per-state rendering, commentary-above-steps, transitions.
- `clients/web/src/components/newbro/adapters.test.ts` — `buildReasoningStepsForTurn` / `buildReasoningStepsForNativeTurn`.
- Backend `tests/unit/runtime/test_bro_detail_thread_projection.py` and
  `test_codex_multi_message_turn.py` — codex turn-content derivation + real-wire contract.

### The untested seam
`TimelineTurnView` in `clients/web/src/ArtboardShell.tsx:1126-1170` decides, from
`turn` + `executionRuns` + `recentExecutionDetails` + `recentNativeTurnReasoning`:
which reasoning source wins (`nativeInFlight` vs run-details), commentary-vs-answer
placement, `liveState`, and `settledHasNothing`. It is buried inline in a
~4400-line component; the only full-render suite (`App.test.tsx`) is order/timing
flaky, so this logic is effectively unprotected.

## Goals
1. Make the UI assembly seam unit-testable **without** introducing flakiness.
2. Lock the codex-turn render contract — including the refresh case — at both layers.
3. **Do not change any runtime behavior.** The extraction must be 1:1; existing
   suites + typecheck/build are the regression gate.

## Non-goals
- No redesign of the reasoning/answer derivation (that is the consolidation tracked
  in issue #70). This is test protection plus a behavior-preserving extraction.
- No new end-to-end/RTL thread-view harness (flakiness risk).

## Design

### 1. UI — extract `buildTurnRenderModel` (behavior-preserving)
New pure module `clients/web/src/lib/turnRenderModel.ts`:

```ts
interface TurnRenderDeps {
  executionRuns: ExecutionRun[];
  recentExecutionDetails: Record<string, ExecutionDetailEntry[]>;
  recentNativeTurnReasoning: Record<string, NativeReasoningStep[]>;
}

interface TurnRenderModel {
  liveState: LiveTurnState;
  activeCommentary: string | null;
  stepsForBubble: ReasoningStep[];
  dedupedSettledSteps: ReasoningStep[];
  answerText: string;
  settledHasNothing: boolean;
  canStop: boolean;
  stopTaskId: string | null;
}

function buildTurnRenderModel(
  turn: BroTimelineTurn,
  record: BroTaskRecord | null,   // from timelineTaskRecord(turn), still computed in the component
  deps: TurnRenderDeps,
): TurnRenderModel
```

- The body is a **verbatim move** of the expressions at `ArtboardShell.tsx:1126-1170`
  (`taskId`, `activeRun`, `anyRun`, `details`, `nativeReasoningSteps`,
  `nativeInFlight`, `nativeSettled`, `reasoningSteps`, `settledReasoningSteps`,
  `answerText`, `answerItemId`, `liveState`, `splitLiveSteps(...)`, `canStop`,
  `settledHasNothing`). Same expressions, same order, no logic change.
- `TimelineTurnView` shrinks to: compute `record = timelineTaskRecord(turn)`, call
  `buildTurnRenderModel`, and spread the result into `<LiveTurnBubble>`. `record`,
  `proposalRequests`, `downloadContext`, and `onStop` stay in the component — they
  are rendering/wiring, not decision logic.
- `record` is passed in (not computed inside) to avoid dragging `timelineTaskRecord`
  and its helper chain out of the component; tests pass `null` for native codex turns.

**No-break guarantee.** Because this is a 1:1 extraction, all existing UI tests
(`LiveTurnBubble`, `splitLiveSteps`, `reasoningPhase`, `adapters`) plus
`tsc`/`vite build` must stay green unchanged. If any behavior would change, stop and
reassess rather than adjusting a test to match.

### 2. UI — `clients/web/src/lib/turnRenderModel.test.ts`
The contract that broke, pinned at the seam. Each case asserts the full output.

| # | Scenario | Inputs | Expected |
|---|----------|--------|----------|
| 1 | **Refresh-reconstructed in-flight (commentary only)** | turn status `running`, `assistant=null`, `recentNativeTurnReasoning` has 2 commentary steps | `liveState=reasoning`; `activeCommentary` = last step; `stepsForBubble` excludes last; `answerText===""`; **`settledHasNothing===false`** (guards the shimmer regression) |
| 2 | In-flight, commentary + streaming answer | running, `assistant.text` set, native steps present | `liveState=answering`; `activeCommentary===null`; `answerText` set |
| 3 | **Refresh after completion (settled)** | status `completed`, `assistant` final answer, native steps incl. answer item | `liveState=settled`; `answerText` set; `dedupedSettledSteps` excludes the answer item |
| 4 | Settled empty | `completed`, no assistant, no steps | `settledHasNothing===true` |
| 5 | Source precedence — native wins | running, native steps present AND an activeRun+details also present | reasoning steps come from native, not run-details |
| 6 | Source path — run details | `turn.task` set, native ignored, activeRun + PROGRESS details | reasoning steps from `buildReasoningStepsForTurn`; `liveState` reflects them |
| 7 | `canStop` | live with `turn.task.task_id` vs settled | `true` while live w/ task; `false` when settled |

### 3. Backend — close remaining gaps
Add to `tests/unit/runtime/test_bro_detail_thread_projection.py`:
- **Lifecycle on the seeding path:** load an in-flight commentary turn (seeds native
  reasoning, `assistant=null`); then apply a `final_answer` item/completed event →
  assert the answer settles into `assistant` and the commentary remains reasoning
  (not duplicated into the answer).
- **Delivery — publish on seed:** `list_bro_timeline_page` calls `publish_snapshot`
  exactly when it seeds reasoning for an in-flight turn (the mechanism that makes a
  refreshed client receive the commentary promptly), and does **not** publish when
  there is nothing to seed.
- **Live-authoritative guard:** when `recentNativeTurnReasoning` already holds the
  turn (live dispatch in-session), history seeding must not overwrite it.

### 4. Documented gap (deferred)
The `NewbroShell` reload reconciliation — initial `getSessionSnapshot` →
`listBroTimelinePage` turns → socket snapshot pushes — has an ordering dimension a
pure-function test cannot capture, and a full RTL harness would inherit the known
`App.test.tsx` flakiness. This is **explicitly out of scope** here and recorded on
issue #70 as a follow-up (needs a non-flaky integration harness).

## Testing & verification
- New: `turnRenderModel.test.ts` (7 cases) + 3 backend projection tests.
- Regression gate (must stay green, unchanged): existing UI suites,
  `npm run typecheck`/`build` in `clients/web`, and `pytest tests/unit/runtime`.
- The extraction is considered correct only if the pre-existing suites pass without
  edits.

## Acceptance criteria
- `buildTurnRenderModel` exists as a pure function; `TimelineTurnView` delegates to it
  with no behavior change.
- The 7-case UI matrix and 3 backend tests pass.
- All pre-existing thread-detail tests pass unchanged.
- The NewbroShell reconciliation-ordering gap is noted on #70.
