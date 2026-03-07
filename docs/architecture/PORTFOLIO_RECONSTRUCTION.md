# Portfolio System — Technical Reconstruction Document

This document describes, step by step, how the portfolio system works in the Automated Trading Platform backend and how to rebuild it from scratch. It is precise and technical: exact behavior only, no marketing language.

---

## 1. Portfolio Data Flow (End-to-End)

### 1.1 Frontend → API

- **API endpoint called by the frontend:** `GET /api/dashboard/state`
- **Frontend code:**  
  - `frontend/src/lib/api.ts`: `getPortfolio()` calls `fetchAPI('/dashboard/state')` and reads `data.portfolio?.assets` and `data.portfolio?.total_value_usd` (or `data.total_usd_value`).  
  - `frontend/src/app/api.ts`: `getDashboardState()` calls `fetchAPI<DashboardState>('/dashboard/state')`.  
  - Dashboard page uses `getDashboardState()` and displays portfolio from `dashboardState.portfolio` (assets, total_value_usd, etc.).
- **Base URL:** The frontend uses the same API base as other endpoints (e.g. `getApiUrl()` / `DEFAULT_API_URL`); the path is `/dashboard/state` (prefixed with `/api` by the app’s API base, so the full path is **GET /api/dashboard/state**).

### 1.2 Backend route

- **File:** `backend/app/api/routes_dashboard.py`
- **Route:** `@router.get("/dashboard/state")`
- **Handler:** `get_dashboard_state(request, db, reconcile_debug)`
- **Behavior:** Builds `request_context` (headers, `reconcile_debug` from query param), then calls `_compute_dashboard_state(db, request_context=request_context)` and returns its result. Router is mounted with prefix `/api`, so the full path is **GET /api/dashboard/state**.

### 1.3 Core computation: `_compute_dashboard_state`

- **File:** `backend/app/api/routes_dashboard.py`
- **Function:** `async def _compute_dashboard_state(db: Session, request_context: Optional[dict] = None) -> dict`

**Order of operations:**

1. **Portfolio snapshot (preferred)**  
   - `get_latest_portfolio_snapshot(db, max_age_minutes=5)` from `app.services.portfolio_snapshot`.  
   - Called via `asyncio.to_thread(get_latest_portfolio_snapshot, db, 5)`.  
   - If a snapshot exists and is younger than 5 minutes, it is used to build `portfolio_assets`, `total_usd_value`, `total_assets_usd`, `total_collateral_usd`, `total_borrowed_usd`, `portfolio_value_source`, `last_updated`.

2. **Portfolio cache (fallback)**  
   - If no fresh snapshot: `get_portfolio_summary(db, request_context)` from `app.services.portfolio_cache`.  
   - Called via `asyncio.to_thread(get_portfolio_summary, db, request_context)`.  
   - Uses DB tables `portfolio_balances` and `portfolio_snapshots` (and optionally `portfolio_loans`).

3. **Live fetch (when cache/snapshot empty)**  
   - If `portfolio_summary` is None or no snapshot was used, the code may call `fetch_live_portfolio_snapshot(db)` and then `store_portfolio_snapshot(db, snapshot)` (from `app.services.portfolio_snapshot`), then build portfolio from that live snapshot.

4. **Empty portfolio path**  
   - If after all of the above there are still no assets, it tries again: `fetch_live_portfolio_snapshot(db)`, `store_portfolio_snapshot(db, snapshot)`, then builds `portfolio_assets` from the result.

5. **Response shape**  
   - The returned state includes a `"portfolio"` key with:  
     `assets`, `total_value_usd`, `total_assets_usd`, `total_collateral_usd`, `total_borrowed_usd`, `portfolio_value_source`, `exchange`, `as_of`, and optionally `reconcile` (when reconcile debug is enabled).

### 1.4 Services and broker methods

