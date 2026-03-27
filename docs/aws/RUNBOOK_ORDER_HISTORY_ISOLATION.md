# Order History Empty — Isolate Root Cause

When portfolio/balances work but `get-order-history` and `get-trades` return 0, possible causes include:

1. **API key valid for balances but not authorized for trade history**
2. **Wrong environment (sandbox vs production)**
3. **Account has zero trades on Exchange** (trades were on App, or new Exchange account)
4. **Margin vs Spot**: Orders are **margin (Cross)** but we were only querying spot. Crypto.com UI shows "Margin Mode: Cross" on each row; the same `private/get-order-history` endpoint may return only spot by default. The backend now tries a **margin fallback** (`spot_margin=MARGIN`) when the default returns 0.

5. **Large time range returns empty**: `private/get-order-history` and `private/get-trades` return data **only** when `instrument_name` is set **and** the time window is narrow (e.g. ±6h or 7-day windows). A single 180-day request with no instrument, or with instrument but very wide range, often returns 0 even with correct signing. The backend now uses **per-instrument, time-windowed sync**: it fetches history per symbol (watchlist or default list) in 7-day windows, subdividing to 1-day or 1-hour when a window returns a full page to avoid truncation.

Use this runbook to isolate which one.

---

## Crypto.com Exchange UI — IP whitelist and key check

**AWS IP to whitelist:** **52.220.32.147** (logged as `CRYPTO_COM_OUTBOUND_IP` in backend). Whitelist this exact IP on the Crypto.com Exchange API key.

Do this in the Crypto.com Exchange UI:

1. **Switch to Main account**
2. **Orders → Order History** — confirm orders exist (or note which account has them)
3. **API Management** — create a new key in that same account if needed
4. **Whitelist 52.220.32.147** on the key
5. **Switch to each sub-account** you use and repeat: Order History check → API Management → whitelist 52.220.32.147

After checking, reply with exactly these three lines:

- **PdoQ key visible:** yes / no  
- **Orders are in:** main / &lt;sub-account name&gt;  
- **PdoQ key is in:** main / &lt;sub-account name&gt;

---

## When account context and IP are ruled out

If PdoQ key is in main, orders are in main, and 52.220.32.147 is whitelisted, remaining causes are:

- Backend is using a different key than you think
- Key permissions don’t include what the endpoint needs
- Wrong product scope or missing required params for the endpoint
- Exchange returns only a time window and we’re outside it

Do these in order.

### 1. Prove which key and which endpoints are used

On EC2:

```bash
sudo docker compose --profile aws logs backend-aws --tail 300 | grep -E "endpoint=/private/|Order history response|Spot instruments|spot_margin|margin fallback|get-order-history|get-trades"
```

- If you **only** see `private/get-order-history`, `private/get-trades`, and "Spot instruments", we are **not** calling any margin history path (old code or margin fallback disabled).
- If you see **"trying margin (spot_margin=MARGIN)"** and/or **"Order history margin fallback returned N orders"**, the margin path is active. Non-zero N means margin orders were fetched.

To confirm key suffix:

```bash
sudo docker compose --profile aws logs backend-aws --tail 200 | grep -E "key_suffix=|CRYPTOCOM_AUTH.*get-order-history" | tail -n 30
```

Confirm the suffix is still **PdoQ** on the order-history calls.

### 2. Check key permissions in Crypto.com UI

Open the API key and confirm:

- **Read** permission for Orders / Trades (not just Balance)
- If there is a separate toggle for “Trading history” or “Orders”, enable it
- If there is an “IP whitelist” mode, ensure it’s enabled and includes **52.220.32.147**

If not 100% sure, create a new key in the same main account with:

- Read balances
- Read orders/trades
- (Optional) trading disabled for safety during testing
- Whitelist **52.220.32.147**

### 3. Force a minimal direct API test from EC2

Bypasses our parsing and proves what the Exchange returns. **Signing must match the backend**: Crypto.com expects `method + id + api_key + params_str + nonce` with `id=1`; params string is key+value concatenation (sorted keys), not JSON.

**Option A — If the script exists in the repo on EC2** (after `git pull`):

```bash
docker exec -it automated-trading-platform-backend-aws-1 python scripts/run_order_history_raw_test.py
```

