# macOS Executor App — Native SwiftUI Rewrite — Design

Status: design (approved for planning)
Date: 2026-06-01
Supersedes: the rumps/Python implementation in
`2026-06-01-macos-executor-menubar-app-design.md` (kept as history).

## Summary

Replace the Python `rumps` menu-bar executor app with a native **SwiftUI**
menu-bar app. The rumps version worked but looked unpolished; SwiftUI gives a
native `MenuBarExtra`, real Settings / Add-Edit windows, and a scrollable log
window.

The Swift app **owns all node-supervision logic** (profiles, status parsing,
subprocess supervision, login item, logs). It spawns the existing Python node
via the stable `newbro executor run` / `newbro.executors.node` CLI contract —
that CLI is the only seam. The entire Python `src/newbro/executors/ui/` package
and its CLI/packaging wiring are removed.

## Goals

- Native, good-looking macOS menu-bar app with the same capabilities as the
  rumps version: multiple concurrent node profiles, run/stop/restart, live
  status, paste-connect-command, add/edit/delete, auto-activate, view logs,
  launch at login.
- Zero configuration to run the node: the app resolves the standard
  `uv`-installed `newbro` CLI (no repo coupling, no baked paths); if `newbro` is
  missing, the app self-heals by running the public install script.
- Keep node/protocol logic in the Python node; the app is a supervisor + editor.
- Build and unit-test headlessly with the installed Swift toolchain (no Xcode
  project files, no GUI required for tests).

## Non-Goals

- Bundling a self-contained Python runtime in the `.app` (the app resolves the
  externally-installed `newbro` CLI; it offers one-click install if missing).
- Code signing / notarization / distribution outside the build machine (V1 is
  local, unsigned).
- Re-implementing or changing the node (`newbro executor run`) behavior.
- A custom app icon (V1 uses an SF Symbol in the menu bar; default bundle icon).

## Resolved Decisions (from brainstorming)

- **Logic home:** Swift owns everything; the Python `ui/` package is deleted.
- **Node invocation:** the public `newbro executor run …` CLI, one subprocess
  per active profile, several concurrent. (`newbro executor run` itself launches
  the `newbro.executors.node` process and forwards its status lines.)
- **Zero-config runtime:** the app resolves the `newbro` executable at runtime
  (override → `~/.local/bin/newbro` (the `uv tool install` location) →
  login-shell `command -v newbro`); no repo path or venv is baked. Missing
  runtime → "Install runtime…" runs the public install script
  (`curl -fsSL <install-newbro-cli.sh> | sh`, which installs `uv` and
  `uv tool install newbro-cli`), then re-resolves; clear error if that fails. A
  hidden override exists but is not required.
- **Build:** Swift Package under `macos/`, `swift build`, plus a `package-app.sh`
  that assembles a `Newbro Executor.app` bundle (menu-bar only via `LSUIElement`
  + `setActivationPolicy(.accessory)`). The bundle is repo-independent and
  portable.
- **macOS 14+** deployment target.
- **Login item** points at `Bundle.main.bundlePath` (runs from any location).
- **Unsigned, local V1.** Reuse `~/.newbro/menubar.json`. No custom icon.
- **Git history:** keep the existing rumps commits; add commits that remove the
  Python UI and add the Swift app. Old spec/plan get a "superseded" note.

## Architecture

```
macos/
  Package.swift
  Sources/
    NewbroExecutorCore/      ← pure logic, XCTest-covered
    NewbroExecutor/          ← @main SwiftUI app (MenuBarExtra), thin
  Tests/
    NewbroExecutorCoreTests/
  package-app.sh             ← swift build + assemble Newbro Executor.app
```

```
Newbro Executor.app  (MenuBarExtra, .accessory)
  ProfileSupervisor (ObservableObject, @Published)
     ├─ per active profile: NodeProcess  ──▶ Process: <newbro> executor run
     │                       StatusParser              --base-url … --node-id …
     │                       ProfileLog                --token … --enabled-executor …
  ProfileStore   ── ~/.newbro/menubar.json
  RuntimeLocator ── resolves `newbro` (override → ~/.local/bin/newbro →
     │                login-shell which); install via public install-newbro-cli.sh
  LoginItem  ── ~/Library/LaunchAgents/com.newbro.executor-ui.plist
        │ subprocess stdout/stderr (status lines)
        ▼
  newbro executor run → newbro.executors.node
        ── outbound WS /api/executors/control  (unchanged)
```

### Boundary principle

The Swift app is a supervisor + config editor. All node/protocol behavior stays
in the Python node, reached only through the `newbro.executors.node` CLI
contract. This preserves the detached-node ownership boundary in
`docs/architecture/executors.md`.

## Components (`NewbroExecutorCore`)

