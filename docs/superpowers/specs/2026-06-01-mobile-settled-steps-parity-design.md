# Mobile settled-turn steps: desktop parity

**Date:** 2026-06-01
**Status:** Design approved, pending implementation
**Scope:** UI only — `ArtboardShell.tsx`, `styles/variants-mobile-design.css`, `__tests__/App.test.tsx`

## Problem

The recent "native codex turn steps" work updated how a **settled** (finished) Bro
turn renders its reasoning steps and final answer — but only on desktop. Mobile
kept an older, divergent rendering. Concretely, for a settled native turn:

- **Desktop** (`DTAnswerBubble`, `ArtboardShell.tsx:1076`): one bubble showing the
  **last 3 steps** by default with a **"Show all N steps"** toggle, followed by the
  **inline answer** (`MarkdownText`).
- **Mobile** (`ThrReasoned`, `ArtboardShell.tsx:1041` + `TaskRecordCard`,
  `ArtboardShell.tsx:1317`): a fully-collapsed **"Show steps"** pill that expands to
  **all** steps at once (no last-3 default, no count), **plus** a separate task
  **status card** (`thr-status`) showing the user's request echoed as a title, a
  100%-filled progress bar, the plan, and the answer as narration.

This produces, on mobile: the user's message duplicated (user bubble + card title),
a vestigial 100% progress bar, status-card chrome desktop never shows, and a
different steps affordance.

## Goal

Make a settled mobile turn render **exactly like desktop**: a single answer bubble
with the last-3 steps + "Show all N steps" toggle + inline answer, and nothing else.

## Already at parity (no change needed)

These updates already thread through shared code or shared adapters and apply to both
desktop and mobile today; they are listed so the implementation does not disturb them:

- Live "is working" in-flight step stream (last-3 window + fade) — desktop branch at
  `ArtboardShell.tsx:1224`, mobile branch at `1257`.
- "step/working" wording.
- Exclude plan-kind steps from native reasoning (`buildReasoningStepsForNativeTurn`).
- De-dup the answer message from its steps (`dedupedSettledSteps`,
  `ArtboardShell.tsx:1217`).
- Plan proposal card + codex plan rendering (`PlanProposalCard` / `TaskPlanView`,
  shared via `prefix`).

## Design

### 1. Generalize the settled answer bubble

Replace `DTAnswerBubble` with a single component that selects `thr-`/`dt-` class
names via a `mobile` ternary — the convention already used by `TaskRecordCard`,
`AudioTurnBubble`, `TextTurnBubble`, etc.