The script calls (1) `private/get-order-history` with `limit=20` (default/spot), (2) `private/get-order-history` with `limit=20` and **`spot_margin=MARGIN`** (margin), (3) `private/get-trades` with `limit=20`. For each it prints `http=`, `code=`, `data_len=`, and `first_order_keys=`. **If default/spot has `data_len=0` and margin has `data_len>0`**, your orders are margin (Cross) and the backend margin fallback should return them after sync.

**Option B — Inline test (no file needed)**  
Use this when `backend/scripts/run_order_history_raw_test.py` is not on the host (script was never committed or not yet pulled). Run **on EC2**:

```bash
sudo docker exec -it automated-trading-platform-backend-aws-1 sh -lc 'python - << "PY"
import os, time, hmac, hashlib, requests

BASE = (os.getenv("EXCHANGE_CUSTOM_BASE_URL") or "https://api.crypto.com/exchange/v1").rstrip("/")
KEY  = os.getenv("EXCHANGE_CUSTOM_API_KEY") or ""
SEC  = os.getenv("EXCHANGE_CUSTOM_API_SECRET") or ""

print("BASE:", BASE)
print("KEY set:", bool(KEY), "SECRET set:", bool(SEC))

def params_to_str(params):
    if not params: return ""
    s = ""
    for k in sorted(params.keys()):
        s += str(k) + str(params[k])
    return s

def call(method, params=None):
    params = params or {}
    nonce = int(time.time() * 1000)
    rid = 1
    sig_payload = f"{method}{rid}{KEY}{params_to_str(params)}{nonce}"
    sig = hmac.new(SEC.encode(), sig_payload.encode(), hashlib.sha256).hexdigest()
    body = {"id": rid, "method": method, "api_key": KEY, "params": params, "nonce": nonce, "sig": sig}
    r = requests.post(f"{BASE}/{method}", json=body, timeout=30)
    j = r.json()
    data = j.get("result", {}).get("data", None)
    data_len = len(data) if isinstance(data, list) else None
    code_val = j.get("code")
    msg_val = j.get("message")
    print(f"{method}: http={r.status_code} code={code_val} data_len={data_len} message={msg_val}")
call("private/get-order-history", {"limit": 20})
call("private/get-order-history", {})
call("private/get-trades", {"limit": 20})
PY'
```

Reply with the three lines that start with `private/get-order-history:` and `private/get-trades:`.

**If you get HTTP 200, code=0, but data_len=0:**  
Crypto.com defaults to a **1-day window** when `start_time`/`end_time` are omitted. The backend is updated to send a 180-day window for page 0. If the container is still old code, you will see only `params: ['limit']` in logs.

**Prove whether the patch is deployed (on EC2):**

```bash
sudo docker compose --profile aws logs backend-aws --tail 200 | grep -E "Order history API:.*get-order-history|params.*page="
```

You want to see **params including** `start_time` and `end_time` (e.g. `params=['limit', 'start_time', 'end_time']` or similar). If you still see only `['limit']`, the container is running old code.

**Force the new code into the running container (on EC2):**

```bash
cd /home/ubuntu/crypto-2.0
git pull --rebase origin main   # or your deploy branch
git log -1 --oneline
sudo docker compose --profile aws build --no-cache backend-aws
sudo docker compose --profile aws up -d --force-recreate backend-aws
```

Then trigger sync and re-check the params line:

```bash
curl -s "http://127.0.0.1:8002/api/orders/history?limit=10&offset=0&sync=true"
sudo docker compose --profile aws logs backend-aws --tail 200 | grep -E "Order history API:.*get-order-history|params.*page="
```

### 4. If raw calls are empty — check time window

Some exchanges default to “recent only”. Try adding a wider window if the API supports it (e.g. `start_ts`, `end_ts`, `from_ts`, `to_ts`). Adapt the test using the API docs or response/error fields.

### 5. If raw calls return data — our parsing is wrong

Then the broker layer needs to be patched to match the actual response shape.

**Reply with only this (redact nothing else; the script does not print secrets):**

- The two `HTTP …` lines and the first 300–600 characters of each response body from step 3.

---

## Step 1 — Confirm which account the key belongs to

On EC2:

```bash
docker logs --since 5m automated-trading-platform-backend-aws-1 \
  | grep -iE "account|subaccount|uid|exchange|base_url|Order history API"
```

Confirm:

- Base URL is `https://api.crypto.com/exchange/v1` (production)
- Log line shows `env=production` (not sandbox)
- No subaccount in the path unless intended

