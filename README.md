<p align="center">
  <img src="src/newbro/ui/public/newbro.webp" alt="Newbro logo" width="120" />
</p>

# Newbro

Newbro is a prototype runtime for AI agents that need to keep talking while
long-running work happens in the background. It is not a single chat loop where
the same model both replies to the user and drives execution. Instead, Newbro
splits the system into a user-facing communication layer, an execution
orchestration layer, and a shared blackboard that records the durable state
between them.

The goal is to make an agent feel less like a blocking command runner and more
like a teammate: it can acknowledge a request, ask clarifying questions, create
or update tasks, hand work to executors such as Codex or ACPX, stream progress
back through the UI, and later resume the conversation with the current state in
view.

This repo contains the backend control plane, protocol models, CLI, executor
node runtime, connector host, and React/Vite UI for that experiment.

Repository: `https://github.com/AgoraIO-Community/Newbro`

## Quick Start

Use this path when you want to run Newbro locally from a fresh repo checkout.

```bash
./install.sh
./newbro setup
./newbro doctor
./newbro status
./newbro dev
```

Then open:

```text
http://127.0.0.1:5173
```

What each command does:

- `./install.sh` creates `.venv`, installs Python and frontend dependencies, and
  creates starter config files under `~/.newbro/`.
- `./newbro setup` asks for required runtime values such as `OPENAI_API_KEY`.
- `./newbro doctor` checks local prerequisites.
- `./newbro status` prints a read-only operational view of config,
  dependencies, ports, local endpoint reachability, connector readiness, and
  executor-node readiness.
- `./newbro dev` starts the backend on `8000` and the frontend on `5173`.

For public hosted deployment, use the Docker-based GitHub Actions path:

```text
GitHub Actions -> GHCR image -> Docker Compose on VPS -> Cloudflare edge
```

See [Public Hosted Deployment](./docs/guides/public-hosted-deployment.md) for
the production path. The older
[Ubuntu systemd deployment](./docs/guides/ubuntu-systemd.md) guide remains for
repo-checkout hosts.

## Docs

- [CLI, setup, executors, and package publishing](./docs/guides/cli.md)
- [Local development details](./docs/guides/local-dev.md)
- [Architecture overview](./ARCHITECTURE.md)
- [Docs index](./docs/README.md)
- [Vercel UI deployment](./docs/guides/vercel-ui-deployment.md)
- [Public hosted deployment](./docs/guides/public-hosted-deployment.md)
- [Ubuntu systemd deployment](./docs/guides/ubuntu-systemd.md)

## Test

```bash
.venv/bin/python -m pytest
```

Frontend build check:

```bash
cd src/newbro/ui
npm run build
```
