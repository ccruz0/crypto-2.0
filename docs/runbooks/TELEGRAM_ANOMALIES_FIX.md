# Fix Telegram Anomalies

When you receive Telegram alerts for these anomalies, use this runbook.

**Important:** The fix scripts need the backend container + PostgreSQL. From your **Mac**, use the SSM script. Do **not** run `fix_telegram_anomalies.sh` locally — it will fail (no watchlist_items table in local SQLite).

## 1. AUTOMATIC ORDER CREATION FAILED (Amount USD not configured)

**Symptom:** `El campo 'Amount USD' no está configurado para BTC_USD`

**Fix:** Set `trade_amount_usd` for the symbol in the watchlist.

### Option A: Via script (recommended)

```bash
# On the server (or via SSM)
./scripts/fix_telegram_anomalies.sh

# Custom amount (default: 50 USD)
BTC_AMOUNT_USD=100 ./scripts/fix_telegram_anomalies.sh
```

### Option B: Via Dashboard

1. Open Dashboard → Watchlist
2. Find the symbol (e.g. BTC_USD)
3. Click on "Amount USD" column, enter the desired amount (e.g. 50)
4. Save

### Option C: Direct DB script (inside container)

```bash
docker compose --profile aws exec backend-aws python scripts/set_watchlist_trade_amount.py BTC_USD 50
```

---

## 2. Scheduler Inactivity

**Symptom:** `Anomaly detected: Scheduler Inactivity` — `scheduler cycle not seen within expected interval`

**Fix:** Run one agent scheduler cycle to seed the activity log. The in-process loop should then continue.

### Option A: Via script (recommended)

```bash
# On the server
./scripts/fix_telegram_anomalies.sh

# Or just the scheduler part
./scripts/run_notion_task_pickup.sh
```

### Option B: Via SSM (from your Mac)

```bash
./scripts/fix_telegram_anomalies_via_ssm.sh
```

### Option C: Manual (inside container)

```bash
docker compose --profile aws exec backend-aws python scripts/run_agent_scheduler_cycle.py
```

---

## Root causes

| Anomaly | Cause |
|---------|-------|
| Amount USD | Symbol has `trade_enabled=true` but `trade_amount_usd` is null |
| Scheduler Inactivity | Agent activity log has no `scheduler_cycle_started` in 15+ min. Can occur if NOTION_API_KEY/NOTION_TASK_DB not set (agent loop never starts), or log file not writable |

---

## Verify NOTION keys (for Scheduler Inactivity)

If the anomaly persists after running the fix, ensure the backend has:

```bash
# In secrets/runtime.env on the server (see secrets/runtime.env.example)
# NOTION_API_KEY and NOTION_TASK_DB must be set
```

Then restart the backend:

```bash
docker compose --profile aws restart backend-aws
```
