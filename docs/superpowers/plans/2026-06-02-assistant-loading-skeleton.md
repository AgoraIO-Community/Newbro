# Responsive Assistant Loading + Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a "Bro is working" shimmer skeleton the instant a turn is sent (so the wait never looks dead), formalize the live reasoning bubble into ack → streaming → done phases on desktop + mobile, and add an immediate **Stop** control that cancels the running turn.

**Architecture:** A pure `deriveReasoningPhase(turn.status, stepCount, hasAnswer)` decides the phase; a focused `<ReasoningBubble>` renders the live phases (ack shimmer / streaming steps + a Stop button) for both surfaces; the existing `SettledAnswerBubble` keeps rendering the done phase. `TimelineBroTurn` replaces its current `isTurnSettled`/`reasoningSteps.length`-gated inline blocks with this. Stop calls a new thin `shell.cancelTask(taskId)` that reuses the already-implemented `cancel_task` command + runtime cancel.

**Tech Stack:** React + TypeScript, Vitest + @testing-library/react (`cd src/newbro/ui && npm test`), existing CSS in `src/newbro/ui/src/styles/`.

---

## File Structure

- Create: `src/newbro/ui/src/lib/reasoningPhase.ts` — `ReasoningPhase` type + `deriveReasoningPhase` (pure).
- Create: `src/newbro/ui/src/lib/reasoningPhase.test.ts` — phase unit tests.
- Create: `src/newbro/ui/src/ReasoningBubble.tsx` — the live (ack/streaming) bubble component, both surfaces, with Stop.
- Create: `src/newbro/ui/src/ReasoningBubble.test.tsx` — render + Stop tests.
- Modify: `src/newbro/ui/src/lib/session-client.test.ts` — add a `sendSocketCommand` cancel test.
- Modify: `src/newbro/ui/src/NewbroShell.tsx` — add `cancelTask`, expose on the shell context.
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` — `TimelineBroTurn`: derive phase, compute `canStop`/`onStop`, replace the inline live/settled blocks.
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` — `dt-reason-skeleton` + shimmer + stop CSS.
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css` — `thr-reason-skeleton` + shimmer + stop CSS.

All commands below run from `src/newbro/ui` unless noted. Run a single test file with `npx vitest run <path>`.

---

### Task 1: `deriveReasoningPhase` pure function

**Files:**
- Create: `src/newbro/ui/src/lib/reasoningPhase.ts`
- Test: `src/newbro/ui/src/lib/reasoningPhase.test.ts`

- [ ] **Step 1: Write the failing test**

`src/newbro/ui/src/lib/reasoningPhase.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { deriveReasoningPhase } from "./reasoningPhase";

