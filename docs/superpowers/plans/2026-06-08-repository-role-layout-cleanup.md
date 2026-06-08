# Repository Role Layout Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the repo into role-based folders, repair all current path references, and remove only clearly generated tracked prototype state.

**Architecture:** `src/newbro` remains the Python runtime/package and keeps executor CLI/runtime ownership. User-facing clients move to `clients/`, platform-specific executor app wrappers move to `executor-apps/`, and design experiments move to `prototypes/`. Path updates are driven by grep verification instead of a fixed file list.

**Tech Stack:** Python 3.12, FastAPI/Pydantic/Pytest, React/Vite/Bun/TypeScript, Swift Package Manager, PlatformIO, Docker, GitHub Actions.

---

## File Structure

Move:
- `src/newbro/ui/` -> `clients/web/`
- `cardputer/` -> `clients/cardputer/`
- `macos/` -> `executor-apps/macos/`
- `design/` -> `prototypes/design/`

Modify:
- `.gitignore` and `.dockerignore`: frontend generated artifact ignore paths.
- `Dockerfile`: frontend build context and runtime static asset copy paths.
- `install.sh`: frontend dependency install path.
- `tests/unit/scripts/test_install_sh.py`: install fixture expects `clients/web`.
- `.github/workflows/deploy-ui-vercel.yml`: web client trigger paths and working directories.
- `.github/workflows/release.yml`: macOS package paths.
- `README.md`: logo and frontend build path.
- `AGENTS.md`: active UI invariant path references.
- `docs/architecture/repository-structure.md`: canonical layout.
- `docs/architecture/executors.md`: macOS executor app path.
- `docs/protocol/codex-turn-streaming.md`: web UI invariant test paths.
- `docs/workaround-audit.md`: audit command exclusions and notes.
- `docs/guides/*.md`: current non-archival web/design path references.
- `docs/README.md`: repository structure link text if needed.
- `docs/memories.md`: short factual note after implementation.
- `evals/communication/runner.py`, `evals/communication/scenarios.py`, `evals/run.py`: replace obsolete `synapse` imports/wording with current `newbro` names.

Create:
- `tests/unit/evals/test_evals_imports.py`: guards that eval entrypoints import under the current package name.

Delete:
- `prototypes/design/.design-canvas.state.json`
- `prototypes/design/.thumbnail`

Do not delete in this pass:
- `GOAL.md`
- `SPEC.md`
- `CLAUDE.md`
- `evals/`

Those need a separate reviewed deletion decision because they may still contain useful active or historical context.

---

### Task 1: Update Install Path Test First

**Files:**
- Modify: `tests/unit/scripts/test_install_sh.py`
- Modify: `install.sh`

- [ ] **Step 1: Change the test fixture to create `clients/web`**

In `tests/unit/scripts/test_install_sh.py`, replace the body of `prepare_repo_root` with:

```python
def prepare_repo_root(root: Path) -> None:
    frontend_dir = root / "clients" / "web"
    frontend_dir.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='newbro-cli'\n", encoding="utf-8")
    (frontend_dir / "package.json").write_text(
        '{"name":"newbro-frontend"}\n',
        encoding="utf-8",
    )
```

- [ ] **Step 2: Run one install test and confirm it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/scripts/test_install_sh.py::test_install_sh_macos_skips_existing_system_dependencies -q
```

Expected: fails because `install.sh` still looks for `src/newbro/ui`.

- [ ] **Step 3: Update `install.sh` frontend path**

In `install.sh`, change:

```bash
FRONTEND_DIR="$ROOT/src/newbro/ui"
```

to:

```bash
FRONTEND_DIR="$ROOT/clients/web"
```

- [ ] **Step 4: Run install script tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/scripts/test_install_sh.py -q
```

Expected: all tests in `tests/unit/scripts/test_install_sh.py` pass.

- [ ] **Step 5: Continue without committing**

Do not commit at this point. The repository root does not contain `clients/web`
until Task 2, so this test and script change must be committed together with
the web directory move.

---

