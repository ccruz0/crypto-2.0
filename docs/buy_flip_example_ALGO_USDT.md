# BUY → WAIT Flip Analysis: ALGO_USDT

## Purpose

This document analyzes why ALGO_USDT briefly shows BUY in the UI and then flips back to WAIT, even though the UI values appear very similar (due to rounding).

## How to Use This Document

1. Run the debug script to capture recent strategy logs:
   ```bash
   python backend/scripts/debug_strategy.py ALGO_USDT --last 20 --compare
   ```

2. Or use docker logs directly:
   ```bash
   cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh --tail 10000 | \
     grep DEBUG_STRATEGY_FINAL | grep ALGO_USDT | tail -20
   ```

3. Find two consecutive entries where:
   - First entry: `decision=BUY` with all `buy_*` flags = True
   - Second entry: `decision=WAIT` with at least one `buy_*` flag = False

4. Document the flip below using the template.

## Example Flip Analysis

### Flip #1 - [DATE/TIME]

**Entry #N (BUY):**
```
Decision: BUY | Buy Signal: True
Raw Values (unrounded):
  price:        0.14280500
  rsi:          35.0000
  buy_target:   0.14281000
  price - target: -0.00000500 ✓
  volume_ratio: 1.200000
  ma50:         0.14000000
  ema10:        0.14100000
  ma200:        0.13500000

Buy Flags:
  buy_ma_ok          = True  ✓
  buy_price_ok       = True  ✓
  buy_rsi_ok         = True  ✓
  buy_target_ok      = True  ✓
  buy_volume_ok      = True  ✓
```

**Entry #N+1 (WAIT):**
```
Decision: WAIT | Buy Signal: False
Raw Values (unrounded):
  price:        0.14282100
  rsi:          35.0000
  buy_target:   0.14281000
  price - target: +0.00001100 ✗
  volume_ratio: 1.200000
  ma50:         0.14000000
  ema10:        0.14100000
  ma200:        0.13500000

Buy Flags:
  buy_ma_ok          = True  ✓
  buy_price_ok       = True  ✓
  buy_rsi_ok         = True  ✓
  buy_target_ok      = False ✗  ← FLIPPED
  buy_volume_ok      = True  ✓
```

**Analysis:**
- **Flag that flipped:** `buy_target_ok`: True → False
- **Root cause:** Price increased from `0.14280500` to `0.14282100` (change: `+0.00001600`)
- **Threshold:** `buy_target = 0.14281000`
- **Condition:** `price <= buy_target` must be True for BUY
- **Why UI looks similar:** Both prices round to `0.1428` in the UI (4 decimal places), but the actual difference (`0.000016`) is enough to cross the threshold
- **Time between entries:** ~30 seconds (monitor cycle)

**Recommendation:**
Consider adding hysteresis to `buy_target_ok`:
- **Enter BUY:** `price <= buy_target` (current)
- **Exit BUY:** `price > buy_target + tolerance` (e.g., `buy_target * 1.001` or `buy_target + 0.0001`)

This prevents rapid BUY↔WAIT flips when price oscillates around the threshold.

---

## Common Flip Patterns

### Pattern 1: buy_target_ok Flip
**Symptom:** Price oscillates around `buy_target` threshold
**Example:** Price = 0.142805 vs buy_target = 0.142810 (difference: 0.000005)
**Solution:** Add hysteresis (tolerance) to exit condition

### Pattern 2: buy_rsi_ok Flip
**Symptom:** RSI oscillates around `rsi_buy_below` threshold
**Example:** RSI = 39.9 vs threshold = 40.0
**Solution:** Add hysteresis (e.g., enter at RSI < 40, exit at RSI > 41)

### Pattern 3: buy_volume_ok Flip
**Symptom:** Volume ratio oscillates around `min_volume_ratio` threshold
**Example:** volume_ratio = 0.499 vs min_volume_ratio = 0.5
**Solution:** Add hysteresis (e.g., enter at >= 0.5, exit at < 0.48)

### Pattern 4: buy_ma_ok Flip
**Symptom:** Price/MA relationship changes slightly
**Example:** Price vs MA50/EMA10 alignment changes
**Solution:** Add tolerance to MA checks

---

## Hysteresis Design Notes

Hysteresis prevents rapid state flips by using different thresholds for entering vs exiting a state:

```
Enter BUY:  condition must be True
Exit BUY:   condition must be False AND exceed tolerance

Example for buy_target_ok:
- Enter: price <= buy_target
- Exit:  price > buy_target * (1 + tolerance_pct)
```

**Tolerance values to consider:**
- `buy_target`: 0.1% - 0.5% above target
- `rsi`: 1-2 points above threshold
- `volume_ratio`: 0.02-0.05 below threshold
- `ma_ok`: Small percentage tolerance

---

## Next Steps

1. Document actual flips using the template above
2. Identify the most common flip pattern
3. Design hysteresis thresholds
4. Implement hysteresis in `calculate_trading_signals()` (if approved)
5. Test with real data to verify reduced flip frequency

