# Native Codex Turn Steps (visible) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a native codex turn's intermediate messages as visible compact steps (last 2–3 + "Show all N steps"), with the final message as the answer; drop the id-less dispatch-marker step; relabel "reasoning" wording.

**Architecture:** Presentation-only change on top of the existing native-reasoning capture/join. Backend: skip recording steps that carry no `codex_item_id`. Frontend: rewrite `DTAnswerBubble`'s inner render to show steps by default (capped to the last 3 with a "Show all N steps" toggle) and relabel the live kicker + the mobile `ThrReasoned` toggle.

**Tech Stack:** Python 3.12 / Pydantic / pytest (backend); React / TypeScript / Vitest (frontend).

Spec: `docs/superpowers/specs/2026-05-31-native-codex-turn-steps-design.md`

---

## File structure

- Modify: `src/newbro/runtime/session.py` — `_record_native_turn_reasoning` skips id-less steps.
- Test: `tests/unit/runtime/test_session_runtime.py` — replace the blank-id dedup test.
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` — `DTAnswerBubble` inner render; relabel kickers + `ThrReasoned`.
- Test: `src/newbro/ui/src/__tests__/App.test.tsx` — update settled test, add >3-steps test.

Backend test command: `.venv/bin/python -m pytest <path>::<test> -v`
Frontend commands (run from `src/newbro/ui`): `npx vitest run <path> -t "<name>"` and `npx tsc --noEmit`.

No CSS changes: the steps reuse `dt-reason-steps dt-reason-steps-static` + `dt-reason-step`, and the toggle reuses the existing `dt-reason-collapsed` button style.

---

## Task 1: Backend — drop id-less dispatch-marker steps

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Replace the blank-id dedup test with an id-less-skip test**

In `tests/unit/runtime/test_session_runtime.py`, find the existing test
`test_codex_turn_event_skips_blank_item_duplicate_text` and replace the WHOLE function
(from its `@pytest.mark.anyio` decorator through its final assertion) with:

```python
@pytest.mark.anyio
async def test_codex_turn_event_skips_steps_without_item_id():
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    request = OutboundTurnRequest(
        request_id="out-turn-1",
        persona_id="forge",
        executor_node_id="node-forge",
        target_thread_id="thread-1",
        client_request_id="client-text-1",
        text="do the thing",
        status="accepted",
        created_at="2026-05-30T08:00:00+00:00",
    )
    await session.blackboard.put_outbound_turn_request(request)

    async def emit(text, *, item_id):
        await session.handle_codex_turn_event(
            CodexTurnEventMessage(
                request_id="out-turn-1",
                node_id="node-forge",
                target_persona_id="forge",
                target_thread_id="thread-1",
                event_type="progress",
                message=text,
                executor_thread_id="native-thread-1",
                executor_turn_id="turn-1",
                metadata={"codex_item_id": item_id},
            )
        )

    await emit("Direct instruction sent to Codex.", item_id="")   # dispatch marker -> skipped
    await emit("Reading the spec", item_id="msg-1")               # real step -> recorded
    await emit("Writing the code", item_id="msg-2")               # real step -> recorded

    snapshot = await session.snapshot(sync_imported_codex_threads=False)
    steps = snapshot.recent_native_turn_reasoning["codex::native-thread-1::turn-1"]
    assert [s.text for s in steps] == ["Reading the spec", "Writing the code"]
    assert all(s.item_id for s in steps)
```

- [ ] **Step 2: Run it, verify it FAILS**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_codex_turn_event_skips_steps_without_item_id -v`
Expected: FAIL — the assertion list includes a leading `"Direct instruction sent to Codex."` because id-less steps are still recorded today.

- [ ] **Step 3: Skip id-less steps and simplify accumulation**

In `src/newbro/runtime/session.py`, in `_record_native_turn_reasoning`, find this block:

```python
        raw_item_id = message.metadata.get("codex_item_id")
        item_id = raw_item_id if isinstance(raw_item_id, str) else ""
        step = NativeReasoningStep(
            item_id=item_id,
            text=text[:_NATIVE_REASONING_TEXT_LIMIT],
            kind="plan" if event_type == "plan" else "progress",
            created_at=timestamp,
        )
        steps = list(self._native_turn_reasoning.get(key, []))
        if steps and item_id and steps[-1].item_id == item_id:
            steps[-1] = step  # same codex item streaming -> grow in place
        elif steps and not item_id and steps[-1].text == step.text:
            return  # blank-item-id duplicate text -> skip
        else:
            steps.append(step)
```

Replace it with:

```python
        raw_item_id = message.metadata.get("codex_item_id")
        item_id = raw_item_id if isinstance(raw_item_id, str) else ""
        if not item_id:
            return  # id-less events (e.g. the dispatch marker) are not real steps
        step = NativeReasoningStep(
            item_id=item_id,
            text=text[:_NATIVE_REASONING_TEXT_LIMIT],
            kind="plan" if event_type == "plan" else "progress",
            created_at=timestamp,
        )
        steps = list(self._native_turn_reasoning.get(key, []))
        if steps and steps[-1].item_id == item_id:
            steps[-1] = step  # same codex item streaming -> grow in place
        else:
            steps.append(step)
```

(Leave the rest of the method — the store-cap slice, the move-to-end, and the turn-cap loop — unchanged.)

- [ ] **Step 4: Run the test, verify it PASSES**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_codex_turn_event_skips_steps_without_item_id -v`
Expected: PASS

- [ ] **Step 5: Run the full runtime file to check no regressions**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q`
Expected: all pass (the accumulation and bounds tests use non-empty `item_id`s and are unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/newbro/runtime/session.py tests/unit/runtime/test_session_runtime.py
git commit -m "feat: drop id-less dispatch-marker from native codex reasoning steps"
```

---

## Task 2: Frontend — visible compact steps in `DTAnswerBubble`

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Update the settled test + add a >3-steps test**

In `src/newbro/ui/src/__tests__/App.test.tsx`, find the test
`it("shows the Reasoned pill for a settled native codex turn", ...)`. Replace its
assertions block — the part that currently reads:

```typescript
    const reasoned = await screen.findByRole("button", { name: /Reasoned/i });
    expect(reasoned).toBeInTheDocument();
    fireEvent.click(reasoned);
    expect(screen.getByText("Reading the spec")).toBeInTheDocument();
    expect(screen.getByText("Writing the section")).toBeInTheDocument();
```

with:

```typescript
    // Two steps render visibly with no toggle and no "Reasoned" pill.
    expect(await screen.findByText("Reading the spec")).toBeInTheDocument();
    expect(screen.getByText("Writing the section")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reasoned/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Show all/i })).toBeNull();
