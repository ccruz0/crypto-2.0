# Automated Trading Platform – End-to-End Audit Report
**Date:** 2026-02-02  
**Scope:** Documentation, static code, AWS runtime, data layer, alerts/trading flow, deployment  
**Constraint:** No code changes made; evidence-based findings only  

---

## Phase 1: Documentation Index

| File | Purpose | Key Commands | Known Issues |
|------|---------|--------------|--------------|
| `README.md` | Project overview, runtime architecture | `docker compose --profile aws ps`, `scripts/deploy_aws.sh` | AWS-only production; local is dev-only |
| `README-ops.md` | Operations guide, Crypto.com SL/TP, auth | `bash scripts/aws/aws_up_backend.sh`, `make aws-backend-up` | **Do not run compose directly** – use aws_up_backend.sh |
| `DEPLOYMENT_POLICY.md` | SSH-based deploy, no uvicorn --reload | `docker compose --profile aws ...` | — |
| `docs/contracts/deployment_aws.md` | Canonical AWS commands | `docker compose --profile aws ps/logs/restart` | — |
| `docs/runbooks/dashboard_healthcheck.md` | 502 troubleshooting, nginx, containers | `scripts/debug_dashboard_remote.sh` | **Stale:** references gluetun (removed from compose) |
| `docs/WORKFLOW_DEVOPS_DEPLOYMENT.md` | Cursor AI deployment workflow | — | Uses Vercel URLs; runbook may be outdated |
| `docker-compose.yml` | Services, profiles (local/aws) | `--profile aws`, `--profile local` | Gluetun commented out; backend-aws uses secrets/runtime.env |
| `Makefile` | Auth checks, backend up | `make aws-verify-exchange-creds`, `make aws-backend-up` | — |
| `backend/README-Docker-backend.md` | Backend image build | `make lock`, `make build` | — |
| `scripts/deploy_aws.sh` | Deploy-by-commit (git reset, build, health) | `bash scripts/deploy_aws.sh` | **Conflict:** Does NOT use aws_up_backend.sh; may fail if secrets/runtime.env missing |
| `scripts/aws/aws_up_backend.sh` | One-command backend deploy | Renders runtime.env, runs deploy_backend_with_secrets | **Prefer over deploy_aws.sh** per README-ops |
| `scripts/rollback_aws.sh` | Rollback to commit | `./scripts/rollback_aws.sh <sha>` | — |
| `docs/CRYPTOCOM_SLTP_REGRESSION.md` | SL/TP evidence, boolean canonicalization | — | 308 Invalid price format; boolean → JSON true/false |
| `docs/ORDER_LIFECYCLE_GUIDE.md` | Order states, Telegram semantics | — | — |

---

## Phase 2: Architecture Map

### Services and Ports (AWS Profile)

| Service | Container | Port (host) | Depends On | Notes |
|---------|-----------|-------------|------------|-------|
| db | postgres_hardened | (internal 5432) | — | No port mapping; Docker network only |
| backend-aws | backend-aws | 8002 | db | Gunicorn + Uvicorn; no --reload |
| frontend-aws | frontend-aws | 3000 | backend-aws | Next.js production |
| market-updater-aws | market-updater-aws | — | db | Healthchecks backend-aws:8002 |
| aws-backup | postgres_hardened_backup | — | — | Optional backup volume |

### Critical Paths

1. **API request → DB → Exchange → Telegram**  
   `routes_*` → `services/` → `models/` → `brokers/crypto_com_trade.py` → `telegram_notifier.py`

2. **Signal monitor loop**  
   `market-updater` or `scheduler` → `signal_monitor.py` → `watchlist_signal_state` (upsert) → `signal_throttle` → `alert_emitter` → `telegram_notifier` → `tp_sl_order_creator` → `crypto_com_trade`

