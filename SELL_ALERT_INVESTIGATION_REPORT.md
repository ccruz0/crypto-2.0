# Sell Alert Investigation Report

## Executive Summary

This report investigates why sell alerts are not being generated despite high RSI values (BTC_USDT: 90.33, LDO_USD: 81.30) that should trigger sell signals.

## Key Findings

### 1. Sell Alert Requirements

For a sell alert to be sent, **ALL** of the following conditions must be met:

1. **`sell_alert_enabled=True`** - SELL-specific flag must be enabled (separate from `alert_enabled`)
2. **`alert_enabled=True`** - Master alert switch must be enabled
3. **RSI > sell threshold** (typically 70) - ✅ **MET** for BTC_USDT (90.33) and LDO_USD (81.30)
4. **Trend reversal** - MA50 < EMA10 (with >= 0.5% difference) OR price < MA10w
5. **Volume confirmation** - `volume_ratio >= min_volume_ratio` (default 0.5x)
6. **Throttle check passes** - Not blocked by cooldown or price change requirements

### 2. Critical Issues Identified

#### Issue A: `sell_alert_enabled` Flag May Be Disabled
- The `sell_alert_enabled` flag is **separate** from `buy_alert_enabled` and `alert_enabled`
- Default value is `False` - must be explicitly enabled
- **Action Required**: Check and enable `sell_alert_enabled=True` for symbols that need sell alerts

#### Issue B: MA Reversal Condition May Not Be Met
- Sell signals require **trend reversal**: MA50 < EMA10 (with >= 0.5% difference)
- If MA50 >= EMA10, sell signal will NOT be generated even with high RSI
- **Action Required**: Verify MA50 and EMA10 values for BTC_USDT and LDO_USD

#### Issue C: Volume Confirmation May Be Failing
- Sell signals require `volume_ratio >= min_volume_ratio` (default 0.5x)
- If volume data is missing or ratio is too low, sell signal is blocked
- **Action Required**: Check volume data availability and ratios

#### Issue D: Monitoring Endpoint Showing 500 Error
- The dashboard shows "Monitoring 500" which indicates a backend error
- This may prevent alert status from being displayed correctly
- **Action Required**: Fix monitoring endpoint error

### 3. Code Flow Analysis

#### Sell Signal Generation (`trading_signals.py`)

```python
# SELL signal requires ALL of:
1. rsi_sell_met = rsi > rsi_sell_threshold (typically 70) ✅
2. trend_reversal = (MA50 < EMA10 with >= 0.5% diff) OR (price < MA10w) ❓
3. sell_volume_ok = volume_ratio >= min_volume_ratio (default 0.5x) ❓

# Only if ALL three are True:
sell_signal = True
```

#### Sell Alert Sending (`signal_monitor.py`)

```python
# Alert sending requires:
1. sell_signal = True ✅ (from trading_signals)
2. alert_enabled = True ❓
3. sell_alert_enabled = True ❓
4. Throttle check passes ❓

# Only if ALL conditions met:
send_sell_signal() is called
```

## Diagnostic Steps

### Step 1: Check `sell_alert_enabled` Flags

Run the diagnostic script:
```bash
cd backend
python scripts/diagnose_sell_alerts.py
```

Or check directly in database:
```sql
SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled, trade_enabled
FROM watchlist_items
WHERE alert_enabled = true AND deleted = false
ORDER BY symbol;
```

### Step 2: Check Current Signal Status

For each symbol with high RSI, verify:
1. RSI value (should be > 70) ✅
2. MA50 and EMA10 values (MA50 should be < EMA10 for trend reversal)
3. Volume ratio (should be >= 0.5x)
4. `sell_alert_enabled` flag (should be True)

### Step 3: Check Backend Logs

Look for these log patterns:
```
🔍 {symbol} SELL alert decision: sell_signal=True, ...
🔴 NEW SELL signal detected for {symbol}
✅ SELL alert SENT for {symbol}
⏭️  SELL alert BLOCKED for {symbol} (throttling)
```

### Step 4: Fix Monitoring Endpoint

The "Monitoring 500" error needs to be resolved. Check:
- Backend logs for exceptions in `/api/monitoring/summary`
- Database connectivity
- Service status

## Proposed Solutions

### Solution 1: Enable Sell Alerts for All Symbols (Quick Fix)

Enable `sell_alert_enabled=True` for all symbols that have `alert_enabled=True`:

```python
# Script: backend/scripts/enable_sell_alerts.py
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

db = SessionLocal()
try:
    items = db.query(WatchlistItem).filter(
        WatchlistItem.alert_enabled == True,
        WatchlistItem.deleted == False
    ).all()
    
    for item in items:
        if not getattr(item, 'sell_alert_enabled', False):
            item.sell_alert_enabled = True
            print(f"✅ Enabled sell alerts for {item.symbol}")
    
    db.commit()
    print(f"\n✅ Enabled sell alerts for {len(items)} symbols")
finally:
    db.close()
```

### Solution 2: Relax MA Reversal Requirement (If Needed)

If MA reversal is too strict, we can make it optional for sell signals:

**Current**: Requires MA50 < EMA10 OR price < MA10w
**Proposed**: Make MA reversal optional when RSI is extremely high (> 80)

### Solution 3: Fix Volume Confirmation Logic

Ensure volume data is available and properly calculated. If volume data is missing, consider:
- Using a fallback volume calculation
- Making volume confirmation optional for sell signals (since high RSI alone is a strong signal)

### Solution 4: Fix Monitoring Endpoint 500 Error

Investigate and fix the monitoring endpoint error to ensure proper status display.

## Implementation Priority

1. **HIGH**: Check and enable `sell_alert_enabled` flags
2. **HIGH**: Fix monitoring endpoint 500 error
3. **MEDIUM**: Verify MA reversal conditions for high RSI symbols
4. **MEDIUM**: Verify volume confirmation is working
5. **LOW**: Consider relaxing MA reversal for extreme RSI (> 80)

## Testing Checklist

After implementing fixes:

- [ ] Verify `sell_alert_enabled=True` for test symbols
- [ ] Check that sell signals are generated when RSI > 70
- [ ] Verify alerts are sent to Telegram
- [ ] Confirm monitoring endpoint returns 200 (not 500)
- [ ] Test with BTC_USDT (RSI 90.33) - should trigger sell alert
- [ ] Test with LDO_USD (RSI 81.30) - should trigger sell alert
- [ ] Verify throttle logic doesn't block legitimate alerts

## Files Modified

- `backend/scripts/diagnose_sell_alerts.py` - New diagnostic script
- `SELL_ALERT_INVESTIGATION_REPORT.md` - This report

## Next Steps

1. Run diagnostic script to identify specific issues
2. Enable `sell_alert_enabled` for symbols that need sell alerts
3. Fix monitoring endpoint 500 error
4. Monitor logs to verify sell alerts are being generated and sent
5. Test with high RSI symbols (BTC_USDT, LDO_USD)




