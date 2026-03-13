# OpenClaw "Update now" from UI (Docker deployments)

When OpenClaw runs in Docker, the built-in "Update now" button fails because it tries `npm i -g openclaw@latest`, which doesn't work in a read-only container. This doc describes how to make "Update now" work by calling a host-side update daemon.

## Architecture

1. **Update daemon** — Runs on the LAB host (systemd service). Listens on `0.0.0.0:19999` for `POST /update`.
2. **OpenClaw container** — Has `host.docker.internal` via `extra_hosts`, so it can reach the daemon at `http://host.docker.internal:19999/update`.
3. **"Update now" flow** — When clicked, the OpenClaw app calls the daemon with `Authorization: Bearer <gateway_token>`. The daemon verifies the token, then runs `docker compose pull && docker compose up -d`.

## ATP side (this repo)

### 1. Install the update daemon on LAB

On the LAB instance (via SSM or SSH):

```bash
cd /home/ubuntu/automated-trading-platform
sudo bash scripts/openclaw/install_openclaw_update_daemon.sh
```

This installs `openclaw-update-daemon.service` and starts it. The daemon reads `gateway.auth.token` from `/opt/openclaw/home-data/openclaw.json` to verify requests.

### 2. docker-compose.openclaw.yml

Already configured with:

- `extra_hosts: host.docker.internal:host-gateway`
- `OPENCLAW_UPDATE_DAEMON_URL=http://host.docker.internal:19999/update`

### 3. Verify daemon

From LAB:

```bash
curl -s http://127.0.0.1:19999/health
# {"status":"ok"}
```

From inside the OpenClaw container:

```bash
docker exec openclaw curl -s http://host.docker.internal:19999/health
# {"status":"ok"}
```

## OpenClaw repo changes (ccruz0/openclaw)

The OpenClaw app must detect Docker and call the daemon instead of `npm install`.

### Detection

- If `OPENCLAW_UPDATE_DAEMON_URL` is set (or `/.dockerenv` exists), use the daemon flow.
- Otherwise, fall back to the existing `npm i -g openclaw@latest` flow for local installs.

### Update flow (when daemon URL is set)

1. Read `gateway.auth.token` from the config (or env).
2. `POST` to `OPENCLAW_UPDATE_DAEMON_URL` with:
   - `Authorization: Bearer <token>`
   - Content-Type: application/json (body can be empty or `{}`)
3. On 200: show success, optionally reload the page.
4. On 4xx/5xx: show error.

### Example (pseudocode)

```ts
async function performUpdate(): Promise<void> {
  const daemonUrl = process.env.OPENCLAW_UPDATE_DAEMON_URL;
  const token = getGatewayToken(); // from config or env

  if (daemonUrl && token) {
    const res = await fetch(daemonUrl, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      // Success — container will restart in a few seconds
      showSuccess("Update started. The page will reload when the new version is ready.");
      setTimeout(() => window.location.reload(), 10_000);
    } else {
      const err = await res.json().catch(() => ({}));
      showError(`Update failed: ${err.error || res.status}`);
    }
  } else {
    // Fallback: npm install (local only)
    await runNpmInstall();
  }
}
```

### Where to find the update logic

Search for where the "Update now" button triggers the update (e.g. `npm i -g openclaw`, `npm install`, or version check logic). Replace or branch that path with the daemon call when `OPENCLAW_UPDATE_DAEMON_URL` is set.

**Cursor prompt:** [CURSOR_PROMPT_OPENCLAW_UPDATE_FROM_UI.md](CURSOR_PROMPT_OPENCLAW_UPDATE_FROM_UI.md) — paste into Cursor with the OpenClaw repo open.

## Security

- The daemon listens on `0.0.0.0:19999`. LAB typically has no public inbound on that port; access is from within the VPC or container.
- All requests require `Authorization: Bearer <gateway_token>`. The token is the same one used for the gateway API.
- The daemon only runs `docker compose pull` and `docker compose up -d`; no arbitrary commands.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| 401 from daemon | Token missing or wrong. Ensure `gateway.auth.token` exists in `/opt/openclaw/home-data/openclaw.json`. |
| Connection refused | Daemon not running. `sudo systemctl status openclaw-update-daemon`. |
| `host.docker.internal` not resolving | Ensure `extra_hosts` is in docker-compose and the container was recreated after the change. |
| 503 | Config file missing. Run OpenClaw once so the config is created, or run `ensure_openclaw_gateway_token.sh`. |
