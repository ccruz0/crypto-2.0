# Open Orders vs Trigger Orders – Diagnostic and Next Steps

## Why "No open orders" when you see a Trigger Order on Crypto.com

- The **dashboard "Open Orders" tab** shows orders from the **unified** cache (open + trigger merged).
- If the UI or API is effectively showing only **regular open orders**, you see "No open orders" while a **Trigger Order** (e.g. BTC/USD TP) still exists on the exchange.
- Confirm what the API returns, then apply the chosen UI change (Option A or B).

---

## 1) Confirm what the API returns (run on EC2)

**Auth check (optional, does not show open/trigger counts):**

```bash
cd /home/ubuntu/automated-trading-platform
sudo docker compose --profile aws exec backend-aws python /app/scripts/verify_crypto_auth_simple.py
```

**Explicit open vs trigger diagnostic (use this for counts):**

```bash
cd /home/ubuntu/automated-trading-platform
sudo docker compose --profile aws exec backend-aws python /app/scripts/diagnose_open_vs_trigger_orders.py
```

**What to look for in the output:**

- **Open orders:** `0` (no regular limit/market open orders).
- **Trigger orders:** `1` (your BTC/USD TP trigger).
- **Sample TRIGGER order keys:** e.g. `product_type`, `spot_margin`, or `instrument_name` to see if the order is Cross/margin (if the API filters spot-only, we may need to add margin in the request).

If `diagnose_open_vs_trigger_orders.py` is not in the image yet, rebuild the backend image (the script lives in `backend/scripts/` and is copied into the image).

---

## 2) Choose the UI change

**Option A (fastest)**  
- Keep the current **"Open Orders"** table.  
- Add a second table below it: **"Trigger Orders"**.  
- Backend already merges open + trigger into the cache; we may expose a dedicated trigger list or split the unified list by `is_trigger` so the second table has data.

**Option B (cleaner UX)**  
- One table with a filter: **All | Open | Trigger**.  
- Same data source; filter in the UI (and optionally an API flag) by open vs trigger.

Reply with:  
1) The **exact output** of `diagnose_open_vs_trigger_orders.py`  
2) Your choice: **Option A** or **Option B**  

Then the minimal patch (only the needed files) can be outlined.

---

## 3) If you see Open: 0, Trigger: 0 but you have a trigger order on the exchange

The backend may be **skipping** trigger orders because of a cached health check: if the API ever returned `40101` for `private/get-trigger-orders`, the code assumes "trigger orders not available" and returns empty without calling the API again (for 24h). Run the **raw trigger API** diagnostic below to see the real HTTP/code/message.

**On EC2 (single command):**

```bash
sudo docker compose --profile aws exec backend-aws python -c "
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.utils.http_client import http_post
c = CryptoComTradeClient()
method = 'private/get-trigger-orders'
params = {'page': 0, 'page_size': 200}
payload = c.sign_request(method, params)
if isinstance(payload, dict) and payload.get('skipped'):
    print('SKIPPED:', payload.get('reason', payload))
else:
    url = c.base_url.rstrip('/') + '/' + method
    r = http_post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10, calling_module='diagnostic')
    body = r.json() if r.text else {}
    print('Status:', r.status_code)
    print('Code:', body.get('code'))
    print('Message:', body.get('message'))
    data = (body.get('result') or {}).get('data') or []
    print('Trigger orders count:', len(data) if isinstance(data, list) else 0)
    if data and isinstance(data, list) and isinstance(data[0], dict):
        print('First order keys:', sorted(data[0].keys()))
"
```

- **Code 40101**: The Exchange rejects `private/get-trigger-orders` for this API key. The app now has a **fallback**: when 40101 is received, it calls `private/advanced/get-open-orders` and uses any trigger-type orders (STOP_LOSS, TAKE_PROFIT, etc.) from that response. Deploy the latest backend to use the fallback. If the advanced endpoint also returns 40101, check API key permissions in Crypto.com Exchange (e.g. enable “Advanced orders” or similar).
- **Code 0** and **Trigger orders count: 1**: The API returns your order; if the dashboard still showed 0 before, the fix was the health-check/fallback logic.

---

## 4) 40101 fix (implemented)

When `private/get-trigger-orders` returns **40101** (Authentication failure) for your API key:

1. **Health check**: The app now tries `private/advanced/get-open-orders`. If that returns 200 and code 0, trigger orders are treated as “available” via the fallback.
2. **get_trigger_orders**: On 40101 it calls `private/advanced/get-open-orders`, filters for trigger-type orders (STOP_LOSS, STOP_LIMIT, TAKE_PROFIT, TAKE_PROFIT_LIMIT), and returns them so the dashboard can show trigger orders.
3. **Unified order format**: `ref_price` from the advanced API is mapped to trigger price in the unified order model.

**What you need to do:** Deploy the updated backend to EC2 (rebuild and restart the backend container). After deploy, the open-orders sync and dashboard should show your BTC/USD TP trigger order if the advanced endpoint accepts your key. If you still see 0 trigger orders, check Crypto.com Exchange → API key settings for any “Advanced orders” or “Trigger orders” permission and enable it.

---

## 5) Why trigger orders can still be empty after the fallback

The advanced endpoint `private/advanced/get-open-orders` only returns **OTO/OTOCO** strategy orders (multi-leg). A **standalone** TP/SL (single order, not part of OTO/OTOCO) only appears in the legacy `private/get-trigger-orders`, which returns 40101 for your key. So the fallback cannot show standalone trigger orders. **Options:** (1) In Crypto.com Exchange, edit the API key and enable permission for trigger/conditional orders so the legacy endpoint is allowed. (2) Create TP/SL as OTO/OTOCO so they appear via the advanced endpoint.

---

## 6) Cross / spot note

If your Crypto.com trigger order shows **"Cross"** (margin/cross product), and our `get-trigger-orders` call is effectively **spot-only**, the API might return 0 trigger orders. The diagnostic script prints sample order keys; if the trigger order appears there, we know the API returns it. If you see 0 trigger orders on the API but 1 in the app, we may need to pass a product/spot_margin parameter for trigger orders (similar to order-history margin fallback).
