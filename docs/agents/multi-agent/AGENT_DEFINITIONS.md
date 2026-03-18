# Multi-Agent Definitions

Each agent has a clear purpose, scope, exclusions, owned files, typical issues, output format, and validation checklist.

---

## 1. Telegram and Alerts Agent

**Status:** Implemented

### Purpose
Analyze and diagnose issues related to Telegram alert delivery, throttling, deduplication, kill switch, channel configuration, and notification flow.

### Scope
- `backend/app/services/telegram_notifier.py`
- `backend/app/services/telegram_commands.py`
- `backend/app/services/telegram_health.py`
- `backend/app/services/alert_emitter.py`
- `backend/app/services/signal_throttle.py` (alert throttle)
- `docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md`
- `docs/monitoring/` (alert-related)
- `secrets/runtime.env` (TELEGRAM_*, never log values)

### Exclusions
- Does NOT change Telegram send logic
- Does NOT modify production RUN_TELEGRAM or credentials
- Does NOT suggest disabling alerts without explicit operator approval

### Typical issues
- Alerts not being sent
- Duplicate / repeated alerts
- Missing alerts after deploy
- Approval noise (too many pings)
- Wrong channel (trading vs ops)
- Kill switch blocking sends
- Throttle/dedup too aggressive
- TELEGRAM_CHAT_ID misconfiguration
- Docs vs code mismatches (runbook outdated)

### Expected output
Structured note per [SHARED_OUTPUT_SCHEMA.md](SHARED_OUTPUT_SCHEMA.md). "Proposed Minimal Fix" must reference exact env vars, file paths, and config keys.

### Validation checklist
- [ ] Cited telegram_notifier.py or telegram_commands.py
- [ ] Checked RUN_TELEGRAM, ENVIRONMENT, chat_id resolution
- [ ] No suggestion to log or expose tokens
- [ ] Cursor Patch Prompt is safe (no credential changes)

---

## 2. Execution and State Agent

**Status:** Implemented

### Purpose
Analyze order lifecycle, exchange sync, state consistency, and execution flow. Diagnose why orders appear missing, stuck, or inconsistent with exchange.

### Scope
- `backend/app/services/exchange_sync.py`
- `backend/app/services/signal_monitor.py` (order creation, lifecycle events)
- `backend/app/services/brokers/crypto_com_trade.py`
- `backend/app/models/exchange_order.py`
- `docs/ORDER_LIFECYCLE_GUIDE.md`
- `docs/SYSTEM_MAP.md`
- `docs/LIFECYCLE_EVENTS_COMPLETE.md`

### Exclusions
- Does NOT place or cancel orders
- Does NOT change sync logic or order state transitions
- Does NOT assume "order not in open orders" = canceled (must use exchange history)

### Typical issues
- Order not found in open orders (resolve via order_history only)
- EXECUTED vs CANCELED confusion
- Exchange vs DB vs dashboard mismatches
- Lifecycle state issues (SL/TP, rendering)
- Sync messages misleading or stale
- State reconciliation / dashboard wrong state

### Expected output
Structured note per [SHARED_OUTPUT_SCHEMA.md](SHARED_OUTPUT_SCHEMA.md). "Confirmed Facts" must cite exchange API behavior or code paths.

### Validation checklist
- [ ] Cited exchange_sync or order lifecycle docs
- [ ] Did not assume missing = canceled without exchange confirmation
- [ ] Proposed fix does not change order placement logic
- [ ] Cursor Patch Prompt is read-only or doc-only where possible

---

## 3. Trading Signal Agent

**Status:** Scaffolded

### Purpose
Analyze signal generation, strategy profiles, watchlist config, and signal throttle. No order placement.

### Scope
- `backend/app/services/trading_signals.py`
- `backend/app/services/strategy_profiles.py`
- `backend/app/services/signal_monitor.py` (signal detection only)
- `backend/app/services/throttle_service.py`
- `backend/app/models/watchlist.py`
- `trading_config.json`

### Exclusions
- Does NOT create or modify orders
- Does NOT change trade_enabled or alert_enabled without approval
- Does NOT modify signal calculation formulas without review

### Typical issues
- Wrong BUY/SELL signal
- Strategy mismatch
- Throttle too strict/loose
- Watchlist config errors

---

## 4. System Health Agent

**Status:** Scaffolded

### Purpose
Analyze market updater, backend health, nginx, SSM, disk, and observability. Diagnose 502, 504, ConnectionLost.

### Scope
- `backend/market_updater.py`
- `backend/run_updater.py`
- `scripts/aws/`
- `docs/runbooks/`
- `docs/aws/`
- Health endpoints, Prometheus, Grafana config

### Exclusions
- Does NOT restart services without approval
- Does NOT change nginx or firewall without runbook
- Does NOT modify production env files

### Typical issues
- 502/504 on dashboard
- Market data stale
- SSM ConnectionLost
- Disk full
- Backend not responding

---

## 5. Docs and Rules Agent

**Status:** Scaffolded (uses existing documentation callback)

### Purpose
Audit and improve runbooks, architecture docs, cursor rules. No runtime changes.

### Scope
- `docs/`
- `.cursor/rules/`
- `README.md`, `DEPLOYMENT_POLICY.md`

### Exclusions
- Does NOT change code
- Does NOT modify secrets or env
- Does NOT suggest deployment without runbook

### Typical issues
- Outdated runbook
- Missing doc
- Incorrect architecture description
- Cursor rule too broad/narrow

---

## 6. Architecture and Refactor Agent

**Status:** Scaffolded

### Purpose
Identify dead code, duplication, tech debt, and structural improvements. Analysis only; no automatic refactors.

### Scope
- Codebase structure
- Duplicate logic
- Dead code
- Deprecated patterns
- `docs/audit/`

### Exclusions
- Does NOT refactor without approval
- Does NOT remove code without verification it is unused
- Does NOT change trading-critical paths

### Typical issues
- Dead code (e.g. api/signal_monitor.py)
- Duplicate implementations
- Stale docs
- Fragile dependencies
