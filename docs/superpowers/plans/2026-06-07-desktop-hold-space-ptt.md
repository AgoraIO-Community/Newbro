# Desktop Hold-Space Push-to-Talk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global hold-Space push-to-talk to the desktop in-thread composer (record on key-down, send on key-up), make the desktop hints honest, and remove the dead "push to talk anywhere" dock.

**Architecture:** A `window` keydown/keyup/blur listener added inside `DesktopComposerBar` (`src/newbro/ui/src/ArtboardShell.tsx`) reuses the component's existing `startRec`/`stopRec`/`cancelRec` and `usePushToTalkAudio` recorder. The listener reads current state through refs (so it attaches once and never uses stale closures), and only fires when a thread is open, mic is enabled, voice mode is push-to-talk, the recorder is idle, and focus is not in a text field.

**Tech Stack:** React + Vite + TypeScript. Tests: vitest + @testing-library/react in jsdom (`MediaRecorder`/`AudioContext` are stubbed in the existing audio tests). Build/typecheck: `npm run build` (vite build + `tsc --noEmit`). Run from `src/newbro/ui`.

**Reference spec:** `docs/superpowers/specs/2026-06-07-desktop-hold-space-ptt-design.md`

---

### Task 1: Global hold-Space push-to-talk in the desktop composer

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (inside `DesktopComposerBar`, after `cancelRec` at ~line 3123)
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

The three tests mirror the existing passing audio test (`App.test.tsx` ~line 2138–2176), which sets up a connected Forge bro, creates a new thread + workspace so the mic is enabled, and asserts `clientMock.submitExecutorAudioInstruction`. We reuse that exact setup and drive recording from `window` Space events instead of pointer events.

- [ ] **Step 1: Write the failing tests**

Add these three tests inside the same `describe` block that contains the existing "records and sends desktop audio" test in `src/newbro/ui/src/__tests__/App.test.tsx` (place them right after that test). They reuse the same module-level helpers already used there: `clientMock`, `getRouter`, `selectWorkWorkspaceAndConfirm`, and the `MockMediaRecorder`/`MockAudioContext` stubs installed in the existing test's body. Each test installs the same stubs locally to stay self-contained:

```tsx
  it("records and sends desktop audio via hold-Space", async () => {
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    vi.stubGlobal("AudioContext", MockAudioContext);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=exec-1");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Existing thread response.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New thread with Forge" }));
    selectWorkWorkspaceAndConfirm();
    expect(await screen.findByText("No messages with Forge yet")).toBeInTheDocument();

    fireEvent.keyDown(window, { code: "Space" });
    await waitFor(() => expect(screen.getByTestId("voice-session-start")).toHaveClass("dt-cmp-mic-free"));
    fireEvent.keyUp(window, { code: "Space" });

    await waitFor(() => {
      expect(clientMock.submitExecutorAudioInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: null,
        createNewThread: true,
        workspaceId: "/tmp/work",
        pcm16: expect.any(Blob),
        durationMs: 1,
        sampleRate: 16000,
        numChannels: 1,
        samplesPerChannel: 16,
        clientRequestId: expect.stringMatching(/^audio-/),
      });
    });
  });

  it("does not record when Space is pressed inside the composer input", async () => {
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    vi.stubGlobal("AudioContext", MockAudioContext);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=exec-1");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Existing thread response.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New thread with Forge" }));
    selectWorkWorkspaceAndConfirm();
    expect(await screen.findByText("No messages with Forge yet")).toBeInTheDocument();

    const input = screen.getByLabelText("Message");
    input.focus();
    fireEvent.keyDown(input, { code: "Space" });

    expect(screen.getByTestId("voice-session-start")).not.toHaveClass("dt-cmp-mic-free");
    expect(clientMock.submitExecutorAudioInstruction).not.toHaveBeenCalled();
  });

  it("ignores auto-repeat so hold-Space records once", async () => {
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    vi.stubGlobal("AudioContext", MockAudioContext);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=exec-1");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Existing thread response.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New thread with Forge" }));
    selectWorkWorkspaceAndConfirm();
    expect(await screen.findByText("No messages with Forge yet")).toBeInTheDocument();

    fireEvent.keyDown(window, { code: "Space" });
    await waitFor(() => expect(screen.getByTestId("voice-session-start")).toHaveClass("dt-cmp-mic-free"));
    fireEvent.keyDown(window, { code: "Space", repeat: true });
    fireEvent.keyUp(window, { code: "Space" });

    await waitFor(() => expect(clientMock.submitExecutorAudioInstruction).toHaveBeenCalledTimes(1));
  });
```

