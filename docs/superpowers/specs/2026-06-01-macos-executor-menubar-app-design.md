# macOS Menu-Bar Executor App — Design

Status: design (approved for planning)
Date: 2026-06-01

## Summary

Package the existing detached executor node as a native, double-clickable
macOS **menu-bar app** so the user can run and manage executor nodes without
living in a terminal.

The app is a thin **supervisor + config editor** over the existing
`newbro executor run` CLI contract. It does **not** reimplement any node or
protocol behavior. All live execution stays inside `ExecutorNodeService`,
reached only by spawning `newbro executor run` subprocesses.

The app supports **multiple node profiles**, each representing an independent
executor instance, and can run **several profiles concurrently** — one node
subprocess per active profile.

## Goals

- Start, stop, and monitor executor nodes from a macOS menu-bar status item.
- Manage multiple node profiles, each with its own identity and enabled
  executors.
- Run several profiles at the same time, independently.
- Auto-connect on launch and run at login, controllable per profile.
- Reuse the existing Python node service, config loader, and CLI contract.
- Surface connection state (connecting / ready / disconnected / error) clearly.
- Keep deeper executor runtime config (binary paths, audio) owned by the
  existing `newbro executor setup` flow — no duplication.

## Non-Goals

- Enrolling / issuing new node credentials from the app. Credentials are still
  issued by the server and surfaced through the web UI's connect command; the
  app consumes them (paste or manual entry).
- Owning per-profile executor binary paths or Whisper/audio config. That stays
  machine-level in `~/.newbro/`, set via `newbro executor setup`.
- Cross-platform UI. This is macOS-only; dependencies are an optional install
  extra so Linux/server installs are unaffected.
- Replacing or bypassing the `newbro executor run` CLI path.

## Scope Decisions (resolved during brainstorming)

- **App role:** run + edit connection credentials + live status. Not an
  enrollment client.
- **Presence:** menu-bar status item only (no Dock icon, no main window beyond a
  small settings window).
- **Autostart:** launches at login (login item) and auto-activates the profiles
  the user marked `auto_activate`.
- **Tech stack:** Python `rumps` for the status item, bundled to a `.app` with
  `py2app`.
- **Node execution:** subprocess via `newbro executor run` (not in-process), for
  crash isolation and reuse of the tested CLI path.
- **Profiles:** multiple profiles, each an independent executor instance;
  several run concurrently.
- **Deep runtime config:** shared, machine-level, owned by
  `newbro executor setup`. Profiles differ only by identity (base URL, node_id,
  token) and which executor families they enable.
- **macOS-only deps:** optional install extra (e.g. `pip install .[macos-ui]`).

## Architecture

The app lives at `src/newbro/executors/ui/` — a sibling of
`src/newbro/executors/node/`. It is a UI surface over the node, not part of the
node runtime.

```
┌──────────────────────────────────────────────────────────┐
│ Newbro Executor.app  (rumps status item)                  │
│                                                            │
│  MenuBarApp ── renders aggregate icon + per-profile menus  │
│      │                                                     │
│  ProfileSupervisor ── map: profile_id → (Controller,State) │
│      │            │            │                           │
│  NodeProcessController   StatusModel   (one pair per       │
│      │                                  active profile)    │
│      ▼                                                     │
│  subprocess: newbro executor run --base-url … --node-id …  │
│              --token … --enabled-executor …                │
│                                                            │
│  ProfileStore (~/.newbro/menubar.json)                     │
│  LoginItem    (~/Library/LaunchAgents/…plist)              │
└──────────────────────────────────────────────────────────┘
        │ outbound WS  (unchanged)
        ▼
   Newbro control plane  WS /api/executors/control
```

### Boundary principle

The menu app is a thin supervisor + config editor. Node/protocol behavior stays
in `ExecutorNodeService`, reached only through the `newbro executor run` CLI
contract. This respects AGENTS.md's "keep transport thin" guardrail and the
detached-node ownership boundary in `docs/architecture/executors.md`.

## Components

### `ProfileStore`

Reads/writes the profile list in `~/.newbro/menubar.json`. Each profile:

