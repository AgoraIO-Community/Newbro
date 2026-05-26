<goal>
Recreate the active Newbro frontend as new artboard-first UI pages matching the exact states represented in `design/Voice Interaction.html`, then wire existing runtime functionality into those pages. Keep only artboarded UI states active, remove or fold away non-artboard pages, and preserve runtime wiring required by the remaining artboarded flows.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `docs/README.md`
- Stable frontend/runtime docs under `docs/architecture/`, `docs/protocol/`, and `docs/guides/` that describe sessions, onboarding, executor nodes, draft-to-execute, and frontend contracts. Treat stable docs as authoritative over RFCs.

Design source of truth:
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

Current active frontend:
- `src/newbro/ui/package.json`
- `src/newbro/ui/src/NewbroShell.tsx`
- `src/newbro/ui/src/App.tsx`
- `src/newbro/ui/src/router.tsx`
- `src/newbro/ui/src/styles/app.css`
- `src/newbro/ui/src/styles/`
- `src/newbro/ui/src/components/newbro/`
- `src/newbro/ui/src/components/newbro/mobile/`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/lib/connector-client.ts`
- `src/newbro/ui/src/lib/voice-runtime.ts`
- `src/newbro/ui/src/types.ts`
- `src/newbro/ui/src/__tests__/`

Use these current frontend files primarily as runtime wiring references, data-shape references, and regression-test anchors. Do not treat the existing visual/page structure as the implementation base unless a small helper is already design-compatible.

Required artboard state matrix:
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

Useful discovery commands:
- `rg --files design src/newbro/ui/src | sort`
- `rg -n "DCArtboard|dt-home|dt-thread|dt-signin|dt-empty-home|dt-create-bro|dt-bro-offline|signin|empty-home|create-bro|bro-offline|HomeVariant|ThreadsVariant|HomeDesktop|BroDetailActiveDesktop|SignInDesktop|FirstRunHomeDesktop|CreateBroDesktop|BroDetailOfflineDesktop" design`
- `rg -n "PageId|activePage|BrosPage|NodesPage|Settings|NotFound|Catch|ShellLoading|ShellApiError|MobileWalkie|BroDetail|HomeShell|signup|createExecutorNode|revealExecutorNodeConnectCommand|setVoiceTarget|sendSocket" src/newbro/ui/src`
</context>

<constraints>
- The design prototype is the visual source of truth. Recreate the app as new artboard-first pages/components from the design, then wire runtime functionality into those pages.
- Do not incrementally tweak the current pages into shape. Existing components may be reused only when they already fit the artboard architecture or are pure wiring/helpers without visual constraints.
- Port or faithfully reuse design tokens, CSS, assets, component structure, and interaction states from `design/` before inventing new visual patterns.
- Only directly artboarded UI states should remain active. Remove, hide, or fold non-artboard UI into artboarded flows.
- Removable UI includes standalone Bros management, standalone Nodes management, standalone Settings/preferences, node credential/enrollment pages beyond create/connect, custom not-found/catch-boundary product screens, custom shell loading/API error product screens, and any non-artboard modal/toast/page.
- No custom fallback UI remains. Loading, API error, missing route, catch-boundary, and failed runtime states must be removed, hidden, allowed to fail plainly, or expressed through an existing artboarded state; do not create or keep a separate fallback screen.
- Preserve runtime wiring needed by artboarded flows: auth/signup/logout, current user bootstrap, `?sid` resume, session snapshots, websocket updates, personas, executor node creation/binding, credential reveal/copy inside create/connect, Bro detail, conversation/thread display, voice connector prepare/activate/stop, STT/draft flow, message/draft send, voice target cleanup, and offline send blocking.
- Do not replace runtime data with static prototype data except artboarded empty/offline states that cannot mask broken API wiring.
- Keep Communication Brain and Execution Brain boundaries intact. UI may render state and call typed clients; it must not invent semantic transcript rules, dispatch raw speech directly to executors, or bypass draft/session contracts.
- Keep transport thin. Browser UI and connector clients translate typed state and actions; they do not own backend policy.
- Do not broaden scope into backend features, new authentication systems, executor orchestration changes, or marketing pages.
- Update stable docs and `docs/memories.md` only if the implementation adopts meaningful frontend/runtime behavior changes beyond visual restructuring.
</constraints>

<done_when>
- Every required artboard state in the matrix is implemented in `src/newbro/ui`.
- UI not represented in the artboards is removed, hidden, or folded into an artboarded flow.
- No custom fallback UI remains for loading, API error, not-found, catch-boundary, or non-artboard runtime states.
- Desktop states visually match the corresponding 1440x900 artboards: home workspace, bro detail active session, sign in/invitation, empty workspace, create/connect bro, and bro detail offline/send blocked.
- Mobile states visually match the corresponding 440x920 artboards: sign in/invitation, empty workspace, create/connect bro, bro offline/send blocked, home workspace, and threads/chat.
- Mobile states remain usable at 390x820 with no clipped primary controls, incoherent text overlap, broken scroll, or horizontal page overflow.
- Remaining artboarded flows use existing runtime APIs for auth, sessions, personas, executor nodes, connect command reveal/copy, Bro detail, voice connector lifecycle, STT/draft, message/draft send, and offline blocking.
- Empty workspace uses the artboarded empty state instead of fake active data.
- Disconnected usable nodes show the artboarded offline/send-blocked state and block talk/send actions without hiding the bro detail state.
- `cd src/newbro/ui && bun run test` passes.
- `cd src/newbro/ui && bun run build` passes.
- Browser/manual visual QA captures screenshots for every required artboard state at the required desktop/mobile viewport sizes.
- Any remaining pixel deltas are documented with concrete reasons and follow-up paths; do not claim pixel-perfect completion for undocumented visual drift.
</done_when>

<workflow>
1. Check git status and preserve unrelated user changes.
2. Read `SPEC.md`, `AGENTS.md`, and stable docs relevant to frontend/session/onboarding/executor/draft behavior before editing.
3. Inspect the design prototype and current frontend in parallel. Build a file-level checklist mapping each artboard state to new page/component files, and separately map current components only to runtime APIs, data transforms, and edge-case behavior.
4. Render or otherwise visually inspect the design artboards. Use `design/screenshots/` where available and capture fresh references if needed.
5. Audit current routes/pages and remove or fold non-artboard product UI from navigation and reachable flows.
6. Create a new artboard-first UI layer: shared visual foundation, tokens, body/page styling, shell dimensions, top bars, mobile bars, paper surfaces, status chips, buttons, command blocks, character/avatar assets, and responsive utilities.
7. Recreate desktop artboard pages first with design-faithful component structure: home, bro detail active, sign in, empty workspace, create/connect, offline/send blocked.
8. Recreate mobile artboard pages first with design-faithful component structure: sign in, empty workspace, create/connect, offline/send blocked, home, threads/chat.
9. Wire runtime data and actions into the recreated pages using existing client functions. Avoid mock data except artboarded empty/offline states.
10. Add or update focused tests for key regressions: signup/auth, session resume, runtime bro cards/home state, create/connect, bro detail voice actions, draft/message send, and offline blocking.
11. Run focused tests during development, then full frontend test and build commands.
12. Perform browser screenshot QA for every matrix row at 1440x900 desktop, 440x920 mobile, and 390x820 mobile spot-checks. Iterate until visual drift is fixed or explicitly documented.
13. Update stable docs and `docs/memories.md` only if adopted runtime/frontend behavior changes meaningfully.
14. Review final diff for unrelated churn, dead non-artboard routes, leaked mock data, broken runtime calls, stale docs, and insufficient visual evidence.
</workflow>

<verification_loop>
Focused inspection:
- `rg --files design src/newbro/ui/src | sort`
- `rg -n "DCArtboard|dt-home|dt-thread|dt-signin|dt-empty-home|dt-create-bro|dt-bro-offline|HomeDesktop|BroDetailActiveDesktop|SignInDesktop|FirstRunHomeDesktop|CreateBroDesktop|BroDetailOfflineDesktop|HomeVariant|ThreadsVariant|SignInVariant|CreateBroVariant|ThreadsOfflineVariant" design`
- `rg -n "BrosPage|NodesPage|Settings|NotFound|Catch|ShellLoading|ShellApiError|mock|sample|bootstrapPublicUser|signupPublicUser|getSessionSnapshot|openSessionStream|sendSocketMessage|sendSocketDraftAsrTurn|createExecutorNode|revealExecutorNodeConnectCommand|setVoiceTarget|clearVoiceTarget|useVoiceSession" src/newbro/ui/src`
- `rg -n "fallback|loading|error panel|catch boundary|not found|NotFound|ShellLoading|ShellApiError|DefaultCatchBoundary" src/newbro/ui/src`

Frontend verification:
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Manual/browser visual QA:
- Start services if needed with `./newbro dev`.
- Capture implementation screenshots for each desktop artboard state at 1440x900.
- Capture implementation screenshots for each mobile artboard state at 440x920.
- Spot-check mobile at 390x820.
- Compare against `design/screenshots/*` and/or freshly rendered design artboards from `design/Voice Interaction.html`.

Functional smoke checks:
- Sign in with an invitation code.
- Confirm current user bootstrap and logout still work.
- Confirm session opens, writes or preserves `?sid`, and resumes from `?sid`.
- Confirm empty workspace renders the design empty state when no bros exist.
- Confirm create/connect creates or binds runtime persona/executor-node state and exposes connect command copy only through the artboarded flow.
- Confirm home workspace renders runtime bros and state.
- Confirm bro detail/thread renders runtime conversation and draft state.
- Confirm voice start/stop uses existing connector flow and cleans up voice target state.
- Confirm STT/draft and message send actions call existing client paths.
- Confirm disconnected usable nodes show offline/send-blocked state and prevent talk/send actions.

If a check cannot run, document why, what was run instead, and the residual risk.
</verification_loop>

<execution_rules>
- Check git status before edits.
- Preserve unrelated user changes.
- Prefer `rg` over `grep` when available.
- Use `apply_patch` for manual file edits.
- Read context files before implementation.
- Batch independent file reads in parallel when available.
- Run focused tests before broad tests.
- Do not paper over failures.
- Do not widen scope.
- Keep the final answer concise.
- Follow repo guardrails from `AGENTS.md`: read stable docs first, preserve Communication Brain and Execution Brain boundaries, avoid fake semantic rules, keep transport thin, diagnose from real state, protect dispatch, test the failure mode, verify activation, and update memory deliberately.
</execution_rules>

<output_contract>
Final output must include:
- Completed artboard state matrix with each state marked complete or documented with reason.
- Summary of removed/hidden/folded non-artboard UI.
- Summary of the new artboard-first UI layer and the design sources, tokens, CSS, assets, and components ported or reused.
- Summary of runtime wiring preserved for auth, sessions, personas, nodes, create/connect, bro detail, voice connector, STT/draft, message/draft send, and offline blocking.
- Key files changed, grouped by UI components/styles/assets, runtime wiring, tests, and docs.
- Verification commands run and outcomes.
- Screenshot QA evidence paths and viewport sizes.
- Any skipped checks, documented pixel deltas, or residual risks.
- Clear completion signal only when every `done_when` item is satisfied or explicitly documented.
</output_contract>
