# TON Alert Order Investigation

**Date:** 2025-12-14  
**Issue:** Last TON alert did not trigger a buy order

---

## Investigation Summary

### Current Status (As of 2025-12-14 14:38 GMT+8)
- **Configuration:** ❌ **ISSUE FOUND**
  - `alert_enabled=True` ✅
  - `buy_alert_enabled=True` ✅
  - `trade_enabled=False` ❌ **THIS IS THE PROBLEM**
  - `trade_amount_usd=None` ❌ **THIS IS ALSO THE PROBLEM**
- **Recent Alerts:** BUY signal detected and recorded in throttle (14:38:09)
- **Signal Status:** BUY signals are being detected, but orders are not created because trading is disabled

### Root Cause Identified

**The alert was sent, but the order was not created because:**
1. `trade_enabled=False` - Automatic trading is disabled for TON_USDT
2. `trade_amount_usd=None` - No trade amount is configured

**Solution:** Enable trading in the dashboard:
1. Go to Watchlist tab
2. Find TON_USDT
3. Enable "Trade Enabled" toggle
4. Set "Amount USD" to desired value (e.g., 10.0)

### Alert Flow

1. **Signal Detection** → `buy_signal=True` ✅
2. **Throttle Check** → `should_emit_signal()` checks cooldown and price change
3. **Alert Sending** → If throttle allows, alert is sent via Telegram
4. **Order Creation** → After alert is sent, order creation is attempted

### Why Orders Might Not Be Created (After Alert Sent)

If an alert **was sent** but no order was created, the following checks can block order creation:

1. **Missing MAs** ❌
   - **Check:** `ma50 is None or ema10 is None`
   - **Action:** Order silently blocked (no notification)
   - **Fix Applied:** ✅ Now sends Telegram notification

2. **Portfolio Value Limit** ⚠️
   - **Check:** `portfolio_value > 3x trade_amount_usd`
   - **Action:** Order skipped, notification sent
   - **Status:** Already has notification

3. **trade_enabled=False** ❌
   - **Check:** `watchlist_item.trade_enabled == False`
   - **Action:** Order skipped (only info log)
   - **Fix Applied:** ✅ Now sends Telegram notification

4. **alert_enabled=False** ❌
   - **Check:** `watchlist_item.alert_enabled == False` (re-checked before order)
   - **Action:** Order blocked with warning log
   - **Status:** Already has warning log

5. **Missing trade_amount_usd** ❌
   - **Check:** `trade_amount_usd is None or <= 0`
   - **Action:** Error notification sent to Telegram
   - **Status:** Already has notification

---

## Fixes Applied

### 1. Missing MAs Notification
**File:** `backend/app/services/signal_monitor.py` (line ~1986)

**Before:**
```python
error_msg = f"❌ Cannot create BUY order for {symbol}: MAs REQUIRED but missing: {', '.join(missing_mas)}"
logger.error(error_msg)
# Bloquear silenciosamente - no enviar notificación a Telegram
return  # Exit - cannot create order without MAs
```

**After:**
```python
error_msg = (
    f"❌ ORDEN NO EJECUTADA: {symbol} - MAs REQUIRED but missing: {', '.join(missing_mas)}. "
    f"La alerta ya fue enviada, pero la orden de compra no se creará sin los indicadores técnicos necesarios."
)
logger.error(error_msg)
# Send notification to Telegram since alert was sent but order wasn't created
try:
    from app.api.routes_monitoring import add_telegram_message
    add_telegram_message(error_msg, symbol=symbol, blocked=False, order_skipped=True)
except Exception:
    pass  # Non-critical, continue
```

### 2. trade_enabled=False Notification
**File:** `backend/app/services/signal_monitor.py` (line ~2105)

**Before:**
```python
logger.info(f"ℹ️ Alert sent for {symbol} but trade_enabled = false - no order created (trade_amount_usd={watchlist_item.trade_amount_usd})")
```

**After:**
```python
info_msg = (
    f"ℹ️ ORDEN NO EJECUTADA: {symbol} - trade_enabled=False. "
    f"La alerta ya fue enviada, pero la orden de compra no se creará porque el trading automático está deshabilitado para este símbolo."
)
logger.info(info_msg)
# Send notification to Telegram since alert was sent but order wasn't created
try:
    from app.api.routes_monitoring import add_telegram_message
    add_telegram_message(info_msg, symbol=symbol, blocked=False, order_skipped=True)
except Exception:
    pass  # Non-critical, continue
```

---

## Immediate Action Required

### Fix TON_USDT Configuration

**Current Issue:**
- `trade_enabled=False` → Orders will not be created
- `trade_amount_usd=None` → Orders cannot be created without amount

**Steps to Fix:**
1. Open the Trading Dashboard
2. Go to the **Watchlist** tab
3. Find **TON_USDT** in the list
4. Enable the **"Trade Enabled"** toggle (should be green/checked)
5. Set **"Amount USD"** to your desired trade amount (e.g., `10.0`)
6. Save the changes

After enabling these settings, the next TON alert will automatically create a buy order.

---

## Next Steps

### To Diagnose Future Issues

1. **Check Recent Logs for Successful Alert:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   bash scripts/aws_backend_logs.sh --tail 100000 | grep -i "TON_USDT" | grep -E "(✅ BUY alert sent|Checking order creation|MA validation|Portfolio value|Cannot create|ORDEN NO EJECUTADA)" | tail -50
   ```

2. **Check Monitoring Messages:**
   - Check the Monitoring tab in the dashboard
   - Look for messages with `order_skipped=True` for TON_USDT
   - These will show why the order wasn't created

3. **Verify MA Availability:**
   - Check if MA50 and EMA10 are available for TON_USDT
   - Check MarketData table for TON_USDT

4. **Check Portfolio Value:**
   - Verify if portfolio value for TON exceeds 3x trade_amount ($30 for TON_USDT)

### Expected Behavior After Fixes

When an alert is sent but an order is not created, you will now receive a Telegram notification explaining why:
- Missing MAs → "❌ ORDEN NO EJECUTADA: TON_USDT - MAs REQUIRED but missing: MA50, EMA10"
- trade_enabled=False → "ℹ️ ORDEN NO EJECUTADA: TON_USDT - trade_enabled=False"
- Portfolio limit → "⚠️ ORDEN NO EJECUTADA POR VALOR EN CARTERA: TON_USDT - Valor en cartera ($X) > 3x trade_amount ($30)"

---

## Related Files

- `backend/app/services/signal_monitor.py` - Main alert and order creation logic
- `backend/app/services/signal_throttle.py` - Throttle logic for alerts
- `backend/app/services/trading_signals.py` - Signal detection logic
- `backend/app/api/routes_monitoring.py` - Monitoring message storage

---

## Testing

After deploying these fixes, the next time an alert is sent but an order is not created, you should receive a clear notification explaining the reason.

To test:
1. Wait for next TON alert (or use `/test/simulate-alert` endpoint)
2. If order is not created, check Telegram for notification
3. Check Monitoring tab for detailed message

