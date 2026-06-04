# Smooth Assistant Response Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the assistant response feel continuously alive and smooth from the moment the user hits send until the final answer is complete, eliminating the three "dead" gaps (optimistic→canonical remount, executor spin-up blank void, and the loading cue dying when answer streaming begins).

**Architecture:** Replace the `ack | streaming | done` phase split (`ReasoningBubble` + a separate `SettledAnswerBubble`) with a single `LiveTurnBubble` that owns the whole turn lifecycle. The state model becomes **live (connecting → reasoning → answering) vs settled**, where `settled` is reached only at a terminal turn status — not the first answer token. Timeline rows are keyed by a stable identity so the optimistic→canonical handoff reuses the same DOM. Frontend-only.

**Tech Stack:** React + TypeScript + Vite, Vitest + @testing-library/react (happy-dom), plain CSS (`variants-desktop.css`, `variants-mobile-design.css`).

**Spec:** `docs/superpowers/specs/2026-06-03-smooth-assistant-response-animation-design.md`

---

## File Structure

- `src/newbro/ui/src/lib/reasoningPhase.ts` — **modify.** Replace `deriveReasoningPhase` with `deriveLiveTurnState` and the `LiveTurnState` type.
- `src/newbro/ui/src/LiveTurnBubble.tsx` — **create.** The unified component (live + settled, desktop + mobile). Replaces `ReasoningBubble.tsx`.
- `src/newbro/ui/src/LiveTurnBubble.test.tsx` — **create.** Component tests. Replaces `ReasoningBubble.test.tsx`.
- `src/newbro/ui/src/lib/timelineRowKey.ts` — **create.** Pure helper for stable list keys.
- `src/newbro/ui/src/lib/timelineRowKey.test.ts` — **create.** Tests for the helper.
- `src/newbro/ui/src/ArtboardShell.tsx` — **modify.** `TimelineTurnView` render branch, remove `SettledAnswerBubble`, use the new deriver and stable keys.
- `src/newbro/ui/src/styles/variants-desktop.css` — **modify.** Caret, divider, body crossfade, reduced-motion.
- `src/newbro/ui/src/styles/variants-mobile-design.css` — **modify.** Same, `thr-` variant.
- `src/newbro/ui/src/ReasoningBubble.tsx` / `ReasoningBubble.test.tsx` — **delete** (after the refactor lands).

**Commands** (run from `src/newbro/ui`):
- Single test file: `npx vitest run src/<file>`
- Full suite: `npm test`
- Type-check + build: `npm run build`

---

## Task 0: Commit the in-progress streaming-progress edits

The working tree already contains coherent in-progress edits (a `StreamingProgress` shimmer added to the streaming phase plus its CSS). Commit them first so the refactor starts from a clean tree and these classes are preserved.

**Files:**
- Modify (already edited, uncommitted): `src/newbro/ui/src/ReasoningBubble.tsx`, `src/newbro/ui/src/ReasoningBubble.test.tsx`, `src/newbro/ui/src/styles/variants-desktop.css`, `src/newbro/ui/src/styles/variants-mobile-design.css`

- [ ] **Step 1: Confirm the suite is green with the current edits**

Run: `cd src/newbro/ui && npm test`
Expected: PASS (the existing `ReasoningBubble` tests pass).

- [ ] **Step 2: Commit the in-progress work**

```bash
git add src/newbro/ui/src/ReasoningBubble.tsx src/newbro/ui/src/ReasoningBubble.test.tsx \
        src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/styles/variants-mobile-design.css
git commit -m "Add streaming progress shimmer to reasoning bubble"
```

---

## Task 1: New live-turn state deriver

Replace the 3-value phase with a `live | settled` model. `settled` is reached only at a terminal status; everything else is live, so no status can fall through to blank.

**Files:**
- Modify: `src/newbro/ui/src/lib/reasoningPhase.ts`
- Test: `src/newbro/ui/src/lib/reasoningPhase.test.ts` (create)

