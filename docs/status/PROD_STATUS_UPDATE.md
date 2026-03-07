# Production Status Update — Automated Trading Platform

**Report date:** 2026-03-01  
**Scope:** Repo `automated-trading-platform`; production host EC2 (dashboard.hilovivo.com).  
**Sources:** Repo documentation only; server verification commands must be run on EC2 and outputs pasted below.

---

## 1) Executive snapshot

- **Production instance:** atp-rebuild-2026 (i-087953603011543c5). Public IP 52.220.32.147. EC2_HOST = dashboard.hilovivo.com (docs/aws/AWS_PROD_QUICK_REFERENCE.md).
- **Stack:** Nginx (reverse proxy) → frontend (Next.js, port 3000) and backend (FastAPI/Gunicorn, port 8002); Postgres (`postgres_hardened`); market-updater-aws; observability (Prometheus, Grafana, Alertmanager, cadvisor, node-exporter); telegram-alerts container; OpenClaw at `/openclaw/` (Basic Auth, proxy to LAB or configured upstream).
- **What is working (per docs and recent fixes):**
  - Dashboard and API are the single deploy target; deploy via SSH to PROD and `docker compose --profile aws`.
  - Backend health endpoints exist: `/api/health`, `/api/health/system`; POST `/api/health/repair` (requires x-api-key) creates missing `order_intents` table.
  - x-api-key auth: backend reads **ATP_API_KEY** (or **INTERNAL_API_KEY**) from env; fallback `demo-key` for local (backend/app/deps/auth.py). Production should set ATP_API_KEY in `secrets/runtime.env`.
  - Script `scripts/aws/create_runtime_env.sh` creates minimal `secrets/runtime.env` (generates ATP_API_KEY) and ensures `.env` exists from `.env.example` if missing.
  - OpenClaw deploy script backs up to `/etc/nginx/backups/` (not sites-enabled), avoiding duplicate default server; checks for `htpasswd` before creating Basic Auth file.
- **What may be failing or unknown (verify on server):**
  - Disk was at 100%; space was freed (~11 GB). Docker healthchecks had failed with “no space left on device”. Current disk usage and Docker disk usage unknown until commands below are run.
  - System health (`/api/health/system`) can show FAIL for: market_data (no symbols / freshness null), market_updater (is_running false), telegram (enabled false / token or chat_id not set), trade_system (order_intents_table_exists false). These depend on runtime env and DB state.
  - SSM for PROD was last recorded as **ConnectionLost** (AWS_PROD_QUICK_REFERENCE.md). Access may be SSH-only.
- **Risk level:** **Medium** — recovery path and runbooks exist; live state (disk, containers, health, Telegram) must be confirmed on EC2.
- **What changed since last known state:**
  - Disk full incident and recovery; ATP_API_KEY and health/repair added; create_runtime_env.sh and runbook EC2_DASHBOARD_LIVE_DATA_FIX; OpenClaw nginx backup path and htpasswd check fixed; runbook index and OpenClaw deploy doc updated.

---

## 2) System status by component

*Run the commands in §6 on PROD (EC2), then paste outputs into the “Evidence” column. Owner from docs/SYSTEM_MAP.md and docker-compose.yml.*

| Component | Status (PASS/FAIL/Unknown) | Evidence (command/output) | Owner (from docs) | Next action |
|-----------|----------------------------|----------------------------|-------------------|-------------|
| **Disk / system** | Unknown | Run: `df -h`, `docker system df`, `uptime` | Ops | Paste output; ensure ≥10% free on `/`. |
| **Postgres** | Unknown | Run: `docker logs --tail 120 postgres_hardened` | db service | Confirm healthy; no OOM or “disk full” in logs. |
| **Backend** | Unknown | Run: `curl -s http://127.0.0.1:8002/api/health \| jq`, `curl -s http://127.0.0.1:8002/api/health/system \| jq` | backend-aws (SYSTEM_MAP: SignalMonitor, ExchangeSync, API) | 200 and `status: ok`; system health shows db_status, market_data, market_updater, trade_system, telegram. |
| **Frontend** | Unknown | Run: `curl -I http://127.0.0.1:3000/ \| head` | frontend-aws | Expect 200. |
| **Market updater** | Unknown | Run: `docker logs --tail 120 automated-trading-platform-market-updater-aws-1` (or exact name from `docker ps`) | market-updater-aws (SYSTEM_MAP: data flow) | Confirm running and logging updates; if not, `docker compose --profile aws up -d market-updater-aws`. |
| **Nginx** | Unknown | Run: `sudo nginx -t`, `curl -I https://dashboard.hilovivo.com/ \| head`, `curl -I https://dashboard.hilovivo.com/openclaw/ \| head` | Nginx (repo: nginx/dashboard.conf) | nginx -t ok; dashboard 200; openclaw 301→401 without auth. |
| **Telegram alerts (container)** | Unknown | Run: `docker logs --tail 120 atp-telegram-alerts` | telegram-alerts (observability) | Confirm container running; alerts depend on config. |
| **Telegram (backend)** | Unknown | From `/api/health/system`: `telegram.enabled`, `bot_token_set`, `chat_id_set` | TelegramNotifier (SYSTEM_MAP) | If FAIL: set TELEGRAM_BOT_TOKEN_AWS, TELEGRAM_CHAT_ID_AWS (or use runtime.env/render script). |
| **Monitoring (Prometheus/Grafana/Alertmanager)** | Unknown | `docker ps` for atp-prometheus, atp-grafana, atp-alertmanager | docker-compose aws profile | Confirm containers up if monitoring stack is enabled. |
| **OpenClaw** | Unknown | `curl -I https://dashboard.hilovivo.com/openclaw/ \| head` | Nginx + deploy_openclaw_nginx_prod.sh | 401 without auth; 200 with Basic Auth. |

