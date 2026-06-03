# Opaque Expiring Download Handles — Design

Status: design (approved for planning)
Date: 2026-06-02

## Summary

The workspace-file download endpoint currently puts the **absolute filesystem
path in the request URL** (`GET …/turns/{turn_id}/file?path=/Users/…/report.md`).
Even though the endpoint is session-authenticated and double-gated, the raw path
leaks into browser history, server/proxy access logs, the `Referer` header, and
screenshots.

Replace the single path-bearing GET with a two-step, **opaque expiring handle**:

1. **Mint** (`POST …/file-handle`, path in the request **body**): authenticate +
   run Gate 1 (the path must appear in the turn's assistant text), then store a
   random token → `{session_id, thread_id, node_id, path, expires_at}` in an
   in-memory store and return an opaque URL `/api/files/<token>`.
2. **Redeem** (`GET /api/files/<token>`): authenticate, look up the token (410 if
   missing/expired), require the caller to own the bound session, then run Gate 2
   (node workspace containment) and stream the file.

The path never appears in any URL or in the token (the token is a random id, not
an encoding). Handles expire after **5 minutes** and are **reusable within that
window** (so a browser HEAD/range preflight doesn't consume them). The redeem
endpoint still requires the session cookie — a leaked token is not a bearer
capability.

Two changes ship together: (1) the **addressing** of the download (opaque expiring
handle instead of a path-bearing URL), and (2) a **Gate-2 fix** so downloads work
from imported codex *history* threads — the node had no workspace binding for them
(the confirmed cause of the 403 seen in testing). Gate 1 and the Gate-2 containment
*check* are unchanged.

## Goal / Success Criteria

- No request URL (or token) ever contains the absolute filesystem path.
- Clicking a download control still downloads the in-workspace file the assistant
  referenced, with the same two-gate security as today.
- A minted handle stops working after 5 minutes (`410 Gone`).
- A leaked token is unusable without the owning session's cookie.

## Non-Goals

- Shareable / bearer links usable without login (redeem keeps session auth).
- Persisting handles across backend restarts (in-memory; re-click re-mints).
- Single-use tokens (reusable within the TTL — see Lifetime).
- Any change to Gate 1 (path ∈ turn assistant text) or Gate 2 **containment
  semantics** (realpath-inside-workspace on the node). (The markdown-link-aware
  grammar landed separately in `55d05db`; this design keeps using it.) Note: §6
  *does* add how the node **resolves the workspace root for imported/history
  threads** — the containment check itself is unchanged.

## Context (current behavior)

- `src/newbro/api/routes/workspace_files.py` exposes
  `GET /sessions/{session_id}/bro-threads/{thread_id}/turns/{turn_id}/file?path=…`.
  It runs `require_session_owner`, **Gate 1**
  (`path ∈ extract_path_tokens(turn.assistant.text)` → 403 `path_not_in_turn`),
  resolves the owning `node_id`, then streams via
  `executor_node_manager.read_workspace_file` with **Gate 2** on the node.
- `require_session_owner` (`api/public_auth.py`) raises **401** (no cookie) or
  **404** (not the owner) — never 403. So a 403 from this route is always Gate 1.
- The UI control (`workspace-file-link.tsx` → `WorkspaceFileLink`) builds the GET
  URL via `downloadUrl(path)` and does `fetch(url, {credentials:"include"})` →
  blob → programmatic `<a download>`.
- `markdown-text.tsx` builds `downloadUrl` from a `downloadContext`
  (`{sessionId, threadId, turnId, workspaceRoot}`) and renders the control for
  in-workspace absolute paths (bare or markdown-link form).

### Root-caused: the observed 403 was Gate 2 (no workspace binding for imported threads)

Diagnosed with logging on a live repro: **Gate 1 passes**; **Gate 2 denies** with
`code='denied' message='no workspace binding for thread'` for a
`codex-import-…` (imported codex *history*) thread. The node only records a
thread→workspace binding inside `_subscribe_codex_thread`, and only when the
subscribe carries a `workspace_id`. Imported history threads are viewed from the
imported snapshot without a workspace-bearing subscription, so the node's Gate-2
registry has nothing for them and every download from a history thread is denied.

The workspace is *known* to the backend (`BroThread.workspace_id = codex_thread.cwd`,
`session.py:1798` — which is why the UI control appears and the file is under it),
but it never reaches the node. The public thread id is
`codex-import-{sha256(persona_id:codex_thread_id)[:16]}` (`session.py:161`) — a
non-reversible hash that mixes in `persona_id`, so the node cannot derive the codex
thread from the public id.

**Fix (node-derived, keeps Gate 2 robust against a compromised backend):** see
§6. The node caches each codex thread's `cwd` (already present on every
`CodexThreadListItem` it returns from `list_threads`) and resolves the Gate-2 root
for an imported thread from that cache, selected by the codex thread id
(`executor_thread_id`) carried on the request. The workspace *root* stays
node-derived from codex's own cwd; the backend only supplies the thread *selector*.

This fix is part of this V1 (the temp-link redesign keeps Gate 2, so it would
otherwise inherit the same bug).

## Design

### 1. Token store — `src/newbro/runtime/workspace_file_handles.py`

A small, focused in-memory component owned by the runtime container.

```python
@dataclass(frozen=True)
class WorkspaceFileHandle:
    session_id: str
    thread_id: str
    executor_thread_id: str | None  # codex thread id; selects the Gate-2 workspace
    node_id: str
    path: str
    expires_at: float  # monotonic deadline

class WorkspaceFileHandleStore:
    def __init__(self, *, ttl_seconds: float = 300.0, now=time.monotonic) -> None: ...
    def mint(self, *, session_id, thread_id, executor_thread_id, node_id, path) -> str:
        """Store a new handle under a random token; return the token."""
    def resolve(self, token: str) -> WorkspaceFileHandle | None:
        """Return the live handle, or None if unknown/expired (evicting expired)."""
```

- Token = `secrets.token_urlsafe(16)` (≈128 bits, unguessable, URL-safe).
- `resolve` lazily evicts the token if `now() >= expires_at` and returns `None`.
- `mint` opportunistically sweeps expired entries (cheap; download volume is low)
  to cap memory.
- Reusable within the TTL: `resolve` does **not** delete a live handle.
- Process-local; lost on restart (acceptable — the user re-clicks).
- Wired onto the runtime container next to `executor_node_manager` so both routes
  reach it via `request.app.state.runtime_container`.

### 2. Mint route — `POST …/turns/{turn_id}/file-handle`

```
POST /api/sessions/{session_id}/bro-threads/{thread_id}/turns/{turn_id}/file-handle
body: { "path": "/abs/path" }
```

- `await require_session_owner(request, session_id)`.
- `session = container.get_session(session_id)` (404 `unknown_session` on KeyError).
- `snapshot = await session.snapshot()`; find the turn by `turn_id` AND `thread_id`
  (404 `unknown_turn`).
- **Gate 1:** `path ∈ extract_path_tokens(turn.assistant.text)` → else 403
  `path_not_in_turn`. (Same markdown-aware grammar as the current route.)
- Resolve `node_id` from the matching thread's `executor_node_id`, falling back to
  `executor_node_manager.node_id`; 504 `node_offline` if none.
- Read `executor_thread_id = turn.executor_thread_id` (the codex thread id; already
  on the turn) — the Gate-2 workspace selector (§6).
- `token = store.mint(session_id=…, thread_id=…, executor_thread_id=…, node_id=…, path=path)`.
- Return `{ "url": f"{API_PREFIX}/files/{token}", "expires_at": <iso8601> }`.

The path is only ever in the request body and the server-side store — never in a
URL.

### 3. Redeem route — `GET /api/files/{token}`

```
GET /api/files/{token}
```

- `user = await require_public_user(request)` (401 if no cookie).
- `handle = store.resolve(token)`; if `None` → **410 Gone** (`expired_or_unknown`).
- `await require_session_owner(request, handle.session_id)` — the authenticated
  user must own the bound session (404 if not). A stolen token is useless without
  that session's cookie.
- **Gate 2 / stream:**
  `executor_node_manager.read_workspace_file(node_id=handle.node_id,
  thread_id=handle.thread_id, executor_thread_id=handle.executor_thread_id,
  path=handle.path)`, pull the first chunk to map
  `WorkspaceFileDenied`/`WorkspaceFileUnavailable` to HTTP status before headers
  commit (403/404/413/502/504), then `StreamingResponse` with
  `Content-Disposition: attachment; filename="<basename(handle.path)>"`,
  `application/octet-stream`.

### 4. UI — `workspace-file-link.tsx` + `markdown-text.tsx`

- `markdown-text.tsx`: replace the `downloadUrl(path)` builder with a
  `mintUrl` builder (the `…/turns/{turnId}/file-handle` endpoint from
  `downloadContext`); `workspaceRoot`/affordance logic is unchanged.
- `WorkspaceFileLink.onClick` becomes two steps:
  1. `POST mintUrl` with `{ path }` and `credentials:"include"`. Non-OK → error
     state. Parse `{ url }`.
  2. `fetch(url, {credentials:"include"})` → non-OK → error state; else blob →
     object URL → programmatic `<a download={basename(path)}>` → revoke. (Same
     download mechanics as today, just preceded by the mint.)
- Inline states unchanged: idle / loading / error. Loading spans both requests.

### 5. Remove the old endpoint

Delete the path-bearing `GET …/turns/{turn_id}/file?path=` route and update its
tests to the new mint+redeem shape. No other consumers exist (only
`WorkspaceFileLink` called it).

### 6. Gate 2 for imported/history threads (the 403 fix)

The node must know an imported thread's workspace root for Gate 2, derived from
codex's own per-thread `cwd` (never from the request path). Changes:

- **Protocol:** `ReadWorkspaceFileCommand` gains
  `executor_thread_id: str | None = None`. This is a thread *selector*, not a
  path — the workspace root is still computed on the node.
- **Node — cache codex thread cwds.** In `_list_codex_threads`
  (`executors/node/service.py`), after building the `CodexThreadListItem` list,
  record `self._codex_thread_workspaces[item.thread_id] = item.cwd` for every item
  with a non-empty `cwd`. `list_threads` already runs during import sync, so the
  cache covers all imported history threads. (Add the dict in `__init__`.)
- **Node — resolve the Gate-2 root.** In `_read_workspace_file`, compute:
  1. `root = self._thread_workspaces.get(command.thread_id)` (live/subscribed
     threads — unchanged), else
  2. if `command.executor_thread_id`:
     `root = self._codex_thread_workspaces.get(command.executor_thread_id)`, else
  3. `root is None` → `WorkspaceFileError(code="denied", message="no workspace
     binding for thread")` (unchanged).
  Then the existing `resolve_within_workspace(command.path, root)` containment +
  streaming is unchanged.
- **Node-manager:** `read_workspace_file(...)` gains an `executor_thread_id`
  parameter and forwards it on the `ReadWorkspaceFileCommand`.
- **Backend mint:** reads `turn.executor_thread_id` from the snapshot turn and
  stores it on the handle (§2); redeem forwards it (§3).

Security note: the workspace *root* is taken from codex's own thread cwd cached on
the node — the backend/request can only *select which codex thread*, not supply an
arbitrary root. A compromised backend can at most point at another real codex
thread's cwd (still bounded; Gate 1 also still applies). This preserves Gate 2's
"holds even if the backend is compromised" property for the root itself.

## Error Handling

- **Mint:** 401 (no cookie) / 404 (`unknown_session` | `unknown_turn` | not owner)
  / 403 (`path_not_in_turn`) / 504 (`node_offline`).
- **Redeem:** 401 (no cookie) / 410 (`expired_or_unknown` token) / 404 (not the
  bound session's owner) / Gate-2 mapping 403·404·413·502·504.
- UI surfaces a single inline "download failed" state for any non-OK at either
  step (the existing pattern); the control never navigates to a raw path.

## Testing

- **Store unit** (`tests/unit/runtime/…`): `mint` returns distinct high-entropy
  tokens; `resolve` returns the live handle; `resolve` returns `None` and evicts
  after expiry (inject a fake clock); a live handle is reusable across multiple
  `resolve` calls; expired entries are swept on `mint`.
- **Mint route:** Gate 1 allow (path in turn) returns an opaque `/api/files/<tok>`
  url whose token is **not** the path; path **not** in turn → 403; unknown turn →
  404; path travels in the body (assert the response url contains no path); auth
  required.
- **Redeem route:** valid token streams the bytes (stub `read_workspace_file`,
  asserting it is called with the handle's `executor_thread_id`); expired token →
  410; unknown token → 410; token bound to a session the caller doesn't own → 404;
  Gate-2 `denied`/`not_found`/`too_large`/offline → 403/404/413/504.
- **Node Gate-2 binding** (`tests/executors/node/…`): after a
  `_list_codex_threads` that returns an item with `thread_id`+`cwd`, a
  `_read_workspace_file` for an in-`cwd` path with that `executor_thread_id`
  streams; with no matching `executor_thread_id` and no subscribe binding → denied;
  an item with empty `cwd` is not cached. Plus the existing containment matrix
  still holds once a root is resolved.
- **UI** (`workspace-file-link` / `markdown-text`): clicking mints (POST to the
  `file-handle` url with `{path}` body) then downloads the returned opaque url;
  mint failure and redeem failure each show the error state; no request URL
  contains the path.

## Files

- Create: `src/newbro/runtime/workspace_file_handles.py` (+ unit test).
- Modify: `src/newbro/api/routes/workspace_files.py` — replace the GET route with
  the mint POST + redeem GET; wire the store from the container.
- Modify: `src/newbro/runtime/container.py` (`RuntimeContainer.__init__`, where
  `self.executor_node_manager = ExecutorNodeManager(…)` is built ~line 28) —
  instantiate `self.workspace_file_handles = WorkspaceFileHandleStore()` so both
  routes reach it via `request.app.state.runtime_container.workspace_file_handles`.
- Modify: `src/newbro/ui/src/components/ui/workspace-file-link.tsx` (mint→fetch),
  `src/newbro/ui/src/components/ui/markdown-text.tsx` (mintUrl context).
- **Gate-2 fix:** `src/newbro/protocol/executor_node.py`
  (`ReadWorkspaceFileCommand.executor_thread_id`);
  `src/newbro/executors/node/service.py` (`_codex_thread_workspaces` cache in
  `_list_codex_threads`; resolve it in `_read_workspace_file`);
  `src/newbro/runtime/executor_node_manager.py`
  (`read_workspace_file(..., executor_thread_id=…)` forwards it on the command).
- Update: `tests/api/routes/test_workspace_files_route.py` and the UI tests to the
  new shape.
- **Remove the temporary `[dl-gate1]`/`[dl-gate2]` diagnostics** added to
  `workspace_files.py` during root-causing.
