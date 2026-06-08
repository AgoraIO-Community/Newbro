# Deploy Dry-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions dry-run that builds the production Docker image, boots it locally on the Actions runner, and verifies `/api/health` plus the served UI before merge.

**Architecture:** Keep the dry-run as a separate workflow from production deployment. The workflow uses the existing `Dockerfile` as the source of truth, runs the built image on loopback only, and reports container logs on failure without touching GHCR or the VPS.

**Tech Stack:** GitHub Actions, Docker, Bash, curl, existing Newbro Dockerfile and FastAPI health route.

---

## File Structure

- Create `.github/workflows/deploy-dry-run.yml`: owns the pre-merge deploy-artifact smoke test.
- Reference `docs/superpowers/specs/2026-06-08-deploy-dry-run-design.md`: approved design source.
- Do not modify `.github/workflows/deploy-vps.yml`: production deployment remains unchanged.
- Do not modify application code: this feature validates the existing deployable artifact.

## Task 1: Create The Dry-Run Workflow

**Files:**
- Create: `.github/workflows/deploy-dry-run.yml`
- Reference: `Dockerfile`
- Reference: `docs/superpowers/specs/2026-06-08-deploy-dry-run-design.md`

- [ ] **Step 1: Verify the workflow does not already exist**

Run:

```bash
test -f .github/workflows/deploy-dry-run.yml
```

Expected: command exits non-zero because the workflow has not been created yet.

- [ ] **Step 2: Add the workflow file**

Create `.github/workflows/deploy-dry-run.yml` with this exact content:

```yaml
name: Deploy Dry Run

on:
  workflow_dispatch:
  pull_request:
    paths:
      - ".github/workflows/deploy-dry-run.yml"
      - ".github/workflows/deploy-vps.yml"
      - "Dockerfile"
      - "README.md"
      - "clients/web/**"
      - "src/**"
      - "tests/**"
      - "docs/**"
      - "pyproject.toml"
      - "install.sh"
      - "newbro"
      - "package*.json"
  push:
    branches-ignore:
      - main
    paths:
      - ".github/workflows/deploy-dry-run.yml"
      - ".github/workflows/deploy-vps.yml"
      - "Dockerfile"
      - "README.md"
      - "clients/web/**"
      - "src/**"
      - "tests/**"
      - "docs/**"
      - "pyproject.toml"
      - "install.sh"
      - "newbro"
      - "package*.json"

permissions:
  contents: read

concurrency:
  group: deploy-dry-run-${{ github.ref }}
  cancel-in-progress: true

jobs:
  docker-smoke:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      IMAGE_NAME: newbro-dry-run:${{ github.sha }}
      CONTAINER_NAME: newbro-dry-run-${{ github.run_id }}-${{ github.run_attempt }}
      HOST_PORT: "18000"
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Prepare CI runtime home
        run: |
          set -euxo pipefail
          mkdir -p "$RUNNER_TEMP/newbro-home"
          cat > "$RUNNER_TEMP/newbro-home/.env" <<'EOF'
          SYNAPSE_COMMUNICATION_BACKEND=scripted
          SYNAPSE_CODEX_EXECUTOR_ENABLED=false
          SYNAPSE_ACPX_EXECUTOR_ENABLED=false
          SYNAPSE_PUBLIC_COOKIE_SECURE=false
          SYNAPSE_LOG_FORMAT=plain
          NEWBRO_SIGNUP_INVITE_CODE=dry-run
          EOF
          cat > "$RUNNER_TEMP/newbro-home/config.yaml" <<'EOF'
          version: 1
          connector_host:
            enabled: false
            public_base_url: http://127.0.0.1:8000
            synapse_base_url: http://127.0.0.1:8000
            cors_allowed_origins: []
            enabled_connectors: []
          connectors: {}
          EOF

      - name: Build Docker image
        run: docker build -t "$IMAGE_NAME" .

      - name: Start container
        run: |
          set -euxo pipefail
          docker run \
            --detach \
            --name "$CONTAINER_NAME" \
            --publish "127.0.0.1:${HOST_PORT}:8000" \
            --volume "$RUNNER_TEMP/newbro-home:/root/.newbro" \
            "$IMAGE_NAME"

      - name: Verify API health
        run: |
          set -euo pipefail
          for attempt in $(seq 1 30); do
            if curl --noproxy "*" --fail --show-error --silent "http://127.0.0.1:${HOST_PORT}/api/health"; then
              exit 0
            fi
            echo "health check attempt ${attempt} failed"
            sleep 2
          done
          echo "container did not become healthy" >&2
          exit 1

      - name: Verify served UI
        run: |
          set -euo pipefail
          curl --noproxy "*" --fail --show-error --silent "http://127.0.0.1:${HOST_PORT}/" > "$RUNNER_TEMP/newbro-root.html"
          grep -qi "<html" "$RUNNER_TEMP/newbro-root.html"

      - name: Show container diagnostics on failure
        if: failure()
        run: |
          docker ps -a
          docker inspect "$CONTAINER_NAME" || true
          docker logs "$CONTAINER_NAME" || true

      - name: Cleanup container
        if: always()
        run: |
          docker rm -f "$CONTAINER_NAME" || true
```

