# Portfolio Derivation from Crypto.com Exchange — Engineering Runbook

This document describes exactly how the Automated Trading Platform computes portfolio (balances, totals, collateral, borrowed, net value) from Crypto.com Exchange data, where it is stored, how it is refreshed, and how to verify or reconstruct it. Use it to rebuild or debug the pipeline with zero guesswork.

**Code and log references are exact** (file paths, function names, log strings). Shell commands are copy-paste ready for EC2/Docker.

---

## 1) Definitions

### What “Portfolio” means in this system

- **Portfolio** = the set of per-asset balances plus aggregate totals (assets, collateral, borrowed, net value) shown in the dashboard and returned by portfolio/snapshot APIs. It is **derived** from Crypto.com Exchange private balance endpoints, priced with public tickers, and optionally cached in the DB.

### Output fields (dashboard state / portfolio endpoints)

- **balances list** (or **assets**)  
  Per-asset entries with:
  - `currency` / `symbol` / `coin` (normalized, e.g. `BTC`)
  - `balance` / `total` (quantity)
  - `free` / `available`, `locked` (when present)
  - `value_usd` / `usd_value` (USD value for the position)
  - `price_usd` (price used; can be `null` for unpriced)
  - `source` (pricing source: see below)

- **Portfolio totals** (exposed as `totals` or top-level in summary):
  - **total_assets_usd** — Gross assets: sum of all positive USD-valued positions (raw, before haircut).
  - **total_collateral_usd** — Collateral after haircuts: Σ (raw_value × (1 − haircut)) for each asset. Used for Margin “Wallet Balance” style calculation.
  - **total_borrowed_usd** — Sum of borrowed/loan amounts in USD (from negative balances or `PortfolioLoan` table).
  - **total_value_usd** / **total_usd** — **Net value (wallet balance)**. This is what the UI shows as “Total Value”. Definition: prefer exchange-reported equity; if missing, use **collateral − borrowed**.

### Source values and what they imply

- `crypto_com` — Crypto.com public ticker
- `crypto_com_market_value` — `market_value` from account summary (no price multiplication)
- `stablecoin` / `stablecoin_1to1` — USD, USDT, USDC at 1.0
- `coingecko` — CoinGecko (snapshot service only)
- `unpriced` — no price; value may be 0 or omitted
- `crypto_com_live` — Net value from exchange-reported equity (e.g. `margin_equity`)
- `crypto_com_live_derived` — Net value computed as collateral − borrowed (when API does not return equity)
- `db_snapshot` — From stored `portfolio_snapshot_data`
- `derived:collateral_minus_borrowed` — From `get_portfolio_summary` when no exchange equity field is found
- `exchange:<field_path>` — From `get_portfolio_summary` when an exchange equity field is used (e.g. `exchange:result.wallet_balance_after_haircut`)

### Timestamps (as_of, snapshot age rules)

- A **snapshot** is a point-in-time view: list of assets + totals + `as_of` timestamp.
- **Latest snapshot** is selected by `as_of` descending; it is used only if age **&lt; 5 minutes** (see `get_latest_portfolio_snapshot(db, max_age_minutes=5)` in `backend/app/services/portfolio_snapshot.py`). If older, the dashboard falls back to `get_portfolio_summary(db)` which reads from `portfolio_balances` + `portfolio_loans` and optionally fresh API for haircuts/equity.

---

## 2) Data Sources (Crypto.com Exchange)

### Private endpoints (balances / account summary)

| Purpose | Method / endpoint | URL base | Env vars | Signing |
|--------|--------------------|----------|----------|--------|
| Primary balance fetch | `private/user-balance` | `EXCHANGE_CUSTOM_BASE_URL` or `https://api.crypto.com/exchange/v1` | `EXCHANGE_CUSTOM_API_KEY`, `EXCHANGE_CUSTOM_API_SECRET` | HMAC-SHA256: `method + id + api_key + params_str + nonce`; params sorted alphabetically; empty params = `""`. |
| Fallback balance fetch | `private/get-account-summary` | Same | Same | Same |

