# Portfolio Risk Alert Throttling

**Date:** 2025-11-29  
**Status:** ✅ IMPLEMENTED

## Overview

Portfolio risk alerts ("ALERTA BLOQUEADA POR VALOR EN CARTERA") are now throttled to prevent spam when the same condition persists across multiple monitor cycles.

## Problem

Previously, portfolio risk alerts were sent every cycle (every ~30 seconds) when a symbol's portfolio value exceeded the limit, even if nothing had changed. This caused repeated identical messages like:

```
🚫 ALERTA BLOQUEADA POR VALOR EN CARTERA: CRO_USDT - 
Valor en cartera: $34845.46 USD (balance actual en exchange). 
Límite: $900.00 (3x trade_amount)
```

## Solution

A throttling mechanism was added that only sends portfolio risk alerts when:

1. **Portfolio value changed significantly** (≥1% change), OR
2. **Limit value changed** (trade_amount or multiple changed), OR
3. **Minimum time interval passed** (≥10 minutes since last alert)

## Throttling Rules

### Configuration

- **Minimum interval**: 10 minutes (`PORTFOLIO_RISK_ALERT_MIN_INTERVAL_MINUTES = 10`)
- **Minimum value change**: 1% (`PORTFOLIO_RISK_ALERT_MIN_CHANGE_PCT = 1.0`)

### Logic

An alert is sent if **any** of these conditions are met:

1. **No previous alert** for this symbol
2. **Limit changed**: `abs(new_limit - last_limit) > 0.01`
3. **Time passed AND value changed**:
   - `elapsed_minutes >= 10` AND `value_change_pct >= 1.0%`
4. **Value changed significantly** (even if time hasn't passed):
   - `value_change_pct >= 1.0%`

An alert is **blocked** if:
- `elapsed_minutes < 10` AND `value_change_pct < 1.0%` AND limit unchanged

## Implementation

### In-Memory Tracking

The throttle uses an in-memory dictionary in `SignalMonitorService`:

```python
self.last_portfolio_risk_alerts: Dict[str, Dict] = {}
# Format: {symbol: {
#     "last_value_usd": float,
#     "last_timestamp": datetime,
#     "last_limit_value": float
# }}
```

### Helper Methods

- `_should_send_portfolio_risk_alert(symbol, portfolio_value, limit_value) -> (bool, Optional[str])`
  - Returns `(True, None)` if alert should be sent
  - Returns `(False, reason)` if alert should be throttled

- `_record_portfolio_risk_alert(symbol, portfolio_value, limit_value) -> None`
  - Records that an alert was sent for future throttling checks

### Applied To

Throttling is applied to all three locations where portfolio risk alerts are sent:

1. **BUY alert blocking** (line ~1400): "ALERTA BLOQUEADA POR VALOR EN CARTERA"
2. **SELL alert blocking** (line ~2080): "ALERTA BLOQUEADA POR VALOR EN CARTERA"
3. **Order creation blocking** (line ~2364): "ORDEN BLOQUEADA POR VALOR EN CARTERA"

## Logging

### When Alert is Sent
```
[RISK_PORTFOLIO_CHECK] symbol=CRO_USDT ... blocked=True
🚫 ALERTA BLOQUEADA POR VALOR EN CARTERA: CRO_USDT - ...
```

### When Alert is Throttled
```
[RISK_THROTTLED] symbol=CRO_USDT reason=elapsed 2.5m < 10m AND value change 0.05% < 1.0% portfolio_value_usd=34845.46 limit_value=900.00
```

## Example Scenarios

### Scenario 1: First Alert
- **Portfolio value**: $35,000
- **Limit**: $900
- **Result**: ✅ Alert sent (no previous alert)

### Scenario 2: Same Value, 2 Minutes Later
- **Portfolio value**: $35,000 (unchanged)
- **Limit**: $900 (unchanged)
- **Elapsed**: 2 minutes
- **Result**: ❌ Alert throttled (time < 10m AND value unchanged)

### Scenario 3: Value Increased 2%, 5 Minutes Later
- **Portfolio value**: $35,700 (2% increase)
- **Limit**: $900 (unchanged)
- **Elapsed**: 5 minutes
- **Result**: ✅ Alert sent (value changed ≥1%)

### Scenario 4: Same Value, 15 Minutes Later
- **Portfolio value**: $35,000 (unchanged)
- **Limit**: $900 (unchanged)
- **Elapsed**: 15 minutes
- **Result**: ✅ Alert sent (time ≥10m, even if value unchanged)

### Scenario 5: Limit Changed
- **Portfolio value**: $35,000 (unchanged)
- **Limit**: $1,200 (changed from $900)
- **Elapsed**: 2 minutes
- **Result**: ✅ Alert sent (limit changed)

## Verification

To verify throttling is working:

1. **Check logs** for `[RISK_THROTTLED]` entries:
   ```bash
   cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh | grep RISK_THROTTLED
   ```

2. **Monitor Telegram Messages**:
   - For a symbol like CRO_USDT with persistent high portfolio value
   - First alert should appear immediately
   - Subsequent alerts should only appear when:
     - Portfolio value changes by ≥1%, OR
     - 10+ minutes have passed

3. **Check risk check logs**:
   ```bash
   cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh | grep RISK_PORTFOLIO_CHECK
   ```

## Files Changed

- `backend/app/services/signal_monitor.py`:
  - Added `last_portfolio_risk_alerts` tracking dictionary
  - Added `_should_send_portfolio_risk_alert()` helper method
  - Added `_record_portfolio_risk_alert()` helper method
  - Applied throttling to all three portfolio risk alert locations

## Notes

- Throttling is per-symbol (each symbol has its own throttle state)
- Throttle state is in-memory only (resets on service restart)
- The risk check logic (3x trade_amount limit) is unchanged
- Only the alert frequency is reduced, not the risk protection


