# Plan Proposal Display (render plan + recolor blue) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the full proposed codex plan inside the proposal card (not a truncated reasoning step), drop the generic summary for codex plans, and recolor the proposal card blue to match the design.

**Architecture:** Frontend-only. The plan already ships in `request.details.proposal.codex_plan`; render it with the existing `timelinePlan()` + `TaskPlanView`. Filter `kind: "plan"` out of the native reasoning steps so the clipped plan step disappears. Swap `--nb-coral*` → `--nb-info*` in the desktop and mobile plan-proposal CSS.

**Tech Stack:** React / TypeScript / Vitest; CSS.

Spec: `docs/superpowers/specs/2026-05-31-plan-proposal-display-design.md`

---

## File structure

- Modify: `src/newbro/ui/src/components/newbro/adapters.ts` — filter `kind: "plan"` in `buildReasoningStepsForNativeTurn`.
- Test: `src/newbro/ui/src/components/newbro/adapters.test.ts` — adapter unit test.
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` — `PlanProposalCard` renders the plan; summary conditional.
- Test: `src/newbro/ui/src/__tests__/App.test.tsx` — proposal-card render test.
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` — `.dt-planprop*` coral → info.
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css` — `.plan-tab-on` coral → info.

Frontend commands (run from `src/newbro/ui`): `npx vitest run <path> -t "<name>"`, `npx vitest run`, `npx tsc --noEmit`.

---

## Task 1: Filter plan-kind steps in the native-reasoning adapter

**Files:**
- Modify: `src/newbro/ui/src/components/newbro/adapters.ts`
- Test: `src/newbro/ui/src/components/newbro/adapters.test.ts`

- [ ] **Step 1: Write the failing test**

In `src/newbro/ui/src/components/newbro/adapters.test.ts`, inside the existing
`describe("buildReasoningStepsForNativeTurn", () => { ... })` block (it already defines a
`baseTurn` fixture with `executor_id: "codex"`, `executor_thread_id: "native-1"`,
`executor_turn_id: "turn-1"`, `status: "running"`), add this test:

```typescript
  it("excludes plan-kind steps", () => {
    const mixed: NativeReasoningStep[] = [
      { item_id: "i1", text: "Working on it", kind: "progress", created_at: "t1" },
      { item_id: "i2", text: "# Big plan markdown", kind: "plan", created_at: "t2" },
    ];
    const result = buildReasoningStepsForNativeTurn(baseTurn, { "codex::native-1::turn-1": mixed });
    expect(result.map((s) => s.label)).toEqual(["Working on it"]);
  });
```

- [ ] **Step 2: Run it, verify FAIL**

Run (from `src/newbro/ui`): `npx vitest run src/components/newbro/adapters.test.ts -t "excludes plan-kind steps"`
Expected: FAIL — currently the plan step is included, so `result.map((s) => s.label)` is `["Working on it", "# Big plan markdown"]`.

- [ ] **Step 3: Filter `kind: "plan"` in the adapter**

In `src/newbro/ui/src/components/newbro/adapters.ts`, in `buildReasoningStepsForNativeTurn`,
find this line:

```typescript
  const steps = recentNativeTurnReasoning[key];
```

Replace it with:

```typescript
  const steps = recentNativeTurnReasoning[key]?.filter((s) => s.kind !== "plan");
```

(The existing `if (!steps || steps.length === 0) return [];` guard on the next line still
applies, so an all-plan list correctly yields `[]`.)

- [ ] **Step 4: Run it, verify PASS**

Run (from `src/newbro/ui`): `npx vitest run src/components/newbro/adapters.test.ts -t "excludes plan-kind steps"`
Expected: PASS

- [ ] **Step 5: Run the full adapters test file**

Run (from `src/newbro/ui`): `npx vitest run src/components/newbro/adapters.test.ts`
Expected: all pass (the existing buildReasoningStepsForNativeTurn tests use `progress` steps, unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/components/newbro/adapters.ts src/newbro/ui/src/components/newbro/adapters.test.ts
git commit -m "feat(ui): exclude plan-kind steps from native reasoning"
```

---

## Task 2: Render the codex plan in the proposal card; drop the generic summary

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