### Task 2: Move Web Client And Repair Operational Paths

**Files:**
- Move: `src/newbro/ui/` -> `clients/web/`
- Modify: `.gitignore`
- Modify: `.dockerignore`
- Modify: `Dockerfile`
- Modify: `install.sh`
- Modify: `tests/unit/scripts/test_install_sh.py`
- Modify: `.github/workflows/deploy-ui-vercel.yml`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/protocol/codex-turn-streaming.md`
- Modify: `docs/workaround-audit.md`
- Modify: `docs/guides/agora-conversational-ai.md`
- Modify: `docs/guides/cli.md`
- Modify: `docs/guides/frontend-handoff.md`
- Modify: `docs/guides/frontend-workbench.md`
- Modify: `docs/guides/vercel-ui-deployment.md`

- [ ] **Step 1: Move tracked web client files**

Run:

```bash
mkdir -p clients
git mv src/newbro/ui clients/web
```

Expected: `git status --short` shows renames from `src/newbro/ui/...` to `clients/web/...`.

- [ ] **Step 2: Replace current exact web path references**

Run:

```bash
rg -l "src/newbro/ui" \
  .gitignore .dockerignore Dockerfile .github/workflows/deploy-ui-vercel.yml \
  README.md AGENTS.md docs/protocol/codex-turn-streaming.md docs/workaround-audit.md \
  docs/guides/agora-conversational-ai.md docs/guides/cli.md \
  docs/guides/frontend-handoff.md docs/guides/frontend-workbench.md \
  docs/guides/vercel-ui-deployment.md \
  | xargs perl -0pi -e 's#src/newbro/ui#clients/web#g'
```

Expected: command exits 0 and the listed files refer to `clients/web`.

- [ ] **Step 3: Update Docker runtime asset target**

In `Dockerfile`, keep the frontend build stage at `/app/clients/web` and copy the built web assets into the runtime package location expected by the backend:

```dockerfile
FROM oven/bun:1.3.13-debian AS frontend

WORKDIR /app/clients/web

COPY clients/web/package.json clients/web/bun.lock ./
COPY clients/web/vendor ./vendor
RUN bun install --frozen-lockfile

