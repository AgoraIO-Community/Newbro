# Repository Role Layout Cleanup Design

## Context

Newbro is now the canonical package and CLI identity. The stable repository
structure doc already says the target Python package is `src/newbro`, organized
by domain boundaries, and warns against introducing a second public package
name. The current checkout has active source mixed with platform clients,
executor app packaging, design prototypes, historical planning files, and
ignored local build artifacts.

The cleanup should make folder roles obvious without moving runtime ownership
into the wrong layer.

## Goals

- Keep `src/newbro` as the Python runtime, protocol, API, CLI, connector,
  executor-node, and adapter package.
- Move user-facing clients out of the Python package tree.
- Move platform-specific executor app wrappers away from client surfaces.
- Move design experiments away from production source.
- Remove or quarantine files that are clearly local state, generated output, or
  no longer relevant to the current `newbro` repo.
- Update current operational docs, scripts, tests, and CI paths.

## Non-Goals

- Do not rename the Python package or CLI.
- Do not move executor-node runtime logic out of `src/newbro`.
- Do not rewrite historical RFCs or old Superpowers plans just because they
  mention old paths.
- Do not remove compatibility fields such as `synapse_base_url` as part of this
  folder cleanup. Those are protocol/config compatibility concerns and need a
  separate design.
- Do not delete ambiguous historical artifacts without an explicit reviewed
  deletion list.

## Target Layout

```text
.
├─ src/newbro/
├─ clients/
│  ├─ web/
│  └─ cardputer/
├─ executor-apps/
│  └─ macos/
├─ prototypes/
│  └─ design/
├─ docs/
├─ tests/
├─ evals/
├─ config/
├─ scripts/
└─ examples/
```

### `src/newbro`

This remains the runtime package and the only public Python package identity.
It keeps:

- `protocol/`
- `blackboard/`
- `communication/`
- `execution/`
- `runtime/`
- `api/`
- `connectors/`
- `executors/`
- `cli/`
- `infrastructure/`
- all other existing runtime subpackages, including `interaction/`,
  `notification/`, `observability/`, and `service/`

The current `src/newbro/ui` should move to `clients/web` because it is a
first-party user-facing client with its own Vite toolchain, not backend package
code.

### `clients`

`clients` contains user-facing surfaces that talk to the Newbro runtime.

- `clients/web`: React/Vite web UI, moved from `src/newbro/ui`.
  The built frontend assets live at `clients/web/dist`; local service defaults
  and Docker runtime copies should serve that path directly.
- `clients/cardputer`: Cardputer firmware/client, moved from `cardputer`.

Cardputer is client-side, analogous to the web UI, even though it has a
different toolchain.

### `executor-apps`

`executor-apps` contains platform-specific apps that supervise or package an
executor-node workflow.

- `executor-apps/macos`: Swift menu-bar app, moved from `macos`.

The macOS app is not a user-facing runtime client in the same sense as web or
Cardputer. It supervises `newbro executor run`, handles local readiness and
updates, and packages the local executor-node experience.

### `prototypes`

`prototypes/design` contains design explorations and visual experiments moved
from `design`.

Prototype-local state files should not remain tracked unless they are needed to
reproduce a design artifact.

### `examples`

`examples` is reserved for minimal runnable examples and integration demos.
Ignored or stale local example outputs should not be treated as source.

## Executor CLI Boundary

The executor CLI and executor-node runtime remain in `src/newbro`.

```text
src/newbro/cli/                  # includes `newbro executor ...`
src/newbro/executors/node/        # Python executor-node process
src/newbro/executors/core/        # executor contracts
src/newbro/executors/adapters/    # Codex, ACPX, mock, hosted adapters

executor-apps/macos/              # Swift supervisor around the CLI
```

This keeps executable runtime logic inside the Python package and limits
`executor-apps` to platform-specific wrappers.

## Migration Mechanics

Move tracked folders with `git mv` so history is preserved:

- `src/newbro/ui` -> `clients/web`
- `cardputer` -> `clients/cardputer`
- `macos` -> `executor-apps/macos`
- `design` -> `prototypes/design`

Then update current operational references with a search-driven pass, not a
fixed hand-written list. For each moved path, grep the repo while excluding
archival design/planning history:

```bash
rg -n "src/newbro/ui|cardputer/|macos/|design/" \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
```

Every non-archival hit should be evaluated and updated unless it is explicitly
describing pre-migration history. This includes ignore files and active agent
instructions, not only scripts and docs. The implementation should keep a final
grep result in its verification notes so missed path updates are visible.

Known current examples include:

- `Dockerfile`
- `.dockerignore`
- `.gitignore`
- `.github/workflows/deploy-ui-vercel.yml`
- `.github/workflows/release.yml`
- `install.sh`
- `AGENTS.md`
- `README.md`
- `docs/README.md`
- `docs/architecture/executors.md`
- `docs/architecture/repository-structure.md`
- `docs/protocol/codex-turn-streaming.md`
- `docs/workaround-audit.md`
- relevant stable docs under `docs/guides/`
- active tests that assert paths or install behavior

Do not bulk-edit archival files under `docs/rfcs/` or historical
`docs/superpowers/plans` and `docs/superpowers/specs`. If a historical file is
still used as a current command reference, update only that operational
reference or promote the information into stable docs.

## Tracked File Audit

Before implementation deletes tracked files, produce a concrete deletion list
and review it. Initial candidates:

- `design/.design-canvas.state.json`: likely design-tool local state.
- `design/.thumbnail`: likely generated design-tool artifact.
- root `GOAL.md`: likely task-specific planning artifact, not stable docs.
- root `SPEC.md`: likely task-specific planning artifact, not stable docs.
- `CLAUDE.md`: keep only if Claude-specific agents still use it; otherwise
  `AGENTS.md` is the active instruction file.
- `evals/communication/*` and `evals/run.py`: currently import `synapse`.
  Either update them to `newbro` if evals are still maintained, or remove the
  stale evals in a reviewed deletion pass.

The Cardputer move has no known current incoming operational references outside
the folder itself, so it should be a low-risk move compared with `clients/web`.

Files with ambiguous historical value should move to an archive only if there
is a clear owner need. Otherwise, prefer stable docs plus Git history over
keeping root-level planning clutter.

## Ignored Local Cleanup

After tracked moves, clean ignored/generated local files separately from Git
changes:

- `__pycache__/`
- `.pytest_cache/`
- `.ruff_cache/`
- `.DS_Store`
- build outputs
- egg-info directories
- frontend generated files such as `dist`, `*.tsbuildinfo`, generated
  declaration/build files, and `node_modules`
- ignored legacy local package remnants: `src/synapse`, `src/synopse`
- ignored empty/stale package remnants that contain only bytecode in this
  checkout, such as `src/newbro/edge` and `src/newbro/executors/ui`

This local cleanup can be performed after the reviewed tracked migration. It
should not rely on these ignored files being present in other checkouts.

## Documentation Updates

Stable docs should describe the new role layout:

- `docs/architecture/repository-structure.md` becomes the canonical layout doc.
- `docs/README.md` links to the updated structure.
- `README.md` quick start references `clients/web` for frontend build commands
  and logo asset paths.
- frontend deployment docs reference `clients/web`.
- macOS release docs and workflow references move to `executor-apps/macos`.
- Cardputer docs, if added or updated, live near `clients/cardputer` or under
  stable guides with links to that path.

Append a short factual note to `docs/memories.md` after the implemented
repository structure change lands, because this is an adopted repo architecture
change.

## Testing And Verification

Expected verification after implementation:

- `.venv/bin/python -m pytest`
- frontend test/build from `clients/web`
- Swift tests from `executor-apps/macos`
- Docker build or at least Dockerfile path validation if Docker is available
- PlatformIO Cardputer build/test if the local toolchain is available

If PlatformIO or Docker is unavailable, record the skipped verification and the
reason. The Python tests and frontend build/test should remain required unless
blocked by missing dependencies.

## Risks

- Moving `clients/web` touches CI, Docker, install scripts, docs, and tests.
  Missing one path can break deployment or local setup.
- Historical docs mention old paths. Bulk editing them would create churn and
  distort records, so stable docs must clearly supersede old references.
- Deleting root planning files can remove useful context if they are still
  active. Review the concrete deletion list before implementation deletes them.
- Legacy `synapse_*` config names are still present intentionally. Treat those
  as a separate compatibility migration, not part of folder cleanup.
