# Week 4: Pipeline Verification and No-Silent-Failure Contract

This document defines the end-to-end pipeline steps, PASS/FAIL evidence for each step, exact commands to run locally and on AWS, where to look for confirmation, and a short incident playbook.

## Pipeline steps (files and functions)

| Step | Description | Main files / functions |
|------|-------------|-------------------------|
| 1. Signal | Signal generation and evaluation | `signal_monitor.py`: `monitor_signals`, `_check_signal_for_coin`; `correlation_id` set in signal paths |
| 2. Decision | Buy/sell decision and throttle | `signal_monitor.py`: decision reason, throttle; `signal_order_orchestrator.py`: `create_order_intent` |
| 3. Order placement | Place order on exchange | `signal_monitor.py`: `_place_order_from_signal`; `brokers/crypto_com_trade.py`: create order |
| 4. Persistence | DB write (orders, intents) | `exchange_sync.py`: `sync_order_history`, `sync_open_orders`; `OrderIntent`, `ExchangeOrder` |
| 5. Notifications | Telegram alerts and fill notifications | `telegram_notifier.py`: `send_executed_order`, send_message; `exchange_sync.py`: FILL_NOTIFICATION audit log |
| 6. Reconciliation | Order history sync, SL/TP, reconciler | `exchange_sync.py`: `sync_order_history`; `reconciler.py`; `protection_order_service.py` |
| 7. UI / admin | Health and diagnostics | `routes_monitoring.py`: `/health/system`; `routes_diag.py`: `/diag/pipeline`; `scripts/run_pipeline_diagnostics.py` |

## PASS/FAIL evidence per step

- **Step 1 (Signal):** Logs contain `[SIGNAL_MONITOR_TICK]`, `[SIGNAL_STATE]` with symbol and correlation_id. No uncaught exception in monitor cycle.
- **Step 2 (Decision):** Logs contain `[ORCHESTRATOR]` and order intent created or DEDUP_SKIPPED. DB: `order_intents` rows.
- **Step 3 (Order placement):** Logs contain order_id and "Order placed successfully" or explicit error. No silent exception.
- **Step 4 (Persistence):** `exchange_orders` has rows; `sync_order_history` runs without `[PIPELINE_FAILURE]` SYNC_ORDER_HISTORY. Logs show `[FILL_NOTIFICATION]` JSON (JSON-serializable).
- **Step 5 (Notifications):** `[TELEGRAM_API_CALL]` or `[ALERT_PERSIST]` in logs; `telegram_messages` rows when applicable.
- **Step 6 (Reconciliation):** `[RECONCILER]` or RECONCILER_RUN_SUMMARY in DB; no float–Decimal TypeError in sync.
- **Step 7 (UI/diagnostics):** `/health/system` returns global_status PASS/WARN/FAIL; diagnostics script prints OVERALL: PASS or FAIL.

## Commands to run

### Local

```bash
# 1) Run pipeline diagnostics (DB, system health, exchange public ping, Telegram config)
cd /Users/carloscruz/automated-trading-platform
PYTHONPATH=backend python3 scripts/run_pipeline_diagnostics.py
```

Expected: lines like `DB_CONNECT: PASS`, `MARKET_DATA: PASS`, `TELEGRAM: PASS`, `EXCHANGE_PING: PASS`, `OVERALL: PASS` (or FAIL with reason).

```bash
# 2) Run Week 3 + Week 4 targeted tests
cd /Users/carloscruz/automated-trading-platform/backend
python3 -m pytest tests/test_exchange_sync_order_history_decimal.py tests/test_pipeline_logging_week4.py -v
```

Expected: all tests pass.

```bash
# 3) Optional: pipeline diag endpoint (if backend is running)
curl -s http://localhost:8000/api/diag/pipeline | jq .
curl -s http://localhost:8000/health/system | jq .
```

### AWS (EC2)

```bash
# 1) SSH and go to repo
cd /home/ubuntu/automated-trading-platform

# 2) Identify backend container
docker ps

# 3) Run pipeline diagnostics inside backend container (or on host with backend env)
docker compose exec backend-aws python3 -c "
import sys; sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.services.system_health import get_system_health
from sqlalchemy import text
db = SessionLocal()
db.execute(text('SELECT 1'))
health = get_system_health(db)
for k, v in health.items():
    if isinstance(v, dict) and 'status' in v:
        print(k.upper(), v['status'])
db.close()
print('DB_CONNECT: PASS')
"
```

