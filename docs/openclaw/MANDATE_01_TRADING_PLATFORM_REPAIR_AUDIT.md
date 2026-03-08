# Mandate #1: Trading Platform Repair Audit (Read-only)

Pegar este texto en la UI de OpenClaw para ejecutar el primer mandato formal.

---

## Goal

- Produce a prioritized fix plan for Hilovivo trading platform stability and safety.

## Scope

- **Repository:** automated-trading-platform
- **Focus areas:**
  - Order lifecycle: creation, SL/TP placement, updates, cancels, sold logic
  - Kill switch / global safety controls
  - Watchlist state consistency (dedupe, toggles, persistence)
  - Telegram command handling and deduplication
  - Scheduler and monitoring services interactions
- Nginx/OpenClaw embedding does not matter for this mandate.

## Rules

- **Read-only only.** Do not modify files. Do not run destructive commands.
- Do not print or request secrets.
- If you need runtime data, ask for the exact command and why.

## Deliverable format

1. **System map** (key modules and data flows)
2. **Top 10 failure modes** (with file paths + functions + why)
3. **Repro steps** for each (best-effort from code)
4. **Fix plan:**
   - **Phase 0:** safety guards (kill switch, idempotency, race conditions)
   - **Phase 1:** correctness (orders, SL/TP, state)
   - **Phase 2:** observability (logs/metrics, alerts, dashboards)
5. **"First PR" suggestion:** the smallest safe change that removes the biggest risk

## Start by scanning these paths

> **Important:** The paths below are directories, not files. List each directory first (`ls` or equivalent), then read the concrete `.py` files inside. Do NOT attempt to read a directory path directly — that causes EISDIR errors.

- `backend/app/services/` — list first, then read key files: `signal_monitor.py`, `signal_order_orchestrator.py`, `exchange_sync.py`, `telegram_commands.py`, `telegram_notifier.py`, `trading_signals.py`, `strategy_profiles.py`, `signal_throttle.py`
- `backend/app/api/` — list first, then read: `routes_orders.py`, `routes_monitoring.py`, `routes_control.py`, `routes_market.py`
- `backend/app/models/` — list first, then read: `exchange_order.py`, `trade_signal.py`, `order_intent.py`, `watchlist.py`, `telegram_state.py`
- `scripts/` — list first, then read relevant `.sh` files
- `docker-compose.yml` and `nginx/dashboard.conf` only if they influence runtime behavior

---

*Mandate #2 can be oriented to "first PR" (with edit permission) and clear acceptance criteria.*