COPY clients/web ./
RUN bun run build
```

The runtime stage should keep:

```dockerfile
COPY --from=frontend /app/clients/web/dist ./src/newbro/ui/dist
```

Rationale: the source client moves to `clients/web`, but the installed Python runtime can still serve static UI from `src/newbro/ui/dist` if existing backend code expects that package-relative output path.

- [ ] **Step 4: Run path grep for old web path**

Run:

```bash
rg -n "src/newbro/ui" \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
```

Expected: no output.

- [ ] **Step 5: Run frontend checks from new path**

Run:

```bash
cd clients/web
bun run test
bun run build
```

Expected: both commands pass.

- [ ] **Step 6: Run focused backend install tests again**

Run:

```bash
.venv/bin/python -m pytest tests/unit/scripts/test_install_sh.py -q
```

Expected: pass.

- [ ] **Step 7: Commit web move**

Run:

```bash
git add -A .gitignore .dockerignore Dockerfile install.sh tests/unit/scripts/test_install_sh.py .github/workflows/deploy-ui-vercel.yml README.md AGENTS.md docs/protocol/codex-turn-streaming.md docs/workaround-audit.md docs/guides/agora-conversational-ai.md docs/guides/cli.md docs/guides/frontend-handoff.md docs/guides/frontend-workbench.md docs/guides/vercel-ui-deployment.md clients/web
git commit -m "chore: move web client to clients"
```

---

### Task 3: Move Cardputer Client

**Files:**
- Move: `cardputer/` -> `clients/cardputer/`

- [ ] **Step 1: Move tracked Cardputer files**

Run:

```bash
git mv cardputer clients/cardputer
```

Expected: `git status --short` shows renames under `clients/cardputer`.

- [ ] **Step 2: Verify there are no old root Cardputer references**

Run:

```bash
rg -n '(^|[[:space:]"'"'"'(])cardputer/' \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
```

Expected: no output.

- [ ] **Step 3: Run Cardputer build/test if PlatformIO exists**

Run:

```bash
command -v pio >/dev/null 2>&1 && pio test -d clients/cardputer || printf 'SKIP: PlatformIO pio not available\n'
```

Expected: either PlatformIO tests pass or the command prints `SKIP: PlatformIO pio not available`.

- [ ] **Step 4: Commit Cardputer move**

Run:

```bash
git add -A clients/cardputer
git commit -m "chore: move cardputer client under clients"
```

---

### Task 4: Move macOS Executor App

**Files:**
- Move: `macos/` -> `executor-apps/macos/`
- Modify: `.github/workflows/release.yml`
- Modify: `executor-apps/macos/README.md`
- Modify: `docs/architecture/executors.md`

- [ ] **Step 1: Move tracked macOS app files**

Run:

```bash
mkdir -p executor-apps
git mv macos executor-apps/macos
```

Expected: `git status --short` shows renames under `executor-apps/macos`.

- [ ] **Step 2: Replace root macOS paths in workflow and docs**

Run:

```bash
perl -0pi -e 's#--package-path macos#--package-path executor-apps/macos#g; s#mkdir -p macos/release#mkdir -p executor-apps/macos/release#g; s#\./macos/package-app\.sh#./executor-apps/macos/package-app.sh#g; s#macos/dist/Newbro Executor\.app#executor-apps/macos/dist/Newbro Executor.app#g; s#macos/release#executor-apps/macos/release#g' .github/workflows/release.yml
perl -0pi -e 's#swift test --package-path macos#swift test --package-path executor-apps/macos#g; s#\./macos/package-app\.sh#./executor-apps/macos/package-app.sh#g; s#macos/dist/#executor-apps/macos/dist/#g' executor-apps/macos/README.md
perl -0pi -e 's#under `macos/`#under `executor-apps/macos/`#g' docs/architecture/executors.md
```

Expected: current docs and workflow point at `executor-apps/macos`.

- [ ] **Step 3: Verify there are no old root macOS path references**

Run:

```bash
rg -n '(^|[[:space:]"'"'"'(])macos/' \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
```

Expected: no output.

- [ ] **Step 4: Run Swift tests**

Run:

```bash
swift test --package-path executor-apps/macos
```

Expected: pass.

- [ ] **Step 5: Commit macOS move**

Run:

```bash
git add -A .github/workflows/release.yml docs/architecture/executors.md executor-apps/macos
git commit -m "chore: move macos executor app"
```

---

### Task 5: Move Design Prototype And Remove Tracked Prototype State

**Files:**
- Move: `design/` -> `prototypes/design/`
- Delete: `prototypes/design/.design-canvas.state.json`
- Delete: `prototypes/design/.thumbnail`
- Modify: `docs/guides/frontend-workbench.md`
- Modify: `docs/guides/frontend-handoff.md`

- [ ] **Step 1: Move tracked design prototype files**

Run:

```bash
mkdir -p prototypes
git mv design prototypes/design
```

Expected: tracked design files are renamed under `prototypes/design`.

- [ ] **Step 2: Delete tracked local prototype state files**

Run:

```bash
git rm prototypes/design/.design-canvas.state.json prototypes/design/.thumbnail
```

Expected: both files are staged as deleted.

- [ ] **Step 3: Replace stable guide references to design prototype paths**

Run:

```bash
perl -0pi -e 's#design/#prototypes/design/#g; s#`design/`#`prototypes/design/`#g' docs/guides/frontend-workbench.md docs/guides/frontend-handoff.md
```

Expected: stable guide references point to `prototypes/design`.

- [ ] **Step 4: Verify there are no old root design path references**

Run:

```bash
rg -n '(^|[[:space:]"'"'"'(])design/' \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
```

Expected: no output.

- [ ] **Step 5: Commit design move and state cleanup**

Run:

```bash
git add -A docs/guides/frontend-workbench.md docs/guides/frontend-handoff.md prototypes/design
git commit -m "chore: move design prototypes"
```

---

### Task 6: Repair Stale Evals Imports

**Files:**
- Create: `tests/unit/evals/test_evals_imports.py`
- Modify: `evals/communication/runner.py`
- Modify: `evals/communication/scenarios.py`
- Modify: `evals/run.py`

- [ ] **Step 1: Add an import guard test**

Create `tests/unit/evals/test_evals_imports.py`:

```python
from __future__ import annotations

