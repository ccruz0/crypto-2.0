# System Map (AI-readable)

**First document for agents.** How the system is connected: components, external APIs, data flow, and dependencies.

---

## System Components

### Dashboard
- **Frontend UI** — Next.js app; served at `https://dashboard.hilovivo.com` (or localhost in dev).
- **Routes**: `/` (dashboard), monitoring, open orders, executed orders, portfolio, settings.
- **Backend dependency**: Consumes `/api/*`; requires backend and (for live data) market-updater.
- **Location**: `frontend/` in repo.

### Trading Engine
- **Signal generation** — `TradingSignals` (RSI, MAs, volume); strategy from `StrategyProfiles` (swing/intraday/scalp, conservative/aggressive).
- **Orchestration** — `SignalMonitorService`: monitor loop → signals → throttle check → alerts and/or orders.
- **Order execution** — `CryptoComTrade` places orders on Crypto.com; SL/TP creation; primary vs TP/SL roles.
- **Order sync** — `ExchangeSyncService`: sync open orders and history; resolve EXECUTED vs CANCELED from exchange (never assume “missing from open orders” = canceled).
- **Throttling** — `SignalThrottle`: price-change and cooldown; blocks duplicate alerts/trades.
- **Location**: `backend/app/services/` (signal_monitor.py, trading_signals.py, strategy_profiles.py, exchange_sync.py, signal_throttle.py, brokers/crypto_com_trade.py).

### Market Data
- **Crypto.com API** — Prices, order book, order/trade history. Backend connects directly (AWS Elastic IP whitelisted in prod).
- **Price feeds** — Used by TradingSignals and SignalMonitorService; stored/cached as needed by backend.
- **Market-updater** — Optional service that keeps market data fresh; runs in Docker (profile `aws`) on EC2.
- **Location**: Backend services + `market-updater` in docker-compose; config: `.env.aws`, `secrets/runtime.env` on EC2.

### Infrastructure
- **AWS EC2** — Single production instance (atp-rebuild-2026). Host for Nginx, Docker Compose.
- **Docker services** — Profile `aws`: backend-aws, frontend-aws, db, market-updater-aws. No `uvicorn --reload` in production.
- **Nginx** — Reverse proxy: `/` → frontend, `/api/` → backend; host-only bind (e.g. 127.0.0.1:3000, 127.0.0.1:8002).
- **Database** — PostgreSQL in Docker; not exposed publicly; backend connects via Docker network.
- **Location**: `docker-compose.yml`; runbooks in [../runbooks](../runbooks/), [../infrastructure](../infrastructure/).

### Automation
- **OpenClaw agents** — Autonomous execution; read this repo (code + `/docs`) as knowledge base.
- **GitHub Actions** — Deploy (Session Manager), Prod Health Check, optional Guard/Sentinel.
- **Schedulers / timers** — Backend scheduler for monitor loop; optional systemd timers for self-heal/health on EC2.

---

## External APIs

| API | Purpose | Config / notes |
|-----|---------|----------------|
| **Crypto.com Exchange v1** | Orders, balance, order/trade history, market data | `EXCHANGE_CUSTOM_*`, `USE_CRYPTO_PROXY`; prod: direct from EC2, IP whitelisted |
| **Telegram** | Alerts, order notifications, bot commands | Telegram bot token; backend only |
| **AWS (SSM)** | Deploy and run commands when SSH unavailable | GitHub secrets; instance ID i-087953603011543c5 for PROD |

---

## Data Flow (summary)

1. **Ingest** — Market data from Crypto.com; watchlist and config from DB.
2. **Signals** — SignalMonitorService → TradingSignals + StrategyProfiles → BUY/SELL + strategy.
3. **Gates** — Throttle (price + cooldown); alert_enabled / trade_enabled; max open orders.
4. **Actions** — Telegram alerts (if allowed); order placement via CryptoComTrade; SL/TP creation.
5. **Sync** — ExchangeSyncService: open orders + order/trade history → DB state; ORDER_EXECUTED / ORDER_CANCELED only after exchange confirmation.
6. **Output** — Dashboard API (/api/monitoring, /api/open-orders, /api/executed-orders, etc.); Telegram messages.

---

## Dependencies (critical for agents)

- **Backend ↔ DB** — PostgreSQL; migrations/schema in backend; do not expose DB publicly.
- **Backend ↔ Crypto.com** — Must have valid API key, secret, and (in prod) whitelisted EC2 IP.
- **Backend ↔ Telegram** — Bot token; single bot instance (no parallel backend with same bot in prod).
- **Frontend ↔ Backend** — `/api`; same-origin in prod via Nginx; CORS/allowed origins if different origins.
- **Deploy** — GitHub → Actions or SSH/SSM on EC2; Docker Compose `--profile aws`; no `uvicorn --reload` in prod.

---

## Where to go next

- [System overview](system-overview.md) — Same content in narrative form.
- [Runbooks](../runbooks/deploy.md) — Deploy, restart, troubleshoot.
- [Infrastructure](../infrastructure/aws-setup.md), [Docker](../infrastructure/docker-setup.md) — AWS and Docker.
- [Integrations](../integrations/crypto-api.md) — Crypto.com and APIs.
- [Operations](../operations/monitoring.md) — Monitoring and health.
- [Agent context](../agents/context.md) — How agents should work in this repo.
