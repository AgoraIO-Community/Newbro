# New-Thread URL Intent (stop jumping to a random thread) — Design

Status: design (approved for planning)
Date: 2026-06-02

## Summary

Sending the first message in a **new** thread sometimes snaps Bro Detail to a
**random existing thread**. Root cause: the "I'm composing a new thread" intent
lives only in an in-memory `pendingNewThread` flag, and the `thread` URL param is
either an id or **absent** — so "pending new thread" is indistinguishable from
"fresh load, no selection." During the brief window between resolving to the
newly created thread and that thread appearing in the snapshot, an auto-select
fallback (`setSelectedThreadId(threads[0])`) fires and jumps to the latest thread.

Fix: make the `thread` URL param the **single source of truth for selection
intent** with three explicit states (`<id>` | `new` | absent), derive
`pendingNewThread` from it, and narrow the `threads[0]` fallback to fire **only**
when there is genuinely no intent. This removes the race-papering band-aids
(`isResolveLag`, `recentResolveRef`) entirely. The duplicated desktop/mobile
selection logic is consolidated into one tested `useThreadSelection` hook.

Frontend-only. No backend/protocol changes. (A separately-tracked backend
reconciliation race can return a wrong `target_thread_id`; that is out of scope —
this fixes the frontend auto-select jump.)

## Goal / Success Criterion

- After starting a new thread and sending the first message, Bro Detail stays on
  the new thread until it resolves to the real thread — it never jumps to an
  existing/random thread.
- The new-thread intent survives re-renders and reloads (durable in the URL).

## Non-Goals

- The backend turn/thread mis-attribution race (a wrong `target_thread_id` from
  the server) — tracked separately.
- Encoding the in-flight `client_request_id` in the URL to re-bind a new thread
  across a mid-send reload — a possible future enhancement, not in this V1.
- Any change to how threads are created or opened server-side.

## Context (current behavior)

`src/newbro/ui/src/ArtboardShell.tsx` has the thread-selection logic duplicated
in two near-identical blocks: desktop (`~3234–3368`) and mobile (`~3951–4077`).
Each has:
- `selectedThreadId` (`useState`, initialized from `readThreadIdFromUrl()`),
  `pendingNewThread` (`useState`), and refs `recentResolveRef`, `openedThreadRef`,
  `activeThreadRef`.
- `isResolveLag` (`:3256–3260`) — true while a just-resolved id isn't in `threads`
  yet; forces `selectedThread`/`activeThreadId` to a loading state.
- `selectedThread = pendingNewThread || isResolveLag ? null : matchedThread ?? threads[0]`
  (`:3261–3263`) — note the `?? threads[0]` fallback.
- Auto-select effect (`:3287–3301`) — when not `pendingNewThread`, threads exist,
  and `selectedThreadId` isn't in `threads` (and isn't `recentResolveRef`),
  `setSelectedThreadId(threads[0])` + `replaceThreadIdInUrl(threads[0])`.
- `selectWorkspace` (`:3331–3340`) sets `pendingNewThread=true`,
  `selectedThreadId=null`, `replaceThreadIdInUrl(null)` (removes the param).
- `resolveThread` (`:3342–3351`) sets `recentResolveRef=id`, `pendingNewThread=false`,
  `selectedThreadId=id`, `replaceThreadIdInUrl(id)`, `openedThreadRef=id`.
- Sends call `onThreadResolved(response.target_thread_id)` → `resolveThread(...)`.

URL helpers: `src/newbro/ui/src/lib/session-url.ts` —
`readThreadIdFromUrl()` reads `?thread`, `replaceThreadIdInUrl(id|null)` sets or
deletes it (via `history.replaceState`).

## Design

### 1. Three-state `thread` URL param (the single source of intent)

`thread` encodes:
- `thread=<id>` → that thread is selected.
- `thread=new` → pending new thread (compose mode).
- absent → no intent → default to the latest thread.

`session-url.ts` stays generic: `readThreadIdFromUrl()` returns the raw value
(including the literal `"new"`); the hook interprets `"new"` as the new-thread
sentinel. Thread ids are UUID-shaped, so they never collide with `"new"`.

### 2. `useThreadSelection` hook (one tested unit, replaces both copies)

Create `src/newbro/ui/src/lib/useThreadSelection.ts`:

```ts
export interface ThreadSelection {
  selectedThreadId: string | null;   // real id, or null while in new/no-intent
  pendingNewThread: boolean;         // derived: urlThread === "new"
  selectedThread: BroThreadRecord | null;  // matched thread, else null (no threads[0] fallback)
  activeThreadId: string | null;
  selectThread: (threadId: string) => void;
  newThread: () => void;             // existing workspace-picker entry
  selectWorkspace: (workspaceId: string) => void;  // → enters new-thread mode
  resolveThread: (threadId: string | null) => void;
  // …pendingWorkspaceId, workspacePickerOpen, etc. as today
}

export function useThreadSelection(args: {
  bro: BroCardModel | null;
  threads: BroThreadRecord[];
  // shell actions: openRuntimeBroThread, closeRuntimeBroThread, setShellError
  …
}): ThreadSelection;
```

Behavior changes vs. the current copies:
- **`pendingNewThread` is derived from the URL** (`urlThread === "new"`), seeded
  from `readThreadIdFromUrl()` and updated by `selectWorkspace`
  (`replaceThreadIdInUrl("new")`) / `selectThread` / `resolveThread`.
- **`selectedThread = matchedThread ?? null`** — drop the `?? threads[0]`
  fallback. A selected-but-not-yet-loaded id shows a loading state, not the latest
  thread.
- **Auto-select fires only on genuine no-intent**: when `urlThread` is absent (and
  not new-thread mode) and threads exist → `setSelectedThreadId(threads[0])` +
  write the URL. It does **not** fire when `urlThread === "new"`, nor when a
  specific id is selected but merely not loaded yet.
- **Remove `isResolveLag`** — no longer needed; the loading state falls out of
  `matchedThread ?? null` naturally.
- **Remove `recentResolveRef`** — its auto-select suppression is obsolete; its
  "don't re-open a just-resolved thread" role is covered by `openedThreadRef`
  (which `resolveThread` already sets to the same id). The open-thread effect
  keeps its `openedThreadRef` guard.

Both desktop and mobile Bro Detail components call `useThreadSelection`,
deleting the two duplicated blocks.

### 3. Data flow (new-thread send)

1. `newThread()` → workspace picker → `selectWorkspace(ws)` → URL `thread=new`,
   `pendingNewThread=true`, `selectedThreadId=null`.
2. Send first message (`create_new_thread=true`). Auto-select stays off the whole
   time because `urlThread === "new"`.
3. Response → `onThreadResolved(target_thread_id)` → `resolveThread(id)` → URL
   `thread=<id>`, `pendingNewThread=false`, `selectedThreadId=id`. While `id`
   isn't in `threads` yet → `selectedThread === null` (loading), **not**
   `threads[0]`.
4. Snapshot arrives with the new thread → `matchedThread` resolves → shown.

## Edge Cases

- Reload while `thread=new` → new-thread compose mode is restored (empty); the
  optimistic in-flight turn is client-only and not restored (acceptable; the
  client_request_id re-bind is an explicit Non-Goal).
- `thread=<id>` for a deleted/invalid thread → `selectedThread` is `null`
  (loading/empty) rather than snapping to the latest. If desired, a follow-up can
  add an explicit "thread not found → fall back" after a load failure; not in V1
  (the current code also doesn't distinguish deleted from loading).
- A literal thread id `"new"` cannot occur (ids are UUID-shaped).

## Testing

Vitest + `@testing-library/react` (`cd src/newbro/ui && npm test`).

- **`session-url`** (unit) — `readThreadIdFromUrl()` → `"new"` for `?thread=new`,
  `<id>` for `?thread=<id>`, `null` when absent; `replaceThreadIdInUrl`
  round-trips `"new"` / `<id>` / `null` (delete).
- **`useThreadSelection`** (`renderHook`) —
  - `?thread=new` → `pendingNewThread` true; with threads present, the auto-select
    does **not** run and `selectedThreadId` stays null (headline regression test).
  - `resolveThread(newId)` → `selectedThreadId === newId`; with `newId` absent from
    `threads` → `selectedThread === null`; after `newId` is added to `threads` →
    `selectedThread` is it (never `threads[0]`).
  - no `thread` param + threads present → auto-selects `threads[0]` and writes the
    URL.
  - `selectThread(existingId)` → selects it, URL updated, leaves new-thread mode.
- Existing `ArtboardShell` / `App.test.tsx` tests stay green after both copies are
  replaced by the hook.

## Files

- Create: `src/newbro/ui/src/lib/useThreadSelection.ts` (+ test
  `useThreadSelection.test.tsx`).
- Modify: `src/newbro/ui/src/lib/session-url.ts` — recognize/round-trip the `"new"`
  sentinel (and tests in `session-url.test.ts` if present, else add).
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` — replace both duplicated
  selection blocks (desktop `~3234–3368`, mobile `~3951–4077`) with the hook;
  delete `isResolveLag` and `recentResolveRef`.