```

Also rename the test title from `"shows the Reasoned pill for a settled native codex turn"`
to `"shows visible steps for a settled native codex turn"`.

Then add this new test immediately after it (mirror the same snapshot/thread setup; only
the reasoning map and assertions differ — it uses 4 steps):

```typescript
  it("collapses to the last 3 steps with a Show all toggle", async () => {
    const snapshot = forgeSnapshot("session-existing");
    snapshot.bro_timeline_turns = [
      timelineTurn({
        thread_id: "codex-import-history",
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
    const importedThread = {
      thread_id: "codex-import-history",
      persona_id: "forge",
      persona_name: "Forge",
      executor_id: "codex",
      executor_node_id: "node-forge",
      execution_session_id: null,
      status: "completed",
      title: "Imported Codex thread",
      preview: "Remote history",
      progress: 100,
      task_ids: [],
      active_task_id: null,
      latest_task_id: null,
      has_resume_handle: true,
      updated_at: "2026-05-26T22:00:00+00:00",
      timeline_status: "loaded",
      timeline_error: null,
      diagnostics: { codex_thread_id: "codex-native-history" },
    };
    snapshot.bro_threads = [importedThread] as any;
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValue(snapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=codex-import-history");

    render(<RouterProvider router={getRouter()} />);

    // Last 3 visible by default; the earliest is hidden behind the toggle.
    expect(await screen.findByText("Mapping the files")).toBeInTheDocument();
    expect(screen.getByText("Writing the section")).toBeInTheDocument();
    expect(screen.getByText("Verifying output")).toBeInTheDocument();
    expect(screen.queryByText("Reading the spec")).toBeNull();

    const showAll = screen.getByRole("button", { name: /Show all 4 steps/i });
    fireEvent.click(showAll);
    expect(screen.getByText("Reading the spec")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Hide steps/i })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the two tests, verify they FAIL**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "native codex turn" && npx vitest run src/__tests__/App.test.tsx -t "Show all toggle"`
Expected: FAIL — the settled test still finds a "Reasoned" button (old render); the new test can't find "Mapping the files" visible by default / the "Show all 4 steps" button.

- [ ] **Step 3: Rewrite `DTAnswerBubble`'s inner render**

In `src/newbro/ui/src/ArtboardShell.tsx`, replace the entire `DTAnswerBubble` function
(its leading comment through its closing brace) with:

```tsx
// Settled desktop bro turn — the agent's progress messages shown as compact steps
// (last 3 by default, with a "Show all N steps" toggle) followed by the final answer.
function DTAnswerBubble({ bro, steps, answer }: { bro: BroCardModel; steps: ReasoningStep[]; answer: string }) {
  const [showAll, setShowAll] = React.useState(false);
  const COLLAPSED = 3;
  const hasMore = steps.length > COLLAPSED;
  const visible = showAll ? steps : steps.slice(-COLLAPSED);
  return (
    <div className="dt-turn dt-turn-bro">
      <div className="dt-bubble dt-bubble-bro dt-bubble-answer">
        {steps.length > 0 ? (
          <>
            {hasMore ? (
              <button
                type="button"
                className={`dt-reason-collapsed${showAll ? " dt-reason-collapsed-open" : ""}`}
                onClick={() => setShowAll((v) => !v)}
                aria-expanded={showAll}
              >
                <span>{showAll ? "Hide steps" : `Show all ${steps.length} steps`}</span>
                <svg className="dt-reason-collapsed-chev" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M6 9l6 6 6-6"/>
                </svg>
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
          </>
        ) : null}
        {answer ? (
          <div className="dt-answer-text">
            <MarkdownText>{answer}</MarkdownText>
          </div>
        ) : null}
      </div>
      <div className="dt-bubble-meta">
        <MessageMeta label={bro.name} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the two tests, verify they PASS**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "native codex turn" && npx vitest run src/__tests__/App.test.tsx -t "Show all toggle"`
Expected: PASS

- [ ] **Step 5: Run the full frontend suite + typecheck**

Run (from `src/newbro/ui`): `npx vitest run` then `npx tsc --noEmit`
Expected: all pass; tsc clean. (The running-stream test asserts the `.dt-bubble-reason` class and step texts, not the pill, so it is unaffected.)

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): show native codex turn steps visibly with Show all toggle"
```

---

## Task 3: Frontend — relabel "reasoning" wording

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`

This task has no new behavior, so it is verified by the existing suite + typecheck rather
than a new test.

- [ ] **Step 1: Relabel the live streaming kickers**

In `src/newbro/ui/src/ArtboardShell.tsx` there are two live-stream kicker lines that read
`{bro.name} is reasoning` (one in the desktop `dt-reason-kicker`, one in the mobile
`thr-reason-kicker`). Change BOTH occurrences of:

```tsx
              {bro.name} is reasoning
```

to:

```tsx
              {bro.name} is working
```

(Use replace-all for the exact string `{bro.name} is reasoning` — there are exactly two.)

- [ ] **Step 2: Relabel the mobile `ThrReasoned` toggle**

In the `ThrReasoned` function, change:

```tsx
        <span>{open ? "Hide reasoning" : "Reasoned"}</span>
```

to:

```tsx
        <span>{open ? "Hide steps" : "Show steps"}</span>
```

Also update the comment above `ThrReasoned` if it mentions "Reasoned": change the leading
comment line `// Collapsed "Reasoned" affordance shown on a finished mobile bro turn — the live`
to `// Collapsed steps affordance shown on a finished mobile bro turn — the live`.

- [ ] **Step 3: Run the full frontend suite + typecheck**

Run (from `src/newbro/ui`): `npx vitest run` then `npx tsc --noEmit`
Expected: all pass; tsc clean. (No test asserts the literal `"is reasoning"` text; the
settled desktop test was already updated in Task 2 to not expect "Reasoned".)

- [ ] **Step 4: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "feat(ui): relabel native reasoning wording to step/working framing"
```

---

## Final verification

- [ ] Backend: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q` → all pass.
- [ ] Frontend (from `src/newbro/ui`): `npx vitest run` → all pass; `npx tsc --noEmit` → clean.
- [ ] Manual (`newbro dev`, fully restarted): a settled native codex turn shows its last
  2–3 messages as visible steps with a "Show all N steps" toggle when there are more, the
  final message as the answer below, no "Direct instruction sent to Codex." line, and no
  "reasoning"/"Reasoned" wording (live kicker reads "is working").

## Notes / gotchas

- The steps + toggle are direct flex children of `dt-bubble-answer` (a flex column), so the
  toggle's `align-self: flex-start` (from `dt-reason-collapsed`) and the existing
  `dt-reason-steps-static` divider work without new CSS. Do not wrap them in an extra div.
- `dt-reason-steps-static` forces every step to `opacity: 1` (no fade) and muted text —
  exactly what we want for a settled, fully-visible list.
- Only the desktop `DTAnswerBubble` gets the compact-visible treatment; mobile keeps the
  collapsible `ThrReasoned` (relabeled). This is intentional per the spec's scope.
