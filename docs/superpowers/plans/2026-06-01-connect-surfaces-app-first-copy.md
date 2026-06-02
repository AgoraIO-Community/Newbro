# Connect Surfaces: App-First Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reword the three web-UI connect surfaces (new-bro creation, bro-detail offline header, home "Add a bro" tile) so the macOS app is the recommended path — download the app + paste the connect command — with the terminal commands kept behind an "advanced / not on a Mac" disclosure.

**Architecture:** Copy/JSX changes in `src/newbro/ui/src/ArtboardShell.tsx` plus one shared URL constant and a small amount of CSS. The connect-command builders (`lib/session-client.ts`) are unchanged; the generated command already matches the app's "Paste connect command…" parser. Tests live in `src/newbro/ui/src/__tests__/App.test.tsx`.

**Tech Stack:** React + TypeScript (Vite), Vitest + Testing Library, lucide-react icons.

**Reference spec:** `docs/superpowers/specs/2026-06-01-connect-surfaces-app-first-copy-design.md`

---

## File Structure

- **Modify** `src/newbro/ui/src/ArtboardShell.tsx`:
  - Add `APP_DOWNLOAD_URL` constant and `Download` to the lucide-react import.
  - `CreateConnectSheet`: add a `mobile?: boolean` prop and a `showTerminal` disclosure state; restructure STEP 3 (download button / mobile defer text + connect command + terminal fallback); reword tip/meta/footer. Pass `mobile` at the two mobile call sites.
  - `NodeOfflineNotice`: reword foot line, disclosure label, reveal text, and the mobile body line.
  - `AddBroTile`: reword the sub-label.
- **Modify** `src/newbro/ui/src/styles/variants-onboarding.css`: add `.ob-download` and disclosure styles.
- **Modify** `src/newbro/ui/src/__tests__/App.test.tsx`: update the two onboarding tests and the offline-disclosure assertion.

> **Run commands from `src/newbro/ui`** (that's where the UI package + test runner live). The test command is `npm test -- run <file>` (Vitest).

---

### Task 1: New-bro creation STEP 3 — app-first

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/styles/variants-onboarding.css`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Update the two onboarding tests to the new copy (failing first)**

In `src/newbro/ui/src/__tests__/App.test.tsx`, replace the body of the desktop test
`it("waits for the first node connection before creating the first Bro", …)` — specifically these assertions:

```javascript
    expect(await screen.findByText(/install-newbro-cli\.sh/)).toBeInTheDocument();
    expect(screen.getByText(/paste this in a terminal to install newbro/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy install command/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy connect command/i })).toBeInTheDocument();
    expect(screen.getByText(/This updates on its own once atlas connects/)).toBeInTheDocument();
```

with:

```javascript
    expect(await screen.findByText(/install the Newbro app/i)).toBeInTheDocument();
    const download = screen.getByRole("link", { name: /Download the Newbro app/i });
    expect(download).toHaveAttribute("href", "https://github.com/AgoraIO/Synopse/releases/latest");
    expect(screen.getByText(/paste it into the app/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy connect command/i })).toBeInTheDocument();
    expect(screen.getByText(/This updates on its own once atlas connects/)).toBeInTheDocument();
    // Terminal commands are tucked behind a disclosure, hidden by default.
    expect(screen.queryByRole("button", { name: /Copy install command/i })).not.toBeInTheDocument();
```

Then replace the body of the mobile test
`it("shows mobile install/connect instructions before creating the first Bro", …)` — these assertions:

```javascript
    expect(await screen.findByText(/paste this in a terminal to install newbro/)).toBeInTheDocument();
    expect(screen.getByText(/curl -fsSL newbro\.dev\/install\.sh \| sh/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy install command/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Copy connect command/i })).toBeInTheDocument();