- **Required env vars for live data:** `EXCHANGE_CUSTOM_API_KEY`, `EXCHANGE_CUSTOM_API_SECRET`. Optional: `EXCHANGE_CUSTOM_BASE_URL` (default `https://api.crypto.com/exchange/v1`). `USE_CRYPTO_PROXY=true` routes calls via proxy (no direct signing in app).
- **Outbound IP:** Broker may log `[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP: <ip>`; use for IP whitelist.

### Response shapes we support

1. **result.accounts** — Array of `{ currency, balance, available, market_value?, ... }`.
2. **result.data** — Array; first element may contain **position_balances**: array of `{ instrument_name, quantity, max_withdrawal_balance, market_value? }`. We normalize `instrument_name` (e.g. `BTC_USDT`) to currency (e.g. `BTC`).
3. **result.account** / **result.balance** / **result.balances** — Treated as account list (single or list).
4. Top-level **accounts** (no `result`) — Used as the account list.

If both `result.accounts` and `result.data` exist, we use both; position_balances are converted to the same shape as accounts (currency, balance, available).

### Public endpoints (pricing)

- **Primary:** Crypto.com public tickers.  
  - **URL:** `https://api.crypto.com/exchange/v1/public/get-tickers` (no auth).  
  - We map `i` (e.g. `BTC_USDT`) → base currency and use `a` (ask) as price.  
- **Per-asset fallback (portfolio_cache):** `https://api.crypto.com/exchange/v1/public/get-ticker?instrument_name={CURRENCY}_USDT` or `_USD`.  
- **Portfolio snapshot service** also tries CoinGecko for missing prices (optional).  
- **Stablecoins:** USD, USDT, USDC are always priced at 1.0.

---

## 3) Normalization & Computation Algorithm (step-by-step)

Documented with exact code locations.

| Step | What happens | Code location |
|------|----------------|---------------|
| Fetch balances | Resolve credentials; call balance API | `portfolio_snapshot.fetch_live_portfolio_snapshot` (top); `portfolio_cache.update_portfolio_cache` (top). Broker: `app/services/brokers/crypto_com_trade.py` → `get_account_summary()` |
| Normalize shapes | Extract list of “accounts” from `accounts`, `result.data` (position_balances), `result.account`/`balance`/`balances`, or `data` | `portfolio_snapshot.fetch_live_portfolio_snapshot` (accounts extraction); `crypto_com_trade.get_account_summary` (result.data / position_balances → accounts) |
| Merge/aggregate by asset | Per-currency balance and available | Same; assets list built in snapshot and cache |
| Detect loans/borrowed | Negative balances → loan; also `borrowed_balance`, `borrowed_value`, `loan_amount`, `debt_amount`; else sum active `PortfolioLoan.borrowed_usd_value` | `portfolio_snapshot` (negative assets → total_borrowed_usd; fallback to PortfolioLoan); `portfolio_cache.update_portfolio_cache` (writes to `portfolio_loans`); `portfolio_cache.get_portfolio_summary` (reads PortfolioLoan for total_borrowed_usd_for_display) |
| Collateral | Σ (raw USD value × (1 − haircut)); haircut from account/position; stablecoins haircut 0. If no haircuts, collateral = total_assets_usd | `portfolio_snapshot` and `portfolio_cache.update_portfolio_cache` / `get_portfolio_summary`: collateral_value = raw_value * (1 - haircut) |
| Borrowed total | Sum \|value_usd\| for assets with total &lt; 0, or sum active `PortfolioLoan.borrowed_usd_value` | Same as above |
| Net value | Prefer exchange-reported equity (e.g. `margin_equity`, `wallet_balance_after_haircut`); else **collateral − borrowed** | `portfolio_cache.get_portfolio_summary`: scans for equity fields; else `derived_equity = total_collateral_usd - total_borrowed_usd_for_display`; `portfolio_snapshot`: margin_equity or collateral − borrowed |
| Pricing rules | Stablecoins = 1.0; missing ticker → try get-ticker per asset; unpriced → value 0, increment unpriced_count | `portfolio_snapshot` (prices dict, stablecoin branch, unpriced_count); `portfolio_cache` (get_crypto_prices, per-asset get-ticker fallback) |

