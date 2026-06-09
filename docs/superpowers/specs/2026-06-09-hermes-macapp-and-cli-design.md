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
  `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash` (vendor-documented).
  Reading the script, it is interactive by default but **appears to degrade without a
  TTY** — it checks `[ -t 0 ]` / `/dev/tty` and, with no terminal, skips prompts and
  defers setup ("Run 'hermes setup' after install"). This non-TTY behavior is inferred
  from the script source, **not vendor-documented**, so the install path must be
  defensive (A2) rather than assume it never blocks.
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
   existing `SYSTEM_CURL` to a temp file and run it via `SYSTEM_BASH`. Reuse the
   existing `_run_install_step` / `_run_logged` helpers and a
   `tempfile.TemporaryDirectory`, like the codex bun-script flow, but **defensively**
   (the non-TTY behavior is unverified): run with **stdin redirected from
   `/dev/null`** (never inherit a TTY) and a **bounded timeout** (the existing
   `COMMAND_TIMEOUT_SECONDS`). If the script blocks (timeout), exits non-zero, or
   leaves `hermes` unavailable, raise `RuntimeError` directing the user to the
   documented fallback: install Hermes manually (or via the macOS app's "Set Up
   Hermes" which opens Terminal — B3) and run `hermes setup --portal`.
3. Resolve the installed `hermes` (PATH + `~/.local/bin/hermes` + login-shell
   lookup, mirroring the codex command discovery), probe it, and `set_hermes_command`.
4. On success print `Hermes is ready: <command>`; the caller surfaces that auth is
   still required (`hermes setup --portal`). `install-hermes` never attempts auth.

**Single-family invariant.** `set_hermes_command` (and `use --executor hermes`) must
**replace** the local `executor_node.enabled_executors` with `["hermes"]`, not append
— a local node runs exactly one family, mirroring the node registry's one-family
rule. (Today `set_hermes_command` appends, which can yield `["codex", "hermes"]`;
this spec changes it to replace.) Switching family via `use`/`install` is the
intended way to repoint a local node; the previously enabled family is dropped from
the local enabled list by design.

Failure modes raise `RuntimeError` with actionable text (curl/bash unavailable,
script timed out, script exited non-zero, `hermes --version` still unavailable after
install).

### A3. Probe surfaces auth state (best-effort)

Extend `hermes_probe_payload` (and the underlying probe) with an optional
`authenticated: bool | None` field, derived from a **non-interactive** `hermes auth`
check. `None` means "could not determine" (the check is best-effort and must not
hang or error the probe). Binary presence remains the authoritative `ok`; auth is
advisory and feeds **only the Settings pane's sign-in row (B3)** — it does **not**
gate profile start (B2). `probe --executor hermes --json` includes the field.

Flagged unknown: confirm during implementation that `hermes auth` (or the right
subcommand) prints status non-interactively and parseably; if not, ship
`authenticated: None` and the Settings pane simply always offers the Sign-in action.

### A4. Probe/use are limited to probeable families; ACPX is run-only

Only Codex and Hermes have a meaningful local readiness probe. Introduce
`PROBEABLE_EXECUTOR_FAMILIES = ("codex", "hermes")`. Today `run_executor_probe` /
`run_executor_use` dispatch `hermes` vs `else=codex`, so `--executor acpx` silently
returns a **codex** payload — a bug. Fix:

- `probe` / `use` `--executor` choices become `PROBEABLE_EXECUTOR_FAMILIES`
  (codex, hermes). `acpx` is rejected by argparse for probe/use (it remains valid for
  `--enabled-executor` on `run`, which is unchanged).
- Dispatch on the family explicitly (codex → codex payload, hermes → hermes payload);
  never fall through to codex for an unrecognized family.

ACPX stays **run-only** with no local readiness gate — matching today's behavior,
where `ProfileStartDiagnosis` only ever gated Codex and treated everything else as
ready.

---

## Workstream B — macOS app (§6)

### B1. Per-family readiness state in `AppModel`

Replace the single global `executorProbe: ExecutorProbe?` and
`codexStatus: CommandStatus` with per-family maps:

- `probeByFamily: [String: ExecutorProbe]`
- `statusByFamily: [String: CommandStatus]`
- per-family setup log/busy (`setupLogByFamily`, `setupBusyByFamily`) replacing the
  codex-specific `codexSetupLog`/`codexSetupBusy`.

`refreshExecutorProbeAndStoredDiagnoses` probes the **probeable families**
(`PROBEABLE_EXECUTOR_FAMILIES` = codex, hermes; ACPX has no probe — A4) and stores
results in `probeByFamily`/`statusByFamily`, so the Settings panes (B3) can show
Hermes status even before any Hermes profile exists. `diagnoseStart(for:)` reads the
probe for **that profile's** family, so a Codex profile and a Hermes profile diagnose
independently (fixes the current bug where one global probe is applied to every
profile). A profile whose family is not probeable (acpx) keeps today's behavior:
ready, no readiness gate. Probing both families on refresh is cheap (each is a
`newbro executor probe --executor <family> --json` call) and runs off the main thread
as today.

### B2. Family-aware `ProfileStartDiagnosis`

Generalize the Codex-only `diagnoseProfileStart` into a family-keyed check driven by
the profile's enabled family. **Start gating stays binary** — the existing status
model (`.ready` / `.blocked` / `.checking`) is unchanged, so we don't risk the
`.ready`-starts-and-clears vs `.blocked`-prevents-launch semantics in `AppModel`:

- Reuse the existing CLI / profile-completeness gates unchanged.
- Codex retains its current reasons/actions.
- Hermes: binary **missing** → `.blocked` with reason `hermesMissing` and action
  `setUpHermes` (runs `install-hermes`). Binary **present** → `.ready` regardless of
  auth — the node is allowed to launch (an unauthenticated Hermes simply fails the
  first turn with its own auth error).
- Auth is **not** a start-gate. The sign-in prompt lives only in the Hermes Settings
  pane (B3), driven by the probe's `authenticated` field, so it never blocks a start
  nor disappears when a `.ready` diagnosis is cleared.

The diagnosis enums grow only `hermesMissing` / `setUpHermes` (and `signInHermes`,
used by the Settings pane action, not by start gating) alongside the Codex cases;
nothing Codex is removed, and no new status case is added.

### B3. Hermes Settings pane

Add a `Hermes` tab to `ExecutorSettingsView` (`SettingsPane.hermes`) with a
`HermesSettingsPane` mirroring `CodexSettingsPane`:

- shows detected `Hermes vX.Y.Z` / `No Hermes found.` from `statusByFamily["hermes"]`
  and a sign-in line from the probe's `authenticated` field,
- a **Set Up Hermes** button → `install-hermes`, streaming output like the codex
  setup flow (per-family busy/log); if it fails or times out, the pane shows the
  error and a "Open Terminal to install" fallback (the documented A2 fallback path),
- a **Sign in** action that opens Terminal at `hermes setup --portal`
  (`open -a Terminal` with the command), since OAuth is interactive,
- a **Refresh** button reusing `refreshExecutorProbeAndStoredDiagnoses`.

The Codex pane is unchanged; the two panes share presentation helpers where natural.

### B4. Single-choice executor picker in `ProfileEditView`

Replace the two independent `codex`/`acpx` toggles with one selector (`Picker`/
segmented) over a shared `supportedExecutorFamilies` constant
(`["codex", "acpx", "hermes"]` — the Swift mirror of the backend's
`SUPPORTED_EXECUTOR_FAMILIES`). The profile stores exactly one family in
`Profile.enabledExecutors` (a single-element array), and `nodeArgv` continues to
forward it as `--enabled-executor <family>`. This both adds Hermes and removes the
pre-existing invalid-multi-family hazard.

No `acpx_agent` handling is in scope: the macOS `Profile` model has no `acpxAgent`
field and `nodeArgv` does not forward `--acpx-agent` today, so acpx continues to run
with its default agent exactly as it does now. Adding acpx-agent persistence/argv is
explicitly out of scope for this workstream.

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
- App: a missing binary blocks profile start with a repair action; not-authed never
  blocks start — it surfaces a Sign-in action in the Hermes Settings pane only (auth
  state is best-effort). Per-family busy/log isolates one family's setup from
  another's.

## Testing

Python:
- `executor_runtime_ready` defaults an unconfigured hermes command to `hermes` and
  passes when on PATH; `executor run` does not launch setup in that case.
- `install_hermes_cli` invokes the vendor script via curl+bash (mocked
  `_run_logged`) with stdin from `/dev/null` and a bounded timeout, then sets the
  command; raises with a clear, fallback-directing message when the script times out,
  exits non-zero, or the binary is still unavailable (the non-TTY failure path).
- `set_hermes_command` **replaces** `enabled_executors` with `["hermes"]` (never
  produces `["codex", "hermes"]`) and writes `executors.hermes.command`.
- `probe` / `use` reject `--executor acpx` (argparse choices = probeable families);
  `probe --executor hermes` returns a hermes payload and never a codex payload for a
  non-codex family.
- `hermes_probe_payload` includes `authenticated` (bool or None) and the supported
  list; `--executor hermes --json` shape.

Swift:
- `ProfileStartDiagnosisTests` / `ProfileStartRulesTests`: Hermes missing →
  `.blocked` / `setUpHermes`; Hermes present → `.ready` regardless of auth (auth never
  blocks start); an acpx profile → `.ready` (no probe/gate); **mixed-family** — a
  Codex profile and a Hermes profile each resolve against their own family's probe
  from `probeByFamily`.
- Hermes Settings pane shows the Sign-in action when `authenticated == false`/`nil`
  and hides it when `true` — independent of start gating.
- `ExecutorSettingsClientTests`: per-family probe/install dispatch (codex, hermes).
- Profile editor: single-choice selector yields exactly one family in
  `Profile.enabledExecutors`; `nodeArgv` forwards a single `--enabled-executor`.

## Flagged unknowns (resolve during implementation)

1. The exact `hermes auth` (or equivalent) subcommand + non-interactive output for
   the `authenticated` field. If unavailable, ship `authenticated: None` and B2
   degrades to no sign-in gating (auth purely manual).
2. Whether the `install.sh` non-TTY path installs the binary cleanly in practice is
   **unverified** (inferred from the script, not vendor-documented). A2 is therefore
   defensive by construction (stdin from `/dev/null`, bounded timeout, hard error on
   block/failure). If implementation finds the headless install unreliable, the
   documented product fallback is B3's "Set Up Hermes" opening Terminal with the
   install command (the same pattern as Sign in) instead of a headless install — this
   is an accepted fallback, not a silent degradation.
