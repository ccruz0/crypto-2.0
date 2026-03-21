# Current Architecture Report — Automated Trading Platform

**Date:** 2026-03-15  
**Scope:** Full repository scan, implementation-based, factual only.

---

## One-Page Summary

| Aspect | Status |
|--------|--------|
| **Production runtime** | AWS EC2 (atp-rebuild-2026, i-087953603011543c5) only. Dashboard: https://dashboard.hilovivo.com |
| **Lab runtime** | AWS EC2 (atp-lab-ssm-clean, i-0d82c172235770a0d). OpenClaw only. No trading. |
| **Local** | Dev only. SignalMonitorService + scheduler + Telegram must NOT run in parallel with AWS. |
| **Order execution** | `backend/app/services/brokers/crypto_com_trade.py` → Crypto.com Exchange API. Called from `SignalMonitorService._place_order_from_signal()` and `routes_orders.place_order()`. |
| **Signal detection** | `backend/app/services/signal_monitor.py` (SignalMonitorService). Runs in backend-aws. Every 30s. |
| **Market data** | `backend/market_updater.py` (run_updater). Runs in market-updater-aws. Every 60s. Writes to DB + `market_cache.json`. |
| **Telegram** | `backend/app/services/telegram_notifier.py`. Only sends when ENV=aws. Two channels: trading (HILOVIVO3.0), ops (AWS_alerts). |
| **OpenClaw** | Separate repo (ccruz0/openclaw). Runs on LAB only. ATP backend calls it via HTTP (OPENCLAW_API_URL). Used for Notion task investigation/apply. Not in trading loop. |
| **State** | PostgreSQL (db). No Redis in prod. `market_cache.json`, `trading_config.json`, `secrets/runtime.env`. |
| **Deploy** | GitHub Actions: `deploy_session_manager.yml` (push main). SSM to PROD. `scripts/deploy_aws.sh` on EC2. |
| **Google Sheets** | Deprecated. Migrated to PostgreSQL (MIGRATION_SUMMARY.md). |

---

# Full Report

---

## A. Executive Summary

### What the system actually is today

An automated crypto trading platform that:
- Monitors watchlist coins for BUY/SELL signals (RSI, MA, volume)
- Places market orders on Crypto.com Exchange when conditions are met
- Sends Telegram alerts for signals and order lifecycle events
- Syncs order state with the exchange (open orders, history, SL/TP)
- Serves a Next.js dashboard at https://dashboard.hilovivo.com
- Integrates OpenClaw (AI agent) for Notion task investigation and code changes

### What is definitely running in AWS

| Service | Instance | Container/Process |
|---------|----------|-------------------|
| Nginx | PROD | Host process |
| backend-aws | PROD | Docker (127.0.0.1:8002) |
| frontend-aws | PROD | Docker (127.0.0.1:3000) |
| db | PROD | Docker (internal) |
| market-updater-aws | PROD | Docker |
| Prometheus, Grafana, Alertmanager, node-exporter, cadvisor, telegram-alerts | PROD | Docker (profile aws) |
| OpenClaw | LAB | Docker (172.31.3.214:8080) |

### What is definitely local/lab/dev only

- Local backend (backend, backend-dev) with `--profile local`
- Local frontend on port 3000
- OpenClaw runs on LAB only; PROD proxies `/openclaw/` to LAB private IP

### What OpenClaw is actually doing today

- **Role:** AI agent for Notion task workflow (investigation, apply changes, verification)
- **Location:** LAB instance (atp-lab-ssm-clean). Image: `ghcr.io/ccruz0/openclaw:latest`
- **ATP integration:** Backend calls `OPENCLAW_API_URL` (default `http://172.31.3.214:8080`) via `openclaw_client.send_to_openclaw()` for:
  - Bug investigations (`_apply_via_openclaw`)
  - Documentation tasks
  - Triage notes
  - Solution verification
- **Not in production trading loop:** OpenClaw does not place orders, read exchange data, or control trading.

### Production-critical path

