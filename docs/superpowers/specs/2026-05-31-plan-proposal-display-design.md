# Render the proposed codex plan in the proposal card; recolor it blue

Date: 2026-05-31
Status: Design (approved for spec review)

## Problem

In plan mode, a codex plan proposal renders two things wrong:

1. **The plan text is cut off.** The full plan only appears as a native-reasoning *step*,
   which is truncated to 280 chars (`_NATIVE_REASONING_TEXT_LIMIT`) — clipped mid-word. The
   proposal card itself shows only a generic line, *"Review the proposed plan before
   execution."*, and no plan body. (Confirmed from the live DOM.)
2. **The card is red.** `.dt-planprop*` (desktop) uses `--nb-coral*` for the header, glyph,
   REVIEW tag, active tab, and selected option, where the design uses `--nb-info*` (blue).

The full plan is in fact already available: `_proposal_from_codex_plan`
(`executor.py:1109`) puts `"codex_plan": plan` into the proposal, so it ships in
`request.details.proposal.codex_plan` — the frontend just never renders it. The frontend
also already has the machinery: `timelinePlan(value)` parses a codex plan into
`{ text, explanation, steps }`, and `TaskPlanView` renders that.

## Goal

Show the full proposed plan in the proposal card (not a 280-char step), and color the card
blue to match the design, on desktop and mobile.

## Non-goals

- No backend change. The plan data already ships in the proposal; the truncated step is
  filtered out on the frontend, not removed at the source (it stays small and bounded).
- No change to non-codex proposals (real summaries / multi-option questions keep their
  current rendering).
- No change to the approved/running (`-on`, `--nb-live` green) state — that is an
  intentional separate state, not the default.

## Design

### 1. Render the plan in the proposal card (`PlanProposalCard`, `ArtboardShell.tsx`)

When the proposal is a final codex plan, parse and render it:

```tsx
const codexPlan = isFinalCodexPlan && proposal && typeof proposal === "object" && !Array.isArray(proposal)
  ? timelinePlan((proposal as Record<string, unknown>).codex_plan)
  : undefined;
```

In the JSX, replace the unconditional summary line with: render `TaskPlanView` when we have
a parsed plan, otherwise the summary line. (Falling back to the summary if the plan fails to
parse avoids an empty card.)

```tsx
{codexPlan ? (
  <TaskPlanView plan={codexPlan} prefix={prefix} />
) : (
  <p className={mobile ? "plan-prop-summary" : "dt-planprop-summary"}>{summary}</p>
)}
```

`TaskPlanView` renders the plan's explanation (markdown) + steps in full — fixing the
cut-off — and the generic *"Review the proposed plan before execution."* summary is dropped
for codex plans (per decision), while other proposals still show their real summary.

### 2. Drop the redundant truncated plan step (`buildReasoningStepsForNativeTurn`, `adapters.ts`)

The plan now lives in the card, so it should not also appear as a clipped reasoning step.
Filter `kind: "plan"` native reasoning steps before mapping:

```tsx
const steps = recentNativeTurnReasoning[key]?.filter((s) => s.kind !== "plan");
```

Progress/commentary steps are unaffected.

### 3. Recolor blue

Swap `--nb-coral*` → `--nb-info*` to match the design.

**Desktop (`src/newbro/ui/src/styles/variants-desktop.css`):**
- `.dt-planprop` border `--nb-line` → `--nb-info-edge`
- `.dt-planprop-head` background `--nb-coral-tint` → `--nb-info-soft`
- `.dt-planprop-glyph` background `--nb-coral` → `--nb-info`
- `.dt-planprop-tag` color `--nb-coral` → `--nb-info-ink`; border `--nb-coral-border` → `--nb-info-edge`
- `.dt-plantab-on` color `--nb-coral-hover` → `--nb-info-ink`; border `--nb-coral-border` → `--nb-info-edge`; background `--nb-coral-tint` → `--nb-info-soft`
- `.dt-planopt-on` background `--nb-coral-tint` → `--nb-info-soft`; border `--nb-coral` → `--nb-info`; box-shadow `rgba(255,106,61,0.16)` → `rgba(59,130,246,0.18)`
- `.dt-planopt-on .dt-planopt-radio` border `--nb-coral` → `--nb-info`
- `.dt-planopt-on .dt-planopt-radio::after` background `--nb-coral` → `--nb-info`
- `.dt-planopt-letter` color `--nb-coral-hover` → `--nb-info-ink`; border `--nb-coral-border` → `--nb-info-edge`

**Mobile (`src/newbro/ui/src/styles/variants-mobile-design.css`):** already blue except the
active tab —
- `.plan-tab-on` color `--nb-coral-hover` → `--nb-info-ink`; border `--nb-coral-border` → `--nb-info-edge`; background `--nb-coral-tint` → `--nb-info-soft`

(The approve button `.dt-planprop-approve` / `.plan-prop-approve` is already `--nb-info-grad-btn`.)

## Edge cases

- `codex_plan` missing or unparseable → `codexPlan` is `undefined` → the generic summary line
  renders as today (no empty card).
- Non-codex proposal (`isFinalCodexPlan` false) → summary + options/questions render exactly
  as today; no plan body, no color change to behavior.
- A turn with only a plan step and no progress steps → after filtering, it has no reasoning
  steps; the answer bubble shows just the answer (and the plan shows in the card).

## Testing

Frontend (`vitest`):
- A plan proposal whose `details.proposal.codex_plan` has steps renders those step texts in
  the card (via `TaskPlanView`) and does **not** render "Review the proposed plan before
  execution." A non-codex proposal still renders its summary.
- `buildReasoningStepsForNativeTurn` excludes `kind: "plan"` steps and keeps `kind:
  "progress"` steps (adapter unit test).

CSS recolor is visual; no automated test.

## Affected files

- `src/newbro/ui/src/ArtboardShell.tsx` — `PlanProposalCard` plan body; summary conditional.
- `src/newbro/ui/src/components/newbro/adapters.ts` — filter `kind: "plan"` in
  `buildReasoningStepsForNativeTurn`.
- `src/newbro/ui/src/styles/variants-desktop.css` — coral → info for `.dt-planprop*`.
- `src/newbro/ui/src/styles/variants-mobile-design.css` — `.plan-tab-on` coral → info.
- Tests under `src/newbro/ui/src/__tests__/` and `components/newbro/adapters.test.ts`.
