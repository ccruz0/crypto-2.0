# LDO Signal Trigger Diagnosis

## Issue
LDO shows INDEX:100% and BUY signal in the UI, but the signal did not actually trigger (no alert/order created).

## Root Cause Analysis

Based on the codebase review, a signal with INDEX:100% should mean all boolean buy flags are `True`, which should trigger `buy_signal=True`. However, there are several potential reasons why it might not trigger:

### Potential Blocking Conditions

1. **Volume Check Failure** (Most Likely)
   - Location: `backend/app/services/trading_signals.py` lines 471-488
   - The volume check requires:
     - `volume > 0` AND `avg_volume > 0`
     - `volume_ratio >= min_volume_ratio` (default 0.5x, configurable)
   - If volume data is missing or ratio is below threshold, `buy_volume_ok = False`
   - This would block BUY even if INDEX shows 100%

2. **RSI Check Failure**
   - RSI must be below `rsi_buyBelow` threshold from strategy config
   - If RSI >= threshold, `buy_rsi_ok = False`

3. **MA Checks Failure**
   - Depends on strategy configuration (maChecks settings)
   - If MA50/EMA10/MA200 checks are required and fail, `buy_ma_ok = False`

4. **Buy Target Check**
   - If `buy_target` is set and price > buy_target, `buy_target_ok = False`

5. **Throttling/Alert Blocking** (After Signal Calculation)
   - Even if `buy_signal=True`, alerts/orders can be blocked by:
     - `alert_enabled = False` in database
     - Cooldown period not met
     - Price change threshold not met
     - See `backend/app/services/signal_monitor.py` for throttling logic

## Debugging Steps

### 1. Check Backend Logs

Look for these log entries when LDO is evaluated:

```bash
# Check for LDO signal evaluation logs
tail -f backend.log | grep -i "LDO"
```

Key log entries to look for:
- `[LDO_DEBUG]` - Shows all buy flags and volume data
- `[LDO_BUY_TRIGGERED]` - Confirms BUY signal was set to True
- `[LDO_BUY_NOT_TRIGGERED]` - Shows why BUY was NOT triggered (blocking reasons)
- `[DEBUG_STRATEGY_FINAL]` - Final signal state with all flags

### 2. Verify Volume Data

Check if volume data is available for LDO_USD:
- `volume` should be > 0
- `avg_volume` should be > 0
- `volume_ratio = volume / avg_volume` should be >= `min_volume_ratio`

### 3. Check Strategy Configuration

Verify LDO_USD's strategy preset configuration:
- RSI buyBelow threshold
- Volume minimum ratio (min_volume_ratio)
- MA checks configuration
- Buy target (if set)

### 4. Check Alert/Trade Settings

In the database or UI, verify:
- `alert_enabled = True` for LDO_USD
- `trade_enabled = True` (if expecting orders)
- No throttling cooldowns active

## Enhanced Logging Added

I've added enhanced logging specifically for LDO symbols that will show:
- Volume data (volume, avg_volume, volume_ratio, min_volume_ratio)
- All buy flags (rsi_ok, ma_ok, vol_ok, target_ok, price_ok)
- Whether all_buy_flags_true is True or False
- Detailed blocking reasons if BUY doesn't trigger

## Next Steps

1. **Monitor logs** - Wait for next LDO signal evaluation and check the `[LDO_DEBUG]` and `[LDO_BUY_NOT_TRIGGERED]` logs
2. **Check volume data** - Verify LDO_USD has valid volume data in MarketData table
3. **Verify strategy config** - Check trading_config.json for LDO_USD's strategy settings
4. **Compare UI vs Backend** - The UI might be calculating INDEX differently than backend

## Code Changes Made

- Added `[LDO_DEBUG]` log entry before canonical rule evaluation
- Added `[LDO_BUY_TRIGGERED]` log when BUY signal is set to True
- Added `[LDO_BUY_NOT_TRIGGERED]` warning log with blocking reasons when BUY doesn't trigger

These logs will help identify exactly why LDO is not triggering even though INDEX shows 100%.