- [ ] **Step 3: Confirm the file exists**

Run:

```bash
test -f .github/workflows/deploy-dry-run.yml
```

Expected: command exits zero.

## Task 2: Validate Workflow Shape Locally

**Files:**
- Modify: `.github/workflows/deploy-dry-run.yml`

- [ ] **Step 1: Run a static workflow content check**

Run:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

path = Path(".github/workflows/deploy-dry-run.yml")
text = path.read_text()
required = [
    "name: Deploy Dry Run",
    "pull_request:",
    "branches-ignore:",
    "- main",
    "\"README.md\"",
    "docker build -t \"$IMAGE_NAME\" .",
    "--publish \"127.0.0.1:${HOST_PORT}:8000\"",
    "curl --noproxy \"*\" --fail --show-error --silent \"http://127.0.0.1:${HOST_PORT}/api/health\"",
    "curl --noproxy \"*\" --fail --show-error --silent \"http://127.0.0.1:${HOST_PORT}/\"",
    "docker logs \"$CONTAINER_NAME\" || true",
    "docker rm -f \"$CONTAINER_NAME\" || true",
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"missing expected workflow content: {missing}")
for forbidden in [
    "docker push",
    "ssh ",
    "NEWBRO_DEPLOY_SSH_KEY",
    "NEWBRO_DEPLOY_HOST",
    "GHCR_TOKEN",
]:
    if forbidden in text:
        raise SystemExit(f"forbidden dry-run content found: {forbidden}")
PY
```

Expected: command exits zero.

- [ ] **Step 2: Run a YAML syntax check**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/deploy-dry-run.yml"); puts "yaml-ok"'
```

Expected: prints `yaml-ok`.

- [ ] **Step 3: Commit the workflow**

Run:

```bash
git add .github/workflows/deploy-dry-run.yml
git commit -m "ci: add deploy dry-run workflow"
```

Expected: commit succeeds and includes only `.github/workflows/deploy-dry-run.yml`.

## Task 3: Exercise The Docker Smoke Test Locally

**Files:**
- Reference: `.github/workflows/deploy-dry-run.yml`
- Reference: `Dockerfile`

- [ ] **Step 1: Check Docker is available**

Run:

```bash
docker version
```

Expected: Docker client and server versions print. If the daemon is not running, start Docker Desktop or the local Docker service before continuing.

- [ ] **Step 2: Build the image with the same command shape as CI**

Run:

```bash
docker build -t newbro-dry-run:local .
```

Expected: image build completes successfully.

- [ ] **Step 3: Prepare local non-secret runtime config**

Run:

```bash
mkdir -p /tmp/newbro-dry-run-home
cat > /tmp/newbro-dry-run-home/.env <<'EOF'
SYNAPSE_COMMUNICATION_BACKEND=scripted
SYNAPSE_CODEX_EXECUTOR_ENABLED=false
SYNAPSE_ACPX_EXECUTOR_ENABLED=false
SYNAPSE_PUBLIC_COOKIE_SECURE=false
SYNAPSE_LOG_FORMAT=plain
NEWBRO_SIGNUP_INVITE_CODE=dry-run
EOF
cat > /tmp/newbro-dry-run-home/config.yaml <<'EOF'
version: 1
connector_host:
  enabled: false
  public_base_url: http://127.0.0.1:8000
  synapse_base_url: http://127.0.0.1:8000
  cors_allowed_origins: []
  enabled_connectors: []
connectors: {}
EOF
```

