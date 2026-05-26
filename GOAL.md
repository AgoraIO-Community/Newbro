<goal>
Refactor the active Newbro frontend under `src/newbro/ui` to follow the new design in `design/` with pixel-accurate desktop and mobile UI while preserving and wiring the existing Newbro runtime functionality. The finished app should use or faithfully port the design prototype's components, tokens, assets, and interaction states, then connect those surfaces to the current session, persona, executor-node, draft, and voice connector flows.
</goal>

<context>
Read first:
- AGENTS.md project instructions in the repo root or conversation.
- docs/guides/frontend-workbench.md
- docs/guides/frontend-contracts.md
- docs/guides/frontend-handoff.md
- docs/architecture/public-onboarding-and-ownership.md
- docs/architecture/executors.md
- docs/protocol/session-stream.md
- docs/protocol/draft-to-execute.md
- docs/memories.md
- design/README-equivalent sources:
  - design/app.jsx
  - design/tokens.css
  - design/voice-state.jsx
  - design/variants-desktop.jsx
  - design/variants-mobile.jsx
  - design/variants-channel-mobile.jsx
  - design/variants-onboarding.jsx
  - design/variant-stage.jsx
  - design/variant-walkie.jsx
  - design/variant-document.jsx
  - design/bro-characters.jsx
  - design/bro-characters.css
  - design/assets/newbro-logo.webp
  - design/assets/avatars/
  - design/screenshots/
  - design/uploads/export 2/README.md
  - design/uploads/export 2/app.jsx
  - design/uploads/export 2/characters.jsx
  - design/uploads/export 2/styles.css
- Current active frontend:
  - src/newbro/ui/package.json
  - src/newbro/ui/src/NewbroShell.tsx
  - src/newbro/ui/src/App.tsx
  - src/newbro/ui/src/router.tsx
  - src/newbro/ui/src/styles/app.css
  - src/newbro/ui/src/components/newbro/
  - src/newbro/ui/src/components/ui/
  - src/newbro/ui/src/lib/session-client.ts
  - src/newbro/ui/src/lib/connector-client.ts
  - src/newbro/ui/src/lib/voice-runtime.ts
  - src/newbro/ui/src/types.ts
  - src/newbro/ui/src/__tests__/App.test.tsx

Useful discovery commands:
- rg --files design src/newbro/ui/src | sort
- rg -n "HomeDesktop|BroDetailActiveDesktop|SignInDesktop|FirstRunHomeDesktop|CreateBroDesktop|BroDetailOfflineDesktop|HomeVariant|ThreadsVariant|SignInVariant|CreateBroVariant|ThreadsOfflineVariant" design
- rg -n "VoiceProvider|useVoice|inputMode|freeSubMode|listening|thinking|working|reporting|offline|send blocked" design
- rg -n "bootstrapPublicUser|signupPublicUser|getCurrentUser|logoutPublicUser|getSessionSnapshot|getConversationSnapshot|openSessionStream|sendSocketMessage|sendSocketDraftAsrTurn|createExecutorNode|updatePersona|revealExecutorNodeConnectCommand|setVoiceTarget|clearVoiceTarget" src/newbro/ui/src
- rg -n "useVoiceSession|prepare|activate|stop|Agora|connector|draft|transcript|executorNodeId|connection_status|last_connected_at" src/newbro/ui/src
- rg -n "data-testid|voice-session-start|voice-session-stop|copy|signup|session|persona|executor" src/newbro/ui/src/__tests__ src/newbro/ui/src/components/newbro
</context>

