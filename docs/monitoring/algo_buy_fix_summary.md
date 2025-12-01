# ALGO_USDT BUY Signal Fix - Scalp-Aggressive Preset

**Date:** 2025-01-XX  
**Issue:** ALGO_USDT with preset **scalp-agresiva** (scalp-aggressive) showed `WAIT` in Signals column even when all BUY criteria were green (RSI < 55, volume ratio ≥ 0.5, no MA required).

## Root Cause

1. **Preset Configuration Mismatch:**
   - ALGO_USDT was configured with `swing-aggressive` preset, which requires all MAs (EMA10, MA50, MA200).
   - User wanted `scalp-aggressive` preset, which only requires EMA10 (or no MAs for BUY).

2. **MA Check Logic Blocking BUY:**
   - The canonical BUY rule was checking `buy_ma_ok` even for strategies that don't require MAs.
   - When `buy_ma_ok` was `None` (not evaluated) or `False` (MA check failed), it blocked the BUY decision.

## Solution

### 1. Updated ALGO_USDT Preset
**File:** `backend/trading_config.json`
- Changed ALGO_USDT preset from `swing-aggressive` to `scalp-aggressive`.

**Scalp-Aggressive Configuration:**
- RSI buyBelow: **55**
- Volume minRatio: **0.5**
- MA checks: `{ema10: true, ma50: false, ma200: false}` (only EMA10 required, but not blocking for BUY if missing)

### 2. Fixed MA Check Logic
**File:** `backend/app/services/trading_signals.py`

**In `calculate_trading_signals` function:**
- Added logic to check if strategy requires MAs from config:
  ```python
  ma_checks = strategy_rules.get("maChecks", {})
  requires_ma = ma_checks.get("ema10", False) or ma_checks.get("ma50", False) or ma_checks.get("ma200", False)
  
  if not requires_ma:
      # Strategy doesn't require MAs - set to True so it doesn't block BUY
      strategy_state["reasons"]["buy_ma_ok"] = True
  else:
      # Strategy requires MAs - use the value from should_trigger_buy_signal
      strategy_state["reasons"]["buy_ma_ok"] = buy_ma_ok_from_decision
  ```

**In `should_trigger_buy_signal` function:**
- When no MA checks are configured (all `maChecks` are `False`), set `ma_ok = True`:
  ```python
  if condition_flags["ma_ok"] is None:
      # No MA checks were configured - set to True (not blocking)
      condition_flags["ma_ok"] = True
      reasons.append("No MA checks required (maChecks all False)")
  ```

### 3. Canonical BUY Rule (Already Implemented)
The canonical rule in `calculate_trading_signals` only checks **boolean flags** (excludes `None`):
- Collects all `buy_*` flags that are `bool` (not `None`).
- If all boolean flags are `True` → `decision = "BUY"` and `buy_signal = True`.
- This ensures that strategies without MA requirements only check RSI, volume, target, and price.

## Expected Behavior

For **ALGO_USDT** with preset **scalp-aggressive**:

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
1. **`DEBUG_BUY_FLAGS`** - Shows all buy_* flags before canonical rule:
   ```
   DEBUG_BUY_FLAGS | symbol=ALGO_USDT | rsi=True | ma=True | vol=True | target=True | price_ok=True
   ```

2. **`DEBUG_STRATEGY_FINAL`** - Shows final decision and buy_signal:
   ```
   [DEBUG_STRATEGY_FINAL] symbol=ALGO_USDT decision=BUY buy=True reasons={...}
   ```

3. **`[VOLUME_CHECK]`** - Shows volume ratio calculation (for ALGO_USDT):
   ```
   [VOLUME_CHECK] symbol=ALGO_USDT volume_ratio=0.7500 min_volume_ratio=0.5000 volume_ok=True
   ```

### Commands to Debug:
```bash
# Check ALGO_USDT logs
ssh hilovivo-aws 'docker logs automated-trading-platform-backend-aws-1 --tail 2000 | grep -E "ALGO_USDT.*DEBUG_BUY_FLAGS|ALGO_USDT.*DEBUG_STRATEGY_FINAL" | tail -10'

# Check preset configuration
ssh hilovivo-aws 'cat /home/ubuntu/automated-trading-platform/backend/trading_config.json | grep -A 5 "ALGO_USDT"'
```

## Testing Checklist

- [x] ALGO_USDT preset changed to `scalp-aggressive`
- [x] MA check logic fixed for strategies without MA requirements
- [x] Backend deployed to AWS
- [ ] Verify ALGO_USDT shows BUY when RSI < 55 and volume ≥ 0.5
- [ ] Verify BUY alerts are sent (if ALERTS ON)
- [ ] Verify no regression for other symbols (TON, LDO, etc.)

## Files Changed

1. `backend/trading_config.json` - Updated ALGO_USDT preset
2. `backend/app/services/trading_signals.py` - Fixed MA check logic for strategies without MA requirements

## Notes

- The frontend already trusts the backend `strategy.decision` and `strategy.reasons` (no changes needed).
- Portfolio risk only blocks **orders**, not **alerts** (already implemented in previous refactor).
- The canonical BUY rule ensures consistency between frontend tooltip and backend decision.

