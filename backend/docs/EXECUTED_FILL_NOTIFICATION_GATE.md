# Executed-fill notification gate (no Telegram spam from history sync)

## What changed

- **Problem**: Order-history sync (last 30 days) was sending Telegram "ORDER EXECUTED" for every filled order, including old ones, causing spam.
- **Solution**: A gating function `should_notify_executed_fill` in `exchange_sync.py` decides whether to send a notification:
  - **Allow**: admin resync, system order (trade_signal_id or parent_order_id), or fill within 1 hour.
  - **Block**: already notified (persisted in `execution_notified_at`), or historical fill outside 1h and not a system order.
- **Persistence**: New column `exchange_orders.execution_notified_at` records when we sent a notification so we never notify twice for the same order.
- **Fill dedup**: When `fill_dedup_postgres` is missing, the gate still prevents history spam; it does not rely on fill_dedup alone.

## Deploy on EC2

```bash
cd /home/ubuntu/automated-trading-platform
git fetch --all
git reset --hard origin/main
# Run migration (add execution_notified_at if missing)
docker compose --profile aws exec backend-aws python3 /app/scripts/add_execution_notified_at_column.py || true
docker compose --profile aws down backend-aws
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
```

## Verify on EC2

1. **Imports**
   ```bash
   BACKEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'backend-aws' | head -n 1)
   docker exec "$BACKEND_CONTAINER" python3 -c "
   from app.services.exchange_sync import should_notify_executed_fill, RECENT_FILL_WINDOW_SECONDS
   print('OK: gate imports'); print('RECENT_FILL_WINDOW_SECONDS', RECENT_FILL_WINDOW_SECONDS)
   "
   ```

2. **No spam in logs** (after a sync cycle)
   ```bash
   docker logs "$BACKEND_CONTAINER" --since 30m 2>&1 | grep -E "ORDER_EXECUTED_NOTIFICATION|FILL_NOTIFICATION|Sent Telegram notification for executed" | tail -20
   ```
   You should see at most one notification per order; historical fills should log `Skipping notification for order ...: historical fill` or `outside window` instead of sending Telegram.

3. **Optional: simulate gate**
   ```bash
   docker exec "$BACKEND_CONTAINER" python3 -c "
   from datetime import datetime, timezone, timedelta
   from app.services.exchange_sync import should_notify_executed_fill, RECENT_FILL_WINDOW_SECONDS
   from unittest.mock import MagicMock
   now = datetime.now(timezone.utc)
   old = now - timedelta(seconds=RECENT_FILL_WINDOW_SECONDS + 60)
   order = MagicMock(trade_signal_id=None, parent_order_id=None, exchange_update_time=old, exchange_create_time=old, execution_notified_at=None)
   allowed, reason = should_notify_executed_fill(db=MagicMock(), order=order, now_utc=now, source='test', requested_by_admin=False)
   print('Old fill, not system:', allowed, reason)
   assert not allowed
   print('OK: gate blocks historical fill')
   "
   ```