from evals.run import build_argument_parser
from evals.communication.runner import CommunicationEvalResult, format_results


def test_evals_import_under_current_newbro_package_name():
    parser = build_argument_parser()
    parsed = parser.parse_args(["communication"])

    result = CommunicationEvalResult(
        scenario="smoke",
        reply_text="ok",
        tool_names=[],
        passed_expected_tools=True,
        passed_forbidden_tools=True,
        mechanical_reply=False,
        passed_mock_only_reply_rules=True,
    )

    assert parsed.suite == "communication"
    assert '"scenario": "smoke"' in format_results([result])
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/evals/test_evals_imports.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'synapse'`.

- [ ] **Step 3: Update eval imports and wording**

In `evals/communication/runner.py`, replace the old imports with:

```python
from newbro.blackboard import InMemoryBlackboard
from newbro.communication import CommunicationBrain, InMemoryConversationHistory
from newbro.communication.models import OpenAICommunicationModel
from newbro.communication.tools import build_default_tool_registry
from newbro.executors.core import ExecutorCapabilities
from newbro.infrastructure.llm import OpenAIProvider
from newbro.runtime import Settings
```

In `evals/communication/scenarios.py`, replace:

```python
from synapse.protocol import Task, TaskStatus, TaskSummary
```

with:

```python
from newbro.protocol import Task, TaskStatus, TaskSummary
```

In `evals/run.py`, replace:

```python
from synapse.runtime import load_settings
```

with:

```python
from newbro.runtime import load_settings
```

Also replace the parser description:

```python
parser = argparse.ArgumentParser(description="Run Newbro behavior-quality evals.")
```

- [ ] **Step 4: Run eval import test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/evals/test_evals_imports.py -q
```

Expected: pass.

- [ ] **Step 5: Run eval help command**

Run:

```bash
.venv/bin/python evals/run.py --help
```

Expected: command prints help text containing `Run Newbro behavior-quality evals.`

- [ ] **Step 6: Commit eval import repair**

Run:

```bash
git add evals/communication/runner.py evals/communication/scenarios.py evals/run.py tests/unit/evals/test_evals_imports.py
git commit -m "fix: update eval imports for newbro package"
```

---

### Task 7: Update Canonical Repository Docs And Memory

**Files:**
- Modify: `docs/architecture/repository-structure.md`
- Modify: `docs/README.md`
- Modify: `README.md`
- Modify: `docs/memories.md`

- [ ] **Step 1: Update repository structure doc target tree**

In `docs/architecture/repository-structure.md`, replace the recommended root tree with the approved role layout:

```text
.
├─ ARCHITECTURE.md
├─ README.md
├─ LICENSE
├─ CONTRIBUTING.md
├─ pyproject.toml
├─ install.sh
├─ clients/
│  ├─ web/
│  └─ cardputer/
├─ executor-apps/
│  └─ macos/
├─ prototypes/
│  └─ design/
├─ docs/
├─ examples/
├─ schemas/
├─ tests/
├─ evals/
├─ scripts/
└─ src/
   └─ newbro/
```

Replace the note that mentions `exmaple-ui/` with:

```markdown
- `clients/`
  - first-party user-facing clients such as the React/Vite web app and
    Cardputer firmware
  - keep reusable backend, connector, and executor runtime logic out of this
    directory
- `executor-apps/`
  - platform-specific wrappers that supervise executor-node workflows
  - keep executor contracts, adapters, and `newbro executor ...` logic in
    `src/newbro`
- `prototypes/`
  - design explorations and non-production prototypes
```