| Step | Service / module | Function / method |
|------|------------------|--------------------|
| Latest snapshot from DB | `app.services.portfolio_snapshot` | `get_latest_portfolio_snapshot(db, max_age_minutes=5)` |
| Portfolio summary from DB | `app.services.portfolio_cache` | `get_portfolio_summary(db, request_context)` |
| Live fetch from exchange | `app.services.portfolio_snapshot` | `fetch_live_portfolio_snapshot(db)` |
| Store snapshot | `app.services.portfolio_snapshot` | `store_portfolio_snapshot(db, snapshot)` |
| Update cache from exchange | `app.services.portfolio_cache` | `update_portfolio_cache(db)` |
| Exchange API client | `app.services.brokers.crypto_com_trade` | `trade_client.get_account_summary()` |

- **Class:** `CryptoComTradeClient` in `backend/app/services/brokers/crypto_com_trade.py`.  
- **Singleton:** `trade_client` (module-level instance).  
- **Method used for balances:** `get_account_summary(self) -> dict`.

### 1.5 Exchange endpoints

- **Primary:** `private/user-balance`  
  - URL: `{base_url}/private/user-balance`  
  - Default `base_url`: from `REST_BASE` in `backend/app/services/brokers/crypto_com_constants.py` → `https://api.crypto.com/exchange/v1`.  
  - Overridable via env: `EXCHANGE_CUSTOM_BASE_URL`.  
- **Fallback when user-balance returns 0 accounts:** `private/get-account-summary` (same base URL).  
- Request: HTTP POST, JSON body with signed payload (see §2).

### 1.6 Authentication

- Credentials are resolved by `app.utils.credential_resolver.resolve_crypto_credentials()`.  
- That returns `(api_key, api_secret, used_pair_name, diagnostics)`.  
- The client uses `api_key` and `api_secret` to build the signed payload in `CryptoComTradeClient.sign_request(method, params)`.  
- Before calling the exchange, `trade_client` may be updated with resolved credentials in `portfolio_cache.update_portfolio_cache()` and `portfolio_snapshot.fetch_live_portfolio_snapshot()` so the same key/secret pair is used.

### 1.7 Balances and prices

- **Balances:** From Crypto.com response to `private/user-balance` (or fallback `private/get-account-summary`).  
  - Parsed from `result.accounts` or `result.data` (e.g. `position_balances`).  
  - Normalized with `_normalize_currency_name()` in `portfolio_cache` and `portfolio_snapshot`.  
- **Prices (in portfolio_cache):**  
  - From Crypto.com: `https://api.crypto.com/exchange/v1/public/get-tickers` (bulk) and per-instrument `get-ticker?instrument_name={CURRENCY}_USDT` or `_USD`.  
  - USD value: prefer `market_value` from the account/balance object; otherwise `balance * price` (stablecoins as 1:1 when applicable).  
- **Prices (in portfolio_snapshot):**  
  - `get_crypto_prices()` from `portfolio_cache` (Crypto.com tickers), then optional CoinGecko fallback for missing symbols via `SimplePriceFetcher`.

### 1.8 Total USD value

- **In portfolio_cache (`get_portfolio_summary`):**  
  - Prefer exchange-reported equity/balance fields from a fresh `get_account_summary()` (e.g. `wallet_balance_after_haircut`, `wallet_balance`, `equity`, `margin_equity`).  
  - Selected by `scan_for_equity_fields()` and priority rules; overridable with `PORTFOLIO_EQUITY_FIELD_OVERRIDE`.  
  - If none found: derived as `total_collateral_usd - total_borrowed_usd` (collateral from cached balances + haircuts from fresh API, borrowed from `portfolio_loans` table if present).  
- **In portfolio_snapshot:**  
  - From API `margin_equity` (or similar) if present; else `total_collateral_usd - total_borrowed_usd` (collateral/borrowed from snapshot assets and optional `PortfolioLoan` table).

### 1.9 Final response shape

