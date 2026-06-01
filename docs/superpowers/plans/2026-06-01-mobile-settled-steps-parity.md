# Mobile Settled-Turn Steps Desktop Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a settled (finished) Bro turn render identically on mobile and desktop — a single answer bubble with last-3 steps, a "Show all N steps" toggle, and the inline answer — replacing mobile's divergent "Show steps" pill + task status card.

**Architecture:** Generalize the desktop-only `DTAnswerBubble` into one `mobile`-aware `SettledAnswerBubble` (the same `mobile ? "thr-…" : "dt-…"` convention used by `TaskRecordCard`, `AudioTurnBubble`, etc.). Route both platforms' settled branch in `TimelineTurnView` through it, drop the mobile-only settled `TaskRecordCard`, delete the now-dead `ThrReasoned`, and add the three mirrored `thr-` CSS classes.

**Tech Stack:** React + TypeScript, Vitest + Testing Library, plain CSS with design tokens.

**Spec:** `docs/superpowers/specs/2026-06-01-mobile-settled-steps-parity-design.md`

---

## File Structure

- `src/newbro/ui/src/ArtboardShell.tsx` — Modify. Replace `DTAnswerBubble` (lines 1074-1120) with `SettledAnswerBubble`; delete `ThrReasoned` (lines 1039-1072); rewire the settled branch of `TimelineTurnView` (lines 1291-1296) and remove the mobile settled `TaskRecordCard` (line 1317).
- `src/newbro/ui/src/styles/variants-mobile-design.css` — Modify. Add `.thr-bubble-answer`, `.thr-reason-collapsed` (+ chevron/open), `.thr-answer-text`.
- `src/newbro/ui/src/__tests__/App.test.tsx` — Modify. Add a mobile settled-turn test on the `/mobile` route.

All commands below run from `src/newbro/ui/`.

---

## Task 1: Failing mobile test for settled-turn parity

**Files:**
- Test: `src/__tests__/App.test.tsx` (add a new `it(...)` block immediately after the existing `it("collapses to the last 3 steps with a Show all toggle", …)` which ends at line 1148)

- [ ] **Step 1: Write the failing test**

Insert this block after line 1148 in `src/__tests__/App.test.tsx`:

```tsx
  it("renders settled mobile turn like desktop: last 3 steps, Show all toggle, inline answer, no task card", async () => {
    const snapshot = forgeSnapshot("session-existing");
    snapshot.bro_threads = [
      {
        thread_id: "thread-existing",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: "exec-existing",
        status: "completed",
        title: "Previous request",
        preview: "Previous request body",
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: "2026-05-20T12:00:00Z",
        diagnostics: {},
      },
    ] as any;
    snapshot.bro_timeline_turns = [
      timelineTurn({
        thread_id: "thread-existing",
        executor_turn_id: "turn-r4",
        executor_thread_id: "native-r4",
        userText: "Make the report",
        assistantText: "Done — report written.",
      }),
    ] as any;
    (snapshot as any).recent_native_turn_reasoning = {
      "codex::native-r4::turn-r4": [
        { item_id: "i1", text: "Reading the spec", kind: "progress", created_at: "t1" },
        { item_id: "i2", text: "Mapping the files", kind: "progress", created_at: "t2" },
        { item_id: "i3", text: "Writing the section", kind: "progress", created_at: "t3" },
        { item_id: "i4", text: "Verifying output", kind: "progress", created_at: "t4" },
      ],
    };
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValue(snapshot);
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByTestId("mobile-bro-row-forge"));

    // Inline answer renders.
    expect(await screen.findByText("Done — report written.")).toBeInTheDocument();

    // Last 3 steps visible; earliest hidden behind the toggle.
    expect(screen.getByText("Mapping the files")).toBeInTheDocument();
    expect(screen.getByText("Writing the section")).toBeInTheDocument();
    expect(screen.getByText("Verifying output")).toBeInTheDocument();
    expect(screen.queryByText("Reading the spec")).toBeNull();

    // "Show all N steps" toggle expands to all steps.
    const showAll = screen.getByRole("button", { name: /Show all 4 steps/i });
    fireEvent.click(showAll);
    expect(screen.getByText("Reading the spec")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Hide steps/i })).toBeInTheDocument();

    // No legacy settled task card (status block / progress bar) for this turn.
    expect(document.querySelector(".thr-status")).toBeNull();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/__tests__/App.test.tsx -t "renders settled mobile turn like desktop"`
Expected: FAIL — `Show all 4 steps` button is not found (mobile currently renders the `ThrReasoned` "Show steps" pill) and/or `.thr-status` is present (the `TaskRecordCard` still renders).

- [ ] **Step 3: Commit the failing test**

```bash
git add src/__tests__/App.test.tsx
git commit -m "test(ui): settled mobile turn should match desktop steps+answer"
```

---