```tsx
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

  const turnClass    = mobile ? "thr-turn thr-turn-bro"            : "dt-turn dt-turn-bro";
  const bubbleClass  = mobile ? "thr-bubble thr-bubble-bro thr-bubble-answer"
                              : "dt-bubble dt-bubble-bro dt-bubble-answer";
  const collapsed    = mobile ? "thr-reason-collapsed"            : "dt-reason-collapsed";
  const collapsedOn  = mobile ? "thr-reason-collapsed-open"       : "dt-reason-collapsed-open";
  const chevClass    = mobile ? "thr-reason-collapsed-chev"       : "dt-reason-collapsed-chev";
  const stepsOl      = mobile ? "thr-reason-steps thr-reason-steps-static"
                              : "dt-reason-steps dt-reason-steps-static";
  const stepLi       = mobile ? "thr-reason-step thr-reason-step-done"
                              : "dt-reason-step dt-reason-step-done";
  const markClass    = mobile ? "thr-reason-mark"                 : "dt-reason-step-mark";
  const textClass    = mobile ? "thr-reason-text"                 : "dt-reason-step-text";
  const answerClass  = mobile ? "thr-answer-text"                 : "dt-answer-text";
  const metaClass    = mobile ? "thr-meta"                        : "dt-bubble-meta";

  return (
    <div className={turnClass}>
      <div className={bubbleClass}>
        {steps.length > 0 ? (
          <>
            {hasMore ? (
              <button
                type="button"
                className={`${collapsed}${showAll ? ` ${collapsedOn}` : ""}`}
                onClick={() => setShowAll((v) => !v)}
                aria-expanded={showAll}
              >
                <span>{showAll ? "Hide steps" : `Show all ${steps.length} steps`}</span>
                <svg className={chevClass} /* …chevron… */ />
              </button>
            ) : null}
            <ol className={stepsOl}>
              {visible.map((s) => (
                <li key={s.id} className={stepLi}>
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

### 2. Rewire `TimelineTurnView`

In the settled branch, route both platforms through the one component and delete the
mobile-specific settled rendering. Replace the three existing blocks
(`ArtboardShell.tsx:1291`, `1294`, `1317`) with:

```tsx
{isTurnSettled && (answerText || dedupedSettledSteps.length > 0) ? (
  <SettledAnswerBubble
    bro={bro}
    steps={dedupedSettledSteps}
    answer={answerText}
    mobile={mobile}
  />
) : null}
```

- Remove the mobile-only `TaskRecordCard` settled usage at `1317`.
- The in-flight branches (`1224` desktop, `1257` mobile) and the
  `reasoningSteps.length === 0` "is working" placeholders (`1297`, `1307`) are
  **unchanged**.

### 3. Delete dead code

`ThrReasoned` becomes unused — remove it. `TaskRecordCard` stays (still used by
`SyncedTaskRecordTurn` at `ArtboardShell.tsx:484` and the conversation path); only its
settled-timeline usage is removed.

### 4. CSS (`styles/variants-mobile-design.css`)

Reuse existing mobile classes: `thr-reason-steps-static`, `thr-reason-step`,
`thr-reason-step-done`, `thr-reason-mark`, `thr-reason-text`, `thr-turn(-bro)`,
`thr-bubble(-bro)`, `thr-meta`.

Add three new `thr-` classes mirroring their `dt-` counterparts
(`variants-desktop.css:4183` `dt-bubble-answer`, `4188` `dt-reason-collapsed`,
`4214` `dt-answer-text`), styled in mobile's token language:

- `.thr-bubble-answer` — settled bubble container
- `.thr-reason-collapsed` (+ `.thr-reason-collapsed-chev`,
  `.thr-reason-collapsed-open .thr-reason-collapsed-chev`) — the "Show all N steps"
  button
- `.thr-answer-text` — inline answer wrapper

## Behavior matrix (settled mobile turn, after change — identical to desktop)

| steps | answer | Render |
|------:|:------:|--------|
| > 3   | yes    | "Show all N steps" toggle + last 3 steps + answer |
| 1–3   | yes    | steps (no toggle) + answer |
| 0     | yes    | answer only |
| > 0   | no     | steps (+ toggle if > 3), no answer block |
| 0     | no     | **nothing** (see edge case) |

## Edge case (intentional)

A settled turn with **neither** answer text **nor** steps now renders **nothing** on
mobile. Today its `TaskRecordCard` would show a plan/progress card. This matches
desktop, which renders nothing in that case
(`!mobile && isTurnSettled && (answerText || settledReasoningSteps.length > 0)`).

**Verified against desktop.** `TimelineTurnView` has exactly one bro-side settled
render (the desktop `DTAnswerBubble` at `ArtboardShell.tsx:1294`), gated on
`answerText || settledReasoningSteps.length > 0`. There is no desktop `TaskRecordCard`
here — the only `TaskRecordCard` (line `1317`) is `mobile`-gated. So when both
`answerText` and the step list are empty, desktop already renders nothing on the bro
side (just the user message and any plan proposal). The change makes mobile do the
same; it is not a new rule.

This state is rare: `answerText` falls back through `turn.assistant` text →
`record.summary` → `record.description`, so a settled turn is "empty" only when all of
those are blank.

## Testing (`__tests__/App.test.tsx`)

A desktop test already exists: *"collapses to the last 3 steps with a Show all toggle"*
(`App.test.tsx:1092`). Add the mobile mirror on the `/mobile` route:

1. Settled native turn with 4 steps + answer → last 3 steps visible, **"Show all 4
   steps"** toggle present; clicking expands to all 4; the inline answer renders.
2. Steps-only and answer-only cases render correctly.
3. The old settled task card is **gone**: no `thr-status` / progress bar / duplicated
   title for the settled turn.

## Out of scope

No backend, adapter, protocol, or in-flight-rendering changes. Desktop behavior is
unchanged (it routes through the same generalized component with `mobile={false}`).