---

## 4) Caching & Snapshots

- **Where portfolio cache lives:** Tables `portfolio_balances`, `portfolio_snapshots`, `portfolio_loans`. Filled by `update_portfolio_cache(db)` in `backend/app/services/portfolio_cache.py`.
- **When it refreshes:** Exchange sync loop (`ExchangeSyncService`) runs every **5 seconds** (`backend/app/services/exchange_sync.py` → `_run_sync_sync` → `sync_balances`). In `sync_balances`: if cache is empty or **last_updated** is older than **60 seconds**, it calls `update_portfolio_cache(db)`; on success it then calls `fetch_live_portfolio_snapshot(db)` and `store_portfolio_snapshot(db, snapshot)`.
- **Snapshot tables:** `portfolio_snapshot_data` stores full snapshot (assets JSON, totals, source, as_of). `portfolio_snapshots` stores legacy single total_usd per row. `portfolio_balances` stores per-currency rows (currency, balance, usd_value). `portfolio_loans` stores active loans.
- **Rule “prefer snapshot if &lt; X minutes old”:** Dashboard uses `get_latest_portfolio_snapshot(db, max_age_minutes=5)`; if returned snapshot is not None it is used; otherwise `get_portfolio_summary(db)` is used. Code: `backend/app/api/routes_dashboard.py` (e.g. around line 687–699: `get_latest_portfolio_snapshot` then `get_portfolio_summary`).

---

## 5) Persistence (DB)

### Tables

| Table | Key columns | Filled by | Used by |
|-------|-------------|-----------|---------|
| **portfolio_balances** | id, currency, balance (Numeric 20,8), usd_value (Float), updated_at | `update_portfolio_cache` (clear + re-insert) | `get_cached_portfolio`, `get_portfolio_summary` (dedup by latest id per currency) |
| **portfolio_snapshots** | id, total_usd (Float), created_at | Legacy; raw gross total per update | `get_last_updated` in get_portfolio_summary |
| **portfolio_snapshot_data** | id, exchange, portfolio_value_source, assets_json, total_assets_usd, total_collateral_usd, total_borrowed_usd, total_value_usd, unpriced_count, as_of, created_at | `store_portfolio_snapshot()` after fetch or when sync updates cache | `get_latest_portfolio_snapshot()`; portfolio snapshot API; dashboard when fresh |
| **portfolio_loans** | currency, borrowed_amount, borrowed_usd_value, is_active, ... | `update_portfolio_cache()` from negative balances / loan fields | `get_portfolio_summary` for total_borrowed_usd_for_display |

### Latest snapshot selection

- **portfolio_snapshot_data:** `get_latest_portfolio_snapshot(db, max_age_minutes=5)` in `backend/app/services/portfolio_snapshot.py`: query order by `as_of desc`, take first row; return `None` if age &gt; 5 minutes.
- **“Latest”** = ordering by `as_of` descending; **max age** = 5 minutes for dashboard use.

---

## 6) Logs: Debug Map

Use these to trace portfolio derivation without secrets.

