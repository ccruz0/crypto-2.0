# Portfolio Risk Refactor: Separate Alerts from Orders

**Date:** 2025-11-30  
**Status:** ✅ Completed

## Goal

Portfolio risk must only block ORDER PLACEMENT, never the SIGNAL ALERT itself.

## Current Problem

When portfolio value exceeds the limit (3x trade_amount), the system:
1. Blocks the BUY/SELL alert from being sent
2. Sends a "ALERTA BLOQUEADA POR VALOR EN CARTERA" message

This is wrong because:
- Users should always receive signal alerts when strategy decides BUY/SELL
- Portfolio risk should only protect against placing orders that exceed limits
- Alerts and orders are separate concerns

## Solution

### Design Principle

**Portfolio risk protects orders, not alerts.**

### Implementation

1. **Pure Risk-Check Function** (`check_portfolio_risk_for_order`)
   - Only calculates risk, never sends alerts
   - Returns `(ok: bool, message: str)`
   - Used only for order placement decisions

2. **Order Risk Block Helper** (`record_order_risk_block`)
   - Records diagnostic in Monitoring tab
   - Does NOT send to Telegram
   - Uses `throttle_status="ORDER_BLOCKED_RISK"`

3. **Refactored BUY Flow**
   ```
   if decision == "BUY" and buy_signal:
       # 1) Always send BUY alert (subject only to throttle + alert_enabled)
       send_buy_alert(...)
       
       # 2) Only if Trade=YES and Amount USD > 0, check risk for ORDER
       if trade_enabled and amount_usd > 0:
           ok_risk, risk_msg = check_portfolio_risk_for_order(...)
           if not ok_risk:
               record_order_risk_block(...)  # Monitoring only
               return  # Skip order, but alert was already sent
           # Risk OK → place order
           place_buy_order(...)
   ```

4. **Refactored SELL Flow** (similar pattern)

5. **Updated Message Text**
   - Changed from: "ALERTA BLOQUEADA POR VALOR EN CARTERA"
   - Changed to: "ORDEN BLOQUEADA POR VALOR EN CARTERA"

## Files Changed

- `backend/app/services/signal_monitor.py`:
  - Added `check_portfolio_risk_for_order()` method (pure risk calculation, no alerts)
  - Removed portfolio risk check from alert path (BUY section - lines ~1772-1896)
  - Removed portfolio risk check from alert path (legacy BUY section - lines ~2307-2431)
  - Updated BUY order placement section to use new risk check (lines ~2531-2569)
  - Updated SELL order placement section to use new risk check (lines ~2909-2938)
  - Added comment block describing flow at class level

- `backend/app/api/routes_monitoring.py`:
  - Added `record_order_risk_block()` helper function
  - Records ORDER_BLOCKED_RISK diagnostics (monitoring only, no Telegram)

## Testing

### Test Cases Needed

1. **BUY alert sent, order blocked by risk**
   - Setup: alert_enabled=True, trade_enabled=True, amount_usd=10
   - Strategy: BUY with buy_signal=True
   - Mock: portfolio risk returns (False, "risk_msg")
   - Assert:
     - `send_buy_alert` called once
     - `place_buy_order` NOT called
     - `record_order_risk_block` called once

2. **BUY alert sent, order placed when risk OK**
   - Same setup, but risk returns (True, "ok")
   - Assert:
     - BUY alert sent
     - Order placement called
     - No `record_order_risk_block` call

3. **Trade disabled: alert sent, no risk check**
   - Setup: alert_enabled=True, trade_enabled=False
   - Assert:
     - BUY alert sent
     - `check_portfolio_risk_for_order` NOT called
     - No order placement

## Verification Checklist

After deployment:

1. **Dashboard:**
   - Pick symbol with large portfolio value and small Amount USD
   - Ensure ALERTS=ON, Bot=Active, strategy=BUY/SELL

2. **Monitoring:**
   - Should see normal green BUY/SELL alert when throttling allows
   - If risk too high:
     - No "ALERTA BLOQUEADA" as BLOCKED alert
     - Instead: INFO/ORDER_BLOCKED_RISK line describing order blocked

3. **Telegram:**
   - Should receive BUY/SELL signal
   - Should NOT receive "ALERTA BLOQUEADA" messages

## Notes

- The refactoring maintains backward compatibility for order placement logic
- Only the alert blocking behavior changes
- Portfolio risk calculation remains the same (3x trade_amount limit)