---

## 3) Recent incident timeline

| When | Event | Source | Resolution / current state |
|------|--------|--------|----------------------------|
| Pre–report | EC2 disk 100%; Docker healthchecks failed (“no space left on device”) | User context | Space freed (~11 GB). Containers reported healthy again. |
| Pre–report | Backend responded 200 for `/` and `/api/health`; `/api/health/system` showed market_data FAIL, market_updater FAIL, telegram FAIL, trade_system FAIL (order_intents_table_exists false) | User context | Runbook EC2_DASHBOARD_LIVE_DATA_FIX: ATP_API_KEY, repair endpoint, market-updater. |
| Pre–report | POST /api/engine/run-once returned “Invalid API key” | User context | Auth fixed: backend uses ATP_API_KEY / INTERNAL_API_KEY from env. Create runtime.env via create_runtime_env.sh or render_runtime_env.sh. |
| 2026-02-24 (from user session) | OpenClaw nginx deploy: htpasswd not found on server; backup file left in sites-enabled caused “duplicate default server” | User session + deploy script | htpasswd: install apache2-utils. Backup: removed from sites-enabled; script now writes backups to /etc/nginx/backups/. |
| 2026-03-01 | create_runtime_env.sh missing on EC2; .env not found | User session | Doc updated: git pull then run script; script now creates .env from .env.example if missing. |

---

## 4) Configuration gaps and blockers

- **ATP_API_KEY:** Must be set in `secrets/runtime.env` (or .env.aws) for production. Used for x-api-key on POST /api/engine/run-once and POST /api/health/repair. If unset, backend falls back to `demo-key`. **File:** `secrets/runtime.env` (do not commit). **Action:** Run `./scripts/aws/create_runtime_env.sh` on EC2 (after `git pull`) or ensure render_runtime_env.sh / .env.aws provides it.
- **order_intents table:** If missing, `/api/health/system` shows trade_system FAIL. **Action:** Restart backend (init_db creates it) or call `POST /api/health/repair` with valid x-api-key.
- **.env:** Required by docker-compose env_file. If missing, compose may error. **Action:** create_runtime_env.sh creates .env from .env.example; or ensure .env or .env.aws exists with at least DATABASE_URL and POSTGRES_PASSWORD for db.
- **Telegram:** health/system shows telegram FAIL if RUN_TELEGRAM=true but TELEGRAM_BOT_TOKEN_AWS and TELEGRAM_CHAT_ID_AWS (or vars read by backend) are not set. **Files:** .env.aws or secrets/runtime.env (from render_runtime_env.sh or SSM). **Action:** Set vars or set RUN_TELEGRAM=false.
- **Market data / market_updater:** health shows FAIL if no fresh data (market_updater not running or not writing). **Action:** Ensure market-updater-aws container is up; check logs.
- **RESPONSIBILITY_MATRIX.md:** Not present in repo. Component ownership taken from **docs/SYSTEM_MAP.md** and **docker-compose.yml** comments.

---

## 5) Action plan (ordered, minimal)

1. **SSH to PROD**  
   `ssh ubuntu@dashboard.hilovivo.com` (or use EC2 key to 52.220.32.147). If unreachable, use RUNBOOK_SSM_PROD_CONNECTION_LOST or RUNBOOK_SSM_FIX_AND_INJECT_SSH_KEY.

2. **Disk and containers**  
   On EC2:  
   `cd ~/automated-trading-platform`  
   `df -h`  
   `docker system df`  
   `uptime`  
   `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`  
   **Expected:** Free space on `/`; no “no space left”; backend, frontend, db, market-updater-aws running.

