# macOS Start Diagnosis And Codex Bootstrap - Design

Status: design for review
Date: 2026-06-06

## Summary

User reports show a profile can remain gray/stopped after clicking Start, while
Settings only says `newbro CLI version unknown` and Codex is unavailable. The
current behavior is diagnosable from code: user-triggered Start can be blocked
before a subprocess launches when Newbro CLI or Codex readiness is false, so the
profile stays truly stopped and the status dot remains gray. The app does not
give the user a single explanation or repair path.

Add a unified macOS readiness diagnosis that runs before profile start, records
the blocker when start cannot proceed, and routes the user to one-click recovery.
For missing Codex, the app should expose a normal-user action named
`Set Up Codex`, not technical Node/npm/Brew instructions. Newbro owns that
bootstrap path and validates Codex before retrying the profile start.

This intentionally supersedes the June 3 onboarding non-goal that avoided
auto-installing Codex. Codex bootstrap is now adopted product behavior when the
user explicitly clicks the setup action.

## Goals

- Fix the inert gray-profile start failure by making user-triggered Start run a
  diagnosis instead of silently returning when readiness is false.
- Keep the profile gray/stopped only when no node process is running, while
  showing the specific reason the start did not happen.
- Preserve `newbro CLI version unknown` as an allowed state, but make it
  actionable.
- Provide a one-click `Set Up Codex` path for non-technical users.
- Stream setup/diagnosis progress in plain language.
- Rerun diagnosis after repair actions and start the profile automatically when
  readiness passes.
- Keep the app as a supervisor over CLI-owned setup and executor commands.

## Non-Goals

- Move executor runtime policy or YAML ownership into Swift.
- Require users to understand or manually choose Homebrew, npm, Node.js, Bun, or
  shell commands for the normal recovery path.
- Silently install Codex without an explicit user action.
- Change the detached executor-node protocol or backend executor ownership.
- Add ACPX bootstrap in this pass.

## Architecture

Add a macOS-side readiness diagnosis model in `NewbroExecutorCore`, such as
`ProfileStartDiagnosis`. It classifies why a profile can or cannot start using
facts from existing runtime helpers and CLI commands.

Diagnosis order:

1. Profile completeness: `base_url`, `node_id`, token, and enabled executors.
2. Newbro CLI resolution through `RuntimeLocator.resolveNewbro()`.
3. Newbro CLI version via `newbro --version`; `unknown` is allowed.
4. Probe support via `newbro executor probe --executor codex --json`.
5. Codex requirement: only Codex profiles need Codex readiness.
6. Codex current/candidate status from the executor probe result.

The app remains a thin supervisor:

- It does not mutate `~/.newbro/config.yaml` directly.
- It invokes CLI-owned actions for setup and executor selection.
- It still launches profiles through the existing `ProfileSupervisor` and
  `newbro executor run` path when diagnosis is ready.

## Diagnosis Model

The diagnosis model should be small and serializable/testable:

- `status`: `ready`, `blocked`, or `checking`.
- `reason`: one of `profile_incomplete`, `newbro_missing`,
  `newbro_too_old_for_probe`, `newbro_version_unknown`, `codex_missing`,
  `codex_configured_but_broken`, `codex_probe_failed`,
  `codex_login_required`, or `installer_failed`.
- `detail`: exact command, path, version, probe error, or failed installer step
  when available.
- `primaryAction`: `install_newbro_cli`, `update_newbro_cli`,
  `set_up_codex`, `open_codex_settings`, `sign_in_codex`, `view_log`,
  `rerun_diagnosis`, or `none`.

`newbro_version_unknown` is not necessarily blocked. It is an informational
state when the CLI can still run the required probe. It becomes actionable when
the same command path also fails probe/update checks.

## Start Flow

When a user clicks `Start`:

1. `AppModel.start` runs diagnosis for the selected profile.
2. If diagnosis is `ready`, the existing supervisor start path runs.
3. If diagnosis is `blocked`, the app stores the latest diagnosis by profile id
   and does not call the supervisor.
4. The profile row remains `stopped` with a gray dot because no node process
   exists, but its submenu shows the blocker and recovery action.

This replaces the current user-visible silent return from start gating. Internal
helpers may still return optional lifecycle actions, but user-triggered actions
must record a diagnosis when they do not launch.

Autostart and paste-autostart should also use diagnosis, but they should avoid
notification spam. They may store the blocker and show it in the menu/settings
without repeatedly notifying on every launch.

## Menu UX

The top-level menu should always show runtime rows:

- `newbro CLI vX.Y.Z`, `newbro CLI version unknown`, or
  `newbro CLI not found`.
- `Codex vX.Y.Z`, `Codex detected`, or `Codex not set up`.

For a stopped profile submenu:

- Show `Start`.
- If the last start attempt was blocked, show a disabled explanation row
  directly under Start, for example `Start blocked: Codex is not set up`.
