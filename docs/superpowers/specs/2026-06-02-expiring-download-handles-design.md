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

Gate 1 and Gate 2 semantics are unchanged; only the *addressing* of the download
changes.

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
- Any change to Gate 1 (path ∈ turn assistant text) or Gate 2 (node workspace
  containment) **semantics**. (The markdown-link-aware grammar landed separately
  in `55d05db`; this design keeps using it.)

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

### Resolved: the observed 403 on a markdown-link download

The 403 seen during manual testing is Gate 1, and is consistent with the backend
process still serving the **pre-`55d05db` grammar** (the old whitespace-split
grammar returns ∅ for a markdown-link path). The frontend had been rebuilt (so the
control appeared) but the backend module had not reloaded. **Restarting the backend
loads the markdown-aware grammar and Gate 1 passes.** This redesign keeps Gate 1 at
the mint step using that same grammar, so once the backend runs current code the
403 is resolved.

Contingency (only if a clean restart does not fix it): the UI's rendered answer
text falls back to the task summary/description when `turn.assistant` is empty
(`ArtboardShell.tsx:1228`), while Gate 1 reads only `turn.assistant.text`. If that
divergence is the real cause, Gate 1 at mint should validate the path against the
turn's **rendered** assistant text (assistant message, falling back to
summary/description) so the UI and backend cannot disagree. This is a contingency,
not part of V1 unless reproduced.

## Design

### 1. Token store — `src/newbro/runtime/workspace_file_handles.py`

A small, focused in-memory component owned by the runtime container.

```python
@dataclass(frozen=True)
class WorkspaceFileHandle:
    session_id: str
    thread_id: str
    node_id: str
    path: str
    expires_at: float  # monotonic deadline

class WorkspaceFileHandleStore:
    def __init__(self, *, ttl_seconds: float = 300.0, now=time.monotonic) -> None: ...
    def mint(self, *, session_id, thread_id, node_id, path) -> str:
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
- `token = store.mint(session_id=…, thread_id=…, node_id=…, path=path)`.
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
- **Gate 2 / stream:** identical to today —
  `executor_node_manager.read_workspace_file(node_id=handle.node_id,
  thread_id=handle.thread_id, path=handle.path)`, pull the first chunk to map
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
- **Redeem route:** valid token streams the bytes (stub `read_workspace_file`);
  expired token → 410; unknown token → 410; token bound to a session the caller
  doesn't own → 404; Gate-2 `denied`/`not_found`/`too_large`/offline → 403/404/
  413/504.
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
- Update: `tests/api/routes/test_workspace_files_route.py` and the UI tests to the
  new shape.
