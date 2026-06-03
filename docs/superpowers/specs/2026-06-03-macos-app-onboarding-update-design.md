# macOS App Onboarding, Runtime Setup, And Updates — Design

Status: design for review
Date: 2026-06-03

## Summary

Make the Newbro Executor macOS app feel self-contained on first launch while
preserving the executor/runtime ownership boundary. The app remains a thin
supervisor over `newbro executor run`, but the CLI gains an intentional
non-interactive Codex auto-configuration path for the common case.

If Codex is detectable, the app/CLI should configure the minimal Codex executor
runtime automatically and start the profile. If Codex is not detectable, the app
should show a clear warning before spawning instead of surfacing a late
subprocess error.

## Goals

- Remove confusing profile onboarding menu surface.
- Auto-configure the obvious default executor (`codex`) when it is detectable.
- Show the detected Codex version as a disabled menu item.
- Show a visible warning when Codex is not detectable.
- Auto-start a newly pasted profile after it is saved.
- Avoid duplicate profiles and duplicate app-generated profile ids.
- Notify the user when profile lifecycle actions succeed or fail.
- Keep `newbro executor setup` useful for advanced/manual configuration, not as
  a normal mac app first-run requirement.
- Fix fragile app/CLI update display and release lookup.

## Non-Goals

- Auto-install Codex itself.
- Remove `newbro setup` or `newbro executor setup`.
- Add Sparkle or app self-update.
- Move executor runtime policy into Swift.
- Add ACPX auto-configuration.

## Decisions

### Setup Role

`newbro setup` remains useful for backend/runtime configuration, OpenAI keys,
connector config, and server/dev installs.

`newbro executor setup` remains useful for:

- custom Codex command paths
- ACPX configuration
- Codex installed outside the app/login-shell PATH
- broken config recovery
- terminal/server operators who want explicit configuration

The mac app happy path should not require either command when Codex is already
installed and discoverable. The app should probe Codex during launch so the
menu can immediately show the runtime readiness state.

### Runtime Auto-Configuration

The CLI owns auto-configuration because it already owns executor setup files and
runtime completeness checks.

When `newbro executor run` is invoked without complete executor runtime config:

1. If a TTY is available, keep the existing interactive setup behavior.
2. If no TTY is available and the selected/default executor is Codex, detect
   `codex` using the same command detection used by setup.
3. If Codex is detectable and runnable enough for the existing readiness check,
   write the minimal config:
   - `executor_node.enabled_executors: ["codex"]`
   - `executors.codex.command: <detected command>`
   - preserve unrelated existing config blocks
4. Print an observable setup line such as
   `[setup] auto-configured codex executor command: codex`.
5. Continue into `newbro executor run`.
6. If Codex is not detectable, return a clear incomplete-runtime error.

This is intentional product behavior, not fallback masking. It is documented,
observable, and tested.

### App Menu

Top-level menu changes:

- Remove `Add profile...`.
- Keep `Paste connect command...` as the primary profile creation action.
- Add a disabled runtime row:
  - `Codex vX.Y.Z` when Codex is detected and `codex --version` succeeds.
  - `Codex detected` when the command is detected but version probing fails.
  - `No Codex found. Newbro may not work properly.` when no Codex command is
    detected.
- Keep `Launch at login`, update items, and `Quit`.

Profile rows remain focused on lifecycle actions: Start, Stop, Restart, View
recent log, Edit, Delete, and auto-activate.

When Codex is missing, `Start` should not spawn a profile that requires Codex.
The menu should surface the warning immediately.

Pasting a valid connect command should create or update the profile, save it,
and auto-start that profile immediately when the runtime is available and the
profile is complete. If Codex is missing, the profile is saved but not started;
the menu warning explains why Newbro may not work properly.

Profile identity rules:

- `profile.id` is an app-generated storage id and must be unique in
  `~/.newbro/menubar.json`.
- A pasted connect command is matched by normalized `(base_url, node_id)`.
  Normalization trims surrounding whitespace and trailing URL slashes, so
  `https://example.com` and `https://example.com/` are the same identity.
