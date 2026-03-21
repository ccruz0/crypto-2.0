# OpenClaw /openclaw Prefix Fix — Root Cause & Validation

**Date:** 2025-03-21  
**Issue:** App redirects to `/containers` instead of `/openclaw/containers` → 404

---

## Root Cause

OpenClaw assumes it is mounted at `/` instead of `/openclaw/`:

1. **Server-side redirects** — Backend returns `Location: /containers` (or `Location: https://host/containers`). Browser follows → `https://dashboard.hilovivo.com/containers` → 404 (dashboard frontend has no `/containers` route).
2. **Client-side routing** — Frontend router uses root-relative paths (e.g. `/containers`, `/logs`). These are baked into the build; without `basePath`, links and `navigate()` stay root-relative.
3. **Build-time config** — OpenClaw must be built with `basePath`/`base` set to `/openclaw` (Next.js) or `/openclaw/` (Vite). The current image is built for root.

---

## Fixes Applied (ATP Repo)

### 1. Nginx — Rewrite `Location` Headers (Server-Side Redirects)

**Files:** `nginx/dashboard.conf`, `scripts/openclaw/openclaw_nginx_block.txt`

Added to the `location ^~ /openclaw/` block:

```nginx
proxy_set_header X-Forwarded-Prefix /openclaw;

# Rewrite Location headers so redirects stay under /openclaw/
proxy_redirect / /openclaw/;
proxy_redirect https://$host/ https://$host/openclaw/;
proxy_redirect http://$host/ http://$host/openclaw/;
```

**Effect:**
- `Location: /containers` → `Location: /openclaw/containers`
- `Location: https://dashboard.hilovivo.com/containers` → `Location: https://dashboard.hilovivo.com/openclaw/containers`

This fixes **server-side** 301/302 redirects. Client-side navigation (React Router, `navigate()`) is still wrong until the OpenClaw frontend is rebuilt with `basePath`.

---

## Fix Required in OpenClaw Repo (Client-Side)

The OpenClaw frontend must be built with base path. Apply in the **OpenClaw frontend repo** (ccruz0/openclaw):

### Next.js

In `next.config.js`:

```js
const basePath = process.env.NEXT_PUBLIC_OPENCLAW_BASE_PATH || "";
const nextConfig = {
  basePath: basePath || undefined,
  assetPrefix: basePath || undefined,
  // ...
};
```

Build for production behind `/openclaw/`:

```bash
NEXT_PUBLIC_OPENCLAW_BASE_PATH=/openclaw npm run build
```

### Vite

In `vite.config.ts`:

```ts
export default defineConfig({
  base: process.env.VITE_OPENCLAW_BASE_PATH || "/",
  // ...
});
```

Build:

```bash
VITE_OPENCLAW_BASE_PATH=/openclaw/ npm run build
```

### Router

- Use relative paths or `basePath + "/containers"` instead of `"/containers"`.
- Ensure `createBrowserRouter` / `<Router basename="/openclaw">` if the framework supports it.

### WebSocket

- Use same-origin: `wss://${location.host}/openclaw/ws` (see `docs/openclaw/OPENCLAW_FRONTEND_WEBSOCKET_AND_BASEPATH.md`).

---

## Before / After

| Scenario | Before | After (nginx only) | After (nginx + OpenClaw basePath) |
|----------|--------|--------------------|------------------------------------|
| Server redirect to `/containers` | 404 on `/containers` | 200 on `/openclaw/containers` | 200 on `/openclaw/containers` |
| Client navigate to `/containers` | 404 on `/containers` | 404 on `/containers` | 200 on `/openclaw/containers` |
| Direct nav to `/openclaw/containers` | — | 200 (if server serves it) | 200 |
| Assets | May 404 if root-relative | May 404 | 200 under `/openclaw/` |

---

## Validation Steps

### 1. Deploy nginx changes on PROD

```bash
cd /home/ubuntu/automated-trading-platform
git pull  # or copy updated nginx/dashboard.conf
# If OpenClaw runs on same host, ensure proxy_pass uses 127.0.0.1:8080; if on LAB, use 172.31.3.214:8081
sudo cp nginx/dashboard.conf /etc/nginx/sites-available/dashboard  # or your actual path
sudo nginx -t
sudo systemctl reload nginx
```

### 2. Check server-side redirects

```bash
# Follow redirects, check final URL
curl -sS -I -L -u openclaw:PASSWORD https://dashboard.hilovivo.com/openclaw/ 2>/dev/null | grep -E "HTTP|ocation"
```

- Final URL should stay under `/openclaw/`, not `/containers` at root.

### 3. Manual browser checks

- **/openclaw/** — Loads, no redirect to `/containers`.
- **/openclaw/containers** — Loads (if route exists).
- **/openclaw/logs** — Loads (if route exists).
- **WebSocket** — DevTools → Network → WS; URL should be `wss://dashboard.hilovivo.com/openclaw/ws`.

### 4. Confirm no root-level redirects

- Open `https://dashboard.hilovivo.com/openclaw/`.
- Navigate via UI.
- Address bar should stay under `/openclaw/...`, never show `/containers` or `/logs` at root.

---

## Reference

| Item | Location |
|------|----------|
| Nginx config | `nginx/dashboard.conf` |
| OpenClaw basePath doc | `docs/openclaw/OPENCLAW_FRONTEND_WEBSOCKET_AND_BASEPATH.md` |
| Reference frontend | `docs/openclaw/reference-frontend/` |
| OPENCLAW_CONTROL_UI_BASE_PATH | `docker-compose.openclaw.yml` (backend env, not frontend build) |