1. **Deploy:** Push to main → `deploy_session_manager.yml` → SSM to PROD → `scripts/deploy_aws.sh` → `docker compose --profile aws up -d`
2. **Trading:** SignalMonitorService (backend-aws) → calculate_trading_signals → CryptoComTrade.place_market_order → Crypto.com API
3. **Alerts:** SignalMonitorService → telegram_notifier.send_message (only when ENV=aws)
4. **Sync:** ExchangeSyncService (backend-aws) → exchange API → DB updates → lifecycle events

---

## B. Runtime Topology

### Services

| Service | Profile | Port | Purpose |
|---------|---------|------|---------|
| db | local, aws | internal 5432 | PostgreSQL |
| backend | local | 8002 | FastAPI, SignalMonitor, ExchangeSync, Telegram, Scheduler |
| backend-dev | local | 8002 | Hot-reload dev |
| backend-aws | aws | 127.0.0.1:8002 | Production backend |
| backend-aws-canary | aws | 127.0.0.1:8003 | Canary (restart: no) |
| market-updater | local | — | Market data worker |
| market-updater-aws | aws | — | Market data worker (PROD) |
| frontend | local | 3000 | Next.js dev |
| frontend-aws | aws | 127.0.0.1:3000 | Production frontend |
| prometheus | aws | 127.0.0.1:9090 | Metrics |
| grafana | aws | 127.0.0.1:3001 | Dashboards |
| alertmanager | aws | 127.0.0.1:9093 | Alerts |
| telegram-alerts | aws | — | Prometheus → Telegram |
| node-exporter | aws | 127.0.0.1:9100 | Host metrics |
| cadvisor | aws | 127.0.0.1:8080 | Container metrics |
| openclaw | — | 8080 (LAB) | docker-compose.openclaw.yml (LAB only) |

### Connections

- **Nginx (PROD):** `/` → frontend-aws:3000, `/api/` → backend-aws:8002, `/openclaw/` → LAB 172.31.3.214:8080
- **Backend → DB:** `postgresql://trader@db:5432/atp`
- **Backend → Crypto.com:** Direct from AWS Elastic IP (no VPN/proxy in prod)
- **Backend → OpenClaw:** HTTP to `OPENCLAW_API_URL` (LAB private IP when configured)
- **Backend → Telegram:** `https://api.telegram.org/bot{token}/sendMessage`
- **GitHub:** Webhook `workflow_run` → `/api/github/webhook` (deploy success/failure, smoke check, Notion task updates)

### Dependencies

| Dependency | Used by |
|------------|---------|
| GitHub | Deploy (push main), health check, fix_openclaw_504, dashboard-data-integrity |
| AWS | EC2 PROD/LAB, SSM, EICE for deploy and fix scripts |
| Crypto.com API | Orders, balance, history |
| Telegram API | Alerts, bot commands |
| OpenClaw (LAB) | Agent task execution (optional) |
| Notion API | Task system, agent scheduler (optional) |

### Ports and processes

- **PROD host:** nginx 80/443, Docker bindings 127.0.0.1 only
- **LAB host:** OpenClaw 8080 (no public IP)
- **Backend:** Gunicorn + Uvicorn workers (2 workers in prod)
- **Market updater:** Single process, `python3 run_updater.py`

---

## C. Trading Flow

### Signal detection → order placement → state update → alerting

| Phase | File/Module | Description |
|-------|-------------|-------------|
| 1. Market data | `backend/market_updater.py` | Fetches OHLCV, RSI, MA, volume. Writes to DB + `market_cache.json`. Every 60s. |
| 2. Signal monitor | `backend/app/services/signal_monitor.py` | `_monitor_signals()` every 30s. For each watchlist item: |
| 2a. Signals | `backend/app/services/trading_signals.py` | `calculate_trading_signals()` → BUY/SELL/WAIT |
| 2b. Strategy | `backend/app/services/strategy_profiles.py` | Resolves strategy type and risk |
| 2c. Throttle | `backend/app/services/throttle_service.py` (optional) | `should_emit_signal()` — price change + cooldown |
| 3. Alert | `backend/app/services/telegram_notifier.py` | `send_buy_alert()` / `send_sell_alert()` (if alert_enabled, throttle allows) |
| 4. Order | `backend/app/services/brokers/crypto_com_trade.py` | `place_market_order()` — real execution path |
| 4b. Manual order | `backend/app/api/routes_orders.py` | `POST /api/orders/place` — same trade_client |
| 5. Sync | `backend/app/services/exchange_sync.py` | `sync_orders()` every 5s. Resolves EXECUTED/CANCELED from exchange history |
| 6. Lifecycle | `backend/app/services/signal_monitor.py` | `_emit_lifecycle_event()` → Telegram, DB |