3. **Routes → Services → Models**
   - `routes_dashboard` → `WatchlistSignalState`, `get_portfolio_summary`
   - `routes_signals` → `signal_evaluator`, `get_signals`
   - `routes_orders` → `exchange_sync`, `order_history_db`
   - `routes_control` → `crypto_com_trade` (trigger probe)

### Profiles

- **local:** backend-dev (uvicorn --reload), backend, market-updater, frontend, db  
- **aws:** backend-aws, frontend-aws, market-updater-aws, db, aws-backup  

---

## Phase 3: AWS Reality Check

### A) Baseline

| Check | Result |
|-------|--------|
| **Path** | `/home/ubuntu/automated-trading-platform` |
| **Git SHA** | `c9ac75e80f3f91513368248f71ae739916612ba9` |
| **Git log** | `c9ac75 chore: ignore local scratch docs` |
| **Git status** | `?? backend/app/models/watchlist_signal_state.py` (untracked on host) |
| **docker compose --profile aws ps** | 5 containers; backend-aws `(health: starting)`, market-updater-aws `(unhealthy)` |
| **Disk** | 18G/48G used (38%) |
| **Memory** | 1189M used, 721M available |

### B) Container File Parity – **BLOCKER**

| Check | Evidence |
|-------|----------|
| `/app/app/models/` in backend-aws | **Missing `watchlist_signal_state.py`** – container has 16 model files; `watchlist_signal_state.py` is NOT present |
| `pkgutil.iter_modules(app.models)` | `['dashboard_cache','db','exchange_balance',...,'watchlist_master']` – no `watchlist_signal_state` |

### C) Health and Logs

| Service | Status | Headline Error |
|---------|--------|----------------|
| backend-aws | Crash loop | `ModuleNotFoundError: No module named 'app.models.watchlist_signal_state'` (routes_dashboard.py:15) |
| market-updater-aws | Unhealthy | Healthcheck probes backend-aws:8002; backend is down → health fails |
| frontend-aws | Healthy | — |
| db | Healthy | — |

### D) Environment (Variable Names Only)

Backend has: `API_BASE_URL`, `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EXCHANGE_CUSTOM_*`, `RUNTIME_ORIGIN`, etc.  
(No secrets printed.)

### E) Database

| Check | Result |
|-------|--------|
| Database name | `atp` (not `trading`) |
| Tables | 18 tables including `watchlist_signal_state` (singular), `telegram_messages`, `exchange_orders` |
| `watchlist_signal_states` (plural) | **Does not exist** – only `watchlist_signal_state` (singular) |
| `watchlist_signal_state` schema | `symbol` PK, `strategy_key`, `signal_side`, `last_price`, `evaluated_at_utc`, `alert_status`, etc. |
| telegram_messages count | 156,745 |
| exchange_orders count | 4,612 |

### F) Network

- Ports: 22, 53, 80, 443, 8002, 3000  
- Nginx on 80/443; backend on 8002; frontend on 3000  

---

## Phase 4: Focused Deep Dives

### 1. Watchlist Signal State

| Item | Evidence | Status |
|------|----------|--------|
| Model in repo | `backend/app/models/watchlist_signal_state.py` (line 17: `__tablename__ = "watchlist_signal_states"`) | ✅ Exists |
| Model in container | `ls /app/app/models` – **no watchlist_signal_state.py** | ❌ **MISSING** |
| Table in DB | `watchlist_signal_state` (singular) exists; `watchlist_signal_states` (plural) does NOT exist | ❌ **MISMATCH** |
| Model schema | `id` PK, `symbol` unique, `evaluated_at_utc` nullable | — |
| DB schema | `symbol` PK (no `id`), `evaluated_at_utc` NOT NULL DEFAULT now(), `updated_at` | **Drift** |
| Migration | `20260128_create_watchlist_signal_states.sql` creates `watchlist_signal_states` (plural) | Never applied to AWS DB |
| signal_monitor upsert | `_upsert_watchlist_signal_state()` uses `WatchlistSignalState` | Would fail: wrong table name + schema |

### 2. SL/TP and Order Formatting

