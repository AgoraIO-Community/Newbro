# Display native codex turn messages as visible steps

Date: 2026-05-31
Status: Design (approved for spec review)

## Problem

The native-codex reasoning feature (see
`2026-05-31-native-codex-reasoning-design.md`) already captures the intermediate
assistant messages a codex turn streams (`PROGRESS`/`PLAN`) as ordered steps, keyed by
executor turn identity, and renders them. A live DOM check confirmed the data and the
render both work: a settled turn shows a collapsed **"Reasoned"** pill containing the
steps.

Two problems remain, both about presentation:

1. **Steps are hidden.** On a settled turn the steps sit behind a click-to-reveal
   "Reasoned" pill, so they read as "nothing shows" until clicked. The user wants the
   intermediate messages **visible as steps**, with the final message as the answer.
2. **"Reasoning" framing is wrong.** These steps are the agent's progress *messages*,
   not hidden chain-of-thought. The "is reasoning" / "Reasoned" wording mislabels them.
3. **A noise step.** Every turn's first captured step is a generic dispatch marker
   `"Direct instruction sent to Codex."` with an empty `codex_item_id`. Real codex
   messages always carry a `msg_…` id; the marker should not appear as a step.

This is a presentation change. No new capture, no snapshot-shape change.

## Goals

- On a settled turn, show the intermediate steps **visibly** (compact: last 2–3),
  with a **"Show all N steps"** toggle to expand the rest, and the final message as the
  answer below.
- Stop recording the id-less dispatch-marker step.
- Replace "reasoning" wording with step/message wording.

## Non-goals

- No change to the capture key, snapshot field name (`recent_native_turn_reasoning`
  stays — internal), bounds, or the executor-identity join.
- No new feature for tracked-run turns (their reasoning still flows through the existing
  `execution_runs` path and the same `DTAnswerBubble`).
- Mobile gets the relabel only; the mobile compact-steps treatment is out of scope for
  this pass (the user works on desktop).

## Design

### 1. Backend — drop the id-less dispatch marker (`src/newbro/runtime/session.py`)

In `_record_native_turn_reasoning`, skip any event without a `codex_item_id`. After
computing `item_id`:

```python
        if not item_id:
            return
```

This removes the `"Direct instruction sent to Codex."` marker (and any other id-less
noise) at the source. With every recorded step now carrying an `item_id`, the accumulation
simplifies to: update the last step in place when its `item_id` matches, else append. The
previous blank-`item_id` text-dedup branch is removed (now unreachable).

Test updates (`tests/unit/runtime/test_session_runtime.py`):
- Replace `test_codex_turn_event_skips_blank_item_duplicate_text` with a test asserting
  that events **without** a `codex_item_id` are not recorded at all, while events with an
  `item_id` are.
- `test_codex_turn_event_accumulates_native_reasoning` and the bounds test already use
  non-empty `item_id`s and are unaffected.

### 2. Frontend — visible compact steps on settled turns (`src/newbro/ui/src/ArtboardShell.tsx`)

Rewrite the inner render of `DTAnswerBubble` (it currently shows a collapsed
`dt-reason-collapsed` "Reasoned" pill that reveals steps on click). New behavior:

- Always render the **last 3** steps as a visible list (`dt-reason-steps
  dt-reason-steps-static` with `dt-reason-step dt-reason-step-done` items — existing
  styles, no CSS change).
- When there are **more than 3** steps, render a toggle (reuse the `dt-reason-collapsed`
  button styling) above the list reading **"Show all N steps"**; when expanded it reads
  **"Hide steps"** and the list renders all steps.
- Render the answer (`dt-answer-text` → `MarkdownText`) below the steps; meta line
  unchanged.
- If `steps.length === 0`, render no steps block — just the answer (unchanged).

Sketch:

```tsx
function DTAnswerBubble({ bro, steps, answer }: { bro: BroCardModel; steps: ReasoningStep[]; answer: string }) {
  const [showAll, setShowAll] = React.useState(false);
  const COLLAPSED = 3;
  const hasMore = steps.length > COLLAPSED;
  const visible = showAll ? steps : steps.slice(-COLLAPSED);
  return (
    <div className="dt-turn dt-turn-bro">
      <div className="dt-bubble dt-bubble-bro dt-bubble-answer">
        {steps.length > 0 ? (
          <div className="dt-answer-steps">
            {hasMore ? (
              <button
                type="button"
                className={`dt-reason-collapsed${showAll ? " dt-reason-collapsed-open" : ""}`}
                onClick={() => setShowAll((v) => !v)}
                aria-expanded={showAll}
              >
                <span>{showAll ? "Hide steps" : `Show all ${steps.length} steps`}</span>
                <svg className="dt-reason-collapsed-chev" /* existing chevron */ />
              </button>
            ) : null}
            <ol className="dt-reason-steps dt-reason-steps-static">
              {visible.map((s) => (
                <li key={s.id} className="dt-reason-step dt-reason-step-done">
                  <span className="dt-reason-step-mark" aria-hidden="true" />
                  <span className="dt-reason-step-text">{s.label}</span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
        {answer ? <div className="dt-answer-text"><MarkdownText>{answer}</MarkdownText></div> : null}
      </div>
      <div className="dt-bubble-meta"><MessageMeta label={bro.name} /></div>
    </div>
  );
}
```

### 3. Frontend — relabel (`src/newbro/ui/src/ArtboardShell.tsx`)

- Live streaming kicker `"<Bro> is reasoning"` → `"<Bro> is working"` (both the desktop
  `dt-reason-kicker` and the mobile `thr-reason-kicker` occurrences). This aligns with the
  existing no-steps "is working" fallback, so all in-flight states read consistently.
- Mobile settled `ThrReasoned`: relabel its toggle from `"Reasoned"`/`"Hide reasoning"`
  to `"Show steps"`/`"Hide steps"` (keep its current collapse behavior — out of scope to
  redo mobile layout).

### 4. Frontend tests (`src/newbro/ui/src/__tests__/App.test.tsx`)

- Update the existing settled test (`"shows the Reasoned pill for a settled native codex
  turn"`): with 2 steps, both step texts are visible **without** clicking; assert no
  `"Reasoned"` button exists. Rename the test to reflect visible steps.
- Add a test for **>3 steps**: only the last 3 are visible initially, a
  `"Show all N steps"` button is present, clicking it reveals the earlier step(s).
- The running-stream test (`"streams reasoning for a running native codex turn"`) asserts
  the `.dt-bubble-reason` class and step texts, not the kicker wording, so the "is working"
  relabel does not break it. Scan `App.test.tsx` for any assertion on the literal text
  `"is reasoning"` or `/Reasoned/` and update those.

## Edge cases

- 1 step only (no intermediate messages beyond the answer): with the dispatch marker
  dropped, a turn whose only content is the final message has 0 steps → no steps block,
  just the answer.
- Many steps: capped at the existing 8-step projection; "Show all" reveals up to 8.
- Tracked-run turns: unaffected — `buildReasoningStepsForNativeTurn` still returns `[]`
  when `turn.task` is set, so `DTAnswerBubble` receives whatever `settledReasoningSteps`
  the run-based path produced; the same compact rendering applies uniformly.

## Affected files

- `src/newbro/runtime/session.py` — id-less skip in `_record_native_turn_reasoning`.
- `tests/unit/runtime/test_session_runtime.py` — replace the blank-id dedup test.
- `src/newbro/ui/src/ArtboardShell.tsx` — rewrite `DTAnswerBubble` inner render; relabel
  kickers and `ThrReasoned`.
- `src/newbro/ui/src/__tests__/App.test.tsx` — update/added settled-step tests.

## Testing

Backend: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q`.
Frontend (from `src/newbro/ui`): `npx vitest run` and `npx tsc --noEmit`.
Manual (`newbro dev`, after restart): a settled native turn shows its last 2–3 messages as
visible steps with a "Show all N steps" toggle and the final message as the answer; no
"Direct instruction sent to Codex." line; no "reasoning" wording.
