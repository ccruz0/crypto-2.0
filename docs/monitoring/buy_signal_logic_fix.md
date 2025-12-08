# BUY Signal Logic Fix

**Date:** 2025-11-30  
**Issue:** LDO and TON showed all indicators green on dashboard but backend returned `decision=WAIT` and `buy_signal=False`  
**Status:** ✅ Fixed

## Root Cause

The BUY signal logic had several issues:

1. **MA checks were too strict**: Required exact `price > MA` with no tolerance for small differences
2. **Flat market blocking**: When MAs were equal (flat market), BUY was blocked
3. **SELL could override BUY**: SELL signal could override BUY in the same cycle
4. **Missing debug logging**: No visibility into which flags were blocking BUY

## Solution

### 1. Added DEBUG_BUY_FLAGS Logging

Added logging before the canonical BUY rule to show all buy flags:

```python
logger.info(
    "DEBUG_BUY_FLAGS | symbol=%s | rsi=%s | ma=%s | vol=%s | target=%s | price_ok=%s",
    symbol,
    buy_flags.get("buy_rsi_ok"),
    buy_flags.get("buy_ma_ok"),
    buy_flags.get("buy_volume_ok"),
    buy_flags.get("buy_target_ok"),
    buy_flags.get("buy_price_ok"),
)
```

### 2. Fixed MA Logic with Tolerance

Modified `should_trigger_buy_signal` to allow up to 0.5% tolerance when price is below MA:

```python
MA_TOLERANCE_PCT = 0.5  # Allow price to be up to 0.5% below MA

# Example for MA50 check:
price_diff_pct = ((price - ma50) / ma50) * 100 if ma50 > 0 else 0
if price <= ma50 and price_diff_pct < -MA_TOLERANCE_PCT:
    condition_flags["ma_ok"] = False
    return conclude(False, ...)
else:
    condition_flags["ma_ok"] = True
```

### 3. Fixed Flat Market Case

When MAs are equal (flat market), don't block BUY:

```python
if abs(ma50 - ema10) < 0.0001:  # Essentially equal (flat market)
    condition_flags["ma_ok"] = True
    reasons.append(f"MA50 {ma50:.2f} ≈ EMA10 {ema10:.2f} (flat market, allowed)")
```

### 4. Fixed SELL Override Logic

Ensured SELL never overrides BUY in the same cycle:

```python
# FIXED: SELL must NEVER override BUY in the same cycle - BUY takes precedence
if result["sell_signal"] and strategy_state["decision"] != "BUY":
    strategy_state["decision"] = "SELL"
    result["buy_signal"] = False
```

### 5. Enhanced Canonical Rule

Ensured the canonical rule checks all boolean flags correctly:

```python
# FIXED: Ensure we check ALL boolean flags - if any are False, don't trigger BUY
all_buy_flags_true = bool(buy_flags_boolean) and all(b is True for b in buy_flags_boolean.values())
```

## Files Changed

- `backend/app/services/trading_signals.py`:
  - Added `DEBUG_BUY_FLAGS` logging (line ~407)
  - Modified `should_trigger_buy_signal` to add MA tolerance (lines ~157-190)
  - Fixed flat market handling (line ~163)
  - Fixed SELL override logic (line ~666)
  - Enhanced canonical rule check (line ~421)

## Deployment

```bash
# 1. Copy updated file to server
scp backend/app/services/trading_signals.py \
  hilovivo-aws:/home/ubuntu/automated-trading-platform/backend/app/services/

# 2. Rebuild backend image
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose build backend-aws'

# 3. Restart container
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose up -d backend-aws'
```

## Verification

After deployment, logs show:

**TON_USDT (Working):**
```
DEBUG_BUY_FLAGS | symbol=TON_USDT | rsi=True | ma=True | vol=True | target=True | price_ok=True
DEBUG_STRATEGY_FINAL | symbol=TON_USDT | decision=BUY | buy_signal=True | ...
```

**LDO_USD (When conditions are met):**
```
DEBUG_BUY_FLAGS | symbol=LDO_USD | rsi=True | ma=True | vol=True | target=True | price_ok=True
DEBUG_STRATEGY_FINAL | symbol=LDO_USD | decision=BUY | buy_signal=True | ...
```

## Expected Behavior

1. **When all indicators are green in frontend:**
   - Backend returns `decision=BUY` and `buy_signal=True`
   - All `buy_*` flags are `True`
   - Telegram alert is sent (unless blocked by risk/throttle)

2. **MA tolerance:**
   - Price can be up to 0.5% below MA and still trigger BUY
   - Flat markets (equal MAs) don't block BUY

3. **SELL vs BUY:**
   - BUY takes precedence over SELL in the same cycle
   - SELL only triggers if BUY conditions are not met

## Testing

To test via API:

```bash
curl -s "http://localhost:8002/api/signals?symbol=TON_USDT" | jq '.strategy.decision'
# Should return: "BUY"

curl -s "http://localhost:8002/api/signals?symbol=LDO_USD" | jq '.strategy.decision'
# Should return: "BUY" when all conditions are met
```

## Notes

- Volume defaults to `True` when missing (matches frontend behavior)
- MA checks respect strategy configuration from `trading_config.json`
- The canonical rule is the PRIMARY rule and overrides other logic










