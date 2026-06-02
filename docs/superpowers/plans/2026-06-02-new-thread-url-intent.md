# New-Thread URL Intent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Bro Detail jumping to a random thread after sending the first message in a new thread, by making the `thread` URL param the single source of selection intent (`<id>` | `new` | absent) and removing the in-memory race-papering fallbacks.

**Architecture:** Extract all thread-selection state/derivation/effects/actions into one generic, self-contained `useThreadSelection` hook (the new-thread intent is durable in the URL; `pendingNewThread` is seeded from the `new` sentinel; auto-select to `threads[0]` fires only when there is no selection at all). Both the desktop and mobile Bro Detail components call the hook, deleting their two duplicated blocks and the now-dead `isResolveLag` / `recentResolveRef`.

**Tech Stack:** React + TypeScript, Vitest + @testing-library/react (`cd src/newbro/ui && npm test`; `renderHook` for the hook). The URL helpers in `src/newbro/ui/src/lib/session-url.ts` already pass `"new"` through unchanged (a non-empty string), so no change there is required — the hook interprets the sentinel.

---

## File Structure

- Create: `src/newbro/ui/src/lib/useThreadSelection.ts` — the selection hook (state, derivation, effects, actions). Owns: `selectedThreadId`, `pendingNewThread`, `pendingWorkspaceId`, `workspacePickerOpen`, internal `openedThreadRef`/`activeThreadRef`, the auto-select / open-thread / unmount-close effects, and `selectThread`/`newThread`/`selectWorkspace`/`resolveThread`.
- Create: `src/newbro/ui/src/lib/useThreadSelection.test.tsx` — `renderHook` tests.
- Create: `src/newbro/ui/src/lib/session-url.test.ts` (if absent) — pin the `"new"` passthrough.
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` — replace the desktop selection block (`~3234–3371`) and the mobile selection block (`~3951–4078`) with `useThreadSelection(...)`; delete `isResolveLag` + `recentResolveRef`.

All commands run from `src/newbro/ui`. Run one test file with `npx vitest run <path-relative-to-src/newbro/ui>`.

---

### Task 1: `useThreadSelection` hook (the new behavior, fully tested)

**Files:**
- Create: `src/newbro/ui/src/lib/useThreadSelection.ts`
- Test: `src/newbro/ui/src/lib/useThreadSelection.test.tsx`
- Test: `src/newbro/ui/src/lib/session-url.test.ts`

- [ ] **Step 1: Write the failing hook tests**

`src/newbro/ui/src/lib/useThreadSelection.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useThreadSelection } from "./useThreadSelection";

interface T { threadId: string; title?: string }

function setUrl(search: string) {
  window.history.replaceState({}, "", search ? `/?${search}` : "/");
}
function threadParam(): string | null {
  return new URLSearchParams(window.location.search).get("thread");
}
function defaults(over: Partial<Parameters<typeof useThreadSelection<T>>[0]> = {}) {
  return {
    broId: "bro-1",
    broSource: "runtime",
    threads: [] as T[],
    workspaceOptions: ["ws-1"],
    needsConnect: false,
    openThread: vi.fn(),
    closeThread: vi.fn(),
    onNoWorkspace: vi.fn(),
    ...over,
  };
}