- [ ] **Step 1: Write the failing test**

Create `src/newbro/ui/src/lib/reasoningPhase.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { deriveLiveTurnState } from "./reasoningPhase";

describe("deriveLiveTurnState", () => {
  it("terminal statuses settle", () => {
    for (const status of ["completed", "failed", "cancelled"]) {
      expect(deriveLiveTurnState({ status, stepCount: 0, hasAnswer: false })).toEqual({ kind: "settled" });
    }
  });

  it("a settled turn stays settled even with steps and an answer", () => {
    expect(deriveLiveTurnState({ status: "completed", stepCount: 3, hasAnswer: true })).toEqual({ kind: "settled" });
  });

  it("optimistic/pending with nothing yet is live:connecting", () => {
    expect(deriveLiveTurnState({ status: "pending", stepCount: 0, hasAnswer: false })).toEqual({ kind: "live", sub: "connecting" });
  });

  it("every non-terminal status stays live (never blank) during executor spin-up", () => {
    for (const status of ["created", "queued", "waiting_executor", "running", "anything-unexpected"]) {
      expect(deriveLiveTurnState({ status, stepCount: 0, hasAnswer: false })).toEqual({ kind: "live", sub: "connecting" });
    }
  });

  it("steps but no answer is live:reasoning", () => {
    expect(deriveLiveTurnState({ status: "running", stepCount: 2, hasAnswer: false })).toEqual({ kind: "live", sub: "reasoning" });
  });

  it("an answer while still non-terminal is live:answering (cue must stay)", () => {
    expect(deriveLiveTurnState({ status: "running", stepCount: 2, hasAnswer: true })).toEqual({ kind: "live", sub: "answering" });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd src/newbro/ui && npx vitest run src/lib/reasoningPhase.test.ts`
Expected: FAIL — `deriveLiveTurnState` is not exported.

- [ ] **Step 3: Replace the deriver implementation**

Replace the entire contents of `src/newbro/ui/src/lib/reasoningPhase.ts` with:

```ts
export type LiveTurnSubState = "connecting" | "reasoning" | "answering";

export type LiveTurnState =
  | { kind: "settled" }
  | { kind: "live"; sub: LiveTurnSubState };

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * State of the assistant's turn. "live" is the default; "settled" is the single
 * explicit end state, reached ONLY at a terminal turn status — not when the
 * first answer token arrives. This keeps the live cue visible while the answer
 * streams, and guarantees that no intermediate or unknown status (created,
 * queued, waiting_executor, …) can fall through to a blank render.
 */
export function deriveLiveTurnState(input: {
  status: string;     // BroTimelineTurn["status"]
  stepCount: number;  // reasoningSteps.length
  hasAnswer: boolean; // answerText !== ""
}): LiveTurnState {
  if (TERMINAL_STATUSES.has(input.status)) return { kind: "settled" };
  if (input.hasAnswer) return { kind: "live", sub: "answering" };
  if (input.stepCount > 0) return { kind: "live", sub: "reasoning" };
  return { kind: "live", sub: "connecting" };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd src/newbro/ui && npx vitest run src/lib/reasoningPhase.test.ts`
Expected: PASS (6 tests).

> Note: `deriveReasoningPhase` is now removed, so `ArtboardShell.tsx` will not type-check until Task 4. Do not run `npm run build` yet. The unit test above is the gate for this task.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/lib/reasoningPhase.ts src/newbro/ui/src/lib/reasoningPhase.test.ts
git commit -m "Replace reasoning phase with live-turn state deriver"
```

---

## Task 2: The unified LiveTurnBubble component

One component renders all four states (connecting, reasoning, answering, settled) for both desktop (`dt-`) and mobile (`thr-`), via a per-platform class map. The answer markdown sits in a stable slot so it survives the answering→settled transition without remounting.

**Files:**
- Create: `src/newbro/ui/src/LiveTurnBubble.tsx`
- Test: `src/newbro/ui/src/LiveTurnBubble.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/newbro/ui/src/LiveTurnBubble.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LiveTurnBubble } from "./LiveTurnBubble";

