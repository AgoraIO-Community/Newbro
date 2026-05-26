# Newbro Desktop And Mobile Design Alignment Spec

## Goal

Make the active Newbro UI follow `design/Voice Interaction.html` closely for the core runtime surfaces: Home, Create & Connect a Bro, and Bro Detail. The goal covers both desktop and mobile, with desktop treated as the first and strictest acceptance gate because the current desktop implementation is visibly farthest from the checked-in design.

This is an alignment and verification goal, not a product rewrite. Keep the runtime behavior that already works, and reshape the UI around the design prototype.

## Source Of Truth

Primary design source:

- `design/Voice Interaction.html`
- `design/app.jsx`
- `design/tokens.css`
- `design/variants-desktop.jsx`
- `design/variants-desktop.css`
- `design/variants-mobile.jsx`
- `design/variants-mobile.css`
- `design/variants-channel-mobile.jsx`
- `design/variants-channel-mobile.css`
- `design/variants-onboarding.jsx`
- `design/variants-onboarding.css`
- `design/bro-characters.jsx`
- `design/bro-characters.css`
- `design/assets/`
- `design/screenshots/`

Current implementation to align:

- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/styles/variants-desktop.css`
- `src/newbro/ui/src/styles/variants-mobile.css`
- `src/newbro/ui/src/styles/variants-onboarding.css`
- `src/newbro/ui/src/styles/app.css`
- `src/newbro/ui/src/components/newbro/`
- `src/newbro/ui/src/NewbroShell.tsx`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/lib/connector-client.ts`
- `src/newbro/ui/src/lib/voice-runtime.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`

## In Scope

Desktop must be aligned first:

- Empty Home: `FirstRunHomeDesktop` / `dt-empty-home`
- Populated Home: `HomeDesktop` / `dt-home`
- Create & Connect modal: `CreateBroModal` and `CreateBroDesktop` / `dt-create-bro`
- Bro Detail active thread: `BroDetailActiveDesktop` / `dt-thread`
- Bro Detail offline/send blocked, if current runtime state reaches it: `BroDetailOfflineDesktop` / `dt-bro-offline`

Mobile must be aligned after desktop is stable:

- Mobile empty Home
- Mobile populated Home
- Mobile Create & Connect
- Mobile Bro Detail / threads
- Mobile Bro offline/send blocked, if current runtime state reaches it

The sign-in/invitation UI may be adjusted only if shared tokens, shell styling, or viewport behavior make it visibly inconsistent with the same design source. It is not the main acceptance target for this goal.

## Non-Goals

- Do not redesign the product beyond the checked-in design prototype.
- Do not remove functional runtime routes solely because they are not part of this alignment pass.
- Do not replace runtime state with static design mock data.
- Do not change backend behavior, auth semantics, executor node semantics, persona creation rules, draft contracts, or voice connector contracts.
- Do not implement new management pages, settings pages, node admin pages, onboarding copy, or marketing screens.
- Do not claim pixel-perfect completion without screenshot evidence.

## User-Visible Behavior

At desktop `1440x900`, the live UI should visually match the design prototype for the desktop target states. The most important desktop fixes are expected around global shell placement, page padding, header height, modal size/position, shadows, card spacing, activity rail placement, thread pane sizing, and composer position.

At mobile `440x920`, the live UI should match the corresponding mobile design states. At `390x820`, the same states must remain usable without clipped primary controls, broken scroll, horizontal overflow, or incoherent overlap.

Runtime data can differ from the static design content, but layout, visual hierarchy, typography, spacing, borders, shadows, button treatment, command block treatment, avatars, chips, and interaction states should come from the design.

## Implementation Constraints

