# De-dup In-flight Answer From Native Codex Steps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a streaming native codex turn from rendering its latest message twice (once as a step, once as the answer body) by dropping the step whose `codex_item_id` equals the answer message's id.

**Architecture:** One frontend change in `TimelineTurnView`: compute the answer message's `codex_item_id`, filter it out of the settled steps, and pass the filtered list to `DTAnswerBubble` (desktop) and `ThrReasoned` (mobile). Exact identity match — no string heuristics, no backend change.

**Tech Stack:** React / TypeScript / Vitest.

Spec: `docs/superpowers/specs/2026-05-31-native-codex-step-answer-dedup-design.md`

---

## File structure

- Modify: `src/newbro/ui/src/ArtboardShell.tsx` — `TimelineTurnView` de-dup + pass filtered steps.
- Test: `src/newbro/ui/src/__tests__/App.test.tsx` — de-dup render test.

Frontend commands (run from `src/newbro/ui`): `npx vitest run <path> -t "<name>"` and `npx tsc --noEmit`.

---

## Task 1: De-dup the answer message from settled steps

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Write the failing test**

In `src/newbro/ui/src/__tests__/App.test.tsx`, add this test immediately after the existing
`it("collapses to the last 3 steps with a Show all toggle", ...)` test (inside the main
`describe("Newbro artboard shell", ...)` block):

```typescript
  it("does not repeat the answer message as a step", async () => {
    const snapshot = forgeSnapshot("session-existing");
    const turn = timelineTurn({
      thread_id: "codex-import-history",
      executor_turn_id: "turn-d1",
      executor_thread_id: "native-d1",
      userText: "Make the report",
      assistantText: "Writing the section",
    }) as any;
    turn.assistant.metadata = { ...turn.assistant.metadata, codex_item_id: "i2" };
    snapshot.bro_timeline_turns = [turn] as any;
    (snapshot as any).recent_native_turn_reasoning = {
      "codex::native-d1::turn-d1": [
        { item_id: "i1", text: "Reading the spec", kind: "progress", created_at: "t1" },
        { item_id: "i2", text: "Writing the section", kind: "progress", created_at: "t2" },
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

    // The non-matching step still renders.
    expect(await screen.findByText("Reading the spec")).toBeInTheDocument();
    // "Writing the section" is the answer; the matching step is dropped, so it appears once.
    expect(screen.getAllByText("Writing the section")).toHaveLength(1);
  });
```

- [ ] **Step 2: Run it, verify FAIL**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "does not repeat the answer message as a step"`
Expected: FAIL — without the de-dup, "Writing the section" renders twice (once as step `i2`, once as the answer body), so `getAllByText` returns length 2.

- [ ] **Step 3: Add the de-dup in `TimelineTurnView`**

In `src/newbro/ui/src/ArtboardShell.tsx`, find this existing line in `TimelineTurnView`:

```typescript
  const answerText = timelineMessageText(turn.assistant) || record?.summary?.trim() || record?.description?.trim() || "";
```

Immediately AFTER it, add:

```typescript
  const rawAnswerItemId = turn.assistant?.metadata?.codex_item_id;
  const answerItemId = typeof rawAnswerItemId === "string" ? rawAnswerItemId : null;
  const dedupedSettledSteps = answerItemId
    ? settledReasoningSteps.filter((s) => s.id !== answerItemId)
    : settledReasoningSteps;
```

- [ ] **Step 4: Pass the de-duped steps to the render sites**

In the same file, in `TimelineTurnView`'s return JSX, change the mobile `ThrReasoned` line:

```typescript
        <ThrReasoned steps={settledReasoningSteps} />
```

to:

```typescript
        <ThrReasoned steps={dedupedSettledSteps} />
```

and change the desktop `DTAnswerBubble` line:

```typescript
        <DTAnswerBubble bro={bro} steps={settledReasoningSteps} answer={answerText} />
```

to:

```typescript
        <DTAnswerBubble bro={bro} steps={dedupedSettledSteps} answer={answerText} />
```

(Leave the `mobile && isTurnSettled && settledReasoningSteps.length > 0` and
`!mobile && isTurnSettled && (answerText || settledReasoningSteps.length > 0)` GUARD
conditions unchanged — only the `steps=` props passed into the two components change.)

- [ ] **Step 5: Run the test, verify PASS**

Run (from `src/newbro/ui`): `npx vitest run src/__tests__/App.test.tsx -t "does not repeat the answer message as a step"`
Expected: PASS

- [ ] **Step 6: Run the full frontend suite + typecheck**

Run (from `src/newbro/ui`): `npx vitest run` then `npx tsc --noEmit`
Expected: all pass; tsc clean. The existing settled test ("shows visible steps for a settled
native codex turn") uses an assistant with no `codex_item_id`, so `answerItemId` is null,
no step is dropped, and it still passes — it is the regression guard for the normal case.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "fix(ui): de-dup native codex answer message from its steps"
```

---

## Final verification

- [ ] Frontend (from `src/newbro/ui`): `npx vitest run` → all pass; `npx tsc --noEmit` → clean.
- [ ] Manual (`newbro dev`, restarted): while a native codex turn streams, its current
  message shows once (as the body), not also as a step; settled turns are unchanged.

## Notes / gotchas

- `turn.assistant?.metadata?.codex_item_id` is typed `unknown` (metadata is
  `Record<string, unknown>`); the `typeof … === "string"` narrowing via the `rawAnswerItemId`
  local keeps TypeScript happy without a cast.
- `s.id` on a `ReasoningStep` holds the step's `item_id` (set by
  `buildReasoningStepsForNativeTurn` as `step.item_id || "<key>:<index>"`), so the id
  comparison is exact.
- Only the settled bubble path can double (the streaming `dt-bubble-reason` path renders no
  answer body), so filtering `settledReasoningSteps` is sufficient — `reasoningSteps` (the
  streaming list) is intentionally left unchanged.