<constraints>
- Treat `src/newbro/ui/` as the only active frontend. Do not revive or route users to an older UI shell.
- Preserve Newbro's protocol-first runtime boundaries. UI components may render state and invoke typed client functions, but must not invent backend policy, parse transcript keywords, or bypass session/draft/executor-node contracts.
- Keep Communication Brain, Execution Brain, Shared Blackboard, and transport responsibilities separate. Do not move business policy into the browser for cosmetic reasons.
- Keep transport thin: same-origin or `VITE_API_BASE_URL` session APIs own durable Newbro state; connector APIs own Agora browser voice/session lifecycle.
- The new design prototype is the visual source of truth. Prefer directly porting components, tokens, assets, and state-specific layouts from `design/` when practical. Where direct copy is not practical, match dimensions, spacing, typography, colors, and interaction states as closely as the active app architecture allows.
- Existing live functionality must remain wired. Do not replace runtime data with static design arrays except for isolated empty/error/demo fallbacks.
- Current routes and deep-link behavior must remain usable: the shell follows one active session, preserves `?sid=...`, resumes it on load, and keeps sidebar/mobile navigation session-aware.
- Existing auth/signup/logout behavior must remain functional and visually align with the design's sign-in/invitation state.
- Existing persona and executor-node management behavior must remain functional, including create, bind, edit, rotate/reveal/copy command, delete where supported, ownership scoping, and token secrecy.
- Preserve current Bro node usability semantics already in the codebase: no usable node stays gated; a usable but disconnected node keeps Bro Detail visible but blocks talk/start actions with warning; live connection changes re-render from snapshot state.
- Preserve current voice and draft behavior: voice target setup/cleanup, connector prepare/activate/stop, STT/draft transcript flow, sendSocketMessage, sendSocketDraftAsrTurn, and stop/error cleanup must stay connected to real runtime clients.
- Do not change backend or protocol contracts unless the frontend cannot represent a required existing runtime behavior without a minimal contract fix. If backend/protocol changes are made, add focused backend tests and update stable docs.
- Do not broaden scope into unrelated backend features, new authentication systems, new executor orchestration, or design-only marketing pages.
- Use existing frontend dependencies and design-system primitives where appropriate. Add dependencies only when the design cannot be implemented cleanly with the current stack and the tradeoff is justified.
- Keep responsive behavior first-class. Desktop and mobile should be purpose-built from the design variants, not an overflowing desktop layout squeezed into mobile.
- Avoid nested cards, decorative gradient/orb backgrounds, and explanatory in-app text about how the UI was built. The product screen should be the first screen after auth/session load.
- Update stable docs and `docs/memories.md` only for adopted implementation-relevant frontend/runtime behavior changes, not for tiny refactors or test-only changes.
</constraints>

<done_when>
- `src/newbro/ui` visually matches the new `design/` prototype for desktop and mobile home, Bro detail, onboarding/sign-in, create/connect Bro, and offline-node states.
- The implementation directly reuses or faithfully ports components, design tokens, CSS, image assets, character assets, and state-specific layouts from `design/` where practical, rather than re-creating a loosely similar layout.
- Existing live functionality remains wired: auth/signup/logout, current user bootstrap, session resume via `?sid`, session snapshot reads, websocket stream updates, conversation history hydration, personas, executor nodes, Bro management, node management, connector prepare/activate/stop, STT/draft flow, voice target behavior, and message/draft send behavior.
- The design's new UI controls invoke the existing runtime actions instead of mock data wherever backend data exists.
- Sample/mock design data is allowed only as an empty/error/demo fallback and is isolated from runtime state so it cannot mask broken API wiring.
- Desktop visual QA covers at least the design-equivalent states for home workspace, active Bro detail, sign-in/invitation, empty workspace, create/connect Bro, and Bro detail with node offline/send blocked.
- Mobile visual QA covers at least the design-equivalent states for home workspace, thread/detail, sign-in/invitation, empty workspace, create/connect Bro, and offline/send blocked.
- The app remains free of horizontal page overflow and incoherent overlapping text at representative desktop and mobile viewports.
- Tests cover key wiring regressions: session bootstrap/resume, Bro cards sourced from runtime personas, Bro detail voice actions, node/offline blocking behavior, onboarding/sign-in flow, and create/connect Bro path.
- Existing frontend tests that validate auth, session, Bro Detail, node management, draft/STT, and voice behavior still pass or are intentionally updated to match the new visual structure without weakening runtime assertions.
- `cd src/newbro/ui && bun run test` passes.
- `cd src/newbro/ui && bun run build` passes.
- Browser/manual visual QA compares the implemented app against `design/screenshots/*` at desktop and mobile viewports, with any remaining pixel deltas documented in the final answer.
- Stable frontend docs are updated if the active UI structure, source-of-truth design, or user-visible runtime behavior changes meaningfully.
- `docs/memories.md` contains a short factual note only if this refactor adopts a meaningful behavior or architecture change beyond visual/component restructuring.
</done_when>