describe("useThreadSelection", () => {
  beforeEach(() => setUrl(""));

  it("?thread=new seeds pendingNewThread and never auto-selects, even with threads", () => {
    setUrl("thread=new");
    const threads: T[] = [{ threadId: "a" }, { threadId: "b" }];
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ threads })));
    expect(result.current.pendingNewThread).toBe(true);
    expect(result.current.selectedThreadId).toBeNull();
    expect(result.current.activeThreadId).toBeNull();
    expect(threadParam()).toBe("new"); // unchanged — no auto-select to threads[0]
  });

  it("no thread param + threads present → auto-selects threads[0] and writes the url", () => {
    const threads: T[] = [{ threadId: "a" }, { threadId: "b" }];
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ threads })));
    expect(result.current.selectedThreadId).toBe("a");
    expect(threadParam()).toBe("a");
  });

  it("selectWorkspace enters new-thread mode and marks the url", () => {
    const { result } = renderHook(() => useThreadSelection<T>(defaults()));
    act(() => result.current.selectWorkspace("ws-1"));
    expect(result.current.pendingNewThread).toBe(true);
    expect(result.current.selectedThreadId).toBeNull();
    expect(threadParam()).toBe("new");
  });

  it("resolveThread to an id not yet in threads → activeThreadId is that id, selectedThread null (no threads[0])", () => {
    const threads: T[] = [{ threadId: "a" }];
    setUrl("thread=new");
    const { result, rerender } = renderHook(
      (props: { threads: T[] }) => useThreadSelection<T>(defaults({ threads: props.threads })),
      { initialProps: { threads } },
    );
    act(() => result.current.resolveThread("newId"));
    expect(result.current.pendingNewThread).toBe(false);
    expect(result.current.selectedThreadId).toBe("newId");
    expect(result.current.activeThreadId).toBe("newId"); // optimistic turns still match
    expect(result.current.selectedThread).toBeNull();     // not yet loaded, NOT threads[0]
    expect(threadParam()).toBe("newId");
    // once the new thread appears, it resolves (and never snaps to threads[0])
    rerender({ threads: [{ threadId: "a" }, { threadId: "newId", title: "New" }] });
    expect(result.current.selectedThread?.threadId).toBe("newId");
  });

  it("selectThread selects an existing thread and writes the url", () => {
    const threads: T[] = [{ threadId: "a" }, { threadId: "b" }];
    setUrl("thread=a");
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ threads })));
    act(() => result.current.selectThread("b"));
    expect(result.current.selectedThreadId).toBe("b");
    expect(result.current.selectedThread?.threadId).toBe("b");
    expect(threadParam()).toBe("b");
  });

  it("newThread with no workspaces calls onNoWorkspace and does not open the picker", () => {
    const onNoWorkspace = vi.fn();
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ workspaceOptions: [], onNoWorkspace })));
    act(() => result.current.newThread());
    expect(onNoWorkspace).toHaveBeenCalledTimes(1);
    expect(result.current.workspacePickerOpen).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/lib/useThreadSelection.test.tsx`
Expected: FAIL — cannot find module `./useThreadSelection`.

- [ ] **Step 3: Write the hook**

`src/newbro/ui/src/lib/useThreadSelection.ts`:
```ts
import { useEffect, useRef, useState } from "react";
import { readThreadIdFromUrl, replaceThreadIdInUrl } from "./session-url";

const NEW_THREAD_SENTINEL = "new";

export interface UseThreadSelectionParams<T extends { threadId: string }> {
  broId: string | null;
  broSource: string | null;
  threads: T[];
  workspaceOptions: unknown[];
  needsConnect: boolean;
  openThread: (broId: string, threadId: string) => void;
  closeThread: (broId: string, threadId: string | null) => void;
  onNoWorkspace: () => void;
}

export interface UseThreadSelectionResult<T> {
  selectedThreadId: string | null;
  pendingNewThread: boolean;
  pendingWorkspaceId: string | null;
  workspacePickerOpen: boolean;
  setWorkspacePickerOpen: (open: boolean) => void;
  selectedThread: T | null;
  activeThreadId: string | null;
  selectThread: (threadId: string) => void;
  newThread: () => void;
  selectWorkspace: (workspaceId: string) => void;
  resolveThread: (threadId: string | null) => void;
}