- Show the action-specific row, such as `Set Up Codex...`,
  `Install/Update Newbro CLI...`, `Sign in to Codex...`, or
  `Run Diagnosis...`.

The gray dot means stopped only; it should no longer be the only signal users
get after a failed Start click.

## Settings UX

Settings can keep the existing Updates and Codex areas, but Codex/settings
should include a diagnosis summary:

- Current Newbro CLI state, including `version unknown` if applicable.
- Current Codex state and selected command path if known.
- Candidate Codex binaries from the CLI probe.
- The same primary recovery action shown in the menu.
- A copyable diagnostic detail for support reports.

The Codex binary selection flow remains available for technical recovery, but
the normal missing-Codex path is `Set Up Codex`.

## One-Click Codex Bootstrap

Add a Newbro-owned installer entry point:
`newbro executor install-codex`. The command may wrap a package-included shell
helper internally, but the macOS app calls the CLI subcommand from
`Set Up Codex` so setup ownership stays in the CLI.

`Set Up Codex` requires a working Newbro CLI. If Newbro CLI is missing or too
old to expose the install command, diagnosis should route the user to
`Install/Update Newbro CLI...` first, then rerun diagnosis and offer
`Set Up Codex`.

The user-facing flow:

1. User clicks `Set Up Codex`.
2. The app opens a setup sheet that explains Newbro will install the required
   local Codex tools for this user account.
3. User confirms.
4. The app streams progress:
   - `Preparing Codex setup...`
   - `Installing required runtime...`
   - `Installing Codex...`
   - `Checking Codex...`
   - `Codex is ready`
5. The app reruns diagnosis.
6. If ready, the app starts the profile automatically.

Internal bootstrap behavior:

- Prefer a user-local install that does not require administrator privileges.
- Reuse the repo's existing Bun bootstrap pattern when no usable JavaScript
  package runtime is present.
- Install `@openai/codex` into a user tool path.
- Validate `codex --version`.
- Register the validated command with
  `newbro executor use --executor codex --command <path>`.
- Do not directly edit Newbro executor config from Swift.

OpenAI's current Codex CLI getting-started guidance documents
`npm install -g @openai/codex` as the standard install path and `codex --login`
for sign-in. Newbro may use a user-local runtime internally for one-click setup,
but should still validate the installed `codex` command rather than assuming the
package install succeeded.

## Codex Sign-In

If Codex installs successfully but the probe or a lightweight validation reports
that authentication is required, diagnosis should show `Codex sign-in required`
with a `Sign in to Codex...` action.

The sign-in action may open a terminal-backed process or a dedicated sheet if
the CLI supports a non-terminal login flow. It must not be hidden behind a
generic “Codex unavailable” message.

## Error Handling

Failures must remain observable and specific:

- Missing Newbro CLI: offer `Install/Update Newbro CLI...`.
- CLI version unknown but probe works: informational only.
- CLI too old for probe: offer `Install/Update Newbro CLI...`.
- Codex missing: offer `Set Up Codex...`.
- Codex configured but broken: show the broken path and offer
  `Set Up Codex...` or `Choose Codex Binary...`.
- Codex installer failed: show the failed step and keep a copyable diagnostic.
- Installer cannot bootstrap its required runtime: show the failed bootstrap
  step and copyable diagnostic. Manual commands are a last-resort support aid,
  not the main user journey.

No path should fail only by leaving the profile gray with no explanation.

## Testing

Swift core tests:

- Diagnosis classifies missing profile fields.
- Diagnosis classifies missing Newbro CLI.
- `newbro CLI version unknown` is informational when probe succeeds.
- Unsupported `executor probe` maps to a CLI update action.
- Missing Codex maps to `set_up_codex`.
- Broken current Codex with a valid candidate maps to binary selection or setup.
- User-triggered Start stores a blocked diagnosis instead of silently doing
  nothing.

Swift app/view-model tests where practical:

- Profile submenu renders the last blocked reason under Start.
- Top-level menu renders Newbro CLI and Codex rows.
- `Set Up Codex` streams progress and reruns diagnosis.
- Successful setup starts the originally requested profile.
- Failed setup leaves the profile stopped and shows the failed step.

Installer tests:

- Existing Codex is detected and no install is performed.
- Existing usable package runtime installs Codex and validates `codex --version`.
- Missing package runtime bootstraps the user-local runtime, installs Codex, and
  validates the command.
- Failed runtime bootstrap reports a distinct failed step.
- Failed Codex install reports a distinct failed step.
- Successful install calls `newbro executor use` with the validated path.

Documentation updates:

- `docs/architecture/executors.md`: user-triggered start diagnosis and explicit
  Codex bootstrap ownership.
- `docs/guides/cli.md`: CLI/setup recovery remains available, but macOS app
  owns the normal one-click Codex setup path.
- `macos/README.md`: menu/settings diagnosis, `Set Up Codex`, and sign-in.
- `docs/memories.md`: short adopted-behavior note because this changes runtime
  onboarding and Codex bootstrap behavior.
