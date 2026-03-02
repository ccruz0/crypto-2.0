# Order History Empty — Isolate Root Cause

When portfolio/balances work but `get-order-history` and `get-trades` return 0, only three causes are realistic:

1. **API key valid for balances but not authorized for trade history**
2. **Wrong environment (sandbox vs production)**
3. **Account has zero trades on Exchange** (trades were on App, or new Exchange account)

Use this runbook to isolate which one.

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

## If you want to be 100% sure

1. Create a **new** API key in Crypto.com Exchange.
2. Enable **all** read + trade permissions; whitelist EC2 IP.
3. Update credentials via the dashboard modal (or secrets); restart backend.
4. Run sync again.

If the **new** key returns trades, the previous key was limited. If it still returns 0, the account has no trades on Exchange (or only on App).

---

## Summary

| Log / check | Meaning |
|-------------|--------|
| `base_url=...exchange/v1` + `env=production` | Using production Exchange |
| `Trying get-trades fallback` | Backend attempted get-trades |
| `get-trades fallback: API returned 0 trades` | API returned empty; backend correct |
| Balances work, order/trade history empty | Key or account limitation, or Exchange vs App |

At that point the infrastructure is correct; the remaining levers are key permissions, environment, and where the trades were executed (Exchange vs App).