export function useThreadSelection<T extends { threadId: string }>(
  params: UseThreadSelectionParams<T>,
): UseThreadSelectionResult<T> {
  const { broId, broSource, threads, workspaceOptions, needsConnect, openThread, closeThread, onNoWorkspace } = params;

  const initialUrlThread = readThreadIdFromUrl();
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(
    initialUrlThread === NEW_THREAD_SENTINEL ? null : initialUrlThread,
  );
  const [pendingNewThread, setPendingNewThread] = useState(initialUrlThread === NEW_THREAD_SENTINEL);
  const [pendingWorkspaceId, setPendingWorkspaceId] = useState<string | null>(null);
  const [workspacePickerOpen, setWorkspacePickerOpen] = useState(false);
  const openedThreadRef = useRef<string | null>(null);
  const activeThreadRef = useRef<string | null>(null);

  const matchedThread = threads.find((thread) => thread.threadId === selectedThreadId) ?? null;
  const selectedThread = pendingNewThread ? null : matchedThread;
  // The id is kept even while the matching record hasn't loaded yet, so a
  // just-resolved new thread's optimistic turns still belong to it.
  const activeThreadId = pendingNewThread ? null : selectedThreadId;

  // Auto-select the latest thread ONLY when there is no selection intent at all.
  // A selected-but-not-yet-loaded id (or `thread=new`) is left alone — no snap to threads[0].
  useEffect(() => {
    if (pendingNewThread || selectedThreadId !== null || threads.length === 0) return;
    setSelectedThreadId(threads[0].threadId);
    replaceThreadIdInUrl(threads[0].threadId);
  }, [pendingNewThread, selectedThreadId, threads]);

  // Open the active thread server-side (skip a just-resolved/just-opened one).
  useEffect(() => {
    if (pendingNewThread || needsConnect || !broId || broSource !== "runtime" || !activeThreadId) return;
    if (openedThreadRef.current === activeThreadId) return;
    openedThreadRef.current = activeThreadId;
    openThread(broId, activeThreadId);
  }, [activeThreadId, broId, broSource, needsConnect, pendingNewThread, openThread]);

  useEffect(() => {
    activeThreadRef.current = activeThreadId;
  }, [activeThreadId]);

  useEffect(() => {
    return () => {
      if (broSource === "runtime" && broId) {
        closeThread(broId, activeThreadRef.current);
      }
    };
  }, [broId, broSource, closeThread]);

  function selectThread(threadId: string) {
    setPendingNewThread(false);
    setPendingWorkspaceId(null);
    setWorkspacePickerOpen(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = null;
  }

  function newThread() {
    if (workspaceOptions.length === 0) {
      onNoWorkspace();
      return;
    }
    setWorkspacePickerOpen(true);
  }

  function selectWorkspace(workspaceId: string) {
    if (broId && broSource === "runtime") {
      closeThread(broId, activeThreadId);
    }
    setPendingNewThread(true);
    setPendingWorkspaceId(workspaceId);
    setWorkspacePickerOpen(false);
    setSelectedThreadId(null);
    replaceThreadIdInUrl(NEW_THREAD_SENTINEL);
  }

  function resolveThread(threadId: string | null) {
    if (!threadId) return;
    setPendingNewThread(false);
    setPendingWorkspaceId(null);
    setWorkspacePickerOpen(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = threadId; // prevents the open-effect from re-opening it
  }

  return {
    selectedThreadId,
    pendingNewThread,
    pendingWorkspaceId,
    workspacePickerOpen,
    setWorkspacePickerOpen,
    selectedThread,
    activeThreadId,
    selectThread,
    newThread,
    selectWorkspace,
    resolveThread,
  };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/lib/useThreadSelection.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Pin the session-url `"new"` passthrough**

Create `src/newbro/ui/src/lib/session-url.test.ts` (or append if it exists):
```ts
import { describe, it, expect, beforeEach } from "vitest";
import { readThreadIdFromUrl, replaceThreadIdInUrl } from "./session-url";

describe("session-url thread param", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));

  it("passes the 'new' sentinel through unchanged", () => {
    window.history.replaceState({}, "", "/?thread=new");
    expect(readThreadIdFromUrl()).toBe("new");
  });
  it("round-trips an id and clears on null", () => {
    replaceThreadIdInUrl("t-123");
    expect(readThreadIdFromUrl()).toBe("t-123");
    replaceThreadIdInUrl(null);
    expect(readThreadIdFromUrl()).toBeNull();
  });
});
```

Run: `npx vitest run src/lib/session-url.test.ts`
Expected: PASS. (No change to `session-url.ts` needed; this documents the contract the hook relies on.)

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/lib/useThreadSelection.ts src/newbro/ui/src/lib/useThreadSelection.test.tsx src/newbro/ui/src/lib/session-url.test.ts
git commit -m "feat(ui): useThreadSelection hook with durable new-thread URL intent"
```

---

### Task 2: Wire the hook into the DESKTOP Bro Detail component

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (the desktop component containing the block at `~3234–3371`)

- [ ] **Step 1: Read the desktop component and identify the block**

Open `src/newbro/ui/src/ArtboardShell.tsx`. Find the desktop Bro Detail component whose body starts with
`const [selectedThreadId, setSelectedThreadId] = useState<string | null>(() => readThreadIdFromUrl());` (around line 3234) and includes `recentResolveRef`, `isResolveLag`, the auto-select effect, `selectThread`/`newThread`/`selectWorkspace`/`resolveThread`, the open-thread effect, the `activeThreadRef` sync effect, and the unmount-close effect (down to ~3371). Note the lines that compute `bro`, `nodeState`, `needsConnect`, `persona`, `threads`, `workspaceOptions` just above/within it — those stay.

- [ ] **Step 2: Add the import**

At the top of `ArtboardShell.tsx`, with the other local imports, add:
```ts
import { useThreadSelection } from "./lib/useThreadSelection";
```
(`readThreadIdFromUrl`/`replaceThreadIdInUrl` may become unused in this file after this task and Task 3 — remove them from the existing `./lib/session-url` import only once BOTH components are migrated, in Task 3.)

- [ ] **Step 3: Replace the selection slice with the hook**

Ensure `bro`, `nodeState`, `needsConnect`, `persona`, `threads`, and `workspaceOptions` are still computed (keep them). Then REPLACE this exact set of declarations/derivations/effects/functions:
- the `useState` for `selectedThreadId`, `pendingNewThread`, `pendingWorkspaceId`, `workspacePickerOpen`
- the refs `openedThreadRef`, `activeThreadRef`, `recentResolveRef`
- `matchedThread`, `isResolveLag`, `selectedThread`, `activeThreadId`
- the auto-select `useEffect` (`if (pendingNewThread || threads.length === 0) return; … setSelectedThreadId(threads[0].threadId); …`)
- the functions `selectThread`, `newThread`, `selectWorkspace`, `resolveThread`
- the open-thread `useEffect` (`… void shell.openRuntimeBroThread(bro.id, activeThreadId);`)
- the `activeThreadRef.current = activeThreadId` `useEffect`
- the unmount-close `useEffect` (`return () => { … shell.closeRuntimeBroThread(bro.id, activeThreadRef.current); }`)

…with this single call (place it right after `workspaceOptions` is computed):
```ts
  const {
    selectedThreadId,
    pendingNewThread,
    pendingWorkspaceId,
    workspacePickerOpen,
    setWorkspacePickerOpen,
    selectedThread,
    activeThreadId,
    selectThread,
    newThread,
    selectWorkspace,
    resolveThread,
  } = useThreadSelection({
    broId: bro?.id ?? null,
    broSource: bro?.source ?? null,
    threads,
    workspaceOptions,
    needsConnect,
    openThread: (id, tid) => { void shell.openRuntimeBroThread(id, tid); },
    closeThread: (id, tid) => { void shell.closeRuntimeBroThread(id, tid); },
    onNoWorkspace: () => shell.setShellError("No Codex workspace is available for this Bro yet."),
  });
```

KEEP everything else in the component unchanged: `threadVisibleCount` (+ its two effects), `threadScrollRef`/`threadScrollVersion` and the scroll effect, `visibleThreads`, `directThreadIntent`, `visibleTextTurns`/`visibleAudioTurns`/`visibleTimelineTurns`, the voice/audio effects, and all JSX (which already consumes `selectedThread`, `activeThreadId`, `selectThread`, `newThread`, `selectWorkspace`, `resolveThread`/`onThreadResolved`, `pendingNewThread`, `workspacePickerOpen`, `pendingWorkspaceId`). These names are unchanged, so the JSX needs no edits.

- [ ] **Step 4: Typecheck + tests**

Run: `npx tsc --noEmit` then `npm test`
Expected: no type errors; all tests pass. If `tsc` flags an unused `recentResolveRef`/`isResolveLag` or a missing reference, you missed deleting or kept a stray use — re-check Step 3. (Leave the `session-url` import for Task 3.)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "refactor(ui): desktop Bro Detail uses useThreadSelection; drop isResolveLag/recentResolveRef"
```

---

### Task 3: Wire the hook into the MOBILE Bro Detail component + cleanup

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (the mobile component containing the block at `~3951–4078`)

- [ ] **Step 1: Replace the mobile selection slice with the hook**

Find the mobile Bro Detail component (its block starts with the same `const [selectedThreadId, setSelectedThreadId] = useState<string | null>(() => readThreadIdFromUrl());` around line 3951, with `drawerThreadVisibleCount`/`visibleDrawerThreads`/`headerThreadTitle` nearby). Apply the SAME replacement as Task 2 Step 3: delete the selection `useState`s, the `openedThreadRef`/`activeThreadRef`/`recentResolveRef` refs, `matchedThread`/`isResolveLag`/`selectedThread`/`activeThreadId`, the auto-select effect, `selectThread`/`newThread`/`selectWorkspace`/`resolveThread`, the open-thread effect, the `activeThreadRef` sync effect, and the unmount-close effect; replace with the identical `useThreadSelection({...})` call (same arguments). KEEP `drawerThreadVisibleCount` (+ its effects), `visibleDrawerThreads`, `hiddenDrawerThreadCount`, `headerThreadTitle`, `directThreadIntent`, the visible-turn filters, and all JSX.

- [ ] **Step 2: Remove now-unused imports**

Now that neither component uses `readThreadIdFromUrl`/`replaceThreadIdInUrl` directly, update the import at the top of `ArtboardShell.tsx`:
```ts
// before: import { readThreadIdFromUrl, replaceThreadIdInUrl } from "./lib/session-url";
// remove that line entirely (the hook owns those calls now), UNLESS a grep shows another use:
```
Run `grep -nE "readThreadIdFromUrl|replaceThreadIdInUrl" src/newbro/ui/src/ArtboardShell.tsx` first; only remove the import if there are zero remaining uses.

- [ ] **Step 3: Verify no stray references**

Run:
```bash
grep -nE "isResolveLag|recentResolveRef" src/newbro/ui/src/ArtboardShell.tsx || echo "clean: both removed"
```
Expected: `clean: both removed`.

- [ ] **Step 4: Full verify**

Run (from `src/newbro/ui`): `npx tsc --noEmit` then `npm test`
Expected: no type errors; full suite passes (including existing `__tests__/App.test.tsx`). If an App test asserted old selection behavior that changed, confirm the change matches the spec (e.g. a selected-but-loading thread no longer falls back to threads[0]); update the assertion only if it encoded the old buggy fallback, not to hide a real regression.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "refactor(ui): mobile Bro Detail uses useThreadSelection; remove dead url-helper import"
```

---

### Task 4: Manual verification

- [ ] **Step 1: Exercise the new-thread flow (performed by the user)**

Run the app. In Bro Detail: start a new thread (pick workspace) → confirm the URL shows `?thread=new` and the composer stays on the new thread. Send the first message → confirm it does NOT jump to a random existing thread; it stays/loads the newly created thread and the URL becomes `?thread=<newId>`. Reload while on `?thread=new` → confirm it restores new-thread compose (empty). Select an existing thread → URL `?thread=<id>`; reload → same thread. Repeat on a mobile viewport (or `/mobile`).

- [ ] **Step 2: Note results** (no commit). If it still jumps, capture whether the backend returned a wrong `target_thread_id` (the separately-tracked reconciliation race) vs. the frontend re-deriving selection — the URL param should make the latter impossible.

---

## Self-Review

**Spec coverage:**
- Three-state `thread` URL (`id`/`new`/absent) → Task 1 (hook init + `selectWorkspace` writes `new`; `session-url` passthrough test).
- `pendingNewThread` derived from URL → Task 1 (init from sentinel).
- Auto-select only on no-intent → Task 1 (effect guarded by `selectedThreadId !== null`).
- Drop `?? threads[0]` derivation fallback → Task 1 (`selectedThread = matchedThread`).
- Remove `isResolveLag` + `recentResolveRef` → Tasks 2–3 (deleted; `activeThreadId = selectedThreadId` keeps optimistic turns; `openedThreadRef` covers the re-open guard).
- De-dup desktop/mobile into one hook → Tasks 2–3.
- Tests (session-url, hook incl. headline new-thread regression) → Task 1.
- Out-of-scope (backend target_thread_id; client_request_id reload) → not implemented; Task 4 Step 2 distinguishes them.

**Placeholder scan:** none — hook + tests are complete code; wiring steps give exact delete/replace lists and the exact hook call.

**Type consistency:** `useThreadSelection<T extends { threadId: string }>(params)` and its returned names (`selectedThreadId`, `pendingNewThread`, `pendingWorkspaceId`, `workspacePickerOpen`, `setWorkspacePickerOpen`, `selectedThread`, `activeThreadId`, `selectThread`, `newThread`, `selectWorkspace`, `resolveThread`) match the call sites in Tasks 2–3 and the existing JSX consumers. `openThread`/`closeThread`/`onNoWorkspace` params match the `shell.openRuntimeBroThread`/`closeRuntimeBroThread`/`setShellError` wrappers.

**Risk note:** Tasks 2–3 are in-place surgery on a large file. The mitigations: the hook (Task 1) is proven by tests before wiring; the returned names exactly match existing locals so JSX is untouched; `tsc --noEmit` + the full suite gate each wiring; and `grep` confirms the dead guards are gone.
