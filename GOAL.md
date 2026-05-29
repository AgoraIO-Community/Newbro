<goal>
Refactor Newbro's startup and management layer so a developer or operator can install, configure, start, inspect, and manage the project through a small, coherent CLI surface. The final result must make the local happy path obvious, split the oversized CLI implementation into maintainable ownership areas, add a read-only operational status view, centralize process/config/check behavior, update docs, and keep runtime/product behavior unchanged except for narrow startup/config boundary fixes.
</goal>

<context>
Read first:
- `AGENTS.md`
- `SPEC.md`
- `README.md`
- `docs/README.md`
- `docs/guides/local-dev.md`
- `docs/guides/cli.md`
- `docs/guides/connector-host.md`
- `docs/guides/public-hosted-deployment.md`
- `docs/guides/ubuntu-systemd.md`
- `docs/architecture/overview.md`
- `docs/architecture/executors.md`
- `docs/architecture/observability.md`

Primary implementation areas:
- `src/newbro/cli/main.py`
- `src/newbro/cli/`
- `install.sh`
- `newbro`
- `src/newbro/runtime/config.py`
- `src/newbro/connectors/host/config.py`
- `src/newbro/connectors/voice/agora_convoai/settings.py`
- `src/newbro/service/app.py`
- `src/newbro/api/app.py`
- `src/newbro/executors/node/`
- `config/connector.example.yaml`
- `tests/unit/cli/test_main.py`
- `tests/unit/runtime/test_config.py`
- `tests/unit/connectors/host/test_config_loader.py`
- frontend package scripts in `src/newbro/ui/package.json` only if command/build expectations change

Useful discovery commands:
- `rg -n "def cmd_|build_parser|run_managed_processes|run_checked|doctor|status|setup|connector|executor|service|frontend|backend|start" src/newbro/cli tests/unit/cli`
- `rg -n "SYNAPSE_|NEWBRO|config.yaml|\\.env|connector_host|executor_node|OPENAI_API_KEY" src/newbro install.sh README.md docs config tests`
- `rg -n "newbro (setup|doctor|dev|backend|frontend|start|status|connector|executor|service)|./newbro|\\.venv/bin/newbro" README.md docs tests`
- `rg -n "uvicorn|subprocess|Popen|systemd|systemctl|frontend|bun|npm|port|health" src/newbro/cli src/newbro/service src/newbro/connectors tests`
- `find src/newbro/cli -maxdepth 3 -type f | sort`

Current problem shape:
- The documented happy path is short: `./install.sh`, `./newbro setup`, `./newbro doctor`, `./newbro dev`.
- The implementation behind that path is spread across `install.sh`, the repo launcher, a very large `src/newbro/cli/main.py`, runtime config loaders, service app, connector host, executor node, frontend scripts, and deployment docs.
- `src/newbro/cli/main.py` currently mixes parser construction, setup, env/YAML rendering, subprocess supervision, service/systemd install, frontend tool selection, port checks, connector commands, executor commands, invite creation, and command construction.
- `doctor` is a prerequisite/config gate, but there is no broader read-only operational status command.
- Detached executor nodes should remain explicit through `newbro executor setup` and `newbro executor run`; do not add `dev --with-executor-node`.
</context>

<constraints>
- Refactor the startup/management layer first. Do not rewrite Communication Brain behavior, Execution Brain scheduling, protocol models, blackboard semantics, executor adapter contracts, connector API contracts, or UI product workflows unless a startup/config boundary requires a narrow change.
- Preserve the essential user entrypoints: repo-root `./newbro`, installed/package `newbro`, and the documented local happy path.
- Do not over-optimize for legacy compatibility. Legacy config names or shapes, including `SYNAPSE_*`, may be simplified or migrated when that reduces startup and management complexity.
- Any breaking config change must be explicit in docs, surfaced by `setup`, `doctor`, or `status`, and covered by tests. Do not silently accept ambiguous old config.
- Keep `./newbro dev` backend+frontend only. Do not add `./newbro dev --with-executor-node`.
- Keep executor-node startup explicit through `./newbro executor setup` and `./newbro executor run`.
- Keep `./newbro stop` out of this goal unless a separate explicit PID/state-file ownership design is approved later.
- Do not remove detached executor-node architecture.
- Do not remove standalone connector-host deployment support; make it clearly optional.
- Do not rename the public package/module names or break the installed `newbro` console script.
- Do not make setup require network access beyond existing dependency installation behavior.
- Do not introduce a new long-running daemon manager or external supervisor beyond existing subprocess management and systemd support.
- Fail visibly when a required dependency, config value, build artifact, port, or child process is missing. Do not add silent startup fallbacks.
- Keep transport thin and preserve Newbro's Communication Brain / Execution Brain boundaries.
- Preserve unrelated user changes in the worktree.
- Use `apply_patch` for manual edits.
</constraints>

