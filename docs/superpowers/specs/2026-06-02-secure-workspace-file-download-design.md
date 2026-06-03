# Secure Workspace-File Download from Assistant Responses — Design

Status: design (approved for planning)
Date: 2026-06-02

## Summary

When an assistant response mentions a file path, the user wants to click and
download that file. The file lives on the **executor node** — a separate machine
(the user's own Mac running the executor app) that connects to the backend over
the existing `/executors/control` WebSocket. Naively fetching any path off that
machine would be an arbitrary-file-exfiltration vector (`/etc/passwd`,
`~/.ssh/id_rsa`).

The design makes a file downloadable only when **two layered gates** both pass:

1. **Content binding (backend, authoritative).** The request is bound to a
   specific turn — `thread_id` + `turn_id` + `path` — and the backend requires
   `path` to appear as an exact path-token in that turn's stored assistant
   content. The client cannot request a path the assistant did not write in that
   exact message. This kills URL injection.
2. **Workspace containment (node).** The node `realpath()`s the file and requires
   it to resolve inside the thread's workspace root (symlinks resolved, no
   traversal, regular file, size cap). This stops a prompt-injected/compromised
   assistant that writes an out-of-workspace path into its reply from making that
   file downloadable.

Bytes travel over the node's existing control WebSocket as base64 chunks
(no new connections), which the backend reassembles and streams to the browser as
an attachment download.

## Goal / Success Criteria

- A user can click a "Download" control next to an absolute path that the
  assistant wrote in a message, and the corresponding workspace file downloads in
  the browser.
- It is **not possible** to download a file that (a) the assistant did not write
  in the referenced turn, or (b) resolves outside the thread's workspace — even by
  hand-crafting the request URL.
- The backend never reads the filesystem itself; the node is the sole filesystem
  authority.

## Non-Goals (V1)

- Node-side approval prompt / per-file egress confirmation, and node-side audit
  logging — explicitly deferred (boundary checks are the V1 guarantee).
- Detecting **relative** paths or paths **containing spaces** (too noisy to detect
  reliably). V1 detects absolute paths only.
- Browser → node **uploads**. This is download-only.
- Directory / multi-file / zip downloads (single file per request).
- Inline preview/rendering of the file.
- Excluding secret files (e.g. `.env`) that live **inside** the workspace — within
  the workspace the boundary equals the assistant's own read scope (see Accepted
  Consequences).

## Context (current behavior)

- **Topology.** Browser (UI) ↔ backend/runtime (FastAPI, possibly remote) ↔
  executor node. The node is the WebSocket *client*; it dials the backend at
  `/executors/control` (`src/newbro/api/ws/executors.py`). The backend cannot open
  a socket to the node — all node interaction is request/response over that one WS,
  correlated by `request_id`.
- **Workspace = a real directory.** `codex` runs with
  `cwd = Path(workspace_id).resolve()` and `sandbox=workspace-write`
  (`src/newbro/executors/adapters/codex/executor.py:71`). Each thread is bound to
  one workspace directory; that is the area the assistant legitimately reads/writes.
  The thread's `workspace_id` is already present in snapshots and on the UI thread
  model.
- **Turns are stored server-side.** `BroTimelineTurn`
  (`src/newbro/protocol/session.py:124`) has `turn_id`, `thread_id`, and
  `assistant: BroTimelineMessage | null` whose `.text` holds the rendered assistant
  content. The backend therefore has authoritative access to exactly what the
  assistant wrote in each turn.
- **No file-read capability exists** in the protocol today. The download path is
  entirely new.
- **Links render inert.** `MarkdownText`
  (`src/newbro/ui/src/components/ui/markdown-text.tsx`) renders links as
  `<a target="_blank">`; an absolute/`file://` path does nothing useful from a
  browser origin.

## Design

### 1. Authorization — two layered gates

Request shape (session-authenticated):

```
GET /threads/{thread_id}/turns/{turn_id}/file?path=<absolute-path>
```

**Gate 1 — content binding (backend).** The backend:
- Authenticates the session user and confirms the user can access `thread_id`.
- Loads the stored `BroTimelineTurn` for (`thread_id`, `turn_id`).
- Extracts path-tokens from that turn's **assistant** message text (`turn.assistant.text`)
  using the shared Path-Token Grammar (§2).
- Requires the requested `path` to **exactly equal** one of those tokens. No
  substring matching (so `/etc/passwd` does not match content `/etc/passwd.txt`).
- On failure → `403 Denied` (path not in content) or `404` (no such turn).