### Source of truth

- **Orders:** Exchange API (order history, trade history). DB is cache; "Order not found in Open Orders" ≠ canceled until exchange confirms.
- **Signals:** `calculate_trading_signals()` + `WatchlistItem` config
- **Strategy:** `trading_config.json` (persisted in `aws_trading_config_data` volume)

### Real vs theoretical execution paths

- **Real:** `SignalMonitorService._place_order_from_signal()` → `trade_client.place_market_order()` (services/signal_monitor.py)
- **Real:** `routes_orders.place_order()` → `trade_client.place_market_order()` (manual/API)
- **Duplicate/dead:** `backend/app/api/signal_monitor.py` — contains a second `SignalMonitorService` class. **Nothing imports from it.** All code uses `app.services.signal_monitor`. This file is dead code.

---

## D. Notification Flow

### Telegram alert generation

- **Entry point:** `TelegramNotifier.send_message()` in `backend/app/services/telegram_notifier.py`
- **Guard:** Only sends when `origin="AWS"` (or runtime ENV=aws). Local/test blocks sends.
- **Channels:**
  - `chat_destination="trading"` → TELEGRAM_CHAT_ID_TRADING (ATP Alerts)
  - `chat_destination="ops"` → TELEGRAM_CHAT_ID_OPS (AWS_alerts)

### Alert types

| Source | Type | chat_destination |
|--------|------|------------------|
| SignalMonitorService | BUY/SELL signal | trading |
| SignalMonitorService | Order lifecycle | trading |
| system_alerts | Health, anomalies | ops |
| daily_summary | Daily report | trading |
| sl_tp_checker | SL/TP reminders | trading |
| github_webhook | Deploy success/failure | (agent_telegram_approval default chat) |

### Deduplication and throttling

- **Duplicate window:** `DUPLICATE_WINDOW_SECONDS = 60` — same message hash within 60s is suppressed
- **Cooldown:** `_TELEGRAM_COOLDOWN_UNTIL_TS` — global cooldown can block sends
- **Signal throttle:** `should_emit_signal()` — min price change + cooldown (fixed 60s per ALERTAS_Y_ORDENES_NORMAS.md)
- **Kill switch:** DB-backed; can disable all Telegram sends

### Repeated alerts

- Multiple callers can trigger similar alerts (e.g. signal_monitor + manual check)
- Throttle and duplicate window reduce but do not eliminate overlap
- `record_signal_event()` logs to `signal_throttle` table for audit

---

## E. OpenClaw Usage Today

### OpenClaw components in ATP repo

| Path | Purpose |
|------|---------|
| `docs/openclaw/` | Runbooks, architecture, prompts |
| `scripts/openclaw/` | Deploy, fix 504, diagnosis, token setup |
| `docker-compose.openclaw.yml` | LAB-only compose for OpenClaw |
| `openclaw/` (if present) | Wrapper Dockerfile, reference — not the app source |
| `backend/app/services/openclaw_client.py` | HTTP client to OpenClaw gateway |
| `backend/app/services/agent_callbacks.py` | Uses OpenClaw for apply/validate/verify |

### Environments

- **LAB:** Primary. OpenClaw runs in Docker on atp-lab-ssm-clean. No prod secrets.
- **PROD:** Nginx proxies `/openclaw/` to LAB. UI at https://dashboard.hilovivo.com/openclaw/ (Basic Auth).
- **Local:** Not deployed. OPENCLAW_API_URL can point to LAB for testing.

### Production loop

- **No.** OpenClaw is not in the trading loop. It is used for:
  - Notion task investigation (bug, doc, triage)
  - Apply changes (code, docs)
  - Solution verification
  - Cursor handoff / report generation

### Permissions and integrations

