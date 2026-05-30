# Filter Codex Ephemeral Threads From Bro Detail Imports

Date: 2026-05-30
Status: Approved for implementation planning.

## Problem

When the user opens the Bro Detail "new thread" workspace picker, it shows many
"strange" workspaces — including cwds under `~/.codex/`. These come from Codex
ephemeral/scratch threads that Codex returns in `thread/list` alongside real
project threads. They are not workspaces the user has intentionally used, and
they clutter the picker and (as duplicate entries) the Bro Detail thread list.

## Root Cause

`_sync_imported_codex_threads()` in `src/newbro/runtime/session.py:1679-1781`
imports every Codex thread returned by `thread/list` into the persona's
`imported_threads` projection, regardless of whether Codex marked the thread
as ephemeral. The picker (`_known_codex_workspaces_for_persona()` at
`session.py:3270`) then derives its workspace list from
`imported.workspace_id` and the persisted `codex_cwd` diagnostic, so every
ephemeral cwd Codex has ever opened ends up offered to the user.

Codex itself already flags these threads. The node service at
`src/newbro/executors/node/service.py:1124` passes the Codex
`ephemeral` field through into `CodexThreadListItem.diagnostics["ephemeral"]`,
but no consumer reads it.

## Goal

Drop Codex-flagged ephemeral threads at import time so they never appear in:

- the Bro Detail new-thread workspace picker,
- `_known_codex_workspaces_for_persona()` validation,
- the Bro Detail thread list.

## Non-Goals

- No cwd-based blocklist (e.g. filtering `~/.codex/`, `/tmp`, `~/Library`).
- No filesystem-allowlist signal (e.g. looking for `.git`, `package.json`).
- No per-persona workspace narrowing.
- No protocol-model change. `diagnostics["ephemeral"]` already flows through.
- No frontend change. The picker reads whatever the snapshot exposes.

If Codex does not tag a thread as ephemeral, this design does not filter it.

## Design

### Filter Semantics

A thread is treated as ephemeral when
`codex_thread.diagnostics.get("ephemeral") is True`. Any other value —
`False`, `None`, missing key, or a non-boolean value — is treated as
non-ephemeral. Codex's flag is the only signal.

### Change Point

`src/newbro/runtime/session.py:1679` — `_sync_imported_codex_threads()`.

Inside the per-thread loop (currently around line 1726, after the
`existing_codex_thread_ids` skip), add an ephemeral check and `continue`
before any `imported_threads[...]` or `imported_resume_handles[...]` write.

A small helper, `_is_ephemeral_codex_thread(codex_thread) -> bool`, lives
next to the sync function and isolates the rule for unit testing.

### Why Only This One Place

`_known_codex_workspaces_for_persona()` derives its workspace set from
`imported.workspace_id` and the persisted `codex_cwd` diagnostic. Both are
written by `_sync_imported_codex_threads()`. Filtering at the sync point
removes ephemeral entries from the picker and from new-thread workspace
validation in one shot. The Bro Detail thread list also renders from the
imported projection, so ephemeral threads disappear from the list with no
separate change.

### Observability

Augment the sync-level diagnostic already emitted by
`_sync_imported_codex_threads()` to also include `skipped_ephemeral_count: int`
counted across the whole sync invocation (one number per call, not per
persona iteration). This makes the filter debuggable from the existing
diagnostics timeline without introducing a new event type. The exact event
name to extend is confirmed during implementation by reading the current
emission site; if no existing sync-level event carries the import counts,
extend the closest equivalent rather than adding a new event type.

### Data Flow After The Change

1. Executor node returns `thread/list` items, each potentially carrying
   `ephemeral=true`.
2. `_codex_thread_list_item()` (`executors/node/service.py:1100`) stores
   `ephemeral` under `diagnostics["ephemeral"]` (unchanged).
3. `_sync_imported_codex_threads()` reads the diagnostic. Items with
   `ephemeral is True` are skipped before projection. The sync's diagnostic
   event records how many were skipped.
4. `imported_threads` only contains non-ephemeral threads. The Bro Detail
   thread list, the new-thread workspace picker, and
   `_validate_new_codex_thread_workspace()` all reflect that automatically.

## Tests

Target file: `tests/unit/runtime/test_session_runtime.py` (or the existing
sibling file that already exercises `_sync_imported_codex_threads`).

- `ephemeral=True` thread is excluded from `imported_threads` and from the
  workspace set returned by `_known_codex_workspaces_for_persona()`.
- `ephemeral=False` thread is imported and its cwd appears in the workspace
  set (regression guard).
- `ephemeral=None` and a thread with no `ephemeral` key are imported
  (regression guard, default-allow behavior).
- A non-boolean `ephemeral` value is treated as non-ephemeral (defensive).
- The sync diagnostic carries the correct `skipped_ephemeral_count` when a
  mix of ephemeral and non-ephemeral threads is returned.

No new integration test is required. The protocol model is unchanged and the
frontend behavior follows automatically from the snapshot.

## Risks

- Codex may begin marking threads we *do* want to keep as ephemeral
  (unlikely for the user's case, but possible). The diagnostic counter makes
  this visible in the timeline so we can revisit if it happens.
- Old persisted `imported_threads` may still contain ephemeral entries from
  before the change. Sync runs project from the current `thread/list`
  response, so a single subsequent sync should clear stale entries; no
  explicit migration step is needed.

## Out Of Scope For This Spec

- Removing the persona × thread fanout in `_sync_imported_codex_threads()`
  (one BroThread per persona per Codex thread). Separate concern; revisit
  only if duplicates remain after ephemeral filtering.
- Surfacing the ephemeral filter rule in the UI.
