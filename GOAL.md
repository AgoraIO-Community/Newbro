<goal>
Align the active Newbro Home, Create & Connect, and Bro Detail UI with `design/Voice Interaction.html` across desktop and mobile. Desktop is the first and strictest gate because it is currently farthest from the design; mobile alignment follows after desktop is stable. Preserve the existing runtime behavior while making the visual structure, spacing, typography, shadows, cards, modal, thread pane, activity rail, composer, and mobile states match the checked-in design.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `docs/README.md`
- Stable frontend/runtime docs under `docs/architecture/`, `docs/protocol/`, and `docs/guides/` that describe public onboarding, executor nodes, frontend contracts, draft-to-execute, and Bro Detail behavior. Stable docs are authoritative over RFCs.

Design source of truth:
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

Current active frontend:
- `src/newbro/ui/package.json`
- `src/newbro/ui/src/ArtboardShell.tsx`
- `src/newbro/ui/src/NewbroShell.tsx`
- `src/newbro/ui/src/App.tsx`
- `src/newbro/ui/src/router.tsx`
- `src/newbro/ui/src/styles/app.css`
- `src/newbro/ui/src/styles/variants-desktop.css`
- `src/newbro/ui/src/styles/variants-mobile.css`
- `src/newbro/ui/src/styles/variants-onboarding.css`
- `src/newbro/ui/src/components/newbro/`
- `src/newbro/ui/src/lib/session-client.ts`
- `src/newbro/ui/src/lib/connector-client.ts`
- `src/newbro/ui/src/lib/voice-runtime.ts`
- `src/newbro/ui/src/types.ts`
- `src/newbro/ui/src/__tests__/App.test.tsx`

Desktop reference components/states:
- `FirstRunHomeDesktop` / `dt-empty-home`
- `HomeDesktop` / `dt-home`
- `CreateBroModal` and `CreateBroDesktop` / `dt-create-bro`
- `BroDetailActiveDesktop` / `dt-thread`
- `BroDetailOfflineDesktop` / `dt-bro-offline` when reachable

Mobile reference states:
- mobile empty Home
- mobile populated Home
- mobile Create & Connect
- mobile Bro Detail / threads
- mobile offline/send blocked when reachable

Useful discovery commands:
- `rg --files design src/newbro/ui/src | sort`
- `rg -n "FirstRunHomeDesktop|HomeDesktop|CreateBroModal|CreateBroDesktop|BroDetailActiveDesktop|BroDetailOfflineDesktop|HomeVariant|ThreadsVariant|CreateBro|offline|empty" design`
- `rg -n "DesktopHome|EmptyWorkspace|CreateConnectSheet|DesktopDetail|MobileHome|MobileDetail|createExecutorNode|revealExecutorNodeConnectCommand|createPersona|setVoiceTarget|sendSocketMessage|sendSocketDraftAsrTurn" src/newbro/ui/src`
</context>

<constraints>
- Desktop alignment is phase one and must be verified before mobile polish is considered complete.
- This is an alignment goal, not a product rewrite. Do not broaden into backend behavior changes, new auth semantics, executor orchestration, new management pages, settings pages, or marketing screens.
- Use `design/Voice Interaction.html` and linked design files as the visual source of truth. Port or reuse design class structure, CSS variables, assets, avatars, spacing, and component anatomy where practical.
- Preserve existing runtime wiring for auth bootstrap, `?sid` session handling, session snapshots, websocket updates, personas, executor nodes, create/connect, connect command copy, first-connection gating, Bro Detail, voice start/stop, STT/draft, draft/message send, voice target cleanup, and offline blocking.
- Do not replace runtime data with static design mock data. Runtime content may differ from design copy, but layout and treatment must match the design.
- Keep Communication Brain and Execution Brain boundaries intact. The UI renders typed state and calls typed clients; it must not invent transcript keyword rules, raw executor dispatch, or backend policy.
- Keep transport thin. Browser UI and connector clients translate typed state/actions; they do not own business rules.
- Preserve mobile behavior while doing desktop work. Desktop-first does not allow mobile regressions.
- Do not claim pixel-perfect completion without screenshot evidence and an explicit delta review.
- Update stable docs and `docs/memories.md` only if adopted behavior changes meaningfully beyond visual alignment.
</constraints>

<done_when>
- Desktop empty Home matches `FirstRunHomeDesktop` at `1440x900`.
- Desktop populated Home matches `HomeDesktop` at `1440x900`.
- Desktop Create & Connect matches `CreateBroDesktop` / `CreateBroModal` at `1440x900`.
- Desktop Bro Detail active matches `BroDetailActiveDesktop` at `1440x900`.
- Desktop Bro Detail offline/send blocked matches `BroDetailOfflineDesktop` if that state is reachable in the active runtime.
- Desktop Home, Create & Connect, and Bro Detail have no horizontal overflow, incoherent overlap, or clipped primary controls at `1440x900`, `1280x800`, and `1024x768`.
- Mobile empty Home, populated Home, Create & Connect, and Bro Detail/threads match the corresponding design states at `440x920`.
- Mobile offline/send blocked matches the corresponding design state if reachable in the active runtime.
- Mobile target states remain usable at `390x820` with no clipped primary controls, broken scroll, incoherent overlap, or horizontal page overflow.
- Existing runtime behavior still works for empty workspace, create/connect, exactly one Bro creation after first successful connection, connected Bro Home, Bro Detail, voice start/stop, draft/message send, and offline blocking.
- `cd src/newbro/ui && bun run test src/__tests__/App.test.tsx` passes.
- `cd src/newbro/ui && bun run test` passes.
- `cd src/newbro/ui && bun run build` passes.
- Screenshot QA evidence exists for the required desktop and mobile state/viewport matrix.
- Any remaining visual deltas are documented with concrete reason and follow-up path; do not mark the goal complete for undocumented drift.
</done_when>

