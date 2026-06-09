# Hermes as a second executor — design

Status: approved design (pre-implementation)
Date: 2026-06-09

## 1. Goal & scope

Add **Hermes** (Nous Research) as a first-class executor family, peer to `codex`,
driven through Hermes's **TUI Gateway JSON-RPC app-server** over stdio.

V1 is **core run loop only**:

- create session → submit prompt → stream progress → final answer → cancel → follow-up.
- No native thread import, no skills, no audio, no `approval.request`/`clarify.request`
  interactive wiring.

Operational surface is **full**: connector config + version probe +
`newbro executor install-hermes` + macOS menubar readiness/repair UI.

A Hermes node is a *separate* executor node with `enabled_executors: [hermes]`. The
node registry already enforces exactly one executor family per node, so a Bro bound
to that node runs on Hermes. This is the "second executor" delivery: a node family
selectable alongside Codex, not a per-Bro dual-executor mode.

### Integration surface decision

Hermes exposes five programmatic surfaces (Python in-process `AIAgent`, CLI one-shot
`hermes -z`, ACP via `hermes acp`, TUI Gateway JSON-RPC, OpenAI-compatible HTTP API).
We use the **TUI Gateway JSON-RPC app-server** because:

- It is the richest surface for custom backend orchestration (per Hermes docs).
- It is a long-lived JSON-RPC app-server with its own method/event vocabulary —
  the same shape as Codex's app-server, fitting Newbro's detached-node model where
  the node owns native session continuity locally.
- It keeps transport thin and brains separate (AGENTS.md), unlike the in-process
  Python embed which would drag Hermes's dependencies into the node process.

Rejected alternatives: ACP-through-existing-`acpx` (acpx is hardwired to the `acpx`
CLI multiplexer, not a generic ACP stdio client, and gives coarser per-prompt
streaming); OpenAI-compatible HTTP (breaks the local-CLI node model; reserve for a
future remote-Hermes story).

## 2. The adapter — `src/newbro/executors/adapters/hermes/`

New package mirroring `codex/`'s structure, with a from-scratch client:

- **`client.py`** — `HermesGatewayClient`: launches the gateway subprocess, frames
  JSON-RPC over stdio (stdout = JSON-RPC transport, stderr = human logs, per Hermes
  docs), exposes `session_create`, `prompt_submit`, `session_steer`,
  `session_interrupt`, and an async event stream. One long-lived gateway process per
  node, multiplexed by session id (same shape as Codex's single app-server).
- **`session.py`** — `HermesExecutorSession(ExecutorSession)` holding `session_id`,
  `cwd`, and the shared gateway handle.
- **`executor.py`** — `HermesExecutor` implementing the `Executor` protocol
  (`get_capabilities`, `create_session`, `run_task`, `handle_text_instruction`,
  `handle_audio_instruction`, `cancel_run`, `pause_run`), plus `refresh_capabilities`
  and `aclose`.
- **`probe.py`** — `probe_hermes_command()` → `(path, version, ok, error)`, plus
  `HERMES_MINIMUM_SUPPORTED_VERSION` / `..._TEXT`.
- **`__init__.py`** — exports `HermesExecutor`, `HermesExecutorSession`.

### Capabilities

```
executor_type             = "hermes"
supports_follow_up        = True
supports_cancel           = True
supports_pause            = False   # see note below: no resume → interrupt is cancel, not pause
supports_resume           = False
supports_thread_list      = False
supports_audio_instruction= False
skills                    = []
```

**Pause/resume:** `supports_pause=False` for V1. In Newbro, Codex pause works only
because Codex has resume/thread continuity: pause interrupts now and resumes later
from a persisted handle (`session.py` gates `pause_run` behind `supports_pause`).
Hermes V1 has no resume path, so an interrupt is indistinguishable from a cancel.
Advertising pause would promise a resumable paused state we do not implement.
`pause_run` is therefore not exercised by the runtime (the `supports_pause` guard
skips it); the method is implemented as an explicit unsupported no-op. Resume can be
added later (Hermes persists sessions to `~/.hermes/state.db`), at which point both
flags flip together.

`refresh_capabilities()` probes the binary and sets `version`, `minimum_version`,
and `availability_reason` (None when supported; a reason string like
`unsupported_hermes_version` / `hermes_not_found` when not). When unsupported it
advertises the capability flags as unavailable rather than pretending to work.

## 3. Protocol mapping (Hermes gateway → generic `ExecutorEvent`)

Newbro calls → Hermes gateway methods:

| Newbro call | Hermes gateway method |
|---|---|
| `create_session(workspace_id)` | `session.create` (cwd = resolved workspace) |
| `run_task` / `handle_text_instruction` (new run) | `prompt.submit` |
| `handle_text_instruction` (follow-up on a live session) | `session.steer` |
| `cancel_run` | `session.interrupt` |
| `pause_run` | unsupported no-op (see §2 pause/resume) |

**Single follow-up contract (no fallback).** V1 follow-ups use `session.steer` and
nothing else. If `session.steer` is unavailable for the target session (e.g. the
session is not live, or the gateway rejects steer), the follow-up **fails
observably** with a `FAILED` event carrying the reason — it does **not** silently
fall back to a fresh `prompt.submit`. This honors AGENTS.md's "no fallback behavior
by default" rule and is covered by a dedicated test (§8).

Hermes gateway events → `ExecutorEventType`:

| Hermes event | `ExecutorEventType` | Notes |
|---|---|---|
| `message.delta` | `PROGRESS` | streaming commentary; carried in `message` |
| `tool.start` / `tool.progress` / `tool.complete` | `PROGRESS` | tool activity narration |
| `message.complete` | `COMPLETED` | settled final answer in `message` |
| error / nonzero gateway exit | `FAILED` | stderr summary in `message` |
| interrupt acknowledged | `CANCELLED` | |
| `approval.request` / `clarify.request` | `BLOCKED` (terminal) | **out of V1**: terminates the run as non-interactively blocked |

**Approval/clarify are terminal in V1, not progress.** `ExecutorEventType.BLOCKED`
is a terminal-ish runtime state: `run_manager` sets `RunStatus.BLOCKED`, task
`WAITING_USER_INPUT`, `run.block_reason`, and emits the `exec.run.blocked` terminal
observability event. Since V1 has **no** response path, an `approval.request` /
`clarify.request` ends the run as blocked, carrying the request text in
`block_reason` and the structured request in `metadata["blocked_event"]`. The run
parks in `WAITING_USER_INPUT` until the user cancels it — this is the honest,
observable V1 limitation, not a silent stall or a "progress" note. Wiring an
interactive response path (`SupplyInteractionResponseCommand`) is explicit future
scope.

This uses Newbro's **generic** executor-event normalization. It does **not** touch
Codex's special multi-message-turn contract (`_merge_timeline_turn`,
`_record_native_turn_reasoning`, the phase/commentary invariants in AGENTS.md).
Hermes is the generic `ExecutorEvent` path, so the Codex-turn invariants and their
tests stay untouched.

## 4. Node wiring

- **`executors/node/service.py` → `_build_executors`**: add an
  `elif executor_type == "hermes"` branch constructing
  `HermesExecutor(command=…, minimum_version=…, timeout_seconds=…)` from the
  `executors.hermes` config block.
- **`_descriptor`**: already generic. `supports_thread_list` remains Codex-only
  (Hermes reports false). No change needed beyond the executor reporting capabilities.
- **`executors/node/config.py` / connector YAML**: read `executors.hermes.command`
  (default `hermes`) and optional `executors.hermes.timeout_seconds`.
- **Single source of truth for supported families.** There is already a runtime
  constant `runtime/config.py: SUPPORTED_DETACHED_EXECUTOR_TYPES = ("codex", "acpx")`,
  published into settings (`detached_executor_types`) at `load_settings()`. Adding a
  *separate* `families.py` constant would leave this one stale and let API/status/
  config drift. Instead: define the canonical tuple once in a low-level neutral module
  `newbro/executors/families.py` as
  `SUPPORTED_EXECUTOR_FAMILIES = ("codex", "acpx", "hermes")`, and have
  `runtime/config.py` **import/alias** it (`SUPPORTED_DETACHED_EXECUTOR_TYPES =
  SUPPORTED_EXECUTOR_FAMILIES`) rather than defining its own literal. Layering is fine
  (runtime already depends on executors). Every other reference — registry, CLI
  parsers, setup prompts, node `__main__` — imports this one tuple.
