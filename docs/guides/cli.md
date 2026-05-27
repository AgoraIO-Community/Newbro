# CLI, Setup, And Publishing

This guide contains the command details that are intentionally kept out of the
root README.

Newbro requires Python 3.12 or newer. The active Python package namespace is
`newbro`. Some environment variables and wire/config fields still intentionally
use legacy `SYNAPSE_*` or `synapse_*` names for compatibility.

## Repo Setup

For a fresh clone:

```bash
./install.sh
./newbro setup
./newbro doctor
./newbro dev
```

`./install.sh` installs supported local development dependencies, creates
`.venv`, installs the project in editable mode, installs frontend dependencies,
and writes starter `~/.newbro/.env` plus `~/.newbro/config.yaml` files when they
do not already exist.

`./newbro setup` fills in `~/.newbro/.env` plus the shared
`~/.newbro/config.yaml` runtime config. By default it prompts for required
runtime values such as `OPENAI_API_KEY`.

For automation:

```bash
OPENAI_API_KEY=... ./newbro setup --non-interactive
```

For connector-only reconfiguration:

```bash
./newbro connector setup
```

If you already have legacy Synapse-era config under `~/.synapse` and
`~/.newbro` does not exist yet, the CLI migrates that home directory to
`~/.newbro` on the first run.

After setup, the installed console script is available as `.venv/bin/newbro`.
You can also activate the virtual environment and run `newbro dev` directly.

## Install From PyPI

Install the public package with:

```bash
python3 -m pip install newbro-cli
newbro --help
newbro executor setup
newbro executor run --base-url https://newbro.example.com --node-id node-1234 --token secret
```

The published package name is `newbro-cli`, the installed console script is
`newbro`, and the Python module namespace is `newbro`.

`~/.newbro/.env` is auto-loaded by the backend at startup. You do not need to
export variables manually. OpenAI is required for normal development and demo
runtime, so set `OPENAI_API_KEY` in `~/.newbro/.env` before starting the app.

## Detached Executor Nodes

Detached executor nodes connect back to the Newbro service with credentials
issued by the Nodes page or the executor-node API.

```bash
newbro executor run \
  --base-url https://newbro.example.com \
  --node-id node-1234 \
  --token secret
```

The run command also accepts per-run executor overrides:

```bash
newbro executor run \
  --base-url https://newbro.example.com \
  --node-id node-1234 \
  --token secret \
  --enabled-executor acpx \
  --acpx-agent openclaw
```

Repeat `--enabled-executor` to enable multiple executor families for one run.

Composer push-to-talk audio uses local Whisper inside the executor node. The
`newbro-cli` package includes the required Whisper runtime dependencies. By
default the node auto-detects language and uses the configured/default model;
foreground runs can override both inline:

```bash
newbro executor run \
  --base-url https://newbro.example.com \
  --node-id node-1234 \
  --token secret \
  --audio-language zh \
  --whisper-model small
```

## Optional ACPX Executor

If you want Newbro to delegate execution through `acpx` instead of the direct
Codex executor, install ACPX first:

```bash
npm install -g acpx@latest
```

Quick verification:

```bash
acpx --version
codex --version
```

The recommended path is to enable ACPX through `./newbro executor setup`, the
Nodes page, or `newbro executor run --enabled-executor acpx`. For legacy env
configuration, add this to `~/.newbro/.env`:

```env
SYNAPSE_ACPX_EXECUTOR_ENABLED=true
```

Optional overrides:

```env
# SYNAPSE_ACPX_COMMAND=acpx
# SYNAPSE_ACPX_AGENT=codex
# SYNAPSE_ACPX_PERMISSION_MODE=approve-all
# SYNAPSE_ACPX_NON_INTERACTIVE_PERMISSIONS=deny
# SYNAPSE_ACPX_TIMEOUT_SECONDS=300
```

When using detached executor-node credentials, the enabled executor families
come from the node record unless overridden with `--enabled-executor`.

## Common Commands

```bash
./install.sh
./newbro setup
./newbro connector setup
./newbro doctor
./newbro dev
./newbro backend
./newbro frontend
./newbro start
./newbro connector run
./newbro executor setup
./newbro executor run --base-url https://newbro.example.com --node-id node-1234 --token secret
./newbro service install
./newbro service start
./newbro service stop
./newbro service restart
```

If the frontend shows `error` and messages do not progress, first confirm the
backend is running from the same virtual environment where dependencies were
installed.

To run only the frontend:

```bash
./newbro frontend
```

To run only the headless connector host:

```bash
./newbro connector run
```

## Test And Build

```bash
.venv/bin/python -m pytest
```

Frontend build check:

```bash
cd src/newbro/ui
npm run build
```

## Release Build And Publish

```bash
python3 -m pip install '.[release]'
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*
```

Automatic publish from GitHub Actions:

```bash
git tag v0.1.2
git push origin v0.1.2
```

The `publish-pypi` workflow runs on tags matching `v*` and derives the package
version from the tag by stripping the leading `v`. For example, tag `v0.1.2`
publishes package version `0.1.2` even if the checked-in `pyproject.toml`
version has not been bumped yet.

This workflow uses PyPI Trusted Publishing, so configure the `newbro-cli` PyPI
project to trust the `AgoraIO-Community/Newbro` GitHub repository and the
`publish-pypi.yml` workflow before creating the first release tag.

For manual publishing or recovery, use the helper script. Pass `--version` when
you want the build/upload version to follow a release tag instead of the
checked-in `pyproject.toml` version:

```bash
PYPI_TOKEN='pypi-...' ./scripts/publish_pypi.sh --version 0.1.2
PYPI_TOKEN='pypi-...' ./scripts/publish_pypi.sh --version v0.1.2 --testpypi
./scripts/publish_pypi.sh --version 0.1.2 --dry-run
```
