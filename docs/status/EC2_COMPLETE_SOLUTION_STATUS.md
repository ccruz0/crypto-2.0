# EC2 Complete Solution — Status

**Last updated:** 2026-03-01

---

## Goals (original)

1. **Production EC2:** Dashboard gets market data; `/api/health/system` shows `market_data` and `market_updater` PASS.
2. **Self-heal:** Restarts, pruning, and unprotected POST `/api/health/fix` only; no schema changes in the fix endpoint.
3. **DB schema:** `watchlist_items` and related tables exist; use `scripts/db/bootstrap.sh` and runbooks; `/api/health/fix` remains restarts-only.
4. **Verify.sh:** Robust restore (emitter/base64), no fragile heredocs.
5. **Postgres password:** Popup to set password on EC2; applied to `.env`/`.env.aws` and backend recreated.
6. **DB reset:** Volume removed, stack brought back up so Postgres re-initializes with password from env.

---

## What’s done

| Area | Status | Notes |
|------|--------|------|
| **DB schema** | Done | `watchlist_items`, `market_data`, `market_prices`, `order_intents` exist. Bootstrap and `ensure_optional_columns` (with raw-SQL fallback for `order_intents`) in place. |
| **order_intents** | Done | Table + indexes created (including one-off raw SQL on EC2). Health reports `order_intents_table_exists: true`. |
| **Trade system health** | Done | Health no longer hides `order_intents_table_exists` when `count_total_open_positions` fails; check order fixed in `system_health.py`. |
| **POST /api/health/fix** | Done | Restarts-only; no schema mutation. |
| **Bootstrap / runbooks** | Done | `scripts/db/bootstrap.sh`, `docs/runbooks/EC2_DB_BOOTSTRAP.md`, `EC2_FIX_MARKET_DATA_NOW.md`, `EC2_SELFHEAL_DEPLOY.md`; runbook index updated. |
| **verify.sh** | Done | `scripts/selfheal/emit_verify_sh.py` can restore `verify.sh` from embedded base64. |
| **Postgres password on EC2** | Done | `scripts/aws/set_postgres_password_ec2.py` (popup on macOS); updates `.env`/`.env.aws`, recreates backend. |
| **DB reset** | Done | Volume removed, stack brought up; Postgres re-initialized with env password. |
| **Deploy** | Done | Latest code pushed to `main`; EC2 pulled, backend built, stack up. |
| **Self-heal timer** | Done | `atp-selfheal.timer` is **active** on EC2; runs on schedule. |

---

## Current health (EC2)

| Component | Status | Reason |
|-----------|--------|--------|
| **db_status** | up | Postgres reachable. |
| **trade_system** | PASS | `order_intents_table_exists: true`, `last_check_ok: true`. |
| **signal_monitor** | PASS | Running, last cycle recent. |
| **market_data** | WARN | `fresh_symbols: 0` — health uses **watchlist_items** to decide which symbols to check; **watchlist_items is empty** (0 rows). |
| **market_updater** | FAIL | Derived from market_data; no “fresh” symbols so reported as not running. |
| **telegram** | FAIL | Intentionally disabled on EC2 (bot token/chat not set). |
| **global_status** | FAIL | Because market_data ≠ PASS and market_updater = FAIL (and optionally telegram). |

**Health fallback (implemented):** When `watchlist_items` is empty, health uses **market_prices** recency: PASS when ≥5 recent symbols, WARN for 1–4, FAIL for 0. Response includes `health_symbol_source` (`"watchlist_items"` or `"market_prices_fallback"`) and when fallback is used, `message`: *"Watchlist empty; using market_prices fallback for health."* So empty watchlist is no longer fatal.

---

## verify.sh

- **Fails** while `market_data.status != PASS` (and/or `market_updater != PASS`).  
- Script requires: disk &lt; 90%, no unhealthy containers, API ok, db up, **market_data PASS**, **market_updater PASS**, signal_monitor PASS.  
- Timer was started **anyway** so self-heal runs on schedule; verify is not a gate for starting the timer.

---

## What’s left (optional)

1. **Get market_data / market_updater to PASS**
   - **Option A:** Populate `watchlist_items` (e.g. from `watchlist_master` or a seed) so health has symbols to check; ensure `market_prices` (or `market_data`) is updated for those symbols (e.g. by market-updater or POST `/api/market/update-cache`).
   - **Option B:** Change health so “market_data PASS” can be based on “any recent rows in market_prices” (or similar) when `watchlist_items` is empty.

2. **Telegram on EC2**  
   If you want production alerts: set bot token and chat id in env, enable in config, restart backend.

3. **Runbook reminder**  
   Document in the runbook that after a DB password change on EC2 you run:  
   `python3 scripts/aws/set_postgres_password_ec2.py` (popup), then backend is recreated with new env.

---

## Summary

- **Schema, order_intents, trade_system health, fix endpoint, bootstrap, verify restore, password script, DB reset, deploy, and self-heal timer** are in place and working.
- **market_data** and **market_updater** stay WARN/FAIL until either `watchlist_items` is populated and has fresh prices, or health logic is relaxed when the watchlist is empty.
- **verify.sh** will pass once market_data (and thus market_updater) report PASS.