<done_when>
- `src/newbro/cli/main.py` is reduced to a small entrypoint/router. Setup, config file IO, status/doctor checks, process management, service/systemd, connector, executor-node, command construction, and path logic live in focused modules under `src/newbro/cli/`.
- Existing documented commands still parse and dispatch successfully:
  `setup`, `doctor`, `dev`, `backend`, `frontend`, `start`, `connector setup`, `connector run`, `executor setup`, `executor run`, `service install`, `service start`, `service stop`, `service restart`, and `invite create`.
- A new read-only `./newbro status` command exists. It reports, without starting services, dependency readiness, config file presence/validity, important ports, backend/frontend reachability when applicable, frontend dev/build availability, connector readiness, and executor-node readiness or explicit next steps.
- `doctor` remains a prerequisite/config gate and shares check/config code with `status` instead of duplicating assumptions.
- Setup, runtime config loading, connector config loading, and executor-node local setup use a shared typed config/read/write layer where practical. Duplicate or legacy config fields may be migrated or deprecated when that simplifies the model.
- `dev`, `backend`, `frontend`, `start`, `connector run`, and executor helper command construction use a centralized process/command abstraction with clear startup lines, shutdown order, SIGINT/SIGTERM handling, and child failure propagation.
- `./newbro dev` remains backend+frontend only. The goal does not add `--with-executor-node`.
- Executor-node management remains explicit through `./newbro executor setup` and `./newbro executor run`, and `status` explains executor-node configuration/connection readiness.
- `./newbro stop` is not added. Docs clearly state that foreground local dev is stopped with Ctrl+C and service mode is stopped through systemd commands.
- The local happy path remains:
  `./install.sh`, `./newbro setup`, `./newbro doctor`, `./newbro dev`.
- Advanced modes are documented as optional and explicit: backend-only, frontend-only, standalone connector host, production `start`, Linux `service`, and detached executor node.
- Missing dependency, invalid config, busy port, missing frontend build, connector misconfiguration, and executor-node misconfiguration produce explicit CLI output and non-zero exit where appropriate.
- Stable docs are updated to match the final command model: at minimum `README.md`, `docs/guides/local-dev.md`, `docs/guides/cli.md`, and `docs/guides/connector-host.md`; update deployment docs if command behavior there changes.
- Add a short stable architecture or guide note for CLI/operations ownership if new CLI module boundaries become source-of-truth design.
- Focused CLI/config/process tests cover parser dispatch, command construction, shared checks, `status`, `doctor`, config migration/deprecation behavior, managed process failure/interrupt behavior, and key edge cases.
- `.venv/bin/python -m pytest tests/unit/cli/test_main.py` passes.
- `.venv/bin/python -m pytest tests/unit/runtime/test_config.py tests/unit/connectors/host/test_config_loader.py` passes if config loading behavior changes.
- `.venv/bin/python -m pytest` passes, or any remaining failure is shown to be unrelated with concrete evidence.
- If frontend scripts or build expectations change, `bun run test` and `bun run build` pass from `src/newbro/ui`; otherwise the reason for skipping frontend checks is documented.
- Final review confirms no runtime/product rewrite was mixed into the operations refactor, no hidden startup fallback was introduced, and the project is simpler to start and inspect than before.
</done_when>