| Log tag / message | Meaning | Next action |
|-------------------|--------|-------------|
| `[PORTFOLIO_SNAPSHOT]` | Snapshot service: fetch/store path | Check credentials, proxy, or API shape |
| `[PORTFOLIO_SNAPSHOT] Fetching live portfolio data from Crypto.com Exchange...` | Starting live fetch | If followed by error, check API/network/auth |
| `[PORTFOLIO_SNAPSHOT_RAW_SHAPE] top_keys=... result_keys=... list_counts=[...]` | Raw API response structure (keys/counts only) | Confirm we have `accounts` or `data`/`position_balances` |
| `[PORTFOLIO_SNAPSHOT] No accounts extracted, candidates checked: ...` | No account list found | Inspect top_keys/result_keys; adjust extraction for new API shape |
| `[PORTFOLIO_SNAPSHOT] Retrieved N account balances from Crypto.com` | Accounts extracted | Proceed to pricing and totals |
| `[PORTFOLIO_SNAPSHOT] Loan detected: CURRENCY balance=... value=$...` | Negative balance treated as loan | Confirms borrowed is counted |
| `[PORTFOLIO_SNAPSHOT] Using margin_equity from API: $...` | Net value from exchange | Source will be `crypto_com_live` |
| `[PORTFOLIO_SNAPSHOT] Calculated wallet balance: $... (collateral: $..., borrowed: $...)` | Net = collateral − borrowed | Source will be `crypto_com_live_derived` |
| `[PORTFOLIO_SNAPSHOT] Snapshot created: N assets, total=$..., source=..., unpriced=...` | Snapshot built successfully | unpriced &gt; 0 means some assets had no price |
| `[PORTFOLIO_SNAPSHOT] ⚠️ No assets found in snapshot` | No assets after parsing/pricing | Check accounts extraction and price availability |
| `[PORTFOLIO_DEBUG]` | Detailed valuation (when `PORTFOLIO_DEBUG=1` or `PORTFOLIO_SNAPSHOT_DEBUG`) | Per-asset price source, haircut, collateral |
| `[PORTFOLIO_CACHE]` | Cache update / credentials | Cache path and credential source |
| `✅ Using exchange-reported equity as total_usd: $... (source: ...)` | get_portfolio_summary chose an exchange field | Net value matches exchange. Code: `portfolio_cache.get_portfolio_summary` |
| `⚠️ Exchange equity not found, using derived calculation: collateral $... - borrowed $... = $...` | No exchange equity; using collateral − borrowed | Net may differ from Crypto.com UI. Code: `portfolio_cache.get_portfolio_summary` |
| `🔴 Found loan for CURRENCY: ... ($...)` | Loan detected in update_portfolio_cache | Synced to portfolio_loans. Code: `portfolio_cache.update_portfolio_cache` |
| `[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP: ...` | Outbound IP used for API | Use for IP whitelist |
| `✅ Portfolio cache updated: $...` | sync_balances called update_portfolio_cache successfully | Code: `exchange_sync.sync_balances` |
| `✅ Portfolio snapshot created: N assets, total=$...` | Snapshot stored after cache update | Code: `exchange_sync.sync_balances` |

---

## 7) Known Failure Modes + Fix

| Symptom (UI/API) | Log signature | Likely cause | Fix steps |
|------------------|---------------|--------------|-----------|
| No live data; empty or cached-only portfolio | `API credentials not configured`; `[PORTFOLIO_SNAPSHOT] ... not configured` | Missing exchange env vars | Set `EXCHANGE_CUSTOM_API_KEY`, `EXCHANGE_CUSTOM_API_SECRET`; optionally `EXCHANGE_CUSTOM_BASE_URL` |
| Net value differs from Crypto.com UI; derived used | `⚠️ Exchange equity not found, using derived calculation` | API does not return wallet_balance_after_haircut / margin_equity | Normal if API doesn’t expose it; accept small difference or need API to return that field |
| Some assets at $0; unpriced_count &gt; 0 | `Could not find Crypto.com price for CURRENCY`; `No price found for CURRENCY` | Pricing fails for some assets | Check Crypto.com public get-tickers and get-ticker; ensure instrument (e.g. BTC_USDT) exists |
| Intermittent empty or stale data | Timeout/connection errors in logs; sync cycle errors | Timeouts / slow calls | Increase timeout; check network/egress; consider `USE_CRYPTO_PROXY=true` |
| Errors on insert or query | SQLAlchemy / “no such table” | Schema/table missing | Ensure models are imported; `portfolio_snapshot_data` created via `_ensure_table_exists()` in portfolio_snapshot; portfolio_balances/snapshots/loans via migrations or create_all |
| API returns no equity | `Exchange equity not found, using derived calculation` | Exchange response missing equity fields | Use derived; or verify API version/docs for equity field name |
| Cache stuck or stale | No `✅ Portfolio cache updated` for &gt; 60s; dashboard shows old totals | Sync not running or update_portfolio_cache failing | Check exchange sync loop; logs for update_portfolio_cache errors; DB reachable |

