# Smooth Assistant Response Animation — Design

**Date:** 2026-06-03
**Status:** Approved design, ready for implementation plan
**Scope:** Frontend-only (React/CSS in `src/newbro/ui`). No backend/runtime/protocol changes.

## Problem

After the user sends a message, the assistant response animation is not smooth and at
times looks dead. Observed sequence:

1. An "ack" shimmer appears, then disappears very quickly.
2. A blank period of a couple of seconds where nothing is visible.
3. The answer starts streaming with visible text updates, but the loading cue is gone — it
   looks finished while it is still typing.

The user wants the interaction to feel continuously alive and smooth from the moment they
hit send until the final answer is complete.

## Root Cause Analysis

The live response is rendered by three components/states that hard-swap, and "alive" is
treated as a narrow whitelist rather than the default. There are three distinct gaps:

- **Gap #1 — the remount.** The timeline list keys rows by `turn_id`
  (`ArtboardShell.tsx:2448`, `:2701`). When the optimistic turn (`turn_id: "optimistic:<id>"`)
  is replaced by the canonical turn (a different `turn_id`), React unmounts the bubble and
  mounts a fresh one. The shimmer/orb restart and any data lag shows as a flash.

- **Gap #2 — the dead void.** `deriveReasoningPhase` (`lib/reasoningPhase.ts`) treats only
  `"pending"`/`"running"` as in-flight. The real task lifecycle passes through
  `created → queued → waiting_executor → running`, and executor spin-up can take seconds.
  When the turn/run reports any status outside `pending`/`running` with no steps and no
  answer, the code falls through to the `done` phase, and `TimelineTurnView` then renders
  `null` (`ArtboardShell.tsx:1247-1259`). The result is a blank screen for seconds.

- **Gap #3 — the alive cue dies.** `deriveReasoningPhase` returns `done` as soon as the
  first answer token arrives (`hasAnswer`). The turn then switches to a different component
  (`SettledAnswerBubble`) which has no orb/shimmer, so the answer streams in looking already
  finished.

The unifying problem: **alive is the exception in the code when it should be the default.**
Any status the logic does not explicitly recognize collapses to blank.

## Goal

Treat **everything from send until a real, complete answer** as one continuous *live*
surface that always renders something and always carries an "alive" cue. Make *settled* the
single, explicit end state. No status can fall through to blank, because alive is the
default — not a whitelist.

## Decisions

- **Scope:** Frontend-only. Gap #2 is partly real backend latency (executor spin-up); the
  UI cannot make data arrive faster, but it keeps showing a lively state instead of a blank.
- **Streaming layout (Layout A):** While the answer streams, reasoning steps stay visible
  above it; they collapse into the "Reasoned" pill only once, at the very end. This minimizes
  motion during streaming.
- **Approach:** Unified `LiveTurnBubble` component that owns the whole turn lifecycle.

## Design

### State model

Replace `ReasoningPhase = "ack" | "streaming" | "done"` with a model where **live is the
default** and **settled is the single explicit end state**:

```
LiveTurnState = "settled" | { live: "connecting" | "reasoning" | "answering" }
```

Derivation, from data already computed in `TimelineTurnView`:

- **`settled`** ⟺ the turn has reached a **terminal status** (`completed` / `failed` /
  `cancelled`). This is the only settle trigger — *not* "first answer token." Kills gap #3.
- Otherwise the turn is **live**, with sub-state:
  - **`answering`** — `answerText` is non-empty (answer streaming) → steps + streaming
    answer + alive cue.
  - **`reasoning`** — at least one reasoning step exists → step list + alive cue.
  - **`connecting`** — neither yet (optimistic send and executor spin-up) → shimmer
    skeleton + alive cue.

The critical property: **anything that is not terminal is live**, so no intermediate or
unknown status (`created`, `queued`, `waiting_executor`, …) can fall through to a blank
`null`. The live branch always renders a bubble with a visible alive cue. Kills gap #2.

`lib/reasoningPhase.ts` is updated: export the new deriver (`deriveLiveTurnState`); remove
`deriveReasoningPhase` and update its callers.

