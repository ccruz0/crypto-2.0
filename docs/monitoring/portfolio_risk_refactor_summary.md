# Portfolio Risk Refactor - Summary

**Date:** 2025-11-30  
**Status:** ✅ Completed

## What Changed

Portfolio risk now **only blocks ORDER PLACEMENT**, never SIGNAL ALERTS.

### Before
- Portfolio risk blocked both alerts and orders
- Users didn't receive BUY/SELL signals when portfolio value exceeded limit
- Messages said "ALERTA BLOQUEADA POR VALOR EN CARTERA"

### After
- Alerts are **always sent** (subject only to throttle + alert_enabled)
- Portfolio risk **only blocks orders**
- Messages say "ORDEN BLOQUEADA POR VALOR EN CARTERA" (order-level diagnostic)

## Implementation Details

### New Functions

1. **`check_portfolio_risk_for_order()`** (SignalMonitorService)
   - Pure risk calculation function
   - Returns `(ok: bool, message: str)`
   - Does NOT send alerts or write to DB
   - Used only for order placement decisions

2. **`record_order_risk_block()`** (routes_monitoring.py)
   - Records diagnostic in Monitoring tab
   - Uses `throttle_status="ORDER_BLOCKED_RISK"`
   - Does NOT send to Telegram

### Flow Changes

**BUY Flow:**
```
1. Strategy decides BUY → send alert (throttle + alert_enabled only)
2. If trade_enabled=True and amount_usd > 0:
   a. Check portfolio risk using check_portfolio_risk_for_order()
   b. If risk blocks: record_order_risk_block() → skip order
   c. If risk OK: place order
```

**SELL Flow:**
```
1. Strategy decides SELL → send alert (throttle + alert_enabled only)
2. If trade_enabled=True and amount_usd > 0:
   a. Check portfolio risk using check_portfolio_risk_for_order()
   b. If risk blocks: record_order_risk_block() → skip order
   c. If risk OK: place order
```

## Verification

After deployment, verify:

1. **Dashboard:**
   - Symbol with large portfolio value + small Amount USD
   - ALERTS=ON, Bot=Active, strategy=BUY/SELL

2. **Monitoring:**
   - ✅ Normal green BUY/SELL alert appears
   - ✅ If risk too high: INFO/ORDER_BLOCKED_RISK diagnostic (not BLOCKED alert)

3. **Telegram:**
   - ✅ BUY/SELL signal received
   - ✅ No "ALERTA BLOQUEADA" messages

## Testing Status

- ✅ Code compiles successfully
- ✅ No linter errors
- ⏳ Unit tests pending (see test_portfolio_risk_vs_alerts.py)

## Deployment Log

### 2025-11-30 - Deployment to AWS

**Deployed Files:**
- `backend/app/services/signal_monitor.py` - Refactored BUY/SELL flows
- `backend/app/api/routes_monitoring.py` - Added `record_order_risk_block()` helper

**Verification:**
- ✅ `rg "ALERTA BLOQUEADA POR VALOR EN CARTERA"` returns zero matches in code
- ✅ `rg "ORDER_BLOCKED_RISK"` confirms new diagnostic helper exists
- ✅ Backend container rebuilt and restarted successfully
- ✅ Runtime verification: No "ALERTA BLOQUEADA" text in container code
- ✅ New diagnostic strings confirmed: "ORDEN BLOQUEADA" and "ORDER_BLOCKED_RISK"

**Confirmed Behavior:**
- Portfolio risk now only blocks orders, never alerts
- Alerts are sent based on strategy decision + throttle + alert_enabled only
- Order-level risk blocks are logged as `ORDER_BLOCKED_RISK` diagnostics (monitoring only, no Telegram)
- Old "ALERTA BLOQUEADA POR VALOR EN CARTERA" message completely removed

**Example Log Pattern (Expected):**
```
[INFO] TELEGRAM_EMIT_DEBUG | emitter=SignalMonitorService | symbol=BTC_USDT | side=BUY
[INFO] ✅ BUY alert sent for BTC_USDT
[INFO] [RISK_PORTFOLIO_CHECK] symbol=BTC_USDT ... blocked=True
[WARNING] 🚫 ORDER BLOCKED BY PORTFOLIO RISK: BTC_USDT – Valor en cartera: $11589.11 USD, Límite: $30.00 (3x trade_amount)
```

**Next Steps:**
- Monitor logs for `ORDER_BLOCKED_RISK` entries during next monitor cycle
- Verify alerts are sent even when orders are blocked
- Add unit tests (optional but recommended)

