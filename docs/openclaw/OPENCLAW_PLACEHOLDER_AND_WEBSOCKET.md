# OpenClaw: placeholder UI and WebSocket connection failed

When https://dashboard.hilovivo.com/openclaw/ loads but you see a placeholder or a console error about WebSocket, use this guide.

---

## 1. "Placeholder. Replace OPENCLAW_IMAGE with full app when ready"

**Cause:** The container on LAB is serving the **placeholder** image, not the full OpenClaw application.

**Fix:** Deploy the real OpenClaw app on LAB and point the compose file at that image.

- **Runbook:** [DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md](../runbooks/DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md)
- **Summary:** On LAB set `OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest` (or your real image), then `docker compose -f docker-compose.openclaw.yml pull && docker compose -f docker-compose.openclaw.yml up -d`. The real image must be built and pushed from the OpenClaw application repo first (see [BUILD_AND_PUSH_OPENCLAW_IMAGE.md](BUILD_AND_PUSH_OPENCLAW_IMAGE.md)).

---

## 2. WebSocket connection to 'ws://localhost:8081/' failed

**Cause:** The OpenClaw frontend (HTML/JS served by the LAB container) is trying to connect to `ws://localhost:8081/`. In the browser, "localhost" is the **user’s machine**, not the server, so the connection fails.

**Nginx (this repo):** The dashboard config in `nginx/dashboard.conf` includes a proxy for `/openclaw/ws` → LAB:8081. Deploy that config and reload nginx on PROD so the app can use the same-origin URL `wss://dashboard.hilovivo.com/openclaw/ws`.

**What must be true:**

- **Nginx on PROD** must proxy WebSocket for `/openclaw/` (same path or a subpath like `/openclaw/ws`). The repo’s Nginx block already includes:
  - `proxy_http_version 1.1;`
  - `proxy_set_header Upgrade $http_upgrade;`
  - `proxy_set_header Connection "upgrade";`
  - `proxy_cache_bypass $http_upgrade;`
- **The OpenClaw application** must **not** use a hardcoded `ws://localhost:8081`. It must use a **proxy-aware** WebSocket URL, for example:
  - Same origin: `const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'; const wsUrl = protocol + '//' + location.host + '/openclaw/ws';` (or whatever path the app’s backend serves).
  - Or a build-time / runtime env var (e.g. `VITE_WS_URL` or `NEXT_PUBLIC_WS_URL`) set to a path under the same host (e.g. `wss://dashboard.hilovivo.com/openclaw/ws`).

**Fix:** In the **OpenClaw application source** (the repo that builds the OpenClaw UI):

1. Change the WebSocket URL from `ws://localhost:8081` to a URL derived from the current page (e.g. same host + path like `/openclaw/ws`) or from an env var.
2. Rebuild the app and push a new image; on LAB, pull and restart the container (see §1).

**Check Nginx on PROD:** If the live config was not inserted with the script that adds WebSocket headers, ensure the `location ^~ /openclaw/` block includes the Upgrade/Connection lines (see [NGINX_OPENCLAW_PROXY_TO_LAB_PRIVATE_IP.md](../runbooks/NGINX_OPENCLAW_PROXY_TO_LAB_PRIVATE_IP.md) and `scripts/openclaw/openclaw_nginx_block.txt` or `nginx/dashboard.conf`).

---

## Quick reference

| Symptom | Cause | Action |
|--------|--------|--------|
| Placeholder text, no real UI | LAB runs placeholder image | Deploy real OpenClaw image on LAB (§1, runbook above). |
| Console: `WebSocket connection to 'ws://localhost:8081/' failed` | App uses localhost for WS | Configure OpenClaw app to use same-origin or env WebSocket URL; rebuild and redeploy on LAB. |
