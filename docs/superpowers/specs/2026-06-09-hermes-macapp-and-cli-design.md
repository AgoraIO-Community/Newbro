# Hermes in the macOS app + CLI default-command-to-PATH — design

Status: approved design (pre-implementation)
Date: 2026-06-09

Follows on from `2026-06-09-hermes-second-executor-design.md` §6 (macOS app), which
was deferred when the backend + CLI shipped. This spec closes the remaining
operator-facing gaps so Hermes is selectable and runnable where the user actually
works: the menu-bar app's profile editor and Settings, plus a config-free
`executor run`.

## Goal & scope

Two workstreams:

- **A. CLI** — make `executor run` work for Hermes without a local config file, make
  `install-hermes` actually install Hermes via the vendor script, and surface auth
  state in the probe.
- **B. macOS app (§6)** — per-family readiness state, a family-aware profile-start
  diagnosis, a Hermes Settings pane, and a single-choice executor picker in the
  profile editor.

Out of scope: web UI (the create-Bro agent-client picker already supports Hermes);
Hermes thread import / skills / audio / interactive approval wiring.

## Key facts that shape the design

- The official Hermes installer is the vendor script
  `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`. It is
  **interactive by default but degrades gracefully without a TTY**: it checks
  `[ -t 0 ]` / `/dev/tty`, and with no terminal it installs the binary, skips all
  prompts, and defers setup ("Run 'hermes setup' after install"). So a headless
  subprocess install (the app's case) installs the binary and will not hang.
- Hermes auth is OAuth via `hermes setup --portal` — genuinely interactive; it
  cannot be driven headlessly and stays a manual, surfaced step.
- Updates are `hermes update`; auth status is shown by `hermes auth`.
- The node runtime (`_build_executors`) already defaults a family's command to the
  family name (`"hermes"`); only the CLI readiness gate is stricter, which is what
  forces the setup prompt for an unconfigured Hermes family.

---

## Workstream A — CLI

### A1. Default-command-to-PATH

`setup_resolvers.executor_runtime_ready` currently requires `executors.<family>.command`
to be explicitly present for non-codex families before a run is allowed; otherwise
`executor run` declares the config incomplete and launches interactive setup.

Change: when a family has no configured command, default it to the family's own
name and PATH-check that (mirroring `_build_executors`). Concretely, the generic
branch becomes:

```python
command = str(existing_block.get("command") or executor_type).strip()
return bool(command) and callbacks.command_available(command)
```

Effect: `newbro executor run --enabled-executor hermes --base-url … --node-id … --token …`
runs with no `~/.newbro/config.yaml` and no setup prompt, as long as `hermes`
resolves on PATH. Codex/acpx behavior is unchanged (they already default, and codex
keeps its detected-command path).

### A2. `install-hermes` performs a real install

`run_executor_install_hermes` / `install_hermes_cli` change from validate-only to a
real install mirroring `install_codex_cli`'s script-bootstrap shape:

1. If a usable `hermes` is already resolvable, set the command and return (no
   reinstall).
2. Otherwise download `https://hermes-agent.nousresearch.com/install.sh` with the
   existing `SYSTEM_CURL` to a temp file and run it via `SYSTEM_BASH`
   **non-interactively** (no inherited TTY; rely on the script's graceful
   degradation to install the binary and skip prompts/auth). Reuse the existing
   `_run_install_step` / `_run_logged` helpers and a `tempfile.TemporaryDirectory`,
   exactly like the codex bun-script flow.
3. Resolve the installed `hermes` (PATH + `~/.local/bin/hermes` + login-shell
   lookup, mirroring the codex command discovery), probe it, and `set_hermes_command`.
4. On success print `Hermes is ready: <command>`; the caller surfaces that auth is
   still required (`hermes setup --portal`). `install-hermes` never attempts auth.

Failure modes raise `RuntimeError` with actionable text (curl/bash unavailable,
script exited non-zero, `hermes --version` still unavailable after install).

### A3. Probe surfaces auth state (best-effort)

Extend `hermes_probe_payload` (and the underlying probe) with an optional
`authenticated: bool | None` field, derived from a **non-interactive** `hermes auth`
check. `None` means "could not determine" (the check is best-effort and must not
hang or error the probe). Binary presence remains the authoritative `ok`; auth is
advisory. `probe --executor hermes --json` includes the field so the macOS app can
render sign-in state.

Flagged unknown: confirm during implementation that `hermes auth` (or the right
subcommand) prints status non-interactively and parseably; if not, ship `authenticated: None`
and treat auth purely as a manual step (B2 degrades to a soft hint only).

---

## Workstream B — macOS app (§6)

### B1. Per-family readiness state in `AppModel`

Replace the single global `executorProbe: ExecutorProbe?` and
`codexStatus: CommandStatus` with per-family maps:

- `probeByFamily: [String: ExecutorProbe]`
- `statusByFamily: [String: CommandStatus]`
- per-family setup log/busy (`setupLogByFamily`, `setupBusyByFamily`) replacing the
  codex-specific `codexSetupLog`/`codexSetupBusy`.

`refreshExecutorProbeAndStoredDiagnoses` probes each family a profile needs and
stores results by family. `diagnoseStart(for:)` passes the probe for **that
profile's** family, so a Codex profile and a Hermes profile diagnose independently
(fixes the current bug where one global probe is applied to every profile).

### B2. Family-aware `ProfileStartDiagnosis`

Generalize the Codex-only `diagnoseProfileStart` into a family-keyed check driven by
the profile's enabled family:

- Reuse the existing CLI / profile-completeness gates unchanged.
- Codex retains its current reasons/actions.
- Add Hermes states: `hermesMissing` → action `setUpHermes` (runs `install-hermes`);
  Hermes present but `authenticated == false` → soft state `hermesSignInRequired` →
  action `signInHermes`; `authenticated == nil` → ready (auth undetermined, don't
  block). Binary-missing is the only hard block for Hermes.

The diagnosis enums grow Hermes cases alongside the Codex ones; nothing Codex is
removed.

### B3. Hermes Settings pane

Add a `Hermes` tab to `ExecutorSettingsView` (`SettingsPane.hermes`) with a
`HermesSettingsPane` mirroring `CodexSettingsPane`:

- shows detected `Hermes vX.Y.Z` / `No Hermes found.` from `statusByFamily["hermes"]`
  and a sign-in line from the probe's `authenticated` field,
- a **Set Up Hermes** button → `install-hermes`, streaming output like the codex
  setup flow (per-family busy/log),
- a **Sign in** action that opens Terminal at `hermes setup --portal`
  (`open -a Terminal` with the command), since OAuth is interactive,
- a **Refresh** button reusing `refreshExecutorProbeAndStoredDiagnoses`.

The Codex pane is unchanged; the two panes share presentation helpers where natural.

### B4. Single-choice executor picker in `ProfileEditView`

Replace the two independent `codex`/`acpx` toggles with one selector (`Picker`/
segmented) over a shared `supportedExecutorFamilies` constant
(`["codex", "acpx", "hermes"]` — the Swift mirror of the backend's
`SUPPORTED_EXECUTOR_FAMILIES`). The profile stores exactly one family. When `acpx`
is selected, keep the existing `acpx_agent` sub-field; it's hidden for other
families. This both adds Hermes and removes the pre-existing invalid-multi-family
hazard.

### B5. `ExecutorSettingsClient` per family

The probe call takes the family and invokes `newbro executor probe --executor <family> --json`;
`install`/`use` calls likewise dispatch on family (`install-hermes` vs
`install-codex`). The `signIn` action for Hermes opens Terminal rather than calling
the CLI.

---

## Error handling

- CLI: `install-hermes` failures raise `RuntimeError` with actionable messages; no
  silent fallback. A non-interactive `hermes auth` check that errors yields
  `authenticated: None`, never a probe failure.
- App: a missing binary blocks profile start with a repair action; not-authed is a
  soft sign-in prompt, not a hard block (auth state is best-effort). Per-family
  busy/log isolates one family's setup from another's.

## Testing

Python:
- `executor_runtime_ready` defaults an unconfigured hermes command to `hermes` and
  passes when on PATH; `executor run` does not launch setup in that case.
- `install_hermes_cli` invokes the vendor script via curl+bash (mocked
  `_run_logged`), then sets the command; raises with a clear message when the binary
  is still unavailable.
- `hermes_probe_payload` includes `authenticated` (bool or None) and the supported
  list; `--executor hermes --json` shape.

Swift:
- `ProfileStartDiagnosisTests` / `ProfileStartRulesTests`: Hermes missing → setUp,
  Hermes present+unauthed → signIn (soft), Hermes present+authed/undetermined →
  ready; **mixed-family** — a Codex profile and a Hermes profile each resolve against
  their own family's probe from `probeByFamily`.
- `ExecutorSettingsClientTests`: per-family probe/install dispatch.
- Profile editor: single-choice selector yields exactly one family; `acpx_agent`
  shown only for acpx.

## Flagged unknowns (resolve during implementation)

1. The exact `hermes auth` (or equivalent) subcommand + non-interactive output for
   the `authenticated` field. If unavailable, ship `authenticated: None` and B2
   degrades to no sign-in gating (auth purely manual).
2. The `install.sh` non-TTY path installs the binary cleanly in practice — verify
   against the live script during implementation; if it still requires a TTY, fall
   back to B's "Set Up Hermes" opening Terminal with the install command (the same
   pattern as Sign in) rather than a headless install.