---

## 8) Rebuild / Reconstruct Checklist (from scratch)

Linear checklist with exact commands. Target: new engineer can rebuild/verify in ~30 minutes.

1. **Confirm env vars are present**  
   - Required: `EXCHANGE_CUSTOM_API_KEY`, `EXCHANGE_CUSTOM_API_SECRET`.  
   - Optional: `EXCHANGE_CUSTOM_BASE_URL` (default `https://api.crypto.com/exchange/v1`), `USE_CRYPTO_PROXY=true`.  
   - On EC2: `grep -E "EXCHANGE_CUSTOM_API_KEY|EXCHANGE_CUSTOM_API_SECRET" /path/to/secrets/runtime.env` (or wherever secrets are loaded); ensure not empty.

2. **Confirm DB reachable and tables exist**  
   - Run inside backend container:  
     `docker exec automated-trading-platform-backend-aws-1 python -c "from app.database import SessionLocal; from sqlalchemy import inspect; db = SessionLocal(); i = inspect(db.bind); print([t for t in ['portfolio_balances', 'portfolio_snapshots', 'portfolio_snapshot_data', 'portfolio_loans'] if t in i.get_table_names()]); db.close()"`  
   - Or multi-line (paste in a shell that supports it):  
     ```bash
     docker exec automated-trading-platform-backend-aws-1 python -c '
     from app.database import SessionLocal
     from sqlalchemy import inspect
     db = SessionLocal()
     inspector = inspect(db.bind)
     for t in ["portfolio_balances", "portfolio_snapshots", "portfolio_snapshot_data", "portfolio_loans"]:
         print(t, "exists" if t in inspector.get_table_names() else "MISSING")
     db.close()
     '
     ```

3. **Rebuild Docker image and restart**  
   - `cd /home/ubuntu/automated-trading-platform` (or repo root on EC2)  
   - `git pull --rebase origin main`  
   - `sudo docker compose --profile aws build --no-cache backend-aws`  
   - `sudo docker compose --profile aws up -d --force-recreate backend-aws`

4. **Run verification curls**  
   - Dashboard state (includes portfolio):  
     `curl -s "http://127.0.0.1:8002/api/dashboard/state" | head -c 800`  
   - Portfolio snapshot (if endpoint exists):  
     `curl -s "http://127.0.0.1:8002/api/portfolio/snapshot" | head -c 500`  
   - Expect JSON with `portfolio` or `totals` (total_value_usd, total_collateral_usd, total_borrowed_usd).

5. **Confirm dashboard state contains portfolio fields**  
   - `curl -s "http://127.0.0.1:8002/api/dashboard/state" | python3 -c "import sys,json; d=json.load(sys.stdin); p=d.get('portfolio',{}); print('total_value_usd' in p or 'totals' in d, p.get('total_value_usd') or d.get('totals',{}).get('total_value_usd'))"`

6. **Confirm snapshot written (optional)**  
   - After a few minutes, check latest snapshot:  
     ```bash
     docker exec automated-trading-platform-backend-aws-1 python -c '
     from app.database import SessionLocal
     from app.services.portfolio_snapshot import PortfolioSnapshotData
     db = SessionLocal()
     r = db.query(PortfolioSnapshotData).order_by(PortfolioSnapshotData.as_of.desc()).first()
     print("Latest as_of:", r.as_of if r else None, "total_value_usd:", getattr(r, "total_value_usd", None))
     db.close()
     '
     ```

7. **Confirm totals match expected**  
   - Run the 30-second verification script (see section 9).  
   - `docker exec automated-trading-platform-backend-aws-1 python scripts/verify_portfolio_consistency.py --live`

---

## 9) 30-Second Verification Script

**Script:** `backend/scripts/verify_portfolio_consistency.py`

It calls `GET /api/dashboard/state` **in-process** (TestClient) and via **HTTP** (curl path), then compares portfolio totals (collateral, borrowed, net, assets count). If they differ beyond tolerance ($0.01), it reports MISMATCH (routing/config vs portfolio math).