- **Node registry** (`executors/node/registry.py`): today it only enforces *exactly
  one* family per node (`len == 1`); it never whitelists which families are valid, so a
  typo or unsupported family is silently accepted. Have `create_node` / `update_node`
  validate membership against `SUPPORTED_EXECUTOR_FAMILIES`. No `acpx_agent`-style
  special field is required for Hermes.
- **`aclose`**: `HermesExecutor.aclose()` terminates the gateway subprocess; it is
  picked up by the existing `ExecutorNodeService.aclose` loop and SIGTERM/SIGINT
  handling (no new shutdown plumbing required).

## 5. CLI operational surface — `cli/commands/executor_settings.py`

The CLI surface spans **five** files. All must change or the new family is
unreachable somewhere in the chain:

**`cli/parser.py`** (top-level argparse) — today hardcodes Codex-only choices:
- `probe --executor` and `use --executor`: change `choices=["codex"]` →
  `choices=SUPPORTED_EXECUTOR_FAMILIES` (or the probeable subset).
- `--enabled-executor`: change `choices=["codex", "acpx"]` → include `"hermes"`.
- Add an `install-hermes` subparser parallel to `install-codex`.

**`cli/dispatch.py`** (`cmd_executor`) — today only routes `install-codex`. Add a
route: `install-hermes` → `executor_settings_command.run_executor_install_hermes`.