### Component architecture

A single `LiveTurnBubble` replaces `ReasoningBubble` and the live render path, and absorbs
`SettledAnswerBubble`'s markup into its `settled` branch. One component owns the whole
lifecycle.

```
LiveTurnBubble({ broName, state, steps, answer, mobile, canStop, onStop, downloadCtx })
  <bubble container>                          // always mounted while the turn is rendered
    <header> orb + "{bro} is working" · [Stop] </header>   // live only
    <body>
       connecting → <Skeleton/>
       reasoning  → <Steps active/>
       answering  → <Steps/> + <divider/> + <StreamingAnswer cursor/>   // layout A
       settled    → <CollapsedPill/> + <Answer/>   // old SettledAnswerBubble markup
    </body>
```

- `TimelineTurnView` keeps its existing data assembly (`reasoningSteps`, `answerText`,
  native-vs-run sources, dedup of the answer item from settled steps). It computes the new
  `state` via the renamed deriver and renders **one** component for both live and settled,
  instead of branching between two components and a `null`.
- The answer text is rendered by the **same** `MarkdownText` in both `answering` and
  `settled` — no duplication, and the markdown component **stays mounted** as the turn
  crosses from streaming to settled, so the text does not unmount/remount at completion.
- Desktop (`dt-`) and mobile (`thr-`) variants are both preserved (same split as today).

### Remount fix

Key the timeline rows by a **stable identity**: `turn.client_request_id ?? turn.turn_id`
(`ArtboardShell.tsx:2448` and `:2701`). The optimistic and canonical turns share the same
`client_request_id`, so React reuses the same DOM node across the handoff — no teardown, the
shimmer does not restart, no flash. Kills gap #1.

### Transitions and the alive cue

Inside the stable container:

- **Sub-state body crossfade:** when the body swaps (skeleton → steps → answer), use a short
  opacity + translateY transition (~150–200ms) rather than an instant cut. The container
  eases its height as content grows (e.g., answer appearing under steps) instead of jumping.
- **Continuous alive cue:** the bouncing orb in the header persists through
  `connecting → reasoning → answering`; a blinking caret trails the streaming answer text.
  Both disappear only at `settled`. This is the "still alive" guarantee.
- **Settle transition:** steps collapse into the "Reasoned" pill once, at the end (layout A),
  using the existing collapse styling; the orb and caret fade out. Because the answer markdown
  stayed mounted, only the surrounding chrome animates.
- **`prefers-reduced-motion`:** all of the above degrade to instant — no shimmer pulse, no
  caret blink, no height tween.

## Testing

- Rework `ReasoningBubble.test.tsx` → `LiveTurnBubble.test.tsx`: each sub-state renders the
  correct body; the alive cue is present in all three live sub-states and absent when settled.
- Deriver tests: terminal statuses → `settled`; every non-terminal status (including
  `created` / `queued` / `waiting_executor`) → a live sub-state, **never** blank;
  `answerText` present + non-terminal → `answering` (proves gap #3 — live cue stays during
  streaming).
- A test asserting the timeline row key is derived from `client_request_id` when present
  (guards the remount fix).

## Out of Scope

- Any backend, runtime, or protocol change (e.g., new "spinning up" status, earlier
  first-token). The executor spin-up latency is accepted; only its UI presentation changes.
- Unrelated refactoring of `ArtboardShell.tsx` beyond what this change touches.

## Affected Files

- `src/newbro/ui/src/lib/reasoningPhase.ts` — new state deriver.
- `src/newbro/ui/src/ReasoningBubble.tsx` → `LiveTurnBubble.tsx` — unified component.
- `src/newbro/ui/src/ArtboardShell.tsx` — `TimelineTurnView` render branch, `SettledAnswerBubble`
  absorption, stable row keys.
- `src/newbro/ui/src/styles/variants-desktop.css`, `variants-mobile-design.css` — transition
  and alive-cue styles, reduced-motion fallbacks.
- `src/newbro/ui/src/ReasoningBubble.test.tsx` → `LiveTurnBubble.test.tsx` — tests.