### What “fast check” validates

- Dashboard route logic, portfolio math, snapshot selection, cache read path, DB consistency.  
- **Does not** validate: live exchange connectivity, fresh balances, pricing calls.

### What `--live` validates

- Forces `update_portfolio_cache(db)` and `fetch_live_portfolio_snapshot(db)` + `store_portfolio_snapshot(db, snapshot)` before comparing.  
- Validates: exchange credentials, signing, balance fetch, price fetch, snapshot write, cache update, dashboard read. **Full end-to-end.**

### What `--json` outputs

- Single JSON object: `match`, `tolerance`, `internal`, `api`, `delta`, `timestamp`, optional `git_sha`. Use in CI/cron/alerts; exit code 0 on match, 1 on mismatch or error.

### Commands

```bash
docker exec automated-trading-platform-backend-aws-1 python scripts/verify_portfolio_consistency.py
docker exec automated-trading-platform-backend-aws-1 python scripts/verify_portfolio_consistency.py --live
docker exec automated-trading-platform-backend-aws-1 python scripts/verify_portfolio_consistency.py --json
```

Optional (different backend URL):  
`BACKEND_URL=http://127.0.0.1:8002 python scripts/verify_portfolio_consistency.py`

### What each command validates

| Command | Validates | Does not validate | When to use | If it fails → interpretation |
|---------|-----------|-------------------|-------------|------------------------------|
| **No flags** (fast check) | Dashboard route logic, portfolio math, snapshot selection, cache read, DB consistency | Live exchange, fresh balances, pricing | After code changes, refactors, Docker rebuilds, migrations | **Internal logic / routing / DB** |
| **`--live`** | Exchange credentials, signing, balance fetch, price fetch, snapshot write, cache update, dashboard read (full E2E) | — | When you need to prove the full pipeline | **Exchange auth, IP whitelist, API change, or pricing** |
| **`--json`** | Same as above (fast or live); output is parseable | — | CI guard, cron, Telegram alerts | Same as above; use exit code and `match` field |

---

## 10) Cursor Rotation Design (Executed-Orders Sync)

This section documents the **executed-orders sync cursor** as an example of **rebuildable sync state** that survives restarts and is safe with multiple workers. It is not portfolio-specific but is part of the same exchange-sync stack.

### Why it exists

- Multi-symbol order-history sync is capped at **20 symbols per run** to avoid hammering the API.  
- A **cursor** records which slice of the symbol list was last synced so the next run syncs the next 20 (rotation).  
- Cursor must **persist across container restarts** and be **safe with multiple backend replicas** (row or file lock).

### Postgres primary cursor

- **Table:** `sync_order_history_cursor`  
  - Columns: `id` (INTEGER PRIMARY KEY, always 1), `cursor_index` (INTEGER NOT NULL DEFAULT 0).  
  - Created automatically: `CREATE TABLE IF NOT EXISTS sync_order_history_cursor (...)` on first use.  
- **Row lock:** `SELECT cursor_index FROM sync_order_history_cursor WHERE id = 1 FOR UPDATE` so only one worker advances the cursor.  
- **Update:** `UPDATE sync_order_history_cursor SET cursor_index = :next_cursor WHERE id = 1`; then commit.  
- **Persistence:** Stored in Postgres, so survives container restart and deploy.

### File fallback

- **Path:** `ORDER_HISTORY_SYNC_CURSOR_PATH` (default `/tmp/order_history_sync_cursor`).  
- **Protection:** `fcntl.flock(f.fileno(), fcntl.LOCK_EX)` when reading and when writing so multiple workers do not corrupt the file.  
- **Persistence:** `/tmp` is ephemeral in the container; to survive restart when using file fallback, set `ORDER_HISTORY_SYNC_CURSOR_PATH` to a path on a **mounted volume**.

### Code pointer