- [ ] **Step 2: Update README frontend command and logo path**

In `README.md`, ensure the logo uses:

```html
<img src="clients/web/public/newbro.webp" alt="Newbro logo" width="120" />
```

Ensure the frontend build check uses:

```bash
cd clients/web
npm run build
```

- [ ] **Step 3: Add docs index link if missing**

In `docs/README.md`, ensure the Architecture section includes:

```markdown
- [Repository Structure](./architecture/repository-structure.md)
```

If that exact link already exists, leave it unchanged.

- [ ] **Step 4: Append memory note**

Append this line to `docs/memories.md`:

```markdown
- Moved first-party clients to `clients/`, the macOS executor supervisor to `executor-apps/macos`, and design prototypes to `prototypes/design`, while keeping the Python runtime, executor CLI, executor node, and adapters under `src/newbro`.
```

- [ ] **Step 5: Run docs path grep**

Run:

```bash
rg -n "src/newbro/ui|exmaple-ui" docs README.md
```

Expected: no output outside `docs/superpowers/` and `docs/rfcs/`. If output appears in stable docs, update it to current paths.

- [ ] **Step 6: Commit docs and memory update**

Run:

```bash
git add docs/architecture/repository-structure.md docs/README.md README.md docs/memories.md
git commit -m "docs: document role-based repository layout"
```

---

### Task 8: Final Grep Audit And Local Generated Cleanup

**Files:**
- No tracked files should be modified by local cleanup.

- [ ] **Step 1: Run old-path grep audit**

Run:

```bash
rg -n "src/newbro/ui" \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
rg -n '(^|[[:space:]"'"'"'(])cardputer/' \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
rg -n '(^|[[:space:]"'"'"'(])macos/' \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
rg -n '(^|[[:space:]"'"'"'(])design/' \
  --glob '!docs/rfcs/**' \
  --glob '!docs/superpowers/**'
```

Expected: no output. If a hit describes pre-migration history, move that historical note under `docs/rfcs/` or `docs/superpowers/`, or rewrite it to current paths if it is operational.

- [ ] **Step 2: Remove ignored local generated directories and files**

Run:

```bash
git clean -fdX -- . ':!/.venv' ':!/clients/web/node_modules' ':!/clients/web/.vercel' ':!/examples/agora_conversational_ai/.env.local'
```

Expected: ignored generated files are removed while `.venv`, web dependencies, Vercel local state, and local example env secrets are preserved.

- [ ] **Step 3: Verify ignored stale package remnants are gone or still ignored**

Run:

```bash
find src/synapse src/synopse src/newbro/edge src/newbro/executors/ui -maxdepth 2 -type f 2>/dev/null || true
git status --short --ignored | rg "src/synapse|src/synopse|src/newbro/edge|src/newbro/executors/ui" || true
```

Expected: no tracked changes. It is acceptable for no files to be printed.

---

### Task 9: Full Verification

**Files:**
- No file edits.

- [ ] **Step 1: Run Python test suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: pass.

- [ ] **Step 2: Run frontend test and build**

Run:

```bash
cd clients/web
bun run test
bun run build
```

Expected: pass.

- [ ] **Step 3: Run Swift tests**

Run:

```bash
swift test --package-path executor-apps/macos
```

Expected: pass.

- [ ] **Step 4: Validate Docker build path if Docker exists**

Run:

```bash
command -v docker >/dev/null 2>&1 && docker build -t newbro-layout-check . || printf 'SKIP: docker not available\n'
```

Expected: Docker build passes, or command prints `SKIP: docker not available`.

- [ ] **Step 5: Run Cardputer PlatformIO check if available**

Run:

```bash
command -v pio >/dev/null 2>&1 && pio test -d clients/cardputer || printf 'SKIP: PlatformIO pio not available\n'
```

Expected: PlatformIO tests pass, or command prints `SKIP: PlatformIO pio not available`.

- [ ] **Step 6: Confirm clean worktree**

Run:

```bash
git status --short
```

Expected: no output.
