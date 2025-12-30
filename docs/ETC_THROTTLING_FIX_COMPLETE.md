# ✅ ETC Alert Blocking Issue - Fixed

## Problem Identified

**Issue**: SELL alerts for ETC_USDT were being sent but then **blocked by throttling**.

## Root Cause

A **stale throttling state record** was blocking alerts:

- **Last Alert Attempt**: 2025-12-22 17:07:30 UTC (3 days ago)
- **Status**: ❌ BLOCKED
- **Reason**: `THROTTLED_MIN_TIME (elapsed 2.83m < 5.00m)`
- **Last Price**: $12.4450

### Why It Was Blocking

1. **Stale Record**: The throttling state had a record from 3 days ago
2. **Old Configuration**: The reason mentions "5.00m" (5 minutes), suggesting an old throttling rule
3. **Current System**: Uses 60 seconds (1 minute) minimum, but the stale record was still being checked
4. **Blocked State**: Even though 58+ hours had passed, the stale "BLOCKED" state was preventing new alerts

## Solution Applied

### ✅ Reset Throttling State

Executed reset script on AWS:
```bash
python3 /app/scripts/reset_etc_throttling.py
```

**Result**:
- ✅ Deleted stale throttling record
- ✅ Next SELL signal will trigger immediately
- ✅ No time gate or price gate will apply to the first alert
- ✅ After first alert, normal throttling (60s + 1% price change) will apply

## Current Status

### Configuration ✅
- `alert_enabled = True`
- `sell_alert_enabled = True`
- `trade_enabled = True`
- `trade_amount_usd = $10.0`

### Throttling State ✅
- **Status**: RESET
- **Next Alert**: Will be allowed immediately
- **Throttling**: Will apply normally after first alert

## Expected Behavior Now

1. **SELL Signal Detected** → System checks flags ✅
2. **Flags OK** → System checks throttling ✅ (no stale record)
3. **Throttling OK** → **SELL Alert Sent** ✅
4. **If `trade_enabled=True`** → **SELL Order Created** ✅

## Monitoring

### Check if Alerts Are Working

```bash
# On AWS
docker compose logs -f backend-aws | grep -i "ETC.*SELL"
```

### Check Throttling State

```sql
SELECT symbol, side, last_price, last_time, emit_reason 
FROM signal_throttle_states 
WHERE symbol = 'ETC_USDT' AND side = 'SELL';
```

### Check Current Signals

```bash
docker compose exec -T backend-aws curl "http://localhost:8000/api/signals?exchange=CRYPTO_COM&symbol=ETC_USDT"
```

## Prevention

To prevent this issue in the future:

1. **Monitor Throttling State**: Regularly check for stale records
2. **Clean Up Old Records**: Remove throttling records older than 24 hours if they're in "BLOCKED" state
3. **Reset on Configuration Changes**: When changing throttling rules, reset affected records

## Scripts Created

- ✅ `backend/scripts/reset_etc_throttling.py` - Reset throttling for ETC_USDT SELL
- ✅ `backend/scripts/check_etc_sell_alert.py` - Diagnostic script
- ✅ `backend/scripts/fix_etc_sell_alerts.py` - Fix configuration (not needed - was already correct)

## Summary

**Problem**: Stale throttling state blocking alerts
**Solution**: Reset throttling state
**Status**: ✅ FIXED - Next SELL signal will trigger immediately

---

**Date Fixed**: 2025-12-25
**Issue**: ETC_USDT SELL alerts blocked by stale throttling state
**Resolution**: Throttling state reset successfully










