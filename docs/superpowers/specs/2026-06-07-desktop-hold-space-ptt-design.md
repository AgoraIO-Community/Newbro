# Desktop hold-Space push-to-talk

Date: 2026-06-07
Status: Approved design

## Problem

The desktop UI hints tell users to "hold Space to talk", but space-to-record is not
wired up globally. Today desktop recording works only via **press-and-hold the mic
button** (pointer) — release sends. Space/Enter record only while that mic button is
*focused*; there is no global hold-Space listener (the only global keydown handlers
handle `Escape`, `ArtboardShell.tsx:150` and `:1389`). The hints therefore overpromise.

We will make the hint true for the in-thread composer: a global **hold-Space**
push-to-talk that records on key-down and sends on key-up while a bro thread is open.

## Scope

In scope:
- Global hold-Space PTT inside an open bro thread (`DesktopComposerBar`), recording to the
  currently selected bro/thread and sending on release.
- Reword the Home-screen hints that promise "hold space anywhere" (no thread/bro context
  there) so copy matches reality.
- Remove dead code directly tied to the abandoned "push to talk anywhere" model.

Out of scope (explicitly deferred):
- Global "hold space anywhere on Home to talk to any bro" — needs target-bro selection
  and a global voice session; much larger.
- Mobile push-to-talk changes (mobile already uses "hold the mic to talk").
- The separate `VoicePad` visual demo component (left as-is).

## Approach

Add a `window` keydown/keyup/blur listener inside `DesktopComposerBar`
(`ArtboardShell.tsx:3018`), reusing its existing `startRec` / `stopRec` / `cancelRec`
and the `usePushToTalkAudio` recorder. The composer already owns the relevant context
(selected bro/thread, `voiceMode`, mic-enabled state, draft focus), so the listener
lives there rather than in the recorder hook.

Rejected alternatives:
- Extend `usePushToTalkAudio` with a space hotkey — the hook lacks composer context
  (`voiceMode`, "is a text field focused"); would require passing it in.
- New `useHoldKeyToTalk` hook — most isolated but adds a file for a single use-site (YAGNI).

## Behavior

State: a `spaceHeldRef` (`useRef<boolean>`) tracks an active space-initiated recording.
The listener reads current values via refs to avoid stale closures / constant
re-subscription.

**keydown, `event.code === "Space"`** — start recording only if ALL hold:
- not `event.repeat` (ignore auto-repeat while held),
- focus is NOT in an editable element — `input`, `textarea`, `select`, or
  `[contenteditable]` (so typing a space still types a space),
- `voiceMode === "ptt"` (hands-free mode does not use PTT),
- mic enabled (not `micDisabled`),
- `recorder.phase === "idle"`.

Then `event.preventDefault()` (stop page scroll), `startRec()`, set `spaceHeldRef = true`.

**keyup, `event.code === "Space"`** — if `spaceHeldRef` is true: `event.preventDefault()`,
`stopRec()` (stop + send), clear `spaceHeldRef`.

**window `blur`** — if `spaceHeldRef` is true (alt-tab mid-hold; keyup never arrives):
`cancelRec()` (discard the partial take) and clear `spaceHeldRef`. (`Escape` already
cancels via the existing hook listener.)

The existing mic-button `onKeyDown`/`onKeyUp` handlers (`ArtboardShell.tsx:3307`) are
**kept**. Existing guards make any overlap a safe no-op: `recorder.start()` returns early
if a recording is active, `stopAndSend()` returns early if none is; `spaceHeldRef` is set
only on the global path, so a focused-button recording is not double-sent.

## Copy changes (`ArtboardShell.tsx`)

- `:3242` composer — "Hold `Space` to talk, or type your message" — **keep** (now true).
- `:2582` thread-empty — "Type below or hold Space to talk." — **keep** (now true inside a
  thread).
- `:1978` Home sub — drop the "anywhere" claim →
  "Open a bro to talk or read their thread. Sessions persist as long as the node stays
  online."
- `:2002` standing-by sub — "Quiet for now - hold space to wake one" →
  "Quiet for now — open one to start talking".

## Dead-code cleanup

- Remove `DesktopVoiceDock` (`ArtboardShell.tsx:3423`) — unused (definition only; no call
  site), the abandoned "push to talk anywhere" dock.
- Leave `VoicePad` (`components/newbro/visual.tsx:28`) in place.

## Testing

Unit (vitest + jsdom; `MediaRecorder`/`getUserMedia` already mocked by existing audio
tests):
- Open a thread, then `fireEvent.keyDown(window, { code: "Space" })` →
  `fireEvent.keyUp(window, { code: "Space" })` asserts `submitExecutorAudioInstruction`
  was called for the selected bro/thread.
- Space while the composer text input is focused does NOT start a recording (no
  `submitExecutorAudioInstruction` call).
- A `keyDown` with `repeat: true` does not start a second recording.

Existing tests that fire space on the focused mic button
(`__tests__/App.test.tsx:2158`, `:3582`) remain green (button handlers kept).

Manual: hold Space inside a thread records and release sends; typing a space in the
composer types a space; alt-tab mid-hold cancels the take.
