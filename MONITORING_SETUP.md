# SELL Order Monitoring Setup

## Summary

✅ **All tasks completed:**

1. ✅ **Checked for newer SELL orders** - Found 2 FILLED SELL orders:
   - `5755600481538037740` (DOT_USDT) - Missing SL/TP ❌
   - `5755600481538026714` (DOT_USDT) - Has SL/TP ✅

2. ✅ **Created manual SL/TP** for order `5755600481538037740`:
   - SL/TP orders successfully created
   - SL: 1 order
   - TP: 1 order

3. ✅ **Monitoring script created** - `backend/monitor_sell_orders.py`

## Monitoring Script

### Usage

Run the monitoring script to watch for new SELL orders:

```bash
# On production server
ssh hilovivo-aws
cd ~/automated-trading-platform/backend
python3 monitor_sell_orders.py
```

The script will:
- Check every 30 seconds for new SELL orders
- Display order details and SL/TP status
- Alert if SL/TP are missing
- Provide command to manually create SL/TP if needed

### Run in Background

To run monitoring in the background:

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform/backend && nohup python3 monitor_sell_orders.py > monitor_sell_orders.log 2>&1 &"
```

Check logs:
```bash
ssh hilovivo-aws "tail -f ~/automated-trading-platform/backend/monitor_sell_orders.log"
```

## Manual SL/TP Creation

If a SELL order is missing SL/TP, create them manually:

### Option 1: Using the script

```bash
ssh hilovivo-aws
cd ~/automated-trading-platform/backend
python3 create_sl_tp_manual.py <order_id> --force
```

### Option 2: Using the API

```bash
curl -X POST "https://dashboard.hilovivo.com/api/orders/<order_id>/create-sl-tp?force=true"
```

### Option 3: Direct Python call

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws exec backend-aws python3 << 'PYEOF'
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder
from app.services.exchange_sync import ExchangeSyncService

db = SessionLocal()
order_id = '<order_id>'
order = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == order_id).first()

if order and order.status.value == 'FILLED':
    filled_price = float(order.avg_price) if order.avg_price else float(order.price)
    filled_qty = float(order.cumulative_quantity) if order.cumulative_quantity else float(order.quantity)
    
    exchange_sync = ExchangeSyncService()
    exchange_sync._create_sl_tp_for_filled_order(
        db=db,
        symbol=order.symbol,
        side=order.side.value,
        filled_price=filled_price,
        filled_qty=filled_qty,
        order_id=order_id,
        force=True,
        source='manual'
    )
    print('✅ SL/TP created')
else:
    print('❌ Order not found or not FILLED')

db.close()
PYEOF
"
```

## Quick Status Check

Check all recent SELL orders and their SL/TP status:

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws exec backend-aws python3 << 'PYEOF'
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from datetime import datetime, timezone, timedelta

db = SessionLocal()
last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
recent = db.query(ExchangeOrder).filter(
    ExchangeOrder.side == 'SELL',
    ExchangeOrder.status == OrderStatusEnum.FILLED,
    ExchangeOrder.exchange_update_time >= last_24h
).order_by(ExchangeOrder.exchange_update_time.desc()).all()

for o in recent:
    sl = db.query(ExchangeOrder).filter(
        ExchangeOrder.parent_order_id == o.exchange_order_id,
        ExchangeOrder.order_role == 'STOP_LOSS'
    ).count()
    tp = db.query(ExchangeOrder).filter(
        ExchangeOrder.parent_order_id == o.exchange_order_id,
        ExchangeOrder.order_role == 'TAKE_PROFIT'
    ).count()
    status = '✅' if (sl > 0 and tp > 0) else '❌'
    print(f'{status} {o.exchange_order_id}: {o.symbol} - SL:{sl} TP:{tp}')

db.close()
PYEOF
"
```

## Expected Behavior

For **new SELL orders** created after the fix:

1. Order is created by `signal_monitor`
2. When order becomes FILLED:
   - `exchange_sync` detects it (runs every 5 seconds)
   - SL/TP are created automatically (if within 1-hour window)
   - Telegram notifications are sent

3. If order is filled >1 hour after creation:
   - Automatic SL/TP creation is skipped (safety mechanism)
   - Use manual creation script if needed

## Files Created

- `backend/create_sl_tp_manual.py` - Manual SL/TP creation script
- `backend/monitor_sell_orders.py` - Monitoring script for new SELL orders
- `MONITORING_SETUP.md` - This documentation