Context: `PlanProposalCard` (`ArtboardShell.tsx:655`) already computes
`const proposal = request.details?.proposal;` and
`const isFinalCodexPlan = Boolean(proposal && typeof proposal === "object" && !Array.isArray(proposal) && "codex_plan" in proposal);`.
`timelinePlan(value)` (same file) parses `{ text, explanation, steps }` from a codex plan and
returns `BroTaskRecord["plan"] | undefined`; `TaskPlanView({ plan, prefix })` renders it.
`planProposalThreadSnapshot` (in App.test.tsx) accepts a `proposalExtras` override that is
spread into `details.proposal`, so passing `proposalExtras: { codex_plan: {...} }` produces a
final-codex-plan proposal.

- [ ] **Step 1: Write the failing test**

In `src/newbro/ui/src/__tests__/App.test.tsx`, inside the main
`describe("Newbro artboard shell", ...)` block (near the other plan-proposal tests, e.g.
after `"renders inline plan proposals after the result card for the same turn"`), add:

```typescript
  it("renders the codex plan body in the proposal card and drops the generic summary", async () => {
    const snapshot = planProposalThreadSnapshot("session-existing", "pending", {
      proposalSummary: "Review the proposed plan before execution.",
      taskTitle: "Plan task",
      proposalExtras: {
        codex_plan: {
          text: "Product Brief plan",
          steps: [
            { step: "Inventory existing variants", status: "pending" },
            { step: "Write the Product Brief report", status: "pending" },
          ],
        },
      },
    });
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValue(snapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=thread-plan");

    render(<RouterProvider router={getRouter()} />);

    // The plan steps render in the card…
    expect(await screen.findByText("Inventory existing variants")).toBeInTheDocument();
    expect(screen.getByText("Write the Product Brief report")).toBeInTheDocument();
    // …and the generic summary line is dropped.
    expect(screen.queryByText("Review the proposed plan before execution.")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it, verify FAIL**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "renders the codex plan body"`
Expected: FAIL — today the card renders the generic summary and not the plan steps, so
`findByText("Inventory existing variants")` times out.

- [ ] **Step 3: Compute the parsed plan in `PlanProposalCard`**

In `src/newbro/ui/src/ArtboardShell.tsx`, find this exact line in `PlanProposalCard`:

```typescript
  const isSingleOptionFinalApprove = isFinalCodexPlan
    && multiQuestions.length === 0
    && options.length === 1
    && request.available_actions.includes("approve");
```

Immediately AFTER it (after the closing `;`), add:

```typescript
  const codexPlan = isFinalCodexPlan && proposal && typeof proposal === "object" && !Array.isArray(proposal)
    ? timelinePlan((proposal as Record<string, unknown>).codex_plan)
    : undefined;
```

- [ ] **Step 4: Render the plan instead of the generic summary**

In the same component's JSX, find this exact line:

```typescript
        <p className={mobile ? "plan-prop-summary" : "dt-planprop-summary"}>{summary}</p>
```

Replace it with:

```typescript
        {codexPlan ? (
          <TaskPlanView plan={codexPlan} prefix={prefix} />
        ) : (
          <p className={mobile ? "plan-prop-summary" : "dt-planprop-summary"}>{summary}</p>
        )}
```

- [ ] **Step 5: Run the test, verify PASS**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "renders the codex plan body"`
Expected: PASS

- [ ] **Step 6: Run the full frontend suite + typecheck**

Run (from `src/newbro/ui`): `npx vitest run` then `npx tsc --noEmit`
Expected: all pass; tsc clean. NOTE: a pre-existing flake
`clears the existing thread history when 'New thread' is clicked…` may fail ONLY in the full
run but passes in isolation — if that is the only failure, re-run it alone
(`npx vitest run src/__tests__/App.test.tsx -t "clears the existing thread history"` → passes)
and treat it as the known unrelated flake; do not try to fix it.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): render codex plan in proposal card, drop generic summary"
```

---

## Task 3: Recolor the proposal card blue (desktop + mobile)

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-desktop.css`
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css`

No automated test (visual CSS); verified by `npx tsc --noEmit` (still clean) and the full
suite still passing.

- [ ] **Step 1: Desktop — `.dt-planprop` border**

In `src/newbro/ui/src/styles/variants-desktop.css`, in the `.dt-planprop {` rule, change:

```css
  border: 1px solid var(--nb-line);
```
to:
```css
  border: 1px solid var(--nb-info-edge);
```

- [ ] **Step 2: Desktop — head, glyph, tag**

In the same file:

In `.dt-planprop-head {` change `background: var(--nb-coral-tint);` to `background: var(--nb-info-soft);`

In `.dt-planprop-glyph {` change `background: var(--nb-coral);` to `background: var(--nb-info);`

In `.dt-planprop-tag {` change `color: var(--nb-coral);` to `color: var(--nb-info-ink);` and
`border: 1px solid var(--nb-coral-border);` to `border: 1px solid var(--nb-info-edge);`

- [ ] **Step 3: Desktop — active tab**

In `.dt-plantab-on {` change the three lines:
```css
  color: var(--nb-coral-hover);
  border-color: var(--nb-coral-border);
  background: var(--nb-coral-tint);
```
to:
```css
  color: var(--nb-info-ink);
  border-color: var(--nb-info-edge);
  background: var(--nb-info-soft);
```

- [ ] **Step 4: Desktop — selected option**

In `.dt-planopt-on {` change:
```css
  background: var(--nb-coral-tint);
  border-color: var(--nb-coral);
  box-shadow: 0 1px 5px rgba(255,106,61,0.16);
```
to:
```css
  background: var(--nb-info-soft);
  border-color: var(--nb-info);
  box-shadow: 0 1px 5px rgba(59,130,246,0.18);
```

In `.dt-planopt-on .dt-planopt-radio {` change `border-color: var(--nb-coral);` to
`border-color: var(--nb-info);`

In `.dt-planopt-on .dt-planopt-radio::after {` change `background: var(--nb-coral);` to
`background: var(--nb-info);`

In `.dt-planopt-letter {` change `color: var(--nb-coral-hover);` to `color: var(--nb-info-ink);`
and `border: 1px solid var(--nb-coral-border);` to `border: 1px solid var(--nb-info-edge);`

- [ ] **Step 5: Mobile — active tab**

In `src/newbro/ui/src/styles/variants-mobile-design.css`, in the `.plan-tab-on {` rule,
change:
```css
  color: var(--nb-coral-hover);
  border-color: var(--nb-coral-border);
  background: var(--nb-coral-tint);
```
to:
```css
  color: var(--nb-info-ink);
  border-color: var(--nb-info-edge);
  background: var(--nb-info-soft);
```

- [ ] **Step 6: Verify no coral remains in the plan-proposal rules**

Run: `grep -n "coral" src/newbro/ui/src/styles/variants-desktop.css | grep -iE "planprop|plantab|planopt"` → expect no output.
Run: `grep -n "coral" src/newbro/ui/src/styles/variants-mobile-design.css | grep -iE "plan-prop|plan-tab|plan-opt"` → expect no output.
(The `.dt-planprop-on` / `.plan-prop-on` rules use `--nb-live*` (green) for the approved state — leave those; they are not coral.)

- [ ] **Step 7: Typecheck + full suite (sanity)**

Run (from `src/newbro/ui`): `npx tsc --noEmit` (clean) and `npx vitest run` (all pass, modulo the known flake noted in Task 2).

- [ ] **Step 8: Commit**

```bash
git add src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/styles/variants-mobile-design.css
git commit -m "fix(ui): recolor plan proposal card from coral to info (blue)"
```

---

## Final verification

- [ ] Frontend (from `src/newbro/ui`): `npx vitest run` → all pass (modulo the known flake, verified in isolation); `npx tsc --noEmit` → clean.
- [ ] Manual (`newbro dev`, restarted): a plan-mode proposal shows the full plan (steps,
  not a truncated fragment) inside a **blue** card, with no "Review the proposed plan before
  execution." line and no clipped plan step in the answer bubble.

## Notes / gotchas

- `timelinePlan` and `TaskPlanView` are existing declarations in `ArtboardShell.tsx`
  (function declarations are hoisted, so `timelinePlan` is callable from `PlanProposalCard`
  even though it is defined later in the file). No imports needed.
- The summary fallback is intentional: if `codex_plan` is missing/unparseable, `codexPlan` is
  `undefined` and the generic summary still renders — no empty card.
- Leave the `--nb-live*` (green) `-on` approved/running state untouched; only the default
  coral styling becomes blue.