Or use the diagnostics script from host (if Python env has access to backend code):

```bash
cd /home/ubuntu/automated-trading-platform
PYTHONPATH=backend python3 scripts/run_pipeline_diagnostics.py
```

```bash
# 4) Tail logs by symbol (last occurrence)
./scripts/aws_tail_symbol_logs.sh backend-aws DOT_USDT
```

```bash
# 5) Tail logs by correlation_id (last occurrence, 60 lines context)
./scripts/aws_tail_correlation_logs.sh backend-aws <correlation_id>
```

```bash
# 6) Confirm no sync crash: search for pipeline failure and TypeError
docker compose logs backend-aws --tail=500 2>&1 | grep -E "PIPELINE_FAILURE|TypeError|sync_order_history"
```

Expected: no `TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`; any failure has a single-line `[PIPELINE_FAILURE]` with error_code and message.

## Where to look for confirmation

| What | Where |
|------|--------|
| Sync / order history errors | Backend logs: `[PIPELINE_FAILURE]`, `Error syncing order history` |
| Fill notifications | Backend logs: `[FILL_NOTIFICATION]` (JSON line) |
| Correlation ID for a request | Backend logs: grep correlation_id; or `scripts/aws_tail_correlation_logs.sh` |
| DB connectivity | Diagnostics script: `DB_CONNECT: PASS`; or `GET /health/system` |
| Exchange connectivity | Diagnostics script: `EXCHANGE_PING: PASS` (public get-instruments) |
| Telegram config | Diagnostics script: `telegram_config_ok: true`; health/system `telegram.status` |
| Pipeline health | `GET /api/diag/pipeline` (event_bus, reconciler, fills, protection counts) |

## Incident playbook (what to do if a step fails)

### Step 1 – Signal not firing

1. **No watchlist / alert disabled:** Check `watchlist` (or watchlist_master) for symbol, `alert_enabled` / `buy_alert_enabled` / `sell_alert_enabled`. Enable and re-run.
2. **Kill switch or throttle:** Check logs for `KILL_SWITCH`, `throttled`, `BLOCKED`. Check `RUN_TELEGRAM` and throttle windows.
3. **No price data:** Check `market_data` and market updater; ensure symbol has recent `MarketPrice` or API ticker.

### Step 4 – Persistence / sync crash

1. **Float–Decimal TypeError:** Fixed in Week 3; ensure `_to_decimal` and Decimal-only math in `sync_order_history`. If still present, check for any new quantity/price path not using `make_json_safe` or `_to_decimal`.
2. **DB connection / transaction:** Check DB connectivity (diagnostics script); check for rollback after exception in `sync_order_history`.
3. **Authentication (40101):** Check API credentials and IP allowlist for Crypto.com; logs will show "Authentication error when syncing order history".

### Step 5 – Notifications not sent

1. **Telegram disabled or wrong env:** Check `RUN_TELEGRAM`, `TELEGRAM_BOT_TOKEN_*`, `TELEGRAM_CHAT_ID_*` for the runtime (AWS vs local). Use diagnostics script `telegram_config_ok`.
2. **Fill dedup / should_notify_fill:** Logs show "Skipping notification" with notify_reason; check fill_dedup state and DB.
3. **JSON serialization error on audit log:** Ensure all audit logs go through `make_json_safe` (Week 4). Check for Decimal/datetime in payloads.

---

## Key log lines that confirm PASS

- `DB_CONNECT: PASS` – diagnostics script
- `EXCHANGE_PING: PASS` – diagnostics script
- `telegram_config_ok: true` – diagnostics script
- `[FILL_NOTIFICATION] {"event":"ORDER_EXECUTED_NOTIFICATION",...}` – JSON line, no TypeError
- `sync_order_history qty (order_id=...` – debug log with Decimal types
- No line containing `TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`
- Any critical failure: single line `[PIPELINE_FAILURE] {"event":"CRITICAL_FAILURE",...}` with error_code and message