| field               | meaning                                            |
| ------------------- | -------------------------------------------------- |
| `id`                | stable, app-generated profile id                   |
| `label`             | user-facing name for the profile                   |
| `base_url`          | Newbro control-plane base URL                      |
| `node_id`           | server-issued node id                              |
| `token`             | server-issued node token                           |
| `enabled_executors` | per-profile list, e.g. `["codex"]`                 |
| `auto_activate`     | start this profile on app launch                   |

Responsibilities:

- Load / save the profile list (JSON round-trip).
- Parse a pasted **connect command** into a new or updated profile, extracting
  `--base-url`, `--node-id`, `--token` (and `--enabled-executor` if present) —
  the same shape the web UI's install/update-and-connect command emits.
- Validate on save and **warn if two profiles share the same `node_id` +
  `base_url`** (the server rejects a duplicate live `node_id`).

It writes **only** `menubar.json`. It never writes the `~/.newbro/` connector
config.

### `NodeProcessController`

Wraps `subprocess.Popen` of one `newbro executor run …` invocation for a single
profile. Responsibilities:

- Start, stop (SIGTERM, then SIGKILL on timeout), restart.
- Read child stdout/stderr on a reader thread; emit raw lines + lifecycle
  events (started / exited-with-code).

It does **not** interpret meaning — it surfaces raw lines and process events.

One instance exists per **active** profile.

### `StatusModel`

Interprets one controller's line stream into a state enum:

```
idle → starting → connecting → ready → disconnected/retrying → error → stopped
```

It maps the known explicit `newbro executor run` output lines (connect / ready /
disconnect / retry) onto states, relying on the documented contract: *"foreground
`newbro executor run` output should make connect, ready, disconnect, and retry
state explicit, and should only report ready after the control-channel
registration handshake succeeds"* (`docs/architecture/executors.md`).

One instance exists per active profile. This is the core testable logic.

### `ProfileSupervisor`

Owns the map `profile_id → (NodeProcessController, StatusModel)`.

Responsibilities:

- Start / stop / restart a profile by id.
- Independent lifecycle per profile: one profile crashing, hitting a bad token,
  or backing off never affects another.
- Compute an **aggregate** status for the menu-bar icon.
- Stop **all** subprocesses on quit (SIGTERM → SIGKILL).
- Per-profile capped exponential backoff on unexpected exit; no tight retry loop
  on a known-bad credential (enter `error` and stop after bounded attempts).

### `MenuBarApp` (rumps.App)

Owns the status-bar icon, the dropdown menu, and the small settings window. Pure
UI + event wiring; holds no protocol logic. Marshals `StatusModel` updates to
the main thread for menu/icon refresh.

### `LoginItem`

Installs/removes `~/Library/LaunchAgents/com.newbro.executor-ui.plist` pointing
at the built `.app`, toggled from the menu. Global (app-level), not per profile.

## Data Flow

### Startup (auto-connect)

1. App launches (manually or via login item).
2. `MenuBarApp` loads profiles via `ProfileStore`.
3. For each profile with `auto_activate = true` and complete settings,
   `ProfileSupervisor.start(profile_id)` spawns its `newbro executor run …`
   subprocess. Menu shows `starting` for that profile.
4. Profiles with incomplete settings show a "needs setup" state and are not
   started.

### Status

- Each controller's reader thread feeds raw lines to that profile's
  `StatusModel`, which updates state and notifies `MenuBarApp` on the main
  thread.
- Per-profile submenu shows its own state, identity, and enabled executors.
- The aggregate menu-bar icon reflects the worst/most-relevant state across
  profiles: `● ready` (any ready), `◌ connecting`, `⚠ error`, `○ all idle`.
- A bounded ring buffer (≈200 lines) per profile backs "View recent log…" and is
  also written to `~/.newbro/logs/executor-ui-<profile_id>.log`.

### Edit credentials

- **Paste connect command:** reads the clipboard, parses
  `--base-url/--node-id/--token`, and creates or updates a profile (fast path
  matching how credentials are issued today).
- **Manual edit:** a small settings window for `label`, `base_url`, `node_id`,
  `token`, `enabled_executors` (codex/acpx checkboxes), and `auto_activate`.
- On save: if the profile is running, stop it, rewrite `menubar.json`, then
  restart with the new args. Credential changes are always an explicit
  stop/start, never a hot mutation.