<workflow>
1. Check `git status --short` and identify unrelated dirty files before editing.
2. Read `AGENTS.md`, `SPEC.md`, and the context docs/files listed above.
3. Inventory current CLI responsibilities in `src/newbro/cli/main.py`; group functions by parser/routing, setup/config, process management, service/systemd, connector, executor, checks/status, paths, and misc commands.
4. Inspect current tests in `tests/unit/cli/test_main.py` and related config tests. Identify which behavior must be preserved and where new tests should land.
5. Design the target CLI module boundaries before moving code. Prefer mechanical extraction first, behavior changes second.
6. Extract path and command construction helpers into focused modules. Keep public command behavior stable during extraction.
7. Extract process lifecycle helpers into a centralized process-management module. Preserve Ctrl+C behavior and child failure propagation.
8. Extract config file parsing/rendering and setup helpers into focused modules. Introduce typed internal config/check results where it reduces duplication.
9. Implement shared check/status primitives for dependencies, env/config files, ports, frontend dev/build availability, connector readiness, executor-node readiness, and optional local endpoint reachability.
10. Add `status` to the parser and implement it as read-only output using shared check primitives.
11. Refactor `doctor` to use the shared check primitives while preserving its stricter prerequisite/config-gate role.
12. Keep `dev` backend+frontend only; improve output if useful, but do not add executor-node startup.
13. Ensure executor-node commands remain explicit and that `status` reports clear next steps for executor-node setup/run.
14. Decide any legacy config cleanup from evidence. If a legacy key/shape is removed or deprecated, add migration guidance in CLI output, docs, and tests.
15. Update docs to match the final command model.
16. Add or update focused tests after each behavior-bearing phase. Use tests to verify long-running command construction/lifecycle rather than leaving real servers running.
17. Run focused tests, then broad tests. If frontend scripts/build expectations changed, run frontend checks.
18. Re-run discovery searches against CLI/docs to confirm documented command names and behavior are consistent.
19. Review the diff for accidental runtime/product rewrites, hidden fallbacks, unrelated refactors, and broken compatibility of essential entrypoints.
</workflow>

<verification_loop>
Focused backend checks:
- `.venv/bin/python -m pytest tests/unit/cli/test_main.py`
- `.venv/bin/python -m pytest tests/unit/runtime/test_config.py tests/unit/connectors/host/test_config_loader.py` when config loading or config files change
- Additional focused pytest files for touched connector/executor-node config code

Broad backend check:
- `.venv/bin/python -m pytest`

Frontend checks, only if frontend scripts/build expectations change:
- `cd src/newbro/ui && bun run test`
- `cd src/newbro/ui && bun run build`

Manual/read-only CLI checks, preferably with temporary `HOME`/config paths where tests do not already cover them:
- `./newbro --help`
- `./newbro setup --help`
- `./newbro doctor --help`
- `./newbro status --help`
- `./newbro dev --help`
- `./newbro backend --help`
- `./newbro frontend --help`
- `./newbro connector run --help`
- `./newbro executor run --help`

Artifact checks:
- Confirm `README.md`, `docs/guides/local-dev.md`, `docs/guides/cli.md`, and `docs/guides/connector-host.md` describe the final command model.
- Confirm no doc still recommends `dev --with-executor-node` or `newbro stop`.
- Confirm `status` is documented as read-only and `doctor` as prerequisite/config validation.
- Confirm executor-node startup remains explicit.
- Confirm config migration/deprecation behavior is tested and documented for any compatibility cleanup.

If a check cannot run, document the exact blocker, the files or behavior left unverified, and the residual risk. Do not mark the goal complete because a check was skipped.
</verification_loop>

<execution_rules>
- Check git status before edits.
- Preserve unrelated user changes.
- Prefer `rg` over `grep`.
- Use `apply_patch` for manual edits.
- Read context files before implementation.
- Batch independent file reads in parallel when possible.
- Run focused tests before broad tests.
- Do not paper over failures.
- Do not widen scope into runtime/product rewrites.
- Keep the final answer concise.
- Follow repo guardrails from `AGENTS.md`: preserve Communication Brain and Execution Brain separation, keep transport thin, treat protocol models as the source of truth, diagnose from real state, test the failure mode, verify activation, and update memory deliberately.
- Do not remove or rewrite unrelated existing user changes.
- Do not use destructive git commands unless explicitly requested.
</execution_rules>

<output_contract>
Final response must include:
- Path to the final `SPEC.md` and `GOAL.md`.
- Summary of the CLI/operations refactor performed.
- Summary of new or changed commands, especially `status`, `doctor`, `dev`, executor-node, and service/connector behavior.
- Summary of any config compatibility cleanup or migration behavior.
- Tests and build commands run with outcomes.
- Any skipped checks, blockers, or residual risks.
- Explicit confirmation that runtime/product behavior was not rewritten beyond narrow startup/config boundary changes.
</output_contract>