**`executors/node/__main__.py`** (the **detached node's own** argparse) — this is a
second parser the top-level CLI forwards into: `command_specs.executor_node_command`
builds `python -m newbro.executors.node --enabled-executor <family> …`, and
`__main__.build_parser` independently hardcodes `--enabled-executor
choices=["codex", "acpx"]`. Without updating it, a forwarded `--enabled-executor
hermes` is rejected by the node process even though the top CLI accepted it. Change
its choices to `SUPPORTED_EXECUTOR_FAMILIES`.

**`cli/prompts.py` + `cli/setup_resolvers.py`** (the interactive `newbro executor
setup` path) — `prompt_executor_selection` hardcodes `executors = ["codex", "acpx"]`,
and `resolve_executor_setup_values` only writes Codex/ACPX executor blocks. Without
Hermes here, the normal setup path cannot create `executors.hermes.command`. Add
`hermes` to the selection list (from `SUPPORTED_EXECUTOR_FAMILIES`) and a Hermes
branch that prompts for the command and writes the `executors.hermes` block.

**`cli/commands/executor_settings.py`** — generalize the Codex-only logic:
- `SUPPORTED_EXECUTORS = list(SUPPORTED_EXECUTOR_FAMILIES)` (shared constant).
- `run_executor_probe` / `run_executor_use` dispatch on `args.executor` instead of
  rejecting any non-codex value.
- Add `run_executor_install_hermes` + `install_hermes_cli` (install via Hermes's
  documented installer, mirroring the bun/codex install-step flow shape) and
  `set_hermes_command` (writes `executors.hermes.command` + adds `hermes` to
  `enabled_executors`).
- Introduce a generic `probe_payload(executor, *, config_path)` so
  `newbro executor probe --executor hermes --json` returns the same shape the macOS
  app consumes, backed by `hermes.probe`.

## 6. macOS menubar app — `executor-apps/macos/`

Generalize the Codex-specific readiness path so a `hermes` profile gets the same UX:

- **`ProfileStartDiagnosis.swift`**: currently branches on
  `enabledExecutors.contains("codex")` with Codex-only reasons/actions. Refactor to an
  executor-agnostic diagnosis keyed off the profile's enabled family, adding Hermes
  variants (`hermesMissing`, `hermesProbeFailed`, `hermesConfiguredButBroken`,
  `setUpHermes`, `openHermesSettings`). Codex reasons/actions stay; Hermes mirrors them.
- **`ExecutorSettingsClient.swift`**: call `newbro executor probe --executor <family>`
  generically rather than assuming codex.
- **`AppModel.swift` — per-family probe state.** Today `AppModel` holds a *single*
  global `executorProbe` and `codexStatus`, and `diagnoseStart` passes that one probe
  to *every* profile. With one Codex profile and one Hermes profile, a single probe
  result cannot diagnose both. Replace the globals with per-family maps —
  `probeByFamily: [String: ExecutorProbe]` and `statusByFamily: [String: CommandStatus]`
  (plus per-family `executorSettingsError`) — and have `diagnoseStart` select the probe
  for the profile's own family. The menu-bar status line shows the status of each
  configured family.
- **`ProfileEditView` / `ExecutorSettingsView`**: today the profile editor uses two
  *independent* toggles (`codex`, `acpx`), which already allows invalid multi-family
  profiles and would get worse with a third Hermes toggle. Replace the toggles with a
  **single-choice executor selector** (a `Picker` over a shared
  `supportedExecutorFamilies` constant — the Swift mirror of §4's
  `SUPPORTED_EXECUTOR_FAMILIES`). This both adds Hermes and fixes the pre-existing
  multi-family hazard in code we are already touching. The selected family drives the
  probe result and repair action shown.
- **Sign-in**: Hermes uses OAuth (`hermes setup --portal`), so the Codex
  `signInCodex` action generalizes to a family-aware `setUp`/`signIn` action that runs
  the selected family's setup command. Hermes repair delegates to the CLI-owned
  install/setup commands (the Swift app does not edit executor YAML directly).

## 7. Error handling

Per AGENTS.md golden rules (fix root causes, no silent fallback):

- Gateway launch failure or unsupported/missing version → set `availability_reason`;
  the executor advertises unavailable instead of pretending.
- Gateway crash mid-run → emit `FAILED` with a stderr summary.
- Interrupt → emit `CANCELLED`.
- `aclose()` terminates the gateway subprocess; best-effort teardown must not block
  other executors or process exit (parallels `CodexExecutor.aclose`).

## 8. Testing (TDD)

- **Unit (adapter)**: `HermesExecutor.run_task` against a **fake stdio JSON-RPC
  transport** replaying a recorded gateway exchange
  (`docs/protocol/fixtures/hermes-gateway-sample.jsonl`); assert the
  `PROGRESS … COMPLETED` sequence, cancel → `CANCELLED`, failure → `FAILED`.
- **Follow-up contract**: `session.steer` drives a live follow-up; an unsteerable
  follow-up emits `FAILED` (proves no silent `prompt.submit` fallback).
- **Approval/clarify**: an `approval.request` event terminates the run as `BLOCKED`
  with `block_reason` + `metadata` (proves terminal, not progress).
- **Capabilities**: `supports_pause=False`, `supports_resume=False`,
  `supports_thread_list=False`; `pause_run` is an unsupported no-op.
- **Probe**: version-too-old / missing binary → correct `availability_reason`.
- **Node**: `_build_executors` constructs a Hermes executor from config;
  `_descriptor` reports the expected capability flags.
- **Families constant**: `runtime/config.py` exposes the aliased
  `SUPPORTED_DETACHED_EXECUTOR_TYPES` including `hermes` (proves no drift from
  `SUPPORTED_EXECUTOR_FAMILIES`).
- **Registry**: an unsupported family value is rejected; `hermes` is accepted; two
  families still rejected.
- **CLI (top parser)**: `probe --executor hermes` parses and returns the expected
  payload; `dispatch` routes `install-hermes`; `--enabled-executor hermes` parses;
  `set_hermes_command` writes config.
- **CLI (node parser)**: `executors/node/__main__.build_parser` accepts
  `--enabled-executor hermes`.
- **CLI (setup)**: the setup resolver, given a `hermes` selection, writes an
  `executors.hermes.command` block.
- **Swift**: extend `ProfileStartRulesTests` / `ProfileStartDiagnosisTests` with
  Hermes readiness cases (missing, broken, ready, sign-in required); the editor's
  single-choice selector yields exactly one family; **mixed-family** diagnosis — a
  Codex profile and a Hermes profile each resolve against their own family's probe
  from `probeByFamily` (not a shared global).

## 9. Docs

- Update `docs/architecture/executors.md`: Hermes as a real adapter family alongside
  Codex/ACPX.
- Add `docs/protocol/hermes-gateway.md`: the method/event mapping plus fixture
  reference.
- Append a short factual note to `docs/memories.md`.

## 10. Flagged unknowns (resolve during implementation, not blocking design)

Against a live `hermes` install:

- (a) The exact gateway launch invocation and whether stdio or WebSocket is preferred.
- (b) The exact JSON-RPC param/result envelopes for the documented methods
  (`session.create`, `prompt.submit`, `session.steer`, `session.interrupt`) and
  events (`message.delta`, `message.complete`, `tool.*`).

The mapping in §3 is the contract; only the wire spellings need confirming. The fake
transport in §8 is recorded from the live gateway once (a) and (b) are pinned.