- **ATP → OpenClaw:** HTTP POST to `/v1/responses`. Bearer token (OPENCLAW_API_TOKEN).
- **OpenClaw → ATP:** Mounts ATP repo read-only at `/home/node/.openclaw/workspace/atp`
- **OpenClaw → GitHub:** Clone, branch, PR (via PAT/deploy key). No prod secrets.
- **OpenClaw → Cursor:** ACP default agent (e.g. codex) for sessions

### Role

- **Developer/operator tool:** Runs investigations, applies patches, generates reports. Not a trading supervisor.

---

## F. Infrastructure and Deployment

### AWS instances

| Role | Name | Instance ID | Private IP | Public IP |
|------|------|-------------|------------|-----------|
| PROD | atp-rebuild-2026 | i-087953603011543c5 | 172.31.32.169 | 52.220.32.147 |
| LAB | atp-lab-ssm-clean | i-0d82c172235770a0d | 172.31.3.214 | varies/none |

**Source:** `docs/runbooks/INSTANCE_SOURCE_OF_TRUTH.md`

### Docker / Compose

- **Main:** `docker-compose.yml` — profiles `local` and `aws`
- **OpenClaw:** `docker-compose.openclaw.yml` — LAB only, name `openclaw-lab`
- **AWS profile:** `docker compose --profile aws up -d`

### Deployment scripts

| Script | Purpose |
|--------|---------|
| `scripts/deploy_aws.sh` | Canonical deploy on EC2: git reset, render runtime.env, compose up |
| `scripts/aws/render_runtime_env.sh` | Renders secrets/runtime.env from SSM/env |
| `scripts/openclaw/deploy_openclaw_lab_from_mac.sh` | Deploy OpenClaw to LAB from Mac |
| `scripts/openclaw/fix_504_via_eice.sh` | Fix OpenClaw 504 via EC2 Instance Connect |

### Environment separation

| Env | Files | Use |
|-----|-------|-----|
| local | .env, .env.local | Dev, TRADING_ENABLED=false, RUN_TELEGRAM=false |
| aws | .env, .env.aws, secrets/runtime.env | Prod. No .env.local. |
| lab | .env.lab | OpenClaw on LAB |

### GitHub workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| deploy_session_manager.yml | push main, manual | Deploy to PROD via SSM |
| deploy.yml | manual | Legacy SSH deploy |
| prod-health-check.yml | 6h, manual | Curl /api/health |
| fix_openclaw_504.yml | manual, cron 06:00/18:00 UTC | Fix OpenClaw 504 |
| dashboard-data-integrity.yml | — | Data integrity checks |
| restart_nginx.yml | manual | Restart nginx via SSM |
| disable_all_trades.yml | — | Disable trades |
| aws-runtime-guard.yml, aws-runtime-sentinel.yml | push, daily | Runtime verification |

---

## G. State and Persistence

### Databases

- **PostgreSQL:** Primary store. Tables include: watchlist_items, exchange_orders, market_price, market_data, signal_throttle, telegram_messages, trade_signals, etc.
- **Connection:** `DATABASE_URL` from env. Backend uses `db:5432` (Docker network).

### Files

| Path | Purpose |
|------|---------|
| `market_cache.json` | Market data cache (MARKET_CACHE_PATH, default /tmp) |
| `trading_config.json` | Strategy config (TRADING_CONFIG_PATH=/data/trading_config.json) |
| `secrets/runtime.env` | Runtime secrets (Telegram, API keys, etc.) |
| `secrets/telegram_key` | Decryption key for encrypted Telegram token |
| `logs/` | Application logs (mounted in backend-aws) |
| `backend/ai_runs/` | Agent run artifacts |

### Caches

- **No Redis in production.** References in .env.example (REDIS_URL) appear unused in critical paths.
- **In-memory:** `TelegramNotifier.recent_messages`, `SignalMonitorService.last_signal_states`, etc.

### Logs

- Docker json-file driver for containers
- Prometheus scrapes backend, market-updater, node-exporter, cadvisor

### Trade/signal/dashboard state

| State | Location |
|-------|----------|
| Orders | PostgreSQL (exchange_orders), source of truth: exchange API |
| Signals | PostgreSQL (trade_signals, signal_throttle) |
| Watchlist | PostgreSQL (watchlist_items, watchlist_master) |
| Strategy | trading_config.json (volume) |
| Dashboard | Reads from API; no separate client-side persistence |

