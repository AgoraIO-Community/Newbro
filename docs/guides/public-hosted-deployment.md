# Public Hosted Deployment

Newbro's first public-user deployment path is a Docker Compose stack on a
long-running Ubuntu VPS with Cloudflare in front of it.

Cloudflare is the public edge for this path. It owns DNS, HTTPS, proxying, and
optionally Cloudflare Tunnel. Cloudflare is not the Newbro runtime host.

## Runtime Shape

The VPS runs Caddy plus Newbro through Docker Compose:

```text
public :80/:443
  -> caddy container
  -> newbro container
  -> newbro start --host 0.0.0.0 --port 8000
```

The public origin should expose:

```text
https://newbro.example.com/
https://newbro.example.com/api/*
https://newbro.example.com/api/connectors/*
wss://newbro.example.com/api/sessions/{session_id}/stream
wss://newbro.example.com/api/executors/control
```

The same-origin shape is intentional. It keeps browser session APIs, voice
connector routes, and websocket upgrades on one public origin.

Caddy terminates HTTPS and reverse-proxies to the Newbro container on the
private Compose network. The deployment workflow derives the Caddy hostname
from `NEWBRO_PUBLIC_BASE_URL`.

## Operator Setup

The VPS owns runtime config and secrets, mounted into the container:

```text
~/.newbro/.env
~/.newbro/config.yaml
```

Configure at least:

- `OPENAI_API_KEY`
- Agora App ID and App Certificate in connector config
- `connector_host.public_base_url` set to the Cloudflare HTTPS origin
- enabled `agora-convoai` connector routes when voice is used
- `SYNAPSE_CONNECTOR_INTERNAL_TOKEN` when a connector process calls back into
  protected Newbro session APIs
- `SYNAPSE_PUBLIC_COOKIE_SECURE=true` when serving over HTTPS

Users do not provide OpenAI or Agora keys for the first public path.

Install Docker on the VPS, or let the deployment workflow install the default
Ubuntu Docker packages:

```bash
apt-get update
apt-get install -y docker.io docker-compose-v2
systemctl enable --now docker
```

Create invite codes through the running container:

```bash
cd /opt/newbro
docker compose exec newbro newbro invite create
docker compose exec newbro newbro invite create friend-code --email user@example.com
```

The command prints the invite code. The public auth database lives under
`~/.newbro/public_auth.sqlite3` by default.

## User Setup

Invited users only need:

1. a browser
2. an invite code
3. microphone permission

After invite redemption, Newbro bootstraps a user-owned session and default Bro,
then opens Bro Detail directly.

Real Codex execution still requires the user's detached local executor node.
When a sent draft is waiting for execution, Bro Detail shows a copyable local
node command. The hosted app issues a user-owned node id and token, and the
user runs:

```bash
python3 -m pip install --user --upgrade newbro-cli
newbro executor run --base-url https://newbro.example.com --node-id node-1234 --token secret
```

## GitHub Actions Deployment

The production workflow deploys with Docker and SSH:

```text
GitHub Actions
  -> run tests
  -> build Docker image, including the frontend
  -> push image to GHCR
  -> SSH to VPS
  -> write docker-compose.yml
  -> docker compose pull
  -> docker compose up -d
  -> verify https://newbro.example.com/api/health
```

Required GitHub secrets:

- `NEWBRO_DEPLOY_HOST`
- `NEWBRO_DEPLOY_USER`
- `NEWBRO_DEPLOY_PATH`
- `NEWBRO_DEPLOY_SSH_KEY`
- `NEWBRO_PUBLIC_BASE_URL`
- optional `NEWBRO_DEPLOY_PORT`

Do not put OpenAI or Agora secrets into GitHub Actions build variables. They
belong in the VPS runtime config.

The workflow publishes images to:

```text
ghcr.io/agoraio-community/newbro
```

The generated Compose file mounts `/root/.newbro` into the container. If the
deployment later moves away from the `root` SSH user, update the Compose mount
and runtime config path together.

The generated Compose file also includes a `caddy:2-alpine` service with named
volumes for Caddy data and config, so certificates survive container updates.
Open or allow inbound `80/tcp` and `443/tcp` on the VPS when using this path.

Manual workflow runs can also create an invite after a successful deploy. In
the GitHub Actions UI, run `Deploy Newbro VPS` with:

- `create_invite`: enabled
- `invite_code`: optional; leave blank to generate one
- `invite_email`: optional email label

The invite command output is written to the workflow log and step summary, so
use this only from a trusted private repo or with the expected operator access.

## Health Checks

After deployment:

```bash
curl -i https://newbro.example.com/api/health
curl -i https://newbro.example.com/api/connectors/agora-convoai/health
```

Then verify from a browser:

- invite redemption works
- bootstrap opens Bro Detail directly
- voice starts from Bro Detail
- session websocket connects
- a local executor node can connect through `/api/executors/control`

For container state and logs:

```bash
cd /opt/newbro
docker compose ps
docker compose logs --tail=200 newbro
docker compose logs --tail=200 caddy
```

## Non-Default Paths

Cloudflare Pages can still be used for static previews, but it is not the
default public deployment.

Cloudflare Workers-native deployment is future work. It requires a separate
state and websocket ownership design before Newbro can move off a long-running
Python service.