- **Endpoint:** GET `/api/dashboard/state`  
- **Key for portfolio:** `result["portfolio"]` with:  
  - `assets`: list of `{ currency, balance, usd_value, ... }` (v4.0 format).  
  - `total_value_usd`: net wallet balance (primary value for “total”).  
  - `total_assets_usd`, `total_collateral_usd`, `total_borrowed_usd`, `portfolio_value_source`, `exchange`, `as_of`, and optionally `reconcile`.

---

## 2. Exchange Integration Details

### 2.1 Environment variables

- **Required for portfolio (canonical names):**  
  - `EXCHANGE_CUSTOM_API_KEY`  
  - `EXCHANGE_CUSTOM_API_SECRET`  
- **Alternative pairs (checked in order by `resolve_crypto_credentials()`):**  
  - `CRYPTO_COM_API_KEY` / `CRYPTO_COM_API_SECRET`  
  - `CRYPTOCOM_API_KEY` / `CRYPTOCOM_API_SECRET`  
- **Optional:**  
  - `EXCHANGE_CUSTOM_BASE_URL` — override API base (default: `https://api.crypto.com/exchange/v1`).  
  - `USE_CRYPTO_PROXY` — if `"true"`, balance requests go through proxy; proxy URL/token: `CRYPTO_PROXY_URL`, `CRYPTO_PROXY_TOKEN`.

### 2.2 Signature construction

- **File:** `backend/app/services/brokers/crypto_com_trade.py`  
- **Method:** `CryptoComTradeClient.sign_request(self, method, params, ...)`

**Algorithm:**

1. **Nonce:** `nonce_ms = int(time.time() * 1000)` (milliseconds). Overridable via `_nonce_override_ms`.
2. **Params string for signing:**  
   - If `params` is empty `{}`: `params_str = ""`.  
   - Else: `params_str = self._params_to_str(params, 0)`.  
   - `_params_to_str`: iterate keys in **sorted** order; for each key append `key` then the value’s canonical string (recursing for dict/list). Value canonicalization in `_params_value_to_sig_str`: `None` → `"null"`, bool → `"true"`/`"false"`, else `str(value)`.
3. **String to sign:**  
   `string_to_sign = method + str(request_id) + self.api_key + params_str + str(nonce_ms)`  
   with `request_id = 1` by default.
4. **Signature:**  
   `signature = hmac.new(bytes(api_secret, 'utf-8'), msg=bytes(string_to_sign, 'utf-8'), digestmod=hashlib.sha256).hexdigest()`.
5. **Payload (JSON body):**  
   `id`, `method`, `api_key`, `params` (alphabetically ordered when non-empty), `nonce`, `sig`.

### 2.3 Params string for signing (empty params)

- For `private/user-balance` the request uses `params = {}`.  
- So `params_str = ""` (empty string), and the string to sign is:  
  `method + "1" + api_key + "" + str(nonce_ms)`.

### 2.4 Auth failure

- **401 response:** Body parsed for `code` and `message`.  
  - `40101`: authentication failure (key/secret/permissions).  
  - `40103`: IP not whitelisted.  
- **Behavior:** Log, optionally try TRADE_BOT failover if configured; otherwise raise `RuntimeError` with a message that includes the code and guidance (e.g. check key, IP allowlist).  
- **Portfolio snapshot endpoint (`GET /api/portfolio/snapshot`):** On auth error, if `ALLOW_PORTFOLIO_FALLBACK=true` and environment is local, it can return data from `app.services.portfolio_fallback` (derived from trades or local file) instead of failing.

### 2.5 Empty balances

- If the exchange returns 200 but no accounts/positions, the code tries `private/get-account-summary` as fallback.  
- If still no accounts, response is parsed as “0 accounts”; portfolio cache/snapshot will have empty assets and total 0 until the next successful fetch.

### 2.6 Why portfolio can work when order history fails

- **Different endpoints:** Portfolio uses `private/user-balance` (and fallback `private/get-account-summary`). Order history uses a different private method (e.g. order-history/list) with different parameters and possibly different permissions or rate limits.  
- **Different response shapes:** user-balance returns balance/position data; order-history returns list of orders. So one can succeed while the other fails (e.g. permissions, account type, or pagination/time range).

