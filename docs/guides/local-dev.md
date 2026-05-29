# Local Development

Preferred local bootstrap and run flow:

```bash
./install.sh
./newbro setup
./newbro doctor
./newbro status
./newbro dev
```

`./install.sh` owns local dependency bootstrap. On reruns it skips system
prerequisite installs when a supported Python 3.12+ interpreter and `bun` are
already available, but it still refreshes the repo virtualenv and frontend
dependencies. It also creates starter `~/.newbro/.env` plus
`~/.newbro/config.yaml` files when they do not already exist. `./newbro
setup` owns interactive runtime configuration for `~/.newbro/.env` plus the
shared `~/.newbro/config.yaml`.

`./newbro doctor` is the prerequisite/config gate for local development.
`./newbro status` is read-only and broader: it reports dependency, config,
port, local endpoint reachability, frontend build, connector, and executor-node
readiness without starting services.

By default, diagnostics timeline polling requests from the frontend inspector are
filtered out of `uvicorn.access` output so local access logs are less noisy. Set
`SYNAPSE_QUIET_DIAGNOSTICS_ACCESS_LOGS=false` if you want to see those polling
requests during development.

Current test command:

```bash
.venv/bin/python -m pytest
```

Real executors now run through the detached executor node.

Typical local real-executor flow:

```bash
./newbro setup
./newbro executor setup
./newbro backend
./newbro executor run
```

`./newbro setup` configures the main control plane plus optional connector
modules in the shared `~/.newbro/.env` and `~/.newbro/config.yaml` files.
`./newbro executor setup` configures the detached executor node itself,
including local Codex or ACPX command settings plus the enabled executor
families this client machine should advertise.
The intended operator flow is:

1. create the node from the frontend `Nodes` page
2. optionally run `./newbro executor setup` on the client machine if you want
   to preconfigure local executor families and command paths
3. copy the generated connect command from the `Nodes` page
4. start the node with that command, for example:
   `newbro executor run --base-url https://newbro.example.com --node-id node-1234 --token secret`

If local executor runtime config is still missing when you run that command,
`./newbro executor run` now launches the same local setup flow automatically
when a TTY is available.

`./newbro executor run` now reports foreground lifecycle state directly in the
terminal:

- `[start]` after local config is loaded
- `[connect]` before each control-channel dial attempt
- `[ready]` only after the node registers successfully with Newbro
- `[warn]` plus `[retry]` when connection or registration fails and the node is
  retrying
- `[stop]` on manual interrupt

`./newbro dev` and `./newbro start` do not auto-start the executor node.
Run `./newbro executor run` explicitly when you want local real execution.
There is intentionally no `./newbro dev --with-executor-node`; executor-node
credentials are issued by Newbro and should stay explicit in the copied
`executor run` command.

Backend-only and frontend-only commands:

```bash
./newbro backend
./newbro frontend
```

`./newbro start` is the production-style runtime entrypoint used by the
systemd service path. It expects an existing frontend production build and runs
one main Newbro service on the public port. That service serves the built UI
from `/`, keeps the normal API and websocket routes on the same origin, and
mounts `/api/connectors/...` routes directly when connectors are enabled.

`./newbro dev` runs the same main service with reload on port `8000` plus the
separate Vite frontend on `5173`. The Vite workspace proxies both `/api/sessions`
and `/api/connectors` to the local main service while you iterate on the UI.

`./newbro connector run` remains available when you want to run the standalone
headless connector host by itself for separate deployment or direct connector
testing.

Foreground local runs stop with Ctrl+C. Newbro does not provide a generic
`./newbro stop` command because local dev runs do not own a PID/state file; use
the `service` commands for systemd-managed deployments.

Separate frontend production deployments are documented in
[`./vercel-ui-deployment.md`](./vercel-ui-deployment.md). Local
`./newbro dev` and `./newbro frontend` do not require `VITE_API_BASE_URL`
unless you intentionally want the local browser app to target a separate public
backend.

The repo-root bootstrap launcher keeps first-run setup working even before the
package is installed. After setup, the installed console script is also
available:

```bash
.venv/bin/newbro dev
```