<workflow>
1. Check git status and preserve unrelated user changes. Treat the existing untracked `design/` folder as user-provided source material.
2. Read the stable frontend/runtime docs, then inspect the current `src/newbro/ui` implementation and tests.
3. Inspect the design prototype sources and screenshots. Identify the canonical components, tokens, assets, and screen states to port:
   - desktop home workspace;
   - desktop active Bro detail;
   - desktop sign-in/invitation;
   - desktop empty workspace;
   - desktop create/connect Bro;
   - desktop offline/send-blocked Bro detail;
   - mobile home;
   - mobile thread/detail;
   - mobile onboarding/create/offline variants;
   - character/avatar/logo assets;
   - voice state model and input-mode controls.
4. Map design components to current runtime surfaces before editing:
   - auth/signup/logout;
   - active session bootstrap/resume;
   - websocket/snapshot state;
   - persona-derived Bro cards;
   - executor-node status and create/connect flows;
   - Bro management and node management routes;
   - conversation memory;
   - voice connector lifecycle;
   - STT/draft transcript;
   - send/talk controls and offline blocking.
5. Decide the integration shape:
   - port reusable visual primitives into `src/newbro/ui/src/components/newbro/` or a clearly named subfolder;
   - merge design tokens into `src/newbro/ui/src/styles/app.css` without breaking Tailwind v4 and existing utility classes;
   - copy required assets into the frontend public/src asset path used by Vite;
   - keep runtime adapters separate from presentational components where practical.
6. Implement the visual foundation first: tokens, fonts, body/page styling, shared primitives, character/logo/avatar assets, and responsive frame/layout utilities.
7. Refactor authenticated shell layout to match the design's desktop and mobile structure while preserving route/session behavior.
8. Refactor home workspace to render runtime persona/task/node state through the design's Bro/channel cards, with isolated fallback data only when runtime data is absent by documented design.
9. Refactor Bro detail/thread surfaces to match the design and wire existing conversation memory, voice state, draft/STT, send, stop, and offline-blocked behavior.
10. Refactor onboarding/sign-in/empty/create-connect/offline states to match the design and call existing auth, persona, node, reveal/copy command, and bind/update APIs.
11. Refactor management pages only as much as needed to stay coherent with the new visual system while preserving existing functionality.
12. Add or update focused tests for runtime wiring through the new components. Prefer assertions on user-observable behavior and mocked client calls over implementation details.
13. Run focused tests during development, then run the full frontend test/build commands.
14. Start the local frontend/backend as needed and perform browser visual QA against desktop and mobile viewports. Compare the implemented states to `design/screenshots/*`; fix layout, overflow, and interaction polish issues.
15. Update stable docs and memory only if the adopted implementation changes the active UI structure or runtime behavior in a meaningful way.
16. Review final diff for unrelated churn, mock-data leakage, broken runtime wiring, duplicated dead components, stale docs, and test assertions that only check cosmetic implementation details.
</workflow>

