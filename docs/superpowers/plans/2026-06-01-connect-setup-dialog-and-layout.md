# One Setup Dialog from Offline Surfaces + Dialog Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the offline/never-connected entry points (home bro card, detail header pill, offline banner) to the single `CreateConnectSheet` setup dialog, fix the banner's never-connected copy, and clean up the dialog's STEP 3 text layout.

**Architecture:** `CreateConnectSheet` is already a full-screen overlay that handles an existing `bro`; each container (home, detail) holds a small "open" state and renders it on demand. The terse surfaces get buttons that flip that state. The `OfflineBanner` becomes a thin status+button. CSS-level rhythm fixes in `variants-onboarding.css`.

**Tech Stack:** React + TypeScript (Vite), Vitest + Testing Library.

**Reference spec:** `docs/superpowers/specs/2026-06-01-connect-setup-dialog-and-layout-design.md`

All UI code is in `src/newbro/ui/src/ArtboardShell.tsx` unless noted. **Run tests from `src/newbro/ui`** as `npm test -- src/__tests__/App.test.tsx -t "<name>"` (the `test` script is already `vitest run`).

---

## File Structure

- **Modify** `src/newbro/ui/src/ArtboardShell.tsx` — `CreateConnectSheet` (adaptive title, layout), `OfflineBanner` (thin), `Header`/`DesktopFrame` (pill `onConnect`), `DesktopDetail`/`MobileDetail` (connect overlay), `DesktopBroCard`/`DesktopRosterRow`/`MobileBroCard`/`HomeBroCopyAction` (card connect action), `DesktopHome`/`MobileHome` (setup overlay).
- **Modify** `src/newbro/ui/src/styles/variants-onboarding.css` — STEP 3 rhythm + toggle treatment.
- **Modify** `src/newbro/ui/src/__tests__/App.test.tsx` — rewrite the offline test; add card/pill open-dialog tests.

---

### Task 1: `CreateConnectSheet` adaptive title

**Files:** Modify `src/newbro/ui/src/ArtboardShell.tsx`

- [ ] **Step 1: Adapt the dialog header for an existing bro**

In `CreateConnectSheet`, replace:

```jsx
              <h2 className="ob-sheet-h">Set up your first bro</h2>
              <p className="ob-sheet-intro">A bro works on a computer you keep on — your Mac, a spare laptop, anything. Three quick steps and it&rsquo;s ready.</p>
```

with:

```jsx
              <h2 className="ob-sheet-h">{bro ? (bro.nodeName ? `Reconnect ${bro.name}` : `Set up ${bro.name}`) : "Set up your first bro"}</h2>
              <p className="ob-sheet-intro">{bro ? (bro.nodeName ? `Get ${bro.name} back online — install the Newbro app on its Mac and paste the connect command.` : `Install the Newbro app on the Mac that runs ${bro.name}, then paste the connect command.`) : "A bro works on a Mac you keep on. Install the Newbro app, paste the connect command, and it’s ready."}</p>
```

- [ ] **Step 2: Build to verify it compiles**

Run (from `src/newbro/ui`): `npm run build` (or `npx tsc -p tsconfig.json --noEmit`)
Expected: no type errors. (`bro` is `BroCardModel | null`; `bro.nodeName`/`bro.name` exist on `BroCardModel`.)

- [ ] **Step 3: Run the onboarding test (new-bro path unaffected)**

Run: `npm test -- src/__tests__/App.test.tsx -t "before creating the first Bro"`
Expected: PASS (new-bro dialog still shows "Set up your first bro" because `bro` is null).

- [ ] **Step 4: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "feat(ui): adaptive CreateConnectSheet title for existing bro

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `CreateConnectSheet` STEP 3 layout cleanup

**Files:**
- Modify `src/newbro/ui/src/ArtboardShell.tsx`
- Modify `src/newbro/ui/src/styles/variants-onboarding.css`

- [ ] **Step 1: Remove the dead meta links**

In `CreateConnectSheet`'s STEP 3, delete this block entirely:

```jsx
                  <div className="ob-connect-meta">
                    <button type="button" className="ob-link ob-link-sm">Get a fresh link</button>
                    <span className="ob-connect-meta-sep">·</span>
                    <button type="button" className="ob-link ob-link-sm">Walk me through it</button>
                  </div>
```

- [ ] **Step 2: Restyle the terminal toggle as a muted disclosure**

Replace the toggle button:

```jsx
                  <button type="button" className="ob-link ob-link-sm ob-terminal-toggle" aria-expanded={showTerminal} onClick={() => setShowTerminal((v) => !v)}>
                    {showTerminal ? "Hide terminal option" : "Not on a Mac? Connect from a terminal"}
                  </button>
```

with:

```jsx
                  <button type="button" className={`ob-terminal-toggle${showTerminal ? " ob-terminal-toggle-open" : ""}`} aria-expanded={showTerminal} onClick={() => setShowTerminal((v) => !v)}>
                    <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>
                    {showTerminal ? "Hide terminal option" : "Not on a Mac? Connect from a terminal"}
                  </button>
```

- [ ] **Step 3: Normalize spacing — remove compounding margins**

In `src/newbro/ui/src/styles/variants-onboarding.css`, change `.ob-connect-guide-2`:

```css
.ob-connect-guide-2 { margin-top: 10px; }
```

to:

```css
.ob-connect-guide-2 { margin-top: 0; }
```

And replace our previously-added block:

```css
.ob-download {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  padding: 8px 14px;
  border-radius: 10px;
  background: var(--nb-info-grad-btn, #2563eb);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  margin: 2px 0 4px;
}
.ob-download:hover { filter: brightness(1.05); }

.ob-terminal-toggle { margin-top: 6px; }
.ob-terminal-fallback { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
```

with:

```css
.ob-download {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  padding: 8px 14px;
  border-radius: 10px;
  background: var(--nb-info-grad-btn, #2563eb);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  margin: 0;
}
.ob-download:hover { filter: brightness(1.05); }

/* Muted disclosure (matches the offline notice chevron), not a coral link. */
.ob-terminal-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start;
  background: transparent;
  border: 0;
  padding: 2px 0;
  margin: 0;
  font-family: inherit;
  font-size: 11px;
  font-weight: 500;
  color: var(--nb-ink-muted);
  cursor: pointer;
}
.ob-terminal-toggle:hover { color: var(--nb-ink-soft); }
.ob-terminal-toggle svg { transition: transform 0.15s ease; }
.ob-terminal-toggle-open svg { transform: rotate(90deg); }
.ob-terminal-fallback { display: flex; flex-direction: column; gap: 6px; }
```

Also change `.ob-connect-guide` margin so the fieldset `gap` is the only spacing:

```css
.ob-connect-guide {
  margin: 0 0 8px;
```

to:

```css
.ob-connect-guide {
  margin: 0;
```

- [ ] **Step 4: Visual verification**