Expected: `/tmp/newbro-dry-run-home/.env` and `/tmp/newbro-dry-run-home/config.yaml` exist.

- [ ] **Step 4: Run the container on loopback**

Run:

```bash
docker rm -f newbro-dry-run-local 2>/dev/null || true
docker run --detach --name newbro-dry-run-local --publish 127.0.0.1:18000:8000 --volume /tmp/newbro-dry-run-home:/root/.newbro newbro-dry-run:local
```

Expected: command prints a container id.

- [ ] **Step 5: Verify API health**

Run:

```bash
for attempt in $(seq 1 30); do
  if curl --noproxy "*" --fail --show-error --silent http://127.0.0.1:18000/api/health; then
    exit 0
  fi
  echo "health check attempt ${attempt} failed"
  sleep 2
done
echo "container did not become healthy" >&2
exit 1
```

Expected: command exits zero after printing the health response.

- [ ] **Step 6: Verify the served UI**

Run:

```bash
curl --noproxy "*" --fail --show-error --silent http://127.0.0.1:18000/ > /tmp/newbro-dry-run-root.html
grep -qi "<html" /tmp/newbro-dry-run-root.html
```

Expected: both commands exit zero.

- [ ] **Step 7: Clean up the local container**

Run:

```bash
docker rm -f newbro-dry-run-local
```

Expected: prints `newbro-dry-run-local`.

## Task 4: Final Verification

**Files:**
- Reference: `.github/workflows/deploy-dry-run.yml`
- Reference: `docs/superpowers/specs/2026-06-08-deploy-dry-run-design.md`

- [ ] **Step 1: Verify the working tree only contains intended changes from this implementation**

Run:

```bash
git status --short
```

Expected: no unstaged changes to `.github/workflows/deploy-dry-run.yml` after the implementation commit. Pre-existing unrelated untracked paths may still be visible and must not be modified.

- [ ] **Step 2: Compare implementation against the approved design**

Run:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

workflow = Path(".github/workflows/deploy-dry-run.yml").read_text()
checks = {
    "separate workflow": "name: Deploy Dry Run" in workflow,
    "pull request trigger": "pull_request:" in workflow,
    "non-main push trigger": "branches-ignore:" in workflow and "- main" in workflow,
    "manual trigger": "workflow_dispatch:" in workflow,
    "readme path filter": "\"README.md\"" in workflow,
    "docker build": "docker build -t \"$IMAGE_NAME\" ." in workflow,
    "loopback container port": "--publish \"127.0.0.1:${HOST_PORT}:8000\"" in workflow,
    "api health check": "/api/health" in workflow,
    "ui root check": "newbro-root.html" in workflow and "grep -qi \"<html\"" in workflow,
    "loopback curl proxy bypass": "curl --noproxy \"*\" --fail --show-error --silent" in workflow,
    "failure diagnostics": "docker inspect \"$CONTAINER_NAME\" || true" in workflow and "docker logs \"$CONTAINER_NAME\" || true" in workflow,
    "cleanup": "docker rm -f \"$CONTAINER_NAME\" || true" in workflow,
    "no ghcr push": "docker push" not in workflow and "GHCR_TOKEN" not in workflow,
    "no vps ssh": "ssh " not in workflow and "NEWBRO_DEPLOY_HOST" not in workflow,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f"design checks failed: {failed}")
PY
```

Expected: command exits zero.

- [ ] **Step 3: Review recent commits**

Run:

```bash
git log --oneline -n 8
```

Expected: recent history includes `ci: bypass proxies in deploy dry run checks`, `docs: use project python for dry-run checks`, `ci: include README in deploy dry run paths`, `ci: add deploy dry-run workflow`, `docs: plan deploy dry-run workflow`, and `docs: design deploy dry-run workflow`.