---

## Step 2 — Direct API test (outside your backend)

Removes the app from the equation. On your laptop or EC2, call the Exchange API with the same key/secret (curl + HMAC or a small script).

Call:

- `private/get-account-summary` (or `private/user-balance`)
- `private/get-trades` (params: `{"limit": 10}` or `{}`)
- `private/get-order-history` (params: `{"limit": 10}` or `{}`)

If **get-account-summary returns balances** but **get-trades and get-order-history return empty arrays** → Exchange/API-side limitation (key or account).

Signing: use the same method as the backend (method + id + api_key + params_str + nonce, HMAC-SHA256). You can run a one-off Python script that uses the same signing logic and prints raw responses.

---

## Step 3 — Check Crypto.com API permissions

In **Crypto.com Exchange** (exchange.crypto.com):

**User → API Management**

Verify the key has:

- **Read**
- **Trade**
- **Read Orders / Read Trades** (if shown separately)
- **Correct IP whitelisted** (EC2 outbound IP)

Often: balance works, trade history needs an extra permission or a key created after a feature change.

---

## Step 4 — Exchange vs App

**Crypto.com App ≠ Crypto.com Exchange.**

- Trades done in the **mobile App** do **not** appear in Exchange API.
- Only trades executed on **exchange.crypto.com** show in `private/get-trades` and `private/get-order-history`.

If all activity was in the App, empty history from the Exchange API is expected.

---

## Step 5 — Interpret backend logs

After a sync, check:

```bash
curl -s -o /dev/null "http://127.0.0.1:8002/api/orders/history?limit=10&offset=0&sync=true"
sudo docker compose --profile aws logs backend-aws --tail 200
```

Look for:

- **"Order history API: base_url=... env=production"** → hitting production Exchange.
- **"Trying get-trades fallback"** → backend tried get-trades.
- **"get-trades fallback: API returned 0 trades"** → API returned empty; backend is behaving correctly.

If you see **env=production**, **Trying get-trades fallback**, and **API returned 0 trades** → the API is returning empty; the issue is key/account/environment or Exchange vs App, not your code.

---

## Quick decisive test

1. On EC2:  
   `curl -s "http://127.0.0.1:8002/api/orders/history?limit=10&offset=0&sync=true"`
2. Immediately:  
   `sudo docker compose --profile aws logs backend-aws --tail 200`
3. Check:
   - Balances (e.g. get-account-summary or portfolio) > 0
   - get-order-history and get-trades both return 0

If **balances > 0** and **trades = 0** → issue is outside your code (key, permissions, or Exchange vs App).

---

## Per-instrument time-windowed sync (why large ranges return 0)

Crypto.com Exchange API often returns **empty** for `private/get-order-history` and `private/get-trades` when:

- No `instrument_name` is sent, or
- The time range is very wide (e.g. 180 days in one request).

**We do not use a single 180-day global request.** We sync **per instrument** using **narrow time windows**: 7-day windows by default, subdividing to 1 day → 1 hour → 5 min → 1 min when a window returns a full page (to avoid truncation). If a 1-minute window still returns a full page, we log **WARNING: window still full at 1m; may be truncating** and continue. Multi-symbol sync is capped at 20 symbols per run with rotation: **cursor is stored in Postgres** (table `sync_order_history_cursor`, one row, row lock for multi-worker safety) so it survives container restart. If the DB cursor fails, we fall back to a file at `ORDER_HISTORY_SYNC_CURSOR_PATH` (default `/tmp/order_history_sync_cursor`); for file fallback to survive restart, set that env var to a path on a mounted volume and use fcntl lock for multi-worker safety. A 200 ms sleep between symbols keeps you under rate limits.

### Trigger per-instrument sync from the API

- **One symbol** (dashboard filter or manual):  
  `GET /api/orders/history?sync=true&symbol=ATOM_USDT`  
  This calls `sync_order_history(instrument_name="ATOM_USDT")`, which uses `sync_order_history_for_instrument` and windowed fetch.

- **All symbols** (watchlist or default list):  
  `GET /api/orders/history?sync=true`  
  (no `symbol`) — syncs each watchlist symbol (or `BTC_USDT`, `ETH_USDT`, `BCH_USDT`, `ATOM_USDT` if watchlist is empty) with windowed fetch per instrument.