---

## H. Mismatches and Risks

### Code vs docs

- **docker-compose.yml** comment on market-updater-aws: "Alerts are generated here (signal_monitor)" — misleading. Alerts are generated by SignalMonitorService in backend-aws. Market-updater only updates market data.
- **README** badges point to `crypto-2.0` repo; this repo is `automated-trading-platform` (may be fork/rename).
- **api/signal_monitor.py** — duplicate, unused. All imports use `app.services.signal_monitor`.

### Duplicated logic

- **SignalMonitorService:** Two definitions (services + api). Only services is used.
- **Order placement:** `_place_order_from_signal` (signal_monitor) and `routes_orders.place_order` both use trade_client. Intended (auto vs manual).

### Dead code / stale docs

- `backend/app/api/signal_monitor.py` — dead (no imports)
- `backend/app/api/routes_dashboard.py.current`, `routes_dashboard.py.bak` — backup files in tree
- Google Sheets references in README_MIGRATION.md — historical; migration done

### Operational blind spots

- **SSM ConnectionLost** on PROD — runbooks exist but SSM may be unreliable
- **OpenClaw 504** — depends on PROD→LAB connectivity; fix_504 workflow runs 2x/day
- **Market updater vs backend** — if market-updater fails, SignalMonitorService still runs but uses stale DB/cache data

### Fragile areas

- **Single PROD instance** — no failover
- **OpenClaw on LAB** — proxy from PROD; LAB down → /openclaw/ fails
- **Secrets** — runtime.env, telegram_key, SSM parameters; rotation is manual

---

## I. Migration Readiness for Mac Mini OpenClaw

### Safe to move to Mac Mini

| Function | Notes |
|----------|-------|
| OpenClaw UI | Run OpenClaw locally; no trading. Would need VPN or tunnel for ATP backend to reach it. |
| Cursor/ACP sessions | OpenClaw can run on Mac Mini; ACP target can point to local. |
| Notion task investigation | If backend can reach Mac Mini (e.g. ngrok, tailscale), OPENCLAW_API_URL can point there. |

### Should stay in AWS

| Function | Reason |
|----------|--------|
| Trading (SignalMonitor, orders) | Requires stable IP for Crypto.com whitelist, 24/7 uptime |
| Telegram bot | Single webhook; conflict if run in two places |
| Exchange sync | Must run where trading runs |
| Dashboard (frontend/backend) | Production user access |

### Blocking dependencies

- **OPENCLAW_API_URL:** Backend must reach OpenClaw. Mac Mini needs stable URL (tunnel, VPN, or dynamic DNS).
- **ATP repo mount:** OpenClaw expects workspace at `/home/node/.openclaw/workspace/atp`. Mac Mini path would differ.
- **Token/auth:** gateway token, Basic Auth for /openclaw/ — need to be consistent.

### Security boundaries

- **Mac Mini must NOT:** Hold prod DB credentials, exchange keys, Telegram prod token
- **Mac Mini may:** Run OpenClaw for dev/triage; receive HTTP from backend if network path exists
- **Recommendation:** Mac Mini as optional dev/staging OpenClaw. Prod agent tasks can stay on LAB or move to Mac Mini only if connectivity and security are verified.

---

# System Inventory Table

