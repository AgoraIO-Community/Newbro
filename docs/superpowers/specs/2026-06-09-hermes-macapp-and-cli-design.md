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

Follow-up (not this spec): the web create-Bro picker currently defaults to Codex and
auto-issues credentials on open. For consistency with the no-fallback rule adopted
for the macOS editor (B4), a later change should make the web picker require an
explicit family choice before issuing. Tracked separately from this macOS/CLI work.

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
   leaves `hermes` unavailable, raise `RuntimeError` whose message tells the user to
   install Hermes manually (`curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`)
   and run `hermes setup --portal`. (The macOS app surfaces this same message in the
   Hermes setup log — B3 — exactly as Codex surfaces install-codex failures; no
   Terminal is launched.)
3. Resolve the installed `hermes` (PATH + `~/.local/bin/hermes` + login-shell
   lookup, mirroring the codex command discovery), probe it, and `set_hermes_command`.
4. On success print `Hermes is ready: <command>`; the caller surfaces that auth is
   still required (`hermes setup --portal`). `install-hermes` never attempts auth.

**Single-family invariant.** A local node runs exactly one family (mirroring the node
registry's one-family rule), so the local-config writers must never manufacture a
multi-family `executor_node.enabled_executors`. `set_hermes_command` (and
`use`/`install-hermes`) **replace** the enabled list with `["hermes"]`, not append.
For consistency, `set_codex_command` is aligned to write a single-element
`["codex"]` as well (today it appends, which can yield `["codex", "hermes"]`). After
this change neither writer can produce a registry-invalid list. Switching family via
`use`/`install` is the intended way to repoint a local node; the previously enabled
family is dropped from the local enabled list by design.

Failure modes raise `RuntimeError` with actionable text (curl/bash unavailable,
script timed out, script exited non-zero, `hermes --version` still unavailable after
install).

### A3. Probe surfaces auth state (best-effort)

Extend `hermes_probe_payload` (and the underlying probe) with an optional
`authenticated: bool | None` field, derived from **`hermes auth list`** (verified
non-interactive, exit 0, prints one block per provider with a credential count).
Rule: exit 0 with at least one listed credential → `true`; exit 0 with no
credentials → `false`; non-zero/timeout/unrecognized output → `None` ("could not
determine"). The check is best-effort, bounded by a short timeout, and must never
hang or fail the probe. Binary presence remains the authoritative `ok` for the probe
itself; the `authenticated` field gates **profile start** (B2) only when confidently
`false` (mirroring Codex's login-required block) and is permissive when `true` or
`None`. It also drives the Settings pane's sign-in row (B3).
`probe --executor hermes --json` includes the field.

(`hermes auth status` is rejected for this purpose: it requires a `provider`
argument, so it can't answer "is Hermes usable at all" without knowing the
configured model's provider. `hermes auth list` is provider-agnostic.)

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

**Scoped, per-family probing (no blanket refresh).** Introduce
`refreshProbe(for family: String)` that probes **only that family**
(`newbro executor probe --executor <family> --json`, off the main thread) and updates
`probeByFamily[family]` / `statusByFamily[family]`, then re-derives stored diagnoses.
Callers are scoped so an unrelated binary is never spawned:

- **Each Settings pane's Refresh** probes only its own family (Codex pane →
  `refreshProbe(for: "codex")`, Hermes pane → `refreshProbe(for: "hermes")`), and a
  pane probes its family `onAppear`.
- **Profile start diagnosis** probes only the **starting profile's family** — a
  Codex-only user never spawns Hermes on a start.
- **App launch** probes the families that existing profiles use (the union of
  profile families), so stored diagnoses are ready without touching unused families.

`diagnoseStart(for:)` reads `probeByFamily[profile's family]`, so a Codex profile and
a Hermes profile diagnose independently (fixes the current bug where one global probe
is applied to every profile). An acpx profile is not probeable (A4) and keeps today's
behavior: ready, no readiness gate.

### B2. Family-aware `ProfileStartDiagnosis`

Generalize the Codex-only `diagnoseProfileStart` into a family-keyed check driven by
the profile's enabled family, **mirroring Codex's existing readiness model**. The
existing status set (`.ready` / `.blocked` / `.checking`) is unchanged — Codex
already expresses "installed but not signed in" as `.blocked` (`codexLoginRequired` →
`signInCodex`), so Hermes uses the same shape and needs no new status case:

- Reuse the existing CLI / profile-completeness gates unchanged.
- Codex retains its current reasons/actions.
- Hermes, in order:
  - binary **missing** → `.blocked` / reason `hermesMissing` / action `setUpHermes`
    (runs `install-hermes`).
  - binary **present** + probe `authenticated == false` → `.blocked` / reason
    `hermesSignInRequired` / action `signInHermes`. This mirrors Codex's
    `codexLoginRequired` exactly: the action is **informational** ("Run
    `hermes setup --portal` in a terminal, then Refresh") — no Terminal is launched,
    parallel to `signInCodex`.
  - binary **present** + `authenticated == true` **or `None`** → `.ready`. The
    `None` (could-not-determine) case resolves to `.ready` so an uncertain auth
    check never false-blocks a start.

So `authenticated` **does** gate start when it is confidently `false`, and is
permissive when unknown. The diagnosis enums grow `hermesMissing` / `setUpHermes` /
`hermesSignInRequired` / `signInHermes` alongside the Codex cases; nothing Codex is
removed and no new status case is added.

### B3. Hermes Settings pane

Codex and Hermes are **two separate panes** under the Settings "Executors" section:
the existing `SettingsPane.codex` / `CodexSettingsPane` stays, and a new
`SettingsPane.hermes` / `HermesSettingsPane` is added alongside it (a distinct
sidebar entry, not a merged pane). The Hermes pane mirrors `CodexSettingsPane`:

- shows detected `Hermes vX.Y.Z` / `No Hermes found.` from `statusByFamily["hermes"]`
  and a sign-in line from the probe's `authenticated` field (signed in / sign-in
  needed),
- a **Set Up Hermes** button → `install-hermes`, streaming output like the codex
  setup flow (per-family busy/log); on failure/timeout the pane shows the error +
  manual-install/`hermes setup --portal` guidance in the log, exactly as the Codex
  pane shows install-codex failures (no Terminal launch),
- when sign-in is needed, **informational text** ("Run `hermes setup --portal` in a
  terminal, then Refresh"), parallel to the Codex `signInCodex` text — no Terminal
  launch,
- a **Refresh** button that calls `refreshProbe(for: "hermes")` — it probes **only
  Hermes**, never Codex. (The Codex pane's Refresh is likewise scoped to
  `refreshProbe(for: "codex")`.)

The Codex pane keeps its current behavior (its Refresh now scoped to codex); the two
panes share presentation helpers where natural.

### B4. Single-choice executor picker in `ProfileEditView`

Replace the two independent `codex`/`acpx` toggles with one selector (`Picker`/
segmented) over a shared `supportedExecutorFamilies` constant
(`["codex", "acpx", "hermes"]` — the Swift mirror of the backend's
`SUPPORTED_EXECUTOR_FAMILIES`). The profile stores exactly one family in
`Profile.enabledExecutors` (a single-element array), and `nodeArgv` continues to
forward it as `--enabled-executor <family>`. This both adds Hermes and removes the
pre-existing invalid-multi-family hazard.

**No fallback selection** (per the "don't hide problems with fallback behavior"
rule):

- A **new** manual profile starts with **no family selected** (placeholder "Choose an
  agent client"). Save / issue-connect-credentials is **disabled until a family is
  explicitly chosen** — no silent default to Codex. This also fixes the current
  latent bug where both toggles off can save an empty `enabledExecutors`.
- For an **existing** profile, select `enabledExecutors.first` only when it is a
  supported family; if it is empty or an unrecognized/legacy value, leave the picker
  **unselected and flag it** ("This profile has no valid agent client — choose one"),
  forcing a correction rather than coercing to Codex.

The editor therefore can never emit an empty or coerced family: every saved profile
carries exactly one explicitly chosen supported family, and a corrupt/legacy profile
is surfaced, not masked.

No `acpx_agent` handling is in scope: the macOS `Profile` model has no `acpxAgent`
field and `nodeArgv` does not forward `--acpx-agent` today, so acpx continues to run
with its default agent exactly as it does now. Adding acpx-agent persistence/argv is
explicitly out of scope for this workstream.

### B5. `ExecutorSettingsClient` per family

The probe call takes the family and invokes `newbro executor probe --executor <family> --json`;
`install`/`use` calls likewise dispatch on family (`install-hermes` vs
`install-codex`). The Hermes `signIn` action is informational text only (the user
runs `hermes setup --portal` themselves), mirroring `signInCodex`.

---

## Error handling

- CLI: `install-hermes` failures raise `RuntimeError` with actionable messages; no
  silent fallback. A non-interactive `hermes auth` check that errors yields
  `authenticated: None`, never a probe failure.
- App: a missing binary blocks profile start (`setUpHermes`); a confidently
  unauthenticated Hermes (`authenticated == false`) blocks start (`signInHermes`),
  mirroring Codex's login-required block; `authenticated == true`/`None` is ready, so
  an uncertain auth check never false-blocks. Per-family busy/log isolates one
  family's setup from another's.

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
  `.blocked` / `setUpHermes`; Hermes present + `authenticated == false` → `.blocked` /
  `signInHermes`; Hermes present + `authenticated == true` → `.ready`; Hermes present
  + `authenticated == nil` → `.ready` (uncertain never false-blocks); an acpx profile
  → `.ready` (no probe/gate); **mixed-family** — a Codex profile and a Hermes profile
  each resolve against their own family's probe from `probeByFamily`.
- Hermes Settings pane shows the Sign-in action when `authenticated == false`/`nil`
  and a "signed in" indicator when `true`.
- `ExecutorSettingsClientTests`: per-family probe/install dispatch (codex, hermes).
- Scoped refresh: `refreshProbe(for:)` issues a probe for only the requested family;
  the Codex pane's Refresh probes only codex and the Hermes pane's only hermes; a
  Codex profile's start diagnosis does not probe hermes (assert via a fake
  probe-runner recording which families were invoked).
- Profile editor: a new profile has no family pre-selected and Save/issue is disabled
  until one is chosen; selecting yields exactly one family in
  `Profile.enabledExecutors`; an existing profile with empty/unrecognized
  `enabledExecutors` loads unselected/flagged (not coerced to codex); `nodeArgv`
  forwards a single `--enabled-executor`.

## Flagged unknowns (resolve during implementation)

1. Whether the `install.sh` non-TTY path installs the binary cleanly in practice is
   **unverified** (inferred from the script, not vendor-documented). A2 is therefore
   defensive by construction (stdin from `/dev/null`, bounded timeout, hard error on
   block/failure). If implementation finds the headless install unreliable, the
   documented product fallback is the install-failure message (in the CLI and in the
   B3 setup log) instructing the user to run the install script and `hermes setup
   --portal` manually — surfaced exactly as Codex surfaces install-codex failures, no
   Terminal launch. This is an accepted fallback, not a silent degradation.
