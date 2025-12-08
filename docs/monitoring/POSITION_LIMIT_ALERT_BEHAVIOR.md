# Position Limit Alert Behavior

## Overview

This document describes the behavior of the alert and order pipeline when position limits are exceeded.

## Key Principle

**Position limits block ORDERS, not ALERTS.**

- Alerts (Telegram messages, Monitoring entries) are **ALWAYS** sent/logged, even when position limits are exceeded.
- Orders are **SKIPPED** when position limits are exceeded.
- The Monitoring UI clearly distinguishes between "order skipped" and "alert blocked".

## Position Limit Rule

A BUY order is skipped when:
```
portfolio_value > 3 × trade_amount_usd
```

Where:
- `portfolio_value`: Current USD value of all positions for the symbol (calculated from open orders and positions)
- `trade_amount_usd`: The configured trade amount for the watchlist item

## Behavior Details

### When Position Limit is Exceeded

1. **Alert is Generated and Sent**
   - The BUY signal is detected and evaluated
   - A Telegram alert is sent to the configured chat
   - The alert message includes signal details (RSI, price, MAs, etc.)

2. **Order is Skipped**
   - Order creation logic checks portfolio value
   - If limit is exceeded, order creation is skipped
   - A monitoring entry is created with `order_skipped=True`

3. **Monitoring Entry Created**
   - Message text: `"⚠️ ORDEN NO EJECUTADA POR VALOR EN CARTERA: {symbol} - Valor en cartera (${portfolio_value:.2f}) > 3x trade_amount (${limit_value:.2f}). La alerta se envió, pero la orden de compra no se creará."`
   - Fields:
     - `blocked=False` (alert was sent)
     - `order_skipped=True` (order was skipped)
     - `throttle_status="SENT"` (if applicable)

### Database Schema

The `telegram_messages` table includes:
- `blocked` (boolean): Indicates if the alert itself was blocked (e.g., due to technical errors, guardrails)
- `order_skipped` (boolean): Indicates if the order was skipped due to position limits
- `throttle_status` (string): Throttle status ("SENT", "BLOCKED", etc.)

### Frontend Display

The Monitoring UI shows:
- **ORDER SKIPPED** badge (yellow/orange) when `order_skipped=True`
- **BLOCKED** badge (red) when `blocked=True` (for technical blocks, not position limits)
- **SENT** badge (green) when alert was sent successfully

## Message Text Changes

### Old Behavior (Before Refactor)
- Message: `"🚫 ALERTA BLOQUEADA POR VALOR EN CARTERA: {symbol} - ..."`
- `blocked=True`
- Alert was NOT sent to Telegram

### New Behavior (After Refactor)
- Message: `"⚠️ ORDEN NO EJECUTADA POR VALOR EN CARTERA: {symbol} - ..."`
- `blocked=False`
- `order_skipped=True`
- Alert IS sent to Telegram

## Code Locations

### Backend

1. **Model**: `backend/app/models/telegram_message.py`
   - Added `order_skipped` field

2. **Signal Monitor**: `backend/app/services/signal_monitor.py`
   - Lines ~1183-1212: First portfolio check (in alert sending path)
   - Lines ~1729-1760: Second portfolio check (in order creation path)
   - Lines ~1852-1876: Third portfolio check (final order validation)

3. **Monitoring API**: `backend/app/api/routes_monitoring.py`
   - `add_telegram_message()` function accepts `order_skipped` parameter
   - API response includes `order_skipped` field

### Frontend

1. **Type Definition**: `frontend/src/lib/api.ts`
   - `TelegramMessage` interface includes `order_skipped?: boolean`

2. **Monitoring Panel**: `frontend/src/app/components/MonitoringPanel.tsx`
   - Shows "ORDER SKIPPED" badge when `order_skipped=True`
   - Uses yellow/orange styling for order skipped messages

## Testing

### Manual Test

1. Find a symbol with high exposure:
   ```bash
   docker compose exec backend python scripts/test_position_limit_alert_behavior.py
   ```

2. Verify monitoring entries:
   ```bash
   docker compose exec backend python -c "
   from app.database import SessionLocal
   from app.models.telegram_message import TelegramMessage
   from datetime import datetime, timezone, timedelta
   
   db = SessionLocal()
   recent = db.query(TelegramMessage).filter(
       TelegramMessage.timestamp >= datetime.now(timezone.utc) - timedelta(hours=1)
   ).order_by(TelegramMessage.timestamp.desc()).limit(10).all()
   
   for msg in recent:
       print(f'{msg.timestamp}: {msg.symbol} - blocked={msg.blocked}, order_skipped={getattr(msg, \"order_skipped\", False)} - {msg.message[:80]}...')
   "
   ```

### Expected Results

For symbols with `portfolio_value > 3 × trade_amount_usd`:
- ✅ Alert is sent to Telegram
- ✅ Monitoring entry created with `blocked=False`, `order_skipped=True`
- ✅ Message says "ORDEN NO EJECUTADA" (not "ALERTA BLOQUEADA")
- ✅ Frontend shows "ORDER SKIPPED" badge (yellow/orange)
- ✅ Order is NOT created

## Guardrail Compliance

This refactor ensures compliance with the guardrail:
> "Alerts must never be blocked after conditions are met"

Position limits are a **risk management feature** that affects order placement, not alert delivery. Users must always be informed when signals are detected, even if orders cannot be executed due to exposure limits.

## Migration Notes

### Database Migration

The `order_skipped` column must be added to the `telegram_messages` table:

```sql
ALTER TABLE telegram_messages 
ADD COLUMN order_skipped BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX ix_telegram_messages_order_skipped ON telegram_messages(order_skipped);
```

If using SQLAlchemy's `Base.create_all()`, the column will be added automatically on next startup (for new tables). For existing tables, run the SQL above manually.

### Backward Compatibility

- Old monitoring entries without `order_skipped` will default to `False`
- Frontend handles missing `order_skipped` field gracefully
- API returns `order_skipped: false` for old entries

## Related Documentation

- `docs/monitoring/business_rules_canonical.md` - Business rules and guardrails
- `docs/BLOCKED_ALERT_REGRESSION_GUARDRAIL.md` - Guardrail preventing alert blocking
- `backend/scripts/test_position_limit_alert_behavior.py` - Test script