- If a matching profile exists, update the first matching profile's
  token/enabled executors instead of creating a new profile.
- If the matching profile is already running, paste should restart it so the new
  token/executor settings take effect.
- If the matching profile is stopped, paste should auto-start it when runtime
  readiness allows it. Paste auto-start applies to both newly created profiles
  and updated existing profiles.
- If the store already contains duplicate `profile.id` values or duplicate
  `(base_url, node_id)` identities, the app should avoid adding another
  duplicate. Paste should update the first matching profile and leave existing
  duplicate rows untouched; it should not silently persist another duplicate row
  or auto-delete old rows.

### Notifications

The app should use macOS user notifications for profile lifecycle events:

- profile created from paste
- profile updated from paste
- profile started
- profile stopped
- profile failed or entered error

Notifications are concise and event-based; they should not replace the menu,
profile status, or recent log as the source of truth. If notification permission
is unavailable or denied, the app still updates menu state and logs normally.

Avoid notification spam:

- Do not notify for every reconnect/retry line from the node.
- Notify on user-triggered lifecycle transitions and terminal error states.
- When paste updates and starts/restarts a profile, it is acceptable to emit one
  combined notification such as `Profile updated and started`.

### Updates

Fix the release source to match the actual repository:

- GitHub latest release API:
  `https://api.github.com/repos/AgoraIO-Community/Newbro/releases/latest`
- Release page links should also point to `AgoraIO-Community/Newbro`.

Display app and CLI versions separately:

- `newbro CLI vX.Y.Z`
- `App vA.B.C`
- update availability should state which component is behind

CLI update behavior remains stop active profiles, run installer, restart the
profiles that were active, then re-check versions. App update remains
notify-and-open-release only.

## Components

### Python CLI

Add a focused helper for non-interactive executor auto-configuration. It should
reuse existing setup resolver callbacks and connector config rendering rather
than ad hoc YAML mutation.

The helper is called only from the missing-config branch in
`_ensure_executor_runtime_configured_for_run`.

### Swift Core

Extend runtime probing so the app can answer:

- resolved `newbro` path
- detected Codex command, if any
- Codex version, if available
- whether a profile requires Codex

Version probing should run through the login-shell PATH environment, matching
node subprocess execution.

### Swift App

Menu building reads the runtime probe and renders a disabled runtime row. Start
actions gate on missing Codex for Codex profiles and leave the profile stopped.

Manual profile creation is fully removed from the menu. Existing stored profiles
can still be edited.

## Testing

- Python unit tests:
  - non-TTY `executor run` auto-configures Codex when detectable
  - non-TTY `executor run` still errors clearly when Codex is not detectable
  - existing TTY interactive setup behavior remains unchanged
  - existing config blocks are preserved
- Swift Core tests:
  - runtime probe reports Codex version from fake command output
  - runtime probe reports warning state when Codex is missing
  - release client uses `AgoraIO-Community/Newbro`
  - update status distinguishes CLI and app display state
- Swift app/core tests where practical:
  - profile start is blocked when Codex is required and missing
  - pasted profiles are auto-started after successful save when Codex is
    available
  - pasted profiles are saved but not started when Codex is missing
  - pasted profiles update an existing `(base_url, node_id)` match instead of
    creating a duplicate
  - matching trims trailing slashes in `base_url`
  - pasting an already-running profile restarts it
  - pasting an existing stopped profile starts it when runtime readiness allows
    it
  - profile id generation does not collide with existing stored profile ids
  - profile lifecycle notifications are emitted for create/update/start/stop
    and error transitions through an injected notifier
  - `Add profile...` is absent from the menu-building path if menu structure is
    covered by testable helpers

## Documentation

Update stable docs:

- `docs/architecture/executors.md`: mac app auto-configures detectable Codex,
  while deeper manual config remains CLI-owned.
- `docs/guides/cli.md`: clarify that `newbro executor setup` is an advanced
  and recovery path for the mac app, not required when Codex is detectable.
- `macos/README.md`: describe Codex detection, warning behavior, and update
  source.
- `docs/memories.md`: append a short factual note because this changes adopted
  runtime/app onboarding behavior.
