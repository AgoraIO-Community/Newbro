# De-duplicate the in-flight answer from native codex steps

Date: 2026-05-31
Status: Design (approved for spec review)

## Problem

After the native-codex steps feature shipped, an in-flight turn shows its latest message
**twice**: once as a step and once as the answer body. Confirmed from the live DOM — an
in-flight turn rendered `answer: "I'll create a future-back retrospective style"` and
`steps: ["I'll create a future-back retrospective style"]` (identical).

Root cause: while a turn streams, its "answer" (`turn.assistant.text`) is the **latest
commentary message**, and that same message is also captured as a step. So the current
message renders as both the answer body and the last step. Once the turn settles, the
answer becomes codex's **final-answer** message (never captured as a step), so the
duplication disappears — which is why "the last message is fine" but in-progress turns
look doubled.

A live capture confirms the de-dup signal: the in-flight turn's answer carries a
`codex_item_id` that matches the duplicated step's `item_id`, while a settled turn's
final answer has a `null`/different `codex_item_id` not present among its steps.

## Goal

For a native turn, never render the same message as both a step and the answer body, using
an exact identity (`codex_item_id`) match — no string/prefix heuristics.

## Non-goals

- No backend change. The capture, snapshot field, key, and bounds are unchanged.
- No change to settled turns' appearance (their answer is already distinct from steps).

## Design

In `TimelineTurnView` (`src/newbro/ui/src/ArtboardShell.tsx`), after `settledReasoningSteps`
is computed, drop the single step whose id equals the answer message's `codex_item_id`:

```tsx
const answerItemId = typeof turn.assistant?.metadata?.codex_item_id === "string"
  ? turn.assistant.metadata.codex_item_id
  : null;
const dedupedSettledSteps = answerItemId
  ? settledReasoningSteps.filter((s) => s.id !== answerItemId)
  : settledReasoningSteps;
```

`s.id` holds the step's `item_id` (set by `buildReasoningStepsForNativeTurn` as
`step.item_id || "<key>:<index>"`). Pass `dedupedSettledSteps` to the desktop
`DTAnswerBubble` and the mobile `ThrReasoned` in place of `settledReasoningSteps`.

Behavior:
- **Streaming:** answer has an `item_id` that matches its step → that step is dropped → the
  message shows once (as the body); earlier messages remain steps.
- **Settled:** the final answer's `item_id` is `null`/different and not among the steps →
  nothing is dropped → all intermediate steps plus the distinct final answer, unchanged.
- **Transition:** when a streaming message is no longer the answer (the real final lands),
  its `item_id` no longer matches → it reappears as a normal step.

## Edge cases

- `answerItemId` null (settled / no metadata) → no filtering; identical to today.
- `answerItemId` set but not among the steps (e.g. a synced final-answer that carries an id)
  → no step removed; correct, since the final answer is not a step.
- The streaming (`dt-bubble-reason`) path renders steps only (no answer body), so it cannot
  double; only the settled bubble path needs the de-dup. Applying it to
  `settledReasoningSteps` is sufficient.

## Testing

Frontend (`src/newbro/ui/src/__tests__/App.test.tsx`): a settled native turn whose
`assistant.metadata.codex_item_id` equals one of its steps' `item_id` renders that message
**once** — assert the answer text is present and that the matching step line does **not**
appear a second time, while a non-matching step still appears. A turn whose answer item_id
does not match any step keeps all steps (regression guard for the normal settled case).

## Affected files

- `src/newbro/ui/src/ArtboardShell.tsx` — `TimelineTurnView` de-dup + pass `dedupedSettledSteps`
  to `DTAnswerBubble` and `ThrReasoned`.
- `src/newbro/ui/src/__tests__/App.test.tsx` — de-dup test.
