# Dashboard 502 Error – Deep Investigation

This document traces the full request path for the Trading Dashboard at **dashboard.hilovivo.com**, identifies every place that can produce or contribute to **HTTP 502**, and recommends fixes.

---

## 1. Request flow (dashboard.hilovivo.com)

### 1.1 Frontend (browser)

- **Domain:** `dashboard.hilovivo.com` → `environment.ts` treats it as `isHiloVivo` → `apiUrl = '/api'` (relative).
- **Effective API base:** `https://dashboard.hilovivo.com/api`.
- **Calls relevant to the 502 / “No portfolio data” behaviour:**
  - **System Health panel:** `getSystemHealth()` → `fetchAPI('/health/system')` → `GET https://dashboard.hilovivo.com/api/health/system`.
  - **Portfolio / dashboard state:** `getDashboardState()` or `getDashboardSnapshot()` → `GET .../api/dashboard/state` or `.../api/dashboard/snapshot`.

### 1.2 Nginx (reverse proxy on EC2)

- **Config:** `docs/runbooks/nginx_aws_dashboard_setup.md` (and `.cursor/rules/ec2-nginx-production.mdc`).
- **Routing:**
  - `location /api/` → `proxy_pass http://127.0.0.1:8002`
  - `location /` → `proxy_pass http://127.0.0.1:3000` (frontend).
- **Timeouts (current):**
  - `proxy_read_timeout 60s`
  - `proxy_connect_timeout 10s`
  - `proxy_send_timeout 60s`

So any `/api/*` request that takes **more than 60 seconds** to receive the first byte of the response causes **nginx to close the connection and return 502** to the client.

### 1.3 Backend (Docker, backend-aws)

- **Service:** `backend-aws` in `docker-compose.yml` (profile `aws`).
- **Process:** Gunicorn + Uvicorn worker:  
  `gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8002 --timeout 120`
- **Important:** Single worker (`-w 1`), backend timeout **120s**.
- **Routes:**
  - `GET /api/health/system` → `routes_monitoring.get_system_health_endpoint` (monitoring router, prefix `/api`).
  - `GET /api/dashboard/state` → `routes_dashboard.get_dashboard_state` (dashboard router, prefix `/api`).

So:

- **502 is not returned by the FastAPI app** for these endpoints. The app returns **503** when DB is down (`/health/system`) or **500** on unhandled exceptions (`/dashboard/state` re-raises).
- **502 is returned by nginx** when:
  1. It cannot connect to `127.0.0.1:8002` (backend down/restarting), or  
  2. The backend does not send a response within **60s** (nginx read timeout).

---

## 2. Where 502 can come from

| Source | When it happens |
|--------|------------------|
| **Nginx** | Connect to backend fails (e.g. backend down) → 502 after up to `proxy_connect_timeout` (10s). |
| **Nginx** | Backend responds after > 60s → nginx closes connection and returns 502 (`proxy_read_timeout 60s`). |
| **Backend** | Does **not** send 502 for `/api/health/system` or `/api/dashboard/state`. It uses 503 (DB down) or 500 (exception). |
| **Backend** | Other routes (e.g. `routes_internal`, `routes_account`, `routes_orders`) can raise `HTTPException(502)` on **outbound** failures (e.g. exchange/egress). Not the case for health or dashboard state. |

Conclusion: the **502 shown in the System Health panel** (and often associated “No portfolio data”) is almost certainly from **nginx**, due to either backend unreachable or **response time > 60s**.

**Fix in repo:** `nginx/dashboard.conf` already uses `proxy_read_timeout 120s` for `location /api`. Deploy that file to the server (or set 120s in the server’s API location) and reload nginx. The script `scripts/fix-502-aws.sh` detects when the active nginx config still has 60s for the API and instructs to deploy the repo config.

---

## 3. Why the backend might exceed 60s

### 3.1 Single worker

- One Gunicorn worker handles all requests.
- If one request (e.g. `/api/dashboard/state`) runs for 70s, the worker is busy for 70s.
- Another request (e.g. `/api/health/system`) is **queued** until the first finishes.
- So the health check can be delayed by a long dashboard/state request, and nginx may already be waiting; if total time exceeds 60s, nginx returns 502.

### 3.2 `/api/dashboard/state` is heavy

- `_compute_dashboard_state()`:
  - Tries `get_latest_portfolio_snapshot()` (DB + possibly cached data).
  - Fallback: `get_portfolio_summary(db)` (DB).
  - If cache/snapshot empty: can call `fetch_live_portfolio_snapshot(db)` (Crypto.com API).
  - Then open orders cache, DB queries for ghost orders, `calculate_portfolio_order_metrics()`, and building a large payload.
- Past notes (e.g. `backend/perf_investigation_log.md`, `RESUMEN_CAMBIOS_ULTIMAS_2H.md`) report **50–70s** for this endpoint in some conditions.
- So **dashboard/state can legitimately exceed 60s**, which matches nginx’s 60s read timeout and explains 502.

### 3.3 `/api/health/system`