- **File:** `backend/app/services/exchange_sync.py`  
- **Function:** `_order_history_cursor_get_and_advance(self, db, symbol_count, max_per_run)`  
- **Called from:** `sync_order_history()` when `instrument_name` is None (multi-symbol path). It returns `(start_index, next_cursor)`; the multi-symbol loop then syncs `symbols_this_run` and sleeps 200 ms between symbols.

### Log reference

- On DB failure fallback: `Order history cursor DB failed, using file fallback: ...`  
- Multi-symbol run: `Order history sync: multi-symbol this_run=N total_stored=M next_cursor=K`

---

## Code Pointers (quick reference)

| Component | File | Functions / models |
|-----------|------|--------------------|
| Portfolio snapshot (fetch, store, latest) | `backend/app/services/portfolio_snapshot.py` | `fetch_live_portfolio_snapshot(db)`, `store_portfolio_snapshot(db, snapshot)`, `get_latest_portfolio_snapshot(db, max_age_minutes=5)`, `PortfolioSnapshotData` |
| Portfolio cache (update, summary, prices) | `backend/app/services/portfolio_cache.py` | `update_portfolio_cache(db)`, `get_portfolio_summary(db, request_context=None)`, `get_crypto_prices()`, `get_cached_portfolio(db)`, `get_last_updated(db)` |
| Broker balance API | `backend/app/services/brokers/crypto_com_trade.py` | `get_account_summary()` (private/user-balance, fallback private/get-account-summary) |
| Dashboard state (portfolio part) | `backend/app/api/routes_dashboard.py` | `_compute_dashboard_state` (or equivalent) — uses `get_latest_portfolio_snapshot` then `get_portfolio_summary`; merges into state |
| Portfolio API routes | `backend/app/api/routes_portfolio.py` | `get_portfolio_snapshot`, `get_latest_portfolio`, `refresh_portfolio_snapshot` |
| Exchange sync (cache + snapshot cadence) | `backend/app/services/exchange_sync.py` | `sync_balances(db)` — conditionally calls `update_portfolio_cache(db)` (if cache empty or &gt;60s old), then `fetch_live_portfolio_snapshot` + `store_portfolio_snapshot`; `_run_sync_sync` → sync_balances every 5s |
| Order history cursor (rotation) | `backend/app/services/exchange_sync.py` | `_order_history_cursor_get_and_advance(db, symbol_count, max_per_run)` |
| Models | `backend/app/models/portfolio.py` | `PortfolioBalance`, `PortfolioSnapshot` |
| | `backend/app/services/portfolio_snapshot.py` | `PortfolioSnapshotData` |
| | `backend/app/models/portfolio_loan.py` | `PortfolioLoan` |

---

## Files Referenced

- `backend/app/services/portfolio_snapshot.py`
- `backend/app/services/portfolio_cache.py`
- `backend/app/services/brokers/crypto_com_trade.py`
- `backend/app/services/exchange_sync.py`
- `backend/app/api/routes_dashboard.py`
- `backend/app/api/routes_portfolio.py`
- `backend/app/models/portfolio.py`
- `backend/app/models/portfolio_loan.py`
- `backend/scripts/verify_portfolio_consistency.py`

## Log Strings Referenced

- `[PORTFOLIO_SNAPSHOT]`, `[PORTFOLIO_SNAPSHOT_RAW_SHAPE]`, `[PORTFOLIO_CACHE]`, `[PORTFOLIO_DEBUG]`
- `✅ Using exchange-reported equity as total_usd:`
- `⚠️ Exchange equity not found, using derived calculation:`
- `🔴 Found loan for`
- `[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP:`
- `✅ Portfolio cache updated:`, `✅ Portfolio snapshot created:`
- `Order history cursor DB failed, using file fallback:`
- `Order history sync: multi-symbol this_run=`

## Commands Included

- DB table check (Python one-liner with inspector)
- Rebuild: `git pull`, `docker compose build --no-cache backend-aws`, `up -d --force-recreate`
- Verification: `curl .../api/dashboard/state`, `curl .../api/portfolio/snapshot`
- Snapshot row check (query `PortfolioSnapshotData`)
- `verify_portfolio_consistency.py` (no flags, `--live`, `--json`)