### Deep runtime config dependency (no-TTY)

`newbro executor run` requires the local executor runtime config (codex/acpx
paths, audio) and, in a TTY, would launch interactive setup. A bundled `.app`
has **no TTY**, so the app will **not** trigger interactive setup.

Before first start the app checks completeness (reuse the existing
`executor_runtime_config_complete` resolver). If incomplete, it shows a clear,
actionable message — *"Run `newbro executor setup` in a terminal to configure
executor commands, then return here"* — rather than failing opaquely. This
respects the AGENTS.md golden rule: surface the real gap; no silent fallback.

## Menu UX

```
Newbro Executor              ← aggregate icon: ●ready / ◌connecting / ⚠error / ○idle
──────────────────
Prod · ● Ready          ▸     node-1a2b · synopse.example.com · codex
                              Stop · Restart · Edit… · Delete
Staging · ○ Stopped     ▸     Start · Edit… · Delete
──────────────────
Add profile…
Paste connect command…       ← creates/updates a profile from clipboard
View recent log…             ← per-profile logs
──────────────────
Launch at login        ✓
Quit                         ← stops all node subprocesses
```

Each profile is a submenu showing its status, identity, enabled executors, and
the lifecycle/edit actions relevant to its current state (Start when stopped;
Stop/Restart when running).

## Error Handling

- **Incomplete runtime config** → "needs setup" state + terminal guidance.
- **Auth/registration failure** (bad node_id/token) → node process exits/logs
  the rejection; that profile's `StatusModel` enters `error`; menu shows ⚠ with
  the reason; bounded backoff, then stop — no tight retry loop on a known-bad
  credential.
- **Unexpected process crash** (valid credentials) → controller detects exit;
  supervisor restarts with capped exponential backoff; profile shows
  "retrying".
- **Duplicate node_id** across profiles pointed at the same `base_url` → warn on
  save; the server would otherwise reject the second live connection.
- **Quit / termination** → supervisor SIGTERMs every child and waits, SIGKILL on
  timeout, so no orphaned node subprocess.

Errors are always per profile; one failing profile never disturbs another.

## Packaging & Distribution

- `py2app` setup script (e.g. `packaging/menubar/setup.py`) builds
  `Newbro Executor.app`, bundling the `newbro` package + `rumps`.
- The bundled app invokes the node via the **in-bundle Python** running
  `python -m newbro.executors.node …` (no reliance on a system `newbro` on
  PATH).
- `rumps` (and `py2app` for building) are an **optional install extra**, e.g.
  `pip install .[macos-ui]`, so Linux/server installs are unaffected.
- Optional dev convenience: a `newbro executor ui` CLI subcommand that launches
  the same `MenuBarApp` from the repo venv without building the `.app`.
- Login item: `LoginItem` writes/removes
  `~/Library/LaunchAgents/com.newbro.executor-ui.plist`.

## Testing

- **`StatusModel`** — feed representative `newbro executor run` stdout line
  sequences (connect → ready → disconnect → retry, auth-reject, crash) and
  assert state transitions. Core logic, fully testable without a UI.
- **`NodeProcessController`** — with a fake child script: assert start / stop /
  restart, SIGTERM-then-SIGKILL, and line capture.
- **`ProfileSupervisor`** — concurrent start/stop of multiple profiles,
  independent per-profile failure, and aggregate-status computation.
- **`ProfileStore`** — round-trip a multi-profile `menubar.json`; parse a
  connect command into a profile; duplicate-`node_id` warning; completeness
  check delegating to the existing resolver.
- **`LoginItem`** — plist render + install/remove against a temp dir.
- The rumps UI wiring stays a thin shell (no business logic) and is verified
  manually.

## Open Risks / Notes

- Multiple active profiles each spawn their own node subprocess, and each Codex
  node owns its own long-lived app-server process. This matches the documented
  one-app-server-per-node model; resource use scales with active profile count.
- `node_id` uniqueness is enforced server-side per live connection; the app's
  duplicate warning is a usability guard, not the source of truth.
- Distribution signing/notarization is out of scope for V1 (local build/run);
  it can be added later without changing this architecture.
