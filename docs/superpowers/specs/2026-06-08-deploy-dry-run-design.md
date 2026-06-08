# Deploy Dry-Run Design

## Context

Merging to `main` currently triggers `.github/workflows/deploy-vps.yml`, which
builds the production Docker image, pushes it to GHCR, deploys it to the VPS
through Docker Compose, and verifies the public `/api/health` endpoint. Normal
feature commits and pull requests do not currently prove that the deployable
Docker artifact can boot before the production deployment runs.

The dry-run should provide pre-merge confidence without becoming another
deployment path.

## Decision

Add a separate GitHub Actions workflow,
`.github/workflows/deploy-dry-run.yml`, that builds and boots the production
Docker image locally on the Actions runner.

The workflow will not push to GHCR, SSH to the VPS, modify Docker Compose on the
server, or require production deployment secrets.

## Workflow Shape

The dry-run workflow triggers on:

- `pull_request` for deploy-relevant paths
- `push` to non-`main` branches for deploy-relevant paths
- `workflow_dispatch`

Deploy-relevant paths should match the production deployment surface:

- `.github/workflows/deploy-dry-run.yml`
- `.github/workflows/deploy-vps.yml`
- `Dockerfile`
- `README.md`
- `clients/web/**`
- `src/**`
- `tests/**`
- `docs/**`
- `pyproject.toml`
- `install.sh`
- `newbro`
- `package*.json`

`main` remains owned by the existing production deployment workflow.

## Runtime Flow

The job runs on `ubuntu-latest` and:

1. Checks out the repository.
2. Builds the Docker image from the existing `Dockerfile`.
3. Starts the image locally, publishing container port `8000` to a loopback-only
   host port such as `127.0.0.1:18000`.
4. Polls `http://127.0.0.1:18000/api/health` until the app is healthy or a
   bounded timeout expires.
5. Requests `http://127.0.0.1:18000/` and verifies the frontend HTML is served.
6. Prints container status and logs on failure.
7. Removes the test container in a cleanup step.

The polling URL is local to the GitHub Actions runner. It does not depend on the
VPS or public DNS.

## Runtime Inputs

The container should use only CI-safe, non-secret runtime values. If startup
requires files under `/root/.newbro`, the workflow should create minimal
temporary files on the runner and mount them into the container in the same
shape as production:

```text
/root/.newbro/.env
/root/.newbro/config.yaml
```

These files must not contain OpenAI, Agora, deploy, or invite-code secrets. If a
future app change makes boot depend on production secrets, the dry-run should
fail clearly so the startup contract can be fixed rather than hidden with
fallback behavior.

## Verification Scope

The dry-run proves:

- the production Docker image builds
- the frontend bundle is included in the image
- `newbro start --host 0.0.0.0 --port 8000` boots inside the container
- `/api/health` is reachable from the runner
- `/` serves the packaged UI

The dry-run does not prove:

- the VPS can pull the image
- SSH deployment credentials are valid
- Caddy configuration or public DNS works
- production runtime secrets are valid
- the public URL is reachable after deployment

Those checks remain owned by the production deploy workflow on `main`.

## Error Handling

On failure, the workflow should print enough information to identify the failing
stage:

- Docker image build output is already visible in the failed build step.
- Startup or health failures should print `docker ps` / `docker inspect` style
  status and container logs.
- Cleanup should run even after failure.

The workflow should use bounded retries for health polling instead of sleeping
for a fixed long period.

## Testing Strategy

The workflow is the primary test for this feature. It should remain focused on
deploy-artifact boot confidence.

Backend unit tests stay in the production deployment workflow for now. They can
be added to the dry-run later if the project wants a single all-in CI signal,
but that is not required for the first version.

## Out Of Scope

- VPS preflight checks.
- Staging Compose deployment.
- GHCR push or image signing.
- Production deployment notifications.
- Changing the production deployment workflow beyond any shared path or naming
  alignment needed for clarity.
