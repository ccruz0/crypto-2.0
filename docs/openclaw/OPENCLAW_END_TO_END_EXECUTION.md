# OpenClaw end-to-end execution path

Tight order of operations so OpenClaw works at https://dashboard.hilovivo.com/openclaw/ (no placeholder, WebSocket OK).

---

## 1) Deploy the real OpenClaw image to LAB

**On the LAB instance** (e.g. via SSM: `aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1`):

```bash
cd /home/ubuntu/crypto-2.0   # or your deploy repo path
docker compose -f docker-compose.openclaw.yml pull openclaw
docker compose -f docker-compose.openclaw.yml up -d openclaw
docker ps | grep openclaw
curl -I http://localhost:8080/
```

**Expected:**

- Container runs; `curl` returns **200**.
- In the browser, you do **not** see "Placeholder" anymore.

If you still see "Placeholder", you are still using the placeholder image tag. Set `OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest` (or your real image) in `.env.lab`, then pull and up again. See [DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md](../runbooks/DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md).

---

## 2) Fix WebSocket in the OpenClaw frontend repo and rebuild the image

**In the OpenClaw frontend repo** (the one that builds `ghcr.io/ccruz0/openclaw`):

- Remove any hardcoded `ws://localhost:8081`.
- **Rule:** If env var exists, use it; else compute from `window.location` and use path `/openclaw/ws`.
- **Prod:** `wss://dashboard.hilovivo.com/openclaw/ws` (or same-origin so it works behind the proxy).
- **Local dev:** Optional override via env, e.g. `ws://localhost:8081/ws` or `ws://localhost:<port>/ws`.

Then **rebuild and push** the image tag you use in LAB (e.g. `ghcr.io/ccruz0/openclaw:latest`).

**Implementation details:** [OPENCLAW_FRONTEND_WEBSOCKET_AND_BASEPATH.md](OPENCLAW_FRONTEND_WEBSOCKET_AND_BASEPATH.md).

---

## 3) Confirm Nginx proxy supports WebSockets on /openclaw/

**On PROD**, `location ^~ /openclaw/` must include:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

This is already in the repo’s block (e.g. `scripts/openclaw/openclaw_nginx_block.txt`, `nginx/dashboard.conf`). If you edited Nginx by hand, verify with:

```bash
sudo nginx -T | sed -n '/location \^~ \/openclaw\//,/^    }/p'
```

If WebSockets still fail after step 2, check:

- **Wrong WS path:** Frontend uses `/openclaw/ws` but backend serves `/ws` or `/socket` → align path or add a proxy rule.
- **Path rewrite:** Nginx proxies `/openclaw/` to backend root; backend must serve WS at the path the frontend uses (e.g. `/ws` under the same server).
- **Backend not listening for WS:** Ensure the app in the container actually exposes a WebSocket endpoint.

---

## 4) Quick test from the browser

After deploying the real image and fixing WS:

1. Open: **https://dashboard.hilovivo.com/openclaw/**
2. In DevTools → **Network** (filter WS): the WebSocket request should be to `wss://dashboard.hilovivo.com/openclaw/ws` (or your real WS route).
3. Status should be **101 Switching Protocols**.

If you see **Placeholder** or **ws://localhost:8081** in the console, re-check steps 1 and 2.

---

## Find WebSocket usage in the OpenClaw frontend repo (for step 2)

The OpenClaw frontend source is **not** in this repo (automated-trading-platform). It lives in the repo that builds `ghcr.io/ccruz0/openclaw`.

**In the OpenClaw frontend repo**, run:

```bash
# From the root of the OpenClaw frontend repo
grep -Rn "localhost:8081" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
grep -Rn "ws://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" .
```

Or in Cursor/VS Code: **Search in files** for:

- `localhost:8081`
- `WebSocket(`
- `ws://`

**Paste the list of matching files and line numbers** (e.g. `src/refresh.js:27`, `src/lib/socket.ts:42`). With that, the exact edits for each file can be given in 2–3 blocks.