### Inspect windowed sync logs on EC2

Include the exchange call signature so you confirm `instrument_name` is always sent during sync:

```bash
# After triggering sync (e.g. curl .../orders/history?sync=true&symbol=ATOM_USDT)
sudo docker compose --profile aws logs backend-aws --tail 400 \
  | grep -E "get-order-history params_keys=|Order history window fetch|Order history window result|subdivide|WARNING" \
  | tail -n 120
```

You should see:

- `get-order-history params_keys=[..., 'instrument_name', ...]` — confirms instrument is included on each call.
- `Order history window fetch: instrument=ATOM_USDT start_ms=... end_ms=... window_days=7 limit=100`
- `Order history window result: instrument=ATOM_USDT fetched=N stored=M`
- If a 1m window is still full: `WARNING: ... window still full at 1m; may be truncating ...`

No secrets are logged; only param keys, instrument name, and timestamps.

### Run the windowed fetch verification script (container)

From the repo root (or EC2 after pull):

```bash
# By instrument (6h window around now)
docker exec -it automated-trading-platform-backend-aws-1 python scripts/test_order_history_windowed.py ATOM_USDT

# By order_id: uses get-order-detail to get instrument + create_time, then 6h window around create_time
docker exec -it automated-trading-platform-backend-aws-1 python scripts/test_order_history_windowed.py --order-id YOUR_ORDER_ID
```

This calls the broker with a 6h window and prints `fetched=N`. Use to confirm the API returns data for a narrow window and one instrument.

### EC2 verification after deploy (single-symbol + DB check)

1. **Single-symbol test via API**

   ```bash
   curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=10&offset=0&sync=true" | head -c 300
   echo
   ```

2. **Confirm window logs and that instrument_name is in params**

   ```bash
   sudo docker compose --profile aws logs backend-aws --tail 400 \
     | grep -E "get-order-history params_keys=|Order history window fetch|Order history window result|subdivide|WARNING" \
     | tail -n 120
   ```

   You want to see `params_keys` including `instrument_name` on those calls.

3. **Confirm DB has orders for that symbol**

   This repo uses `from app.database import SessionLocal`. If you get `ImportError`, try `from app.db.session import SessionLocal` instead.

   ```bash
   sudo docker exec -it automated-trading-platform-backend-aws-1 sh -lc '
   python - << "PY"
   from app.database import SessionLocal
   from app.models.exchange_order import ExchangeOrder
   db = SessionLocal()
   print("ATOM_USDT orders:", db.query(ExchangeOrder).filter(ExchangeOrder.symbol=="ATOM_USDT").count())
   db.close()
   PY
   '
   ```

   If that count is > 0, the dashboard should show executed orders for that symbol.

4. **If DB count > 0 but dashboard still shows empty**

   Then the issue is not sync but how the dashboard queries or filters. Check:

   - Symbol format (e.g. `ATOM_USDT` vs `ATOM/USDT`)
   - Status mapping (FILLED vs CANCELLED vs PARTIALLY_FILLED)
   - Different DB/schema for write vs read

   **Fast validation** — if this returns orders, the API route and DB read path are correct; the dashboard issue is aggregation/filtering:

   ```bash
   curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=5&offset=0&sync=false" | head -c 500
   echo
   ```

   If you paste the output of steps 1–3 plus this grep and the sync=false curl, you can see which branch you’re in and what to change next.

---

## If you want to be 100% sure

1. Create a **new** API key in Crypto.com Exchange.
2. Enable **all** read + trade permissions; whitelist EC2 IP.
3. Update credentials via the dashboard modal (or secrets); restart backend.
4. Run sync again.

If the **new** key returns trades, the previous key was limited. If it still returns 0, the account has no trades on Exchange (or only on App).

---

## What each log outcome means

### Case A — Wrong environment

You see:
- `Order history API: base_url=... env=check_base_url`  
  or  
- `base_url=https://uat-api.crypto.com`

Then you are **not** hitting production Exchange.

**Fix:** Set `EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1`, recreate backend, retest.

---

### Case B — Production, both endpoints return 0

You see:
- `Order history API: base_url=https://api.crypto.com/exchange/v1 env=production`
- `Trying get-trades fallback (private/get-trades with limit=...)`
- `get-trades fallback: API returned 0 trades`

