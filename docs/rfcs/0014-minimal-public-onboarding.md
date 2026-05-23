# RFC 0014: Minimal Public Onboarding for Hosted Newbro

This RFC proposes the first public-user onboarding model for Newbro.

It is a proposal document, not the current source of truth for runtime
behavior. When this RFC conflicts with stable docs under `docs/architecture/`,
`docs/protocol/`, `docs/guides/`, or current code, treat the stable docs and
implemented behavior as authoritative.

## Summary

Newbro should let invited public users try the voice-first Bro Detail
experience with minimal setup.

The target user flow is:

1. Open hosted HTTPS Newbro.
2. Redeem an invite or sign in.
3. Land directly on a default Bro Detail page.
4. Grant microphone permission.
5. Talk, see live drafts, correct drafts, and confirm dispatch intent.
6. Connect a local executor node only when real Codex execution is needed.

Server-managed OpenAI and Agora credentials make voice setup zero-config for
users. Local executor setup remains optional and deferred.

## Problem

The current repo is still operator/developer oriented:

- local setup requires repo checkout and `newbro setup`
- API sessions are not user-owned
- persona and executor-node state is effectively shared at the service level
- voice requires operator-managed Agora/OpenAI configuration
- real execution requires a detached executor node

That shape is acceptable for trusted local testing, but not for invited public
users.

Opening the current service directly would make onboarding easier, but it would
also make session ownership, node-token access, and shared credential use too
loose for public access.

## Goals

- Make voice-first usage require only a browser, invite, and microphone
  permission.
- Open directly into Bro Detail, not a Bro picker or global workspace.
- Keep server-managed Agora and OpenAI credentials hidden from users.
- Keep real Codex execution on the user's detached local node.
- Defer local node setup until execution is needed.
- Support repeatable deployment from GitHub Actions to a Cloudflare-fronted
  hosted service.
- Preserve the quiet communication design from RFC 0013.
- Preserve protocol-first runtime boundaries and avoid hard-coded demo
  behavior.

## Non-Goals

- Open anonymous public access.
- Hosted shared Codex execution fleet.
- User-provided OpenAI or Agora keys in the first public version.
- Replacing the detached executor-node architecture.
- Reworking Newbro into a Cloudflare Workers-native application in the first
  public version.
- Deploying the frontend separately from the runtime as the default public
  shape.
- Turning `/chat/completions` compatibility paths into the runtime source of
  truth.
- Updating stable docs or `docs/memories.md` before adoption.

## Proposed Design

### Access Model

Use invite-gated accounts for the first public version.

The hosted app should require an authenticated user session before allowing
browser access to sessions, personas, drafts, executor nodes, or voice-session
preparation.

A lightweight account model is sufficient:

- invite code
- user id
- session cookie
- created and last-seen timestamps

Session cookies should be HttpOnly and secure in production.

### User Bootstrap

After login, the app should call a bootstrap endpoint that returns:

- current user
- default session id
- default Bro/persona
- voice readiness
- bound executor-node status

If the user has no session or Bro yet, the server creates them automatically.

The UI should route the user directly to Bro Detail. Bro selection and node
management remain advanced paths, not the first-run flow.

### Voice Path

Voice should work without local installation.

The hosted server owns:

- OpenAI API key
- Agora App ID and App Certificate
- ASR/TTS vendor configuration
- connector public base URL

Users only grant microphone permission. Browser calls should go through the
hosted HTTPS origin, preferably same-origin `/api/connectors/...`.

Agora/vendor callbacks may need connector-level binding credentials, but they
should not depend on browser cookies.

### Draft and Confirmation

The RFC 0013 draft-to-execute flow remains unchanged:

- STT events update draft state.
- LLM-backed classification and rewriting determine draft content and
  readiness.
- The communication brain speaks only when `RuntimeDecision.should_speak` says
  to speak.
- Confirmed drafts dispatch into runtime task state.

No hard-coded phrase rules should be added to fake correctness.

### Executor Node

Real execution requires the user's local detached node.

If a user confirms a draft without a live bound node:

- create or keep the task in `waiting_executor`
- show a clear "Connect Codex to run" state
- provide a copyable command

Recommended command shape:

```bash
python3 -m pip install --user --upgrade newbro-cli
newbro executor run --base-url https://newbro.example.com --node-id node-1234 --token secret
```

Executor nodes must be user-scoped. A user must not list, reveal, rotate, bind,
or delete another user's node.

## Deployment Model

The recommended first public deployment is a single hosted Newbro service on a
long-running Ubuntu host or VPS, with Cloudflare in front of it.

Cloudflare is the public edge for v1. It is not the Newbro runtime host.

Cloudflare should own the public edge:

- DNS for the public Newbro domain
- HTTPS termination
- optional Cloudflare Tunnel to the origin host

The Newbro origin should remain a normal Python service on an Ubuntu VPS or
similar long-running host:

- `newbro start` serves the built React UI from `/`
- the same process serves `/api/*`
- the same process mounts `/api/connectors/*`
- browser session streams use `/api/sessions/{session_id}/stream`
- detached executor nodes connect to `/api/executors/control`
- systemd runs the process as `newbro.service`

The intended public topology is:

```text
GitHub Actions
  -> SSH/rsync deploy
  -> Ubuntu VPS
       -> newbro.service
       -> newbro start

Cloudflare
  -> https://newbro.example.com
       /                         built React UI
       /api/*                    FastAPI runtime
       /api/connectors/*         service-mounted voice connector routes
       /api/sessions/{id}/stream browser session websocket
       /api/executors/control    detached node websocket
```

This same-origin shape is the default because it avoids CORS, split connector
origins, websocket origin mismatches, and Agora callback confusion.

### Automated Deployment

GitHub Actions should own repeatable deployment after merge to `main`.

The default deployment transport is SSH plus rsync to the VPS. This matches the
current service-install path and avoids requiring a Docker or serverless runtime
for the first public version.

The production workflow should:

1. check out the repo
2. install backend and frontend dependencies
3. run the project test suite
4. build the frontend production assets
5. rsync the repo or release artifact to the VPS
6. run `./newbro service install` or restart `newbro.service`
7. verify the public health endpoint through the Cloudflare domain

The origin host should own runtime secrets and local config:

- `~/.newbro/.env`
- `~/.newbro/config.yaml`
- OpenAI API key
- Agora App ID and App Certificate
- connector public base URL

GitHub Actions should not bake OpenAI or Agora secrets into frontend assets.
Actions only needs SSH deployment credentials for the VPS and, if used,
Cloudflare deployment or tunnel credentials.

### Non-Default Deployment Options

Cloudflare Pages may still be useful for static UI previews, but it should not
be the default public product deployment because the voice and runtime paths
benefit from a same-origin service.

Cloudflare Workers-native Python/FastAPI deployment is a future option, not the
first target. Moving Newbro to Workers would require a separate design for
runtime state, websocket ownership, connector lifecycle, and detached executor
control channels.

## Public Interfaces

The proposal implies new or changed browser-facing surfaces:

- `POST /api/auth/invites/redeem`
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `GET /api/me/bootstrap`

The bootstrap response should include enough state for the app to enter Bro
Detail without a separate pick/setup flow.

Existing session, persona, draft, executor-node, and browser connector routes
should keep their current protocol meaning, but require authenticated owner
context before serving browser requests.

## Security Requirements

Before public use:

- all browser-facing APIs require authenticated user context
- sessions are owner-scoped
- personas are owner-scoped
- executor nodes and raw node tokens are owner-scoped
- websocket session streams enforce ownership
- server credentials are never exposed to the browser

## Acceptance Criteria

- A new invited user can start voice from Bro Detail with no local install.
- Drafts update from speech and can be corrected before dispatch.
- Confirming without a node does not fail silently; it shows
  `waiting_executor`.
- Connecting a local node resumes waiting execution.
- User A cannot access User B's sessions, personas, drafts, node tokens, or
  streams.
- Server credentials are never exposed to the browser.
- The implementation preserves the RFC 0013 quiet communication behavior.

## Adoption Notes

If adopted, update stable docs for:

- public deployment
- auth/session ownership
- executor-node ownership
- voice connector production setup

Append a short factual note to `docs/memories.md` only after implementation is
merged.