### 2.7 Why user-balance may return data when order-history is empty

- user-balance reflects current account/position balances. Order-history is filtered by time and pagination; it can be empty for the requested window even when the account has balances. So “no orders” does not imply “no balances”.

---

## 3. Database Layer

### 3.1 Tables involved in portfolio

| Table | Model | File |
|-------|--------|------|
| `portfolio_balances` | `PortfolioBalance` | `backend/app/models/portfolio.py` |
| `portfolio_snapshots` | `PortfolioSnapshot` | `backend/app/models/portfolio.py` |
| `portfolio_snapshot_data` | `PortfolioSnapshotData` | `backend/app/services/portfolio_snapshot.py` (class in same file) |
| `portfolio_loans` | `PortfolioLoan` | `backend/app/models/portfolio_loan.py` |

- **portfolio_balances:** `id`, `currency`, `balance`, `usd_value`, `updated_at`. Populated by `portfolio_cache.update_portfolio_cache()` (replace-all each run: delete all then bulk insert).  
- **portfolio_snapshots:** `id`, `total_usd`, `created_at`. One row per cache update in `update_portfolio_cache()`.  
- **portfolio_snapshot_data:** `id`, `exchange`, `portfolio_value_source`, `assets_json`, `total_assets_usd`, `total_collateral_usd`, `total_borrowed_usd`, `total_value_usd`, `unpriced_count`, `as_of`, `created_at`. Used by `store_portfolio_snapshot()` / `get_latest_portfolio_snapshot()`.  
- **portfolio_loans:** `id`, `currency`, `borrowed_amount`, `borrowed_usd_value`, `interest_rate`, `notes`, `is_active`, `created_at`, `updated_at`. Used when present for borrowed amounts in summary/snapshot.

### 3.2 When tables are created

- **At startup:**  
  - `backend/app/main.py` runs `import app.models` then `Base.metadata.create_all(bind=engine)`.  
  - `app.models` imports `PortfolioBalance` and `PortfolioSnapshot` from `app.models.portfolio`, so **portfolio_balances** and **portfolio_snapshots** are created at startup if they do not exist.  
  - **portfolio_loans** and **portfolio_snapshot_data** are not imported in `app.models`; they are **not** created by this `create_all`.  
- **portfolio_snapshot_data:** Created on first use in `app.services.portfolio_snapshot._ensure_table_exists(db)` by `PortfolioSnapshotData.__table__.create(db.bind, checkfirst=True)`.  
- **portfolio_loans:** Created by a dedicated step, e.g. `backend/run_migration.py` which runs `Base.metadata.create_all(bind=engine, tables=[PortfolioLoan.__table__])`.  
- **Optional columns / extra tables:** `backend/app/database.py`’s `ensure_optional_columns()` creates watchlist_items, market_data, market_price, order_intents; it does **not** create portfolio_balances, portfolio_snapshots, portfolio_snapshot_data, or portfolio_loans.

### 3.3 If tables do not exist

- **portfolio_balances / portfolio_snapshots:** If missing, `get_portfolio_summary()` and `update_portfolio_cache()` will hit SQL errors when querying/inserting; dashboard state may return empty portfolio or 500.  
- **portfolio_snapshot_data:** If missing, `get_latest_portfolio_snapshot()` returns None; `store_portfolio_snapshot()` calls `_ensure_table_exists()` so the table is created on first store.  
- **portfolio_loans:** If missing, `get_portfolio_summary()` and `update_portfolio_cache()` check with `_table_exists(db, 'portfolio_loans')` and skip loan logic; portfolio still works with `total_borrowed_usd = 0`.

### 3.4 Migrations

- No Alembic (or similar) migration is required for the core portfolio tables; they are created by SQLAlchemy `create_all` or by `_ensure_table_exists` / `run_migration.py` as above.  
- Optional SQL migration exists for index only: `backend/migrations/add_portfolio_balances_index.sql` (composite index on `portfolio_balances(currency, id DESC)`).