Meaning: code is correct, auth works, API calls succeed, Exchange returns empty arrays.

Only two possibilities left:
1. This Exchange account has never placed trades.
2. Trades were done in the **Crypto.com App**, not Exchange. (App trades do **not** appear in Exchange API.)

Infrastructure is fine.

---

### Case C — Fallback fails

You see:
- `Trying get-trades fallback`
- `get-trades fallback failed: <error>`

Then: key may lack “Read Trade History”, wrong IP whitelist, or subaccount with restricted scope.

---

### Critical distinction

| System               | Where              | Shows in Exchange API? |
|----------------------|--------------------|-------------------------|
| Crypto.com App       | mobile app         | No                      |
| Crypto.com Exchange  | exchange.crypto.com| Yes                     |

If trades were executed in the App → Exchange API will always return 0.

---

### Fastest final test

Log into **https://exchange.crypto.com** → Order History / Trade History.

- If it shows **0** there → API returning 0 is correct.
- If it shows **trades** there but API returns 0 → permission issue on API key.

---

### Absolute certainty

Create a **new** Exchange API key (all read + trade, whitelist IP), replace credentials in the modal, restart backend, trigger sync. If the new key returns trades, the previous key was restricted.

---

## Margin vs Spot order history (root cause and fix)

**Root cause (when UI shows orders with "Margin Mode: Cross" but API returns 0):**  
We were calling only `private/get-order-history` (and `private/get-trades`) without requesting **margin** orders. Crypto.com Exchange can return **spot** history by default and margin (Cross) orders only when requested (e.g. with `spot_margin=MARGIN`). So the dashboard was "correct" but showed 0 because we never queried margin history.

**Evidence:**  
- Backend logs show "Spot instruments" fallbacks and get-trades, all returning 0.  
- Crypto.com UI shows many orders and every row has "Margin Mode: Cross".  
- No margin-specific endpoint or param was used before the fix.

**Fix (minimal, backward compatible):**  
When the default get-order-history path (and empty-params, spot-instrument, and get-trades fallbacks) all return 0, the backend now tries one more time with **`spot_margin=MARGIN`** on `private/get-order-history`. If that returns data, we use it and log `Order history margin fallback returned N orders`.

**EC2 — rebuild, restart, validate:**

```bash
cd /home/ubuntu/crypto-2.0
git pull --rebase origin main
git log -1 --oneline
sudo docker compose --profile aws build --no-cache backend-aws
sudo docker compose --profile aws up -d --force-recreate backend-aws
```

Then validate:

```bash
# Trigger sync
curl -s "http://127.0.0.1:8002/api/orders/history?limit=10&offset=0&sync=true"

# Confirm margin path was tried and/or returned data
sudo docker compose --profile aws logs backend-aws --tail 300 | grep -E "spot_margin|margin fallback|Order history response|data_len="
```

**Expected logs when margin fix is active:**  
- `Order history empty for default/spot; trying margin (spot_margin=MARGIN) params_keys=[...]`  
- If margin returns data: `Order history margin fallback returned N orders (spot_margin=MARGIN)`  
- `Order history response: code=0 ... data_len=N` with N > 0 after margin fallback

**Validate margin vs spot with raw script (inside backend container):**

```bash
docker exec -it automated-trading-platform-backend-aws-1 python scripts/run_order_history_raw_test.py
```

Interpret: if the line for `(default/spot)` has `data_len=0` and the line for `(spot_margin=MARGIN)` has `data_len>0`, your orders are margin and the backend margin fallback will fetch them.

---

## Summary

| Log / check | Meaning |
|-------------|--------|
| `base_url=...exchange/v1` + `env=production` | Using production Exchange |
| `Trying get-trades fallback` | Backend attempted get-trades |
| `get-trades fallback: API returned 0 trades` | API returned empty; backend correct |
| `trying margin (spot_margin=MARGIN)` | Backend attempted margin order history |
| `Order history margin fallback returned N orders` | Margin path returned N orders (N > 0) |
| Balances work, order/trade history empty | Key or account limitation, Exchange vs App, or margin vs spot |

**Paste these lines from your logs** and you can assign the branch in one go:
1. `Order history API: base_url=...`
2. `Trying get-trades fallback` and/or `trying margin (spot_margin=MARGIN)`
3. `get-trades fallback: API returned N trades` and/or `Order history margin fallback returned N orders`