- Uses a **2s** DB `statement_timeout` in `system_health.py` so it should not hang on DB.
- If the **worker is busy** with a long `/api/dashboard/state`, `/api/health/system` waits in queue; by the time it runs, the client (or nginx) may have already timed out → 502.

---

## 4. Frontend timeouts

- **`/dashboard/state`:** 180s in `frontend/src/lib/api.ts` (so frontend is willing to wait longer than nginx).
- **`/health/system`:** no specific branch → **default 30s**. So the UI will abort after 30s; if the response was already 502 from nginx, the user sees “HTTP error! status: 502”.

---

## 5. Root-cause scenarios (concise)

1. **Backend down or restarting**  
   Nginx cannot connect to `127.0.0.1:8002` → 502 (within ~10s). Both health and dashboard calls can 502.

2. **Slow `/api/dashboard/state` (> 60s)**  
   Nginx read timeout → 502 for that request. Portfolio/data fails; “No portfolio data available” and possibly a 502 in the System Health panel if that request also hits the same nginx timeout or is delayed by the same worker.

3. **Single worker busy**  
   Long dashboard/state blocks the worker; health runs late and nginx or client times out → 502 for health and/or dashboard.

4. **Uvicorn `--reload` in production**  
   Documented as forbidden (e.g. `docker-compose.yml`, README): causes restarts and 502s. Ensure production uses the gunicorn command without `--reload`.

---

## 6. Recommendations

### 6.1 Nginx (critical)

- **Increase** `proxy_read_timeout` (and if desired `proxy_send_timeout`) for `/api/` to at least **90s or 120s** so they are not shorter than the backend’s 120s gunicorn timeout.
- Example (in the `location /api/` block):

```nginx
proxy_read_timeout 120s;
proxy_connect_timeout 10s;
proxy_send_timeout 120s;
```

- Optionally use a **longer** timeout only for heavy paths (e.g. `location /api/dashboard/state`) if your nginx version supports it; otherwise a single 120s for `/api/` is the simplest and safest.

### 6.2 Backend

- Consider **more than one worker** (e.g. `-w 2`) so that one slow `/api/dashboard/state` does not block `/api/health/system` (and other requests). Validate resource limits (CPU/memory) and any shared state (caches, DB) before changing.
- Keep **no `--reload`** in production.

### 6.3 Frontend (already improved)

- System Health panel: on 502, show a clear message and a **Retry** button (implemented in `SystemHealth.tsx`).
- Optional: give `/health/system` a dedicated timeout (e.g. 15s) in `frontend/src/lib/api.ts` so the UI fails fast instead of waiting the default 30s.

### 6.4 Operational checks

When 502 appears:

1. **Backend reachable?**  
   On EC2: `curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/api/health` or `http://127.0.0.1:8002/ping_fast`.
2. **Backend slow?**  
   `time curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/api/dashboard/state`. If > 60s, nginx will 502.
3. **Nginx config:**  
   `sudo nginx -T 2>/dev/null | grep -A 20 'location /api/'` and confirm timeouts.
4. **Containers:**  
   `docker compose --profile aws ps` and logs for `backend-aws`.

---

## 7. Solution summary (what’s done / what you do)

| Done in repo | Your action on the server |
|--------------|----------------------------|
| `nginx/dashboard.conf` uses **120s** for `location /api` | Deploy this file to EC2 and reload nginx (see runbook **Quick fix for 502**, Option A) |
| Frontend: 502 message + Retry in System Health; 15s timeout for `/health/system` | None |
| `scripts/fix-502-aws.sh` checks for API timeout 60s and tells you to deploy repo config | Run the script; if it reports 60s, deploy `nginx/dashboard.conf` and reload nginx |
| Runbooks and docs cross-linked; 120s documented everywhere | Use Quick fix (Option A or B) once so the live nginx config matches the repo |

After deploying the repo’s `nginx/dashboard.conf` (or setting 120s for `/api` and reloading), 502 from timeout for `/api/dashboard/state` and `/api/health/system` should stop.

---

## 8. References

- Frontend API URL: `frontend/src/lib/environment.ts` (hilovivo → `/api`).
- Frontend timeouts: `frontend/src/lib/api.ts` (dashboard/state 180s; health/system 15s).
- Nginx runbook: `docs/runbooks/nginx_aws_dashboard_setup.md` (includes **Quick fix for 502 (timeout)**).
- 502 runbook: `docs/runbooks/502_BAD_GATEWAY.md` (quick checks, script, timeout note).
- Backend routing: `backend/app/main.py` (routers with prefix `/api`).
- Dashboard state: `backend/app/api/routes_dashboard.py` (`_compute_dashboard_state`, `get_dashboard_state`).
- Health: `backend/app/api/routes_monitoring.py` (`/health/system`), `backend/app/services/system_health.py` (DB timeout 2s).
- Compose: `docker-compose.yml` (backend-aws: gunicorn `-w 1`, `--timeout 120`).
- README: “Dashboard Not Loading (502 / Blank UI)”, “nginx 502” troubleshooting.