---

## 4. Sync Logic

### 4.1 How and when exchange_sync runs

- **Start:** In `backend/app/main.py`, after DB init, `asyncio.create_task(exchange_sync_service.start())` is called.  
- **Service:** `ExchangeSyncService` in `backend/app/services/exchange_sync.py`. Global instance: `exchange_sync_service`.  
- **Method:** `async def start(self)`: waits 15 seconds, then runs a loop that calls `await self.run_sync()` then `await asyncio.sleep(self.sync_interval)` with `sync_interval = 5` seconds.

### 4.2 On request vs background

- Portfolio data is **not** synced on every dashboard request.  
- Sync runs in the **background** every 5 seconds via `ExchangeSyncService`.  
- Each sync cycle calls `_run_sync_sync(db)`, which calls `sync_balances(db)` (and order history / open orders).  
- Dashboard requests **read** from DB/cache: snapshot (if fresh) or `get_portfolio_summary()`; they only trigger a **live** fetch when there is no snapshot and no summary, or when assets are empty (see §1.3).

### 4.3 How portfolio snapshot is refreshed

- **By exchange_sync:** When `sync_balances()` decides cache is empty or stale (>60 seconds), it calls `update_portfolio_cache(db)`. On success it then calls `fetch_live_portfolio_snapshot(db)` and `store_portfolio_snapshot(db, snapshot)`.  
- **By dashboard:** When there is no fresh snapshot and no portfolio summary (or empty assets), `_compute_dashboard_state` calls `fetch_live_portfolio_snapshot(db)` and `store_portfolio_snapshot(db, snapshot)`.  
- **By API:** `POST /api/portfolio/refresh` calls `fetch_live_portfolio_snapshot(db)` and `store_portfolio_snapshot(db, snapshot)`.

### 4.4 Caching

- **In-memory (portfolio_cache):** `_last_update_time`, `_last_update_result`, and `_min_update_interval = 60` seconds. Update is skipped if the last update was within 60 seconds.  
- **DB:** Latest snapshot is read from `portfolio_snapshot_data` (or from `portfolio_balances` + `portfolio_snapshots` for summary). Snapshot is considered fresh if younger than `max_age_minutes` (default 5).

### 4.5 Throttling / rate limits

- **Minimum interval between cache updates:** 60 seconds (in `portfolio_cache`).  
- **Exchange sync interval:** 5 seconds; each cycle may or may not call `update_portfolio_cache()` depending on cache age.  
- No explicit rate limiting for Crypto.com is implemented in the described code; respect exchange API limits externally.

---

## 5. Failure Modes

### 5.1 Missing exchange credentials

- **Condition:** `resolve_crypto_credentials()` returns None for key or secret.  
- **Logs:** e.g. `[PORTFOLIO_SNAPSHOT] Missing credentials: ['EXCHANGE_CUSTOM_API_KEY', 'EXCHANGE_CUSTOM_API_SECRET']`, or in portfolio_cache “No credentials found via resolver”.  
- **API:**  
  - `/api/portfolio/snapshot`: returns 200 with `ok: false`, `missing_env: [list]`, empty positions.  
  - `/api/dashboard/state`: may return empty portfolio or trigger live fetch which raises `ValueError` and can surface as empty/error state.  
- **Diagnosis:** Check env vars: `EXCHANGE_CUSTOM_API_KEY`, `EXCHANGE_CUSTOM_API_SECRET` (or alternate pairs).  
- **Fix:** Set both in environment (or in runtime.env / secrets) and restart backend.

### 5.2 IP not whitelisted

- **Condition:** Exchange returns 401 with code 40103.  
- **Logs:** “IP not whitelisted (40103)”, “API authentication failed … Outbound IP: …”.  
- **API:** Live fetch raises `RuntimeError`; dashboard may return empty portfolio; `/api/portfolio/snapshot` returns `ok: false`, message about 40103.  
- **Diagnosis:** Compare outbound IP (e.g. from log or ipify) with Crypto.com API key IP allowlist.  
- **Fix:** Add server/egress IP to the key’s allowlist in Crypto.com Exchange settings.