Note: if `MockMediaRecorder` / `MockAudioContext` are declared inside the existing test's function body rather than at module scope, lift those two class declarations to the `describe` scope (above the tests) so all tests can reference them. Do not change their behavior.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd src/newbro/ui && npm run test -- App.test.tsx -t "hold-Space"`
Expected: FAIL — `submitExecutorAudioInstruction` is not called (no global Space listener yet).

- [ ] **Step 3: Implement the global listener**

In `src/newbro/ui/src/ArtboardShell.tsx`, inside `DesktopComposerBar`, immediately after the `cancelRec` function definition (the block ending at ~line 3123), insert:

```tsx
  // Hold-Space push-to-talk: record while Space is held (when not typing), send on
  // release. Latest handlers/state live in refs so the window listener attaches once
  // and never runs against stale closures.
  const spaceHeldRef = useRef(false);
  const micDisabledRef = useRef(micDisabled);
  const voiceModeRef = useRef(voiceMode);
  const phaseRef = useRef(recorder.phase);
  const startRecRef = useRef(startRec);
  const stopRecRef = useRef(stopRec);
  const cancelRecRef = useRef(cancelRec);
  useEffect(() => {
    micDisabledRef.current = micDisabled;
    voiceModeRef.current = voiceMode;
    phaseRef.current = recorder.phase;
    startRecRef.current = startRec;
    stopRecRef.current = stopRec;
    cancelRecRef.current = cancelRec;
  });
  useEffect(() => {
    function isEditableTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      const tag = target.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.code !== "Space" || event.repeat) return;
      if (isEditableTarget(event.target)) return;
      if (voiceModeRef.current !== "ptt" || micDisabledRef.current) return;
      if (phaseRef.current !== "idle") return;
      event.preventDefault();
      spaceHeldRef.current = true;
      startRecRef.current();
    }
    function onKeyUp(event: KeyboardEvent) {
      if (event.code !== "Space" || !spaceHeldRef.current) return;
      event.preventDefault();
      spaceHeldRef.current = false;
      stopRecRef.current();
    }
    function onBlur() {
      if (!spaceHeldRef.current) return;
      spaceHeldRef.current = false;
      cancelRecRef.current();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, []);
```

`useRef`/`useEffect` are already imported in this file. `startRec` accepts an optional pointer event, so calling `startRecRef.current()` with no argument is valid.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd src/newbro/ui && npm run test -- App.test.tsx -t "hold-Space"`
Expected: PASS (all three).

Also run the focus + repeat tests by name to be sure:
Run: `cd src/newbro/ui && npm run test -- App.test.tsx -t "composer input"` and `... -t "auto-repeat"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): hold-Space push-to-talk in desktop thread composer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Make the Home hints honest

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (~line 1978 and ~line 2002)

The composer (`:3242`) and thread-empty (`:2582`) hints are now true and stay as-is. Only the Home-screen hints that promise "hold space anywhere" (no thread/bro context there) change.

- [ ] **Step 1: Reword the Home page subtitle**

Find:

```tsx
                  <p className="dt-page-sub">Hold space anywhere, talk to any bro, or open one to read their thread. Sessions persist as long as the node stays online.</p>
```

Replace with:

```tsx
                  <p className="dt-page-sub">Open a bro to talk or read their thread. Sessions persist as long as the node stays online.</p>
```

