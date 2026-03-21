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
# If upstream returns absolute Location with internal host:port
proxy_redirect http://127.0.0.1:8080/ https://$host/openclaw/;
proxy_redirect http://127.0.0.1:8081/ https://$host/openclaw/;
proxy_redirect http://127.0.0.1:18789/ https://$host/openclaw/;
proxy_redirect http://172.31.3.214:8081/ https://$host/openclaw/;
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

**Important:** Nginx loads the file symlinked by `/etc/nginx/sites-enabled/default` (often `/etc/nginx/sites-available/default`), **not** `sites-available/dashboard`. Copying only to `dashboard` does nothing if that file is not enabled.

Use the deploy script (copies to the resolved target):

```bash
cd /home/ubuntu/automated-trading-platform
git pull
./scripts/openclaw/deploy_openclaw_basepath_nginx.sh
```

Or manually:

```bash
TARGET=$(readlink -f /etc/nginx/sites-enabled/default)
sudo cp nginx/dashboard.conf "$TARGET"
sudo nginx -t && sudo systemctl reload nginx
```

### 2. Check server-side redirects

`/openclaw/` uses **Basic Auth**. `curl` without `-u` returns **401** and **no `Location`** — that is normal; nginx never proxies to OpenClaw.

```bash
# Replace USER:PASS with your .htpasswd_openclaw credentials
curl -sS -I -u USER:PASS https://dashboard.hilovivo.com/openclaw/ | grep -i location
```

- **Good:** `Location: /openclaw/containers` (or `/openclaw/containers/`)
- **Bad:** `Location: /containers` (proxy_redirect not active or wrong nginx file — see deploy script `readlink -f sites-enabled/default`)

Optional follow chain:

```bash
curl -sS -I -L -u USER:PASS https://dashboard.hilovivo.com/openclaw/ 2>/dev/null | grep -E "HTTP|ocation"
```

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
| Basic Auth find/reset + validate | `scripts/openclaw/openclaw_basic_auth_find_or_reset.sh` (run on dashboard EC2) |
| OpenClaw basePath doc | `docs/openclaw/OPENCLAW_FRONTEND_WEBSOCKET_AND_BASEPATH.md` |
| Reference frontend | `docs/openclaw/reference-frontend/` |
| OPENCLAW_CONTROL_UI_BASE_PATH | `docker-compose.openclaw.yml` (backend env, not frontend build) |

---

## Continue checklist (copy-paste)

1. **Push latest ATP changes** (at minimum these paths if you do not want one giant commit):

   ```bash
   git add nginx/dashboard.conf scripts/openclaw/deploy_openclaw_basepath_nginx.sh scripts/openclaw/openclaw_nginx_block.txt docs/runbooks/OPENCLAW_BASEPATH_FIX.md
   git commit -m "OpenClaw nginx: deploy to sites-enabled target, proxy_redirect, Basic Auth curl note"
   git push
   ```

2. **Deploy on dashboard host** (one line; no comment lines — zsh can mangle pasted `#` blocks):

   ```bash
   ssh ubuntu@dashboard.hilovivo.com 'cd /home/ubuntu/automated-trading-platform && git pull && ./scripts/openclaw/deploy_openclaw_basepath_nginx.sh'
   ```

3. **Verify redirect** (must use Basic Auth):

   ```bash
   curl -sS -I -u 'openclaw:YOUR_PASSWORD' https://dashboard.hilovivo.com/openclaw/ | grep -i location
   ```

4. **Confirm nginx loaded `proxy_redirect`** (on server):

   ```bash
   sudo nginx -T 2>/dev/null | grep -A2 'location \^~ /openclaw/' | head -20
   sudo nginx -T 2>/dev/null | grep proxy_redirect
   ```

5. **Optional shell alias for LAB** (on your Mac, `~/.zshrc` — replace host):

   ```bash
   alias lab='ssh ubuntu@YOUR_LAB_HOST_OR_IP'
   ```

6. **Still broken in-browser after nginx is correct?** Rebuild OpenClaw image with `basePath` (see **Fix Required in OpenClaw Repo** above); nginx cannot fix client-side `navigate('/containers')`.

---

## Troubleshooting: `nginx -t` fails — `zero size shared memory zone "monitoring_limit"`

`nginx/dashboard.conf` uses `limit_req zone=monitoring_limit` and `zone=api_limit`. Those zones must be defined in the **`http { }`** block (not inside `server { }`).

**Fix (automated):** Re-run `./scripts/openclaw/deploy_openclaw_basepath_nginx.sh` from a repo that includes the script update: it copies `nginx/rate_limiting_zones.conf` to `/etc/nginx/` and adds `include /etc/nginx/rate_limiting_zones.conf;` after `http {` in `/etc/nginx/nginx.conf` if missing.

**Fix (manual):**

```bash
sudo cp /home/ubuntu/automated-trading-platform/nginx/rate_limiting_zones.conf /etc/nginx/rate_limiting_zones.conf
# Edit /etc/nginx/nginx.conf — inside http { }, add before sites-enabled:
#   include /etc/nginx/rate_limiting_zones.conf;
sudo nginx -t && sudo systemctl reload nginx
```

If nginx was left broken after a failed deploy, restore the previous site file from backup or `git checkout` the old `default` from backup under `/etc/nginx/nginx.conf.bak.*` only if you edited nginx.conf badly.

---

## Basic Auth: find, reset, validate (script)

On the **dashboard** host:

```bash
cd /home/ubuntu/automated-trading-platform
git pull
./scripts/openclaw/openclaw_basic_auth_find_or_reset.sh
```

The script (in order): checks `OPENCLAW_BASIC_AUTH`, repo `.env` / `secrets/runtime.env` for `OPENCLAW_BASIC_AUTH=openclaw:…`, scans `~/.bash_history` for `curl -u openclaw:…`; if nothing validates with `curl` against `/openclaw/`, backs up `/etc/nginx/.htpasswd_openclaw`, sets a new random password, `nginx -t` + `reload`, prints the password and a test `curl` command.

**Do not commit** the printed password. Prefer a password manager; optional local file: `~/.openclaw_basic_auth.env` with `chmod 600` (see script output).

---

## 503 on `/openclaw/` but message mentioned port 3000 (misleading)

**Cause:** Basic Auth works; nginx **cannot reach** the OpenClaw **upstream** (`proxy_pass` in `location ^~ /openclaw/` — e.g. `http://172.31.3.214:8081/`). Older nginx used `@frontend_error` for that path and wrongly said “frontend on port 3000”. Current `nginx/dashboard.conf` uses `@openclaw_upstream_error` with an accurate message.

**Diagnose on the dashboard EC2:**

```bash
# Match IP:port to your nginx openclaw proxy_pass
curl -sS -I --max-time 5 http://172.31.3.214:8081/ || echo "LAB unreachable"
curl -sS -I --max-time 5 http://127.0.0.1:8080/   || echo "local 8080 unreachable"
```

**Fix:**

1. Start OpenClaw on the LAB (or bind on PROD `127.0.0.1:8080` if that is your design).
2. **Security group:** allow TCP from dashboard instance (or its subnet) to OpenClaw host on **8081** (or **8080**).
3. Edit `proxy_pass` in `nginx/dashboard.conf` to the real IP and port, then redeploy nginx (`./scripts/openclaw/deploy_openclaw_basepath_nginx.sh`).