- Read stable docs before implementation and preserve Newbro runtime boundaries from `AGENTS.md`.
- Use the design files as the visual source of truth. Port or reuse design CSS/class structure where practical.
- Preserve existing runtime wiring for auth bootstrap, `?sid` session handling, session snapshots, websocket updates, personas, executor nodes, create/connect, command copy, Bro Detail, voice start/stop, STT/draft, draft send, and offline blocking.
- Keep the browser UI transport thin. The UI may call typed client APIs and render state; it must not invent business policy or semantic transcript shortcuts.
- Prefer aligning the active `ArtboardShell` and style files over building a second disconnected prototype.
- Use icons from the existing icon system where the active app already uses them; do not introduce hand-drawn replacement icons unless the design asset requires it.
- Preserve mobile behavior while doing desktop work. Desktop-first does not mean mobile regressions are acceptable.

## Edge Cases

- Empty workspace must render the design empty state when there are no runtime personas.
- Create/connect must keep the real executor-node command flow and first-connection gating.
- Completed create/connect state must have a meaningful close/confirm action, not disabled decorative buttons.
- Long node commands must not overflow the modal.
- Long Bro names and task titles must wrap or truncate like the design without resizing fixed controls.
- Offline usable nodes must keep Bro Detail visible, show the offline/send-blocked treatment, and block talk/send.
- Active voice state must not push the desktop thread pane or mobile controls out of frame.
- Mobile browser chrome / small viewport height must not hide the primary create/connect or voice controls.

## Verification

Required commands:

- `cd src/newbro/ui && bun run test src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Required screenshot evidence:

- Desktop design references at `1440x900` for empty Home, populated Home, Create & Connect, Bro Detail active, and Bro Detail offline if implemented.
- Desktop live screenshots at `1440x900` for the same states.
- Desktop live spot checks at `1280x800` and `1024x768` for Home, Create & Connect, and Bro Detail.
- Mobile design references at `440x920` for empty Home, populated Home, Create & Connect, Bro Detail/threads, and offline if implemented.
- Mobile live screenshots at `440x920` for the same states.
- Mobile live spot checks at `390x820` for empty Home, Create & Connect, and Bro Detail.

Suggested artifact naming:

- `/tmp/newbro-design-desktop-empty-home-1440x900.png`
- `/tmp/newbro-live-desktop-empty-home-1440x900.png`
- `/tmp/newbro-design-desktop-create-bro-1440x900.png`
- `/tmp/newbro-live-desktop-create-bro-1440x900.png`
- `/tmp/newbro-design-desktop-home-1440x900.png`
- `/tmp/newbro-live-desktop-home-1440x900.png`
- `/tmp/newbro-design-desktop-detail-1440x900.png`
- `/tmp/newbro-live-desktop-detail-1440x900.png`
- `/tmp/newbro-design-mobile-*.png`
- `/tmp/newbro-live-mobile-*.png`

## Done When

- Desktop empty Home matches the design at `1440x900`.
- Desktop populated Home matches the design at `1440x900`.
- Desktop Create & Connect matches the design at `1440x900`.
- Desktop Bro Detail active matches the design at `1440x900`.
- Desktop Bro Detail offline/send blocked matches the design if that state is reachable in the active runtime.
- Desktop Home, Create & Connect, and Bro Detail have no horizontal overflow, incoherent overlap, or clipped primary controls at `1440x900`, `1280x800`, and `1024x768`.
- Mobile empty Home, populated Home, Create & Connect, and Bro Detail/threads match the design at `440x920`.
- Mobile offline/send blocked matches the design if that state is reachable in the active runtime.
- Mobile target states remain usable at `390x820` with no clipped primary controls, broken scroll, or horizontal overflow.
- Existing runtime behavior still works for empty workspace, create/connect, one Bro creation after first successful connection, connected Bro Home, Bro Detail, voice start/stop, draft/message send, and offline blocking.
- `cd src/newbro/ui && bun run test src/__tests__/App.test.tsx` passes.
- `cd src/newbro/ui && bun run test` passes.
- `cd src/newbro/ui && bun run build` passes.
- Screenshot QA evidence exists for the required state and viewport matrix.
- Any remaining visual deltas are documented with concrete reason and follow-up path.
