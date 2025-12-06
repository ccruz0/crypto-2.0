## 2025-11-16
- Process rule: Before starting any new work, read `docs/decisions-log.md` and append a new dated section at the top for any new decisions/rules/conventions; never rewrite or reorder past entries.
- Validation rule: For LIVE_TRADING endpoint checks, prefer `scripts/test_live_toggle.sh`; default to `READ_ONLY=1` in shared/CI environments and require explicit intent to toggle.

## 2025-11-16
- Backend LIVE_TOGGLE and LIVE_STATUS endpoints now always return JSON; success format `{ ok:true, success:true, live_trading_enabled, mode, message }` and error format `{ ok:false, success:false, error, mode }`. No HTML or empty bodies.
- Frontend `toggleLiveTrading` reads the body once (text → safe JSON.parse fallback) to prevent “body stream already read”.
- Nginx: enforce `location = /api/health` proxy to backend `__ping` before general `/api` block; avoid error-page interception for JSON API.
- Unified SSH helpers finalized in `scripts/ssh_key.sh`; all scripts must use `ssh_cmd`, `scp_cmd`, `rsync_cmd`. No raw `ssh/scp/rsync`, `.pem`, `ssh-agent`, or `ssh-add`.
- Added DRY_RUN to `start-aws-stack.sh` and `start-stack-and-health.sh` with full command preview, resolved SERVER/path printout, and skipped sleeps.
- Added validators: `scripts/test_ssh_system.sh` (strict checks), `scripts/pre_deploy_check.sh` (runs validator + DRY_RUN sims), `scripts/simulate_deploy.sh` (end-to-end dry-run), `scripts/deploy_production.sh` (requires explicit confirmation).
- Health monitoring and domain setup scripts updated to use helper functions and avoid raw SSH; systemd timers validated.
- Rule: Never change `/api` proxy shape, `/api/health` exact-match, or the unified SSH helper contract without updating documentation and validators.

## 2025-11-15
- Frontend API timeouts tuned by endpoint:
  - `/signals`: 15s, with circuit breaker and non-failure timeouts to avoid tripping on slowness.
  - `/market/top-coins-data`: 60s, `/orders/history`: 60s, `/dashboard/state`: 45s.
  - Watchlist alert updates: 15s; custom coin add: 30s.
- Circuit breaker for `/signals` endpoint: failure counts, auto-reset after 30s, timeouts don’t count as failures; deduplicated error logs to prevent noise.
- Fallback behavior for `/signals` during circuit open: frontend returns `null` and backs off; retries with exponential backoff on non-circuit errors.
- `getCurrentPrice` explicitly handles 400 (invalid symbol) by returning `0` without logging errors to reduce noise.

## 2025-11-14
- Dashboard source consolidation: prefer `/dashboard/state` (Postgres-backed) over `/assets` (outdated SQLite) for portfolio and value.
- “Bot status” on dashboard returns optimistic running state on transient errors to avoid false “stopped” UI when backend is momentarily unavailable.
- Added more resilient error logging paths with suppression windows for repeated identical messages.

## 2025-11-13
- Watchlist settings persistence rule: Only symbols with `trade_enabled === true` qualify for fast refresh cadence; slower cadence for non-trading items.
- Watchlist `saveCoinSettings`:
  - Sends nulls explicitly for `sl_percentage`/`tp_percentage`.
  - If symbol exists: merge updates; otherwise create with defaults (exchange `CRYPTO_COM`).
  - Error specialization (404 not found, 502 bad gateway, 500) with actionable messages.

## 2025-11-12
- Order history pagination: `GET /orders/history?limit=&offset=` returns `{ orders, count, total?, has_more? }`.
- Quick order API: `POST /orders/quick` requires `{symbol, side, price, amount_usd, use_margin}`; returns `{ ok, dry_run, exchange, symbol, side, type, order_id, qty, price, result }`.
- Manual trade API: `POST /manual-trade` supports SL/TP modes (`sl_tp_mode`, percentages), leverage flags (`is_margin`, `leverage`).

## 2025-11-11
- Data sources status endpoint added to surface live availability/latency for providers (binance, kraken, crypto_com, coinpaprika). On failure, returns a default “all down” object to avoid UI breakage.
- “Top coins” cache includes indicators (RSI, MA50/200, EMA10, ATR, volumes, resistance levels) to reduce CPU on UI refresh.

## 2025-11-10
- Deployment profiles: `local` vs `aws`.
  - AWS uses `gluetun` for outbound VPN, `backend-aws`, `frontend-aws`, hardened Postgres, Nginx TLS.
  - Local uses direct ports: backend 8002, frontend 3000.
- Health checks:
  - `dashboard_health_check` (systemd timer): validates `/market/top-coins-data` JSON, minimal coin count, and data quality (non-null prices).
  - Telegram notifier enabled to alert on failure with contextual data.

## 2025-11-09
- LIVE vs DRY_RUN switch persists in database (`TradingSettings` with key `LIVE_TRADING`); on toggle, environment variable is updated for current process.
- DB write resilience: commit with rollback-on-failure, retry up to 3 times with backoff; logs success attempt number.

## 2025-11-08
- Nginx TLS and security: Enforce modern TLS (`TLSv1.2+`), security headers (X-Frame-Options, X-Content-Type-Options, X-XSS-Protection).
- CORS: Backend whitelist includes hilovivo.com domains; can extend via `CORS_ORIGINS` env (comma-separated).

## 2025-11-07
- Error handling policy:
  - Frontend logs use deduplication windows and levels (warn/error) to reduce noise.
  - All fetch paths return structured fallbacks: empty arrays/objects when safe, and never throw raw HTML/text into UI layers.


