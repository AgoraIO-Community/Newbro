# One Setup Dialog from Offline Surfaces + CreateConnectSheet Layout — Design

Date: 2026-06-01
Status: Approved (design)

## Goal

Make the terse offline/needs-connect entry points lead to the single app-first
setup dialog instead of dead-ending in status text, fix one wrong-state copy in
the offline banner, and clean up the cramped text layout in the setup dialog.

Builds on `2026-06-01-connect-surfaces-app-first-copy-design.md` (already
implemented): the `CreateConnectSheet` dialog and `OfflineBanner` are now
app-first, but two entry points (home bro card, detail header pill) don't reach
the dialog, and the dialog's STEP 3 text spacing is uneven.

## Current state (`src/newbro/ui/src/ArtboardShell.tsx`)

- **`CreateConnectSheet`** — full-screen overlay (`nb-first-run-sheet-layer`,
  `role="dialog"`). Accepts `bro?` and `mobile?`. Already rendered: as an overlay
  for new-bro at home (`addOpen`), and inline for an existing bro in the
  needs-connect branch of `DesktopDetail` (line ~3588) / `MobileDetail`
  (line ~4242). Header reads "Set up your first bro" regardless of `bro`.
- **Home bro card** (`DesktopBroCard`, and the mobile card): offline/never
  shows only a meta label via `homeBroLast` → "computer offline" / "needs a
  computer". The card already supports non-navigating actions via
  `data-home-card-action` + `clickedInsideHomeCardAction`.
- **Detail header** (`DesktopFrame` header): a status pill
  `paused · computer offline` (`detailPaused`). Not actionable.
