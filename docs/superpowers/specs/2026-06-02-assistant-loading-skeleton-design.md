# Responsive Assistant Loading State — Design

Status: design (approved for planning)
Date: 2026-06-02

## Summary

Make the chat UI show a "Bro is working" loading state **the instant a message
is sent**, so the user never stares at a blank wait and doubts whether the
assistant is dead. Today the assistant-side reasoning bubble renders only once
`reasoningSteps.length > 0`, so the gap between send and the first reasoning line
shows nothing. This adds an **instant shimmer skeleton** (the "ack" phase) and
formalizes the live reasoning bubble into three phases — **ack → streaming →
done** — on both desktop and mobile.

This ports the loading treatment prototyped in `design/` (the `DTReasoningBubble`
"instant skeleton + streamed thinking + collapse") into the real UI. It is
frontend-only: no protocol, runtime, or backend changes.

## Goal / Success Criterion

- Within a frame of sending a text or audio turn, the assistant side shows a
  shimmer "Bro is working" skeleton, and keeps showing a live working state
  until the first reasoning line, the answer, or a terminal status arrives.
- The user is never left with a silent, empty assistant area while a turn is
  in flight.

## Non-Goals

- Tool marks (act-vs-think distinction) — needs a new backend signal; deferred.
- Steer / mid-turn redirect / cancel wiring — runtime-dependent; deferred.
- A timeout / "taking longer than usual" / stuck-turn affordance — worthwhile
  follow-up, not in this V1. The shimmer signals "working," not "stuck."
- Any change to how reasoning/progress signals are produced by the runtime.

## Context (current behavior)

- `src/newbro/ui/src/ArtboardShell.tsx` `TimelineBroTurn` renders the live
  reasoning bubble only when `reasoningSteps.length > 0`, and only on desktop
  (`!mobile && reasoningSteps.length > 0`).
- On send, an **optimistic turn is already inserted** into the timeline with
  `status: "pending"` (`optimisticTextTurnToTimeline` /
  `optimisticAudioTurnToTimeline`), swapped for the canonical turn by
  `client_request_id`. So a pending turn is present instantly — but it has no
  `activeRun` and no reasoning steps yet, so nothing renders on the assistant
  side. That blank gap is the problem.
- Existing signals on `TimelineBroTurn`: `turn.status`
  (`pending | running | completed | failed | cancelled`), `activeRun`,
  `nativeInFlight`, `reasoningSteps`, `answerText`.

## Design

### Unit 1 — `deriveReasoningPhase` (pure function; the testable core)

```ts
type ReasoningPhase = "ack" | "streaming" | "done";

function deriveReasoningPhase(input: {
  status: BroTimelineTurn["status"]; // turn.status
  stepCount: number;                  // reasoningSteps.length
  hasAnswer: boolean;                 // answerText !== ""
}): ReasoningPhase;
```

Rules (note: in-flight is keyed off **`turn.status`**, NOT off `activeRun` /
reasoning steps — this is what makes the just-sent pending turn show the
skeleton):

```
inFlight = (status === "pending" || status === "running") && !hasAnswer

done      → !inFlight                       // settled (completed/failed/cancelled) or hasAnswer
streaming → inFlight && stepCount > 0
ack       → inFlight && stepCount === 0
```

This guarantees the optimistic `status: "pending"` turn (no activeRun, no steps,
no answer) resolves to `ack` → the skeleton shows immediately.

### Unit 2 — `<ReasoningBubble>` (presentational component)

Extracted out of the ~2000-line `ArtboardShell.tsx` into a focused component.

```tsx
<ReasoningBubble
  broName={string}
  phase={ReasoningPhase}
  steps={ReasoningStep[]}        // windowed steps for streaming; settled steps for done
  answer={string}               // for done
  mobile={boolean}
  collapsedOpen={boolean}
  onToggleCollapsed={() => void}
/>
```

Renders by phase (surface class prefix `dt-` desktop / `thr-` mobile, matching
existing conventions):

- **ack** — the existing bubble shell + "{broName} is working" kicker, with the
  step list replaced by **two shimmer skeleton lines** (`*-reason-skel` +
  `*-reason-shimmer` keyframe). The only new markup.
- **streaming** — the existing windowed, fading last-3 reasoning steps. Unchanged
  behavior; the first real line simply replaces the shimmer.
- **done** — the existing answer + tucked-away collapsed reasoning (desktop
  expandable / mobile collapsed pill). Unchanged behavior.

### Integration in `TimelineBroTurn`

`TimelineBroTurn` keeps computing the signals it already does, then:

```ts
const phase = deriveReasoningPhase({
  status: turn.status,
  stepCount: reasoningSteps.length,
  hasAnswer: answerText !== "",
});
```

and renders `<ReasoningBubble phase=… mobile=… …/>`, replacing the current inline
`!mobile && reasoningSteps.length > 0` block. The live bubble (ack + streaming)
now renders on **both** desktop and mobile; the done-phase collapse keeps each
surface's existing treatment.

### CSS

Port the shimmer pieces from the `design/` commit into the real stylesheets:
- desktop: `@keyframes dt-reason-shimmer` + `.dt-reason-skel`
- mobile: the `thr-reason-shimmer` + skeleton equivalent

No other CSS changes — streaming/done styles already exist.

## Data Flow

1. Send → optimistic turn (`status: "pending"`) inserted instantly → `phase =
   ack` → shimmer skeleton renders within a frame.
2. First reasoning/progress line arrives (`reasoningSteps.length > 0`, still
   running) → `phase = streaming` → windowed steps replace the shimmer.
3. Answer / terminal status (`completed | failed | cancelled` or `hasAnswer`) →
   `phase = done` → answer + collapsed reasoning.

## Edge Cases

- Fast/cached turn (pending → answer, no steps): `ack → done`, no streaming
  flicker.
- Failed / cancelled turn: not in-flight → `done` (no perpetual shimmer).
- Backend truly hangs (status never changes): shimmer persists ("working", not
  "stuck"). A timeout affordance is a deferred follow-up (Non-Goals).
- Optimistic → canonical swap: continuous because both carry the same
  `client_request_id`; phase is derived per-turn from `turn.status`.

## Testing

Test runner: **Vitest + @testing-library/react** (`cd src/newbro/ui && npm test`,
i.e. `vitest run`). Existing UI tests live under `src/newbro/ui/src/__tests__/`
and `src/newbro/ui/src/**/*.test.tsx`.

- **`deriveReasoningPhase`** (unit) — `pending`+0 steps → `ack`; `running`+0 →
  `ack`; `running`+steps → `streaming`; `pending`+`hasAnswer` → `done`;
  `completed` → `done`; `failed` → `done`; `cancelled` → `done`.
- **`<ReasoningBubble>`** (RTL render) — ack renders the shimmer skeleton and no
  step list; streaming renders the windowed steps; done renders answer +
  collapsed reasoning; `mobile` uses `thr-` classes, desktop uses `dt-`.
- Manual: send a text turn against a running backend and confirm the skeleton
  appears immediately and transitions ack → streaming → done.

## Files

- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (`TimelineBroTurn`: derive phase,
  render `<ReasoningBubble>`; remove the `!mobile && reasoningSteps.length > 0`
  inline block).
- Create: `deriveReasoningPhase` + `<ReasoningBubble>` (new module under
  `src/newbro/ui/src/`, following existing file/layout conventions).
- Modify: the desktop + mobile stylesheets — add the shimmer skeleton CSS.
- Create: unit/render tests next to the existing UI tests.
