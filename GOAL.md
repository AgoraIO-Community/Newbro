<goal>
Implement RFC 0014, "Minimal Public Onboarding for Hosted Newbro", as an adopted public-user v1 path.

The deliverable is a working, tested, documented hosted Newbro experience where an invited user can open the Cloudflare-fronted HTTPS app, redeem/sign in with an invite, land directly in a per-user Bro Detail page, start voice with only browser microphone permission, draft/correct/confirm work, and connect a local executor node only when real Codex execution is needed.

The deliverable also includes a repeatable GitHub Actions deployment path that deploys to a long-running Ubuntu VPS over SSH/rsync and runs Newbro through `newbro.service`, with Cloudflare used as public edge only.
</goal>

<context>
Read first:
- docs/rfcs/0014-minimal-public-onboarding.md
- docs/rfcs/0013-newbro-v1.md
- docs/guides/ubuntu-systemd.md
- docs/guides/local-dev.md
- docs/guides/cli.md
- docs/guides/connector-host.md
- docs/guides/agora-conversational-ai.md
- docs/architecture/executors.md
- docs/protocol/draft-to-execute.md
- docs/memories.md
- AGENTS.md project instructions in the conversation or repo root if present

Inspect current implementation areas before editing:
- src/newbro/api/app.py
- src/newbro/api/routes/
- src/newbro/api/ws/stream.py
- src/newbro/api/ws/executors.py
- src/newbro/runtime/container.py
- src/newbro/runtime/session.py
- src/newbro/runtime/config.py
- src/newbro/communication/persona_pool.py
- src/newbro/executors/node/registry.py
- src/newbro/runtime/executor_node_manager.py
- src/newbro/connectors/voice/agora_convoai/
- src/newbro/ui/src/App.tsx
- src/newbro/ui/src/NewbroShell.tsx
- src/newbro/ui/src/routes/
- src/newbro/ui/src/components/newbro/BroDetailPage.tsx
- src/newbro/ui/src/components/newbro/BrosPage.tsx
- src/newbro/ui/src/components/newbro/NodesPage.tsx
- src/newbro/ui/src/lib/session-client.ts
- .github/workflows/

Useful discovery commands:
- rg "create_session|get_session|sessions/|stream|executor-nodes|personas|draft|connectors|agora-convoai" src/newbro tests docs
- rg "cookie|auth|invite|user|owner|session_id|node_id|token|raw_token|set_cookie|Depends|WebSocket" src/newbro tests docs
- rg "newbro service install|newbro.service|rsync|ssh|Cloudflare|Vercel|Workers|Pages|deploy" .github docs README.md scripts src/newbro
- rg "VITE_API_BASE_URL|VITE_CONNECTOR_BASE_URL|createSession|bootstrap|BroDetail|BrosPage|NodesPage" src/newbro/ui/src
</context>

<constraints>
Source-of-truth and scope constraints:
- RFC 0014 is the product target for this goal, but stable docs and current code remain authoritative until implementation adopts the behavior.
- Preserve RFC 0013 quiet communication behavior. Do not change the draft-to-execute interaction model except where needed to add public onboarding, auth ownership, and deployment.
- Keep Communication Brain and Execution Brain separate.
- Keep connector transport thin. Browser connector routes may require authenticated owner context, but connector/vendor callbacks must not depend on browser cookies.
- Treat protocol models as the source of truth.
- Runtime V1 may remain single-executor in behavior, but schemas and ownership should not block future multi-executor support.

Hard non-goals:
- Do not add quotas, usage limits, billing, throttling, or rate-limit systems for this goal.
- Do not add anonymous public access.
- Do not build a hosted shared Codex executor fleet.
- Do not require user-provided OpenAI or Agora keys for first-run voice.
- Do not replace the detached executor-node architecture.
- Do not rework Newbro into a Cloudflare Workers-native application.
- Do not make Cloudflare Pages or Vercel the default public deployment shape.
- Do not turn `/chat/completions` compatibility paths into the runtime source of truth.
- Do not add hard-coded demo rules or transcript keyword shortcuts to make the user flow appear to work.

Product constraints:
- First public launch is invite-gated.
- Public safety for this goal relies on invite-only access plus strict owner scoping, not quotas or limits.
- Server-managed OpenAI and Agora credentials must remain server-side and must not be exposed to browser bundles or API responses.
- A new invited user must land directly in Bro Detail after bootstrap, not a Bro picker or global workspace.
- The default Bro/persona must be per-user, not global.
- Voice-first usage must work without local install.
- Real Codex execution requires a user-owned detached local executor node.
- If a user confirms a draft without a live bound node, the task must enter or remain in a clear waiting-for-executor state and the UI must show how to connect a local node.

