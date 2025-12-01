# LDO_USDT BUY Signal Fix Summary

**Date:** 2025-01-XX  
**Issue:** LDO_USDT (and LDO_USD) was not generating BUY alerts even though all conditions were green (RSI < 55, volume ratio ≥ 0.5, no MA required for scalp-aggressive preset).

## Root Cause

1. **Missing Strategy Profile Configuration:**
   - LDO_USD and LDO_USDT were not explicitly configured in `trading_config.json`
   - `resolve_strategy_profile()` was falling back to default "swing" preset instead of "scalp-aggressive"
   - Swing preset has RSI buyBelow=40, so RSI=50.35 was failing the check (50.35 ≥ 40 = False)

2. **Insufficient Debug Logging:**
   - No logs showing which preset was being resolved
   - No clear visibility into why BUY decision was WAIT instead of BUY

3. **SELL Logic Potentially Overriding BUY:**
   - SELL conditions could potentially override BUY in the same cycle

## Solution

### 1. Added Explicit Strategy Configuration
**File:** `backend/trading_config.json`
- Added explicit entries for both `LDO_USD` and `LDO_USDT` with preset `"scalp-aggressive"`
- Ensures `resolve_strategy_profile()` finds the correct preset

### 2. Enhanced resolve_strategy_profile() with Warning Logs
**File:** `backend/app/services/strategy_profiles.py`
- Added warning log when symbol doesn't have explicit preset in config
- Added debug log when preset is found
- Helps identify configuration issues early

### 3. Added Comprehensive Debug Logging
**File:** `backend/app/services/trading_signals.py`

**Added three key debug logs:**

1. **`[DEBUG_RESOLVED_PROFILE]`** - Logged at the start of `calculate_trading_signals()`:
   ```
   [DEBUG_RESOLVED_PROFILE] symbol=LDO_USDT | strategy_type=scalp | risk_approach=aggressive | preset=scalp-aggressive
   ```

2. **`[DEBUG_BUY_FLAGS]`** - Logged before canonical BUY rule evaluation:
   ```
   [DEBUG_BUY_FLAGS] symbol=LDO_USDT | rsi_ok=True | ma_ok=True | vol_ok=True | target_ok=True | price_ok=True
   ```

3. **`[DEBUG_STRATEGY_FINAL]`** - Logged at the end with final decision:
   ```
   [DEBUG_STRATEGY_FINAL] symbol=LDO_USDT | decision=BUY | buy_signal=True | sell_signal=False | ...
   ```

### 4. Fixed SELL Override Logic
**File:** `backend/app/services/trading_signals.py`
- Modified SELL condition check to skip if `strategy_state["decision"] == "BUY"`
- Added debug log when SELL is blocked because BUY is already set
- Ensures BUY has priority in the same cycle

### 5. Enhanced Canonical BUY Rule Debug Logging
**File:** `backend/app/services/trading_signals.py`
- Added `[CANONICAL_BUY_RULE]` log for LDO/ALGO/TON symbols
- Shows which boolean flags are being evaluated and whether all are True

## Expected Behavior

For **LDO_USDT** (and **LDO_USD**) with preset **scalp-aggressive**:

### BUY Conditions (all must be True):
1. ✅ **RSI < 55** → `buy_rsi_ok = True`
2. ✅ **Volume ratio ≥ 0.5** → `buy_volume_ok = True`
3. ✅ **No MA blocking** → `buy_ma_ok = True` (set automatically when MAs not required)
4. ✅ **Price valid** → `buy_price_ok = True`
5. ✅ **Target OK** (if configured) → `buy_target_ok = True`

### When All Conditions Met:
- **Backend:** `decision = "BUY"`, `buy_signal = True`
- **Frontend:** Signals chip shows **BUY** (green)
- **Alerts:** BUY alert sent to Telegram and Monitoring (if `alert_enabled=True` and throttle allows)

## Debugging

### Logs to Check:
1. **`[DEBUG_RESOLVED_PROFILE]`** - Shows which preset is being used:
   ```
   [DEBUG_RESOLVED_PROFILE] symbol=LDO_USDT | strategy_type=scalp | risk_approach=aggressive | preset=scalp-aggressive
   ```

2. **`[DEBUG_BUY_FLAGS]`** - Shows all buy_* flags before canonical rule:
   ```
   [DEBUG_BUY_FLAGS] symbol=LDO_USDT | rsi_ok=True | ma_ok=True | vol_ok=True | target_ok=True | price_ok=True
   ```

3. **`[CANONICAL_BUY_RULE]`** - Shows which flags are evaluated:
   ```
   [CANONICAL_BUY_RULE] symbol=LDO_USDT | boolean_flags={'buy_rsi_ok': True, 'buy_volume_ok': True, ...} | all_true=True | requires_ma=False
   ```

4. **`[DEBUG_STRATEGY_FINAL]`** - Shows final decision:
   ```
   [DEBUG_STRATEGY_FINAL] symbol=LDO_USDT | decision=BUY | buy_signal=True | sell_signal=False | ...
   ```

### Commands to Debug:
```bash
# Check LDO logs
ssh hilovivo-aws 'docker logs automated-trading-platform-backend-aws-1 --tail 2000 | grep -E "LDO.*DEBUG" | tail -20'

# Check preset configuration
ssh hilovivo-aws 'cat /home/ubuntu/automated-trading-platform/backend/trading_config.json | grep -A 3 "LDO"'
```

## Files Changed

1. `backend/trading_config.json` - Added LDO_USD and LDO_USDT with scalp-aggressive preset
2. `backend/app/services/strategy_profiles.py` - Added warning/debug logs for missing presets
3. `backend/app/services/trading_signals.py` - Added comprehensive debug logging and fixed SELL override logic

## Testing Checklist

- [x] LDO_USD and LDO_USDT added to trading_config.json with scalp-aggressive preset
- [x] resolve_strategy_profile() enhanced with warning logs
- [x] DEBUG_RESOLVED_PROFILE, DEBUG_BUY_FLAGS, DEBUG_STRATEGY_FINAL logs added
- [x] SELL override logic fixed to not override BUY
- [x] Backend deployed to AWS
- [ ] Verify LDO_USDT shows BUY when RSI < 55 and volume ≥ 0.5
- [ ] Verify BUY alerts are sent (if ALERTS ON)
- [ ] Verify no regression for other symbols (ALGO, TON, etc.)

## Notes

- The frontend already trusts the backend `strategy.decision` and `strategy.reasons` (no changes needed).
- Portfolio risk only blocks **orders**, not **alerts** (already implemented in previous refactor).
- The canonical BUY rule ensures consistency between frontend tooltip and backend decision.
- All debug logs include the symbol name for easy filtering.