```

with:

```javascript
    expect(await screen.findByText(/Install the Newbro app on the Mac/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy connect command/i })).toBeInTheDocument();
    // No usable Mac download on a phone, and terminal commands stay collapsed.
    expect(screen.queryByRole("link", { name: /Download the Newbro app/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy install command/i })).not.toBeInTheDocument();
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `src/newbro/ui`): `npm test -- run src/__tests__/App.test.tsx -t "before creating the first Bro"`
Expected: both tests FAIL (old strings/buttons still rendered; new ones absent).

- [ ] **Step 3: Add the constant and icon import**

In `src/newbro/ui/src/ArtboardShell.tsx`, add `Download` to the existing `lucide-react` import (the line begins `import { … } from "lucide-react";` — insert `Download` alphabetically). Then add this constant near the top of the file, just after the imports:

```typescript
const APP_DOWNLOAD_URL = "https://github.com/AgoraIO/Synopse/releases/latest";
```

- [ ] **Step 4: Add the `mobile` prop and disclosure state to `CreateConnectSheet`**

Change the signature:

```typescript
function CreateConnectSheet({
  sessionId,
  onClose,
  onCreated,
  bro,
}: {
  sessionId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
  bro?: BroCardModel | null;
}) {
```

to:

```typescript
function CreateConnectSheet({
  sessionId,
  onClose,
  onCreated,
  bro,
  mobile = false,
}: {
  sessionId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
  bro?: BroCardModel | null;
  mobile?: boolean;
}) {
```

And add the disclosure state next to the other `useState` calls in the component (e.g. after `const [completed, setCompleted] = useState(false);`):

```typescript
  const [showTerminal, setShowTerminal] = useState(false);
```

- [ ] **Step 5: Pass `mobile` at the two mobile call sites**

In `MobileHome` (the `<CreateConnectSheet … />` around the `addOpen` block) change:

```jsx
        <CreateConnectSheet
          sessionId={shell.activeShellSessionId}
          onClose={() => setAddOpen(false)}
          onCreated={shell.refreshShellSession}
        />
```

to add `mobile`:

```jsx
        <CreateConnectSheet
          sessionId={shell.activeShellSessionId}
          onClose={() => setAddOpen(false)}
          onCreated={shell.refreshShellSession}
          mobile
        />
```

In `MobileDetail` change:

```jsx
              <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={onBack} onCreated={shell.refreshShellSession} bro={bro} />
```

to:

```jsx
              <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={onBack} onCreated={shell.refreshShellSession} bro={bro} mobile />
```

(Leave the two desktop call sites — in `Home`/`DesktopFrame` and `DesktopDetail` — unchanged; `mobile` defaults to false.)

- [ ] **Step 6: Replace the STEP 3 fieldset block**

Replace this exact block (the `<div className="ob-fieldset">` for STEP 3, through its closing `</div>`, i.e. from `<div className="ob-fieldset-eyebrow-row">` down to the line before `<div className="dt-modal-tip">`):

