# Bro Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users rename existing Bros from the create/connect sheet, desktop Home/Detail, and mobile Manage Bros.

**Architecture:** Keep rename as a frontend call to the existing persona API through `updatePersona(sessionId, bro.id, { name })`, followed by `refreshShellSession()`. Add one shared rename dialog component in `ArtboardShell.tsx` and reuse it from desktop and mobile surfaces. Do not change protocol models, runtime scheduling, executor-node ownership, or persona ids.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, existing Newbro FastAPI persona API.

---

## File Structure

- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
  - Add a shared `RenameBroDialog` component.
  - Add edit buttons on desktop Home cards/rows and desktop detail header area.
  - Add rename action in mobile Manage Bros edit mode.
  - Let `CreateConnectSheet` save an existing Bro's name through `updatePersona`.
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`
  - Add focused regression tests for desktop rename, create/connect sheet rename, and mobile Manage Bros rename.
- Modify: `src/newbro/ui/src/styles/app.css`
  - Add small styles for edit icon buttons and the rename dialog if existing classes are insufficient.

No backend files should change unless a test proves the existing PATCH route cannot support this behavior.

---

### Task 1: Desktop Rename Dialog

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`
- Modify: `src/newbro/ui/src/styles/app.css`

- [ ] **Step 1: Write the failing desktop rename test**

Add this test near the existing desktop Home/Bro Detail tests in `src/newbro/ui/src/__tests__/App.test.tsx`:

```tsx
it("renames a Bro from desktop detail and refreshes the shell snapshot", async () => {
  window.history.replaceState({}, "", "/bros/forge?sid=session-existing");
  clientMock.updatePersona.mockResolvedValue({
    persona_id: "forge",
    name: "Scout",
    avatar: "bro",
    base_prompt: "",
    executor_node_id: "node-forge",
    bro_detail_session_id: "detail-forge",
    status: "idle",
  });
  clientMock.getSessionSnapshot.mockImplementation(async (sessionId: string) => {
    const snapshot = forgeSnapshot(sessionId);
    if (clientMock.updatePersona.mock.calls.length > 0) {
      snapshot.personas[0].name = "Scout";
      snapshot.bro_threads = snapshot.bro_threads.map((thread: any) => ({
        ...thread,
        persona_name: "Scout",
      }));
    }
    return snapshot;
  });

  render(<RouterProvider router={getRouter()} />);

  expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit Bro" }));
  const dialog = await screen.findByRole("dialog", { name: /Edit Forge/i });
  fireEvent.change(within(dialog).getByLabelText("Bro name"), { target: { value: "Scout" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

  await waitFor(() => {
    expect(clientMock.updatePersona).toHaveBeenCalledWith("session-existing", "forge", { name: "Scout" });
  });
  await waitFor(() => expect(screen.getByRole("heading", { name: "Scout" })).toBeInTheDocument());
  expect(screen.queryByRole("dialog", { name: /Edit Forge/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the desktop rename test to verify it fails**

Run:

```bash
cd src/newbro/ui && bun run test -- src/__tests__/App.test.tsx -t "renames a Bro from desktop detail"
```

Expected: FAIL because no `Edit Bro` button/dialog exists.

- [ ] **Step 3: Add the shared rename dialog component**

In `src/newbro/ui/src/ArtboardShell.tsx`, update the lucide import:

```tsx
import { ArrowUp, Check, ChevronLeft, Download, FileText, GitBranch, Layers, LogOut, MessageSquare, Mic, Pencil, Plus, Radio, Settings, WifiOff, X } from "lucide-react";
```

Add this component above `DesktopHome`:

```tsx
function RenameBroDialog({
  bro,
  sessionId,
  onClose,
  onRenamed,
  mobile = false,
}: {
  bro: BroCardModel;
  sessionId: string;
  onClose: () => void;
  onRenamed: () => Promise<void>;
  mobile?: boolean;
}) {
  const [name, setName] = useState(bro.name);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmedName = name.trim();
  const unchanged = trimmedName === bro.name.trim();
  const canSave = trimmedName.length > 0 && !unchanged && !pending;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    if (!trimmedName) {
      setError("Bro name is required.");
      return;
    }
    if (unchanged) {
      onClose();
      return;
    }
    setPending(true);
    setError(null);
    try {
      await updatePersona(sessionId, bro.id, { name: trimmedName });
      await onRenamed();
      onClose();
    } catch (err) {
      setError(describeError(err, "Could not rename this Bro."));
    } finally {
      setPending(false);
    }
  };

  return (
    <div
      className="nb-first-run-sheet-layer nb-rename-dialog-layer"
      role="dialog"
      aria-modal="true"
      aria-label={`Edit ${bro.name}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form className={`nb-rename-dialog${mobile ? " nb-rename-dialog-mobile" : ""}`} onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
        <header className="nb-rename-head">
          <div>
            <span className="ob-eyebrow ob-eyebrow-coral">BRO SETTINGS</span>
            <h2 className="nb-rename-title">Edit {bro.name}</h2>
          </div>
          <button type="button" className="ob-sheet-close" aria-label="Close" onClick={onClose}>
            <X size={16} strokeWidth={2.2} />
          </button>
        </header>
        <label className="ob-field">
          <span className="ob-field-eyebrow">BRO NAME</span>
          <div className={`ob-input${trimmedName ? " ob-input-filled" : ""}`}>
            <span className="ob-input-prefix">@</span>
            <input
              aria-label="Bro name"
              type="text"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
              }}
              autoFocus
            />
          </div>
          <span className="ob-field-hint">Use a short name that is easy to say out loud.</span>
        </label>
        {error ? <div className="nb-status-banner nb-status-banner-error">{error}</div> : null}
        <footer className="nb-rename-actions">
          <button type="button" className="nb-rename-secondary" onClick={onClose} disabled={pending}>
            Cancel
          </button>
          <button type="submit" className={`ob-cta${!canSave ? " ob-cta-pending" : ""}`} disabled={!canSave}>
            {pending ? <span className="ob-cta-spinner" aria-hidden="true" /> : null}
            <span>{pending ? "Saving..." : "Save"}</span>
          </button>
        </footer>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Wire the dialog into desktop Home and Detail**

Update `DesktopBroCard` to accept `onRename`:

```tsx
function DesktopBroCard({
  bro,
  onOpen,
  onSetup,
  onRename,
  featured = false,
}: {
  bro: BroCardModel;
  onOpen: (id: string) => void;
  onSetup: (bro: BroCardModel) => void;
  onRename: (bro: BroCardModel) => void;
  featured?: boolean;
}) {
```

Inside `DesktopBroCard`, directly before `HomeBroConnectAction`, add:

```tsx
{bro.source === "runtime" ? (
  <button
    type="button"
    className="dt-bro-card-edit"
    data-home-card-action="rename"
    aria-label={`Edit ${bro.name}`}
    onClick={(event) => {
      event.preventDefault();
      event.stopPropagation();
      onRename(bro);
    }}
  >
    <Pencil size={12} strokeWidth={2.2} />
    <span>Edit</span>
  </button>
) : null}
```

Update `DesktopRosterRow` to accept `onRename`:

```tsx
function DesktopRosterRow({
  bro,
  onOpen,
  onSetup,
  onRename,
}: {
  bro: BroCardModel;
  onOpen: (id: string) => void;
  onSetup: (bro: BroCardModel) => void;
  onRename: (bro: BroCardModel) => void;
}) {
```

Inside `DesktopRosterRow`, directly before `HomeBroConnectAction`, add:

```tsx
{bro.source === "runtime" ? (
  <button
    type="button"
    className="dt-roster-edit"
    data-home-card-action="rename"
    aria-label={`Edit ${bro.name}`}
    onClick={(event) => {
      event.preventDefault();
      event.stopPropagation();
      onRename(bro);
    }}
  >
    <Pencil size={12} strokeWidth={2.2} />
    <span>Edit</span>
  </button>
) : null}
```

In `DesktopHome`, add state near `setupBro`:

```tsx
const [renameBro, setRenameBro] = useState<BroCardModel | null>(null);
```

Update both desktop Home call sites:

```tsx
{workingBros.map((bro) => (
  <DesktopBroCard key={bro.id} bro={bro} featured onOpen={onOpenBro} onSetup={setSetupBro} onRename={setRenameBro} />
))}
```

```tsx
{standingByBros.map((bro) => (
  <DesktopRosterRow key={bro.id} bro={bro} onOpen={onOpenBro} onSetup={setSetupBro} onRename={setRenameBro} />
))}
```

Render the shared dialog near the existing Home sheets:

```tsx
{renameBro && shell.activeShellSessionId ? (
  <RenameBroDialog
    bro={renameBro}
    sessionId={shell.activeShellSessionId}
    onClose={() => setRenameBro(null)}
    onRenamed={shell.refreshShellSession}
  />
) : null}
```

In `DesktopDetail`, add local state near the existing `connectOpen` state:

```tsx
const [renameOpen, setRenameOpen] = useState(false);
```

Inside the `DesktopFrame` children, before the `WorkspacePickerDialog`, add a compact edit button near the detail surface. Place it above `DesktopActivityRail` in the non-connect branch so it is always available for runtime Bros:

```tsx
<div className="nb-detail-edit-row">
  <button type="button" className="nb-bro-edit-button" aria-label="Edit Bro" onClick={() => setRenameOpen(true)}>
    <Pencil size={14} strokeWidth={2} />
    <span>Edit Bro</span>
  </button>
</div>
```

Render the dialog near the existing connect sheet rendering:

```tsx
{renameOpen && shell.activeShellSessionId ? (
  <RenameBroDialog
    bro={bro}
    sessionId={shell.activeShellSessionId}
    onClose={() => setRenameOpen(false)}
    onRenamed={shell.refreshShellSession}
  />
) : null}
```

- [ ] **Step 5: Add minimal CSS for the desktop dialog and edit button**

Append to `src/newbro/ui/src/styles/app.css`:

```css
.nb-detail-edit-row {
  position: absolute;
  right: 28px;
  top: 82px;
  z-index: 2;
}

.nb-bro-edit-button,
.dt-bro-card-edit,
.dt-roster-edit {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  border: 1px solid rgba(17, 24, 39, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  padding: 0 11px;
  font-size: 12px;
  font-weight: 700;
  color: #111827;
  box-shadow: 0 8px 24px rgba(17, 24, 39, 0.08);
}

.nb-bro-edit-button:hover,
.dt-bro-card-edit:hover,
.dt-roster-edit:hover {
  border-color: rgba(244, 99, 76, 0.32);
  color: #dc4b39;
}

.dt-bro-card-edit,
.dt-roster-edit {
  align-self: flex-start;
  min-height: 30px;
  padding: 0 9px;
  box-shadow: none;
}

.nb-rename-dialog-layer {
  align-items: center;
  justify-content: center;
}

.nb-rename-dialog {
  width: min(420px, calc(100vw - 32px));
  border: 1px solid rgba(17, 24, 39, 0.1);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 24px 80px rgba(17, 24, 39, 0.22);
  padding: 18px;
}

.nb-rename-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.nb-rename-title {
  margin: 4px 0 0;
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0;
  color: #111827;
}

.nb-rename-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}

.nb-rename-secondary {
  min-height: 38px;
  border: 1px solid rgba(17, 24, 39, 0.1);
  border-radius: 8px;
  background: #fff;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 700;
  color: #4b5563;
}
```

- [ ] **Step 6: Run the desktop rename test to verify it passes**

Run:

```bash
cd src/newbro/ui && bun run test -- src/__tests__/App.test.tsx -t "renames a Bro from desktop detail"
```

Expected: PASS.

- [ ] **Step 7: Commit desktop rename dialog**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx src/newbro/ui/src/styles/app.css
git commit -m "Add desktop Bro rename dialog"
```

---

### Task 2: Create / Connect Sheet Rename Support

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`

- [ ] **Step 1: Write the failing create/connect sheet test**

Add this test near the existing create/connect sheet tests:

```tsx
it("allows renaming an existing Bro from the create connect sheet", async () => {
  const offlineNode = usableExecutorNode({
    connected_executors: [],
    connection_status: "disconnected",
    last_connected_at: "2026-05-23T20:00:00Z",
  });
  clientMock.getSessionSnapshot.mockResolvedValueOnce(forgeSnapshot("session-existing", offlineNode));
  clientMock.updatePersona.mockResolvedValue({
    persona_id: "forge",
    name: "Scout",
    avatar: "bro",
    base_prompt: "",
    executor_node_id: "node-forge",
    bro_detail_session_id: "detail-forge",
    status: "idle",
  });
  window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

  render(<RouterProvider router={getRouter()} />);

  fireEvent.click(await screen.findByRole("button", { name: /computer offline · set up/i }));
  const dialog = await screen.findByRole("dialog", { name: /Create and connect a Bro/i });
  const nameInput = within(dialog).getByLabelText("Bro name");
  expect(nameInput).toBeEnabled();
  fireEvent.change(nameInput, { target: { value: "Scout" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save name" }));

  await waitFor(() => {
    expect(clientMock.updatePersona).toHaveBeenCalledWith("session-existing", "forge", { name: "Scout" });
  });
});
```

- [ ] **Step 2: Run the create/connect sheet test to verify it fails**

Run:

```bash
cd src/newbro/ui && bun run test -- src/__tests__/App.test.tsx -t "allows renaming an existing Bro from the create connect sheet"
```

Expected: FAIL because the name input is disabled and no `Save name` button exists.

- [ ] **Step 3: Add name-save state and helper to `CreateConnectSheet`**

Inside `CreateConnectSheet`, after the existing `busy` state:

```tsx
const [nameSaving, setNameSaving] = useState(false);
```

After `const canCreate = ...`, add:

```tsx
const existingBroNameChanged = Boolean(bro) && trimmedName.length > 0 && trimmedName !== (bro?.name.trim() ?? "");
const canSaveExistingBroName = Boolean(bro) && existingBroNameChanged && !busy && !nameSaving && !completed;
```

Add this function inside `CreateConnectSheet` before `copyCommand`:

```tsx
async function saveExistingBroName() {
  if (!bro || nameSaving) return;
  if (!trimmedName) {
    setError("Bro name is required.");
    return;
  }
  if (!existingBroNameChanged) {
    return;
  }
  setNameSaving(true);
  setError(null);
  try {
    await updatePersona(sessionId, bro.id, { name: trimmedName });
    await onCreated();
  } catch (err) {
    setError(describeError(err, "Could not rename this Bro."));
  } finally {
    setNameSaving(false);
  }
}
```

- [ ] **Step 4: Save changed name before connect/setup action**

At the start of `issueConnectCredentials`, after `setError(null);`, insert:

```tsx
if (bro && existingBroNameChanged) {
  await updatePersona(sessionId, bro.id, { name: trimmedName });
  await onCreated();
}
```

Keep `const nextBroName = trimmedName;` after this block so new node labels use the latest input.

- [ ] **Step 5: Update the Step 1 input markup**

Replace the current Step 1 input block:

```tsx
<input type="text" value={name} disabled={Boolean(bro) || Boolean(commands) || busy} onChange={(event) => setName(event.target.value)} />
```

with:

```tsx
<input
  aria-label="Bro name"
  type="text"
  value={name}
  disabled={busy || nameSaving || completed}
  onChange={(event) => setName(event.target.value)}
/>
```

Immediately after the hint for Step 1, add:

```tsx
{bro ? (
  <button
    type="button"
    className="nb-inline-save-name"
    disabled={!canSaveExistingBroName}
    onClick={() => { void saveExistingBroName(); }}
  >
    {nameSaving ? "Saving..." : "Save name"}
  </button>
) : null}
```

- [ ] **Step 6: Add small CSS for the inline save**

Append to `src/newbro/ui/src/styles/app.css`:

```css
.nb-inline-save-name {
  align-self: flex-start;
  min-height: 32px;
  border: 1px solid rgba(17, 24, 39, 0.1);
  border-radius: 8px;
  background: #fff;
  padding: 0 11px;
  font-size: 12px;
  font-weight: 800;
  color: #111827;
}

.nb-inline-save-name:not(:disabled):hover {
  border-color: rgba(244, 99, 76, 0.35);
  color: #dc4b39;
}

.nb-inline-save-name:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
```

- [ ] **Step 7: Run the create/connect sheet test to verify it passes**

Run:

```bash
cd src/newbro/ui && bun run test -- src/__tests__/App.test.tsx -t "allows renaming an existing Bro from the create connect sheet"
```

Expected: PASS.

- [ ] **Step 8: Commit create/connect sheet rename support**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx src/newbro/ui/src/styles/app.css
git commit -m "Allow Bro rename from connect sheet"
```

---

### Task 3: Mobile Manage Bros Rename

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx`
- Modify: `src/newbro/ui/src/styles/app.css`

- [ ] **Step 1: Write the failing mobile rename test**

Add this test near the existing mobile tests:

```tsx
it("renames a Bro from mobile Manage bros", async () => {
  window.history.replaceState({}, "", "/mobile?sid=session-existing");
  clientMock.updatePersona.mockResolvedValue({
    persona_id: "forge",
    name: "Scout",
    avatar: "bro",
    base_prompt: "",
    executor_node_id: "node-forge",
    bro_detail_session_id: "detail-forge",
    status: "idle",
  });

  render(<RouterProvider router={getRouter()} />);

  fireEvent.click(await screen.findByRole("button", { name: "Account" }));
  fireEvent.click(await screen.findByRole("button", { name: /Manage bros/i }));
  fireEvent.click(await screen.findByRole("button", { name: "Rename Forge" }));
  const dialog = await screen.findByRole("dialog", { name: /Edit Forge/i });
  fireEvent.change(within(dialog).getByLabelText("Bro name"), { target: { value: "Scout" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

  await waitFor(() => {
    expect(clientMock.updatePersona).toHaveBeenCalledWith("session-existing", "forge", { name: "Scout" });
  });
});
```

- [ ] **Step 2: Run the mobile rename test to verify it fails**

Run:

```bash
cd src/newbro/ui && bun run test -- src/__tests__/App.test.tsx -t "renames a Bro from mobile Manage bros"
```

Expected: FAIL because mobile edit mode exposes only remove.

- [ ] **Step 3: Add mobile rename state**

In `MobileHome`, add state after `setupBro`:

```tsx
const [renameBro, setRenameBro] = useState<BroCardModel | null>(null);
```

Update `anyOverlay`:

```tsx
const anyOverlay = accountOpen || addOpen || !!confirmId || !!renameBro;
```

Update `closeAll`:

```tsx
const closeAll = () => { setAccountOpen(false); setAddOpen(false); setConfirmId(null); setRenameBro(null); };
```

- [ ] **Step 4: Add rename callback to `HomeBroEditable`**

Change the component signature:

```tsx
function HomeBroEditable({
  bro,
  featured,
  editing,
  onRemove,
  onRename,
  onOpen,
  onSetup,
}: {
  bro: BroCardModel;
  featured: boolean;
  editing: boolean;
  onRemove: (id: string) => void;
  onRename: (bro: BroCardModel) => void;
  onOpen: (id: string) => void;
  onSetup: (bro: BroCardModel) => void;
}) {
```

Inside the `editing && (...)` block, render both rename and remove controls:

```tsx
{editing && (
  <div className="home-edit-actions">
    <button
      type="button"
      className="home-edit-rename"
      aria-label={`Rename ${bro.name}`}
      onClick={(e) => { e.stopPropagation(); onRename(bro); }}
    >
      <Pencil size={12} strokeWidth={2.4} />
    </button>
    <button
      type="button"
      className="home-edit-remove"
      aria-label={`Remove ${bro.name}`}
      onClick={(e) => { e.stopPropagation(); onRemove(bro.id); }}
    >
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
        <path d="M6 12h12" />
      </svg>
    </button>
  </div>
)}
```

Update both `HomeBroEditable` call sites in `MobileHome`:

```tsx
<HomeBroEditable key={bro.id} bro={bro} featured editing={editMode} onRemove={setConfirmId} onRename={setRenameBro} onOpen={onOpenBro} onSetup={setSetupBro} />
```

```tsx
<HomeBroEditable key={bro.id} bro={bro} featured={false} editing={editMode} onRemove={setConfirmId} onRename={setRenameBro} onOpen={onOpenBro} onSetup={setSetupBro} />
```

- [ ] **Step 5: Render `RenameBroDialog` from mobile Home**

After `HomeConfirmRemove`, add:

```tsx
{renameBro && shell.activeShellSessionId ? (
  <RenameBroDialog
    bro={renameBro}
    sessionId={shell.activeShellSessionId}
    onClose={() => setRenameBro(null)}
    onRenamed={shell.refreshShellSession}
    mobile
  />
) : null}
```

- [ ] **Step 6: Add mobile edit action CSS**

Append to `src/newbro/ui/src/styles/app.css`:

```css
.home-edit-actions {
  position: absolute;
  left: -8px;
  top: -8px;
  z-index: 4;
  display: flex;
  gap: 6px;
}

.home-edit-rename,
.home-edit-remove {
  display: grid;
  height: 25px;
  width: 25px;
  place-items: center;
  border: 2px solid #fff;
  border-radius: 999px;
  box-shadow: 0 8px 18px rgba(17, 24, 39, 0.2);
}

.home-edit-rename {
  background: #111827;
  color: #fff;
}

.home-edit-remove {
  background: #ef4444;
  color: #fff;
}

.nb-rename-dialog-mobile {
  align-self: flex-end;
  width: 100%;
  max-width: 390px;
  border-radius: 18px 18px 0 0;
}
```

If `.home-edit-remove` already exists with conflicting absolute positioning, replace that existing block with the combined `.home-edit-actions`, `.home-edit-rename`, and `.home-edit-remove` block above.

- [ ] **Step 7: Run the mobile rename test to verify it passes**

Run:

```bash
cd src/newbro/ui && bun run test -- src/__tests__/App.test.tsx -t "renames a Bro from mobile Manage bros"
```

Expected: PASS.

- [ ] **Step 8: Commit mobile rename support**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx src/newbro/ui/src/styles/app.css
git commit -m "Add mobile Bro rename action"
```

---

### Task 4: Full Verification

**Files:**
- Verify: `src/newbro/ui/src/ArtboardShell.tsx`
- Verify: `src/newbro/ui/src/__tests__/App.test.tsx`
- Verify: `src/newbro/ui/src/styles/app.css`

- [ ] **Step 1: Run focused frontend tests**

Run:

```bash
cd src/newbro/ui && bun run test -- src/__tests__/App.test.tsx
```

Expected: PASS for the full App test file.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd src/newbro/ui && bun run build
```

Expected: Vite build completes and `tsc --noEmit` reports no TypeScript errors.

- [ ] **Step 3: Run backend/API tests for persona ownership and sync**

Run:

```bash
.venv/bin/python -m pytest tests/integration/api/test_personas.py tests/integration/api/test_public_auth_onboarding.py -q
```

Expected: PASS. These tests guard the existing persona update and owner-scoped session behavior.

- [ ] **Step 4: Check worktree**

Run:

```bash
git status --short
```

Expected: only intentional implementation changes remain, with unrelated pre-existing untracked files still untouched.

- [ ] **Step 5: Commit verification fixes if needed**

If Step 1, 2, or 3 required fixes, commit only those fixes:

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx src/newbro/ui/src/styles/app.css
git commit -m "Stabilize Bro rename verification"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review Notes

Spec coverage:

- Create/connect sheet name edit: Task 2.
- Desktop Home/Detail edit action: Task 1.
- Mobile Manage Bros rename: Task 3.
- Existing API contract, trim + non-empty validation, refresh from snapshot, and no optimistic local-only state: Tasks 1, 2, and 3.
- Error display: shared `RenameBroDialog` and `CreateConnectSheet.saveExistingBroName`.
- Testing: Tasks 1, 2, 3, and 4.

No protocol, runtime, or memory-doc updates are required because this is a UI affordance over an existing persona API contract.