<verification_loop>
Focused inspection:
- rg --files design src/newbro/ui/src | sort
- rg -n "mock|sample|CHANNELS|BROS|bootstrapPublicUser|signupPublicUser|getSessionSnapshot|openSessionStream|sendSocketMessage|sendSocketDraftAsrTurn|createExecutorNode|updatePersona|setVoiceTarget|clearVoiceTarget|useVoiceSession" src/newbro/ui/src

Frontend tests and build:
- cd src/newbro/ui && bun run test
- cd src/newbro/ui && bun run build

Backend tests, only if backend/protocol files changed:
- .venv/bin/python -m pytest tests/unit tests/integration/api
- .venv/bin/python -m pytest

Manual/browser visual QA when feasible:
- Start backend if needed: ./newbro backend
- Start frontend if needed: cd src/newbro/ui && bun run dev
- Open the local UI in a browser and check desktop viewport around 1440x900.
- Check mobile viewport around 390x820 or 440x920.
- Compare against `design/screenshots/01-canvas.png`, `design/screenshots/02-stage-focus.png`, `design/screenshots/dt-detail-current.png`, `design/screenshots/firsthome-sheet-closed.png`, `design/screenshots/hero-only.png`, `design/screenshots/hero-tight.png`, `design/screenshots/hero-zoom.png`, `design/screenshots/onboarding-overview.png`, `design/screenshots/onboarding-right.png`, `design/screenshots/recheck-hq.png`, and `design/screenshots/recheck.png` as applicable to the implemented states.

Manual functional smoke checks:
- Sign in with email and invitation code, including visible error handling.
- Confirm current user bootstrap and logout still work.
- Confirm session opens, writes `?sid`, resumes from `?sid`, and falls back cleanly if resume fails.
- Confirm home Bro/channel cards come from runtime personas and node/task state.
- Confirm navigation preserves `sid` on desktop and mobile.
- Confirm Bro Detail can start/stop voice through the existing connector flow.
- Confirm STT/draft transcript and message/draft send actions call existing client paths.
- Confirm create/connect Bro flow creates or binds an executor node, shows/reveals/copies the connect command only through existing credential flows, and updates persona binding.
- Confirm offline/send-blocked state appears for usable disconnected nodes and blocks talk/start actions without hiding normal detail.
- Confirm empty runtime state uses the design empty/onboarding state rather than silently replacing runtime with fake active data.

Audits:
- rg -n "design/|uploads/export|localhost|TODO|FIXME|Babel|CDN|window.__voice|TWEAK|CHANNELS|NEWBRO_INDEX" src/newbro/ui/src
- rg -n "frontend|UI|design|Newbro Walkie|Bro detail|offline|create/connect" docs/guides docs/architecture docs/memories.md

If a check cannot run, document why, what was run instead, and the residual risk. Do not claim pixel-perfect completion without either browser visual QA evidence or an explicit note of unverified visual risk.
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
- Do not widen scope beyond the new-design UI refactor and required runtime wiring.
- Keep the final answer concise.
- Respect AGENTS.md project skills:
  - read stable docs before RFCs;
  - preserve Communication Brain and Execution Brain boundaries;
  - avoid fake semantic rules;
  - keep transport thin;
  - diagnose from real state;
  - protect dispatch from raw speech shortcuts;
  - verify activation before judging a manual run;
  - update stable docs and memories deliberately only for adopted meaningful changes.
</execution_rules>

<output_contract>
Final output must include:
- Summary of the design integration approach, including which design sources/components/assets were ported or reused.
- Summary of runtime wiring preserved for auth, sessions, personas, nodes, Bro detail, draft/STT, and voice connector actions.
- Key files changed, grouped by UI components/styles/assets, runtime wiring, tests, and docs.
- Verification commands run and outcomes.
- Manual visual QA performed, including desktop/mobile viewports and any known pixel deltas from `design/screenshots/*`.
- Any skipped checks or residual risks.
- A clear completion signal only when every `done_when` item is satisfied or explicitly documented.
</output_contract>