| Item | Evidence |
|------|----------|
| Price/trigger formatters | `crypto_com_trade.py`: `normalize_price()`, `_normalize_price_str()`, trigger_price/trigger_condition variants |
| Error 308 | README-ops.md L110–111: "Invalid price format" – use plain decimal strings, correct trigger key |
| CRYPTOCOM_SLTP_REGRESSION | Boolean canonicalization (`True`→`"True"` vs `true`); 308 from float prices |
| Canonical formatter | `normalize_price()` in crypto_com_trade; multiple variation fallbacks in place_stop_loss_order/place_take_profit_order |

### 3. Telegram Menu Interactions

| Item | Evidence |
|------|----------|
| Mode | Long polling (`getUpdates`), not webhook – `telegram_commands.py` L991 |
| Startup | Deletes webhook if present (`_run_startup_diagnostics`) |
| Callback handlers | `handle_telegram_update()` processes `menu:*`, `cmd:*`; idempotency via `PROCESSED_CALLBACK_DATA` |
| Buttons “dead” | Backend crash loop → no Telegram polling → buttons not processed |

### 4. Deployment Drift

| Item | Evidence |
|------|----------|
| Build context | `backend/Dockerfile.aws`: context `.`, `COPY backend/ /app/` |
| watchlist_signal_state in image | Not present – image built from code without it, or cached layer |
| secrets/runtime.env | Required by backend-aws `env_file`; `aws_up_backend.sh` renders it |
| deploy_aws.sh vs aws_up_backend | `deploy_aws.sh` uses `docker compose up --build` directly; may fail if runtime.env missing |

---

## Phase 5: Findings Table

| Area | Issue | Evidence | Impact | Fix Approach | Verification |
|------|-------|----------|--------|--------------|--------------|
| **Backend** | `watchlist_signal_state.py` missing from container | Container `ls`; `ModuleNotFoundError` in logs | **BLOCKER** – backend crash loop | Include file in image: ensure committed, pull on AWS, rebuild backend-aws | `docker compose exec backend-aws ls /app/app/models` |
| **Schema** | Table name mismatch: model `watchlist_signal_states`, DB `watchlist_signal_state` | `\d watchlist_signal_states` → "Did not find" | **BLOCKER** – queries fail | Align: either (a) run migration to create `watchlist_signal_states`, or (b) change model `__tablename__` to `watchlist_signal_state` and align columns | `psql -c "\dt"` and query test |
| **Schema** | Column/schema drift: model has `id` PK, DB has `symbol` PK; `updated_at` in DB only | Model vs `\d watchlist_signal_state` | HIGH | Add migration to match model or adjust model to match DB | Inspect schema, run migration |
| **Docs** | Runbook references gluetun | `dashboard_healthcheck.md` dependencies | LOW | Update runbook; gluetun removed | Read runbook |
| **Deploy** | deploy_aws.sh bypasses aws_up_backend | README-ops vs deploy_aws.sh | MEDIUM | Standardize on aws_up_backend or ensure deploy_aws renders runtime.env | Compare scripts |
| **market-updater** | Unhealthy | Depends on backend healthcheck | MEDIUM | Cascading: fix backend first | `docker compose ps` |
| **WatchlistSignalState** | Not in models/__init__.py | `app/models/__init__.py` | LOW | Optional: add for consistency | Import test |

---

## Step-by-Step Remediation Plan

### Immediate Fixes (Today)

1. **Fix backend boot (BLOCKER)**  
   - Ensure `backend/app/models/watchlist_signal_state.py` is committed and on `main`.  
   - On AWS: `git pull origin main`, then rebuild backend:  
     `docker compose --profile aws build --no-cache backend-aws && docker compose --profile aws up -d backend-aws`  
   - **Owner:** DevOps; **Risk:** Low  