3. **Env and API key**  
   On EC2:  
   `cd ~/automated-trading-platform`  
   `git pull origin main`  
   `./scripts/aws/create_runtime_env.sh`  
   Save printed ATP_API_KEY. If script missing, add ATP_API_KEY to `secrets/runtime.env` (generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).

4. **Restart stack**  
   On EC2:  
   `cd ~/automated-trading-platform`  
   `docker compose --profile aws down`  
   `docker compose --profile aws up -d`  
   Wait ~30s.  
   **Expected:** All aws-profile services up; backend logs show “[BOOT] order_intents table OK” or repair creates it.

5. **Repair DB if needed**  
   On EC2 (replace YOUR_ATP_API_KEY):  
   `curl -s -X POST "http://127.0.0.1:8002/api/health/repair" -H "x-api-key: YOUR_ATP_API_KEY" | jq`  
   **Expected:** `{"ok": true, "message": "Repair completed ..."}`.

6. **Backend health**  
   On EC2:  
   `curl -s http://127.0.0.1:8002/api/health | jq`  
   `curl -s http://127.0.0.1:8002/api/health/system | jq`  
   **Expected:** health 200 with status ok; system health with global_status PASS or WARN, order_intents_table_exists true, market_data/market_updater non-FAIL once updater has run.

7. **Frontend and public**  
   On EC2:  
   `curl -I http://127.0.0.1:3000/ | head`  
   `curl -I https://dashboard.hilovivo.com/ | head`  
   `curl -I https://dashboard.hilovivo.com/openclaw/ | head`  
   **Expected:** 200 for frontend and dashboard; openclaw 401 without auth.

8. **Run full verification**  
   Run all commands in §6 below on EC2; paste outputs into §2 “Evidence” and update Status column.

9. **Optional: Telegram**  
   If alerts desired: set TELEGRAM_BOT_TOKEN_AWS and TELEGRAM_CHAT_ID_AWS in secrets/runtime.env (or .env.aws); set RUN_TELEGRAM=true; restart backend-aws and market-updater-aws.

10. **Document**  
    Update this report’s §2 with actual outputs and set Status to PASS/FAIL per component.

---

## 6) Server verification commands (run on EC2)

*Run these on PROD (cd ~/automated-trading-platform first). Paste outputs into §2 Evidence column.*

```bash
cd ~/automated-trading-platform

# 1) Disk and system
df -h
docker system df
uptime

# 2) Containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 3) Backend health
curl -s http://127.0.0.1:8002/api/health | jq
curl -s http://127.0.0.1:8002/api/health/system | jq

# 4) Frontend health
curl -I http://127.0.0.1:3000/ | head

# 5) Nginx routing
sudo nginx -t
curl -I https://dashboard.hilovivo.com/ | head
curl -I https://dashboard.hilovivo.com/openclaw/ | head

# 6) Market updater (adjust container name if different)
docker compose --profile aws ps --format "{{.Name}}" | grep -i market
docker logs --tail 120 $(docker compose --profile aws ps -q market-updater-aws 2>/dev/null | head -1) 2>/dev/null || docker logs --tail 120 automated-trading-platform-market-updater-aws-1 2>/dev/null || echo "Container name not found"

# 7) Telegram alerts container
docker logs --tail 120 atp-telegram-alerts 2>/dev/null || echo "Container not found"

# 8) Postgres
docker logs --tail 120 postgres_hardened 2>/dev/null || echo "Container not found"
```

---

## Documentation used

| Doc | Purpose |
|-----|---------|
| docs/SYSTEM_MAP.md | Components, ownership, data flow, order lifecycle |
| docs/aws/AWS_PROD_QUICK_REFERENCE.md | Instance IDs, IPs, SSM state, scripts, workflows |
| DEPLOYMENT_POLICY.md | SSH-only deploy, docker compose --profile aws |
| docs/aws/RUNBOOK_INDEX.md | Runbooks and “if PROD down” steps |
| docs/runbooks/EC2_DASHBOARD_LIVE_DATA_FIX.md | ATP_API_KEY, market-updater, order_intents, repair |
| docs/openclaw/DEPLOY_OPENCLAW_NGINX_PROD.md | OpenClaw nginx block, backup path, htpasswd |
| docker-compose.yml | Services (backend-aws, frontend-aws, db, market-updater-aws, observability), env_file, profiles |
| nginx/dashboard.conf | server_name, locations, OpenClaw proxy |
| backend/app/services/system_health.py | Health structure (global_status, market_data, market_updater, trade_system, telegram) |

**Not found:** RESPONSIBILITY_MATRIX.md (ownership from SYSTEM_MAP.md and compose comments).

---

*End of report. Fill §2 and re-run §6 after any change to get a current snapshot.*
