# Vercel UI Deployment

Use this path when `clients/web/` is deployed on Vercel and the main Newbro
backend stays on a separate HTTPS origin on your own server.

## Required Runtime Contract

The deployed UI expects one public backend base URL that serves both:

- HTTPS requests for:
  - `POST /api/sessions`
  - `GET /api/sessions/{session_id}`
  - `GET /api/sessions/{session_id}/conversation`
  - `GET /api/sessions/{session_id}/diagnostics/timeline`
- secure websocket upgrades for:
  - `WS /api/sessions/{session_id}/stream`

Point `VITE_API_BASE_URL` at that public backend origin itself. Do not point it
at `/api/sessions`, `/api/connectors`, or the connector host on port `8010`.

If the deployed UI also enables the compact Agora voice accessory in the main
workbench, set a second frontend env var:

```env
VITE_CONNECTOR_BASE_URL=https://connectors.example.com
```

That value is used only for browser calls to:

- `GET /api/connectors/agora-convoai/config`
- `POST /api/connectors/agora-convoai/sessions/prepare`
- `POST /api/connectors/agora-convoai/sessions/activate`
- `POST /api/connectors/agora-convoai/sessions/stop`

The main shell's `Voice` mode now attaches to the already-active shell
`synapse_session_id`, so deployed environments must ensure the public
main-backend origin and the public connector origin are both reachable from the
browser while voice mode is started, stopped, and used live.

If your main Newbro service already mounts `/api/connectors/...` routes directly, you
may set `VITE_CONNECTOR_BASE_URL` to the same public origin as
`VITE_API_BASE_URL`.

## Backend Configuration

The backend must allow the deployed frontend origin through
`SYNAPSE_CORS_ALLOWED_ORIGINS`:

```env
SYNAPSE_CORS_ALLOWED_ORIGINS=https://app.example.com
```

If you also use Vercel preview deployments, include those exact preview origins
as additional comma-separated values.

The main Newbro API should remain the upstream for browser session traffic.
The connector host is a separate vendor-facing process and is not the frontend's
session API origin.

The connector host must separately allow the deployed frontend origin for browser
voice-mode requests. In the shared connector host config:

```yaml
connector_host:
  cors_allowed_origins:
    - https://app.example.com
```

## Vercel Configuration

Set the Vercel frontend env var:

```env
VITE_API_BASE_URL=https://api.example.com
VITE_CONNECTOR_BASE_URL=https://connectors.example.com
```

That value is consumed by `clients/web/src/lib/session-client.ts` and is
used for both HTTPS requests and websocket URL derivation.
`VITE_CONNECTOR_BASE_URL` is consumed by
`clients/web/src/lib/connector-client.ts` for voice connector calls only.

The frontend workspace now vendors the `agora-rtm` package locally under
`clients/web/vendor/agora-rtm/` because the published `agora-rtm` npm
package still declares an incompatible peer on `agora-rtc-sdk-ng@4.23.0` while
the Agora voice toolkit requires `agora-rtc-sdk-ng>=4.23.4`. Keep Vercel on the
default `npm install` path; do not add `--legacy-peer-deps` for this project.

The workspace also declares `@rolldown/binding-linux-x64-gnu` directly in root
`optionalDependencies`. Vite 8 pulls Rolldown transitively, but some npm/Vercel
installs can omit the nested Linux native binding and then fail during
`npm run build` with `Cannot find native binding`. Keep the binding pinned at
the root so plain `npm install` on Linux runners remains sufficient.

For this repo's GitHub Actions production deploy path, the workflow currently
injects both `VITE_API_BASE_URL=https://newbro.plutoless.com` and
`VITE_CONNECTOR_BASE_URL=https://newbro.plutoless.com` directly during the
production build. Keep the Vercel project env aligned with those same values
if you also use manual Vercel CLI or dashboard-triggered deploys outside
GitHub Actions.

## Reverse Proxy Shape

If your public backend origin is served through Nginx, proxy the session routes
to the main Newbro API on `127.0.0.1:8000`.

If you choose not to expose a separate `VITE_CONNECTOR_BASE_URL`, the same public
origin must still expose `/api/connectors/agora-convoai/*`, either directly from the
main Newbro service or by forwarding those routes to a standalone connector host.

Typical requirements:

- preserve the original `Host`
- forward `X-Forwarded-For` and `X-Forwarded-Proto`
- do not rewrite the `/api/sessions` path prefix
- keep websocket upgrade handling on `/api/sessions/{session_id}/stream`

Example shape:

```nginx
location ~ ^/api/sessions/[^/]+/stream$ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /api/sessions {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /api/sessions/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Verification

After deployment:

- verify `POST https://your-backend-origin/api/sessions`
- verify the deployed Vercel UI can load a session and conversation snapshot
- verify the websocket stream opens over `wss://.../api/sessions/{session_id}/stream`
- verify `GET https://your-connector-origin/api/connectors/agora-convoai/config` when
  `VITE_CONNECTOR_BASE_URL` is set
- verify the main UI can start and stop the voice accessory without CORS or
  mixed-origin failures
- verify browser devtools show no CORS failures and no failed websocket
  handshake