- **`OfflineBanner`** renders for `usable_disconnected` *and* `never_connected`
  nodes (`offline = … ? node : null`, with `needsConnect` excluding
  `never_connected`). Its copy assumes a prior connection ("{node} is offline",
  "until this computer reconnects", "Open the Newbro app on {node} — it
  reconnects on its own"), which is wrong for a never-connected node.
- **STEP 3 layout:** `.ob-fieldset` is `display:flex; flex-direction:column;
  gap:10px`, but `.ob-connect-guide` (margin `0 0 8px`), `.ob-connect-guide-2`
  (`margin-top:10px`), `.ob-download` (`margin:2px 0 4px`), `.ob-terminal-toggle`
  (`margin-top:6px`), and `.ob-terminal-fallback` (`margin-top:8px`) add margins
  that compound with the gap, so vertical rhythm is uneven. The coral
  `.ob-terminal-toggle` link sits directly above the coral `.ob-connect-meta`
  links ("Get a fresh link", "Walk me through it"), so the two link rows read as
  one cluttered block.

## Design

### A. Reusable on-demand setup dialog

`CreateConnectSheet` already is a full-screen overlay and already handles an
existing `bro`. Make it openable on demand from any surface and label it for the
target:

- Adapt the header (`ob-sheet-h` + `ob-sheet-intro`) when `bro` is provided:
  - never-connected (no node bound): "Set up {bro}"
  - otherwise (offline/reconnect): "Reconnect {bro}"
  - no `bro` (new): unchanged "Set up your first bro".
- No change to the command-generation logic; it already produces the connect
  command for the given bro.

### B. Home bro card → opens the dialog

- Add an `onSetup?: (bro: BroCardModel) => void` prop to the home card
  components (`DesktopBroCard` and the mobile card). When the card's state is
  offline or never-connected, render a small action button inside the card:
  - **"Reconnect"** when the bro has a node (`bro.nodeName`),
  - **"Set up"** when it has none.
  - The button carries `data-home-card-action="setup"` so
    `clickedInsideHomeCardAction` suppresses card navigation, and its `onClick`
    calls `onSetup(bro)`.
- The home container (`Home` / `MobileHome`) holds a `setupBro:
  BroCardModel | null` state, passes `onSetup={setSetupBro}` to the cards, and
  renders `<CreateConnectSheet bro={setupBro} mobile? onClose={() => setSetupBro(null)} … />`
  when `setupBro` is set (mobile passes `mobile`).

### C. Detail header pill → opens the dialog

- `DesktopFrame` gains an optional `onConnect?: () => void`. When present and the
  bro is paused, render the `paused · computer offline` pill as a `<button>` (or
  add a small "Set up" button beside it) that calls `onConnect()`.
- `DesktopDetail` holds a `connectOpen` state, passes `onConnect={() =>
  setConnectOpen(true)}` to `DesktopFrame`, and renders `<CreateConnectSheet
  bro={bro} onClose={() => setConnectOpen(false)} … />` as an overlay when
  `connectOpen` (independent of the existing needs-connect inline rendering,
  which stays). The mobile detail keeps its existing flow; if its header has an
  equivalent pill, wire it the same way, otherwise the `OfflineBanner` button
  (below) is its entry point.

### D. `OfflineBanner` → thin banner that opens the dialog

The banner becomes a short status line + a button; all command/terminal detail
lives in the dialog (the single source). Remove the inline `OfflineCommandLine`
command box, the reinstall disclosure (`showReinstall`), and the
`useCopyNodeConnectCommand` usage from `OfflineBanner`.

- Branch the copy on whether the node has ever connected (pass a
  `neverConnected` boolean from the caller, which already knows `nodeState.kind`):
  - **never-connected:** title "{node} isn't connected yet"; body "Set it up in
    the Newbro app — {bro} can take messages once it connects."
  - **disconnected:** title "{node} is offline"; body "{bro} can't take new
    messages until this computer reconnects. Your draft is saved — the last turn
    retries on its own." Keep the "Auto-retrying" pip (desktop).
- Add a primary button — **"Set up"** (never-connected) / **"Reconnect"**
  (disconnected) — that calls a passed `onConnect`, opening the same setup dialog
  as the card and pill. Both desktop and mobile branches use this thin form.

### E. `CreateConnectSheet` STEP 3 layout cleanup

Normalize the vertical rhythm and de-clutter the secondary links (CSS-only where
possible, in `variants-onboarding.css`):

- Remove the compounding margins so the `.ob-fieldset` `gap` is the single
  source of spacing: zero `.ob-connect-guide` margin (keep its `padding`),
  drop `.ob-connect-guide-2`'s `margin-top`, and remove the `margin` on
  `.ob-download`, `.ob-terminal-toggle`, `.ob-terminal-fallback`. If a slightly
  tighter sub-group is wanted for the install-guide→command pairing, wrap each
  guide+box in a small flex column with a 6px gap rather than per-element
  margins.
- **Remove** the non-functional `.ob-connect-meta` block entirely (the
  "Get a fresh link" / "Walk me through it" placeholder links). This deletes one
  of the two clashing link rows, so the terminal toggle no longer competes with
  them.
- Render the remaining **"Not on a Mac? Connect from a terminal"** toggle as a
  muted disclosure (reuse the offline `dt-offline-disclose` chevron style —
  small, ink-muted, rotating chevron) instead of an `ob-link` coral link, so it
  reads as a secondary affordance.
- Keep the command-box markup/test hooks stable (the aria-labels and the
  disclosure behavior); this is spacing + the toggle's visual treatment + the
  meta-row removal, not new command structure.
- **Visual verification:** because this is layout, verify the rendered STEP 3
  dialog (run the UI and open the create/reconnect dialog, or have the reviewer
  confirm) before considering it done; iterate on spacing values against the
  real render rather than guessing pixel-perfect.

## Testing

- Reuse `App.test.tsx`. Note the existing offline test asserts the in-banner
  command controls (`bro-node-copy-run-only-command`, `bro-node-copy-command`,
  "Reinstall from a terminal"); since the banner becomes thin, **rewrite** that
  test to assert the new flow instead: the banner shows the status + a
  "Reconnect"/"Set up" button, clicking it opens the dialog, and the
  connect-command copy now lives in the dialog.
- Add/adjust:
  - Clicking the home card's "Reconnect"/"Set up" button opens the dialog
    (assert the dialog heading "Reconnect {bro}" / "Set up {bro}" appears and the
    card did not navigate).
  - The detail header pill button opens the dialog.
  - `OfflineBanner` for a never-connected node shows the "isn't connected
    yet"/"Set up" copy, not "is offline".
- The command-builder tests (`lib/session-client.test.ts`) stay unchanged.
- Run the full UI suite (`npm test` in `src/newbro/ui`).

## Out of scope (YAGNI)

- A `newbro://` deep link / one-click handoff.
- Making the placeholder "Get a fresh link" / "Walk me through it" links
  functional (left as-is; only their layout is tidied).
- Any change to command-builder logic or the connect-command format.
- Reworking the needs-connect inline rendering in detail (kept as today; we only
  add the on-demand overlay path).