```jsx
                  <div className="ob-fieldset-eyebrow-row">
                    <span className="ob-field-eyebrow">STEP 3 · CONNECT A COMPUTER</span>
                    <span className="ob-fieldset-eyebrow-meta">{completed ? "connected" : commands ? "installs CLI + starts the executor" : "on demand"}</span>
                  </div>
                  <p className="ob-connect-guide">On the computer where {pendingBroName || trimmedName || "your bro"} should work, paste this in a terminal to install newbro:</p>
                  <div className="ob-connect">
                    <div className="ob-connect-cmd">
                      <span className="ob-connect-prompt">$</span>
                      <span className="ob-connect-line">{commands?.installOnly ?? "curl -fsSL newbro.dev/install.sh | sh"}</span>
                      <button type="button" className="ob-connect-copy" aria-label="Copy install command" disabled={!commands} onClick={() => { if (commands) void copyCommand(commands.installOnly, "install"); }}>
                        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="9" y="9" width="11" height="11" rx="2"/>
                          <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                        </svg>
                      </button>
                    </div>
                  </div>
                  <p className="ob-connect-guide ob-connect-guide-2">Then start it with your one-time key — we filled in the details for you:</p>
                  <div className="ob-connect">
                    <div className="ob-connect-cmd">
                      <span className="ob-connect-prompt">$</span>
                      <span className="ob-connect-line">{commands?.runOnly ?? "newbro executor run --token pending"}</span>
                      <button type="button" className="ob-connect-copy" aria-label="Copy connect command" disabled={!commands} onClick={() => { if (commands) void copyCommand(commands.runOnly, "run"); }}>
                        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="9" y="9" width="11" height="11" rx="2"/>
                          <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                        </svg>
                      </button>
                    </div>
                    <div className="ob-connect-status">
                      <span className="ob-connect-spinner" aria-hidden="true"><span /><span /><span /></span>
                      <span className="ob-connect-status-text">
                        <strong>{completed ? `${pendingBroName || trimmedName} is connected.` : commands ? `Waiting to hear from your computer…` : `Ready to connect ${trimmedName || "a bro"}...`}</strong>
                        <span>{completed ? "The bro has been created after the computer connected successfully." : commands ? `This updates on its own once ${pendingBroName || trimmedName} connects. Nothing else on that computer changes.` : "Newbro will issue an install/connect command first. The bro appears after the first successful connection."}</span>
                      </span>
                      <span className="ob-connect-time">{completed ? "done" : copiedKind ? "copied" : commands ? "installs CLI + starts the executor" : "new"}</span>
                    </div>
                  </div>
                  <div className="ob-connect-meta">
                    <button type="button" className="ob-link ob-link-sm">Get a fresh link</button>
                    <span className="ob-connect-meta-sep">·</span>
                    <button type="button" className="ob-link ob-link-sm">Walk me through it</button>
                  </div>
```

with:

```jsx
                  <div className="ob-fieldset-eyebrow-row">
                    <span className="ob-field-eyebrow">STEP 3 · CONNECT A COMPUTER</span>
                    <span className="ob-fieldset-eyebrow-meta">{completed ? "connected" : commands ? "download app + paste connect" : "on demand"}</span>
                  </div>
                  {mobile ? (
                    <p className="ob-connect-guide">Install the Newbro app on the Mac that will run {pendingBroName || trimmedName || "your bro"}, then paste this connect command into it (menu → Paste connect command):</p>
                  ) : (
                    <>
                      <p className="ob-connect-guide">On the Mac where {pendingBroName || trimmedName || "your bro"} should work, install the Newbro app:</p>
                      <a className="ob-download" href={APP_DOWNLOAD_URL} target="_blank" rel="noreferrer">
                        <Download size={14} strokeWidth={2} />
                        Download the Newbro app
                      </a>
                      <p className="ob-connect-guide ob-connect-guide-2">Then copy this connect command and paste it into the app (menu → Paste connect command):</p>
                    </>
                  )}
                  <div className="ob-connect">
                    <div className="ob-connect-cmd">
                      <span className="ob-connect-prompt">$</span>
                      <span className="ob-connect-line">{commands?.runOnly ?? "newbro executor run --token pending"}</span>
                      <button type="button" className="ob-connect-copy" aria-label="Copy connect command" disabled={!commands} onClick={() => { if (commands) void copyCommand(commands.runOnly, "run"); }}>
                        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="9" y="9" width="11" height="11" rx="2"/>
                          <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                        </svg>
                      </button>
                    </div>
                    <div className="ob-connect-status">
                      <span className="ob-connect-spinner" aria-hidden="true"><span /><span /><span /></span>
                      <span className="ob-connect-status-text">
                        <strong>{completed ? `${pendingBroName || trimmedName} is connected.` : commands ? `Waiting to hear from your computer…` : `Ready to connect ${trimmedName || "a bro"}...`}</strong>
                        <span>{completed ? "The bro has been created after the computer connected successfully." : commands ? `This updates on its own once ${pendingBroName || trimmedName} connects. Nothing else on that Mac changes.` : "Newbro will issue a connect command first. The bro appears after the first successful connection."}</span>
                      </span>
                      <span className="ob-connect-time">{completed ? "done" : copiedKind ? "copied" : commands ? "download app + paste connect" : "new"}</span>
                    </div>
                  </div>
                  <button type="button" className="ob-link ob-link-sm ob-terminal-toggle" aria-expanded={showTerminal} onClick={() => setShowTerminal((v) => !v)}>
                    {showTerminal ? "Hide terminal option" : "Not on a Mac? Connect from a terminal"}
                  </button>
                  {showTerminal ? (
                    <div className="ob-terminal-fallback">
                      <p className="ob-connect-guide">Install — paste this in a terminal on that computer:</p>
                      <div className="ob-connect">
                        <div className="ob-connect-cmd">
                          <span className="ob-connect-prompt">$</span>
                          <span className="ob-connect-line">{commands?.installOnly ?? "curl -fsSL newbro.dev/install.sh | sh"}</span>
                          <button type="button" className="ob-connect-copy" aria-label="Copy install command" disabled={!commands} onClick={() => { if (commands) void copyCommand(commands.installOnly, "install"); }}>
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                              <rect x="9" y="9" width="11" height="11" rx="2"/>
                              <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                            </svg>
                          </button>
                        </div>
                      </div>
                      <p className="ob-connect-guide ob-connect-guide-2">Then start it with your one-time key:</p>
                      <div className="ob-connect">
                        <div className="ob-connect-cmd">
                          <span className="ob-connect-prompt">$</span>
                          <span className="ob-connect-line">{commands?.runOnly ?? "newbro executor run --token pending"}</span>
                          <button type="button" className="ob-connect-copy" aria-label="Copy connect command from terminal" disabled={!commands} onClick={() => { if (commands) void copyCommand(commands.runOnly, "run"); }}>
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                              <rect x="9" y="9" width="11" height="11" rx="2"/>
                              <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                            </svg>
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : null}
                  <div className="ob-connect-meta">
                    <button type="button" className="ob-link ob-link-sm">Get a fresh link</button>
                    <span className="ob-connect-meta-sep">·</span>
                    <button type="button" className="ob-link ob-link-sm">Walk me through it</button>
                  </div>
```

- [ ] **Step 7: Reword the TIP**

Replace:

```jsx
                  <p>
                    That computer can be anything that stays on — your Mac, a spare
                    laptop, a mini in the closet. {pendingBroName || trimmedName || "your bro"} only runs there when you ask
                    it to, and you can move it to another computer anytime.
                  </p>
```

with:

```jsx
                  <p>
                    That computer should be a Mac that stays on — your main machine, a spare
                    laptop, a mini in the closet. {pendingBroName || trimmedName || "your bro"} only runs there when you ask
                    it to. (Linux or a server? Use the terminal option above.)
                  </p>
```

- [ ] **Step 8: Update the footer status string**

Replace (in the `<footer className="ob-sheet-foot">` of `CreateConnectSheet`):

```jsx
              {completed ? "Connected once · Bro ready" : commands ? "We’ll detect your computer automatically · link valid 9:46" : "Install/connect command will be generated on demand"}
```

with:

```jsx
              {completed ? "Connected once · Bro ready" : commands ? "We’ll detect your computer automatically · link valid 9:46" : "Download link + connect command will be generated on demand"}
```

- [ ] **Step 9: Add CSS**

Append to `src/newbro/ui/src/styles/variants-onboarding.css`:

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

- [ ] **Step 10: Run the onboarding tests to verify they pass**

Run (from `src/newbro/ui`): `npm test -- run src/__tests__/App.test.tsx -t "before creating the first Bro"`
Expected: both onboarding tests PASS.

- [ ] **Step 11: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-onboarding.css src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): app-first connect step in new-bro creation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Bro-detail offline header — app-first

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Test: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Update the offline-disclosure assertion (failing first)**

In `src/newbro/ui/src/__tests__/App.test.tsx`, find:

```javascript
    fireEvent.click(screen.getByRole("button", { name: /Reinstall or update the CLI/i }));
```

replace with:

```javascript
    fireEvent.click(screen.getByRole("button", { name: /Reinstall from a terminal/i }));
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `src/newbro/ui`): `npm test -- run src/__tests__/App.test.tsx -t "offline"`
Expected: the offline test FAILS (the old button name no longer matches — but it's still rendered as the old label).

- [ ] **Step 3: Reword the desktop foot line and disclosure**

In `NodeOfflineNotice` (the desktop `return`), replace:

```jsx
      <div className="dt-offline-foot">
        <span>Run on <strong>{node.name}</strong> to bring it back — it already has the CLI installed.</span>
        <button
          type="button"
          className="dt-offline-disclose"
          aria-expanded={showReinstall}
          onClick={() => setShowReinstall((v) => !v)}
        >
          <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>
          {showReinstall ? "Hide reinstall" : "Reinstall or update the CLI"}
        </button>
      </div>
```

with:

```jsx
      <div className="dt-offline-foot">
        <span><strong>Open the Newbro app on {node.name}</strong> — it reconnects on its own. Not set up there yet? Copy the connect command above and paste it into the app.</span>
        <button
          type="button"
          className="dt-offline-disclose"
          aria-expanded={showReinstall}
          onClick={() => setShowReinstall((v) => !v)}
        >
          <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>
          {showReinstall ? "Hide terminal" : "Reinstall from a terminal"}
        </button>
      </div>
```

- [ ] **Step 4: Reword the reveal panel text**

Replace:

```jsx
        <div className="dt-offline-reinstall">
          <p>CLI missing or out of date? This installs the latest and reconnects in one step:</p>
```

with:

```jsx
        <div className="dt-offline-reinstall">
          <p>The app keeps the CLI updated automatically. To reinstall manually, run this in a terminal:</p>
```

- [ ] **Step 5: Reword the mobile body line**

In the `if (mobile) { return … }` branch of `NodeOfflineNotice`, replace:

```jsx
          <span>Copy or share Install + connect from desktop, then run it in Terminal on the computer that should work for this bro.</span>
```

with:

```jsx
          <span>Copy the connect command from desktop, then paste it into the Newbro app on the Mac that should work for this bro.</span>
```

- [ ] **Step 6: Run the offline test to verify it passes**

Run (from `src/newbro/ui`): `npm test -- run src/__tests__/App.test.tsx -t "offline"`
Expected: the offline test PASSES (the disclosure button now reads "Reinstall from a terminal", still revealing `bro-node-copy-command`).

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): app-first copy in bro-detail offline header

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Home "Add a bro" tile

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`

- [ ] **Step 1: Reword the sub-label**

In `AddBroTile`, replace:

```jsx
        <span className="home-add-sub">Generates an install/connect command</span>
```

with:

```jsx
        <span className="home-add-sub">Download the app + connect a computer</span>
```

- [ ] **Step 2: Run the full UI test suite**

Run (from `src/newbro/ui`): `npm test -- run`
Expected: all tests pass (no test asserts the old "Generates an install/connect command" string; the suite is green overall).

- [ ] **Step 3: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx
git commit -m "feat(ui): reword home Add-a-bro tile for app-first connect

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Run tests from `src/newbro/ui`.** Vitest filter: `npm test -- run src/__tests__/App.test.tsx -t "<name fragment>"`.
- **`getByRole` uniqueness:** the terminal-fallback run button uses aria-label "Copy connect command from terminal" so `getByRole("button", { name: /Copy connect command/i })` still matches the single primary button while the disclosure is collapsed. Keep these labels distinct.
- **Don't touch `lib/session-client.ts` or its tests** — the generated commands are unchanged; that's intentional.
- **If `npm test -- run` reveals any other test asserting changed copy** (beyond the three updated here), update that assertion to the new string — do not revert the copy.
