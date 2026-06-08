# Newbro Startup And Management Refactor Spec

## Status

Approved for `GOAL.md` compilation. The approved direction is to refactor the
startup and management layer first, keep runtime/product behavior intact unless
a startup/config boundary requires a narrow change, avoid `dev
--with-executor-node`, keep `stop` out of scope, and allow legacy config cleanup
when it reduces operational complexity.

## Goal

Refactor Newbro so a developer or operator can install, configure, start,
inspect, and manage the project through a small, coherent set of commands.
Starting or managing Newbro should not require knowing which internal process,
config file, port, frontend package manager, connector mode, or executor-node
mode is involved.

The target outcome is a simpler operational surface, not a rewrite of the
Communication Brain, Execution Brain, protocol models, executor semantics, or
frontend product behavior.

## Current Problems From Repo Inspection

- The recommended happy path is already short in docs:
  `./install.sh`, `./newbro setup`, `./newbro doctor`, `./newbro dev`.
  However the implementation behind it is spread across `install.sh`,
  `newbro`, `src/newbro/cli/main.py`, runtime config loaders, service app,
  connector host, executor node, frontend scripts, and deployment docs.
- `src/newbro/cli/main.py` owns many unrelated concerns in one file:
  parser construction, interactive setup, env/YAML rendering, process
  supervision, service install, systemd rendering, frontend package-manager
  selection, port checks, connector setup, executor setup, invite creation, and
  subprocess command construction.
- Several commands overlap in meaning:
  `dev`, `backend`, `frontend`, `start`, `connector run`, `executor run`,
  `service install`, and `service start`. The distinctions are documented, but
  the CLI does not expose a single status/control model for them.
- Setup and runtime config are split between `~/.newbro/.env`,
  `~/.newbro/config.yaml`, legacy `SYNAPSE_*` names, connector YAML sections,
  and command-line overrides.
- `doctor` checks prerequisites and ports, but it does not give a complete
  service status view for backend/frontend/connector/executor-node processes.
- `./newbro dev` starts backend and frontend. Real execution still requires an
  explicit detached executor node connection flow, and the CLI/status surface
  should make that state easy to inspect without trying to hide the node
  credential model.
- Production and deployment paths are distributed across `start`,
  `service install`, Docker/GitHub Actions docs, Vercel UI docs, connector-host
  docs, and Ubuntu systemd docs.

## Product Decisions

- Keep one obvious local command path:
  `./install.sh`, `./newbro setup`, `./newbro dev`.
- Keep advanced commands available, but make their relationship explicit:
  backend-only, frontend-only, service production mode, standalone connector
  host, detached executor node.
- Prefer a unified CLI management layer over more documentation. Docs should
  explain the commands, not compensate for an unclear command model.
- Preserve the essential user entrypoints, but do not over-optimize for legacy
  compatibility. The repo-root `./newbro`, installed/package `newbro`, and the
  documented local happy path should keep working. Legacy config names or
  shapes may be simplified when the new behavior has clear migration docs and
  visible errors.
- Refactor for maintainability in phases. Do not attempt a full product rewrite
  or frontend redesign.
- Fail visibly when a required dependency, config value, build artifact, port,
  or child process is missing. Do not add silent startup fallbacks.

## In Scope

- CLI structure and command behavior under `src/newbro/cli/`.
- Repo bootstrap wrapper `./newbro` and `install.sh` only where needed to align
  with the new CLI management model.
- Runtime/service process management for:
  - local main service
  - Vite frontend dev server
  - production service app
  - optional standalone connector host
  - detached executor node command generation and local setup checks
- Config loading and setup UX for `~/.newbro/.env` and
  `~/.newbro/config.yaml`.
- Health/status/doctor output for local development and operation.
- Stable docs under `README.md`, `docs/guides/local-dev.md`,
  `docs/guides/cli.md`, `docs/guides/connector-host.md`, and deployment docs
  if command behavior changes.
- Tests for CLI parsing, command construction, setup/config behavior, process
  management, status output, docs-visible commands, and regression paths.

## Non-Goals

- Do not rewrite the Communication Brain, Execution Brain, protocol models,
  blackboard semantics, executor adapter contracts, connector API contracts, or
  UI product workflows unless a startup/management boundary requires a narrow
  change.
- Do not remove detached executor-node architecture.
- Do not remove standalone connector-host deployment support; make it clearly
  optional.
- Do not rename public package/module names or break the installed `newbro`
  console script.
- Legacy `SYNAPSE_*` compatibility may be reduced or migrated when it directly
  simplifies startup and management. Any breaking change must be explicit in
  docs, surfaced by `setup`/`doctor`/`status`, and covered by tests.
- Do not make setup require network access beyond dependency installation that
  already exists.
- Do not introduce a long-running daemon manager or external supervisor beyond
  existing subprocess management/systemd support unless explicitly approved.

## Proposed Refactor Shape

### CLI Modules

Split `src/newbro/cli/main.py` into focused modules while preserving the public
command surface:

- `parser.py`: argparse construction and command routing
- `commands/setup.py`: setup and config writing
- `commands/dev.py`: local dev process orchestration
- `commands/status.py`: status/doctor checks
- `commands/service.py`: production service and systemd helpers
- `commands/connector.py`: connector setup/run helpers
- `commands/executor.py`: executor node setup/run helpers
- `config_files.py`: `.env` and YAML read/write/render helpers
- `processes.py`: child process command specs, lifecycle, signals, and output
- `paths.py`: repo/package path discovery
- `checks.py`: dependency, port, config, frontend-build, and health checks

Names may change during implementation, but the final code should make these
ownership boundaries clear.

### Command Model

Keep existing commands working:

```bash
./newbro setup
./newbro doctor
./newbro dev
./newbro backend
./newbro frontend
./newbro start
./newbro connector setup
./newbro connector run
./newbro executor setup
./newbro executor run --base-url ... --node-id ... --token ...
./newbro service install
./newbro service start
./newbro service stop
./newbro service restart
```

Add or refine management commands so the operational model is visible:

- `./newbro status`: summarize configured files, dependency readiness, port
  usage, reachable local service endpoints, frontend dev/build availability,
  connector configuration, and executor-node readiness.
- Executor-node management remains explicit through `./newbro executor setup`
  and `./newbro executor run`. `dev` should not grow a `--with-executor-node`
  mode unless a later product decision introduces a safe local credential
  ownership model.

### Config Model

- Define a typed internal model for local management settings that can be
  projected from `.env`, `config.yaml`, and CLI flags.
- Prefer one clear config ownership model. Keep `.env` for secrets and values
  that truly need environment-variable behavior; keep `config.yaml` for
  structured runtime, connector, executor-node, and connector module settings.
  Migrate or deprecate duplicate legacy fields when they make startup behavior
  harder to understand.
- Make `setup`, `doctor`, and `status` use the same config parser and validation
  path.
- Report missing or invalid config with actionable field names and exact files.

### Process Management

- Introduce a `ManagedProcessSpec` style abstraction for commands started by
  `dev`, `backend`, `frontend`, `start`, `connector run`, and executor helpers.
- Centralize signal handling, startup lines, exit reporting, and shutdown order.
- Preserve current Ctrl+C behavior for foreground dev runs.
- Do not hide child process failures. If one required child exits, stop the
  group and return that exit code.

### Documentation

- Update README and local-dev docs so the first-run path is unambiguous.
- Move command reference details into `docs/guides/cli.md`.
- Keep connector-host and deployment docs aligned with the new command model.
- Add a short architecture note for CLI/operations ownership if the refactor
  creates stable internal modules.

## Edge Cases

- Repo checkout run before `.venv` exists.
- Installed package run outside a repo checkout.
- Missing Python, missing venv support, missing pip, missing Bun/npm.
- Port already in use.
- Invalid or partially migrated `~/.newbro/config.yaml`.
- Missing `OPENAI_API_KEY`.
- Frontend production build missing for `start`.
- Connector enabled but missing Agora/ASR/TTS credentials.
- Executor-node run without local executor config.
- Non-interactive setup in CI.
- macOS local dev and Linux/systemd deployment.
- Ctrl+C and SIGTERM during multi-process dev runs.

## Verification

Backend tests:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_main.py
.venv/bin/python -m pytest tests/unit/runtime/test_config.py tests/unit/connectors/host/test_config_loader.py
.venv/bin/python -m pytest
```

Frontend checks when command/docs behavior touches frontend scripts or build
expectations:

```bash
cd clients/web
bun run test
bun run build
```

Manual CLI checks, using temporary config homes where possible:

```bash
./newbro --help
./newbro setup --non-interactive
./newbro doctor
./newbro status
./newbro dev --help
./newbro backend --help
./newbro frontend --help
./newbro connector run --help
./newbro executor run --help
```

If a command starts long-running processes, verify command construction and
process lifecycle through tests rather than leaving real servers running.

## Done When

- `src/newbro/cli/main.py` is reduced to a small entrypoint/router; setup,
  process management, status/doctor checks, service/systemd, connector, and
  executor-node concerns live in separate focused modules.
- Existing documented commands continue to parse and dispatch successfully, and
  tests cover their command construction or validation paths.
- A coherent management command exists, preferably `./newbro status`, that
  reports local dependency, config, port, backend/frontend, connector, and
  executor-node readiness without starting services.
- `doctor` and `status` share validation/check code instead of duplicating
  assumptions.
- `setup`, runtime config loading, connector config loading, and executor-node
  local setup use a shared typed config/read/write layer where practical.
- `dev` process orchestration uses a centralized managed-process abstraction
  with clear startup lines, shutdown order, SIGINT/SIGTERM handling, and child
  failure propagation.
- The local happy path remains exactly:
  `./install.sh`, `./newbro setup`, `./newbro doctor`, `./newbro dev`.
- Advanced modes are documented as optional and explicit:
  backend-only, frontend-only, standalone connector host, production `start`,
  Linux `service`, and detached executor node.
- No startup or management failure is hidden by a silent fallback. Missing
  dependency, invalid config, busy port, missing frontend build, connector
  misconfiguration, and executor-node misconfiguration produce explicit CLI
  output and non-zero exit where appropriate.
- Stable docs are updated to match the final command model.
- Focused CLI/config/process tests cover the refactored modules and key edge
  cases.
- `.venv/bin/python -m pytest` passes.
- `bun run test` and `bun run build` pass from `clients/web` if frontend
  scripts/build expectations are changed; otherwise the reason for skipping
  frontend checks is documented.

## Approved Product Decisions

The approved product decisions are:

1. Add a new `./newbro status` command instead of overloading `doctor`.
   `doctor` remains the prerequisite/config gate; `status` becomes the broader
   operational view.
2. Do not add `./newbro dev --with-executor-node`. Keep executor-node startup
   explicit through `./newbro executor setup` and `./newbro executor run`, and
   make `status` explain whether a local/remote executor node is configured or
   connected.
3. Keep `./newbro stop` out of this goal. Without a PID/state-file ownership
   design, Ctrl+C for foreground dev runs and systemd for service runs are the
   honest stop mechanisms.
4. Allow config-file shape changes and legacy key cleanup when they reduce
   startup and management complexity. Existing entrypoints should fail with
   clear migration guidance rather than silently accepting ambiguous old config.

This spec is ready to compile into `GOAL.md`.
