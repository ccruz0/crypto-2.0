# Order History Sync – Deploy & Capture Diagnostic

Use this after the **order history response parsing + diagnostic logging** change in `backend/app/services/brokers/crypto_com_trade.py` to see why the Exchange returns 0 orders.

## 1. On your machine: commit and push (if not already)

```bash
cd /Users/carloscruz/automated-trading-platform
git add backend/app/services/brokers/crypto_com_trade.py
git status
git commit -m "fix: order history response parsing and add diagnostic logging"
git push
```

## 2. On EC2: pull, rebuild backend, restart

```bash
cd ~/automated-trading-platform   # or your repo path on EC2
git pull

# Rebuild only the backend-aws image and recreate the container
sudo docker compose --profile aws build --no-cache backend-aws
sudo docker compose --profile aws up -d --force-recreate backend-aws
```

## 3. Trigger order history sync

- **Option A – Dashboard:** Open the dashboard → **Executed Orders** tab (with sync enabled), or use any “Sync order history” / “Refresh” that calls the orders API with `sync=true`.
- **Option B – API:** From your machine or EC2:
  ```bash
  curl -s -X GET "https://YOUR_DASHBOARD_HOST/api/orders/history?limit=10&offset=0&sync=true"
  ```
  (Replace `YOUR_DASHBOARD_HOST` with your real dashboard host if calling from outside; from EC2 you can use `http://localhost:PORT` or the internal backend URL.)

## 4. Capture the diagnostic log line

On EC2:

```bash
sudo docker compose --profile aws logs backend-aws --tail 200 | grep -i "Order history response"
```

You should see a line like:

```text
Order history response: result_keys=[...] result.result_keys=[...] data_type=... data_len=...
```

- **result_keys** / **result.result_keys**: show the actual API response shape.
- **data_type** / **data_len**: show whether we got a list and how many orders.

## 5. Interpret and next steps

- If **data_len > 0**: parsing is working; if the Executed Orders tab is still empty, the issue is likely in DB write or frontend.
- If **data_len = 0** and **result.result_keys** is e.g. `['data']`: the API is returning an empty list; check date range, API key scope (Exchange vs App), and that the key has “Order history” / “Read” permission.
- If the log line is missing: the request might be skipped (e.g. non-AWS), or an exception occurs before the log; check for errors:
  ```bash
  sudo docker compose --profile aws logs backend-aws --tail 300 | grep -E "order history|get_order_history|Error|401|Unexpected"
  ```

Share the **Order history response:** log line (and any nearby errors) to continue debugging.