The vertical spacing in STEP 3 should now be uniform (driven by the fieldset's `gap: 10px`), the "Not on a Mac?" control reads as a muted chevron disclosure, and the "Get a fresh link / Walk me through it" links are gone. Verify by running the UI and opening the create dialog (or have the reviewer confirm against the running app). Run:
```bash
npm test -- src/__tests__/App.test.tsx -t "before creating the first Bro"
```
Expected: PASS (the onboarding tests don't depend on the removed links or the toggle's class).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-onboarding.css
git commit -m "fix(ui): tidy CreateConnectSheet STEP 3 spacing and toggle

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Thin `OfflineBanner` + detail connect overlay

**Files:**
- Modify `src/newbro/ui/src/ArtboardShell.tsx`
- Modify `src/newbro/ui/src/styles/variants-onboarding.css`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Rewrite the offline test (failing first)**

In `App.test.tsx`, replace the body of the offline test (the one asserting `Workshop Mini is offline`, currently using `bro-node-copy-run-only-command`, `bro-node-copy-command`, and `/Reinstall from a terminal/i`). Replace from the `expect(await screen.findByTestId("bro-node-disconnected-warning"))…` line through the `expect(screen.getByPlaceholderText("Reconnect your computer before sending")).toBeDisabled();` line with:

```javascript
    const banner = await screen.findByTestId("bro-node-disconnected-warning");
    expect(banner).toHaveTextContent("Workshop Mini is offline");
    // The banner no longer holds the command; it opens the setup dialog.
    expect(screen.queryByTestId("bro-node-copy-run-only-command")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reconnect/i }));
    expect(await screen.findByText(/Reconnect Workshop Mini|Reconnect forge/i)).toBeInTheDocument();
    expect(screen.getByTestId("voice-session-start")).toBeDisabled();
    expect(screen.getByPlaceholderText("Reconnect your computer before sending")).toBeDisabled();
```

(The bro in that test is `forge` on node `Workshop Mini`; the dialog heading is "Reconnect {bro.name}". The regex accepts either name in case the fixture's bro/node naming differs — keep whichever matches when you run it.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- src/__tests__/App.test.tsx -t "offline"`
Expected: FAIL (banner still renders the old command line / no "Reconnect" button yet).

- [ ] **Step 3: Rewrite `OfflineBanner` to a thin status + button**

Replace the entire `OfflineBanner` function with:

```jsx
function OfflineBanner({
  bro,
  node,
  neverConnected = false,
  onConnect,
  mobile,
}: {
  bro: BroCardModel;
  node: ExecutorNodeRecord;
  neverConnected?: boolean;
  onConnect: () => void;
  mobile?: boolean;
}) {
  const title = neverConnected ? `${node.name} isn't connected yet` : `${node.name} is offline`;
  const body = neverConnected
    ? `Set it up in the Newbro app — ${bro.name} can take messages once it connects.`
    : `${bro.name} can't take new messages until this computer reconnects. Your draft is saved — the last turn retries on its own.`;
  const action = neverConnected ? "Set up" : "Reconnect";

  if (mobile) {
    return (
      <section data-testid="bro-node-disconnected-warning" className="ob-offline-banner dt-offline-banner nb-artboard-offline">
        <span className="ob-offline-banner-icon" aria-hidden="true">
          <WifiOff size={16} strokeWidth={2} />
        </span>
        <div className="ob-offline-banner-body">
          <strong>{title}</strong>
          <span>{body}</span>
          <button type="button" className="ob-offline-action" onClick={onConnect}>{action} with the app</button>
        </div>
      </section>
    );
  }

  return (
    <section data-testid="bro-node-disconnected-warning" className="dt-offline-notice nb-artboard-offline">
      <div className="dt-offline-notice-head">
        <span className="dt-offline-notice-icon" aria-hidden="true">
          <WifiOff size={17} strokeWidth={2} />
        </span>
        <div className="dt-offline-notice-copy">
          <strong>{title}</strong>
          <span>{body}</span>
        </div>
        {!neverConnected ? (
          <span className="dt-offline-notice-status" aria-hidden="true">
            <span className="dt-offline-notice-pip" />
            Auto-retrying
          </span>
        ) : null}
      </div>
      <div className="dt-offline-foot">
        <button type="button" className="ob-offline-action" onClick={onConnect}>{action} with the app</button>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Add the banner action style**

Append to `src/newbro/ui/src/styles/variants-onboarding.css`:

```css
.ob-offline-action {
  align-self: flex-start;
  margin-top: 8px;
  padding: 7px 14px;
  border: 0;
  border-radius: 9px;
  background: var(--nb-info-grad-btn, #2563eb);
  color: #fff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.ob-offline-action:hover { filter: brightness(1.05); }
```

- [ ] **Step 5: Add the connect overlay + wire the banner in `DesktopDetail`**

In `DesktopDetail`, add a state near the other `useState`s (e.g. after `const [workspacePickerOpen, …]`):

```jsx
  const [connectOpen, setConnectOpen] = useState(false);
```

Change the `OfflineBanner` render to pass `neverConnected` + `onConnect`:

```jsx
              <div className="dt-pane-banner">
                <OfflineBanner bro={bro} node={offline} sessionId={shell.activeShellSessionId} />
              </div>
```

to:

```jsx
              <div className="dt-pane-banner">
                <OfflineBanner bro={bro} node={offline} neverConnected={nodeState.kind === "never_connected"} onConnect={() => setConnectOpen(true)} />
              </div>
```

And render the overlay — add this just before the closing `</DesktopFrame>` of `DesktopDetail` (after the `WorkspacePickerDialog`):

```jsx
      {connectOpen && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setConnectOpen(false)} onCreated={shell.refreshShellSession} bro={bro} />
      ) : null}
```

- [ ] **Step 6: Wire the banner in `MobileDetail`**

Add `const [connectOpen, setConnectOpen] = useState(false);` near `MobileDetail`'s other state. Change:

```jsx
        {offline ? <OfflineBanner bro={bro} node={offline} sessionId={shell.activeShellSessionId} mobile /> : null}
```

to:

```jsx
        {offline ? <OfflineBanner bro={bro} node={offline} neverConnected={nodeState.kind === "never_connected"} onConnect={() => setConnectOpen(true)} mobile /> : null}
```

And render the overlay near the end of `MobileDetail`'s returned tree (e.g. just before the final closing tag of its `MobileStage`/root):

```jsx
      {connectOpen && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setConnectOpen(false)} onCreated={shell.refreshShellSession} bro={bro} mobile />
      ) : null}
```

- [ ] **Step 7: Remove now-dead code**

`OfflineCommandLine` and `useCopyNodeConnectCommand` may now be unused (check: `useCopyNodeConnectCommand` is still used by `HomeBroCopyAction` until Task 5, and `OfflineCommandLine` is only used by the old banner). If `OfflineCommandLine` has no remaining references, delete its function definition. Run `npm run build` to surface unused-symbol/type errors; remove whatever is now unreferenced (do NOT remove `useCopyNodeConnectCommand` yet — Task 5 handles `HomeBroCopyAction`).

- [ ] **Step 8: Run the offline test — verify PASS**

Run: `npm test -- src/__tests__/App.test.tsx -t "offline"`
Expected: PASS — banner shows the status + "Reconnect with the app"; clicking opens the dialog ("Reconnect {bro}").

- [ ] **Step 9: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-onboarding.css src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): thin offline banner opens the setup dialog

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Detail header pill opens the dialog

**Files:**
- Modify `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Thread `onConnect` through `DesktopFrame` → `Header`**

Add `onConnect?: () => void` to `DesktopFrame`'s props and pass it to `Header`. Change the `DesktopFrame` signature:

```jsx
function DesktopFrame({
  active,
  bro,
  children,
  onHome,
}: {
  active: RuntimePage;
  bro?: BroCardModel | null;
  children: React.ReactNode;
  onHome: () => void;
}) {
```

to add `onConnect`:

```jsx
function DesktopFrame({
  active,
  bro,
  children,
  onHome,
  onConnect,
}: {
  active: RuntimePage;
  bro?: BroCardModel | null;
  children: React.ReactNode;
  onHome: () => void;
  onConnect?: () => void;
}) {
```

and in its `<Header … />` add `onConnect={onConnect}`.

Add `onConnect?: () => void` to `Header`'s props type and destructure it.

- [ ] **Step 2: Make the paused pill a button**

In `Header`, replace:

```jsx
          <span className={`dt-header-pill ${detailPaused ? "dt-header-pill-paused" : "dt-header-pill-live"}`}>
            <span className="dt-header-pill-dot" />
            {detailPaused ? "paused · computer offline" : "live · listening"}
          </span>
```

with:

```jsx
          detailPaused && onConnect ? (
            <button type="button" className="dt-header-pill dt-header-pill-paused dt-header-pill-action" onClick={onConnect}>
              <span className="dt-header-pill-dot" />
              computer offline · set up
            </button>
          ) : (
            <span className={`dt-header-pill ${detailPaused ? "dt-header-pill-paused" : "dt-header-pill-live"}`}>
              <span className="dt-header-pill-dot" />
              {detailPaused ? "paused · computer offline" : "live · listening"}
            </span>
          )
```

(Wrap the existing `{bro ? ( … ) : null}` expression accordingly — the pill is inside that conditional; keep the structure, just swap the single `<span>` for the `detailPaused && onConnect ? <button> : <span>` expression.)

- [ ] **Step 3: Style the actionable pill**

Append to `src/newbro/ui/src/styles/variants-onboarding.css`:

```css
.dt-header-pill-action { border: 0; cursor: pointer; font: inherit; }
.dt-header-pill-action:hover { filter: brightness(1.06); }
```

- [ ] **Step 4: Pass `onConnect` from `DesktopDetail`**

In `DesktopDetail`, change the detail frame opening tag:

```jsx
    <DesktopFrame active="detail" bro={bro} onHome={onHome}>
```

to:

```jsx
    <DesktopFrame active="detail" bro={bro} onHome={onHome} onConnect={() => setConnectOpen(true)}>
```

- [ ] **Step 5: Add a header-pill test**

Add to `App.test.tsx` (near the offline test) a test that, with the same offline fixture, clicks the header pill and asserts the dialog opens:

```javascript
  it("opens the setup dialog from the detail header pill", async () => {
    // reuse the offline-bro setup from the existing offline test fixture:
    const offlineNode = forgeNode({ /* same offline node config as the offline test */ });
    clientMock.getSessionSnapshot.mockResolvedValueOnce(forgeSnapshot("session-existing", offlineNode));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");
    render(<RouterProvider router={getRouter()} />);
    fireEvent.click(await screen.findByRole("button", { name: /computer offline · set up/i }));
    expect(await screen.findByText(/Reconnect forge|Reconnect Workshop Mini/i)).toBeInTheDocument();
  });
```

(Mirror the exact fixture setup used by the existing offline test in this file — copy its `offlineNode`/snapshot construction so the bro is offline. If the helper names differ, match them.)

- [ ] **Step 6: Run the test + build**

Run: `npm test -- src/__tests__/App.test.tsx -t "header pill"` then `npm run build`
Expected: PASS; no type errors.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-onboarding.css src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): detail header pill opens the setup dialog

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Home card connect action opens the dialog

**Files:**
- Modify `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Repurpose `HomeBroCopyAction` → open the dialog**

Replace the `HomeBroCopyAction` function with a connect-action that calls `onSetup` instead of copying:

```jsx
function HomeBroConnectAction({ bro, variant, onSetup }: { bro: BroCardModel; variant: "card" | "row"; onSetup: (bro: BroCardModel) => void }) {
  if (bro.source !== "runtime") return null;
  if (bro.liveState !== "offline" && bro.liveState !== "unbound") return null;
  const label = bro.nodeName ? "Reconnect" : "Set up";
  const handle = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onSetup(bro);
  };
  return (
    <button
      type="button"
      data-testid={`home-bro-connect-${bro.id}`}
      data-home-card-action="connect"
      className={variant === "card" ? "dt-bro-card-copy" : "dt-roster-copy"}
      onClick={handle}
    >
      <Plus size={12} strokeWidth={2} />
      <span>{label}</span>
    </button>
  );
}
```

(`MouseEvent` and `Plus` are already imported in this file. The `data-home-card-action` attribute keeps `clickedInsideHomeCardAction` working — note it checks `[data-home-card-action]` presence, so the value can be "connect".)

- [ ] **Step 2: Thread `onSetup` through the card/row components**

Add `onSetup` to `DesktopBroCard` and `DesktopRosterRow` and pass it to the action. Change `DesktopBroCard` signature:

```jsx
function DesktopBroCard({ bro, onOpen, featured = false }: { bro: BroCardModel; onOpen: (id: string) => void; featured?: boolean }) {
```

to:

```jsx
function DesktopBroCard({ bro, onOpen, onSetup, featured = false }: { bro: BroCardModel; onOpen: (id: string) => void; onSetup: (bro: BroCardModel) => void; featured?: boolean }) {
```

and replace `<HomeBroCopyAction bro={bro} variant="card" />` with `<HomeBroConnectAction bro={bro} variant="card" onSetup={onSetup} />`.

Change `DesktopRosterRow` signature:

```jsx
function DesktopRosterRow({ bro, onOpen }: { bro: BroCardModel; onOpen: (id: string) => void }) {
```

to:

```jsx
function DesktopRosterRow({ bro, onOpen, onSetup }: { bro: BroCardModel; onOpen: (id: string) => void; onSetup: (bro: BroCardModel) => void }) {
```

and replace `<HomeBroCopyAction bro={bro} variant="row" />` with `<HomeBroConnectAction bro={bro} variant="row" onSetup={onSetup} />`.

- [ ] **Step 3: Hold the dialog state in `DesktopHome` and pass `onSetup`**

In `DesktopHome`, add state next to `sheetOpen`:

```jsx
  const [setupBro, setSetupBro] = useState<BroCardModel | null>(null);
```

Pass `onSetup={setSetupBro}` to every `DesktopBroCard` and `DesktopRosterRow` render in `DesktopHome` (the `workingBros.map(...)` and the standing-by `...map(...)`). Then render the overlay — add just before `DesktopHome`'s closing `</DesktopFrame>`:

```jsx
      {setupBro && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setSetupBro(null)} onCreated={shell.refreshShellSession} bro={setupBro} />
      ) : null}
```

- [ ] **Step 4: Wire the mobile card**

In `MobileBroCard`, add `onSetup` to its props and render `<HomeBroConnectAction bro={bro} variant="card" onSetup={onSetup} />` inside the offline/unbound card body (alongside the existing card content). In `MobileHome`, add `const [setupBro, setSetupBro] = useState<BroCardModel | null>(null);`, pass `onSetup={setSetupBro}` to each `<MobileBroCard … />`, and render the overlay near `MobileHome`'s existing `addOpen` `CreateConnectSheet`:

```jsx
      {setupBro && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setSetupBro(null)} onCreated={shell.refreshShellSession} bro={setupBro} mobile />
      ) : null}
```

(If `MobileBroCard`'s offline state is a distinct early-return branch, add the action there; match the existing markup so layout stays intact.)

- [ ] **Step 5: Build to surface any leftover references**

Run: `npm run build`
Expected: no errors. If `useCopyNodeConnectCommand` / `OfflineCommandLine` / `highlightCommandToken` are now entirely unused after removing the copy action, delete them. (Keep `buildExecutorConnectCommands` and `lib/session-client.ts` — still used by the dialog.)

- [ ] **Step 6: Add a home-card test**

Add to `App.test.tsx`:

```javascript
  it("opens the setup dialog from an offline home bro card", async () => {
    // Render home with an offline bro (reuse the offline-bro fixture/snapshot helper used elsewhere in this file).
    // Then:
    fireEvent.click(await screen.findByTestId(/home-bro-connect-/));
    expect(await screen.findByText(/Reconnect |Set up /i)).toBeInTheDocument();
  });
```

(Use the file's existing home-with-bros fixture; assert the connect button appears for the offline bro and clicking it opens the dialog without navigating. Match the existing fixture/helper names.)

- [ ] **Step 7: Run the full UI suite**

Run (from `src/newbro/ui`): `npm test`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): home bro card opens the setup dialog

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Run tests from `src/newbro/ui`**; `npm test -- <file> -t "<name>"` (script is `vitest run`).
- **Fixtures:** Tasks 3–5 reference the offline/home fixtures already in `App.test.tsx` (the `forge` bro on `Workshop Mini`, `forgeSnapshot`, etc.). Don't invent new fixtures — copy the construction from the existing offline test and adjust. If a referenced helper name differs, match what's in the file.
- **Single dialog component:** every new overlay is the same `CreateConnectSheet` with `bro` set; only the open-state owner differs (home vs detail). Don't fork the component.
- **Don't remove `useCopyNodeConnectCommand` until Task 5** (it's still used by the copy action being replaced).
- **Visual layout (Task 2):** verify against the running dialog; iterate spacing values rather than guessing pixel-perfect.
- If `npm run build` flags an unused symbol after the copy action is gone, delete it (`OfflineCommandLine`, `highlightCommandToken`, `useCopyNodeConnectCommand`) — but confirm no other references first.