2. **Fix table name / schema (BLOCKER)**  
   - Option A: Create `watchlist_signal_states` per migration and migrate data from `watchlist_signal_state`.  
   - Option B: Change model `__tablename__ = "watchlist_signal_state"` and add `updated_at`; ensure columns match DB.  
   - **Owner:** Backend; **Risk:** Medium (data migration if Option A)  

3. **Verify backend health**  
   - After rebuild: `curl -s http://localhost:8002/health`  
   - **Owner:** DevOps; **Risk:** Low  

### Hardening (This Week)

4. **Standardize deploy**  
   - Prefer `bash scripts/aws/aws_up_backend.sh` over `deploy_aws.sh` for backend, or make `deploy_aws.sh` call it.  
   - **Owner:** DevOps; **Risk:** Low  

5. **Update runbook**  
   - Remove gluetun from `docs/runbooks/dashboard_healthcheck.md`.  
   - **Owner:** Docs; **Risk:** None  

6. **Add build-time check for watchlist_signal_state**  
   - In Dockerfile.aws: `RUN test -f /app/app/models/watchlist_signal_state.py || (echo "ERROR: ..." && exit 1)`  
   - **Owner:** DevOps; **Risk:** Low  

### Structural Refactors (Later)

7. **Unify SL/TP formatter**  
   - Centralize price/trigger formatting in one module; document in `docs/trading/crypto_com_order_formatting.md`.  
   - **Owner:** Backend; **Risk:** Medium  

8. **Add migration automation**  
   - Run migrations as part of deploy (e.g., backend startup or pre-deploy step).  
   - **Owner:** DevOps; **Risk:** Medium  

---

## Verification Suite

Run after each fix stage:

```bash
# 1. Compose status
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws ps

# 2. Backend health
curl -sS http://localhost:8002/health
curl -sS http://localhost:8002/api/health/system | jq .

# 3. Backend model presence
docker compose --profile aws exec -T backend-aws ls -la /app/app/models/watchlist_signal_state.py

# 4. market-updater health (after backend is healthy)
docker compose --profile aws ps market-updater-aws

# 5. API smoke test
curl -sS http://localhost:8002/api/config | head -5

# 6. DB table
docker compose --profile aws exec -T db sh -lc "PGPASSWORD=\$POSTGRES_PASSWORD psql -U trader -d atp -c '\dt'"

# 7. Dry-run signal (if backend healthy)
curl -sS -X POST http://localhost:8002/api/control/evaluate-signal \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"BTC_USDT"}' | jq .
```

---

## Executive Summary

| Status | Summary |
|--------|---------|
| **Broken** | Backend in crash loop: `watchlist_signal_state` model missing from container. Table name mismatch (`watchlist_signal_states` vs `watchlist_signal_state`). |
| **Works** | DB, frontend, market-updater (except healthcheck), nginx. Telegram/market data pipelines run when backend is up. |
| **Risky** | Deploy script inconsistency; schema drift; no automated migrations. |

**First action:** Fix model inclusion in image and align table name/schema, then rebuild and verify.

---

## Post-Audit Fixes Applied (2026-02-02)

1. **Model aligned with AWS DB** (`backend/app/models/watchlist_signal_state.py`):
   - `__tablename__` set to `"watchlist_signal_state"` (matches existing table)
   - `symbol` as primary key (replacing `id`)
   - Added `updated_at` column
   - `evaluated_at_utc` with `server_default=func.now()` to match DB

2. **Dockerfile.aws assertion** added:
   - Build fails if `watchlist_signal_state.py` is missing from the image

**Next steps for deploy:**
```bash
# On your machine: commit and push
git add backend/app/models/watchlist_signal_state.py backend/Dockerfile.aws docs/audit/
git commit -m "fix: align WatchlistSignalState with AWS DB schema"
git push

# On AWS (SSH):
cd /home/ubuntu/automated-trading-platform
git pull origin main   # or your branch
bash scripts/aws/aws_up_backend.sh
# Or: docker compose --profile aws build --no-cache backend-aws && docker compose --profile aws up -d backend-aws
```
