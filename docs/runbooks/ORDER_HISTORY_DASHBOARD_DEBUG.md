# Order History → Dashboard Debug (Executed Orders Not Showing)

**Scope:** Executed orders only. This runbook does not cover portfolio or dashboard portfolio logic.

---

## Key facts

- **Executed orders come ONLY from `GET /api/orders/history`.**  
  The UI fetches that endpoint and then filters/renders the result.
- **`/api/dashboard/state` is NOT used for executed orders.**  
  It is used for open orders, balances, and other dashboard data—not for the Executed Orders tab.

So the only question: are orders in the DB and returned by the API but the frontend isn’t showing them, or are they not being stored / not returned?

---

## Run on EC2 (copy/paste ready)

All commands assume you are on the EC2 host where Docker and the backend run. Use a single symbol (e.g. `ATOM_USDT`) to isolate sync and read path.

### Step 1: Force sync for a single symbol

```bash
cd /home/ubuntu/automated-trading-platform
curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=10&offset=0&sync=true" | head -c 400
echo
```

### Step 2: DB count and sample rows

```bash
cd /home/ubuntu/automated-trading-platform
sudo docker exec -it automated-trading-platform-backend-aws-1 sh -lc '
python - << "PY"
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder
db = SessionLocal()
q = db.query(ExchangeOrder).filter(ExchangeOrder.symbol=="ATOM_USDT")
print("COUNT:", q.count())
for o in q.order_by(ExchangeOrder.created_at.desc()).limit(5):
    print(o.id, o.symbol, o.status, o.side, o.created_at)
db.close()
PY
'
```

### Step 3: API read path (no sync)

```bash
cd /home/ubuntu/automated-trading-platform
curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=5&offset=0&sync=false" | head -c 600
echo
```

**Alternative:** run the one-shot script (same three steps with section headers). On EC2, use `sudo` so docker access works. Make the script executable once with `chmod +x`.

```bash
cd /home/ubuntu/automated-trading-platform
chmod +x scripts/diag/order_history_four_checks.sh
sudo ./scripts/diag/order_history_four_checks.sh
```

Paste the full output to interpret below. **The DB step (Step 2) in the script is what removes all guessing** between sync not writing, API filter wrong, and frontend issue.

**Minimum (no script):** If you prefer not to run the script, paste the two curl outputs below. With only the two curls we can still infer a lot, but we cannot fully separate sync not writing, API filter wrong, and frontend issue without the DB count.

```bash
curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=10&offset=0&sync=true" | head -c 400
echo
curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=5&offset=0&sync=false" | head -c 800
echo
```

---

## 10-second decision

| Result | Meaning | Fix in |
|--------|--------|--------|
| **DB COUNT = 0** | Sync is not writing orders to DB | **(A)** Sync write path → `backend/app/services/exchange_sync.py` |
| **DB COUNT > 0** but **Step 3 returns empty** | API query or filter is wrong | **(B)** API read path → `backend/app/api/routes_orders.py` |
| **Step 3 returns orders** | Backend is fine; UI or request is wrong | **(C)** Frontend → endpoint, params, or tab filter logic |

---

## Expected outputs

### Step 1 (force sync)

- **Good:** JSON with `"ok": true` and an `"orders"` array (may be empty if no history for that symbol). No 5xx or connection error.
- **Bad:** Empty response, connection refused, 5xx, or JSON with `"orders": []` and no later steps showing DB/API data → suggests sync or exchange not returning data.
- **Inspect next:** If sync fails, check `exchange_sync.py` (sync path) and backend logs.

### Step 2 (DB count)

- **Good:** `COUNT: N` with N ≥ 0 and, if N > 0, a few lines with `id`, `symbol`, `status`, `side`, `created_at`.
- **Bad:** `COUNT: 0` after a successful Step 1 for a symbol that has history on the exchange → sync is not persisting to `ExchangeOrder`.
- **Inspect next:** `backend/app/services/exchange_sync.py` — sync and upsert into `ExchangeOrder`.

### Step 3 (API read, sync=false)

- **Good:** JSON with `"orders": [ ... ]` when DB has rows for that symbol; `count`/`total` consistent with data.
- **Bad:** `"orders": []` or missing `orders` while Step 2 shows COUNT > 0 → API filter or query bug.
- **Inspect next:** `backend/app/api/routes_orders.py` — `get_order_history` handler, filters (symbol, status), ordering, pagination.

If Step 3 is good but the Executed Orders tab is empty, the bug is in the frontend (wrong URL, params, or client-side filter).

---

## Code pointers by branch