Persistence and ownership constraints:
- Add durable public-user ownership storage. Prefer a small SQLite-backed store under `~/.newbro` unless existing repo patterns clearly indicate a better local durable store.
- User, invite, browser session, runtime session ownership, persona/Bro ownership, executor-node ownership, and node-token reveal/rotation must be represented durably or derived from durable owner-scoped records.
- Existing service-level file stores for personas and executor nodes must not remain globally shared for public-user paths.
- Websocket streams must enforce the same owner boundary as HTTP routes.

Deployment constraints:
- The adopted v1 deployment is GitHub Actions -> SSH/rsync -> Ubuntu VPS -> `newbro.service` / `newbro start`.
- Cloudflare is DNS/HTTPS/proxy/Tunnel edge only, not the Newbro runtime host.
- Runtime secrets and `~/.newbro/.env` / `~/.newbro/config.yaml` live on the VPS.
- GitHub Actions must not bake OpenAI or Agora secrets into frontend build output.
</constraints>

<done_when>
- A new durable auth/ownership layer exists for invite redemption, browser sessions, users, session ownership, per-user default Bro/persona ownership, and executor-node ownership.
- Browser-facing HTTP routes for sessions, conversations, drafts, personas, executor nodes, and browser-started connector prepare/start paths require authenticated user context and enforce owner scoping.
- Browser websocket session streams reject unauthenticated users and reject users who do not own the session.
- Executor-node websocket registration still authenticates detached nodes by node id and token, and node credentials are scoped so User A cannot use, reveal, rotate, bind, delete, or list User B's node.
- Invite flow exists with concrete API behavior for `POST /api/auth/invites/redeem`, `GET /api/auth/me`, and `POST /api/auth/logout`, or equivalent routes documented in stable docs and tests.
- Bootstrap flow exists with concrete API behavior for `GET /api/me/bootstrap`, or an equivalent route documented in stable docs and tests. It returns enough state for the UI to enter Bro Detail directly.
- First authenticated bootstrap creates or resumes a user-owned default session and per-user default Bro/persona.
- The UI routes authenticated first-run users directly to Bro Detail and does not require a Bro picker or node setup before voice use.
- Voice can be started from Bro Detail for an authenticated user without local install, using server-managed OpenAI and Agora configuration only.
- Server-managed OpenAI and Agora secrets are not present in frontend source-visible configuration, browser responses, generated build assets, or logs produced by normal API responses.
- Confirming a draft without a live bound executor node creates or preserves a waiting-for-executor task state and shows a clear UI path with a copyable local node command.
- The generated local node command uses the hosted public base URL and `newbro executor run --base-url ... --node-id ... --token ...`; it must not require repo checkout for the user-facing command.
- Connecting the user's detached node resumes or enables waiting execution without exposing another user's sessions or node credentials.
- A GitHub Actions workflow exists for production deployment to an Ubuntu VPS using SSH/rsync, then `./newbro service install` or `systemctl restart newbro.service`.
- Deployment docs describe required GitHub secrets, VPS prerequisites, Cloudflare DNS/proxy or Tunnel shape, runtime config location, and post-deploy health checks.
- Stable docs are updated for adopted behavior: public onboarding, auth/session ownership, executor-node ownership, service-hosted voice setup, and Cloudflare-fronted VPS deployment.
- `docs/memories.md` contains a short factual note for the adopted public onboarding/deployment behavior.
- RFC 0014 remains proposal/history and is not rewritten to pretend it is the stable runtime contract.
- Tests prove User A cannot access User B's session snapshot, conversation, draft, personas, node list, node token reveal/rotation, browser connector prepare path, or session websocket stream.
- Tests prove an unauthenticated browser request to protected routes returns 401 or an equivalent explicit auth failure.
- Tests prove a new invited user bootstrap creates/resumes a default session and per-user default Bro/persona.
- Tests prove no quota/rate-limit/usage-limit system was introduced for this goal by auditing implementation code and docs for quota/limit language, with any unrelated existing uses explained.
- Verification succeeds with focused backend auth/ownership tests, focused connector/voice route tests, focused frontend onboarding tests, frontend build, and the full backend test suite.
</done_when>

<workflow>
1. Check git status and preserve unrelated user changes.
2. Re-read RFC 0014 carefully. Extract all hard decisions: invite-only, no quotas/limits, per-user Bro Detail, managed credentials, detached node only for execution, Cloudflare edge only, SSH/rsync VPS deploy.
3. Read stable docs and current code listed in `<context>` before implementing.
4. Inspect existing runtime/session/persona/node persistence and route boundaries. Identify current global state that must become owner-scoped.
5. Design the smallest durable auth/ownership substrate:
   - invite records
   - user records
   - browser session records
   - runtime session ownership
   - default Bro/persona ownership
   - executor-node ownership
   Use SQLite under `~/.newbro` unless existing repo patterns strongly justify a different durable local store.