## Task 2: Generalize the settled answer bubble and rewire the mobile branch

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (delete `ThrReasoned` 1039-1072; replace `DTAnswerBubble` 1074-1120 with `SettledAnswerBubble`; rewire settled branch 1291-1296; remove line 1317)

- [ ] **Step 1: Delete the dead `ThrReasoned` component**

Remove these lines (the comment + function, currently lines 1039-1072):

```tsx
// Collapsed steps affordance shown on a finished mobile bro turn — the live
// reasoning stream is gone; tucked behind an expandable pill.
function ThrReasoned({ steps }: { steps: ReasoningStep[] }) {
  const [open, setOpen] = React.useState(false);
  if (steps.length === 0) return null;
  return (
    <div className="thr-reasoned">
      <button
        type="button"
        className={`thr-reasoned-toggle${open ? " thr-reasoned-toggle-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 12.5L10 18L20 6"/>
        </svg>
        <span>{open ? "Hide steps" : "Show steps"}</span>
        <svg className="thr-reasoned-chev" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      {open && (
        <ol className="thr-reason-steps thr-reason-steps-static">
          {steps.map((s) => (
            <li key={s.id} className="thr-reason-step thr-reason-step-done">
              <span className="thr-reason-mark" aria-hidden="true" />
              <span className="thr-reason-text">{s.label}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Replace `DTAnswerBubble` with `SettledAnswerBubble`**

Replace the entire `DTAnswerBubble` definition (comment + function, currently lines 1074-1120) with:

```tsx
// Settled bro turn (desktop + mobile) — the agent's progress messages shown as
// compact steps (last 3 by default, with a "Show all N steps" toggle) followed
// by the final answer. Class names switch between dt-/thr- via the mobile flag.
function SettledAnswerBubble({
  bro,
  steps,
  answer,
  mobile = false,
}: {
  bro: BroCardModel;
  steps: ReasoningStep[];
  answer: string;
  mobile?: boolean;
}) {
  const [showAll, setShowAll] = React.useState(false);
  const COLLAPSED = 3;
  const hasMore = steps.length > COLLAPSED;
  const visible = showAll ? steps : steps.slice(-COLLAPSED);

  const turnClass = mobile ? "thr-turn thr-turn-bro" : "dt-turn dt-turn-bro";
  const bubbleClass = mobile
    ? "thr-bubble thr-bubble-bro thr-bubble-answer"
    : "dt-bubble dt-bubble-bro dt-bubble-answer";
  const collapsedClass = mobile ? "thr-reason-collapsed" : "dt-reason-collapsed";
  const collapsedOpenClass = mobile ? "thr-reason-collapsed-open" : "dt-reason-collapsed-open";
  const chevClass = mobile ? "thr-reason-collapsed-chev" : "dt-reason-collapsed-chev";
  const stepsOlClass = mobile
    ? "thr-reason-steps thr-reason-steps-static"
    : "dt-reason-steps dt-reason-steps-static";
  const stepLiClass = mobile ? "thr-reason-step thr-reason-step-done" : "dt-reason-step dt-reason-step-done";
  const markClass = mobile ? "thr-reason-mark" : "dt-reason-step-mark";
  const textClass = mobile ? "thr-reason-text" : "dt-reason-step-text";
  const answerClass = mobile ? "thr-answer-text" : "dt-answer-text";
  const metaClass = mobile ? "thr-meta" : "dt-bubble-meta";

  return (
    <div className={turnClass}>
      <div className={bubbleClass}>
        {steps.length > 0 ? (
          <>
            {hasMore ? (
              <button
                type="button"
                className={`${collapsedClass}${showAll ? ` ${collapsedOpenClass}` : ""}`}
                onClick={() => setShowAll((v) => !v)}
                aria-expanded={showAll}
              >
                <span>{showAll ? "Hide steps" : `Show all ${steps.length} steps`}</span>
                <svg className={chevClass} viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M6 9l6 6 6-6"/>
                </svg>
              </button>
            ) : null}
            <ol className={stepsOlClass}>
              {visible.map((s) => (
                <li key={s.id} className={stepLiClass}>
                  <span className={markClass} aria-hidden="true" />
                  <span className={textClass}>{s.label}</span>
                </li>
              ))}
            </ol>
          </>
        ) : null}
        {answer ? (
          <div className={answerClass}>
            <MarkdownText>{answer}</MarkdownText>
          </div>
        ) : null}
      </div>
      <div className={metaClass}>
        <MessageMeta label={bro.name} />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rewire the settled branch in `TimelineTurnView`**

Find this block (currently lines 1291-1296):

```tsx
      {mobile && isTurnSettled && settledReasoningSteps.length > 0 ? (
        <ThrReasoned steps={dedupedSettledSteps} />
      ) : null}
      {!mobile && isTurnSettled && (answerText || settledReasoningSteps.length > 0) ? (
        <DTAnswerBubble bro={bro} steps={dedupedSettledSteps} answer={answerText} />
      ) : null}
```

Replace it with:

```tsx
      {isTurnSettled && (answerText || dedupedSettledSteps.length > 0) ? (
        <SettledAnswerBubble bro={bro} steps={dedupedSettledSteps} answer={answerText} mobile={mobile} />
      ) : null}
```

- [ ] **Step 4: Remove the mobile-only settled task card**

Delete this line (currently line 1317):

```tsx
      {isTurnSettled && mobile && record ? <TaskRecordCard bro={bro} record={record} mobile={mobile} /> : null}
```

- [ ] **Step 5: Run the new mobile test to verify it passes**

Run: `npx vitest run src/__tests__/App.test.tsx -t "renders settled mobile turn like desktop"`
Expected: PASS

- [ ] **Step 6: Run the full UI test file to confirm no desktop regressions**

Run: `npx vitest run src/__tests__/App.test.tsx`
Expected: PASS — including the existing desktop tests `"shows visible steps for a settled native codex turn"`, `"collapses to the last 3 steps with a Show all toggle"`, and `"does not repeat the answer message as a step"`.

- [ ] **Step 7: Typecheck / build to catch unused symbols**

Run: `npm run build`
Expected: build succeeds (pre-existing Vite chunk-size / agora-rtm eval warnings are unrelated). No TypeScript error about an unused `ThrReasoned` or `DTAnswerBubble` (both removed).

- [ ] **Step 8: Commit**

```bash
git add src/ArtboardShell.tsx
git commit -m "feat(ui): unify settled-turn steps+answer bubble across mobile and desktop"
```

---

## Task 3: Add the mirrored mobile CSS classes

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css` (add after the existing `.thr-reason-steps-static` rules, which end at line 3275)

- [ ] **Step 1: Add the three new `thr-` classes**

Append this block immediately after the existing `.thr-reason-steps-static .thr-reason-text { … }` rule (line 3275):

```css
.thr-bubble-answer {
  display: flex; flex-direction: column;
  gap: 9px;
}
.thr-reason-collapsed {
  align-self: flex-start;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 9px 4px 7px;
  border: 1px solid var(--nb-info-edge);
  border-radius: 999px;
  background: rgba(59,130,246,0.06);
  color: var(--nb-info-ink);
  font-family: var(--nb-font-mono);
  font-size: 10px; font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.thr-reason-collapsed-chev { transition: transform 0.2s ease; opacity: 0.7; }
.thr-reason-collapsed-open .thr-reason-collapsed-chev { transform: rotate(180deg); }
.thr-answer-text {
  font-size: 14px;
  line-height: 1.5;
  color: var(--nb-ink);
  letter-spacing: -0.01em;
  text-wrap: pretty;
}
```

- [ ] **Step 2: Verify the build still succeeds**

Run: `npm run build`
Expected: build succeeds; no CSS syntax errors.

- [ ] **Step 3: Visually confirm in the running app (optional but recommended)**

Run the dev server (`npm run dev`), open a mobile-width view of a Bro thread with a finished turn, and confirm: last-3 steps with a "Show all N steps" pill, the answer below it, and no status/progress card or duplicated title.

- [ ] **Step 4: Commit**

```bash
git add src/styles/variants-mobile-design.css
git commit -m "style(ui): mobile classes for unified settled steps+answer bubble"
```

---

## Self-Review

**Spec coverage:**
- Generalize `DTAnswerBubble` → `SettledAnswerBubble` (mobile-aware) — Task 2, Step 2. ✓
- Rewire `TimelineTurnView` settled branch through one component — Task 2, Step 3. ✓
- Drop mobile settled `TaskRecordCard` — Task 2, Step 4. ✓
- Delete `ThrReasoned` — Task 2, Step 1. ✓
- Preserve in-flight branches and "is working" placeholders — untouched (only lines 1291-1296 and 1317 change). ✓
- New mobile CSS `thr-bubble-answer` / `thr-reason-collapsed` (+chev/open) / `thr-answer-text` — Task 3. ✓
- Tests: last-3 + "Show all N steps" + inline answer + absence of task card — Task 1. ✓
- Edge case (no answer + no steps → renders nothing) — covered by the gate `answerText || dedupedSettledSteps.length > 0` in Task 2, Step 3; matches desktop. No dedicated test needed (it is the same expression desktop already uses).

**Placeholder scan:** No TBD/TODO; every code/CSS/test step contains full content. ✓

**Type consistency:** `SettledAnswerBubble({ bro, steps, answer, mobile })` is defined in Task 2 Step 2 and called with exactly those props in Task 2 Step 3. `ReasoningStep`, `BroCardModel`, `MarkdownText`, `MessageMeta` are already imported/used by the replaced `DTAnswerBubble`, so they remain in scope. ✓