At that point the infrastructure is correct; the remaining levers are key permissions, environment, where the trades were executed (Exchange vs App), and margin vs spot (margin fallback addresses the latter).

---

## When user-balance and get-open-orders work but get-order-history / get-trades return empty

That combo usually means:
1. **Different account context** — orders in account A, API key in account B (main vs sub-account).
2. **Key restricted** — key allows balances and open orders but not historical endpoints.

### A) Match the key in the UI

In Crypto.com Exchange → API Management, find the key whose last 4 chars match what the backend uses (e.g. `…PdoQ`). If you don’t see that key there, you’re using a different key than you think. Create a new key from the **same account where you see orders**.

**If you can’t find the suffix in the UI:** Crypto.com may show only a label, only the first characters, or hide the suffix until you open details. Open each API key entry and look for “API Key” full value or “Key ID”. If the UI never shows the last 4 chars, create a **temporary** new key in the UI → put it in `secrets/runtime.env` → restart backend → check the log line `key_suffix=....`; that tells you which UI key the backend is using. Then restore your real key and use the suffix to match.

### B) Main vs Sub-account (most likely)

In the Exchange UI (top-right), switch between **Main** and any **Sub-accounts**. In each:
- **Orders → Order History** — which account has the orders?
- **API Management** — which account has the key ending in e.g. `PdoQ`?

If orders are in account A and the key is in account B, that explains empty history.

**Fix:** Create a new key **inside the account that has the orders**. Whitelist `52.220.32.147` (or your `CRYPTO_COM_OUTBOUND_IP`). Update `secrets/runtime.env` with the new key/secret. Restart backend.

### C) Outbound IP to whitelist

Use the IP your backend uses (e.g. from logs: `CRYPTO_COM_OUTBOUND_IP: 52.220.32.147`). Whitelist exactly that IP in the key’s IP whitelist.

### D) Decisive test (no code)

In the Exchange UI, **export Order History as CSV**. If the export shows orders but the API with key `…PdoQ` returns empty, it’s account/key scope.

### If orders exist in the UI but API still returns empty

Almost always **account context**: orders live in one account (main or sub), the API key in another. Use the checklist: **Orders are in** (main / sub) vs **Key is in** (main / sub). If they don’t match → create a new key **in the account that has the orders**, whitelist **52.220.32.147**, update `secrets/runtime.env`, restart backend.

### Reply format to close the loop

After checking the UI, reply with **exactly** these three lines (as in the runbook):
- **PdoQ key visible:** yes / no  
- **Orders are in:** main / &lt;sub-account name&gt;  
- **PdoQ key is in:** main / &lt;sub-account name&gt;

---

## Per-instrument debug

When the Exchange returns empty for **global** order history but orders exist in the UI (e.g. Margin/Cross), the backend supports **per-instrument** history so you can confirm the correct params are sent and data is returned.

### 1. EC2 command — request history for one symbol with sync

```bash
curl -s "http://127.0.0.1:8002/api/orders/history?symbol=BCH_USDT&limit=10&offset=0&sync=true"
```

- **With `symbol` + `sync=true`:** backend calls `private/get-order-history` (and fallbacks) with `instrument_name=BCH_USDT`.
- **Without `symbol`:** backend uses the same endpoint but does **not** send `instrument_name` (global history).

### 2. Log grep — confirm instrument_name is passed

On EC2 after triggering the request above:

```bash
sudo docker compose --profile aws logs backend-aws --tail 250 | grep -E "params_keys=|endpoint=/private/get-order-history|get-trades"
```

**Expected:**

- **Without `symbol`:**  
  - `get-order-history params_keys=['end_time', 'limit', 'start_time']` → **params_count = 3** (limit, start_time, end_time).
- **With `symbol=BCH_USDT`:**  
  - `get-order-history params_keys=['end_time', 'instrument_name', 'limit', 'start_time']` → **params_count = 4** (plus instrument_name).
- If the get-trades fallback runs:  
  - `get-trades params_keys=[...]` should include `instrument_name` when the request was per-symbol.
- Sync log:  
  - `Starting order history sync: ... instrument_name=BCH_USDT` (or `instrument_name=None` when no symbol).

If you see **params_count 4** and `instrument_name` in the keys when using `?symbol=BCH_USDT&sync=true`, the per-instrument path is active and you can use it to verify that the Exchange returns data for that instrument.