6. Implement auth helpers/middleware/dependencies for HTTP routes and websocket routes.
7. Add invite redemption, current-user, logout, and bootstrap APIs.
8. Scope session creation/lookup, conversation, drafts, personas, and executor-node APIs by authenticated owner.
9. Scope browser-started connector prepare/start paths by authenticated session/Bro owner while keeping vendor callback paths functional without browser cookies.
10. Update runtime/bootstrap behavior so authenticated first-run users get a default session and per-user default Bro/persona.
11. Update the UI login/invite/bootstrap path so users land directly in Bro Detail after authentication.
12. Update Bro Detail and node UX so voice works immediately and execution without a live node shows waiting-for-executor plus a copyable local node command.
13. Add the GitHub Actions SSH/rsync VPS deployment workflow. Keep OpenAI/Agora runtime secrets on the VPS, not in frontend build env.
14. Update stable docs for the adopted public onboarding, deployment, auth/ownership, and service-hosted voice behavior. Append a short factual note to `docs/memories.md`.
15. Add focused backend tests for auth, ownership, bootstrap, invite redemption, protected routes, websocket rejection, and node ownership.
16. Add focused connector tests for authenticated browser connector paths and unauthenticated/vendor callback separation.
17. Add focused frontend tests for invite/bootstrap/direct Bro Detail and waiting-for-executor/node command UX.
18. Run focused tests, then full backend tests, then frontend checks. Fix failures in scope.
19. Run audits for forbidden scope drift: quotas/limits, serverless/Workers default deployment, separate frontend default deployment, secret exposure, and hard-coded demo shortcuts.
</workflow>

<verification_loop>
Focused backend checks:
- .venv/bin/python -m pytest tests/unit
- .venv/bin/python -m pytest tests/integration/api
- If new auth/ownership tests are in narrower files, run those files first before broader suites.

Focused connector checks:
- .venv/bin/python -m pytest tests/unit/connectors/voice/agora_convoai

Full backend check:
- .venv/bin/python -m pytest

Frontend checks:
- cd src/newbro/ui && bun run test
- cd src/newbro/ui && bun run build

Deployment workflow checks:
- Review the new GitHub Actions workflow for required secrets and commands.
- Validate workflow syntax as far as local tooling permits.
- If `act` or GitHub workflow validation is unavailable, document the manual review and any unverified assumptions.

Security/constraint audits:
- rg -n "quota|rate.?limit|usage.?limit|billing|throttle" src docs .github
- rg -n "Workers|Cloudflare Pages|Vercel|VITE_API_BASE_URL|VITE_CONNECTOR_BASE_URL" docs .github src/newbro/ui/src
- rg -n "OPENAI_API_KEY|AGORA|APP_CERTIFICATE|APP_CERT" src/newbro/ui .github
- rg -n "keyword|phrase|hard.?code|demo" src/newbro/runtime src/newbro/connectors src/newbro/api tests
- Inspect every hit. Hits are acceptable only when they are documentation of non-goals, existing unrelated constants, test assertions against shortcuts, or non-secret public configuration.

Manual local smoke check when feasible:
- Start the backend/UI with service-hosted connector routes.
- Redeem an invite.
- Confirm `/api/auth/me` returns the user and bootstrap creates/resumes a default session plus Bro.
- Confirm the browser opens Bro Detail directly.
- Start voice from Bro Detail without local node setup.
- Confirm draft/correction/confirmation still follows RFC 0013 behavior.
- Confirm sending/confirming without a live node shows waiting-for-executor and a copyable node command.
- Connect a local executor node with the generated command and confirm the node appears only for the owning user.

If any check cannot run, document exactly why, what was run instead, and what risk remains. Do not claim the goal is complete with unexplained failures.
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
- Do not widen scope beyond RFC 0014 public onboarding, owner scoping, same-origin hosted voice, deferred local executor node UX, deployment workflow, docs, and tests.
- Do not introduce quotas, usage limits, rate limits, billing, hosted shared executor fleets, Cloudflare Workers-native runtime migration, or separate frontend deployment as default.
- Do not expose server-managed OpenAI or Agora credentials to the browser or GitHub Actions build output.
- Do not implement semantic transcript heuristics, hard-coded demo rules, or fake success paths.
- Update stable docs and `docs/memories.md` only for adopted implementation-relevant behavior.
- Keep final answer concise.
</execution_rules>

<output_contract>
Final output must include:
- A concise summary of the public onboarding path implemented.
- A concise summary of the auth/ownership model and persistence choice.
- A concise summary of how direct Bro Detail bootstrap works.
- A concise summary of how voice remains zero-config for users and how real execution is deferred to local nodes.
- A concise summary of the GitHub Actions -> SSH/rsync -> Ubuntu VPS -> Cloudflare edge deployment path.
- Key files changed, grouped by backend/auth, runtime ownership, connector, UI, deployment, docs, and tests.
- Verification commands run and outcomes.
- Security/constraint audit results, including no quota/limit implementation and no secret exposure.
- Any skipped checks, blockers, or residual risks.
- A clear completion signal only when every `done_when` item is satisfied or explicitly documented as out of scope.
</output_contract>