### `Profile`
`Codable` struct: `id: String`, `label: String`, `baseURL: String`,
`nodeID: String`, `token: String`, `enabledExecutors: [String]`,
`autoActivate: Bool`.

### `ProfileStore`
Loads/saves `~/.newbro/menubar.json` (same path and JSON shape as the rumps
version: `{"version": 1, "profiles": [...]}`). Missing file → empty list.

### `ConnectCommandParser`
- `parseConnectCommand(_ text:) -> ConnectCommandFields` — tokenize a
  `newbro executor run --base-url … --node-id … --token … [--enabled-executor …]`
  string; throw if base-url/node-id/token missing.
- `conflictingProfileIDs(_ profiles:) -> Set<String>` — ids sharing the same
  `(baseURL, nodeID)`.

### `NodeStatus` + `StatusParser`
- `NodeStatus`: `idle, starting, connecting, ready, disconnected, retrying,
  error, stopped`.
- `StatusParser` maps the node's stderr prefixes:
  `[start]`→starting, `[connect]`→connecting, `[ready]`→ready, `[retry]`→retrying,
  `[warn] …disconnected=`→disconnected, `[warn] …connect_failed=`→connecting;
  unknown lines leave status unchanged. `onExit(code:expected:)` →
  stopped/error.
- `aggregate(_ statuses:) -> NodeStatus` priority: error > disconnected >
  retrying > connecting > starting > ready, else idle.

### `NodeProcess`
Wraps Foundation `Process`. Spawns an argv, merges stdout+stderr through a
`Pipe.readabilityHandler`, emits each line via a callback and the termination
code via a callback. `start()`, `stop()` (`terminate()` = SIGTERM, then SIGKILL
on timeout), `isRunning`.

### `ProfileSupervisor` (`ObservableObject`)
Owns `profileID → (NodeProcess, NodeStatus, ProfileLog)`. `start/stop/restart`
per profile; `aggregateStatus`; `stopAll`. Publishes per-profile status so
SwiftUI re-renders reactively (no polling). Unexpected exit → `error` (record
kept); user stop → `stopped` (record dropped). No process-restart loop: the node
owns its own reconnection. Process spawning is injected (a factory) so tests use
a fake.

### `RuntimeLocator`
Resolves the `newbro` executable with no baked repo path: an optional override
(stored in `UserDefaults`), then `~/.local/bin/newbro` (the `uv tool install`
location), then a login-shell `command -v newbro`. `isRuntimeAvailable` is true
when a resolved path exists. `nodeArgv(for: Profile)` builds
`[newbro, "executor", "run", "--base-url", …, "--node-id", …, "--token", …]`
plus `--enabled-executor` for each enabled family. `runInstall()` runs the
public install script
(`curl -fsSL https://raw.githubusercontent.com/AgoraIO-Community/Newbro/main/scripts/install-newbro-cli.sh | sh`),
streaming output, then re-resolves.

### `LoginItem`
Renders/installs/removes
`~/Library/LaunchAgents/com.newbro.executor-ui.plist` with
`ProgramArguments = ["/usr/bin/open", Bundle.main.bundlePath]`, `RunAtLoad=true`.

### `ProfileLog`
Appends node lines to `~/.newbro/logs/executor-ui-<id>.log`; `recent(maxLines:)`
tails the file (works for stopped profiles).

## App (`NewbroExecutor`, SwiftUI)

- `@main App` with `MenuBarExtra`; `setActivationPolicy(.accessory)` on launch
  for menu-bar-only (no Dock icon).
- **Menu:** aggregate status icon (SF Symbol). Per profile: status line +
  Start/Stop/Restart, "Auto-activate at login" toggle, "View recent log…",
  "Edit…", "Delete". Footer: "Add profile…", "Paste connect command…",
  "Launch at login" toggle, "Settings…", "Quit" (stops all first).
- **Add/Edit window:** native form — label, base URL, node id, token,
  enabled-executor checkboxes (codex/acpx), auto-activate.
- **Log window:** scrollable text view of `ProfileLog.recent`.
- **Runtime-missing state:** banner/menu item "Node runtime not found" with the
  tried path and an "Install runtime…" button (runs `RuntimeLocator.runInstall`,
  streams output in a window).
- The app holds no supervision logic; it binds to `ProfileSupervisor`,
  `ProfileStore`, `RuntimeLocator`, `LoginItem`.

## Build & Packaging

- `swift build -c release` builds the `NewbroExecutor` executable.
- `macos/package-app.sh` (repo-independent — bakes nothing):
  1. `swift build -c release`.
  2. Assemble `macos/dist/Newbro Executor.app/Contents/{Info.plist, MacOS/}`;
     copy the binary; write `Info.plist`
     (`CFBundleIdentifier=com.newbro.executor-ui`, `LSUIElement=true`,
     bundle name/version).