<workflow>
1. Check git status and preserve unrelated user changes.
2. Read `SPEC.md`, `AGENTS.md`, and stable frontend/session/onboarding/executor/draft docs before editing.
3. Inspect the design prototype and active frontend in parallel. Map each target design state to the current active components and CSS that must be changed.
4. Render or capture fresh design reference screenshots from `design/Voice Interaction.html` for the target desktop and mobile states. Use `design/screenshots/` as supporting reference, but generate fresh references if existing screenshots do not map cleanly.
5. Capture current live implementation screenshots for the same states and viewport sizes. Create a concise visual delta checklist for shell/header, page padding, grid widths, modal sizing/position, card treatment, shadows, borders, typography, command blocks, activity rail, thread pane, composer, and mobile scrolling.
6. Fix desktop first:
   - align global desktop frame/header/body background
   - align empty Home
   - align Create & Connect modal and overlay
   - align populated Home
   - align Bro Detail active thread
   - align Bro Detail offline/send blocked if reachable
7. After desktop screenshots pass the visual delta review, fix mobile target states:
   - empty Home
   - populated Home
   - Create & Connect
   - Bro Detail / threads
   - offline/send blocked if reachable
8. Preserve and re-test runtime wiring while changing visuals. Do not break API calls or session behavior for the sake of static design parity.
9. Add or update focused tests for regressions touched by the alignment, especially create/connect completion, empty workspace, Bro Detail routing, voice controls, draft/message send, and offline blocking.
10. Run focused frontend tests, then full frontend tests and build.
11. Repeat browser screenshot QA at `1440x900`, `1280x800`, `1024x768`, `440x920`, and `390x820`. Iterate until visual drift is fixed or explicitly documented.
12. Review the final diff for unrelated churn, lost runtime behavior, leaked static mock data, stale docs, and insufficient screenshot evidence.
</workflow>

<verification_loop>
Focused inspection:
- `rg --files design src/newbro/ui/src | sort`
- `rg -n "FirstRunHomeDesktop|HomeDesktop|CreateBroModal|CreateBroDesktop|BroDetailActiveDesktop|BroDetailOfflineDesktop|HomeVariant|ThreadsVariant|CreateBro|offline|empty" design`
- `rg -n "DesktopHome|EmptyWorkspace|CreateConnectSheet|DesktopDetail|MobileHome|MobileDetail|createExecutorNode|revealExecutorNodeConnectCommand|createPersona|setVoiceTarget|sendSocketMessage|sendSocketDraftAsrTurn" src/newbro/ui/src`

Frontend verification:
- `cd src/newbro/ui && bun run test src/__tests__/App.test.tsx`
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Manual/browser visual QA:
- Start services if needed with `./newbro dev`.
- Capture desktop design and live screenshots at `1440x900` for empty Home, populated Home, Create & Connect, Bro Detail active, and offline/send blocked if reachable.
- Capture desktop live spot checks at `1280x800` and `1024x768` for Home, Create & Connect, and Bro Detail.
- Capture mobile design and live screenshots at `440x920` for empty Home, populated Home, Create & Connect, Bro Detail/threads, and offline/send blocked if reachable.
- Capture mobile live spot checks at `390x820` for empty Home, Create & Connect, and Bro Detail.
- Compare screenshots against the design references and document paths in the final report.

Functional smoke checks:
- Confirm empty workspace renders when local Bro/persona data is empty.
- Confirm create/connect shows a real connect command, waits for first successful node connection, and creates exactly one Bro.
- Confirm connected Bro appears on Home using runtime state.
- Confirm Bro Detail opens for the runtime Bro and preserves `?sid` behavior.
- Confirm voice start/stop uses existing connector flow and voice target cleanup still runs.
- Confirm draft/message send still uses existing client paths.
- Confirm disconnected usable nodes show offline/send-blocked state and prevent talk/send.

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
- Completed desktop and mobile state matrix with each state marked complete, not reachable, or documented with reason.
- Summary of design sources, tokens, CSS, assets, and component structures ported or reused.
- Summary of runtime wiring preserved for auth/session, personas, nodes, create/connect, Bro Detail, voice connector, STT/draft, message/draft send, and offline blocking.
- Key files changed, grouped by UI components/styles, runtime wiring, tests, and docs.
- Verification commands run and outcomes.
- Screenshot QA evidence paths and viewport sizes.
- Any skipped checks, documented pixel deltas, or residual risks.
- Clear completion signal only when every `done_when` item is satisfied or explicitly documented.
</output_contract>