**Gate 2 — workspace containment (node).** The backend resolves which node owns
the thread's workspace and relays a `ReadWorkspaceFileCommand` (§4). The node:
- Derives `workspace_root` **from its own authoritative thread/session binding**
  for `thread_id` (the workspace it used when creating/subscribing that thread's
  session) — **not** from any backend- or client-supplied value, so Gate 2 holds
  even if the backend is compromised. If the node has no workspace binding for
  `thread_id`, it returns `denied`.
- Resolves the path (absolute → as-is) and computes `real = realpath(path)` and
  `root = realpath(workspace_root)`.
- Requires `real == root` or `real.startswith(root + os.sep)`. Else `denied`.
- Requires an existing, readable **regular file** (not a directory, device,
  socket, FIFO). Else `not_found` / `denied`.
- Enforces the **size cap** (default 100 MB). Else `too_large`.

Both gates must pass. The two gates are independent: Gate 1 stops requests for
paths the assistant never wrote; Gate 2 stops in-message paths that point outside
the workspace.

### 2. Path-Token Grammar (shared contract)

"Part of the message content" means: an **absolute path** that begins at a token
boundary in the turn's assistant text.

- A token begins at a **boundary** — string start, whitespace, or an opening
  bracket/brace/angle/quote/backtick — so paths written bare, in backticks/quotes/
  parentheses, **or as a markdown link target** `[label](/abs/path)` are all
  detected. (Assistants commonly emit file references as markdown links, so this
  case matters in practice.)
- The path starts with `/` (POSIX) and runs until whitespace or a closing
  bracket/brace/angle/quote/backtick; trailing sentence punctuation
  (`. , ; : ! ?`) is then stripped; NUL-containing tokens are rejected.
- A **relative** path (`out/x`) is not matched (its `/` follows a word char) and a
  **URL** (`https://…`) is not matched (its `//` follows `:`).
- V1 ignores paths containing spaces.

The backend (Gate 1) and the client (affordance, §3) implement the **same grammar**
so the set of clickable paths equals the set of accepted paths. The grammar is
specified by a shared set of fixtures both test against (backtick-wrapped, trailing
punctuation, quote-wrapped, non-path tokens).

### 3. UI affordance

- `MarkdownText` receives the thread's `workspaceRoot`, the `turnId`, and the
  thread/bro context needed to build the download URL.
- A path-token helper finds absolute-path tokens (§2 grammar) in the rendered
  assistant text and, **for those that fall under `workspaceRoot`**, replaces the
  plain text with a "↓ Download `<basename>`" control linking to the turn-scoped
  endpoint with `path` set to the token.
- Absolute paths **outside** `workspaceRoot`, and any non-path text, render as plain
  text — no control. (Gate 2 is still the real enforcement; this is clean UX so
  users are not offered downloads that would be denied.)
- The control is only rendered when the thread is a runtime thread with a known
  workspace and a connected owning node; otherwise the path stays plain text.

### 4. Transport / data flow

Chunked over the existing control WS (no new connections, fits the thin JSON
command/ack/event transport and `request_id` correlation):

```
click ↓ Download
  → GET /threads/{tid}/turns/{turnId}/file?path=…        (browser → backend)
  backend: auth + Gate 1 (path ∈ turn.assistant text)
           → resolve owning node + workspace_root
           → new request_id
  ── ReadWorkspaceFileCommand(request_id, thread_id, path) ──WS──► node
                                                          node: Gate 2
  ◄── WorkspaceFileChunk(request_id, seq, data_b64) × N ─────────  (stream)
  ◄── WorkspaceFileEof(request_id, total_bytes[, sha256])
      | WorkspaceFileError(request_id, code, message) ───────────
  backend reassembles → streams attachment to browser
      Content-Disposition: attachment; filename="<basename>"
      Content-Type: application/octet-stream
```

- **Chunk size:** 256 KB of raw bytes per chunk (base64-encoded on the wire).
- **Backpressure:** the node awaits send completion per chunk before reading the
  next.
- **Backend mapping:** node `code` → HTTP status: `denied` → 403, `not_found` →
  404, `too_large` → 413, node offline / timeout / disconnect → 504.
- The backend streams to the browser as chunks arrive (it does not buffer the whole
  file), tearing down on client disconnect.

### 5. Protocol additions

New node-level messages (multi-executor compatible; not codex-specific),
correlated by `request_id`:

- `ReadWorkspaceFileCommand { request_id, thread_id, path }`
  (deliberately carries **no** `workspace_root` — the node derives it from its own
  thread/session binding, per Gate 2)
