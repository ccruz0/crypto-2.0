# Fix OpenClaw gateway binding (127.0.0.1 → 0.0.0.0)

**Apply this in the repo `ccruz0/openclaw`** (the one that builds `ghcr.io/ccruz0/openclaw:latest`).

**Applied fix (Dockerfile):** The image CMD was updated to `gateway --bind lan --allow-unconfigured` so the gateway listens on `0.0.0.0:18789` inside the container. Rebuild and push the image, then redeploy on LAB.

## Problem

The gateway logs: `[gateway] listening on ws://127.0.0.1:18789, ws://[::1]:18789`. It only binds to localhost, so when Docker publishes `-p 8081:18789`, connections from the host (or from Nginx on PROD) never reach the process → "Empty reply from server", curl returns `000`, and Nginx returns 504.

## Fix

Make the gateway **bind to `0.0.0.0`** (and optionally `::` for IPv6) when running in Docker, so it accepts connections from any interface inside the container.

### 1. Find where the server binds

In the openclaw repo, search for the listen address and port 18789:

```bash
grep -Rn "127.0.0.1\|18789\|localhost.*listen\|listen.*18789" --include="*.ts" --include="*.js" .
```

Look for:
- `createServer`, `listen(18789)`, `listen(port)` with a host
- Config or env that sets the bind host (e.g. `HOST`, `BIND_ADDRESS`, `host: '127.0.0.1'`)

### 2. Use 0.0.0.0 in container

**Option A – env var (recommended)**  
- Add an env var, e.g. `OPENCLAW_GATEWAY_HOST` or `HOST`, defaulting to `0.0.0.0` in Docker and `127.0.0.1` for local dev.
- In `Dockerfile` or entrypoint: `ENV OPENCLAW_GATEWAY_HOST=0.0.0.0` (or equivalent).
- In code: use `process.env.OPENCLAW_GATEWAY_HOST || '127.0.0.1'` (or your env name) as the host when calling `listen()`.

**Option B – always 0.0.0.0 in Docker**  
- If the app only runs in Docker for this image, set the listen host to `0.0.0.0` in code where the server is started.

Example (Node/TypeScript):

```ts
const host = process.env.OPENCLAW_GATEWAY_HOST ?? '127.0.0.1';
server.listen(18789, host, () => { ... });
```

### 3. Rebuild and redeploy

```bash
# Build and push (e.g. from openclaw repo)
docker build -t ghcr.io/ccruz0/openclaw:latest .
docker push ghcr.io/ccruz0/openclaw:latest
```

On LAB (via SSM):

```bash
sudo docker pull ghcr.io/ccruz0/openclaw:latest
sudo docker stop openclaw; sudo docker rm openclaw
sudo docker run -d --restart unless-stopped -p 8081:18789 --name openclaw ghcr.io/ccruz0/openclaw:latest
sudo docker logs openclaw --tail 20
```

### 4. Verify

Logs should show something like `listening on ws://0.0.0.0:18789` (not only `127.0.0.1`). Then from LAB:

```bash
curl -s -m 3 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/
```

You should get `200` or `301`/`302`, not `000`. After that, https://dashboard.hilovivo.com/openclaw/ should load without 504.
