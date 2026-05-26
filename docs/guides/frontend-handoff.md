# Frontend Handoff

This document records the current handoff state for `src/newbro/ui/` after the
active shell was refactored toward the design prototype in `design/` while
keeping the Newbro runtime clients wired.

## Current Product State

The root route now renders a design-backed `Newbro` workspace shell.

Current visible structure:

- compact top header with session-aware route navigation, account, and logout
- top voice summary bar with the existing connector-backed session controls
- runtime Bro card grid sourced from `personas`, `tasks`, and `executor_nodes`
- explicit empty workspace state when the session has no Bros
- Bro Detail with local-node setup gate, disconnected-node warning, Draft/STT,
  send, and hold-to-talk controls
- mobile Walkie route sourced from the same runtime Bro card models

## Runtime Relationship

The shell remains one-session-at-a-time and protocol-first.

Current behavior:

- the app resumes the shell session from `?sid=...` on load when available,
  otherwise it creates a fresh shell session
- it writes the active session id back to the URL as `sid`
- if that `sid` cannot be resumed, it opens a fresh session, replaces the URL,
  and shows a non-blocking warning
- it fetches that session snapshot for personas
- if `personas` exist, it maps them into `Bro` cards
- if not, it renders the empty workspace card rather than seeded active data
- the root `Home` route stays the workspace even when a default Bro exists;
  Bro Detail opens only from a Bro card or `/bros/:broId`
- pressing `Start` prepares and activates a gateway-backed voice session
- the connector attaches that voice session to the existing shell
  `synapse_session_id`
- `Interaction memory` hydrates from Newbro durable conversation history on
  open and then continues from Newbro user-message and assistant stream events
- pressing `Stop` tears the voice session down without changing the shell
- the stopped transcript remains visible until the next live session replaces it
- left-sidebar route navigation preserves the active `sid`

The current root page does **not** expose:

- the text composer
- the previous workbench/task detail panes
- the websocket-backed conversation shell
- right-side debug or task-control surfaces

## Important Files

- `src/newbro/ui/src/App.tsx`
- `src/newbro/ui/src/components/newbro/*`
- `src/newbro/ui/src/__tests__/App.test.tsx`
- `src/newbro/ui/src/routes/__root.tsx`

## Verified Commands

```bash
cd src/newbro/ui
bun run test
bun run build
```

These should pass from the current state.

## Visual QA Evidence

The current design refactor was checked against the design screenshots in
`design/screenshots/` using desktop captures at `1440x900` and mobile captures
at `390x820`.

| Required state | Design reference | Current evidence |
| --- | --- | --- |
| Desktop sign-in / invitation | `design/screenshots/onboarding-overview.png`, `design/screenshots/onboarding-right.png` | `/tmp/newbro-live-signin-desktop-current.png` |
| Mobile sign-in / invitation | `design/screenshots/onboarding-overview.png`, `design/screenshots/onboarding-right.png` | `/tmp/newbro-live-signin-mobile-current.png` |
| Desktop empty workspace | `design/screenshots/firsthome-sheet-closed.png`, `design/screenshots/recheck.png` | `/tmp/newbro-live-empty-desktop-current.png` |
| Mobile empty workspace | `design/screenshots/firsthome-sheet-closed.png`, `design/screenshots/recheck.png` | `/tmp/newbro-live-empty-mobile-current.png` |
| Desktop create/connect Bro | `design/screenshots/recheck-hq.png`, `design/screenshots/recheck.png` | `/tmp/newbro-live-create-sheet-desktop-current.png` |
| Mobile create/connect Bro | `design/screenshots/recheck-hq.png`, `design/screenshots/recheck.png` | `/tmp/newbro-live-create-sheet-mobile-current.png` |
| Desktop home workspace | `design/screenshots/01-canvas.png`, `design/screenshots/hero-only.png`, `design/screenshots/hero-tight.png`, `design/screenshots/hero-zoom.png` | `/tmp/newbro-live-home-desktop-current.png` |
| Mobile home workspace | `design/screenshots/01-canvas.png`, `design/screenshots/hero-only.png`, `design/screenshots/hero-tight.png`, `design/screenshots/hero-zoom.png` | `/tmp/newbro-live-home-mobile-current.png` |
| Desktop active Bro detail / thread | `design/screenshots/dt-detail-current.png`, `design/screenshots/02-stage-focus.png` | `/tmp/newbro-live-detail-connected-desktop-current.png` |
| Mobile active Bro detail / thread | `design/screenshots/dt-detail-current.png`, `design/screenshots/02-stage-focus.png` | `/tmp/newbro-live-detail-connected-mobile-current.png` |
| Desktop offline / send blocked | `design/screenshots/dt-detail-current.png` | `/tmp/newbro-live-offline-send-blocked-desktop-current.png` |
| Mobile offline / send blocked | `design/screenshots/dt-detail-current.png` | `/tmp/newbro-live-offline-send-blocked-mobile-current.png` |

Known intentional deltas:

- The implementation is the production app viewport, not the design canvas or
  iOS device frame. Outer bezels, status bars, and artboard chrome are not
  duplicated.
- Some screenshot references are prototype overview/canvas variants, including
  stage, hero, and recheck frames. The production UI maps their layout language
  to real runtime surfaces instead of recreating the prototype carousel or
  static artboard exactly.
- App typography keeps `letter-spacing: 0` to satisfy the frontend UI
  constraint against negative or viewport-scaled text, so it differs from some
  prototype tracking.
- Sign-in uses the prototype's segmented invitation-code idea but supports
  real longer invite codes such as `open-sesame` by shrinking cells on mobile.
- Create/connect uses the real executor-node and persona APIs and shows the
  issued `newbro executor run ...` command instead of the static prototype
  command copy.
- Counts, names, node status, draft content, and warnings reflect live runtime
  snapshots rather than the prototype's fixed sample data.

## Next Likely Directions

If work continues on this shell, choose one direction explicitly before
implementing:

1. polish the current voice-transcript shell further
2. add more Newbro runtime surfaces into this layout deliberately
3. expose the older runtime shell on a secondary route

Do not mix those directions casually; the UI contract stays cleaner if one is
chosen first.

## Constraints

- Keep backend and protocol contracts unchanged unless the task explicitly
  requires runtime changes.
- Preserve the componentized structure under `src/components/newbro/`.
- Keep browser-local voice toolkit transcript separate from the adopted
  interaction-memory contract; the left pane now follows Newbro conversation
  state instead of Agora transcript turns.
