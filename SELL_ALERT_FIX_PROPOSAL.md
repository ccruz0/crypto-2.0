# Sell Alert Fix Proposal

## Problem Statement

Sell alerts are not being generated despite high RSI values (BTC_USDT: 90.33, LDO_USD: 81.30) that should trigger sell signals.

## Root Cause Analysis

After investigation, the following issues were identified:

### 1. **Primary Issue: `sell_alert_enabled` Flag Disabled**

The `sell_alert_enabled` flag is **separate** from `buy_alert_enabled` and defaults to `False`. This flag must be explicitly enabled for each symbol that should receive sell alerts.

**Evidence**: The code in `signal_monitor.py` line 2155 checks:
```python
if sell_signal and watchlist_item.alert_enabled and sell_alert_enabled:
```

If `sell_alert_enabled=False`, the alert will be skipped even if `sell_signal=True`.

### 2. **Secondary Issues**

- **MA Reversal Requirement**: Sell signals require MA50 < EMA10 (trend reversal). If MA50 >= EMA10, sell signal won't be generated.
- **Volume Confirmation**: Sell signals require `volume_ratio >= min_volume_ratio` (default 0.5x). Missing or low volume blocks sell signals.
- **Monitoring Endpoint 500**: The dashboard shows "Monitoring 500" which may indicate backend issues.

## Proposed Solution

### Phase 1: Quick Fix - Enable Sell Alerts (IMMEDIATE)

**Action**: Enable `sell_alert_enabled=True` for all symbols with `alert_enabled=True`.

**Script**: `backend/scripts/enable_sell_alerts.py`

**Command**:
```bash
cd backend
python scripts/enable_sell_alerts.py
```

**Expected Result**: All symbols with `alert_enabled=True` will have `sell_alert_enabled=True`, allowing sell alerts to be sent when conditions are met.

### Phase 2: Verify Signal Conditions (VERIFICATION)

After enabling sell alerts, verify that sell signals are being generated:

1. **Check RSI Values**: Should be > 70 (✅ Already met for BTC_USDT and LDO_USD)
2. **Check MA Reversal**: Verify MA50 < EMA10 for symbols with high RSI
3. **Check Volume**: Verify volume_ratio >= 0.5x
4. **Check Throttle Status**: Ensure alerts aren't being throttled

**Diagnostic Script**: `backend/scripts/diagnose_sell_alerts.py`

**Command**:
```bash
cd backend
python scripts/diagnose_sell_alerts.py
```

### Phase 3: Fix Monitoring Endpoint (IF NEEDED)

If the monitoring endpoint continues to show 500 errors:

1. Check backend logs for exceptions in `/api/monitoring/summary`
2. Verify database connectivity
3. Check service status

**Investigation**:
```bash
# Check backend logs
tail -f backend/logs/app.log | grep -i "monitoring\|500\|error"

# Test endpoint directly
curl -v https://dashboard.hilovivo.com/api/monitoring/summary
```

### Phase 4: Optional Enhancements (FUTURE)

If sell alerts are still not triggering after Phase 1-2, consider:

1. **Relax MA Reversal for Extreme RSI**: When RSI > 80, make MA reversal optional
2. **Volume Fallback**: Use fallback volume calculation if primary source fails
3. **Alert Threshold Adjustment**: Lower RSI sell threshold for specific strategies

## Implementation Steps

### Step 1: Enable Sell Alerts
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python scripts/enable_sell_alerts.py
```

### Step 2: Verify Configuration
```bash
python scripts/diagnose_sell_alerts.py
```

### Step 3: Monitor Backend Logs
```bash
# Watch for sell alert activity
tail -f logs/app.log | grep -i "sell.*alert\|sell.*signal"
```

### Step 4: Test with High RSI Symbols
- BTC_USDT (RSI 90.33) - Should trigger sell alert
- LDO_USD (RSI 81.30) - Should trigger sell alert

### Step 5: Verify Telegram Alerts
Check Telegram for sell alert messages.

## Expected Outcomes

After implementing Phase 1:

1. ✅ `sell_alert_enabled=True` for all symbols with `alert_enabled=True`
2. ✅ Sell alerts will be sent when:
   - RSI > 70 (sell threshold)
   - MA reversal condition met (MA50 < EMA10 OR price < MA10w)
   - Volume confirmation passed (volume_ratio >= 0.5x)
   - Throttle check passes
3. ✅ Monitoring endpoint should show sell alerts in the dashboard

## Rollback Plan

If issues occur after enabling sell alerts:

1. **Disable for specific symbols**:
```sql
UPDATE watchlist_items 
SET sell_alert_enabled = FALSE 
WHERE symbol = 'SYMBOL_NAME';
```

2. **Disable for all symbols**:
```sql
UPDATE watchlist_items 
SET sell_alert_enabled = FALSE 
WHERE alert_enabled = TRUE;
```

## Testing Checklist

- [ ] Run `enable_sell_alerts.py` script
- [ ] Verify `sell_alert_enabled=True` in database
- [ ] Run `diagnose_sell_alerts.py` to check signal conditions
- [ ] Monitor backend logs for sell alert activity
- [ ] Test with BTC_USDT (high RSI)
- [ ] Test with LDO_USD (high RSI)
- [ ] Verify Telegram receives sell alerts
- [ ] Check monitoring dashboard shows sell alerts
- [ ] Verify throttle logic works correctly

## Files Created/Modified

1. **New Files**:
   - `backend/scripts/diagnose_sell_alerts.py` - Diagnostic tool
   - `backend/scripts/enable_sell_alerts.py` - Enable sell alerts script
   - `SELL_ALERT_INVESTIGATION_REPORT.md` - Investigation report
   - `SELL_ALERT_FIX_PROPOSAL.md` - This document

2. **No Code Changes Required** (yet):
   - The existing code logic is correct
   - The issue is configuration (flags not enabled)

## Success Criteria

✅ Sell alerts are generated when:
- RSI > 70
- MA reversal condition met
- Volume confirmation passed
- `sell_alert_enabled=True` ✅ (after fix)
- `alert_enabled=True` ✅
- Throttle check passes

✅ Monitoring dashboard shows:
- Sell alerts in the alerts list
- No 500 errors
- Correct status for all symbols

✅ Telegram receives:
- Sell alert messages for symbols meeting conditions

## Next Steps

1. **IMMEDIATE**: Run `enable_sell_alerts.py` to enable sell alerts
2. **VERIFY**: Run `diagnose_sell_alerts.py` to check signal conditions
3. **MONITOR**: Watch backend logs for sell alert activity
4. **TEST**: Verify alerts are sent for high RSI symbols
5. **FIX**: Address monitoring endpoint 500 error if it persists




