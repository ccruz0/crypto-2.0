# 📋 ETC Alert and Order Issue - Resolution Summary

## Problem Statement
ETC (Ethereum Classic) is not creating alerts and sell orders when SELL signals are detected.

## Root Cause Analysis

### Primary Issue
The `sell_alert_enabled` flag defaults to `False` and must be explicitly enabled. This is separate from the master `alert_enabled` flag, allowing independent control of BUY and SELL alerts.

### Required Configuration for SELL Alerts
1. ✅ `alert_enabled = True` (Master switch)
2. ✅ `sell_alert_enabled = True` (SELL-specific flag - **CRITICAL**)
3. ✅ `sell_signal = True` (Signal from indicators)

### Required Configuration for SELL Orders
1. ✅ All alert flags above
2. ✅ `trade_enabled = True` (Enables order creation)
3. ✅ `trade_amount_usd > 0` (Must be configured)

### Additional Blocking Factors
- **Throttling**: 60-second minimum between alerts (time gate)
- **Price Gate**: Minimum price change % required (from strategy)
- **Missing Indicators**: MA50 and EMA10 must be available for orders

## Solution Implemented

### Tools Created

#### 1. Diagnostic Script
**File**: `backend/scripts/check_etc_sell_alert.py`
- Checks all configuration flags
- Verifies throttling state
- Identifies specific issues
- Provides SQL fix commands

**Usage**:
```bash
python3 backend/scripts/check_etc_sell_alert.py
```

#### 2. Automatic Fix Script
**File**: `backend/scripts/fix_etc_sell_alerts.py`
- Automatically enables all required flags
- Sets trade_amount_usd if missing
- Shows what was changed

**Usage**:
```bash
python3 backend/scripts/fix_etc_sell_alerts.py
```

#### 3. API Check Script
**File**: `backend/scripts/check_etc_via_api.sh`
- Quick configuration check via API
- No database access required
- Shows current state

**Usage**:
```bash
./backend/scripts/check_etc_via_api.sh
```

### Documentation Created

1. **ETC_SELL_ALERT_TROUBLESHOOTING.md** - Comprehensive troubleshooting guide
2. **ETC_QUICK_FIX.md** - Quick reference for common fixes
3. **ETC_ISSUE_RESOLUTION_SUMMARY.md** - This document

## Resolution Steps

### Step 1: Diagnose the Issue
```bash
# Option A: Via API (if backend is running)
./backend/scripts/check_etc_via_api.sh

# Option B: Full diagnostic (requires database)
python3 backend/scripts/check_etc_sell_alert.py
```

### Step 2: Apply the Fix
```bash
# Automatic fix (recommended)
python3 backend/scripts/fix_etc_sell_alerts.py
```

**OR** via SQL:
```sql
UPDATE watchlist_items 
SET 
    alert_enabled = TRUE,
    sell_alert_enabled = TRUE,
    trade_enabled = TRUE,
    trade_amount_usd = COALESCE(NULLIF(trade_amount_usd, 0), 10.0)
WHERE symbol = 'ETC_USDT' AND is_deleted = FALSE;
```

**OR** via Dashboard UI:
1. Go to Dashboard
2. Find `ETC_USDT`
3. Enable: Alerts, SELL Alerts, Trade
4. Set Amount USD

### Step 3: Verify the Fix
```bash
# Check configuration
./backend/scripts/check_etc_via_api.sh

# Check if signals are being detected
curl "http://localhost:8000/api/signals?exchange=CRYPTO_COM&symbol=ETC_USDT"
```

### Step 4: Monitor Results
- Check backend logs for SELL signal detection
- Verify alerts are being sent
- Confirm orders are being created (if trade_enabled=True)

## Expected Behavior After Fix

### Alert Flow
1. **Signal Detection** → SELL signal detected (RSI > 70, etc.)
2. **Flag Check** → `alert_enabled=True` AND `sell_alert_enabled=True` ✅
3. **Throttling Check** → Time gate (60s) and price gate passed ✅
4. **Alert Sent** → Telegram notification sent ✅

### Order Flow (if trade_enabled=True)
1. **After Alert** → System checks `trade_enabled` and `trade_amount_usd`
2. **Indicator Check** → MA50 and EMA10 available ✅
3. **Order Created** → SELL order placed automatically ✅

## Troubleshooting After Fix

### Issue: Still no alerts
**Check:**
- [ ] `alert_enabled = TRUE` in database
- [ ] `sell_alert_enabled = TRUE` in database
- [ ] SELL signals are being detected (check logs/API)
- [ ] Throttling is not blocking (check `signal_throttle_states`)

### Issue: Alerts sent but no orders
**Check:**
- [ ] `trade_enabled = TRUE` in database
- [ ] `trade_amount_usd > 0` in database
- [ ] MA50 and EMA10 are available (check logs)
- [ ] No order creation blocks (max positions, cooldown, etc.)

### Issue: Throttling blocking
**Solution:**
```sql
-- Reset throttling for ETC_USDT SELL
DELETE FROM signal_throttle_states 
WHERE symbol = 'ETC_USDT' AND side = 'SELL';
```

**Note**: This allows immediate alerts but should only be done if you understand the implications.

## Prevention

To prevent this issue for other symbols:

1. **When adding new symbols**: Ensure both `alert_enabled` and `sell_alert_enabled` are set
2. **Bulk enable**: Use scripts to enable SELL alerts for all symbols:
   ```sql
   UPDATE watchlist_items 
   SET sell_alert_enabled = TRUE 
   WHERE alert_enabled = TRUE AND sell_alert_enabled = FALSE;
   ```
3. **Dashboard UI**: Always check both BUY and SELL alert toggles when configuring symbols

## Related Files

### Scripts
- `backend/scripts/check_etc_sell_alert.py` - Diagnostic
- `backend/scripts/fix_etc_sell_alerts.py` - Automatic fix
- `backend/scripts/check_etc_via_api.sh` - API check

### Documentation
- `docs/ETC_SELL_ALERT_TROUBLESHOOTING.md` - Detailed guide
- `docs/ETC_QUICK_FIX.md` - Quick reference
- `docs/ALERTAS_Y_ORDENES_NORMAS.md` - Complete alert/order rules

### Code References
- `backend/app/services/signal_monitor.py` - Signal monitoring logic
- `backend/app/services/signal_throttle.py` - Throttling logic
- `backend/app/models/watchlist.py` - Watchlist model

## Testing Checklist

After applying the fix, verify:

- [ ] Configuration flags are enabled
- [ ] SELL signals are detected (check API/logs)
- [ ] Alerts are sent when conditions are met
- [ ] Orders are created (if trade_enabled=True)
- [ ] Throttling works correctly (60s cooldown)
- [ ] Price gate works correctly (minimum % change)

## Notes

- The `sell_alert_enabled` flag was introduced to allow independent control of BUY and SELL alerts
- This flag defaults to `False` for safety (prevents accidental SELL alerts)
- The same pattern applies to `buy_alert_enabled` for BUY alerts
- Both flags require `alert_enabled=True` (master switch) to work

## Status

✅ **Tools Created**: Diagnostic and fix scripts ready
✅ **Documentation**: Complete troubleshooting guides available
⏳ **Fix Pending**: User needs to run fix script or apply SQL/dashboard changes
⏳ **Verification Pending**: After fix is applied, verify alerts/orders are working

---

**Last Updated**: 2025-12-25
**Issue**: ETC not creating alerts and sell orders
**Status**: Tools and documentation ready, fix pending user action