- The install-script URL and the `newbro` resolution candidates are constants in
  `NewbroExecutorCore` (no per-build configuration).
- macOS 14 platform in `Package.swift`.

## Data Flow

1. Launch → `setActivationPolicy(.accessory)`; `ProfileStore.load`;
   `RuntimeLocator` resolves `newbro`.
2. Auto-start every profile with `autoActivate == true` that passes the
   completeness check and has an available runtime.
3. Each `NodeProcess` streams lines → `StatusParser` updates the profile's
   status (published → SwiftUI re-renders) and `ProfileLog` appends.
4. Start gates on `RuntimeLocator.isRuntimeAvailable` (else runtime-missing
   state) and on profile completeness (else the `newbro executor setup` alert).
5. Edit/Add/Paste mutate profiles → `ProfileStore.save` → reactive UI update;
   credential changes stop+restart the affected profile.
6. Quit → `stopAll()` (SIGTERM → SIGKILL), no orphaned node processes.

## Error Handling

- **Runtime missing** (`newbro` not resolvable) → "Node runtime not found" +
  the candidate paths tried + "Install runtime…" (runs the public
  `install-newbro-cli.sh` via `curl … | sh`, then re-resolves); clear failure
  message, no silent fallback.
- **Incomplete executor setup** (no codex/acpx binary) → native alert pointing
  to `newbro executor setup` in a terminal.
- **Bad node id/token** → persistent connecting/retrying state. The node service
  reconnects in an unbounded loop and does not exit on a rejected credential, so
  the app cannot show a terminal `error` for this case. Documented limitation,
  unchanged from the rumps version.
- **Unexpected process exit** → `error` (no restart loop; the node owns
  reconnection).
- **Duplicate `node_id`+`base_url`** → inline "(duplicate node id)" annotation.
- **Quit/terminate** → `stopAll` SIGTERM→SIGKILL; no orphans.

Errors are per profile; one failing profile never disturbs another.

## Testing

`NewbroExecutorCoreTests` (XCTest, `swift test`, headless):
- `ProfileStore` — multi-profile round-trip in a temp dir; defaults;
  missing-file → empty.
- `ConnectCommandParser` — field extraction; missing-field error;
  `conflictingProfileIDs`.
- `StatusParser` — real line-sequence transitions (connect→ready, disconnect,
  retry, connect_failed-stays-connecting); exit expected/unexpected;
  `aggregate` priority.
- `NodeProcess` — spawn a real `/bin/sh -c` script that prints lines then exits;
  assert line capture + exit code; assert `stop()` terminates a long-runner.
- `ProfileSupervisor` — injected fake process factory: concurrent start/stop,
  per-profile independence, aggregate, stopAll.
- `RuntimeLocator` — resolution order (override > `~/.local/bin/newbro` >
  login-shell) against temp paths; present/missing detection; `nodeArgv` shape
  (`executor run --base-url … --node-id … --token … --enabled-executor …`).
- `LoginItem` — plist render contains label + app path; install→remove in a
  temp dir.

SwiftUI views hold no logic and are verified manually (`swift build` + launch).

## Migration / Removal of the Python UI

- Remove `src/newbro/executors/ui/` and `tests/unit/executors/ui/`.
- Remove the `newbro executor ui` subparser (`src/newbro/cli/parser.py`), the
  dispatch `ui` branch (`src/newbro/cli/dispatch.py`), and
  `src/newbro/cli/commands/executor_ui.py`.
- Remove `macos-ui` / `macos-ui-build` extras from `pyproject.toml`; delete
  `packaging/menubar/`.
- Keep `newbro.executors.node` / `newbro executor run` untouched.
- Update `docs/architecture/executors.md` (replace the rumps bullet with the
  SwiftUI app) and append a `docs/memories.md` note. Add a "superseded by
  SwiftUI" note atop the two earlier rumps spec/plan files.
- Confirm `.venv/bin/python -m pytest` stays green after the removals.

## Open Risks / Notes

- The app depends on `newbro` being installed where it runs; the install
  self-heal (`install-newbro-cli.sh` → `uv tool install newbro-cli`, landing at
  `~/.local/bin/newbro`) covers the missing case, but the per-executor binaries
  still need a one-time `newbro executor setup`.
- `newbro executor run` requires the local executor runtime config; launched
  non-interactively from the app, an incomplete config surfaces as the
  "needs setup" alert rather than a TTY setup prompt.
- Reusing `~/.newbro/menubar.json` means profiles created by the rumps version
  carry over unchanged.
- Unsigned local builds may trigger a Gatekeeper prompt on first launch; opening
  via `open` or right-click→Open clears it. Signing is deferred.