### (A) Sync not writing

**File:** `backend/app/services/exchange_sync.py`

- `sync_order_history(db, page_size=..., max_pages=..., instrument_name=...)` — entry; when `instrument_name` is set, delegates to per-instrument sync.
- `sync_order_history_for_instrument(db, trade_client, instrument_name, ...)` — fetches for one symbol and upserts.
- `_fetch_order_history_windowed(...)` — time-windowed fetch for one instrument (Crypto.com needs narrow windows).
- `_fetch_range_subdivided(...)` — subdivides a time range (e.g. 1d → 1h → 5m → 1m) so the exchange returns data.
- ExchangeOrder upsert logic lives in `sync_order_history` (same file): build/update `ExchangeOrder` from API payload and commit.

### (B) API query / filter bug

**File:** `backend/app/api/routes_orders.py`

- Route: `GET /api/orders/history` → handler `get_order_history(limit, offset, sync, symbol, db)`.
- Query: `ExchangeOrder` filtered by `status.in_(executed_statuses)` where `executed_statuses = [FILLED, CANCELLED, REJECTED, EXPIRED]`; optional `symbol` filter; ordering by `exchange_update_time`/`updated_at`; pagination via `limit`/`offset`.
- If DB has rows but API returns empty, check: symbol filter (e.g. case or format), status list, or wrong table/column.

### (C) Frontend bug

- **API call:** `frontend/src/app/api.ts` — `getOrderHistory(limit, offset, sync)` → calls `GET /api/orders/history?limit=...&offset=...&sync=...` (no `symbol` in default call).
- **Hook:** `frontend/src/hooks/useOrders.ts` — `fetchExecutedOrders()` calls `getOrderHistory(100, 0, true)` and sets `executedOrders` state.
- **Tab:** `frontend/src/app/components/tabs/ExecutedOrdersTab.tsx` — uses `useOrders()` for `executedOrders` and `fetchExecutedOrders`; applies `orderFilter` (symbol, status, side, dates) and `hideCancelled`; renders the list.

Check: base URL, query params (e.g. adding `symbol` if needed), and tab filters that might hide all rows (e.g. status or symbol mismatch like `instrument_name` vs `symbol`).

---

## Common pitfalls

1. **Symbol vs instrument_name**  
   Our API and DB use `symbol` (e.g. `ATOM_USDT`). Crypto.com uses `instrument_name`. Backend maps when talking to the exchange; ensure the API and frontend use the same key for filtering (e.g. `symbol` in query, `instrument_name` in response for UI).

2. **Time window too wide returns 0**  
   Crypto.com’s private/get-order-history often returns empty when the requested time range is too large. The sync uses **per-instrument, time-windowed** requests (subdivided ranges). A single 180-day request without instrument can return nothing.

3. **Per-instrument windowing**  
   Sync must use `instrument_name` (symbol) and narrow time windows. Global history without symbol is unreliable. The runbook steps use `symbol=ATOM_USDT` so the backend runs per-instrument sync for that symbol.

4. **Status filtering**  
   Executed/terminal statuses in the API are: `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`. Open/active are `NEW`, `ACTIVE`, `PARTIALLY_FILLED`. If the API or UI filters by the wrong set (e.g. only `FILLED` or wrong casing like `CANCELED`), rows can disappear. Backend uses `OrderStatusEnum`; frontend must match (e.g. `filled` vs `FILLED` for display).

5. **`TypeError: get_order_history() got an unexpected keyword argument 'instrument_name'`**  
   The backend image was built from an old `crypto_com_trade.py` that does not accept `instrument_name`. Sync will fall back to calling without it (and may return empty). **Fix:** Ensure the repo on EC2 has the latest `backend/app/services/brokers/crypto_com_trade.py` (with `instrument_name` in `get_order_history`), then rebuild the backend image with `--no-cache`:  
   `docker compose --profile aws build --no-cache backend-aws && docker compose --profile aws up -d`.

---

## If you only do one thing

1. **Run the three steps above on EC2** (or `sudo ./scripts/diag/order_history_four_checks.sh`).
2. **Check Step 2:**  
   - COUNT = 0 → fix sync/upsert in `exchange_sync.py`.  
   - COUNT > 0 → go to Step 3.
3. **Check Step 3:**  
   - Empty response → fix query/filter in `routes_orders.py` `get_order_history`.  
   - Non-empty → backend is fine; fix frontend (URL, params, or filters in `useOrders` / `ExecutedOrdersTab`).

That narrows the bug to (A) sync write, (B) API read, or (C) frontend in under two minutes.