const steps = [{ id: "s1", label: "Reading the repo" }, { id: "s2", label: "Drafting a plan" }];

describe("LiveTurnBubble", () => {
  it("connecting renders the shimmer skeleton + alive orb and no steps", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "connecting" }} steps={[]} answer="" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).not.toBeNull();
    expect(container.querySelector(".dt-reason-orb")).not.toBeNull();
    expect(container.querySelector(".dt-reason-steps")).toBeNull();
    expect(screen.getByText(/Atlas is working/)).toBeTruthy();
  });

  it("reasoning renders the step list, progress shimmer, and alive orb", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).toBeNull();
    expect(container.querySelectorAll(".dt-reason-step").length).toBe(2);
    expect(container.querySelector(".dt-reason-stream-progress")).not.toBeNull();
    expect(container.querySelector(".dt-reason-orb")).not.toBeNull();
  });

  it("answering streams the answer while keeping steps, the alive orb, and a caret", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "answering" }} steps={steps} answer="Here is the answer" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-orb")).not.toBeNull();
    expect(container.querySelector(".dt-reason-caret")).not.toBeNull();
    expect(container.querySelectorAll(".dt-reason-step").length).toBe(2);
    expect(screen.getByText(/Here is the answer/)).toBeTruthy();
  });

  it("settled shows the answer with no alive cue, no header, no Stop", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "settled" }} steps={steps} answer="Final answer" mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-orb")).toBeNull();
    expect(container.querySelector(".dt-reason-caret")).toBeNull();
    expect(screen.queryByText(/Atlas is working/)).toBeNull();
    expect(screen.getByText(/Final answer/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /stop/i })).toBeNull();
  });

  it("settled offers a Show all toggle when there are more than 3 steps", () => {
    const many = [1, 2, 3, 4, 5].map((n) => ({ id: `s${n}`, label: `Step ${n}` }));
    render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "settled" }} steps={many} answer="Done" mobile={false} canStop={false} onStop={() => {}} />,
    );
    const toggle = screen.getByRole("button", { name: /show all 5 steps/i });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /hide steps/i })).toBeTruthy();
  });

  it("uses thr- classes on mobile", () => {
    const { container } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".thr-reason")).not.toBeNull();
    expect(container.querySelectorAll(".thr-reason-step").length).toBe(2);
  });

  it("shows Stop while live and fires onStop; hidden when !canStop", () => {
    const onStop = vi.fn();
    const { rerender } = render(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile={false} canStop onStop={onStop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /stop/i }));
    expect(onStop).toHaveBeenCalledTimes(1);
    rerender(
      <LiveTurnBubble broName="Atlas" state={{ kind: "live", sub: "reasoning" }} steps={steps} answer="" mobile={false} canStop={false} onStop={onStop} />,
    );
    expect(screen.queryByRole("button", { name: /stop/i })).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd src/newbro/ui && npx vitest run src/LiveTurnBubble.test.tsx`
Expected: FAIL — cannot resolve `./LiveTurnBubble`.

- [ ] **Step 3: Implement the component**

Create `src/newbro/ui/src/LiveTurnBubble.tsx`:

```tsx
import { useState } from "react";
import type { LiveTurnState } from "./lib/reasoningPhase";
import { MarkdownText, type MarkdownDownloadContext } from "./components/ui/markdown-text";

export interface ReasoningStepView {
  id: string;
  label: string;
}

const WINDOW = 3;
const FADE = [1, 0.55, 0.26];
const SETTLED_COLLAPSED = 3;

function windowed(steps: ReasoningStepView[]) {
  const startAt = Math.max(0, steps.length - WINDOW);
  return steps.slice(startAt, steps.length);
}

interface ClassMap {
  turn: string;
  bubbleLive: string;
  bubbleSettled: string;
  head: string;
  kicker: string;
  orb: string;
  stop: string;
  skeleton: string;
  steps: string;
  stepsStatic: string;
  step: string;
  stepActive: string;
  stepDone: string;
  mark: string;
  text: string;
  streamProgress: string;
  divider: string;
  answer: string;
  caret: string;
  collapsed: string;
  collapsedOpen: string;
  chev: string;
  meta: string;
}

const DESKTOP: ClassMap = {
  turn: "dt-turn dt-turn-bro",
  bubbleLive: "dt-bubble dt-bubble-bro dt-bubble-reason",
  bubbleSettled: "dt-bubble dt-bubble-bro dt-bubble-answer",
  head: "dt-reason-head",
  kicker: "dt-reason-kicker",
  orb: "dt-reason-orb",
  stop: "dt-reason-stop",
  skeleton: "dt-reason-skeleton",
  steps: "dt-reason-steps",
  stepsStatic: "dt-reason-steps dt-reason-steps-static",
  step: "dt-reason-step",
  stepActive: "dt-reason-step-active",
  stepDone: "dt-reason-step-done",
  mark: "dt-reason-step-mark",
  text: "dt-reason-step-text",
  streamProgress: "dt-reason-stream-progress",
  divider: "dt-reason-divider",
  answer: "dt-answer-text",
  caret: "dt-reason-caret",
  collapsed: "dt-reason-collapsed",
  collapsedOpen: "dt-reason-collapsed-open",
  chev: "dt-reason-collapsed-chev",
  meta: "dt-bubble-meta",
};

const MOBILE: ClassMap = {
  turn: "thr-turn thr-turn-bro",
  bubbleLive: "thr-bubble thr-bubble-bro thr-reason",
  bubbleSettled: "thr-bubble thr-bubble-bro thr-bubble-answer",
  head: "thr-reason-head",
  kicker: "thr-reason-kicker",
  orb: "thr-reason-orb",
  stop: "thr-reason-stop",
  skeleton: "thr-reason-skeleton",
  steps: "thr-reason-steps",
  stepsStatic: "thr-reason-steps thr-reason-steps-static",
  step: "thr-reason-step",
  stepActive: "thr-reason-step-active",
  stepDone: "thr-reason-step-done",
  mark: "thr-reason-mark",
  text: "thr-reason-text",
  streamProgress: "thr-reason-stream-progress",
  divider: "thr-reason-divider",
  answer: "thr-answer-text",
  caret: "thr-reason-caret",
  collapsed: "thr-reason-collapsed",
  collapsedOpen: "thr-reason-collapsed-open",
  chev: "thr-reason-collapsed-chev",
  meta: "thr-meta",
};

function StreamingProgress({ className }: { className: string }) {
  return (
    <div className={className} aria-hidden="true">
      <span />
      <span />
    </div>
  );
}

function LiveSteps({ c, steps }: { c: ClassMap; steps: ReasoningStepView[] }) {
  const vis = windowed(steps);
  if (vis.length === 0) return null;
  return (
    <ol className={c.steps}>
      {vis.map((s, j) => {
        const dist = vis.length - 1 - j;
        const isLast = dist === 0;
        return (
          <li
            key={s.id}
            className={`${c.step} ${isLast ? c.stepActive : c.stepDone}`}
            style={{ opacity: FADE[dist] ?? 0.26 }}
          >
            <span className={c.mark} aria-hidden="true" />
            <span className={c.text}>{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function SettledSteps({ c, steps }: { c: ClassMap; steps: ReasoningStepView[] }) {
  const [showAll, setShowAll] = useState(false);
  if (steps.length === 0) return null;
  const hasMore = steps.length > SETTLED_COLLAPSED;
  const visible = showAll ? steps : steps.slice(-SETTLED_COLLAPSED);
  return (
    <>
      {hasMore ? (
        <button
          type="button"
          className={`${c.collapsed}${showAll ? ` ${c.collapsedOpen}` : ""}`}
          onClick={() => setShowAll((v) => !v)}
          aria-expanded={showAll}
        >
          <span>{showAll ? "Hide steps" : `Show all ${steps.length} steps`}</span>
          <svg className={c.chev} viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      ) : null}
      <ol className={c.stepsStatic}>
        {visible.map((s) => (
          <li key={s.id} className={`${c.step} ${c.stepDone}`}>
            <span className={c.mark} aria-hidden="true" />
            <span className={c.text}>{s.label}</span>
          </li>
        ))}
      </ol>
    </>
  );
}

/**
 * The assistant's turn bubble across its whole lifecycle. "live" (connecting →
 * reasoning → answering) carries a persistent alive cue (orb, and a caret while
 * answering); "settled" drops the cue and collapses steps. The answer markdown
 * lives in a stable slot so it is not remounted when the turn settles.
 */
export function LiveTurnBubble({
  broName,
  state,
  steps,
  answer,
  mobile,
  canStop,
  onStop,
  downloadContext,
}: {
  broName: string;
  state: LiveTurnState;
  steps: ReasoningStepView[];
  answer: string;
  mobile: boolean;
  canStop: boolean;
  onStop: () => void;
  downloadContext?: MarkdownDownloadContext;
}) {
  const c = mobile ? MOBILE : DESKTOP;
  const settled = state.kind === "settled";
  const sub = state.kind === "live" ? state.sub : null;

  const header = settled ? null : (
    <div className={c.head}>
      <span className={c.kicker}>
        <span className={c.orb} aria-hidden="true"><span /><span /><span /></span>
        {broName} is working
      </span>
      {canStop ? (
        <button type="button" className={c.stop} onClick={onStop} aria-label="Stop">
          Stop
        </button>
      ) : null}
    </div>
  );

  let reasoningRegion = null;
  if (sub === "connecting") {
    reasoningRegion = (
      <div className={c.skeleton} aria-hidden="true">
        <span style={{ width: "82%" }} />
        <span style={{ width: "61%" }} />
      </div>
    );
  } else if (sub === "reasoning") {
    reasoningRegion = (
      <>
        <LiveSteps c={c} steps={steps} />
        <StreamingProgress className={c.streamProgress} />
      </>
    );
  } else if (sub === "answering") {
    reasoningRegion = <LiveSteps c={c} steps={steps} />;
  } else if (settled) {
    reasoningRegion = <SettledSteps c={c} steps={steps} />;
  }

  const hasAnswer = answer !== "";
  const showDivider = sub === "answering" && hasAnswer && windowed(steps).length > 0;
  const showAnswer = (sub === "answering" || settled) && hasAnswer;

  return (
    <div className={c.turn}>
      <div className={settled ? c.bubbleSettled : c.bubbleLive} aria-live="polite">
        {header}
        {reasoningRegion}
        {showDivider ? <div className={c.divider} aria-hidden="true" /> : null}
        {showAnswer ? (
          <div className={c.answer}>
            <MarkdownText downloadContext={downloadContext}>{answer}</MarkdownText>
            {sub === "answering" ? <span className={c.caret} aria-hidden="true" /> : null}
          </div>
        ) : null}
      </div>
      {settled ? (
        <div className={c.meta}><span>{broName}</span></div>
      ) : mobile ? (
        <div className="thr-meta">{broName} · updating live</div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd src/newbro/ui && npx vitest run src/LiveTurnBubble.test.tsx`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/LiveTurnBubble.tsx src/newbro/ui/src/LiveTurnBubble.test.tsx
git commit -m "Add unified LiveTurnBubble for the whole turn lifecycle"
```

---

## Task 3: Stable timeline row key helper

Extract a pure helper so the optimistic→canonical handoff reuses one DOM node, and guard it with a test.

**Files:**
- Create: `src/newbro/ui/src/lib/timelineRowKey.ts`
- Test: `src/newbro/ui/src/lib/timelineRowKey.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/newbro/ui/src/lib/timelineRowKey.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { timelineRowKey } from "./timelineRowKey";

describe("timelineRowKey", () => {
  it("uses client_request_id so optimistic and canonical turns share a key", () => {
    const optimistic = { turn_id: "optimistic:abc", client_request_id: "abc" };
    const canonical = { turn_id: "turn-real-123", client_request_id: "abc" };
    expect(timelineRowKey(optimistic)).toBe("abc");
    expect(timelineRowKey(canonical)).toBe(timelineRowKey(optimistic));
  });

  it("falls back to turn_id when there is no client_request_id", () => {
    expect(timelineRowKey({ turn_id: "turn-real-123", client_request_id: null })).toBe("turn-real-123");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd src/newbro/ui && npx vitest run src/lib/timelineRowKey.test.ts`
Expected: FAIL — cannot resolve `./timelineRowKey`.

- [ ] **Step 3: Implement the helper**

Create `src/newbro/ui/src/lib/timelineRowKey.ts`:

```ts
/**
 * Stable React list key for a timeline turn. The optimistic turn and the
 * canonical turn that replaces it share a client_request_id, so keying on it
 * lets React reuse the same DOM node across the handoff (no remount / flash).
 */
export function timelineRowKey(turn: { turn_id: string; client_request_id: string | null }): string {
  return turn.client_request_id ?? turn.turn_id;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd src/newbro/ui && npx vitest run src/lib/timelineRowKey.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/lib/timelineRowKey.ts src/newbro/ui/src/lib/timelineRowKey.test.ts
git commit -m "Add stable timeline row key helper"
```

---

## Task 4: Wire LiveTurnBubble into ArtboardShell

Switch `TimelineTurnView` to the new state model and component, remove `SettledAnswerBubble`, and apply stable keys. This is the task that restores type-checking.

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`

- [ ] **Step 1: Update imports**

In `src/newbro/ui/src/ArtboardShell.tsx`, replace the two import lines:

```ts
import { deriveReasoningPhase } from "./lib/reasoningPhase";
import { ReasoningBubble } from "./ReasoningBubble";
```

with:

```ts
import { deriveLiveTurnState } from "./lib/reasoningPhase";
import { LiveTurnBubble } from "./LiveTurnBubble";
import { timelineRowKey } from "./lib/timelineRowKey";
```

- [ ] **Step 2: Delete the `SettledAnswerBubble` function**

Remove the entire `function SettledAnswerBubble({ … }) { … }` definition (the block starting at `function SettledAnswerBubble({` and ending at its closing `}` before `function TimelineUserMessage`). Its markup now lives inside `LiveTurnBubble`.

- [ ] **Step 3: Replace the phase derivation and render branch in `TimelineTurnView`**

Find this block in `TimelineTurnView`:

```tsx
  const phase = deriveReasoningPhase({
    status: turn.status,
    stepCount: reasoningSteps.length,
    hasAnswer: answerText !== "",
  });
  const stopTaskId = turn.task?.task_id ?? null;
  const canStop = phase !== "done" && stopTaskId !== null;
  const onStop = () => { if (stopTaskId) shell.cancelTask(stopTaskId); };

  return (
    <>
      <TimelineUserMessage bro={bro} turn={turn} mobile={mobile} />
      {phase === "done" ? (
        (answerText || dedupedSettledSteps.length > 0) ? (
          <SettledAnswerBubble
            bro={bro}
            steps={dedupedSettledSteps}
            answer={answerText}
            mobile={mobile}
            sessionId={sessionId}
            workspaceRoot={workspaceRoot}
            threadId={turn.thread_id}
            turnId={turn.turn_id}
          />
        ) : null
      ) : (
        <ReasoningBubble
          broName={bro.name}
          phase={phase}
          steps={reasoningSteps}
          mobile={Boolean(mobile)}
          canStop={canStop}
          onStop={onStop}
        />
      )}
```

Replace it with:

```tsx
  const liveState = deriveLiveTurnState({
    status: turn.status,
    stepCount: reasoningSteps.length,
    hasAnswer: answerText !== "",
  });
  const stopTaskId = turn.task?.task_id ?? null;
  const canStop = liveState.kind !== "settled" && stopTaskId !== null;
  const onStop = () => { if (stopTaskId) shell.cancelTask(stopTaskId); };

  const downloadContext =
    sessionId && turn.thread_id && turn.turn_id && workspaceRoot
      ? { sessionId, threadId: turn.thread_id, turnId: turn.turn_id, workspaceRoot }
      : undefined;
  const settledHasNothing =
    liveState.kind === "settled" && answerText === "" && dedupedSettledSteps.length === 0;

  return (
    <>
      <TimelineUserMessage bro={bro} turn={turn} mobile={mobile} />
      {settledHasNothing ? null : (
        <LiveTurnBubble
          broName={bro.name}
          state={liveState}
          steps={liveState.kind === "settled" ? dedupedSettledSteps : reasoningSteps}
          answer={answerText}
          mobile={Boolean(mobile)}
          canStop={canStop}
          onStop={onStop}
          downloadContext={downloadContext}
        />
      )}
```

Leave the rest of the return (the `proposalRequests.map(...)` and closing `</>`) unchanged.

- [ ] **Step 4: Apply stable keys to the two timeline maps**

There are two `renderedTurns.map(...)` call sites that render `<TimelineTurnView ... key={turn.turn_id} />` (around `ArtboardShell.tsx:2446` desktop and `:2699` mobile). Change both `key={turn.turn_id}` to:

```tsx
key={timelineRowKey(turn)}
```

- [ ] **Step 5: Type-check and run the full suite**

Run: `cd src/newbro/ui && npm run build`
Expected: PASS — no TypeScript errors (confirms `SettledAnswerBubble` has no remaining references and the new props line up).

Run: `cd src/newbro/ui && npm test`
Expected: PASS — `LiveTurnBubble`, `reasoningPhase`, `timelineRowKey`, and the still-present `ReasoningBubble` tests all pass.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "Render turns through LiveTurnBubble with stable row keys"
```

---

## Task 5: Remove the obsolete ReasoningBubble

`ReasoningBubble` is no longer referenced. Delete it and its test.

**Files:**
- Delete: `src/newbro/ui/src/ReasoningBubble.tsx`, `src/newbro/ui/src/ReasoningBubble.test.tsx`

- [ ] **Step 1: Confirm there are no remaining references**

Run: `cd src/newbro/ui && grep -rn "ReasoningBubble" src --include=*.ts --include=*.tsx`
Expected: only matches inside `ReasoningBubble.tsx` / `ReasoningBubble.test.tsx` themselves (no imports elsewhere).

- [ ] **Step 2: Delete the files**

```bash
git rm src/newbro/ui/src/ReasoningBubble.tsx src/newbro/ui/src/ReasoningBubble.test.tsx
```

- [ ] **Step 3: Type-check and run the full suite**

Run: `cd src/newbro/ui && npm run build && npm test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git commit -m "Remove obsolete ReasoningBubble component"
```

---

## Task 6: Transitions, caret, divider, and reduced motion (CSS)

Add the styles the new component references (`*-reason-caret`, `*-reason-divider`), smooth the body/height transitions and the orb persistence, and provide reduced-motion fallbacks. CSS is verified by build + manual run, not unit tests.

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-desktop.css`
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css`

- [ ] **Step 1: Append desktop styles**

Append to `src/newbro/ui/src/styles/variants-desktop.css`:

```css
/* Live turn — streaming caret, divider, and smooth transitions. */
.dt-reason-divider {
  border-top: 1px solid var(--nb-info-edge);
  margin: 9px 0 1px;
}
.dt-reason-caret {
  display: inline-block;
  width: 7px; height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  border-radius: 1px;
  background: var(--nb-info);
  animation: dt-reason-caret-blink 1s steps(2, start) infinite;
}
@keyframes dt-reason-caret-blink { 50% { opacity: 0; } }
/* The bubble eases as content grows between sub-states. */
.dt-bubble-reason, .dt-bubble-answer { transition: none; }
.dt-bubble-reason > *, .dt-bubble-answer > * {
  animation: dt-reason-fade-in 0.18s var(--nb-ease-out, ease-out);
}
@keyframes dt-reason-fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .dt-reason-orb span,
  .dt-reason-skeleton span,
  .dt-reason-stream-progress span,
  .dt-reason-step-active,
  .dt-reason-caret,
  .dt-bubble-reason > *, .dt-bubble-answer > * {
    animation: none !important;
  }
}
```

- [ ] **Step 2: Append mobile styles**

Append to `src/newbro/ui/src/styles/variants-mobile-design.css`:

```css
/* Live turn — streaming caret, divider, and smooth transitions (mobile). */
.thr-reason-divider {
  border-top: 1px solid var(--nb-info-edge);
  margin: 9px 0 1px;
}
.thr-reason-caret {
  display: inline-block;
  width: 7px; height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  border-radius: 1px;
  background: var(--nb-info);
  animation: thr-reason-caret-blink 1s steps(2, start) infinite;
}
@keyframes thr-reason-caret-blink { 50% { opacity: 0; } }
.thr-reason > *, .thr-bubble-answer > * {
  animation: thr-reason-fade-in 0.18s var(--nb-ease-out, ease-out);
}
@keyframes thr-reason-fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .thr-reason-orb span,
  .thr-reason-skeleton span,
  .thr-reason-stream-progress span,
  .thr-reason-step-active,
  .thr-reason-caret,
  .thr-reason > *, .thr-bubble-answer > * {
    animation: none !important;
  }
}
```

- [ ] **Step 3: Type-check / build**

Run: `cd src/newbro/ui && npm run build`
Expected: PASS.

- [ ] **Step 4: Manual verification (the real test)**

Start the app and send a message; watch a full turn from send to completion.

Run: `cd src/newbro/ui && npm run dev` (or the project's normal run path — see `AGENTS.md` / the `run` skill).

Verify against the spec's three gaps:
- On send: the shimmer skeleton appears immediately and **does not vanish into a blank** before steps arrive (gaps #1 + #2 gone — no remount flash, no dead void during executor spin-up).
- When the answer starts: the orb stays bouncing and a caret trails the text — it does **not** look finished while typing (gap #3 gone).
- On completion: steps collapse once into the "Reasoned" pill; orb and caret disappear; the answer text stays put (no jump).
- With OS "reduce motion" on: no shimmer/caret/step animation, content still renders correctly.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/styles/variants-mobile-design.css
git commit -m "Smooth live-turn transitions: caret, divider, reduced motion"
```

---

## Self-Review Notes

- **Spec coverage:** state model → Task 1; unified component + layout A + absorbed settled markup → Task 2; remount fix (stable key) → Tasks 3–4; never-blank live branch → Tasks 1 & 4 (`settledHasNothing` keeps the null only for genuinely empty *settled* turns, per spec "Out of scope" of live blanks); alive cue during streaming → Task 2 (orb + caret) + Task 6 (CSS); transitions + reduced motion → Task 6; tests for deriver, component, and key → Tasks 1–3.
- **Type consistency:** `LiveTurnState` (`{ kind: "settled" } | { kind: "live"; sub }`) is produced by `deriveLiveTurnState` (Task 1) and consumed by `LiveTurnBubble` (Task 2) and `TimelineTurnView` (Task 4) identically. `MarkdownDownloadContext` is reused from `markdown-text` rather than redefined. `timelineRowKey` signature matches its two call sites.
- **Frontend-only:** no backend/runtime/protocol files touched.
```