### 5.3 Wrong key type / permissions

- **Condition:** 40101 or “Authentication failure”.  
- **Logs:** “Crypto.com API authentication failed”, “40101”, possible “Invalid API key/secret, missing Read permission…”.  
- **API:** Same as auth failure above.  
- **Diagnosis:** Confirm key is for Exchange (not only App), has Read (and if needed Trade) permissions, and is active.  
- **Fix:** Create or use an Exchange API key with correct permissions and use it in env.

### 5.4 Wrong account context

- **Condition:** Key is for a different account or environment (e.g. sandbox vs prod).  
- **Logs:** 401 or empty/incorrect data.  
- **Diagnosis:** Verify `EXCHANGE_CUSTOM_BASE_URL` and that the key matches the intended environment.  
- **Fix:** Set correct base URL and credentials for the account you want.

### 5.5 Empty result from API

- **Condition:** 200 OK but no accounts or empty list.  
- **Logs:** “user-balance returned 0 accounts”, “No accounts extracted”, fallback to get-account-summary may be tried.  
- **API:** Portfolio returns empty assets and total 0.  
- **Diagnosis:** Check account has balances on Exchange; confirm API returns data for this key (e.g. in Postman).  
- **Fix:** Use correct account/key; if using proxy, ensure proxy returns real data.

### 5.6 DB missing tables

- **Condition:** `portfolio_balances` or `portfolio_snapshots` missing.  
- **Logs:** SQL errors on query/insert in portfolio_cache.  
- **API:** Dashboard or portfolio endpoints can 500 or return empty.  
- **Diagnosis:** Inspect DB for presence of `portfolio_balances`, `portfolio_snapshots`.  
- **Fix:** Restart backend so `Base.metadata.create_all` runs (after `import app.models`), or create tables manually from the model definitions.

### 5.7 Exchange returns 200 but empty data

- **Condition:** Response has no `accounts` / no `data` / empty arrays.  
- **Logs:** “No balance data received”, “0 accounts”, “No accounts extracted”.  
- **API:** Empty portfolio.  
- **Diagnosis:** Log response shape (e.g. `[CRYPTO_BALANCE_SHAPE]`); verify key and account type (Spot vs Margin, etc.).  
- **Fix:** Align key/account with the product that holds balances; if needed try fallback endpoint (get-account-summary) which may return a different shape.

---

## 6. How To Rebuild Portfolio From Zero

Assumptions: DB is reset or tables are dropped; backend container is recreated; exchange credentials are re-set.

### 6.1 Environment variables

Set at least:

- `EXCHANGE_CUSTOM_API_KEY` — Crypto.com Exchange API key.  
- `EXCHANGE_CUSTOM_API_SECRET` — Crypto.com Exchange API secret.  

Optional:

- `EXCHANGE_CUSTOM_BASE_URL` — e.g. `https://api.crypto.com/exchange/v1` (default).  
- `USE_CRYPTO_PROXY`, `CRYPTO_PROXY_URL`, `CRYPTO_PROXY_TOKEN` — if using proxy.  
- DB connection (e.g. `DATABASE_URL`) so the app can create/use tables.

### 6.2 Commands to run

1. **Database:** Ensure DB is up. If you recreated it, run migrations or table creation as used in your deployment (e.g. start backend once so `create_all` runs, and if you use `portfolio_loans`, run `run_migration.py` or equivalent for `PortfolioLoan`).  
2. **Backend:** Start the backend so that:  
   - `import app.models` runs and `Base.metadata.create_all(bind=engine)` creates `portfolio_balances` and `portfolio_snapshots`.  
   - Exchange sync starts and, after 15s, runs the first sync (which will call `update_portfolio_cache` when cache is empty).  
