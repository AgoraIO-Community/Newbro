# Onboarding dialog footer visibility on short windows

Date: 2026-06-07
Status: Approved design

## Problem

The newbro creation/updating dialog (`CreateConnectSheet`, "Set up / Reconnect bro")
can hide its bottom action button when the window is not tall enough. The footer holds
the primary **Done** / **Create and connect** button (`data-testid="bro-setup-done"` /
`bro-setup-create-node`). When the viewport is short, that button becomes clipped and
unreachable.

### Root cause

The sheet is a CSS grid (`.ob-sheet`) whose rows are header / body / footer. The base
and mobile rule (`src/newbro/ui/src/styles/variants-onboarding.css`) is:

```css
.ob-sheet { grid-template-rows: auto auto 1fr auto; overflow: hidden; }
```

Here the body is `1fr`, so it absorbs overflow and the footer stays pinned.

The desktop override (`src/newbro/ui/src/styles/app.css`, `@media (min-width: 768px)`) is:

```css
.nb-first-run-sheet-frame .ob-sheet { grid-template-rows: auto auto auto; max-height: min(760px, calc(100dvh - 64px)); }
```

All three rows size to content. When content exceeds the clamped `max-height`, the sheet
(`overflow: hidden`) clips the last `auto` row — the footer — so the Done button
disappears below the hidden boundary. The body never receives a bounded, scrollable
height because its track is `auto` instead of fractional.

## Scope

All onboarding sheets that share the `.ob-sheet` / sheet-frame styling:

| Dialog | Component | Current short-window behavior |
| --- | --- | --- |
| Create/Connect ("Set up / Reconnect bro") | `CreateConnectSheet` | Broken — desktop grid `auto auto auto` clips the footer |
| Workspace picker | `WorkspacePickerDialog` | Already safe — `auto minmax(0,1fr) auto` + inner `.nb-workspace-scroll` |
| Rename/Edit bro | `RenameBroDialog` | At risk — flex card with no `max-height`/scroll; footer can fall off-screen |

## Approach

Pin the header and footer; make the body the scrollable region. This reuses the pattern
already proven by `WorkspacePickerDialog`, directly delivers "Done is always visible," and
requires no JS changes.

Rejected alternatives:
- Scroll the whole sheet — footer still requires scrolling to reach, only partially solves the report.
- Responsive shrink (collapse columns / shrink padding at short heights) — does not address the root cause; tall content can still overflow.

## Changes

1. **`CreateConnectSheet` desktop grid** — `src/newbro/ui/src/styles/app.css`,
   `@media (min-width: 768px)`, rule `.nb-first-run-sheet-frame .ob-sheet`:
   change `grid-template-rows: auto auto auto` → `auto minmax(0, 1fr) auto`
   (header / body / footer; the handle is `display: none` in this breakpoint).

2. **Base body scroll** — `src/newbro/ui/src/styles/variants-onboarding.css`,
   rule `.ob-sheet-body`: add `min-height: 0;` (it already has `overflow-y: auto`).
   Required so the fractional body track actually scrolls instead of expanding to
   content height; hardens both the mobile (`1fr`) and desktop (`minmax(0,1fr)`) layouts.

3. **`RenameBroDialog`** — `src/newbro/ui/src/styles/app.css`, rule `.nb-rename-dialog`:
   add `max-height: calc(100dvh - 48px)` and `overflow-y: auto`. It is a single-field
   form, so whole-card scroll is sufficient to keep Save/Cancel reachable; no grid
   restructure needed.

4. **No change** to `WorkspacePickerDialog` — already correct (listed for completeness).

## Testing / verification

jsdom (vitest) does not compute layout, so footer *visibility* cannot be asserted in unit
tests. Verification is a manual short-window resize check of all three dialogs, consistent
with the project's manual-verify guidance:

- Open Set up / Reconnect bro, Rename bro, and Workspace picker at a short window height.
- Confirm the bottom action button stays visible and the body scrolls.

Existing tests that assert the presence of `bro-setup-done` / `bro-setup-create-node`
remain green (CSS-only change).
