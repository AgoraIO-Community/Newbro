# Onboarding Dialog Footer Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the bottom action button (Done / Create / Save) of the onboarding dialogs visible on short windows by pinning the footer and scrolling the body instead.

**Architecture:** CSS-only change. The create/connect sheet's desktop grid is changed so the body track is fractional (`minmax(0, 1fr)`) and scrolls, pinning header and footer — the pattern `WorkspacePickerDialog` already uses. The shared `.ob-sheet-body` gets `min-height: 0` so the fractional track actually scrolls. The rename dialog gets a viewport-bounded `max-height` + scroll.

**Tech Stack:** React + Vite + TypeScript UI; plain CSS in `src/newbro/ui/src/styles/`. Build/typecheck via `npm run build`; unit tests via `npm run test` (vitest). jsdom cannot compute layout, so footer *visibility* is verified manually.

**Reference spec:** `docs/superpowers/specs/2026-06-07-onboarding-dialog-footer-visibility-design.md`

---

### Task 1: Make the shared sheet body scrollable

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-onboarding.css` (rule `.ob-sheet-body`, ~line 627)

This is the base rule shared by the create/connect sheet (and inherited at all breakpoints).
Adding `min-height: 0` lets the body's fractional grid track scroll instead of expanding to
its content height. The rule already declares `overflow-y: auto`.

- [ ] **Step 1: Apply the edit**

Find:

```css
.ob-sheet-body {
  overflow-y: auto;
  padding: 16px 22px 20px;
  display: flex; flex-direction: column;
  gap: 18px;
}
```

Replace with:

```css
.ob-sheet-body {
  overflow-y: auto;
  min-height: 0;
  padding: 16px 22px 20px;
  display: flex; flex-direction: column;
  gap: 18px;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/newbro/ui/src/styles/variants-onboarding.css
git commit -m "fix(ui): allow onboarding sheet body to scroll"
```

---

### Task 2: Fix the create/connect sheet desktop grid

**Files:**
- Modify: `src/newbro/ui/src/styles/app.css` (rule `.nb-first-run-sheet-frame .ob-sheet` inside `@media (min-width: 768px)`, ~line 3293)

On desktop the sheet currently uses `grid-template-rows: auto auto auto`, so all three
visible rows (header / body / footer — the handle is `display: none` at this breakpoint)
size to content and the footer is clipped by the sheet's `overflow: hidden` when the window
is short. Change the body track to `minmax(0, 1fr)` so it absorbs the overflow and scrolls.

- [ ] **Step 1: Apply the edit**

Find:

```css
  .nb-first-run-sheet-frame .ob-sheet {
    position: relative;
    inset: auto;
    max-height: min(760px, calc(100dvh - 64px));
    border: 1px solid var(--nb-line);
    border-radius: 18px;
    box-shadow:
      0 30px 80px rgba(15, 23, 42, 0.25),
      0 8px 24px rgba(15, 23, 42, 0.08),
      inset 0 1px 0 rgba(255, 255, 255, 0.9);
    grid-template-rows: auto auto auto;
  }
```

Replace the last property so it reads:

```css
    grid-template-rows: auto minmax(0, 1fr) auto;
  }
```

(Only the `grid-template-rows` line changes; leave the rest of the rule intact.)

- [ ] **Step 2: Commit**

```bash
git add src/newbro/ui/src/styles/app.css
git commit -m "fix(ui): keep create/connect sheet footer visible on short windows"
```

---

### Task 3: Bound the rename dialog to the viewport

**Files:**
- Modify: `src/newbro/ui/src/styles/app.css` (rule `.nb-rename-dialog`, ~line 3510)

`RenameBroDialog` is a flex-column card with no `max-height`, so on a short window the
card overflows the viewport and the Save/Cancel footer falls off-screen. It is a
single-field form, so bounding the card height and letting it scroll is sufficient.

- [ ] **Step 1: Apply the edit**

Find:

```css
.nb-rename-dialog {
  width: min(390px, 100%);
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px;
  border: 1px solid var(--nb-line);
  border-radius: 22px;
  background: var(--nb-paper);
  box-shadow: var(--nb-shadow-lift);
}
```

Replace with:

```css
.nb-rename-dialog {
  width: min(390px, 100%);
  max-height: calc(100dvh - 48px);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px;
  border: 1px solid var(--nb-line);
  border-radius: 22px;
  background: var(--nb-paper);
  box-shadow: var(--nb-shadow-lift);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/newbro/ui/src/styles/app.css
git commit -m "fix(ui): bound rename bro dialog to viewport height"
```

---

### Task 4: Verify build, tests, and manual layout

**Files:** none (verification only)

- [ ] **Step 1: Build + typecheck**

Run: `cd src/newbro/ui && npm run build`
Expected: build succeeds, `tsc --noEmit` reports no errors.

- [ ] **Step 2: Unit tests**

Run: `cd src/newbro/ui && npm run test`
Expected: PASS. The existing tests that assert `bro-setup-done` /
`bro-setup-create-node` presence remain green (CSS-only change).

- [ ] **Step 3: Manual short-window check**

Run: `cd src/newbro/ui && npm run dev`, then in the browser shrink the window height
(e.g. ~500px) and open each dialog:
- Set up / Reconnect bro (`CreateConnectSheet`)
- Edit/Rename bro (`RenameBroDialog`)
- Workspace picker (`WorkspacePickerDialog`)

Expected: in every dialog the bottom action button (Done / Create / Save / confirm)
stays visible and the body scrolls to reach the rest of the content.

---

## Self-Review Notes

- **Spec coverage:** Task 2 → create/connect desktop grid (spec change 1); Task 1 →
  base body scroll (spec change 2); Task 3 → rename dialog (spec change 3); workspace
  dialog unchanged (spec change 4); Task 4 → spec testing/verification section. All
  covered.
- **Placeholder scan:** none — every step has exact paths, exact CSS, and exact commands.
- **Type consistency:** N/A (CSS-only; no new symbols).