3. **Optional:** Create `portfolio_loans` if you use loans:  
   - `python run_migration.py` (or your script that runs `Base.metadata.create_all(bind=engine, tables=[PortfolioLoan.__table__])`).

### 6.3 Docker Compose

- Start the stack that runs the backend (e.g. `docker compose up -d backend` or your equivalent).  
- Ensure the same env vars are passed into the backend container (e.g. via `env_file` or `environment`).  
- After backend start, wait ~15–60 seconds for the first sync and cache update.

### 6.4 Verification endpoint

- **GET** `http://<backend_host>/api/dashboard/state`  
  - Check `response.portfolio.assets` (non-empty if balances exist) and `response.portfolio.total_value_usd`.  
- Or **GET** `http://<backend_host>/api/portfolio/snapshot`  
  - Check `ok === true`, `positions` length, `totals.total_value_usd`.

### 6.5 Logs that confirm success

- “Portfolio cache updated successfully. Raw assets: $…”, “Portfolio snapshot stored: … assets, total=$…”.  
- “Using fresh portfolio snapshot: … assets”, or “Portfolio summary loaded in …s”.  
- “[DASHBOARD_STATE_DEBUG] response_status=200 has_portfolio=true assets_count=…”.  
- No 401 or “Missing credentials” or “No balance data received” for the portfolio path.

---

## 7. Verification Checklist

- [ ] **Exchange auth:** No 40101/40103 in logs when calling `private/user-balance`; outbound IP is whitelisted if required.  
- [ ] **user-balance returns assets:** Logs show non-zero accounts or position_balances; no “0 accounts” unless account is truly empty.  
- [ ] **Portfolio endpoint:** GET `/api/dashboard/state` returns `portfolio.assets` with at least one asset and `portfolio.total_value_usd` > 0 (when you have balance).  
- [ ] **Snapshot endpoint (optional):** GET `/api/portfolio/snapshot` returns `ok: true` and `totals.total_value_usd` consistent with dashboard.  
- [ ] **Frontend:** Dashboard tab shows balances and total value matching the API response (and Crypto.com UI if applicable).

---

## Reference: Key File and Symbol Summary

| Item | Location |
|------|----------|
| Dashboard route | `backend/app/api/routes_dashboard.py`: `get_dashboard_state`, `_compute_dashboard_state` |
| Portfolio snapshot API | `backend/app/api/routes_portfolio.py`: `get_portfolio_snapshot`, `refresh_portfolio_snapshot`, `get_latest_portfolio` |
| Portfolio cache | `backend/app/services/portfolio_cache.py`: `get_portfolio_summary`, `update_portfolio_cache`, `get_cached_portfolio`, `get_last_updated` |
| Portfolio snapshot service | `backend/app/services/portfolio_snapshot.py`: `fetch_live_portfolio_snapshot`, `store_portfolio_snapshot`, `get_latest_portfolio_snapshot` |
| Crypto.com client | `backend/app/services/brokers/crypto_com_trade.py`: `CryptoComTradeClient`, `trade_client`, `get_account_summary`, `sign_request` |
| Credential resolver | `backend/app/utils/credential_resolver.py`: `resolve_crypto_credentials`, `get_missing_env_vars` |
| Exchange sync | `backend/app/services/exchange_sync.py`: `ExchangeSyncService`, `exchange_sync_service`, `start()`, `sync_balances`, `_run_sync_sync` |
| Constants | `backend/app/services/brokers/crypto_com_constants.py`: `REST_BASE` |
| Portfolio models | `backend/app/models/portfolio.py`: `PortfolioBalance`, `PortfolioSnapshot` |
| Portfolio snapshot data model | `backend/app/services/portfolio_snapshot.py`: `PortfolioSnapshotData` |
| Portfolio loans model | `backend/app/models/portfolio_loan.py`: `PortfolioLoan` |
| Frontend dashboard state | `frontend/src/app/api.ts`, `frontend/src/lib/api.ts`: `getDashboardState()`, `getPortfolio()` |
