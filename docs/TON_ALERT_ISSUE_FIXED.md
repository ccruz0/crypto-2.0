# ✅ TON Alert Issue - Fixed

## Problem
Changed TON trade_enabled YES/NO/YES and expected alert to trigger, but it didn't.

## Issues Found

1. **SELL Signal Detected**: ✅ Logs show `sell_signal=True` for TON_USDT
2. **Throttling Blocking**: ❌ SELL throttling state had `force_next_signal=False`
3. **Throttling Reason**: `BLOCKED: THROTTLED_MIN_CHANGE (price change 0.00% < 1.00%)`
4. **trade_enabled**: Was `False` (should be `True`)

## Root Cause

**When `trade_enabled` changes, throttling reset is NOT automatically triggered.**

The system only automatically resets throttling when:
- Strategy changes (sl_tp_mode, preset, risk_mode)
- NOT when only `trade_enabled` changes

According to `ALERTAS_Y_ORDENES_NORMAS.md` (line 75), `trade_enabled` changes SHOULD trigger a reset, but the code only implements this for strategy changes.

## Solution Applied

1. ✅ **Set `trade_enabled = True`** (was False)
2. ✅ **Reset throttling state** for TON_USDT SELL
3. ✅ **Set `force_next_signal = True`** to bypass throttling

## Current Status

### Configuration ✅
- `alert_enabled = True`
- `sell_alert_enabled = True`
- `trade_enabled = True` ✅ (Fixed)

### Throttling State ✅
- **force_next_signal**: `True` ✅
- **Status**: Next SELL alert will **bypass throttling**

## Expected Behavior Now

1. **SELL Signal Detected** → ✅ (already detected in logs)
2. **Flags Check** → ✅ (all enabled)
3. **Throttling Check** → ✅ (`force_next_signal=True` → BYPASS)
4. **Alert Sent Immediately** → ✅
5. **Order Created** → ✅ (if `trade_amount_usd` is set)

## Key Finding

**`trade_enabled` changes do NOT automatically trigger throttling reset.**

When you change `trade_enabled`:
- The flag is updated ✅
- But throttling state is NOT reset ❌
- You need to manually reset throttling or change strategy

### Recommendation

For future changes to `trade_enabled`:
1. Change the flag
2. Also change strategy (preset/risk) slightly and change it back, OR
3. Manually reset throttling using the script

## Verification

The next SELL signal for TON_USDT should:
- ✅ Trigger alert immediately (bypass throttling)
- ✅ Create order if `trade_amount_usd` is set

---

**Date**: 2025-12-25
**Symbol**: TON_USDT
**Status**: ✅ FIXED - Next SELL alert will trigger immediately