- `WorkspaceFileChunk { request_id, seq, data /* base64 */ }`
- `WorkspaceFileEof { request_id, total_bytes, sha256? }`
- `WorkspaceFileError { request_id, code, message }`
  with `code ∈ { denied, not_found, too_large, read_error }`.

### 6. Components / files

- **Protocol:** new models in `src/newbro/protocol/` (executor-node command +
  result family), exported alongside the existing executor-node messages.
- **Node:** new handler in `src/newbro/executors/node/service.py`, with the
  validation + streaming logic extracted into a focused, independently testable
  `src/newbro/executors/node/workspace_files.py` (resolve, containment check,
  regular-file check, size cap, chunk generator).
- **Backend:**
  - `src/newbro/runtime/executor_node_manager.py` — relay the command to the owning
    node and expose the chunk stream (an async generator keyed by `request_id`).
  - `src/newbro/api/routes/…` — the turn-scoped download route: auth, Gate 1 against
    the stored turn, call into the node manager, stream the attachment, map error
    codes → HTTP status. Wire into the app.
- **UI:**
  - `src/newbro/ui/src/components/ui/markdown-text.tsx` + a path-token helper
    (e.g. `lib/workspace-paths.ts`) — detection + Download control.
  - `src/newbro/ui/src/ArtboardShell.tsx` — pass `workspaceRoot`, `turnId`, and
    thread context into `MarkdownText` at the assistant-message call sites.

## Error Handling

- The backend never falls back to reading the file itself (it may be on a different
  machine; the node is the authority). Failures surface as HTTP errors, not silent
  empties.
- UI states for a Download control: idle, fetching, denied (outside workspace),
  not found, node offline, too large — surfaced as a concise inline message/toast.
- Backend maps node error `code` → HTTP status as in §4.

## Edge Cases

- **Substring trick:** request `path=/etc/passwd` when the turn text contains
  `/etc/passwd.txt` → Gate 1 exact-token match **denies** (different token).
- **Symlink inside workspace pointing outside:** Gate 2 `realpath()` resolves it;
  resolves outside `root` → **denied**.
- **`..` traversal / absolute escape inside the in-message path:** resolved by
  `realpath()` then containment check → **denied**.
- **Wrong turn_id (path real, but in a different turn):** Gate 1 → **denied**.
- **Directory path:** regular-file check → **denied/not_found**.
- **File deleted between render and click:** Gate 2 `not_found` → 404, UI shows
  "file no longer available".
- **Node offline:** 504, UI shows "your machine isn't connected".
- **Path containing spaces / relative path:** not detected in V1 (no control
  rendered); if hand-crafted, Gate 1 only accepts tokens it would have extracted, so
  a space-containing request fails the grammar/token check.

## Accepted Consequences

- **Dotfiles/secrets inside the workspace are downloadable** (e.g. `.env`,
  `.git/config`) when the assistant writes their absolute path into a message. This
  equals the assistant's own read scope within the workspace. Excluding sensitive
  files within the workspace is a possible follow-up, not V1.

## Testing

- **Backend Gate 1 (content binding):** path present in `turn.assistant.text` →
  allowed; path absent → 403; substring-only (`/etc/passwd` vs `/etc/passwd.txt`)
  → 403; unknown `turn_id` → 404; thread the user cannot access → 403/404; auth
  required.
- **Node Gate 2 (security core, exhaustive):** in-workspace file, nested file,
  `..` escape, absolute-outside, **symlink-inside→outside**, directory,
  nonexistent, **too-large** (> cap). ALLOW/DENY matrix.
- **Path-Token Grammar:** backend and client run the **same fixtures** —
  backtick-wrapped path, trailing punctuation, quote-wrapped, plain prose with no
  path, absolute vs relative, space-containing (ignored).
- **Transport:** chunked round-trip reassembles byte-identically (incl. binary);
  EOF total/`sha256` matches; `WorkspaceFileError` maps to the right HTTP status;
  backend streams without buffering the whole file; client-disconnect tears down.
- **UI:** Download control rendered only for in-workspace absolute paths in a
  turn; out-of-workspace path stays plain; control targets
  `/threads/{tid}/turns/{turnId}/file?path=…`; error states render; no control when
  node offline / no workspace.
- **Protocol:** model round-trip (serialize/deserialize) for the four new messages.

## Defaults (confirmed)

- Size cap **100 MB** (configurable); chunk **256 KB**.
- Direct download on click (no confirmation dialog).
- Absolute-paths-only detection in V1.
- Dotfiles inside the workspace allowed.
