# Newbro UI Artboard Realignment Spec

## Goal

Recreate the active Newbro frontend as new artboard-first UI pages based on `design/Voice Interaction.html` and its linked design assets, then wire the existing runtime functionality into those new pages. The product boundary is strict: only UI states directly represented by the artboards should remain active. UI that is not on an artboard should be removed, hidden, or folded into an artboarded flow.

## Source Of Truth

The visual source of truth is:

- `design/Voice Interaction.html`
- `design/app.jsx`
- `design/tokens.css`
- `design/variants-desktop.jsx`
- `design/variants-desktop.css`
- `design/variants-mobile.jsx`
- `design/variants-mobile.css`
- `design/variants-onboarding.jsx`
- `design/variants-onboarding.css`
- `design/variants-channel-mobile.jsx`
- `design/variants-channel-mobile.css`
- `design/bro-characters.jsx`
- `design/bro-characters.css`
- `design/assets/`
- `design/screenshots/`

## In Scope

The implemented app should keep and align only these directly artboarded states:

- Desktop home workspace: `dt-home`
- Desktop bro detail active session: `dt-thread`
- Desktop sign in / invitation: `dt-signin`
- Desktop empty workspace: `dt-empty-home`
- Desktop create/connect bro: `dt-create-bro`
- Desktop bro detail offline/send blocked: `dt-bro-offline`
- Mobile sign in / invitation: `signin`
- Mobile empty workspace: `empty-home`
- Mobile create/connect bro: `create-bro`
- Mobile bro offline/send blocked: `bro-offline`
- Mobile home workspace: `home`
- Mobile threads/chat: `threads`

## Out Of Scope / Removable UI

The following current UI is not directly on the artboards and should be removed, made unreachable, or folded into an artboarded flow:

- Standalone Bros management page
- Standalone Nodes management page
- Standalone Settings/preferences page
- Node credentials/enrollment pages beyond the create/connect artboard flow
- Not found and catch-boundary custom product screens
- Shell loading/error screens
- Any custom fallback UI not represented in the artboards
- Any modal, toast, page, or route state not represented in the artboards

Backend-required functionality may remain available only when it is needed by an artboarded flow. For example, creating a persona, creating/binding an executor node, revealing/copying a connect command, voice actions, session resume, and offline blocking should stay wired through the artboarded create/connect, home, and bro detail states.

## User-Visible Behavior

Desktop states should visually match the corresponding 1440x900 artboards. Mobile states should visually match the corresponding 440x920 artboards and remain usable at 390x820.

Dynamic runtime data may differ from the static prototype, but the implemented shell, layout, spacing, typography, colors, surfaces, cards, buttons, voice controls, status chips, mobile sheets, avatar/character treatments, and empty/offline states should match the design.

## Architecture Constraints

- Treat `src/newbro/ui/` as the active frontend.
- Implementation should create a new artboard-first UI surface instead of incrementally tweaking the current pages. Existing components may be read for runtime wiring, data shape, edge cases, and tests, but should not constrain the new visual/component architecture.
- Prefer porting/reusing design tokens, CSS, assets, and component structure from `design/` over inventing a parallel visual system.
- Wire runtime behavior into the new pages after the page structure is recreated from the design.
- Preserve runtime wiring required by artboarded flows: auth/signup/logout, session bootstrap and `?sid` resume, persona and executor node creation/binding, connect command reveal/copy, Bro detail, conversation/thread display, voice connector prepare/activate/stop, STT/draft flow, message/draft send, and offline send blocking.
- Do not replace live runtime state with static design data except artboarded empty/offline states that cannot mask broken API wiring.
- Do not keep custom fallback UI. If an error, loading, missing route, or failed runtime state is not represented in the artboards, remove that product UI or route it into an artboarded state; do not design a separate fallback screen.
- Keep Communication Brain and Execution Brain boundaries intact. The UI renders state and invokes typed client APIs; it must not invent transcript keyword rules, backend policy, or dispatch shortcuts.
- Do not broaden scope into backend features, new auth systems, executor orchestration changes, or marketing pages.

## Edge Cases

- No signed-in user should show the artboarded invitation/sign-in state.
- Empty workspace should use the artboarded empty state instead of fake active data.
- Loading, error, and not-found cases should not introduce separate visible fallback UI unless they are expressed through an existing artboarded state.
- A created or connected bro should appear through the artboarded home and detail states.
- A disconnected but usable node should keep the bro detail visible, show the artboarded offline/send-blocked state, and block talk/send actions.
- Long names, prompts, commands, and transcript text should wrap or scroll without clipping primary controls.
- Desktop and mobile navigation should preserve the active session id where session routing is still required.

## Verification

Required commands:

- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Required visual checks:

- Capture desktop screenshots at 1440x900 for every desktop artboarded state.
- Capture mobile screenshots at 440x920 for every mobile artboarded state.
- Spot-check mobile at 390x820.
- Compare implementation screenshots against `design/screenshots/*` and/or freshly rendered design artboards.

Required functional smoke checks:

- Sign in with an invitation code.
- Resume a session from `?sid`.
- Show empty workspace when no bros exist.
- Create/connect a bro through the artboarded flow.
- Show home workspace with runtime bros.
- Open active bro detail/thread.
- Start/stop voice through the existing connector flow.
- Send draft/message through existing client paths.
- Show offline/send-blocked state for disconnected usable nodes.

## Done When

- Every in-scope artboarded state is implemented in the active frontend.
- UI not represented in the artboards is removed, hidden, or folded into an artboarded flow.
- No custom fallback UI remains for loading, API error, not-found, catch-boundary, or non-artboard runtime states.
- Desktop states visually match their 1440x900 artboards.
- Mobile states visually match their 440x920 artboards and remain usable at 390x820.
- Runtime actions needed by the remaining artboarded flows remain wired to existing APIs.
- No page has horizontal overflow, incoherent overlap, clipped primary controls, or unreadable command/thread text at the checked viewports.
- `cd src/newbro/ui && bun run test` passes.
- `cd src/newbro/ui && bun run build` passes.
- Screenshot QA evidence is produced for the artboarded state matrix.
- Any remaining pixel deltas are documented with a concrete reason and follow-up path.