- [ ] **Step 2: Reword the standing-by subtitle**

Find:

```tsx
                    <span className="dt-home-section-sub">Quiet for now - hold space to wake one</span>
```

Replace with:

```tsx
                    <span className="dt-home-section-sub">Quiet for now — open one to start talking</span>
```

- [ ] **Step 3: Verify the suite still passes**

Run: `cd src/newbro/ui && npm run test`
Expected: PASS (no test asserts the old strings).

- [ ] **Step 4: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "fix(ui): reword desktop Home hints to match real space behavior

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Remove the dead DesktopVoiceDock

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (delete the `DesktopVoiceDock` function, lines ~3423–3449)

`DesktopVoiceDock` is defined but never rendered (no call site) and carries the abandoned "push to talk anywhere" copy. The `Mic` icon import it uses stays needed (also used at ~line 3006), so no import change.

- [ ] **Step 1: Delete the function**

Remove the entire `DesktopVoiceDock` function — from the line `function DesktopVoiceDock({` through its closing `}` (the block shown below) plus the trailing blank line, leaving `function DesktopDetail(` directly after the preceding function:

```tsx
function DesktopVoiceDock({
  phase,
  disabled,
  onToggle,
}: {
  phase: ReturnType<typeof useNewbroShell>["voiceSession"]["phase"];
  disabled: boolean;
  onToggle: () => void;
}) {
  const connected = phase === "connected";
  return (
    <div className="nb-talk-dock">
      <div className="nb-talk-hint"><span className="nb-talk-key">space</span><span>{connected ? "voice channel open" : "push to talk anywhere"}</span></div>
      <button
        type="button"
        className={`nb-talk-btn${connected ? " nb-talk-btn-listening" : ""}`}
        data-testid={connected ? "voice-session-stop" : "voice-session-start"}
        aria-label={connected ? "Stop voice session" : "Start voice session"}
        disabled={disabled || phase === "loading"}
        onClick={onToggle}
      >
        <Mic size={18} aria-hidden="true" />
        <span>{connected ? "Stop voice" : "Start voice"}</span>
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verify build + tests**

Run: `cd src/newbro/ui && npm run build`
Expected: build + `tsc --noEmit` succeed (no "unused" or "undefined" errors).

Run: `cd src/newbro/ui && npm run test`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "chore(ui): remove unused DesktopVoiceDock

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Build + typecheck**

Run: `cd src/newbro/ui && npm run build`
Expected: succeeds.

- [ ] **Step 2: Full unit suite**

Run: `cd src/newbro/ui && npm run test`
Expected: PASS, including the existing focused-mic-button space tests at `App.test.tsx:2158` and `:3582` (button handlers were left intact).

- [ ] **Step 3: Manual check**

Run: `cd src/newbro/ui && npm run dev`, open a bro thread on desktop, then:
- Hold Space (focus not in the text box) → records; release → sends.
- Click into the message input and press Space → types a space, no recording.
- Hold Space, then alt-tab away before releasing → recording cancels (no send).

---

## Self-Review Notes

- **Spec coverage:** Task 1 → global hold-Space behavior + keydown/keyup/blur + editable/repeat/voiceMode/mic/idle guards + the three unit tests; Task 2 → Home copy changes (`:1978`, `:2002`), with `:3242`/`:2582` intentionally kept; Task 3 → remove `DesktopVoiceDock` (VoicePad left as spec states); Task 4 → build + full suite + manual. All spec sections covered.
- **Placeholder scan:** none — exact paths, full code, exact commands.
- **Type consistency:** ref names (`spaceHeldRef`, `micDisabledRef`, `voiceModeRef`, `phaseRef`, `startRecRef`, `stopRecRef`, `cancelRecRef`) and handlers (`startRec`/`stopRec`/`cancelRec`, `recorder.phase`, `micDisabled`, `voiceMode`) match the existing `DesktopComposerBar` definitions.
