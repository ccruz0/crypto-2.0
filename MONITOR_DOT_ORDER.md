# Monitoring DOT_USDT Order SL/TP Creation

## Current Status

**Order ID:** `5755600481538037740`
- **Symbol:** DOT_USDT
- **Side:** SELL
- **Status:** NEW (not FILLED yet)
- **Type:** MARKET
- **SL/TP:** Not created yet (will be created when order becomes FILLED)

## What to Monitor

### 1. Check Order Status

Run this command on production to check if the order has been filled:

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws exec backend-aws python3 -c \"
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

db = SessionLocal()
try:
    order = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == '5755600481538037740').first()
    if order:
        print(f'Order Status: {order.status.value}')
        print(f'Symbol: {order.symbol}')
        print(f'Side: {order.side.value}')
        print(f'Price: {order.price or order.avg_price}')
        print(f'Quantity: {order.quantity}')
        
        if order.status == OrderStatusEnum.FILLED:
            print('\\n✅ Order is FILLED - Checking for SL/TP...')
            sl = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == '5755600481538037740',
                ExchangeOrder.order_role == 'STOP_LOSS'
            ).all()
            tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == '5755600481538037740',
                ExchangeOrder.order_role == 'TAKE_PROFIT'
            ).all()
            
            print(f'🛑 Stop Loss: {\"✅\" if sl else \"❌ MISSING\"} ({len(sl)} order(s))')
            print(f'🚀 Take Profit: {\"✅\" if tp else \"❌ MISSING\"} ({len(tp)} order(s))')
            
            if sl:
                for s in sl:
                    print(f'   SL Order: {s.exchange_order_id} | Status: {s.status.value} | Price: {s.price}')
            if tp:
                for t in tp:
                    print(f'   TP Order: {t.exchange_order_id} | Status: {t.status.value} | Price: {t.price}')
        else:
            print(f'\\nℹ️  Order is still {order.status.value} - waiting for FILLED status')
    else:
        print('❌ Order not found')
finally:
    db.close()
\""
```

### 2. Check Exchange Sync Logs

Monitor the exchange_sync service to see when it detects the order as FILLED:

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws -f | grep -E '(5755600481538037740|DOT_USDT|SL/TP|FILLED)'"
```

### 3. Check for SL/TP Creation

Once the order is FILLED, verify SL/TP orders were created:

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws exec backend-aws python3 check_specific_order.py 5755600481538037740"
```

### 4. Check All Recent Orders

Check all orders from today to see their SL/TP status:

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws exec backend-aws python3 check_orders_sl_tp.py"
```

## Expected Behavior

1. **When order becomes FILLED:**
   - `exchange_sync` service (runs every 5 seconds) will detect the FILLED status
   - It will call `_create_sl_tp_for_filled_order()` for the SELL order
   - SL/TP orders will be created as BUY orders (to close the SELL position)
   - SL price will be higher than entry (to limit loss if price goes up)
   - TP price will be lower than entry (to take profit if price goes down)

2. **Telegram Notifications:**
   - You should receive notifications when SL/TP orders are created
   - You should receive notifications if orphaned orders are deleted

## Troubleshooting

If SL/TP are not created after order is FILLED:

1. Check exchange_sync logs for errors
2. Verify the order has `avg_price` set (required for SL/TP creation)
3. Check if there are any existing SL/TP orders (might already exist)
4. Verify watchlist item has SL/TP percentages configured

## Quick Status Check

Run this one-liner to quickly check order and SL/TP status:

```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws exec backend-aws python3 -c \"
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
db = SessionLocal()
o = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == '5755600481538037740').first()
print(f'Status: {o.status.value if o else \"NOT FOUND\"}')
if o and o.status == OrderStatusEnum.FILLED:
    sl = db.query(ExchangeOrder).filter(ExchangeOrder.parent_order_id == '5755600481538037740', ExchangeOrder.order_role == 'STOP_LOSS').count()
    tp = db.query(ExchangeOrder).filter(ExchangeOrder.parent_order_id == '5755600481538037740', ExchangeOrder.order_role == 'TAKE_PROFIT').count()
    print(f'SL: {sl}, TP: {tp}')
db.close()
\""
```