| Component | Purpose | Status | Environment | Main Files | Dependencies | Risk Notes |
|-----------|----------|--------|-------------|------------|--------------|------------|
| backend-aws | API, SignalMonitor, ExchangeSync, Telegram, Scheduler | Active | AWS PROD | app/main.py, services/signal_monitor.py | db, Crypto.com, Telegram | Single instance |
| market-updater-aws | Market data fetch | Active | AWS PROD | market_updater.py, run_updater.py | db, Crypto.com API | Stale data if down |
| frontend-aws | Dashboard UI | Active | AWS PROD | frontend/ | backend API | — |
| db | PostgreSQL | Active | AWS PROD | docker/postgres | — | No public port |
| SignalMonitorService | Signal detection, order creation | Active | backend-aws | services/signal_monitor.py | trading_signals, trade_client, telegram | — |
| ExchangeSyncService | Order sync | Active | backend-aws | exchange_sync.py | trade_client, db | — |
| TradingScheduler | Daily summary, SL/TP check | Active | backend-aws | scheduler.py | daily_summary, sl_tp_checker | — |
| TelegramNotifier | Alerts | Active | backend-aws | telegram_notifier.py | Telegram API | Only when ENV=aws |
| CryptoComTrade | Order execution | Active | backend-aws | brokers/crypto_com_trade.py | Crypto.com API | — |
| openclaw_client | OpenClaw HTTP client | Active | backend-aws | openclaw_client.py | OPENCLAW_API_URL | Optional |
| OpenClaw container | AI agent UI + gateway | Active | AWS LAB | docker-compose.openclaw.yml | ATP repo (read-only) | 504 if LAB/proxy down |
| api/signal_monitor.py | Duplicate SignalMonitorService | Dead | — | api/signal_monitor.py | — | Remove |
| Google Sheets | Legacy | Deprecated | — | — | — | Migrated to DB |
| agent_scheduler | Notion task scanner | Active (if configured) | backend-aws | agent_scheduler.py | NOTION_API_KEY | Optional |
| Prometheus/Grafana | Observability | Active | AWS PROD | scripts/aws/observability/ | — | — |

---

# Fact vs Assumption

## Confirmed from code

- backend-aws starts SignalMonitorService, ExchangeSyncService, TradingScheduler, Telegram commands
- Order execution via `trade_client.place_market_order()` in crypto_com_trade.py
- Telegram sends only when ENV=aws (guard in send_message)
- OpenClaw runs on LAB; PROD proxies /openclaw/ to LAB
- deploy_session_manager.yml is default deploy on push to main
- api/signal_monitor.py is never imported
- Google Sheets replaced by PostgreSQL (signal_writer, MIGRATION_SUMMARY)
- market_cache.json written by market_updater, read by routes_market

## Inferred (not directly verified)

- PROD SSM status (docs say ConnectionLost; may change)
- Actual Telegram channel IDs and token setup
- Crypto.com API whitelist configuration
- Whether OPENCLAW_API_TOKEN is set in prod secrets

## Cannot confirm from repo

- Live state of containers on PROD/LAB
- Whether fix_openclaw_504 workflow succeeds
- Exact nginx config on PROD host
- Whether agent_scheduler/Notion integration is enabled

---

# Recommended Next Steps

1. **Remove dead code:** Delete `backend/app/api/signal_monitor.py` (unused duplicate).
2. **Fix docker-compose comment:** Correct market-updater-aws comment — alerts come from backend, not market-updater.
3. **Document OpenClaw role:** Add a short "OpenClaw is not in the trading loop" note to main README.
4. **Audit backup files:** Remove or archive `routes_dashboard.py.current`, `routes_dashboard.py.bak`.
5. **Clarify repo identity:** Resolve crypto-2.0 vs automated-trading-platform naming in badges and docs.
6. **Mac Mini prep:** Document network options (tailscale, ngrok) if OpenClaw will run on Mac Mini.
7. **State diagram:** Add a single "Production data flow" diagram (signal → order → sync → alert).
8. **Secrets inventory:** List all secrets (SSM, runtime.env, telegram_key) and rotation procedures.
9. **Health check coverage:** Ensure prod-health-check validates market_updater and signal_monitor.
10. **Runbook index:** Keep RUNBOOK_INDEX.md updated as the single ops entry point.

---

# Target Architecture Recommendations

## a) Current AWS setup cleanup

- Consolidate on `deploy_session_manager.yml`; treat `deploy.yml` as legacy-only.
- Remove dead `api/signal_monitor.py`.
- Standardize instance references (use INSTANCE_SOURCE_OF_TRUTH.md).
- Add a simple "what runs where" diagram to docs/architecture/.

## b) Future hybrid: AWS production + Mac Mini OpenClaw

- **AWS:** Keep trading, dashboard, Telegram, exchange sync, DB.
- **Mac Mini:** Optional OpenClaw for dev/triage. Require:
  - Stable URL (e.g. tailscale) for OPENCLAW_API_URL
  - No prod secrets on Mac Mini
  - Clear docs on when to use LAB vs Mac Mini
- **LAB:** Can remain as primary OpenClaw host until Mac Mini is validated.

---

*End of report*
