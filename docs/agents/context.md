# Agent Context (AI-readable)

How an autonomous agent (Cursor, OpenClaw, or other tools) should work inside this repository: purpose, critical areas, and where to find things.

---

## Purpose of the project

- **Automated Trading Platform** — Monitors market signals, sends Telegram alerts, places and tracks orders on Crypto.com Exchange.
- **Production** — Single AWS EC2 instance (atp-rebuild-2026); dashboard at https://dashboard.hilovivo.com. Local setup is for development only; do not run a second live trading/alert stack in parallel with production.

---

## Main system components (quick reference)

| Component | Location | Role |
|-----------|----------|------|
| **Dashboard (frontend)** | `frontend/` | Next.js UI; consumes `/api/*`. |
| **Backend API** | `backend/app/api/` | Routes for health, monitoring, orders, portfolio, etc. |
| **Trading engine** | `backend/app/services/` | SignalMonitorService, TradingSignals, ExchangeSyncService, CryptoComTrade, TelegramNotifier, SignalThrottle. |
| **Data models** | `backend/app/models/` | WatchlistItem, ExchangeOrder, SignalThrottleState, TradeSignal, etc. |
| **Infrastructure** | `docker-compose.yml`, `scripts/`, `nginx/` | Docker profiles `local` / `aws`; deploy and runbooks. |
| **Documentation** | `docs/` | Architecture, runbooks, infrastructure, integrations, operations, agents, decision-log. |

---

## Critical modules — do not break

1. **Order lifecycle and sync**
   - `ExchangeSyncService`: must resolve EXECUTED vs CANCELED from exchange order/trade history only. **Never** assume “order not in open orders” = canceled.
   - Order states: CREATED → EXECUTED (FILLED) or CANCELED; ORDER_EXECUTED / ORDER_CANCELED only after confirmation.

2. **Single production runtime**
   - Only one backend running SignalMonitorService + scheduler + Telegram bot for production. No parallel local prod; no duplicate alerts/orders.

3. **Production runtime rules**
   - No `uvicorn --reload` in production (use Gunicorn as in docker-compose).
   - Backend and frontend bind to 127.0.0.1 on host; Nginx in front; DB not exposed.

4. **Throttling and gates**
   - SignalThrottle and trade gates (max open orders, cooldown, trade_enabled) must remain enforced; changing them can cause duplicate orders or alert spam.

5. **Crypto.com and Telegram**
   - Exchange: valid credentials and (in prod) whitelisted EC2 IP. Telegram: one bot token per environment; no conflicting instances.

---

## How agents should read the repository

1. **Start here** — [System map](../architecture/system-map.md) (components, APIs, data flow, dependencies).
2. **Then** — [System overview](../architecture/system-overview.md); [Agent context](context.md) (this file); [Task system](task-system.md).
3. **Before changing behavior** — Check [Decision log](../decision-log/README.md) for existing decisions and [runbooks](../runbooks/deploy.md) for procedures.
4. **When modifying** — Prefer minimal, targeted changes; update docs if you change contracts, runbooks, or critical behavior.
5. **After changes** — Run relevant tests; use runbooks to validate (e.g. deploy, restart, monitoring).

---

## Where documentation lives

- **Architecture** — [docs/architecture/](../architecture/) (system-map.md, system-overview.md).
- **Runbooks** — [docs/runbooks/](../runbooks/) (deploy.md, restart-services.md, dashboard_healthcheck.md, etc.); index: [docs/aws/RUNBOOK_INDEX.md](../aws/RUNBOOK_INDEX.md).
- **Infrastructure** — [docs/infrastructure/](../infrastructure/) (aws-setup.md, docker-setup.md).
- **Integrations** — [docs/integrations/](../integrations/) (crypto-api.md).
- **Operations** — [docs/operations/](../operations/) (monitoring.md).
- **Agents** — [docs/agents/](../agents/) (context.md, task-system.md, README.md).
- **Decisions** — [docs/decision-log/](../decision-log/README.md).
- **Root** — [README.md](../../README.md) (project overview and Documentation section).

---

## Where configuration lives

- **Environment** — `.env`, `.env.local` (dev), `.env.aws` (prod); `secrets/runtime.env` on EC2 (not in repo).
- **Docker** — Root `docker-compose.yml`; profiles `local` and `aws`.
- **Nginx** — Host config (path on EC2; see runbooks); repo may have `nginx/` or `scripts/` references.
- **GitHub** — Secrets/variables for deploy (EC2_HOST, EC2_KEY, API_BASE_URL, AWS_*); see [AWS quick reference](../aws/AWS_PROD_QUICK_REFERENCE.md).

---

## Single source of truth

- **GitHub** — Code and all technical documentation (this repo).
- **Notion** — Projects, tasks, ideas, business ops (references this repo when needed).
- **Cursor** — Development (edits code and docs here).
- **OpenClaw** — Autonomous execution (reads this repo as knowledge base).

Agents must use this repository and `/docs` as the canonical source; do not rely on conversation-only or external docs for technical truth.