describe("deriveReasoningPhase", () => {
  it("pending with no steps → ack (the just-sent optimistic turn)", () => {
    expect(deriveReasoningPhase({ status: "pending", stepCount: 0, hasAnswer: false })).toBe("ack");
  });
  it("running with no steps → ack", () => {
    expect(deriveReasoningPhase({ status: "running", stepCount: 0, hasAnswer: false })).toBe("ack");
  });
  it("running with steps → streaming", () => {
    expect(deriveReasoningPhase({ status: "running", stepCount: 3, hasAnswer: false })).toBe("streaming");
  });
  it("pending but answer already present → done", () => {
    expect(deriveReasoningPhase({ status: "pending", stepCount: 0, hasAnswer: true })).toBe("done");
  });
  it("completed → done", () => {
    expect(deriveReasoningPhase({ status: "completed", stepCount: 5, hasAnswer: true })).toBe("done");
  });
  it("failed → done", () => {
    expect(deriveReasoningPhase({ status: "failed", stepCount: 0, hasAnswer: false })).toBe("done");
  });
  it("cancelled → done", () => {
    expect(deriveReasoningPhase({ status: "cancelled", stepCount: 2, hasAnswer: false })).toBe("done");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/reasoningPhase.test.ts`
Expected: FAIL — cannot find module `./reasoningPhase`.

- [ ] **Step 3: Write the implementation**

`src/newbro/ui/src/lib/reasoningPhase.ts`:
```ts
export type ReasoningPhase = "ack" | "streaming" | "done";

/**
 * Phase of the assistant's live turn. In-flight is keyed off the TURN STATUS
 * (not activeRun/steps) so the optimistic `pending` turn shown the instant a
 * message is sent resolves to `ack` and the skeleton appears immediately.
 */
export function deriveReasoningPhase(input: {
  status: string;       // BroTimelineTurn["status"]
  stepCount: number;    // reasoningSteps.length
  hasAnswer: boolean;   // answerText !== ""
}): ReasoningPhase {
  const inFlight = (input.status === "pending" || input.status === "running") && !input.hasAnswer;
  if (!inFlight) return "done";
  return input.stepCount > 0 ? "streaming" : "ack";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/reasoningPhase.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/lib/reasoningPhase.ts src/newbro/ui/src/lib/reasoningPhase.test.ts
git commit -m "feat(ui): derive assistant reasoning phase from turn status"
```

---

### Task 2: `sendSocketCommand` test + `cancelTask` shell method

**Files:**
- Modify: `src/newbro/ui/src/lib/session-client.test.ts`
- Modify: `src/newbro/ui/src/NewbroShell.tsx`

- [ ] **Step 1: Write the failing test for the cancel command payload**

Append to `src/newbro/ui/src/lib/session-client.test.ts` (inside the top-level `describe`, or add a new `describe`). Add the import of `sendSocketCommand` to the existing import from `./session-client` if not already imported:
```ts
import { sendSocketCommand } from "./session-client";

describe("sendSocketCommand", () => {
  it("emits a cancel_task send_command with the task id", () => {
    const sent: string[] = [];
    const socket = { send: (m: string) => sent.push(m) } as unknown as WebSocket;
    sendSocketCommand(socket, "req-1", "cancel_task", "task-1");
    expect(JSON.parse(sent[0])).toEqual({
      type: "send_command",
      request_id: "req-1",
      command_type: "cancel_task",
      task_id: "task-1",
    });
  });
});
```

- [ ] **Step 2: Run test to verify it passes (the function already exists)**

Run: `npx vitest run src/lib/session-client.test.ts`
Expected: PASS. (`sendSocketCommand` already exists in `session-client.ts`; this test pins its payload so the shell wiring is trustworthy. If the import line already exists, don't duplicate it.)

- [ ] **Step 3: Add `cancelTask` to the shell**

In `src/newbro/ui/src/NewbroShell.tsx`:

(a) Ensure `sendSocketCommand` is imported from `./lib/session-client` (the file already imports `sendSocketMessage` and `sendSocketDraftAsrTurn` from there — add `sendSocketCommand` to that import list).

(b) Immediately after the existing `sendMessage` callback (the one that ends `return true; }, []);`), add:
```ts
  const cancelTask = useCallback((taskId: string): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    const requestId = `cancel-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    sendSocketCommand(socket, requestId, "cancel_task", taskId);
    return true;
  }, []);
```

(c) Add `cancelTask` to the object returned by `useNewbroShellState` (the `return { … }` near the end of the hook), alongside `sendMessage`.

- [ ] **Step 4: Verify the UI still type-checks and tests pass**

Run: `npm test`
Expected: the full Vitest suite passes (existing tests + the new ones). If TypeScript errors surface from the new `cancelTask` in the context type, they resolve once it's in the returned object (the context type is `ReturnType<typeof useNewbroShellState>`).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/lib/session-client.test.ts src/newbro/ui/src/NewbroShell.tsx
git commit -m "feat(ui): add cancelTask shell method (cancel_task over the session socket)"
```

---

### Task 3: Shimmer + Stop CSS (desktop + mobile)

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-desktop.css`
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css`

No test (pure CSS); verified visually + via the component test in Task 4 referencing the classes.

- [ ] **Step 1: Append desktop CSS**

Append to `src/newbro/ui/src/styles/variants-desktop.css`:
```css
/* Instant loading skeleton — shown the moment a turn is sent (ack phase). */
.dt-reason-head { display: flex; align-items: center; gap: 8px; }
.dt-reason-skeleton { display: flex; flex-direction: column; gap: 7px; padding: 4px 0 1px; }
.dt-reason-skeleton span {
  height: 9px; border-radius: 5px;
  background: linear-gradient(100deg, rgba(59,130,246,0.08) 30%, rgba(59,130,246,0.20) 50%, rgba(59,130,246,0.08) 70%);
  background-size: 220% 100%;
  animation: dt-reason-shimmer 1.25s ease-in-out infinite;
}
@keyframes dt-reason-shimmer { from { background-position: 180% 0; } to { background-position: -80% 0; } }
.dt-reason-stop {
  margin-left: auto; font: inherit; font-size: 11px; line-height: 1; cursor: pointer;
  padding: 3px 9px; border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.14); background: transparent; color: rgba(0,0,0,0.55);
}
.dt-reason-stop:hover { background: rgba(0,0,0,0.05); }
```

- [ ] **Step 2: Append mobile CSS**

Append to `src/newbro/ui/src/styles/variants-mobile-design.css`:
```css
/* Instant loading skeleton (mobile). */
.thr-reason-head { display: flex; align-items: center; gap: 8px; }
.thr-reason-skeleton { display: flex; flex-direction: column; gap: 7px; padding: 3px 0 1px; }
.thr-reason-skeleton span {
  height: 9px; border-radius: 5px;
  background: linear-gradient(100deg, rgba(59,130,246,0.08) 30%, rgba(59,130,246,0.20) 50%, rgba(59,130,246,0.08) 70%);
  background-size: 220% 100%;
  animation: thr-reason-shimmer 1.25s ease-in-out infinite;
}
@keyframes thr-reason-shimmer { from { background-position: 180% 0; } to { background-position: -80% 0; } }
.thr-reason-stop {
  margin-left: auto; font: inherit; font-size: 11px; line-height: 1; cursor: pointer;
  padding: 3px 9px; border-radius: 8px;
  border: 1px solid rgba(0,0,0,0.14); background: transparent; color: rgba(0,0,0,0.55);
}
```

- [ ] **Step 3: Commit**

```bash
git add src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/styles/variants-mobile-design.css
git commit -m "style(ui): add reasoning shimmer skeleton and stop-button styles"
```

---

### Task 4: `<ReasoningBubble>` component + integrate into `TimelineBroTurn`

**Files:**
- Create: `src/newbro/ui/src/ReasoningBubble.tsx`
- Test: `src/newbro/ui/src/ReasoningBubble.test.tsx`
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`

- [ ] **Step 1: Write the failing component test**

`src/newbro/ui/src/ReasoningBubble.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReasoningBubble } from "./ReasoningBubble";

const steps = [{ id: "s1", label: "Reading the repo" }, { id: "s2", label: "Drafting a plan" }];

describe("ReasoningBubble", () => {
  it("ack renders the shimmer skeleton and no step list", () => {
    const { container } = render(
      <ReasoningBubble broName="Atlas" phase="ack" steps={[]} mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).not.toBeNull();
    expect(container.querySelector(".dt-reason-steps")).toBeNull();
    expect(screen.getByText(/Atlas is working/)).toBeTruthy();
  });

  it("streaming renders the windowed step list and no skeleton", () => {
    const { container } = render(
      <ReasoningBubble broName="Atlas" phase="streaming" steps={steps} mobile={false} canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".dt-reason-skeleton")).toBeNull();
    expect(container.querySelectorAll(".dt-reason-step").length).toBe(2);
  });

  it("uses thr- classes on mobile", () => {
    const { container } = render(
      <ReasoningBubble broName="Atlas" phase="ack" steps={[]} mobile canStop={false} onStop={() => {}} />,
    );
    expect(container.querySelector(".thr-reason-skeleton")).not.toBeNull();
  });

  it("shows Stop when canStop and fires onStop on click; hidden when !canStop", () => {
    const onStop = vi.fn();
    const { rerender } = render(
      <ReasoningBubble broName="Atlas" phase="streaming" steps={steps} mobile={false} canStop onStop={onStop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /stop/i }));
    expect(onStop).toHaveBeenCalledTimes(1);
    rerender(
      <ReasoningBubble broName="Atlas" phase="streaming" steps={steps} mobile={false} canStop={false} onStop={onStop} />,
    );
    expect(screen.queryByRole("button", { name: /stop/i })).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/ReasoningBubble.test.tsx`
Expected: FAIL — cannot find module `./ReasoningBubble`.

- [ ] **Step 3: Write the component**

`src/newbro/ui/src/ReasoningBubble.tsx`:
```tsx
import type { ReasoningPhase } from "./lib/reasoningPhase";

export interface ReasoningStepView {
  id: string;
  label: string;
}

const WINDOW = 3;
const FADE = [1, 0.55, 0.26];

function windowed(steps: ReasoningStepView[]) {
  const startAt = Math.max(0, steps.length - WINDOW);
  return steps.slice(startAt, steps.length);
}

/**
 * The assistant's live reasoning bubble for the `ack` and `streaming` phases.
 * (The `done` phase is rendered by SettledAnswerBubble.)
 */
export function ReasoningBubble({
  broName,
  phase,
  steps,
  mobile,
  canStop,
  onStop,
}: {
  broName: string;
  phase: ReasoningPhase; // "ack" | "streaming"
  steps: ReasoningStepView[];
  mobile: boolean;
  canStop: boolean;
  onStop: () => void;
}) {
  const stopButton = canStop ? (
    <button
      type="button"
      className={mobile ? "thr-reason-stop" : "dt-reason-stop"}
      onClick={onStop}
      aria-label="Stop"
    >
      Stop
    </button>
  ) : null;

  if (mobile) {
    return (
      <div className="thr-turn thr-turn-bro">
        <div className="thr-bubble thr-bubble-bro thr-reason" aria-live="polite">
          <div className="thr-reason-head">
            <span className="thr-reason-kicker">
              <span className="thr-reason-orb" aria-hidden="true"><span /><span /><span /></span>
              {broName} is working
            </span>
            {stopButton}
          </div>
          {phase === "ack" ? (
            <div className="thr-reason-skeleton" aria-hidden="true">
              <span style={{ width: "82%" }} />
              <span style={{ width: "61%" }} />
            </div>
          ) : (
            <ol className="thr-reason-steps">
              {windowed(steps).map((s, j, vis) => {
                const dist = vis.length - 1 - j;
                const isLast = dist === 0;
                return (
                  <li
                    key={s.id}
                    className={`thr-reason-step${isLast ? " thr-reason-step-active" : " thr-reason-step-done"}`}
                    style={{ opacity: FADE[dist] ?? 0.26 }}
                  >
                    <span className="thr-reason-mark" aria-hidden="true" />
                    <span className="thr-reason-text">{s.label}</span>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
        <div className="thr-meta">{broName} · updating live</div>
      </div>
    );
  }

  return (
    <div className="dt-turn dt-turn-bro">
      <div className="dt-bubble dt-bubble-bro dt-bubble-reason" aria-live="polite">
        <div className="dt-reason-head">
          <span className="dt-reason-kicker">
            <span className="dt-reason-orb" aria-hidden="true"><span /><span /><span /></span>
            {broName} is working
          </span>
          {stopButton}
        </div>
        {phase === "ack" ? (
          <div className="dt-reason-skeleton" aria-hidden="true">
            <span style={{ width: "82%" }} />
            <span style={{ width: "61%" }} />
          </div>
        ) : (
          <ol className="dt-reason-steps">
            {windowed(steps).map((s, j, vis) => {
              const dist = vis.length - 1 - j;
              const isLast = dist === 0;
              return (
                <li
                  key={s.id}
                  className={`dt-reason-step${isLast ? " dt-reason-step-active" : " dt-reason-step-done"}`}
                  style={{ opacity: FADE[dist] ?? 0.26 }}
                >
                  <span className="dt-reason-step-mark" aria-hidden="true" />
                  <span className="dt-reason-step-text">{s.label}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the component test to verify it passes**

Run: `npx vitest run src/ReasoningBubble.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Integrate into `TimelineBroTurn` (ArtboardShell.tsx)**

(a) Add imports near the top of `src/newbro/ui/src/ArtboardShell.tsx` (with the other local imports):
```ts
import { deriveReasoningPhase } from "./lib/reasoningPhase";
import { ReasoningBubble } from "./ReasoningBubble";
```

(b) In `TimelineBroTurn`, just after the existing `const dedupedSettledSteps = …` line (around line 1212-1214), add:
```ts
  const phase = deriveReasoningPhase({
    status: turn.status,
    stepCount: reasoningSteps.length,
    hasAnswer: answerText !== "",
  });
  const stopTaskId = turn.task?.task_id ?? null;
  const canStop = phase !== "done" && stopTaskId !== null;
  const onStop = () => { if (stopTaskId) shell.cancelTask(stopTaskId); };
```

(c) Replace the FIVE conditional blocks currently in the returned JSX — the desktop steps block (`!mobile && reasoningSteps.length > 0 ? …`), the mobile steps block (`mobile && reasoningSteps.length > 0 ? …`), the settled block (`isTurnSettled && (answerText || dedupedSettledSteps.length > 0) ? <SettledAnswerBubble …/> : null`), and the two `!isTurnSettled && … reasoningSteps.length === 0` "Bro is working" blocks — with this single block:
```tsx
      {phase === "done" ? (
        (answerText || dedupedSettledSteps.length > 0) ? (
          <SettledAnswerBubble bro={bro} steps={dedupedSettledSteps} answer={answerText} mobile={mobile} />
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
Keep `<TimelineUserMessage … />` (the first child) unchanged. Remove the now-unused windowing IIFEs that lived in the deleted blocks. If `isTurnSettled` becomes unused after this, delete its declaration to avoid a lint error.

- [ ] **Step 6: Run the full UI suite + typecheck**

Run: `npm test`
Expected: all tests pass, including the existing `__tests__/App.test.tsx` settled-turn parity test (the done phase still renders `SettledAnswerBubble`). If `App.test.tsx` asserts on the live "working" bubble, confirm the new markup still satisfies it; if it asserted on the old 0-step bubble shape, update that assertion to the new `dt-reason-skeleton`/`ReasoningBubble` shape.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/ReasoningBubble.tsx src/newbro/ui/src/ReasoningBubble.test.tsx src/newbro/ui/src/ArtboardShell.tsx
git commit -m "feat(ui): instant loading skeleton + phase-driven reasoning bubble with Stop"
```

---

### Task 5: Manual verification

- [ ] **Step 1: Build + run the app and exercise the flow**

From repo root: `./newbro dev` (or the project's usual dev command). In Bro Detail:
1. Send a text message → confirm the assistant-side shimmer "{Bro} is working" skeleton appears **immediately** (within a frame), before any reasoning line.
2. Confirm it transitions: skeleton → streamed reasoning steps → settled answer (collapsed reasoning).
3. While running (steps visible), click **Stop** → confirm the turn settles to cancelled and the bubble stops.
4. Repeat on a mobile viewport (or `/mobile`) → confirm the same skeleton + Stop appear with `thr-` styling.

- [ ] **Step 2: Note results**

Record what you observed (no commit needed). If the skeleton does NOT appear instantly, verify the optimistic turn's `status` is `pending`/`running` reaching `deriveReasoningPhase` (the root cause would be the turn not being optimistically inserted, which is outside this change).

---

## Self-Review

**Spec coverage:**
- Instant shimmer skeleton on send (ack) → Task 1 (phase from `turn.status`), Task 3 (CSS), Task 4 (ack render).
- Three phases ack/streaming/done on desktop + mobile → Task 1 + Task 4 (component both surfaces; done via existing `SettledAnswerBubble`).
- Stop (immediate, shown only when task exists) → Task 2 (`cancelTask`), Task 4 (`canStop`/`onStop`, Stop button gating).
- Reuse existing `cancel_task` transport/runtime → Task 2 (`sendSocketCommand`, no backend change).
- Tests: `deriveReasoningPhase`, `ReasoningBubble` (incl. Stop), `sendSocketCommand` → Tasks 1, 2, 4.
- CSS shimmer port (dt- + thr-) → Task 3.
- Files list in spec matches Tasks 1–4.

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `deriveReasoningPhase({status, stepCount, hasAnswer})` and `ReasoningPhase` are used identically in Tasks 1 and 4; `ReasoningBubble` props (`broName, phase, steps, mobile, canStop, onStop`) match between its definition (Task 4 Step 3), its tests (Step 1), and the call site (Step 5); `cancelTask(taskId)` defined in Task 2 is called in Task 4 Step 5(b). Step classes (`dt-reason-step`/`dt-reason-skeleton`/`thr-…`) match the CSS added in Task 3.

**Note:** the only risky edit is Task 4 Step 5(c) — deleting the five existing inline blocks and replacing with one. The implementer must read the current `TimelineBroTurn` return body and remove exactly those blocks (keeping `TimelineUserMessage`).
